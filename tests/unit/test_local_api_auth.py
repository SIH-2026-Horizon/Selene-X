"""Contracts for the local Compose API-key boundary."""

from __future__ import annotations

from contextlib import nullcontext
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from selene_service.api.dependencies import get_db_session
from selene_service.api.errors import APIProblem
from selene_service.api.local_auth import (
    LOCAL_PLATFORM_KEY_LABEL,
    SERVICE_WRITE_SCOPE,
    authenticate_api_key,
    bootstrap_local_api_key,
    digest_api_key,
)
from selene_service.app import create_app
from selene_service.persistence.models import ApiKey, Subject
from selene_service.settings import AuthenticationMode, ServiceSettings

LOCAL_KEY = "local_platform_api_key_for_unit_tests_1234567890"


class _BootstrapSession:
    def __init__(self) -> None:
        self.subject: Subject | None = None
        self.key: ApiKey | None = None
        self.added: list[object] = []
        self.closed = False
        self.update_called = False

    def begin(self) -> object:
        return nullcontext()

    def scalar(self, statement: object) -> Subject | ApiKey | None:
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is Subject:
            return self.subject
        if entity is ApiKey:
            return self.key
        return None

    def add(self, instance: object) -> None:
        self.added.append(instance)
        if isinstance(instance, Subject):
            instance.id = uuid4()
            self.subject = instance
        elif isinstance(instance, ApiKey):
            self.key = instance

    def flush(self) -> None:
        return None

    def execute(self, _: object) -> None:
        self.update_called = True

    def close(self) -> None:
        self.closed = True


class _CredentialSession:
    def __init__(self, key: ApiKey | None, subject: Subject | None) -> None:
        self.key = key
        self.subject = subject

    def scalar(self, _: object) -> ApiKey | None:
        return self.key

    def get(self, _: object, __: object) -> Subject | None:
        return self.subject

    def close(self) -> None:
        return None


class _MissingProductSession:
    def __init__(self) -> None:
        self.subject = Subject(
            id=uuid4(),
            subject_name="local-platform-operator",
            subject_type="local",
            is_active=True,
        )

    def begin(self) -> object:
        return nullcontext()

    def scalar(self, _: object) -> Subject:
        return self.subject

    def get(self, _: object, __: object) -> None:
        return None

    def execute(self, _: object) -> None:
        return None

    def close(self) -> None:
        return None


def _external_settings() -> ServiceSettings:
    return ServiceSettings.model_validate(
        {
            "bind_host": "127.0.0.1",
            "authentication_mode": AuthenticationMode.EXTERNAL,
            "local_api_key": LOCAL_KEY,
        }
    )


@pytest.mark.unit
def test_local_bootstrap_persists_only_a_digest_and_is_idempotent() -> None:
    session = _BootstrapSession()

    bootstrap_local_api_key(lambda: session, _external_settings())
    bootstrap_local_api_key(lambda: session, _external_settings())

    assert session.subject is not None
    assert session.subject.subject_name == "local-platform-operator"
    assert session.key is not None
    assert session.key.key_digest == digest_api_key(LOCAL_KEY)
    assert session.key.key_digest != LOCAL_KEY
    assert session.key.label == LOCAL_PLATFORM_KEY_LABEL
    assert session.key.scopes == [SERVICE_WRITE_SCOPE]
    assert len([record for record in session.added if isinstance(record, ApiKey)]) == 1
    assert session.update_called is True
    assert session.closed is True


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


@pytest.mark.unit
def test_api_key_authentication_resolves_only_an_active_write_scoped_subject() -> None:
    subject = Subject(
        id=uuid4(),
        subject_name="local-platform-operator",
        subject_type="local",
        is_active=True,
    )
    credential = ApiKey(
        subject_id=subject.id,
        key_digest=digest_api_key(LOCAL_KEY),
        scopes=[SERVICE_WRITE_SCOPE],
    )

    identity = authenticate_api_key(_CredentialSession(credential, subject), LOCAL_KEY)  # type: ignore[arg-type]

    assert identity == ("local-platform-operator", "local")
    with pytest.raises(APIProblem, match="Authentication is required") as problem:
        authenticate_api_key(_CredentialSession(None, subject), LOCAL_KEY)  # type: ignore[arg-type]
    assert problem.value.status_code == 401


@pytest.mark.unit
def test_bootstrap_rejects_a_digest_already_reserved_by_a_different_credential() -> None:
    session = _BootstrapSession()
    subject = Subject(
        id=uuid4(),
        subject_name="local-platform-operator",
        subject_type="local",
        is_active=True,
    )
    session.subject = subject
    session.key = ApiKey(
        subject_id=subject.id,
        key_digest=digest_api_key(LOCAL_KEY),
        label="operator-api-key",
        scopes=[],
    )

    with pytest.raises(RuntimeError, match="another credential"):
        bootstrap_local_api_key(lambda: session, _external_settings())


@pytest.mark.unit
def test_external_mutations_reject_spoofed_subject_and_require_a_verified_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential_subject = Subject(
        id=uuid4(),
        subject_name="local-platform-operator",
        subject_type="local",
        is_active=True,
    )
    credential = ApiKey(
        subject_id=credential_subject.id,
        key_digest=digest_api_key(LOCAL_KEY),
        scopes=[SERVICE_WRITE_SCOPE],
    )
    app = create_app(_external_settings())
    app.dependency_overrides[get_db_session] = _MissingProductSession
    monkeypatch.setattr("selene_service.app.bootstrap_local_api_key", lambda *_: None)
    payload = {
        "source_product_id": str(uuid4()),
        "reference_product_id": str(uuid4()),
        "parameter_manifest": {"matching": {"threshold": 0.75}},
        "algorithm_versions": {"matching": "operator-supplied"},
        "code_revision": "a" * 40,
        "environment_fingerprint": "b" * 64,
    }

    with TestClient(app) as client:
        app.state.session_factory = lambda: _CredentialSession(credential, credential_subject)
        spoofed = client.post(
            "/api/v1/runs",
            json=payload,
            headers={"X-SELENE-Subject": "attacker"},
        )
        authorized = client.post(
            "/api/v1/runs",
            json=payload,
            headers={"X-SELENE-API-Key": LOCAL_KEY},
        )

    assert spoofed.status_code == 401
    assert spoofed.json()["error"]["code"] == "unauthorized"
    # The product IDs deliberately do not exist: 404 proves authentication ran
    # before the route's persisted-domain check without manufacturing a record.
    assert authorized.status_code == 404
    assert authorized.json()["error"]["code"] == "not_found"
