"""Contracts for server-side operator sessions and login lockout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
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
    """A real transactional Postgres session; see ``tests/conftest.py``.

    Cleans this module's own rows *before* each test rather than relying on
    ``session.rollback()`` at teardown alone: several tests below call
    ``db_session.commit()`` mid-test (to exercise real lockout/session
    persistence against Postgres), which durably writes rows to the shared
    test database. Without this, a later test reusing the fixed usernames
    "operator"/"admin" would collide with a prior test's committed row via
    the real ``uq_user_accounts_username`` constraint, and the "no accounts
    exist yet" assertion in the bootstrap no-op test would see leftover
    rows from earlier tests. Scoped narrowly to the fixed identifiers this
    file itself creates, so it does not touch unrelated data in the shared
    test database.
    """

    Base.metadata.create_all(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(text("DELETE FROM user_sessions"))
        connection.execute(
            text("DELETE FROM user_accounts WHERE username IN ('operator', 'admin')")
        )
        connection.execute(
            text(
                "DELETE FROM subjects WHERE subject_name = 'operator-under-test' "
                "OR subject_name LIKE 'user:%'"
            )
        )

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

    with pytest.raises(APIProblem) as unknown_user:
        authenticate_with_password(db_session, "nobody", "irrelevant", _settings())
    with pytest.raises(APIProblem) as wrong_password:
        authenticate_with_password(db_session, "operator", "totally wrong", _settings())

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
        authenticate_with_password(db_session, "operator", "correct horse battery staple", settings)


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
