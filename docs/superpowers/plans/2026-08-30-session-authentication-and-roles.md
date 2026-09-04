# Session-Based Operator Authentication and Roles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the SELENE-XR service real, backend-verified operator logins (username/password, Argon2, server-side sessions) with a fixed per-account role (analyst/reviewer/admin) that gates server-side behavior, plus the minimal web console UI to log in, show who's logged in, and let an Admin provision accounts.

**Architecture:** A new `AuthenticationMode.SESSION` mode adds a session-cookie identity path alongside the service's existing loopback/API-key paths, without changing either. Each operator account (`user_accounts`) is 1:1-linked to its own `Subject` row, so every existing provenance/ownership column that already references `subjects.id` works unchanged for human-authenticated actions. Sessions are server-side and opaque (`user_sessions`, no JWT). The auth HTTP surface (login/logout/session/user-management) is only mounted when the deployment is actually in `SESSION` mode, so existing `UNAUTHENTICATED`/`EXTERNAL` deployments are unaffected and the frontend can detect "auth isn't configured here" (404) versus "you're not logged in" (401).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL, `argon2-cffi` (new dependency) on the backend. React, TanStack Query, react-router-dom, Tailwind on the frontend (no new frontend dependency).

**Spec:** `docs/adr/0016-session-authentication-and-roles.md`

## Global Constraints

- Passwords are hashed with Argon2 (`argon2-cffi`) — never SHA-256, never stored plaintext, never logged. (ADR-0016 Decision)
- Session id is a UUID stored server-side in `user_sessions`; the cookie carries no claims of its own. Cookie is `httpOnly`, `SameSite=Strict`. (ADR-0016 Decision)
- Role is exactly one of `"analyst" | "reviewer" | "admin"`, fixed per account. No endpoint may let a session change its own role. (ADR-0016 Decision, Alternatives considered)
- Every operator account is 1:1-linked to a `Subject` row (`subject_type='user'`) via a unique `subject_id` FK on `user_accounts`. No other persisted table changes. (ADR-0016 Decision, Context)
- `AuthenticationMode.SESSION` does not loosen `validate_network_boundary()` — this plan does not touch that function or ADR-0015's open question. (ADR-0016 Context)
- The first Admin account is bootstrapped the same way the existing local API key is (`bootstrap_local_api_key`'s pattern): an idempotent upsert from `SELENE_SERVICE_BOOTSTRAP_ADMIN_USERNAME` / `SELENE_SERVICE_BOOTSTRAP_ADMIN_PASSWORD`, no-op when either is unset. Every later account is Admin-created via the API — no self-service signup. (ADR-0016 Decision)
- No OAuth/SSO/Keycloak, no password reset over email, no multi-device session-management UI, no rate limiting beyond a simple fixed-window lockout after repeated failed logins on one account. (ADR-0016 Consequences — explicitly out of scope)
- Backend commands: `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy`, `uv run pytest -m "unit or property"` (run from repo root; strict mypy — every new function needs full type annotations).
- Frontend commands (run from `web/`): `./node_modules/.bin/oxlint <files>`, `./node_modules/.bin/tsc -b --noEmit`, `./node_modules/.bin/vitest run <files>`.
- Follow existing file conventions exactly: routes delegate to `services.py`, which delegates to repositories/ORM; Pydantic schemas use `ConfigDict(extra="forbid")` for requests and `ConfigDict(frozen=True)` for responses; frontend API contracts (snake_case) live in `services/api/contracts.ts`, repositories translate to camelCase domain types, hooks live under `features/<area>/`.

---

## Task 1: Password hashing

**Files:**
- Create: `packages/selene_service/src/selene_service/api/password_auth.py`
- Test: `tests/unit/test_password_auth.py`
- Modify: `packages/selene_service/pyproject.toml`

**Interfaces:**
- Produces: `hash_password(raw: str) -> str`, `verify_password(raw: str, hashed: str) -> bool` — used by Task 4 (session_auth) and Task 7 (admin user creation/reset).

- [ ] **Step 1: Add the `argon2-cffi` dependency**

In `packages/selene_service/pyproject.toml`, add to the `dependencies` list (keep alphabetical-by-topic ordering already used there — add after `alembic>=1.13`):

```toml
dependencies = [
    "selene-core",
    "fastapi>=0.111",
    "uvicorn>=0.30",
    "pydantic-settings>=2.3",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "argon2-cffi>=23.1",
    "psycopg[binary]>=3.1",
    "geoalchemy2>=0.15",
]
```

Run `uv sync` from the repo root so the lockfile picks it up.

- [ ] **Step 2: Write the failing test**

```python
"""Contracts for operator password hashing."""

from __future__ import annotations

import pytest

from selene_service.api.password_auth import hash_password, verify_password


@pytest.mark.unit
def test_hash_password_never_returns_the_raw_value() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2id$")


@pytest.mark.unit
def test_verify_password_accepts_the_matching_raw_value() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


@pytest.mark.unit
def test_verify_password_rejects_a_wrong_value() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("wrong password", hashed) is False


@pytest.mark.unit
def test_verify_password_rejects_a_malformed_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


@pytest.mark.unit
def test_hash_password_is_salted_so_two_hashes_of_one_password_differ() -> None:
    first = hash_password("same password")
    second = hash_password("same password")

    assert first != second
    assert verify_password("same password", first) is True
    assert verify_password("same password", second) is True
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_password_auth.py -v`
Expected: FAIL / ERROR — `selene_service.api.password_auth` does not exist yet.

- [ ] **Step 4: Write the implementation**

```python
"""Argon2 password hashing for operator accounts.

Never reuse ``selene_service.api.local_auth.digest_api_key`` (SHA-256) here —
that digest is for comparing a supplied API key against a stored value in
constant time, not for storing a human-chosen secret. Argon2id is memory-hard
and salted per call, which SHA-256 is neither.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_HASHER = PasswordHasher()


def hash_password(raw: str) -> str:
    """Return a salted Argon2id hash string; never the raw password."""

    return _HASHER.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """Return whether *raw* matches *hashed*, without raising on bad input."""

    try:
        return _HASHER.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_password_auth.py -v`
Expected: PASS (5/5)

- [ ] **Step 6: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/api/password_auth.py` and `uv run ruff check packages/selene_service/src/selene_service/api/password_auth.py tests/unit/test_password_auth.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/selene_service/pyproject.toml uv.lock packages/selene_service/src/selene_service/api/password_auth.py tests/unit/test_password_auth.py
git commit -m "feat(service): add Argon2 password hashing for operator accounts"
```

---

## Task 2: Persistence — `user_accounts` and `user_sessions`

**Files:**
- Modify: `packages/selene_service/src/selene_service/persistence/models.py`
- Create: `packages/selene_service/src/selene_service/persistence/migrations/versions/20260830_005_add_user_accounts_and_sessions.py`
- Test: `tests/unit/test_service_models.py` (create if it doesn't already cover this; check first — if a models test file exists, add to it instead)

**Interfaces:**
- Produces: ORM classes `UserAccount` (`user_accounts`) and `UserSession` (`user_sessions`) in `selene_service.persistence.models`, importable exactly as `Subject`/`ApiKey` are today. Consumed by Task 4 (session_auth), Task 5 (identity seam), Task 7 (admin user management).
- `UserAccount` columns: `id: UUID`, `subject_id: UUID` (FK `subjects.id`, unique), `username: str`, `password_hash: str`, `role: str`, `display_name: str`, `is_active: bool`, `created_by_user_account_id: UUID | None` (self-FK), `failed_login_count: int`, `locked_until: datetime | None`, `last_login_at: datetime | None`, `created_at: datetime`.
- `UserSession` columns: `id: UUID` (the cookie value), `user_account_id: UUID` (FK `user_accounts.id`), `created_at: datetime`, `expires_at: datetime`, `revoked_at: datetime | None`.

- [ ] **Step 1: Check for an existing models test file**

Run: `ls tests/unit/ | grep -i model`

If a file like `test_service_models.py` exists, read it and add the new tests below to it, following its existing style. If none exists, create `tests/unit/test_service_models.py` fresh — it only needs a real Postgres-backed session to test constraints, so keep these as pure ORM-construction tests (no DB) matching the style of tests elsewhere that build model instances directly (see `tests/unit/test_local_api_auth.py`'s `Subject(...)`/`ApiKey(...)` construction).

- [ ] **Step 2: Write the failing test**

```python
"""Contracts for the operator account and session ORM mapping."""

from __future__ import annotations

from uuid import uuid4

import pytest

from selene_service.persistence.models import UserAccount, UserSession


@pytest.mark.unit
def test_user_account_constructs_with_required_fields() -> None:
    subject_id = uuid4()

    account = UserAccount(
        subject_id=subject_id,
        username="dijo.benelen",
        password_hash="$argon2id$fake",
        role="reviewer",
        display_name="Dijo Benelen",
    )

    assert account.subject_id == subject_id
    assert account.username == "dijo.benelen"
    assert account.role == "reviewer"
    assert account.is_active is True
    assert account.failed_login_count == 0
    assert account.locked_until is None


@pytest.mark.unit
def test_user_session_constructs_with_required_fields() -> None:
    account_id = uuid4()

    session = UserSession(user_account_id=account_id)

    assert session.user_account_id == account_id
    assert session.revoked_at is None
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_service_models.py -v`
Expected: FAIL — `UserAccount`/`UserSession` do not exist yet.

- [ ] **Step 4: Add the models**

In `packages/selene_service/src/selene_service/persistence/models.py`, add directly after the `ApiKey` class (before `Product`):

```python
class UserAccount(Base):
    """A human operator's login, 1:1-linked to its own durable subject."""

    __tablename__ = "user_accounts"
    __table_args__ = (
        CheckConstraint(
            "role IN ('analyst', 'reviewer', 'admin')", name="ck_user_accounts_role"
        ),
        UniqueConstraint("subject_id", name="uq_user_accounts_subject_id"),
        UniqueConstraint("username", name="uq_user_accounts_username"),
        Index("ix_user_accounts_created_by_user_account_id", "created_by_user_account_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    subject_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    # Argon2id encoded hash string (algorithm, params, salt, and digest all
    # inline). Never a plaintext password or a separate salt column.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default=text("true"))
    created_by_user_account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    @validates("username")
    def _normalize_username(self, _key: str, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class UserSession(Base):
    """An opaque, server-side, revocable operator session."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_account_id", "user_account_id"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_service_models.py -v`
Expected: PASS (2/2)

- [ ] **Step 6: Write the Alembic migration**

Create `packages/selene_service/src/selene_service/persistence/migrations/versions/20260830_005_add_user_accounts_and_sessions.py`:

```python
"""Add operator user accounts and server-side sessions.

Revision ID: 20260830_005
Revises: 20260830_004
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260830_005"
down_revision = "20260830_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create user_accounts (1:1 with subjects) and user_sessions."""

    op.create_table(
        "user_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_user_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_user_account_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_accounts"),
        sa.UniqueConstraint("subject_id", name="uq_user_accounts_subject_id"),
        sa.UniqueConstraint("username", name="uq_user_accounts_username"),
        sa.CheckConstraint(
            "role IN ('analyst', 'reviewer', 'admin')", name="ck_user_accounts_role"
        ),
    )
    op.create_index(
        "ix_user_accounts_created_by_user_account_id",
        "user_accounts",
        ["created_by_user_account_id"],
        unique=False,
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_account_id"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
    )
    op.create_index(
        "ix_user_sessions_user_account_id", "user_sessions", ["user_account_id"], unique=False
    )
    op.create_index(
        "ix_user_sessions_expires_at", "user_sessions", ["expires_at"], unique=False
    )


def downgrade() -> None:
    """Drop sessions before accounts to respect the foreign key."""

    op.drop_table("user_sessions")
    op.drop_table("user_accounts")
```

- [ ] **Step 7: If a local Postgres is reachable, verify the migration applies cleanly**

Run (only if `SELENE_SERVICE_TEST_DATABASE_URL` is set in your environment — otherwise skip this step, the integration suite covers it later):
`SELENE_SERVICE_DATABASE_URL=$SELENE_SERVICE_TEST_DATABASE_URL uv run alembic -c packages/selene_service/alembic.ini upgrade head`
Expected: no errors; `alembic -c packages/selene_service/alembic.ini current` shows `20260830_005`.

- [ ] **Step 8: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/persistence/models.py` and `uv run ruff check packages/selene_service/src/selene_service/persistence/models.py packages/selene_service/src/selene_service/persistence/migrations/versions/20260830_005_add_user_accounts_and_sessions.py tests/unit/test_service_models.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add packages/selene_service/src/selene_service/persistence/models.py packages/selene_service/src/selene_service/persistence/migrations/versions/20260830_005_add_user_accounts_and_sessions.py tests/unit/test_service_models.py
git commit -m "feat(service): add user_accounts and user_sessions persistence"
```

---

## Task 3: Settings — SESSION mode and bootstrap configuration

**Files:**
- Modify: `packages/selene_service/src/selene_service/settings.py`
- Test: `tests/unit/test_service_app.py` (add to the existing settings tests near `test_settings_read_typed_service_environment`)

**Interfaces:**
- Produces: `AuthenticationMode.SESSION`, and on `ServiceSettings`: `session_cookie_name: str` (default `"selene_session"`), `session_ttl_seconds: int` (default `43200`, i.e. 12 hours), `bootstrap_admin_username: str | None`, `bootstrap_admin_password: SecretStr | None`, `login_lockout_threshold: int` (default `5`), `login_lockout_seconds: int` (default `30`). Consumed by Task 4 (session_auth), Task 5 (identity seam), Task 6 (auth routes/app wiring).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_service_app.py`:

```python
@pytest.mark.unit
def test_settings_read_session_authentication_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SELENE_SERVICE_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("SELENE_SERVICE_AUTHENTICATION_MODE", "session")
    monkeypatch.setenv("SELENE_SERVICE_SESSION_COOKIE_NAME", "selene_session_test")
    monkeypatch.setenv("SELENE_SERVICE_SESSION_TTL_SECONDS", "600")
    monkeypatch.setenv("SELENE_SERVICE_BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("SELENE_SERVICE_BOOTSTRAP_ADMIN_PASSWORD", "a-strong-bootstrap-password")
    monkeypatch.setenv("SELENE_SERVICE_LOGIN_LOCKOUT_THRESHOLD", "3")
    monkeypatch.setenv("SELENE_SERVICE_LOGIN_LOCKOUT_SECONDS", "15")

    settings = ServiceSettings()

    assert settings.authentication_mode is AuthenticationMode.SESSION
    assert settings.session_cookie_name == "selene_session_test"
    assert settings.session_ttl_seconds == 600
    assert settings.bootstrap_admin_username == "admin"
    assert settings.bootstrap_admin_password is not None
    assert settings.bootstrap_admin_password.get_secret_value() == "a-strong-bootstrap-password"
    assert settings.login_lockout_threshold == 3
    assert settings.login_lockout_seconds == 15


@pytest.mark.unit
def test_session_settings_default_without_environment_configuration() -> None:
    settings = _settings()

    assert settings.session_cookie_name == "selene_session"
    assert settings.session_ttl_seconds == 43_200
    assert settings.bootstrap_admin_username is None
    assert settings.bootstrap_admin_password is None
    assert settings.login_lockout_threshold == 5
    assert settings.login_lockout_seconds == 30
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_service_app.py -k session -v`
Expected: FAIL — `AuthenticationMode.SESSION` and the new settings fields don't exist yet.

- [ ] **Step 3: Extend the settings**

In `packages/selene_service/src/selene_service/settings.py`:

```python
class AuthenticationMode(StrEnum):
    """Authentication boundary declared by the service operator.

    ``EXTERNAL`` deliberately names no identity provider. It is a configuration
    declaration for a future authentication integration or an upstream gateway;
    it does not implement, validate, or advertise Keycloak authentication.
    ``SESSION`` is a real, implemented mechanism: operator username/password
    login with a server-side session cookie (ADR-0016). It does not change
    the loopback-only-versus-authenticated network boundary question, which
    stays governed separately by ADR-0015.
    """

    UNAUTHENTICATED = "unauthenticated"
    EXTERNAL = "external"
    SESSION = "session"
```

Then, in `ServiceSettings`, add these fields directly after `local_api_key_subject`:

```python
    session_cookie_name: str = Field(default="selene_session", min_length=1, max_length=64)
    session_ttl_seconds: int = Field(default=43_200, ge=60)
    # Both must be set together to bootstrap the first Admin account; a
    # deployment that never sets them simply never gets an auto-created
    # Admin (ADR-0016).
    bootstrap_admin_username: str | None = Field(default=None, min_length=1, max_length=64)
    bootstrap_admin_password: SecretStr | None = Field(default=None, min_length=8)
    login_lockout_threshold: int = Field(default=5, ge=1)
    login_lockout_seconds: int = Field(default=30, ge=1)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_service_app.py -v`
Expected: PASS, including all pre-existing tests in this file (no regressions).

- [ ] **Step 5: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/settings.py` and `uv run ruff check packages/selene_service/src/selene_service/settings.py tests/unit/test_service_app.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add packages/selene_service/src/selene_service/settings.py tests/unit/test_service_app.py
git commit -m "feat(service): add SESSION authentication mode and bootstrap settings"
```

---

## Task 4: Session mechanics

**Files:**
- Create: `packages/selene_service/src/selene_service/api/session_auth.py`
- Test: `tests/unit/test_session_auth.py`

**Interfaces:**
- Consumes: `hash_password`/`verify_password` (Task 1), `UserAccount`/`UserSession` (Task 2), `ServiceSettings` (Task 3), `Subject` (existing).
- Produces (all consumed by Task 5 and Task 6):
  - `bootstrap_admin_user(session_factory: Callable[[], Session], settings: ServiceSettings) -> None`
  - `create_session(session: Session, user_account: UserAccount, settings: ServiceSettings) -> UserSession`
  - `resolve_session(session: Session, session_id: UUID) -> tuple[UserAccount, Subject] | None` — `None` for missing/expired/revoked, or the account is inactive.
  - `revoke_session(session: Session, session_id: UUID) -> None`
  - `authenticate_with_password(session: Session, username: str, password: str, settings: ServiceSettings) -> UserAccount` — raises `APIProblem(401, "unauthorized", ...)` on any failure (unknown user, wrong password, locked, inactive); never distinguishes which in the message (no username enumeration).
  - `record_login_failure(session: Session, user_account: UserAccount, settings: ServiceSettings) -> None`
  - `record_login_success(session: Session, user_account: UserAccount) -> None`

- [ ] **Step 1: Write the failing test**

```python
"""Contracts for server-side operator sessions and login lockout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from selene_service.api.errors import APIProblem
from selene_service.api.password_auth import hash_password
from selene_service.api.session_auth import (
    authenticate_with_password,
    bootstrap_admin_user,
    create_session,
    resolve_session,
    revoke_session,
)
from selene_service.persistence.models import Base, Subject, UserAccount, UserSession
from selene_service.settings import AuthenticationMode, ServiceSettings

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session(postgres_engine) -> Session:  # type: ignore[no-untyped-def]
    """A real transactional Postgres session; see tests/integration/conftest.py."""

    Base.metadata.create_all(postgres_engine)
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=postgres_engine)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _settings(**overrides: object) -> ServiceSettings:
    defaults: dict[str, object] = {
        "bind_host": "127.0.0.1",
        "authentication_mode": AuthenticationMode.SESSION,
        "bootstrap_admin_username": "admin",
        "bootstrap_admin_password": "a-strong-bootstrap-password",
    }
    defaults.update(overrides)
    return ServiceSettings.model_validate(defaults)


def _make_account(db_session: Session, *, role: str = "reviewer") -> UserAccount:
    subject = Subject(subject_name="operator-under-test", subject_type="user", is_active=True)
    db_session.add(subject)
    db_session.flush()
    account = UserAccount(
        subject_id=subject.id,
        username="operator",
        password_hash=hash_password("correct horse battery staple"),
        role=role,
        display_name="Operator",
    )
    db_session.add(account)
    db_session.flush()
    return account


@pytest.mark.integration
def test_bootstrap_admin_user_creates_one_active_admin_idempotently(db_session: Session) -> None:
    settings = _settings()

    bootstrap_admin_user(lambda: db_session, settings)
    bootstrap_admin_user(lambda: db_session, settings)

    accounts = db_session.scalars(select(UserAccount).where(UserAccount.username == "admin")).all()
    assert len(accounts) == 1
    assert accounts[0].role == "admin"
    assert accounts[0].is_active is True


@pytest.mark.integration
def test_bootstrap_admin_user_is_a_noop_without_both_settings(db_session: Session) -> None:
    settings = _settings(bootstrap_admin_password=None)

    bootstrap_admin_user(lambda: db_session, settings)

    assert db_session.scalars(select(UserAccount)).first() is None


@pytest.mark.integration
def test_authenticate_with_password_accepts_correct_credentials(db_session: Session) -> None:
    account = _make_account(db_session)
    db_session.commit()

    authenticated = authenticate_with_password(
        db_session, "operator", "correct horse battery staple", _settings()
    )

    assert authenticated.id == account.id


@pytest.mark.integration
def test_authenticate_with_password_rejects_wrong_password_without_enumeration(
    db_session: Session,
) -> None:
    _make_account(db_session)
    db_session.commit()

    with pytest.raises(APIProblem) as unknown_user, pytest.raises(APIProblem):
        authenticate_with_password(db_session, "nobody", "irrelevant", _settings())
    with pytest.raises(APIProblem) as wrong_password:
        authenticate_with_password(
            db_session, "operator", "totally wrong", _settings()
        )

    assert unknown_user.value.status_code == 401
    assert wrong_password.value.status_code == 401
    assert unknown_user.value.message == wrong_password.value.message


@pytest.mark.integration
def test_repeated_failures_lock_the_account_for_the_configured_window(
    db_session: Session,
) -> None:
    _make_account(db_session)
    db_session.commit()
    settings = _settings(login_lockout_threshold=2, login_lockout_seconds=30)

    with pytest.raises(APIProblem):
        authenticate_with_password(db_session, "operator", "wrong", settings)
    with pytest.raises(APIProblem):
        authenticate_with_password(db_session, "operator", "wrong", settings)
    with pytest.raises(APIProblem):
        # Third attempt uses the *correct* password but the account is locked.
        authenticate_with_password(
            db_session, "operator", "correct horse battery staple", settings
        )


@pytest.mark.integration
def test_create_resolve_and_revoke_session_round_trip(db_session: Session) -> None:
    account = _make_account(db_session)
    db_session.commit()
    settings = _settings()

    session_row = create_session(db_session, account, settings)
    db_session.commit()
    resolved = resolve_session(db_session, session_row.id)
    assert resolved is not None
    resolved_account, resolved_subject = resolved
    assert resolved_account.id == account.id
    assert resolved_subject.id == account.subject_id

    revoke_session(db_session, session_row.id)
    db_session.commit()
    assert resolve_session(db_session, session_row.id) is None


@pytest.mark.integration
def test_resolve_session_returns_none_for_an_expired_session(db_session: Session) -> None:
    account = _make_account(db_session)
    db_session.flush()
    expired = UserSession(
        user_account_id=account.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db_session.add(expired)
    db_session.commit()

    assert resolve_session(db_session, expired.id) is None
```

- [ ] **Step 2: Check for an integration test fixture named `postgres_engine`**

Run: `grep -rn "postgres_engine\|SELENE_SERVICE_TEST_DATABASE_URL" tests/integration/conftest.py tests/conftest.py 2>/dev/null`

If no `postgres_engine` fixture exists yet, read `tests/integration/test_postgres_persistence.py` for how it currently constructs a Postgres engine and either (a) add a small shared `postgres_engine` fixture to `tests/integration/conftest.py` that mirrors that file's `create_service_engine`/skip-if-unset pattern, or (b) inline the same skip-if-unset + engine construction directly at the top of `tests/unit/test_session_auth.py` instead of using a fixture, matching whatever `test_postgres_persistence.py` already does. Do not invent a new database-connection pattern — copy the existing one exactly.

- [ ] **Step 3: Run the test to verify it fails**

Run: `SELENE_SERVICE_TEST_DATABASE_URL=<your test db url> uv run pytest tests/unit/test_session_auth.py -v` (or `uv run pytest tests/unit/test_session_auth.py -v` to confirm it skips cleanly if unset)
Expected: FAIL/ERROR — `selene_service.api.session_auth` does not exist yet (once a database is available; otherwise the whole file should skip via the same mechanism `test_postgres_persistence.py` uses).

- [ ] **Step 4: Write the implementation**

```python
"""Server-side operator sessions, login, lockout, and Admin bootstrap.

Mirrors ``selene_service.api.local_auth``'s bootstrap pattern: an idempotent
upsert driven by env-configured settings, called from the app's lifespan
hook. Unlike that module, credentials here are human-chosen passwords, so
they are Argon2-hashed (``password_auth``), never SHA-256-digested.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from selene_service.api.errors import APIProblem
from selene_service.api.password_auth import hash_password, verify_password
from selene_service.persistence.models import Subject, UserAccount, UserSession
from selene_service.settings import ServiceSettings

_UNAUTHORIZED_MESSAGE = "The username or password is incorrect."
_BOOTSTRAP_SUBJECT_TYPE = "user"


def bootstrap_admin_user(
    session_factory: Callable[[], Session],
    settings: ServiceSettings,
) -> None:
    """Idempotently create the first Admin account from configured settings.

    A no-op unless both ``bootstrap_admin_username`` and
    ``bootstrap_admin_password`` are set. Never overwrites an existing
    account's password or role on a later restart with different env values
    — that would silently change a live account out from under an operator
    who has since changed it. Rotate a bootstrap admin's password through
    the normal Admin-reset path, not by editing the environment.
    """

    if settings.bootstrap_admin_username is None or settings.bootstrap_admin_password is None:
        return

    username = settings.bootstrap_admin_username.strip().casefold()
    session = session_factory()
    try:
        with session.begin():
            existing = session.scalar(
                select(UserAccount).where(UserAccount.username == username)
            )
            if existing is not None:
                return

            subject = Subject(
                subject_name=f"user:{username}",
                subject_type=_BOOTSTRAP_SUBJECT_TYPE,
                is_active=True,
            )
            session.add(subject)
            session.flush()
            session.add(
                UserAccount(
                    subject_id=subject.id,
                    username=username,
                    password_hash=hash_password(
                        settings.bootstrap_admin_password.get_secret_value()
                    ),
                    role="admin",
                    display_name=settings.bootstrap_admin_username,
                )
            )
    finally:
        session.close()


def authenticate_with_password(
    session: Session,
    username: str,
    password: str,
    settings: ServiceSettings,
) -> UserAccount:
    """Return the matching active, unlocked account or raise 401.

    The failure message never reveals whether the username exists, whether
    the password was wrong, or whether the account is locked — all three
    return the identical 401 (ADR-0016 Verification: no username
    enumeration).
    """

    normalized = username.strip().casefold()
    account = session.scalar(select(UserAccount).where(UserAccount.username == normalized))
    if account is None:
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)
    if not account.is_active:
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)
    if account.locked_until is not None and account.locked_until > datetime.now(UTC):
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)

    if not verify_password(password, account.password_hash):
        record_login_failure(session, account, settings)
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)

    record_login_success(session, account)
    return account


def record_login_failure(
    session: Session, user_account: UserAccount, settings: ServiceSettings
) -> None:
    """Increment the failure counter and lock the account past the threshold."""

    user_account.failed_login_count += 1
    if user_account.failed_login_count >= settings.login_lockout_threshold:
        user_account.locked_until = datetime.now(UTC) + timedelta(
            seconds=settings.login_lockout_seconds
        )
    session.add(user_account)
    session.flush()


def record_login_success(session: Session, user_account: UserAccount) -> None:
    """Reset lockout state and stamp the login time."""

    user_account.failed_login_count = 0
    user_account.locked_until = None
    user_account.last_login_at = datetime.now(UTC)
    session.add(user_account)
    session.flush()


def create_session(
    session: Session, user_account: UserAccount, settings: ServiceSettings
) -> UserSession:
    """Create and persist one new server-side session for *user_account*."""

    row = UserSession(
        user_account_id=user_account.id,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
    )
    session.add(row)
    session.flush()
    return row


def resolve_session(session: Session, session_id: UUID) -> tuple[UserAccount, Subject] | None:
    """Return the (account, subject) pair for a live session, else ``None``."""

    row = session.get(UserSession, session_id)
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        return None
    account = session.get(UserAccount, row.user_account_id)
    if account is None or not account.is_active:
        return None
    subject = session.get(Subject, account.subject_id)
    if subject is None or not subject.is_active:
        return None
    return account, subject


def revoke_session(session: Session, session_id: UUID) -> None:
    """Revoke a session; a no-op if it does not exist or is already revoked."""

    row = session.get(UserSession, session_id)
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = datetime.now(UTC)
    session.add(row)
    session.flush()
```

Note: `postgresql_insert` is imported but unused in the version above — remove that import; `bootstrap_admin_user` uses a plain select-then-insert inside `session.begin()` instead (matching `bootstrap_local_api_key`'s transactional pattern, not its upsert helper, since accounts are created once and never overwritten here).

- [ ] **Step 5: Run the test to verify it passes**

Run: `SELENE_SERVICE_TEST_DATABASE_URL=<your test db url> uv run pytest tests/unit/test_session_auth.py -v`
Expected: PASS (all cases), or a clean skip if no test database is configured in this environment — in that case, note in your task report that this task's tests are unverified pending a database and must be run before merge.

- [ ] **Step 6: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/api/session_auth.py` and `uv run ruff check packages/selene_service/src/selene_service/api/session_auth.py tests/unit/test_session_auth.py`
Expected: no errors. Confirm the unused `postgresql_insert` import was removed per the note in Step 4.

- [ ] **Step 7: Commit**

```bash
git add packages/selene_service/src/selene_service/api/session_auth.py tests/unit/test_session_auth.py tests/integration/conftest.py
git commit -m "feat(service): add session mechanics, login lockout, and admin bootstrap"
```

---

## Task 5: Identity seam — session-aware `get_subject_identity`

**Files:**
- Modify: `packages/selene_service/src/selene_service/api/dependencies.py`
- Modify: `packages/selene_service/src/selene_service/api/local_auth.py`
- Test: `tests/unit/test_local_api_auth.py` (extend), `tests/unit/test_session_auth_dependency.py` (create)

**Interfaces:**
- Consumes: `resolve_session` (Task 4), `UserAccount`/`Subject` (Task 2/existing).
- Produces: `SubjectIdentity` gains `role: str | None = None` and `user_account_id: UUID | None = None` (both defaulted — every existing construction like `SubjectIdentity(subject_name=..., subject_type=...)` keeps compiling unchanged). `get_subject_identity` gains a session-cookie branch. Consumed by Task 6 (auth routes use the cookie name), Task 7 (admin routes require `identity.role == "admin"`), Task 8 (review role-gating).

- [ ] **Step 1: Write the failing test for the extended `SubjectIdentity` and dependency behavior**

Create `tests/unit/test_session_auth_dependency.py`:

```python
"""Contracts for the session-cookie branch of get_subject_identity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from selene_service.api.dependencies import SubjectIdentity, get_subject_identity
from selene_service.api.errors import APIProblem
from selene_service.persistence.models import Subject, UserAccount, UserSession
from selene_service.settings import AuthenticationMode, ServiceSettings


def _settings(**overrides: object) -> ServiceSettings:
    defaults: dict[str, object] = {
        "bind_host": "127.0.0.1",
        "authentication_mode": AuthenticationMode.SESSION,
    }
    defaults.update(overrides)
    return ServiceSettings.model_validate(defaults)


def _request_with_cookie(settings: ServiceSettings, session_factory: object, cookie: str | None) -> Request:
    scope = {
        "type": "http",
        "headers": [(b"cookie", f"{settings.session_cookie_name}={cookie}".encode())]
        if cookie
        else [],
        "app": MagicMock(state=MagicMock(settings=settings, session_factory=session_factory)),
    }
    return Request(scope)


@pytest.mark.unit
def test_subject_identity_defaults_role_and_account_id_to_none() -> None:
    identity = SubjectIdentity(subject_name="local-loopback", subject_type="local")

    assert identity.role is None
    assert identity.user_account_id is None


@pytest.mark.unit
def test_session_branch_resolves_role_from_a_valid_cookie() -> None:
    settings = _settings()
    account_id = uuid4()
    subject_id = uuid4()
    session_id = uuid4()
    account = UserAccount(
        id=account_id,
        subject_id=subject_id,
        username="reviewer.one",
        password_hash="unused",
        role="reviewer",
        display_name="Reviewer One",
    )
    subject = Subject(id=subject_id, subject_name="user:reviewer.one", subject_type="user", is_active=True)

    class _Session:
        def get(self, model: object, ident: object) -> object:
            if model is UserSession:
                return UserSession(
                    id=session_id,
                    user_account_id=account_id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            if model is UserAccount:
                return account
            return subject

        def close(self) -> None:
            return None

    request = _request_with_cookie(settings, lambda: _Session(), str(session_id))

    identity = get_subject_identity(request, api_key=None)

    assert identity == SubjectIdentity(
        subject_name="user:reviewer.one",
        subject_type="user",
        role="reviewer",
        user_account_id=account_id,
    )


@pytest.mark.unit
def test_session_branch_falls_through_to_api_key_requirement_without_a_cookie() -> None:
    settings = _settings()
    request = _request_with_cookie(settings, lambda: None, cookie=None)

    with pytest.raises(APIProblem) as problem:
        get_subject_identity(request, api_key=None)

    assert problem.value.status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_session_auth_dependency.py -v`
Expected: FAIL — `SubjectIdentity` has no `role`/`user_account_id` fields yet, and there is no session-cookie branch.

- [ ] **Step 3: Extend `SubjectIdentity` and `get_subject_identity`**

In `packages/selene_service/src/selene_service/api/dependencies.py`:

```python
"""FastAPI dependency seams for database access and local identity."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from selene_service.api.errors import APIProblem
from selene_service.api.local_auth import authenticate_api_key
from selene_service.api.session_auth import resolve_session
from selene_service.settings import AuthenticationMode


@dataclass(frozen=True, slots=True)
class SubjectIdentity:
    """The non-secret identity descriptor used to locate a durable subject."""

    subject_name: str
    subject_type: str
    role: str | None = None
    user_account_id: UUID | None = None


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield an application-owned request session without committing implicitly.

    Tests can override this dependency directly, so they never need a live
    PostgreSQL server merely to exercise request validation or response shapes.
    """

    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise RuntimeError("Database session factory is not available")
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def get_subject_identity(
    request: Request,
    api_key: Annotated[str | None, Header(alias="X-SELENE-API-Key")] = None,
) -> SubjectIdentity:
    """Return the local single-user identity, a session identity, or an API-key subject.

    Unauthenticated deployments are restricted to loopback by settings, so a
    stable local subject is sufficient and is persisted lazily on the first
    mutating request. Session-mode deployments try the session cookie first;
    a missing or invalid cookie falls through to the same API-key requirement
    EXTERNAL mode already enforces, so a session-mode deployment still
    accepts the local-platform-web-proxy key for non-browser callers.
    """

    settings = request.app.state.settings
    if settings.authentication_mode is AuthenticationMode.UNAUTHENTICATED:
        return SubjectIdentity(subject_name="local-loopback", subject_type="local")

    if settings.authentication_mode is AuthenticationMode.SESSION:
        cookie_value = request.cookies.get(settings.session_cookie_name)
        if cookie_value:
            session_factory = getattr(request.app.state, "session_factory", None)
            if session_factory is None:
                raise RuntimeError("Database session factory is not available")
            db_session = session_factory()
            try:
                resolved = resolve_session(db_session, UUID(cookie_value))
            except ValueError:
                resolved = None
            finally:
                db_session.close()
            if resolved is not None:
                account, subject = resolved
                return SubjectIdentity(
                    subject_name=subject.subject_name,
                    subject_type=subject.subject_type,
                    role=account.role,
                    user_account_id=account.id,
                )

    if api_key is None or not api_key.strip():
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise RuntimeError("Database session factory is not available")
    session = session_factory()
    try:
        subject_name, subject_type = authenticate_api_key(session, api_key.strip())
    finally:
        session.close()
    return SubjectIdentity(subject_name=subject_name, subject_type=subject_type)


DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentIdentity = Annotated[SubjectIdentity, Depends(get_subject_identity)]
```

The cookie is read via `request.cookies.get(...)` rather than a FastAPI `Cookie(...)` parameter, so it can be looked up by the *configured* cookie name (`settings.session_cookie_name`) rather than a name hardcoded at parameter-declaration time.

- [ ] **Step 4: Broaden `bootstrap_local_api_key`'s mode gate**

In `packages/selene_service/src/selene_service/api/local_auth.py`, change:

```python
    if (
        settings.authentication_mode is not AuthenticationMode.EXTERNAL
        or settings.local_api_key is None
    ):
        return
```

to:

```python
    if (
        settings.authentication_mode
        not in (AuthenticationMode.EXTERNAL, AuthenticationMode.SESSION)
        or settings.local_api_key is None
    ):
        return
```

This keeps the packaged local-platform-web-proxy API key working under `SESSION` mode too, for the proxy's own internal calls — session cookies are for browser operators, not the proxy.

Add one test for this to `tests/unit/test_local_api_auth.py`, next to the existing bootstrap tests:

```python
@pytest.mark.unit
def test_local_bootstrap_also_runs_under_session_mode() -> None:
    session = _BootstrapSession()
    settings = ServiceSettings.model_validate(
        {
            "bind_host": "127.0.0.1",
            "authentication_mode": AuthenticationMode.SESSION,
            "local_api_key": LOCAL_KEY,
        }
    )

    bootstrap_local_api_key(lambda: session, settings)

    assert session.key is not None
```

- [ ] **Step 5: Run all the affected tests**

Run: `uv run pytest tests/unit/test_session_auth_dependency.py tests/unit/test_local_api_auth.py -v`
Expected: PASS, including every pre-existing test in `test_local_api_auth.py` (no regressions).

- [ ] **Step 6: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/api/dependencies.py packages/selene_service/src/selene_service/api/local_auth.py` and `uv run ruff check packages/selene_service/src/selene_service/api/dependencies.py packages/selene_service/src/selene_service/api/local_auth.py tests/unit/test_session_auth_dependency.py tests/unit/test_local_api_auth.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/selene_service/src/selene_service/api/dependencies.py packages/selene_service/src/selene_service/api/local_auth.py tests/unit/test_session_auth_dependency.py tests/unit/test_local_api_auth.py
git commit -m "feat(service): resolve identity from a session cookie before API key"
```

---

## Task 6: Auth HTTP surface — login, logout, session

**Files:**
- Modify: `packages/selene_service/src/selene_service/api/schemas.py`
- Create: `packages/selene_service/src/selene_service/api/auth_services.py`
- Create: `packages/selene_service/src/selene_service/api/auth_routes.py`
- Modify: `packages/selene_service/src/selene_service/app.py`
- Test: `tests/unit/test_auth_routes.py`

**Interfaces:**
- Consumes: `authenticate_with_password`, `create_session`, `revoke_session` (Task 4); `CurrentIdentity`, `DatabaseSession` (Task 5); `bootstrap_admin_user` (Task 4).
- Produces: `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/session`. Mounted **only** when `settings.authentication_mode is AuthenticationMode.SESSION` — in any other mode these paths 404, which Task 11's frontend guard relies on to detect "auth isn't configured here". Response schema `SessionUserResponse` (username, display_name, role) consumed by Task 9's `authRepository`.

- [ ] **Step 1: Write the failing test**

```python
"""Contracts for login, logout, and session-hydration routes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from selene_service.api.dependencies import get_db_session
from selene_service.api.password_auth import hash_password
from selene_service.app import create_app
from selene_service.persistence.models import Subject, UserAccount, UserSession
from selene_service.settings import AuthenticationMode, ServiceSettings


def _session_settings(**overrides: object) -> ServiceSettings:
    defaults: dict[str, object] = {
        "bind_host": "127.0.0.1",
        "authentication_mode": AuthenticationMode.SESSION,
    }
    defaults.update(overrides)
    return ServiceSettings.model_validate(defaults)


class _FakeSession:
    """An in-memory double wide enough for one login/logout/session round trip."""

    def __init__(self) -> None:
        subject_id = uuid4()
        self.account_id = uuid4()
        self.subject = Subject(id=subject_id, subject_name="user:operator", subject_type="user", is_active=True)
        self.account = UserAccount(
            id=self.account_id,
            subject_id=subject_id,
            username="operator",
            password_hash=hash_password("correct horse battery staple"),
            role="reviewer",
            display_name="Operator",
        )
        self.sessions: dict[object, UserSession] = {}

    def begin(self):  # noqa: ANN201 - test double
        from contextlib import nullcontext

        return nullcontext()

    def scalar(self, statement: object) -> object:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is UserAccount:
            return self.account
        return None

    def get(self, model: object, ident: object) -> object:
        if model is UserSession:
            return self.sessions.get(ident)
        if model is UserAccount:
            return self.account if ident == self.account_id else None
        if model is Subject:
            return self.subject
        return None

    def add(self, instance: object) -> None:
        if isinstance(instance, UserSession):
            if instance.id is None:
                instance.id = uuid4()
            self.sessions[instance.id] = instance

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.unit
def test_login_sets_an_httponly_cookie_and_returns_the_session_user() -> None:
    app = create_app(_session_settings())
    fake = _FakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "correct horse battery staple"}
        )

    assert response.status_code == 200
    assert response.json() == {"username": "operator", "display_name": "Operator", "role": "reviewer"}
    assert "selene_session" in response.cookies
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie.lower()


@pytest.mark.unit
def test_login_rejects_wrong_credentials_with_401() -> None:
    app = create_app(_session_settings())
    app.dependency_overrides[get_db_session] = lambda: _FakeSession()

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username": "operator", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.unit
def test_session_endpoint_requires_a_valid_cookie() -> None:
    app = create_app(_session_settings())
    app.dependency_overrides[get_db_session] = lambda: _FakeSession()

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/session")

    assert response.status_code == 401


@pytest.mark.unit
def test_auth_routes_are_not_mounted_outside_session_mode() -> None:
    app = create_app(
        ServiceSettings.model_validate({"bind_host": "127.0.0.1", "authentication_mode": "unauthenticated"})
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/session")

    assert response.status_code == 404


@pytest.mark.unit
def test_login_then_session_round_trip_with_the_returned_cookie() -> None:
    app = create_app(_session_settings())
    fake = _FakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "correct horse battery staple"}
        )
        session_response = client.get("/api/v1/auth/session")
        logout = client.post("/api/v1/auth/logout")
        after_logout = client.get("/api/v1/auth/session")

    assert login.status_code == 200
    assert session_response.status_code == 200
    assert session_response.json()["username"] == "operator"
    assert logout.status_code == 204
    assert after_logout.status_code == 401
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_auth_routes.py -v`
Expected: FAIL — none of the auth routes/schemas/services exist yet.

- [ ] **Step 3: Add the schemas**

In `packages/selene_service/src/selene_service/api/schemas.py`, add near the end of the file:

```python
class LoginRequest(BaseModel):
    """Operator-supplied login credentials."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class SessionUserResponse(BaseModel):
    """The logged-in operator's public identity — never the password hash."""

    model_config = ConfigDict(frozen=True)

    username: str
    display_name: str
    role: Literal["analyst", "reviewer", "admin"]
```

- [ ] **Step 4: Write `auth_services.py`**

```python
"""Business logic for login, logout, and session hydration."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from selene_service.api.dependencies import SubjectIdentity
from selene_service.api.errors import APIProblem
from selene_service.api.schemas import LoginRequest, SessionUserResponse
from selene_service.api.session_auth import authenticate_with_password, create_session, revoke_session
from selene_service.persistence.models import UserAccount
from selene_service.settings import ServiceSettings


def login(session: Session, request: LoginRequest, settings: ServiceSettings) -> tuple[SessionUserResponse, UUID]:
    """Authenticate and return the public session-user view plus a new session id."""

    with session.begin():
        account = authenticate_with_password(session, request.username, request.password, settings)
        session_row = create_session(session, account, settings)
        session.flush()
        session_id = session_row.id
    return _session_user_response(account), session_id


def current_session_user(identity: SubjectIdentity) -> SessionUserResponse:
    """Return the caller's session identity, or 401 if this isn't a session caller."""

    if identity.role is None or identity.user_account_id is None:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    return SessionUserResponse(
        username=identity.subject_name.removeprefix("user:"),
        display_name=identity.subject_name.removeprefix("user:"),
        role=identity.role,  # type: ignore[arg-type]
    )


def logout(session: Session, session_id: UUID) -> None:
    """Revoke the caller's current session."""

    with session.begin():
        revoke_session(session, session_id)


def _session_user_response(account: UserAccount) -> SessionUserResponse:
    return SessionUserResponse(
        username=account.username,
        display_name=account.display_name,
        role=account.role,  # type: ignore[arg-type]
    )
```

`current_session_user` reconstructs `display_name` from `subject_name` as a placeholder — fix this in Step 4a below once you notice the `SessionUserResponse` returned by `GET /auth/session` needs the *real* `display_name`, not a derived one.

- [ ] **Step 4a: Fix `current_session_user` to fetch the real display name**

`SubjectIdentity` doesn't carry `display_name` (Task 5 deliberately kept it minimal). Rather than growing `SubjectIdentity` further, have the route load the account row directly. Replace `current_session_user` with a version that takes the DB session too:

```python
def current_session_user(session: Session, identity: SubjectIdentity) -> SessionUserResponse:
    """Return the caller's session identity, or 401 if this isn't a session caller."""

    if identity.role is None or identity.user_account_id is None:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    account = session.get(UserAccount, identity.user_account_id)
    if account is None:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    return _session_user_response(account)
```

- [ ] **Step 5: Write `auth_routes.py`**

```python
"""Session-mode-only HTTP routes for login, logout, and session hydration.

Mounted by ``app.py`` only when ``authentication_mode is AuthenticationMode.SESSION``
— every other mode leaves these paths returning FastAPI's normal 404, which
the web console's session hook uses to tell "auth isn't configured here"
apart from "you're not logged in" (401).
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from selene_service.api import auth_services
from selene_service.api.dependencies import CurrentIdentity, DatabaseSession
from selene_service.api.errors import APIProblem
from selene_service.api.schemas import LoginRequest, SessionUserResponse
from selene_service.settings import ServiceSettings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def build_auth_router(settings: ServiceSettings) -> APIRouter:
    """Return the auth router bound to *settings* for cookie configuration."""

    @router.post("/login", response_model=SessionUserResponse, operation_id="login")
    def login_route(
        request: LoginRequest,
        session: DatabaseSession,
        response: Response,
    ) -> SessionUserResponse:
        """Authenticate and set the httpOnly session cookie."""

        session_user, session_id = auth_services.login(session, request, settings)
        response.set_cookie(
            key=settings.session_cookie_name,
            value=str(session_id),
            httponly=True,
            samesite="strict",
            secure=settings.environment.value == "production",
            max_age=settings.session_ttl_seconds,
            path="/",
        )
        return session_user

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logout")
    def logout_route(session: DatabaseSession, response: Response) -> None:
        """Revoke the current session cookie, if any, and clear it client-side."""

        # Logout is reached via the same identity dependency as any other
        # session-gated route would be, but logout must also succeed for a
        # caller whose cookie has already expired — so it reads the raw
        # cookie value directly rather than depending on CurrentIdentity,
        # which would 401 first and prevent clearing a stale cookie.
        response.delete_cookie(key=settings.session_cookie_name, path="/")

    @router.get("/session", response_model=SessionUserResponse, operation_id="get_session")
    def session_route(session: DatabaseSession, identity: CurrentIdentity) -> SessionUserResponse:
        """Hydrate the caller's own session identity."""

        return auth_services.current_session_user(session, identity)

    return router
```

The `logout_route` above doesn't actually call `auth_services.logout` yet — fix this in Step 5a.

- [ ] **Step 5a: Fix `logout_route` to actually revoke the session**

`Response.delete_cookie` alone only clears the browser's copy; the server-side `UserSession` row must be revoked too, or a copied cookie value stays valid until it expires. Replace `logout_route` with:

```python
    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="logout")
    def logout_route(request: Request, session: DatabaseSession, response: Response) -> None:
        """Revoke the current session (if any) and clear the cookie."""

        cookie_value = request.cookies.get(settings.session_cookie_name)
        if cookie_value:
            try:
                auth_services.logout(session, UUID(cookie_value))
            except ValueError:
                pass
        response.delete_cookie(key=settings.session_cookie_name, path="/")
```

Add the now-needed imports at the top of the file: `from uuid import UUID` and `from fastapi import Request` (alongside the existing `APIRouter, Response, status` import).

- [ ] **Step 6: Wire the router into `app.py`**

In `packages/selene_service/src/selene_service/app.py`, add the import:

```python
from selene_service.api.auth_routes import build_auth_router
from selene_service.settings import AuthenticationMode, ServiceEnvironment, ServiceSettings
```

(extending the existing `from selene_service.settings import ...` line with `AuthenticationMode`), and after the existing `app.include_router(v1_router)` line, add:

```python
    if configured_settings.authentication_mode is AuthenticationMode.SESSION:
        app.include_router(build_auth_router(configured_settings))
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_auth_routes.py -v`
Expected: PASS (all cases).

- [ ] **Step 8: Run the full existing app test suite to confirm no regression**

Run: `uv run pytest tests/unit/test_service_app.py tests/unit/test_local_api_auth.py tests/unit/test_service_persisted_api.py -v`
Expected: PASS, unchanged.

- [ ] **Step 9: Add the real-Postgres HTTP round-trip integration test**

Task 6 through here only exercises login/logout/session against an in-memory fake session double. ADR-0016's Verification section specifically calls for one integration test, against a real database, of the full `login → session cookie → authenticated request → logout → cookie rejected` path — the fake double can't prove the cookie and the `user_sessions` row actually agree with each other. Add `tests/integration/test_session_authentication.py`, mirroring `tests/integration/test_postgres_persistence.py`'s skip-if-unset + `alembic upgrade head` + real engine pattern exactly (read that file first for the precise fixture/skip code to copy):

```python
"""Opt-in real PostgreSQL verification of the login/session HTTP round trip."""

from __future__ import annotations

from fastapi.testclient import TestClient

from selene_service.app import create_app
from selene_service.settings import AuthenticationMode, ServiceSettings

# Reuse this file's real-Postgres setup exactly as test_postgres_persistence.py
# does: the same skip-if-SELENE_SERVICE_TEST_DATABASE_URL-unset guard, the
# same `alembic.command.upgrade(Config(...), "head")` call, and the same
# `create_service_engine`/session-factory construction. Do not re-derive a
# different connection pattern here.

pytestmark = pytest.mark.integration


def test_login_then_authenticated_request_then_logout_round_trip(
    session_factory,  # the real, migrated session factory this file's setup provides
) -> None:
    settings = ServiceSettings.model_validate(
        {
            "bind_host": "127.0.0.1",
            "authentication_mode": AuthenticationMode.SESSION,
            "bootstrap_admin_username": "integration-admin",
            "bootstrap_admin_password": "an-actually-strong-bootstrap-password",
        }
    )
    app = create_app(settings)
    app.state.session_factory = session_factory

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "integration-admin", "password": "an-actually-strong-bootstrap-password"},
        )
        assert login.status_code == 200

        session_response = client.get("/api/v1/auth/session")
        assert session_response.status_code == 200
        assert session_response.json()["role"] == "admin"

        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 204

        after_logout = client.get("/api/v1/auth/session")
        assert after_logout.status_code == 401
```

Add `import pytest` at the top alongside the other imports. The `session_factory` fixture argument is a placeholder name — replace it with whatever this file's copied setup actually calls its real, migrated session factory (check the exact fixture/helper name in `test_postgres_persistence.py` and use that, not an invented one). The important part FastAPI-side: `create_app(settings)` runs its own `lifespan` bootstrap (which will call `bootstrap_admin_user` once `AuthenticationMode.SESSION` is wired into the lifespan hook — see Step 9a below, which this test depends on).

- [ ] **Step 9a: Wire `bootstrap_admin_user` into the app lifespan**

Task 4 wrote `bootstrap_admin_user` but nothing calls it yet — `bootstrap_local_api_key` is the only bootstrap function currently invoked from `create_app`'s `lifespan`. In `packages/selene_service/src/selene_service/app.py`, add the import `from selene_service.api.session_auth import bootstrap_admin_user` and, inside the `lifespan` function, call it alongside the existing bootstrap:

```python
        try:
            bootstrap_local_api_key(application.state.session_factory, configured_settings)
            bootstrap_admin_user(application.state.session_factory, configured_settings)
            yield
```

Without this, `SELENE_SERVICE_BOOTSTRAP_ADMIN_USERNAME`/`_PASSWORD` would be read into settings (Task 3) but never actually create an account — the Step 9 integration test above is what catches that gap.

- [ ] **Step 9b: Run the integration test**

Run: `SELENE_SERVICE_TEST_DATABASE_URL=<your test db url> uv run pytest tests/integration/test_session_authentication.py -v` (or confirm it skips cleanly if unset, same as the rest of the integration suite).
Expected: PASS if a test database is configured in this environment; otherwise note in your task report that this test is unverified pending a database and must be run before merge.

- [ ] **Step 10: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/api/schemas.py packages/selene_service/src/selene_service/api/auth_services.py packages/selene_service/src/selene_service/api/auth_routes.py packages/selene_service/src/selene_service/app.py` and `uv run ruff check packages/selene_service/src/selene_service/api/schemas.py packages/selene_service/src/selene_service/api/auth_services.py packages/selene_service/src/selene_service/api/auth_routes.py packages/selene_service/src/selene_service/app.py tests/unit/test_auth_routes.py tests/integration/test_session_authentication.py`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add packages/selene_service/src/selene_service/api/schemas.py packages/selene_service/src/selene_service/api/auth_services.py packages/selene_service/src/selene_service/api/auth_routes.py packages/selene_service/src/selene_service/app.py tests/unit/test_auth_routes.py tests/integration/test_session_authentication.py
git commit -m "feat(service): add login, logout, and session HTTP routes"
```

---

## Task 7: Admin user management

**Files:**
- Modify: `packages/selene_service/src/selene_service/api/schemas.py`
- Modify: `packages/selene_service/src/selene_service/api/auth_services.py`
- Modify: `packages/selene_service/src/selene_service/api/auth_routes.py`
- Test: `tests/unit/test_auth_admin_routes.py`

**Interfaces:**
- Consumes: `hash_password` (Task 1), `CurrentIdentity` (Task 5).
- Produces: `POST /api/v1/auth/users` (create, admin-only), `GET /api/v1/auth/users` (list, admin-only), `PATCH /api/v1/auth/users/{id}` (update role/active/reset password, admin-only, and forbids `id == identity.user_account_id` — no self-role-change per ADR-0016). Schemas `UserAccountCreateRequest`, `UserAccountResponse`, `UserAccountUpdateRequest`. Consumed by Task 14 (Admin Users screen).

- [ ] **Step 1: Write the failing test**

```python
"""Contracts for admin-only operator account management."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from selene_service.api.dependencies import get_db_session
from selene_service.api.password_auth import hash_password
from selene_service.app import create_app
from selene_service.persistence.models import Subject, UserAccount, UserSession
from selene_service.settings import AuthenticationMode, ServiceSettings


def _session_settings(**overrides: object) -> ServiceSettings:
    """Local copy of Task 6's helper — test files in this codebase are
    self-contained (see the independent `_BootstrapSession`/`_CredentialSession`
    doubles already in tests/unit/test_local_api_auth.py); this file does not
    import from tests/unit/test_auth_routes.py."""

    defaults: dict[str, object] = {
        "bind_host": "127.0.0.1",
        "authentication_mode": AuthenticationMode.SESSION,
    }
    defaults.update(overrides)
    return ServiceSettings.model_validate(defaults)


class _AdminFakeSession:
    """An in-memory double for one login + admin user-management round trip."""

    def __init__(self) -> None:
        subject_id = uuid4()
        self.account_id = uuid4()
        self.subject = Subject(id=subject_id, subject_name="user:operator", subject_type="user", is_active=True)
        self.account = UserAccount(
            id=self.account_id,
            subject_id=subject_id,
            username="operator",
            password_hash=hash_password("correct horse battery staple"),
            role="admin",
            display_name="Operator",
        )
        self.sessions: dict[object, UserSession] = {}
        self.created: list[UserAccount] = []

    def begin(self):  # noqa: ANN201 - test double
        from contextlib import nullcontext

        return nullcontext()

    def scalar(self, statement: object) -> object:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is UserAccount:
            return self.account
        return None

    def get(self, model: object, ident: object) -> object:
        if model is UserSession:
            return self.sessions.get(ident)
        if model is UserAccount:
            return self.account if ident == self.account_id else None
        if model is Subject:
            return self.subject
        return None

    def add(self, instance: object) -> None:
        if isinstance(instance, UserSession):
            if instance.id is None:
                instance.id = uuid4()
            self.sessions[instance.id] = instance
        if isinstance(instance, UserAccount):
            if instance.id is None:
                instance.id = uuid4()
            self.created.append(instance)
        if isinstance(instance, Subject) and instance.id is None:
            instance.id = uuid4()

    def flush(self) -> None:
        return None

    def refresh(self, instance: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeSession(_AdminFakeSession):
    """The non-admin variant used by the non-admin-cannot-create-a-user case."""

    def __init__(self) -> None:
        super().__init__()
        self.account.role = "reviewer"


@pytest.mark.unit
def test_non_admin_cannot_create_a_user() -> None:
    app = create_app(_session_settings())
    fake = _FakeSession()  # role="reviewer" by default
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "correct horse battery staple"}
        )
        response = client.post(
            "/api/v1/auth/users",
            json={"username": "new.analyst", "password": "another-strong-password", "role": "analyst", "display_name": "New Analyst"},
        )

    assert login.status_code == 200
    assert response.status_code == 403


@pytest.mark.unit
def test_admin_can_create_a_user_and_the_password_is_hashed() -> None:
    app = create_app(_session_settings())
    fake = _AdminFakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "correct horse battery staple"}
        )
        response = client.post(
            "/api/v1/auth/users",
            json={"username": "new.analyst", "password": "another-strong-password", "role": "analyst", "display_name": "New Analyst"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body == {"username": "new.analyst", "display_name": "New Analyst", "role": "analyst", "is_active": True}
    assert fake.created[-1].password_hash != "another-strong-password"


@pytest.mark.unit
def test_admin_cannot_change_their_own_role() -> None:
    app = create_app(_session_settings())
    fake = _AdminFakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "correct horse battery staple"}
        )
        response = client.patch(f"/api/v1/auth/users/{fake.account_id}", json={"role": "analyst"})

    assert response.status_code == 403
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_auth_admin_routes.py -v`
Expected: FAIL — the user-management endpoints and schemas don't exist yet.

- [ ] **Step 3: Add the schemas**

In `packages/selene_service/src/selene_service/api/schemas.py`, add after `SessionUserResponse`:

```python
class UserAccountCreateRequest(BaseModel):
    """Admin-supplied definition of a new operator account."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=512)
    role: Literal["analyst", "reviewer", "admin"]
    display_name: str = Field(min_length=1, max_length=255)


class UserAccountResponse(BaseModel):
    """Public operator-account view — never the password hash."""

    model_config = ConfigDict(frozen=True)

    username: str
    display_name: str
    role: Literal["analyst", "reviewer", "admin"]
    is_active: bool


class UserAccountPageResponse(BaseModel):
    """The full operator-account roster — small enough to never need paging."""

    model_config = ConfigDict(frozen=True)

    items: list[UserAccountResponse]


class UserAccountUpdateRequest(BaseModel):
    """Partial admin update to another account's role, activity, or password."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["analyst", "reviewer", "admin"] | None = None
    is_active: bool | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=512)
```

- [ ] **Step 4: Add the service functions**

Append to `packages/selene_service/src/selene_service/api/auth_services.py`:

```python
from uuid import UUID

from sqlalchemy import select

from selene_service.api.errors import BadRequestProblem, NotFoundProblem
from selene_service.api.password_auth import hash_password
from selene_service.api.schemas import (
    UserAccountCreateRequest,
    UserAccountPageResponse,
    UserAccountResponse,
    UserAccountUpdateRequest,
)
from selene_service.persistence.models import Subject


def _require_admin(identity: SubjectIdentity) -> None:
    if identity.role != "admin":
        raise APIProblem(403, "forbidden", "The request is not permitted.")


def create_user_account(
    session: Session, identity: SubjectIdentity, request: UserAccountCreateRequest
) -> UserAccountResponse:
    """Create a new operator account; Admin-only, never self-service."""

    _require_admin(identity)
    with session.begin():
        normalized = request.username.strip().casefold()
        existing = session.scalar(select(UserAccount).where(UserAccount.username == normalized))
        if existing is not None:
            raise BadRequestProblem("That username is already taken.")
        subject = Subject(subject_name=f"user:{normalized}", subject_type="user", is_active=True)
        session.add(subject)
        session.flush()
        account = UserAccount(
            subject_id=subject.id,
            username=normalized,
            password_hash=hash_password(request.password),
            role=request.role,
            display_name=request.display_name,
            created_by_user_account_id=identity.user_account_id,
        )
        session.add(account)
        session.flush()
        session.refresh(account)
        return _account_response(account)


def list_user_accounts(session: Session, identity: SubjectIdentity) -> UserAccountPageResponse:
    """List every operator account; Admin-only."""

    _require_admin(identity)
    accounts = session.scalars(select(UserAccount).order_by(UserAccount.username)).all()
    return UserAccountPageResponse(items=[_account_response(account) for account in accounts])


def update_user_account(
    session: Session,
    identity: SubjectIdentity,
    target_account_id: UUID,
    request: UserAccountUpdateRequest,
) -> UserAccountResponse:
    """Update another account's role, activity, or password; Admin-only.

    Never permits an Admin to change their own role or active state — a
    role change always targets a different account (ADR-0016 Alternatives
    considered: no endpoint lets a session change its own role).
    """

    _require_admin(identity)
    if target_account_id == identity.user_account_id:
        raise APIProblem(403, "forbidden", "An account cannot change its own role.")
    with session.begin():
        account = session.get(UserAccount, target_account_id)
        if account is None:
            raise NotFoundProblem("No such operator account.")
        if request.role is not None:
            account.role = request.role
        if request.is_active is not None:
            account.is_active = request.is_active
        if request.new_password is not None:
            account.password_hash = hash_password(request.new_password)
        session.add(account)
        session.flush()
        session.refresh(account)
        return _account_response(account)


def _account_response(account: UserAccount) -> UserAccountResponse:
    return UserAccountResponse(
        username=account.username,
        display_name=account.display_name,
        role=account.role,  # type: ignore[arg-type]
        is_active=account.is_active,
    )
```

- [ ] **Step 5: Add the routes**

In `packages/selene_service/src/selene_service/api/auth_routes.py`, add the import of the new schemas/services and, inside `build_auth_router`, add three more route functions before `return router`:

```python
    @router.post(
        "/users",
        response_model=UserAccountResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="create_user_account",
    )
    def create_user_route(
        request: UserAccountCreateRequest, session: DatabaseSession, identity: CurrentIdentity
    ) -> UserAccountResponse:
        """Admin-only: provision a new operator account."""

        return auth_services.create_user_account(session, identity, request)

    @router.get("/users", response_model=UserAccountPageResponse, operation_id="list_user_accounts")
    def list_users_route(session: DatabaseSession, identity: CurrentIdentity) -> UserAccountPageResponse:
        """Admin-only: list every operator account."""

        return auth_services.list_user_accounts(session, identity)

    @router.patch(
        "/users/{user_account_id}",
        response_model=UserAccountResponse,
        operation_id="update_user_account",
    )
    def update_user_route(
        user_account_id: UUID,
        request: UserAccountUpdateRequest,
        session: DatabaseSession,
        identity: CurrentIdentity,
    ) -> UserAccountResponse:
        """Admin-only: change another account's role, activity, or password."""

        return auth_services.update_user_account(session, identity, user_account_id, request)
```

Update the top-of-file imports accordingly:

```python
from selene_service.api.schemas import (
    LoginRequest,
    SessionUserResponse,
    UserAccountCreateRequest,
    UserAccountPageResponse,
    UserAccountResponse,
    UserAccountUpdateRequest,
)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_auth_admin_routes.py -v`
Expected: PASS (all 3 cases). If `test_admin_can_create_a_user_and_the_password_is_hashed` fails because `_AdminFakeSession.execute` needs to also handle the `Subject` unique-check select used elsewhere, adjust the fake session's `scalar`/`execute` to return `None` for the username-existence check (no pre-existing account) — the fake should stay a minimal double, not a real query engine.

- [ ] **Step 7: Run the full auth test suite to confirm no regression**

Run: `uv run pytest tests/unit/test_auth_routes.py tests/unit/test_auth_admin_routes.py tests/unit/test_session_auth_dependency.py -v`
Expected: PASS, unchanged.

- [ ] **Step 8: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/api/schemas.py packages/selene_service/src/selene_service/api/auth_services.py packages/selene_service/src/selene_service/api/auth_routes.py` and `uv run ruff check packages/selene_service/src/selene_service/api/schemas.py packages/selene_service/src/selene_service/api/auth_services.py packages/selene_service/src/selene_service/api/auth_routes.py tests/unit/test_auth_admin_routes.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add packages/selene_service/src/selene_service/api/schemas.py packages/selene_service/src/selene_service/api/auth_services.py packages/selene_service/src/selene_service/api/auth_routes.py tests/unit/test_auth_admin_routes.py
git commit -m "feat(service): add admin-only operator account management"
```

---

## Task 8: Role-gate `submit_review`

**Files:**
- Modify: `packages/selene_service/src/selene_service/api/services.py`
- Test: `tests/unit/test_service_persisted_api.py` (extend existing review tests)

**Interfaces:**
- Consumes: `identity.role` (Task 5), already-injected `CurrentIdentity` in `submit_review`.
- Produces: `submit_review` raises `APIProblem(403, "forbidden", ...)` when `identity.role is not None and identity.role not in ("reviewer", "admin")`. Callers with `identity.role is None` (API-key/loopback, no session) are unaffected — this only gates human session callers, per the plan's Global Constraints discussion of ADR-0016.

- [ ] **Step 1: Find the existing review submission tests to extend**

Run: `grep -n "def test.*review\|submit_review" tests/unit/test_service_persisted_api.py`

Read the surrounding 30-40 lines around the first match to see the exact fixture/session-double pattern already used for `submit_review` in that file (it will look like the `_FakeSession`/`_MemorySession` style from `test_local_api_auth.py`, but scoped to runs/reviews) and reuse it — do not invent a new fixture.

- [ ] **Step 2: Write the failing test**

Add to `tests/unit/test_service_persisted_api.py`, next to the existing review tests, using whatever identity/session fixtures that file already exposes for `submit_review` (adapt `identity=` construction to match; the shape below is the contract to hit regardless of the exact local fixture names):

```python
@pytest.mark.unit
def test_submit_review_rejects_a_session_caller_without_reviewer_or_admin_role() -> None:
    identity = SubjectIdentity(subject_name="user:analyst.one", subject_type="user", role="analyst", user_account_id=uuid4())

    with pytest.raises(APIProblem) as problem:
        submit_review(<session-fixture-from-this-file>, identity, <existing-run-id-fixture>, <existing-review-request-fixture>)

    assert problem.value.status_code == 403


@pytest.mark.unit
def test_submit_review_allows_a_session_caller_with_reviewer_role() -> None:
    identity = SubjectIdentity(subject_name="user:reviewer.one", subject_type="user", role="reviewer", user_account_id=uuid4())

    # This should proceed to the file's existing success path, not raise.
    submit_review(<session-fixture-from-this-file>, identity, <existing-run-id-fixture>, <existing-review-request-fixture>)
```

Replace the `<...>` placeholders with the file's real fixtures/helpers before running — they exist already; this task only adds the role check, not new run/review fixtures.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_service_persisted_api.py -k role -v`
Expected: FAIL — `submit_review` doesn't check role yet, so the analyst case does not raise 403.

- [ ] **Step 4: Add the role check**

In `packages/selene_service/src/selene_service/api/services.py`, inside `submit_review`, immediately after the `with session.begin():` line and before `subject = _resolve_subject(session, identity)`, add:

```python
        if identity.role is not None and identity.role not in ("reviewer", "admin"):
            raise APIProblem(403, "forbidden", "The request is not permitted.")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_service_persisted_api.py -v`
Expected: PASS, including every pre-existing test in this file (no regressions to the API-key/loopback path, where `identity.role` stays `None`).

- [ ] **Step 6: Type-check and lint**

Run: `uv run mypy packages/selene_service/src/selene_service/api/services.py` and `uv run ruff check packages/selene_service/src/selene_service/api/services.py tests/unit/test_service_persisted_api.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add packages/selene_service/src/selene_service/api/services.py tests/unit/test_service_persisted_api.py
git commit -m "feat(service): require Reviewer or Admin role to submit a review"
```

---

## Task 9: Frontend API contracts and `authRepository`

**Files:**
- Modify: `web/src/services/api/contracts.ts`
- Create: `web/src/repositories/authRepository.ts`
- Test: `web/src/repositories/authRepository.test.ts`

**Interfaces:**
- Produces: `ApiSessionUser` and `ApiUserAccount` types in `contracts.ts`; `authRepository.login(username, password)`, `.logout()`, `.getSession()`, `.listUsers()`, `.createUser(...)`, `.updateUser(id, ...)` in `authRepository.ts`. Consumed by Task 10 (hooks).

- [ ] **Step 1: Add the API contracts**

Append to `web/src/services/api/contracts.ts`:

```typescript
export interface ApiSessionUser {
  username: string
  display_name: string
  role: 'analyst' | 'reviewer' | 'admin'
}

export interface ApiUserAccount {
  username: string
  display_name: string
  role: 'analyst' | 'reviewer' | 'admin'
  is_active: boolean
}

export interface ApiUserAccountPage {
  items: ApiUserAccount[]
}
```

- [ ] **Step 2: Write the failing test**

```typescript
import { afterEach, describe, expect, it, vi } from 'vitest'
import { authRepository } from './authRepository'

afterEach(() => vi.unstubAllGlobals())

describe('authRepository', () => {
  it('posts credentials to login and returns the session user', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ username: 'operator', display_name: 'Operator', role: 'reviewer' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const user = await authRepository.login('operator', 'a-password')

    expect(user).toEqual({ username: 'operator', displayName: 'Operator', role: 'reviewer' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/auth/login')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ username: 'operator', password: 'a-password' })
  })

  it('treats a 404 session response as auth not being configured', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 404 })))

    await expect(authRepository.getSession()).rejects.toMatchObject({ status: 404 })
  })

  it('treats a 401 session response as not logged in', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'Authentication is required.' } }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(authRepository.getSession()).rejects.toMatchObject({ status: 401 })
  })

  it('lists users and maps the roster', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ items: [{ username: 'a', display_name: 'A', role: 'admin', is_active: true }] }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const page = await authRepository.listUsers()

    expect(page).toEqual([{ username: 'a', displayName: 'A', role: 'admin', isActive: true }])
  })
})
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && ./node_modules/.bin/vitest run src/repositories/authRepository.test.ts`
Expected: FAIL — `authRepository.ts` does not exist yet.

- [ ] **Step 4: Write the implementation**

```typescript
import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiSessionUser, ApiUserAccount, ApiUserAccountPage } from '@/services/api/contracts'

export interface SessionUser {
  username: string
  displayName: string
  role: 'analyst' | 'reviewer' | 'admin'
}

export interface UserAccount {
  username: string
  displayName: string
  role: 'analyst' | 'reviewer' | 'admin'
  isActive: boolean
}

export interface CreateUserAccountInput {
  username: string
  password: string
  role: 'analyst' | 'reviewer' | 'admin'
  displayName: string
}

export interface UpdateUserAccountInput {
  role?: 'analyst' | 'reviewer' | 'admin'
  isActive?: boolean
  newPassword?: string
}

function sessionUserFromApi(user: ApiSessionUser): SessionUser {
  return { username: user.username, displayName: user.display_name, role: user.role }
}

function userAccountFromApi(account: ApiUserAccount): UserAccount {
  return {
    username: account.username,
    displayName: account.display_name,
    role: account.role,
    isActive: account.is_active,
  }
}

export const authRepository = {
  async login(username: string, password: string, options?: ApiRequestOptions): Promise<SessionUser> {
    return sessionUserFromApi(
      await seleneApi.post<ApiSessionUser, { username: string; password: string }>(
        'auth/login',
        { username, password },
        options,
      ),
    )
  },

  async logout(options?: ApiRequestOptions): Promise<void> {
    await seleneApi.post<void, Record<string, never>>('auth/logout', {}, options)
  },

  async getSession(options?: ApiRequestOptions): Promise<SessionUser> {
    return sessionUserFromApi(await seleneApi.get<ApiSessionUser>('auth/session', options))
  },

  async listUsers(options?: ApiRequestOptions): Promise<UserAccount[]> {
    const page = await seleneApi.get<ApiUserAccountPage>('auth/users', options)
    return page.items.map(userAccountFromApi)
  },

  async createUser(input: CreateUserAccountInput, options?: ApiRequestOptions): Promise<UserAccount> {
    return userAccountFromApi(
      await seleneApi.post<ApiUserAccount, { username: string; password: string; role: string; display_name: string }>(
        'auth/users',
        { username: input.username, password: input.password, role: input.role, display_name: input.displayName },
        options,
      ),
    )
  },
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && ./node_modules/.bin/vitest run src/repositories/authRepository.test.ts`
Expected: PASS (4/4).

- [ ] **Step 6: Type-check and lint**

Run: `cd web && ./node_modules/.bin/tsc -b --noEmit && ./node_modules/.bin/oxlint src/services/api/contracts.ts src/repositories/authRepository.ts src/repositories/authRepository.test.ts`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add web/src/services/api/contracts.ts web/src/repositories/authRepository.ts web/src/repositories/authRepository.test.ts
git commit -m "feat(web): add auth API contracts and repository"
```

---

## Task 10: `useSession`, `useLogin`, `useLogout` hooks

**Files:**
- Create: `web/src/features/auth/useSession.ts`
- Create: `web/src/features/auth/useLogin.ts`
- Create: `web/src/features/auth/useLogout.ts`
- Test: `web/src/features/auth/useSession.test.ts`

**Interfaces:**
- Consumes: `authRepository` (Task 9).
- Produces: `useSession()` returns a TanStack Query result over `authRepository.getSession()`; `useSession().data` is `SessionUser | undefined`. `isAuthConfigured(query)` helper distinguishes a 404 (auth not configured for this deployment — treat as "no gate") from a 401 (not logged in — redirect) from success. `useLogin()`/`useLogout()` are mutations that invalidate the `['session']` query on success. Consumed by Task 11 (route guard, login page), Task 12 (TopBar badge), Task 13 (review gating), Task 14 (admin users screen).

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, expect, it, vi, afterEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { isSeleneApiError } from '@/services/api/client'
import { authRepository } from '@/repositories/authRepository'
import { authConfigurationState, useSession } from './useSession'

afterEach(() => vi.restoreAllMocks())

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useSession', () => {
  it('resolves the session user on success', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'a', displayName: 'A', role: 'admin' })

    const { result } = renderHook(() => useSession(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({ username: 'a', displayName: 'A', role: 'admin' })
  })

  it('classifies a 404 error as auth-not-configured', async () => {
    const error = Object.assign(new Error('not found'), { status: 404, code: 'HTTP_404' })
    Object.setPrototypeOf(error, Object.getPrototypeOf(await import('@/services/api/client').then((m) => new m.SeleneApiError({ code: 'x', message: 'x', status: 404 }))))

    expect(authConfigurationState({ status: 404 } as ReturnType<typeof isSeleneApiError> extends never ? never : any)).toBe('not-configured')
    expect(authConfigurationState({ status: 401 } as any)).toBe('unauthenticated')
    expect(authConfigurationState(undefined)).toBe('unknown')
  })
})
```

Note: the second test above is written slightly awkwardly to avoid depending on `SeleneApiError`'s constructor shape beyond `{status}`. Simplify it once you're implementing — the essential contract is:
`authConfigurationState(error: unknown): 'not-configured' | 'unauthenticated' | 'unknown'` where a `SeleneApiError` with `status === 404` maps to `'not-configured'`, `status === 401` maps to `'unauthenticated'`, anything else (including no error) maps to `'unknown'`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && ./node_modules/.bin/vitest run src/features/auth/useSession.test.ts`
Expected: FAIL — `useSession.ts` does not exist yet.

- [ ] **Step 3: Write `useSession.ts`**

```typescript
import { useQuery } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import { isSeleneApiError } from '@/services/api/client'

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: ({ signal }) => authRepository.getSession({ signal }),
    retry: false,
    staleTime: 60_000,
  })
}

/**
 * A 404 means this deployment never mounted the auth routes at all (it is
 * running in UNAUTHENTICATED or EXTERNAL mode) — there is nothing to gate.
 * A 401 means auth *is* configured and this caller simply isn't logged in.
 * Anything else is not yet known (still loading, or an unrelated failure).
 */
export function authConfigurationState(error: unknown): 'not-configured' | 'unauthenticated' | 'unknown' {
  if (isSeleneApiError(error)) {
    if (error.status === 404) return 'not-configured'
    if (error.status === 401) return 'unauthenticated'
  }
  return 'unknown'
}
```

- [ ] **Step 4: Write `useLogin.ts` and `useLogout.ts`**

```typescript
// useLogin.ts
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authRepository.login(username, password),
    onSuccess: (user) => {
      queryClient.setQueryData(['session'], user)
    },
  })
}
```

```typescript
// useLogout.ts
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => authRepository.logout(),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['session'] })
    },
  })
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && ./node_modules/.bin/vitest run src/features/auth/useSession.test.ts`
Expected: PASS. If the awkward second test case from Step 1 is hard to get green as written, rewrite it more simply — it only needs to prove `authConfigurationState` maps `{status: 404}`-shaped `SeleneApiError` instances correctly; feel free to construct real `SeleneApiError` instances via `new SeleneApiError({code: 'x', message: 'x', status: 404})` imported directly, which is simpler than the placeholder above.

- [ ] **Step 6: Type-check and lint**

Run: `cd web && ./node_modules/.bin/tsc -b --noEmit && ./node_modules/.bin/oxlint src/features/auth/`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/auth/
git commit -m "feat(web): add session, login, and logout hooks"
```

---

## Task 11: Login page, router wiring, and session gate

**Files:**
- Create: `web/src/routes/login/LoginRoute.tsx`
- Modify: `web/src/app/router.tsx`
- Modify: `web/src/components/shell/AppShell.tsx`
- Test: `web/src/routes/login/LoginRoute.test.tsx`

**Interfaces:**
- Consumes: `useLogin` (Task 10), `useSession`/`authConfigurationState` (Task 10).
- Produces: `/login` route (sibling of the `AppShell`-wrapped tree, so it renders without `TopBar`/`SideNavigation`); `AppShell` redirects to `/login` when `authConfigurationState(sessionQuery.error) === 'unauthenticated'`, renders normally (no gate) when `'not-configured'`, and shows a full-page loading state while the session query is still pending.

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import { LoginRoute } from './LoginRoute'

function renderLoginRoute() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/login']}>
        <LoginRoute />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginRoute', () => {
  it('submits the entered username and password', async () => {
    const loginSpy = vi.spyOn(authRepository, 'login').mockResolvedValue({ username: 'a', displayName: 'A', role: 'admin' })
    renderLoginRoute()

    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-password' } })
    fireEvent.click(screen.getByRole('button', { name: /log in/i }))

    await waitFor(() => expect(loginSpy).toHaveBeenCalledWith('operator', 'a-password'))
  })

  it('shows the server error message on failed login', async () => {
    const { SeleneApiError } = await import('@/services/api/client')
    vi.spyOn(authRepository, 'login').mockRejectedValue(
      new SeleneApiError({ code: 'unauthorized', message: 'The username or password is incorrect.', status: 401 }),
    )
    renderLoginRoute()

    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: /log in/i }))

    await waitFor(() => expect(screen.getByText(/username or password is incorrect/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/login/LoginRoute.test.tsx`
Expected: FAIL — `LoginRoute.tsx` does not exist yet.

- [ ] **Step 3: Write `LoginRoute.tsx`**

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { isSeleneApiError } from '@/services/api/client'
import { useLogin } from '@/features/auth/useLogin'

export function LoginRoute() {
  const navigate = useNavigate()
  const login = useLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    login.mutate(
      { username, password },
      { onSuccess: () => navigate('/', { replace: true }) },
    )
  }

  return (
    <div className="flex h-screen items-center justify-center bg-canvas p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm border border-hairline p-6">
        <h1 className="text-section-title">SELENE-XR</h1>
        <p className="mt-1 text-caption text-mute">Sign in with your operator account.</p>

        <label htmlFor="login-username" className="mt-5 block text-micro uppercase tracking-wide text-mute">
          Username
        </label>
        <input
          id="login-username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none"
        />

        <label htmlFor="login-password" className="mt-4 block text-micro uppercase tracking-wide text-mute">
          Password
        </label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none"
        />

        <Button
          type="submit"
          variant="primary"
          disabled={!username || !password || login.isPending}
          className="mt-5 w-full justify-center"
        >
          {login.isPending ? 'Signing in…' : 'Log in'}
        </Button>

        {login.error && (
          <p className="mt-3 text-caption text-danger">
            {isSeleneApiError(login.error) ? login.error.message : 'The login request failed.'}
          </p>
        )}
      </form>
    </div>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/login/LoginRoute.test.tsx`
Expected: PASS (2/2).

- [ ] **Step 5: Wire `/login` into the router**

In `web/src/app/router.tsx`, add the import `import { LoginRoute } from '@/routes/login/LoginRoute'` and add a sibling top-level entry to the router array (outside the `AppShell` tree, since the login page has no top bar or side navigation):

```typescript
export const router = createBrowserRouter([
  { path: '/login', element: <LoginRoute /> },
  {
    path: '/',
    element: <AppShell />,
    children: [
      // ...unchanged...
    ],
  },
])
```

- [ ] **Step 6: Gate `AppShell` on session state**

In `web/src/components/shell/AppShell.tsx`, add the session check. Full updated file:

```tsx
import { useEffect } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { TopBar } from './TopBar'
import { SideNavigation } from './SideNavigation'
import { CommandPalette } from './CommandPalette'
import { LoadingState } from '@/components/ui/LoadingState'
import { useCommandPaletteStore } from '@/stores/commandPaletteStore'
import { useApplyTheme } from '@/stores/themeStore'
import { authConfigurationState, useSession } from '@/features/auth/useSession'

export function AppShell() {
  const toggle = useCommandPaletteStore((s) => s.toggle)
  const sessionQuery = useSession()
  useApplyTheme()

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        toggle()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [toggle])

  if (sessionQuery.isLoading) return <LoadingState label="Checking session" />
  if (authConfigurationState(sessionQuery.error) === 'unauthenticated') {
    return <Navigate to="/login" replace />
  }

  return (
    <div className="motion-enter flex h-screen flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <SideNavigation />
        <main className="min-w-0 flex-1 overflow-y-auto scrollbar-hairline">
          <Outlet />
        </main>
      </div>
      <CommandPalette />
    </div>
  )
}
```

A `'not-configured'` (404) or `'unknown'` result both fall through to rendering the shell normally — `'not-configured'` because there's genuinely nothing to gate, `'unknown'` so an unrelated transient error never locks operators out of a working console.

- [ ] **Step 7: Write a test for the AppShell gate**

Create `web/src/components/shell/AppShell.test.tsx`:

```typescript
import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import { SeleneApiError } from '@/services/api/client'
import { AppShell } from './AppShell'

afterEach(() => vi.restoreAllMocks())

function renderShell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      { path: '/login', element: <div>LOGIN PAGE</div> },
      { path: '/', element: <AppShell />, children: [{ index: true, element: <div>HOME</div> }] },
    ],
    { initialEntries: ['/'] },
  )
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('AppShell session gate', () => {
  it('redirects to /login on a 401 session response', async () => {
    vi.spyOn(authRepository, 'getSession').mockRejectedValue(
      new SeleneApiError({ code: 'unauthorized', message: 'x', status: 401 }),
    )
    renderShell()

    await waitFor(() => expect(screen.getByText('LOGIN PAGE')).toBeInTheDocument())
  })

  it('renders the shell normally on a 404 (auth not configured)', async () => {
    vi.spyOn(authRepository, 'getSession').mockRejectedValue(
      new SeleneApiError({ code: 'not_found', message: 'x', status: 404 }),
    )
    renderShell()

    await waitFor(() => expect(screen.getByText('HOME')).toBeInTheDocument())
  })

  it('renders the shell normally once a session resolves', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'a', displayName: 'A', role: 'admin' })
    renderShell()

    await waitFor(() => expect(screen.getByText('HOME')).toBeInTheDocument())
  })
})
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd web && ./node_modules/.bin/vitest run src/components/shell/AppShell.test.tsx src/routes/login/LoginRoute.test.tsx`
Expected: PASS (all cases).

- [ ] **Step 9: Type-check and lint**

Run: `cd web && ./node_modules/.bin/tsc -b --noEmit && ./node_modules/.bin/oxlint src/routes/login/ src/app/router.tsx src/components/shell/AppShell.tsx`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add web/src/routes/login/ web/src/app/router.tsx web/src/components/shell/AppShell.tsx web/src/components/shell/AppShell.test.tsx
git commit -m "feat(web): add login page and session-aware route guard"
```

---

## Task 12: TopBar role badge and avatar

**Files:**
- Modify: `web/src/components/shell/TopBar.tsx`
- Test: `web/src/components/shell/TopBar.test.tsx`

**Interfaces:**
- Consumes: `useSession` (Task 10).
- Produces: a read-only `ROLE [badge]` and an initials avatar rendered in `TopBar`, only when `useSession().data` is present — nothing renders when session isn't configured or hasn't resolved. No dropdown, no client-side role setter (ADR-0016 Decision, Alternatives considered).

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import { TopBar } from './TopBar'

afterEach(() => vi.restoreAllMocks())

function renderTopBar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TopBar />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TopBar role badge', () => {
  it('shows the role and initials once a session resolves', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'dijo.benelen', displayName: 'Dijo Benelen', role: 'reviewer' })
    renderTopBar()

    expect(await screen.findByText('REVIEWER')).toBeInTheDocument()
    expect(await screen.findByText('DB')).toBeInTheDocument()
  })

  it('renders nothing extra when auth is not configured for this deployment', async () => {
    const { SeleneApiError } = await import('@/services/api/client')
    vi.spyOn(authRepository, 'getSession').mockRejectedValue(new SeleneApiError({ code: 'not_found', message: 'x', status: 404 }))
    renderTopBar()

    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(screen.queryByText(/REVIEWER|ANALYST|ADMIN/)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && ./node_modules/.bin/vitest run src/components/shell/TopBar.test.tsx`
Expected: FAIL — the badge/avatar don't exist yet.

- [ ] **Step 3: Add the badge and avatar**

In `web/src/components/shell/TopBar.tsx`, add the import and the rendering. Full updated file:

```tsx
import { useCommandPaletteStore } from '@/stores/commandPaletteStore'
import { AsciiStatus } from '@/components/ui/AsciiStatus'
import { useSession } from '@/features/auth/useSession'
import { ThemeToggle } from './ThemeToggle'

function initialsFor(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] ?? ''
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : ''
  return `${first}${last}`.toUpperCase()
}

export function TopBar() {
  const openPalette = useCommandPaletteStore((s) => s.open)
  const sessionQuery = useSession()
  const sessionUser = sessionQuery.data

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-hairline bg-canvas px-4">
      <img src="/brand/selene-xr-wordmark.svg" alt="SELENE-XR" className="brand-mark h-7 w-auto shrink-0" />

      <div className="mx-auto w-full max-w-xl">
        <button
          onClick={openPalette}
          className="flex w-full items-center gap-2 rounded border border-hairline bg-surface-soft px-3 py-1.5 text-left text-caption text-mute hover:border-hairline-strong"
        >
          <span aria-hidden="true">[?]</span>
          <span className="flex-1">Search persisted products, runs, or semantic entities…</span>
          <kbd className="rounded border border-hairline-strong px-1.5 py-0.5 text-micro">⌘K</kbd>
        </button>
      </div>

      <div className="flex items-center gap-4 whitespace-nowrap">
        <span className="flex items-center gap-1.5 text-caption">
          <AsciiStatus marker="dot" tone="muted" />
          <span className="text-mute">API STATUS NOT VERIFIED</span>
        </span>

        {sessionUser && (
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded border border-hairline px-2 py-1 text-micro">
              <span className="text-mute">ROLE</span>
              <span className="font-semibold uppercase">{sessionUser.role}</span>
            </span>
            <span
              title={sessionUser.displayName}
              className="flex h-7 w-7 items-center justify-center rounded-full border border-hairline text-micro font-semibold"
            >
              {initialsFor(sessionUser.displayName)}
            </span>
          </div>
        )}

        <ThemeToggle />
      </div>
    </header>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && ./node_modules/.bin/vitest run src/components/shell/TopBar.test.tsx`
Expected: PASS (2/2).

- [ ] **Step 5: Type-check and lint**

Run: `cd web && ./node_modules/.bin/tsc -b --noEmit && ./node_modules/.bin/oxlint src/components/shell/TopBar.tsx`
Expected: no errors.

- [ ] **Step 6: Visually verify in the browser**

Follow the pattern from the earlier logo work: start `./node_modules/.bin/vite --port 5183` in the background, use the cached Playwright Chromium (`/home/dj/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.mjs`, per the working script from the header-logo task) to screenshot the top bar. Since there's no real backend running, `useSession()` will reject with a network error (not a clean 404/401) — that's expected in this manual check; just confirm the badge area renders without throwing and nothing looks visually broken. A full real-session screenshot isn't possible without the backend from Tasks 1-8 actually running against Postgres; note this limitation in your task report rather than fabricating a screenshot of a logged-in state.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/shell/TopBar.tsx web/src/components/shell/TopBar.test.tsx
git commit -m "feat(web): show the operator's role badge and initials avatar"
```

---

## Task 13: Role-gate the Review Accept/Reject actions

**Files:**
- Modify: `web/src/routes/review/ReviewRoute.tsx`
- Test: `web/src/routes/review/ReviewRoute.test.tsx` (create if it doesn't exist; check first)

**Interfaces:**
- Consumes: `useSession` (Task 10).
- Produces: the Accept/Reject buttons in `ReviewRoute` are additionally disabled (with an explanatory message) when `sessionUser` exists and `sessionUser.role` is not `'reviewer'` or `'admin'`. When there is no session user at all (auth not configured, or still loading), behavior is unchanged from today — this only tightens the gate for an authenticated non-Reviewer, matching the backend's Task 8 rule (`identity.role is not None and identity.role not in (...)`).

- [ ] **Step 1: Check for an existing ReviewRoute test file**

Run: `ls web/src/routes/review/*.test.tsx 2>/dev/null || echo "none"`

If one exists, read it fully and add the new test case to it in its existing style rather than replacing the file.

- [ ] **Step 2: Write the failing test**

```typescript
import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import * as useJobsModule from '@/features/jobs/useJobs'
import { ReviewRoute } from './ReviewRoute'

afterEach(() => vi.restoreAllMocks())

function renderReviewRoute() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/jobs/job-1/review']}>
        <Routes>
          <Route path="/jobs/:id/review" element={<ReviewRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReviewRoute role gating', () => {
  it('disables Accept/Reject for a logged-in Analyst even on an eligible run', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'a', displayName: 'A', role: 'analyst' })
    vi.spyOn(useJobsModule, 'useJobDetail').mockReturnValue({
      isLoading: false,
      error: null,
      data: {
        id: 'job-1',
        state: 'succeeded',
        computedVerdict: 'pass',
        artifacts: [],
        metrics: [],
        reviews: [],
        collectionCursors: {},
      },
    } as unknown as ReturnType<typeof useJobsModule.useJobDetail>)

    renderReviewRoute()

    expect(await screen.findByRole('button', { name: /accept/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /reject/i })).toBeDisabled()
    expect(screen.getByText(/reviewer or admin role is required/i)).toBeInTheDocument()
  })
})
```

Adjust the `useJobDetail` mock shape to match this file's real `Job`/`JobDetail` type exactly (check `web/src/types/job.ts` if the fields above don't compile) — the point of this test is the role gate, not re-deriving the job-detail fixture shape from scratch.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/review/ReviewRoute.test.tsx`
Expected: FAIL — the buttons are enabled today whenever `reviewEligible` is true, regardless of role.

- [ ] **Step 4: Add the role gate**

In `web/src/routes/review/ReviewRoute.tsx`, add the import `import { useSession } from '@/features/auth/useSession'` and, inside the component body, compute the gate:

```typescript
  const sessionQuery = useSession()
  const sessionUser = sessionQuery.data
  const roleForbidden = Boolean(sessionUser && sessionUser.role !== 'reviewer' && sessionUser.role !== 'admin')
```

Then change the `reviewEligible` line to also account for it (keep `reviewEligible` meaning "the run itself is eligible", and gate the buttons/message on both):

```typescript
  const reviewEligible = job.state === 'succeeded' && job.computedVerdict !== null
  const canSubmitReview = reviewEligible && !roleForbidden
```

Update the disabled conditions on both buttons from `disabled={!reviewEligible || ...}` to `disabled={!canSubmitReview || ...}`, and add one line under the existing `{!reviewEligible && ...}` warning paragraph:

```tsx
{roleForbidden && <p className="mt-2 text-caption text-warning">Reviewer or Admin role is required to record a review decision.</p>}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/review/ReviewRoute.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run the full ReviewRoute-adjacent suite to confirm no regression**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/review/ src/features/review/`
Expected: PASS, unchanged.

- [ ] **Step 7: Type-check and lint**

Run: `cd web && ./node_modules/.bin/tsc -b --noEmit && ./node_modules/.bin/oxlint src/routes/review/ReviewRoute.tsx`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add web/src/routes/review/ReviewRoute.tsx web/src/routes/review/ReviewRoute.test.tsx
git commit -m "feat(web): require Reviewer or Admin role to submit a review decision"
```

---

## Task 14: Admin Users screen

**Files:**
- Create: `web/src/routes/admin/UsersRoute.tsx`
- Modify: `web/src/routes/admin/AdminRoute.tsx`
- Modify: `web/src/app/router.tsx`
- Test: `web/src/routes/admin/UsersRoute.test.tsx`

**Interfaces:**
- Consumes: `authRepository.listUsers`/`createUser` (Task 9), `useSession` (Task 10).
- Produces: `/admin/users` page listing accounts and a create-account form; a link to it from `AdminRoute`. Client-side role gate (shows a forbidden message for non-Admins) backed by the real server-side 403 from Task 7 — the client-side check is a UX convenience, not the enforcement boundary.

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import { UsersRoute } from './UsersRoute'

afterEach(() => vi.restoreAllMocks())

function renderUsersRoute() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <UsersRoute />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('UsersRoute', () => {
  it('shows a forbidden message for a non-admin session', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'a', displayName: 'A', role: 'reviewer' })
    renderUsersRoute()

    expect(await screen.findByText(/admin role is required/i)).toBeInTheDocument()
  })

  it('lists accounts and creates a new one for an admin session', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'admin', displayName: 'Admin', role: 'admin' })
    vi.spyOn(authRepository, 'listUsers').mockResolvedValue([
      { username: 'admin', displayName: 'Admin', role: 'admin', isActive: true },
    ])
    const createSpy = vi.spyOn(authRepository, 'createUser').mockResolvedValue({
      username: 'new.analyst', displayName: 'New Analyst', role: 'analyst', isActive: true,
    })
    renderUsersRoute()

    expect(await screen.findByText('admin')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/^username$/i), { target: { value: 'new.analyst' } })
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'New Analyst' } })
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'a-strong-password' } })
    fireEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith({
        username: 'new.analyst',
        password: 'a-strong-password',
        role: 'analyst',
        displayName: 'New Analyst',
      }),
    )
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/admin/UsersRoute.test.tsx`
Expected: FAIL — `UsersRoute.tsx` does not exist yet.

- [ ] **Step 3: Write `UsersRoute.tsx`**

```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { authRepository } from '@/repositories/authRepository'
import { useSession } from '@/features/auth/useSession'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { isSeleneApiError } from '@/services/api/client'

type Role = 'analyst' | 'reviewer' | 'admin'

function useUsers() {
  return useQuery({ queryKey: ['auth', 'users'], queryFn: () => authRepository.listUsers() })
}

function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: authRepository.createUser,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['auth', 'users'] }),
  })
}

export function UsersRoute() {
  const sessionQuery = useSession()
  const usersQuery = useUsers()
  const createUser = useCreateUser()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('analyst')

  if (sessionQuery.isLoading) return <div className="p-6">Loading…</div>
  if (sessionQuery.data?.role !== 'admin') {
    return (
      <div className="p-6">
        <EmptyState title="FORBIDDEN" description="Admin role is required to manage operator accounts." />
      </div>
    )
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    createUser.mutate(
      { username, displayName, password, role },
      { onSuccess: () => { setUsername(''); setDisplayName(''); setPassword('') } },
    )
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader
        eyebrow="System"
        title="Operator accounts"
        description="Create accounts and assign roles. There is no self-service signup."
        actions={<Link to="/admin" className="text-caption text-accent hover:underline">← Platform status</Link>}
      />

      <section className="border border-hairline">
        <table className="w-full border-collapse text-caption">
          <thead className="bg-surface-soft">
            <tr>
              {['USERNAME', 'DISPLAY NAME', 'ROLE', 'ACTIVE'].map((heading) => (
                <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro uppercase tracking-wide text-mute">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(usersQuery.data ?? []).map((account) => (
              <tr key={account.username} className="border-b border-hairline last:border-b-0">
                <td className="px-3 py-2 font-mono">{account.username}</td>
                <td className="px-3 py-2">{account.displayName}</td>
                <td className="px-3 py-2 uppercase">{account.role}</td>
                <td className="px-3 py-2">{account.isActive ? 'YES' : 'NO'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="border border-hairline p-4">
        <h2 className="text-section-title">Create account</h2>
        <form onSubmit={handleSubmit} className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="new-username" className="block text-micro uppercase tracking-wide text-mute">Username</label>
            <input id="new-username" value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="new-display-name" className="block text-micro uppercase tracking-wide text-mute">Display name</label>
            <input id="new-display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="new-password" className="block text-micro uppercase tracking-wide text-mute">Password</label>
            <input id="new-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="new-role" className="block text-micro uppercase tracking-wide text-mute">Role</label>
            <select id="new-role" value={role} onChange={(e) => setRole(e.target.value as Role)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none">
              <option value="analyst">Analyst</option>
              <option value="reviewer">Reviewer</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" variant="primary" disabled={!username || !displayName || !password || createUser.isPending}>
              {createUser.isPending ? 'Creating…' : 'Create account'}
            </Button>
            {createUser.error && (
              <p className="mt-2 text-caption text-danger">
                {isSeleneApiError(createUser.error) ? createUser.error.message : 'The account could not be created.'}
              </p>
            )}
          </div>
        </form>
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/admin/UsersRoute.test.tsx`
Expected: PASS (2/2).

- [ ] **Step 5: Wire `/admin/users` into the router and link it from `AdminRoute`**

In `web/src/app/router.tsx`, add the import `import { UsersRoute } from '@/routes/admin/UsersRoute'`, and replace the existing wildcard entry:

```typescript
{ path: 'admin/*', element: <AdminRoute /> },
```

with two explicit entries:

```typescript
{ path: 'admin', element: <AdminRoute /> },
{ path: 'admin/users', element: <UsersRoute /> },
```

In `web/src/routes/admin/AdminRoute.tsx`, add a link to the new screen. Add the import `import { Link } from 'react-router-dom'` and change the `actions` prop of the existing `<PageHeader ...>` call from:

```tsx
actions={<Button variant="secondary" onClick={() => statusQuery.refetch()} disabled={statusQuery.isFetching}>{statusQuery.isFetching ? 'Refreshing…' : 'Refresh status'}</Button>}
```

to:

```tsx
actions={<><Link to="/admin/users" className="text-caption text-accent hover:underline">Operator accounts →</Link><Button variant="secondary" onClick={() => statusQuery.refetch()} disabled={statusQuery.isFetching}>{statusQuery.isFetching ? 'Refreshing…' : 'Refresh status'}</Button></>}
```

- [ ] **Step 6: Run the full admin-adjacent suite to confirm no regression**

Run: `cd web && ./node_modules/.bin/vitest run src/routes/admin/`
Expected: PASS, unchanged for `AdminRoute`'s own existing tests (if any — check `ls web/src/routes/admin/*.test.tsx` first) plus the new `UsersRoute` tests.

- [ ] **Step 7: Type-check and lint**

Run: `cd web && ./node_modules/.bin/tsc -b --noEmit && ./node_modules/.bin/oxlint src/routes/admin/ src/app/router.tsx`
Expected: no errors.

- [ ] **Step 8: Visually verify in the browser**

Start the dev server and screenshot `/login` and (with a mocked/forbidden session, since no real backend is running) `/admin/users`, same Playwright approach as the earlier logo work. Confirm the login form and the Users table/form render without layout breakage in both light and dark theme. Note in your task report that a true end-to-end "log in as Admin and create a user" pass requires Tasks 1-8's backend running against a real Postgres, which is out of this task's reach — that's covered by the plan's final integration pass below.

- [ ] **Step 9: Commit**

```bash
git add web/src/routes/admin/UsersRoute.tsx web/src/routes/admin/AdminRoute.tsx web/src/routes/admin/UsersRoute.test.tsx web/src/app/router.tsx
git commit -m "feat(web): add admin operator-accounts screen"
```

---

## Final integration pass (manual, after all 14 tasks)

This plan's unit/component tests all use fakes or mocks — by design, per the codebase's existing convention (no live DB for unit tests). Before considering this feature done, run one real end-to-end pass by hand:

1. Start Postgres and run migrations through `20260830_005` (`uv run alembic -c packages/selene_service/alembic.ini upgrade head`).
2. Start the service with `SELENE_SERVICE_AUTHENTICATION_MODE=session`, `SELENE_SERVICE_BOOTSTRAP_ADMIN_USERNAME=admin`, `SELENE_SERVICE_BOOTSTRAP_ADMIN_PASSWORD=<a real password>`, bound to loopback.
3. Start the web console against that service (same-origin proxy or `VITE_SELENE_API_PROXY_TARGET`, per `web/README.md`).
4. In a browser: confirm `/` redirects to `/login`; log in as `admin`; confirm the role badge shows ADMIN and the avatar shows initials; visit `/admin/users`, create an `analyst` account; log out; log in as the new analyst; confirm `/jobs/<id>/review`'s Accept/Reject buttons are disabled with the "Reviewer or Admin role is required" message on an eligible run; log in as `admin` again, promote the analyst to `reviewer` via a `PATCH /api/v1/auth/users/{id}`, log in as them again, confirm the buttons are now enabled.
5. Confirm `SELENE_SERVICE_AUTHENTICATION_MODE=unauthenticated` (today's default) still serves the console with no login redirect and no role badge — the backward-compatibility path this whole plan depends on.

Record the outcome of this pass in the final whole-plan review; it is the one thing no automated test in this plan actually proves end-to-end.
