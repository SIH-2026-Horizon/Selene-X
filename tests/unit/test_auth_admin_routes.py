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
        self.subject = Subject(
            id=subject_id, subject_name="user:operator", subject_type="user", is_active=True
        )
        self.account = UserAccount(
            id=self.account_id,
            subject_id=subject_id,
            username="operator",
            password_hash=hash_password("correct horse battery staple"),
            role="admin",
            display_name="Operator",
            is_active=True,
        )
        self.sessions: dict[object, UserSession] = {}
        self.created: list[UserAccount] = []

    def begin(self) -> object:
        from contextlib import nullcontext

        return nullcontext()

    def scalar(self, statement: object) -> object:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is UserAccount:
            # A minimal double, not a real query engine: distinguish the
            # login lookup (username == "operator", the seeded account)
            # from the create-user-account existence check (any other
            # username, which never has a pre-existing account) by reading
            # the literal bind out of the compiled WHERE clause.
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]
            if self.account.username in compiled:
                return self.account
            return None
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
                instance.id = uuid4()  # type: ignore[unreachable]
            self.sessions[instance.id] = instance
        if isinstance(instance, UserAccount):
            if instance.id is None:
                instance.id = uuid4()  # type: ignore[unreachable]
            self.created.append(instance)
        if isinstance(instance, Subject) and instance.id is None:
            instance.id = uuid4()  # type: ignore[unreachable]

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
        # The cookie-based branch of get_subject_identity (Task 5) reads
        # request.app.state.session_factory directly rather than through the
        # overridable get_db_session dependency, so it must be pointed at the
        # fake separately, and only after lifespan startup — which otherwise
        # overwrites it with a real engine's session factory — has already
        # run. Mirrors the same pattern in test_auth_routes.py.
        app.state.session_factory = lambda: fake
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        response = client.post(
            "/api/v1/auth/users",
            json={
                "username": "new.analyst",
                "password": "another-strong-password",
                "role": "analyst",
                "display_name": "New Analyst",
            },
        )

    assert login.status_code == 200
    assert response.status_code == 403


@pytest.mark.unit
def test_admin_can_create_a_user_and_the_password_is_hashed() -> None:
    app = create_app(_session_settings())
    fake = _AdminFakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        # See the comment in test_non_admin_cannot_create_a_user above.
        app.state.session_factory = lambda: fake
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        response = client.post(
            "/api/v1/auth/users",
            json={
                "username": "new.analyst",
                "password": "another-strong-password",
                "role": "analyst",
                "display_name": "New Analyst",
            },
        )

    assert response.status_code == 201
    body = response.json()
    # The account's id is server-generated (the fake's add() assigns it a
    # fresh uuid4() the same way a real DB-backed insert would), so it can't
    # be a literal in the expected body — compare it against the account the
    # fake actually recorded instead.
    assert body == {
        "id": str(fake.created[-1].id),
        "username": "new.analyst",
        "display_name": "New Analyst",
        "role": "analyst",
        "is_active": True,
    }
    assert fake.created[-1].password_hash != "another-strong-password"  # noqa: S105 - not a real credential


@pytest.mark.unit
def test_admin_cannot_change_their_own_role() -> None:
    app = create_app(_session_settings())
    fake = _AdminFakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        # See the comment in test_non_admin_cannot_create_a_user above.
        app.state.session_factory = lambda: fake
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        response = client.patch(f"/api/v1/auth/users/{fake.account_id}", json={"role": "analyst"})

    assert response.status_code == 403


@pytest.mark.unit
def test_admin_can_self_update_active_state_and_password_without_changing_role() -> None:
    """A self-targeted update is only blocked when it changes ``role``
    (ADR-0016: "No endpoint lets a session change its own role"). Rotating
    one's own password, or toggling one's own ``is_active``, is permitted —
    see the final-review finding this test guards against a regression on
    (the bootstrap Admin previously could never rotate their own password).
    """

    app = create_app(_session_settings())
    fake = _AdminFakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        # See the comment in test_non_admin_cannot_create_a_user above.
        app.state.session_factory = lambda: fake
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        response = client.patch(
            f"/api/v1/auth/users/{fake.account_id}",
            json={"is_active": True, "new_password": "a-new-strong-password"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(fake.account_id)
    assert body["role"] == "admin"
    assert body["is_active"] is True
    assert fake.account.password_hash != "a-new-strong-password"  # noqa: S105 - not a real credential


@pytest.mark.unit
def test_admin_cannot_create_a_duplicate_username() -> None:
    app = create_app(_session_settings())
    fake = _AdminFakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        # See the comment in test_non_admin_cannot_create_a_user above.
        app.state.session_factory = lambda: fake
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        # A successful login already re-adds the existing operator account
        # to `fake.created` via record_login_success's session.add() (the
        # fake tracks every UserAccount add, not just newly-created ones —
        # see test_admin_can_create_a_user_and_the_password_is_hashed's use
        # of `created[-1]` above). Snapshot the count here so the assertion
        # below only checks for growth caused by *this* request.
        created_before_request = len(fake.created)
        # "operator" is the seeded admin's own username, so the fake's
        # scalar() (see its docstring above) returns the existing account
        # for this existence check the same way it does for the login
        # lookup — no changes to the fake needed.
        response = client.post(
            "/api/v1/auth/users",
            json={
                "username": "operator",
                "password": "another-strong-password",
                "role": "analyst",
                "display_name": "Duplicate Operator",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
    assert len(fake.created) == created_before_request
