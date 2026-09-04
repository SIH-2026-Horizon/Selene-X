"""Contracts for login, logout, and session-hydration routes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from selene_service.api.dependencies import get_db_session
from selene_service.api.password_auth import hash_password, verify_password
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
        self.subject = Subject(
            id=subject_id, subject_name="user:operator", subject_type="user", is_active=True
        )
        self.account = UserAccount(
            id=self.account_id,
            subject_id=subject_id,
            username="operator",
            password_hash=hash_password("correct horse battery staple"),
            role="reviewer",
            display_name="Operator",
            is_active=True,
            failed_login_count=0,
        )
        self.sessions: dict[object, UserSession] = {}

    def begin(self) -> object:
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
            instance.id = uuid4()
            self.sessions[instance.id] = instance

    def flush(self) -> None:
        return None

    def refresh(self, instance: object) -> None:
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
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "username": "operator",
        "display_name": "Operator",
        "role": "reviewer",
    }
    assert "selene_session" in response.cookies
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "samesite=strict" in set_cookie.lower()


@pytest.mark.unit
def test_login_rejects_wrong_credentials_with_401() -> None:
    app = create_app(_session_settings())
    app.dependency_overrides[get_db_session] = lambda: _FakeSession()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "wrong"}
        )

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
        ServiceSettings.model_validate(
            {"bind_host": "127.0.0.1", "authentication_mode": "unauthenticated"}
        )
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/session")

    assert response.status_code == 404


@pytest.mark.unit
def test_login_then_session_round_trip_with_the_returned_cookie() -> None:
    settings = _session_settings()
    app = create_app(settings)
    fake = _FakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        # The cookie-based branch of get_subject_identity (Task 5) reads
        # request.app.state.session_factory directly rather than through the
        # overridable get_db_session dependency, so it must be pointed at the
        # fake separately, and only after lifespan startup — which otherwise
        # overwrites it with a real engine's session factory — has already
        # run. Mirrors the same pattern in test_local_api_auth.py.
        app.state.session_factory = lambda: fake
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        # Capture the actual session id the server issued before anything
        # clears it client-side, so it can be re-attached after logout below.
        session_cookie = client.cookies.get(settings.session_cookie_name)
        session_response = client.get("/api/v1/auth/session")
        logout = client.post("/api/v1/auth/logout")
        # `logout_route`'s `response.delete_cookie` has already cleared this
        # cookie from the TestClient's jar, so a plain follow-up request
        # would return 401 merely because the client has nothing to send —
        # that would not prove the session was revoked *server-side*.
        # Re-attach the captured session id explicitly to prove the session
        # itself is now rejected, not just that the client lost its cookie.
        assert session_cookie is not None
        client.cookies.set(settings.session_cookie_name, session_cookie)
        after_logout = client.get("/api/v1/auth/session")

    assert login.status_code == 200
    assert session_response.status_code == 200
    assert session_response.json()["username"] == "operator"
    assert logout.status_code == 204
    assert after_logout.status_code == 401


@pytest.mark.unit
def test_signed_in_operator_can_update_their_display_name_and_password() -> None:
    app = create_app(_session_settings())
    fake = _FakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        app.state.session_factory = lambda: fake
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        response = client.patch(
            "/api/v1/auth/profile",
            json={
                "display_name": "Updated Operator",
                "current_password": "correct horse battery staple",
                "new_password": "a-new-strong-password",
            },
        )

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "username": "operator",
        "display_name": "Updated Operator",
        "role": "reviewer",
    }
    assert fake.account.display_name == "Updated Operator"
    assert verify_password("a-new-strong-password", fake.account.password_hash)


@pytest.mark.unit
def test_profile_password_change_rejects_an_incorrect_current_password() -> None:
    app = create_app(_session_settings())
    fake = _FakeSession()
    app.dependency_overrides[get_db_session] = lambda: fake

    with TestClient(app) as client:
        app.state.session_factory = lambda: fake
        client.post(
            "/api/v1/auth/login",
            json={"username": "operator", "password": "correct horse battery staple"},
        )
        response = client.patch(
            "/api/v1/auth/profile",
            json={"current_password": "wrong", "new_password": "a-new-strong-password"},
        )

    assert response.status_code == 401
    assert verify_password("correct horse battery staple", fake.account.password_hash)
