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


def _request_with_cookie(
    settings: ServiceSettings, session_factory: object, cookie: str | None
) -> Request:
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
        password_hash="unused",  # noqa: S106 - not a real credential
        role="reviewer",
        display_name="Reviewer One",
        is_active=True,
    )
    subject = Subject(
        id=subject_id, subject_name="user:reviewer.one", subject_type="user", is_active=True
    )

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


@pytest.mark.unit
def test_session_mode_rejects_an_api_key_when_there_is_no_session_cookie() -> None:
    """A shared proxy key must not impersonate an operator in SESSION mode."""

    settings = _settings()
    request = _request_with_cookie(settings, lambda: None, cookie=None)

    with pytest.raises(APIProblem) as problem:
        get_subject_identity(request, api_key="a-shared-key")

    assert problem.value.status_code == 401
