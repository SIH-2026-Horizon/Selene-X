"""Contract tests for the service-process foundation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from selene_service.app import SERVICE_TITLE, create_app
from selene_service.launcher import run_service
from selene_service.settings import (
    AuthenticationMode,
    ServiceConfigurationError,
    ServiceEnvironment,
    ServiceSettings,
)


def _settings(**overrides: object) -> ServiceSettings:
    defaults: dict[str, object] = {
        "bind_host": "127.0.0.1",
        "environment": ServiceEnvironment.TEST,
        "package_version": "1.2.3",
    }
    defaults.update(overrides)
    return ServiceSettings.model_validate(defaults)


@pytest.mark.unit
def test_settings_read_typed_service_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SELENE_SERVICE_BIND_HOST", "::1")
    monkeypatch.setenv("SELENE_SERVICE_PORT", "8123")
    monkeypatch.setenv("SELENE_SERVICE_ENVIRONMENT", "production")
    monkeypatch.setenv("SELENE_SERVICE_PACKAGE_VERSION", "4.5.6")
    monkeypatch.setenv("SELENE_SERVICE_AUTHENTICATION_MODE", "external")
    monkeypatch.setenv("SELENE_SERVICE_AUTH_ISSUER_URL", "https://identity.example.test")
    monkeypatch.setenv("SELENE_SERVICE_AUTH_AUDIENCE", "selene-service")
    monkeypatch.setenv(
        "SELENE_SERVICE_DATABASE_URL",
        "postgresql+psycopg://selene:local@127.0.0.1:5432/selene",
    )

    settings = ServiceSettings()

    assert settings.bind_host == "::1"
    assert settings.port == 8123
    assert settings.environment is ServiceEnvironment.PRODUCTION
    assert settings.package_version == "4.5.6"
    assert settings.authentication_mode is AuthenticationMode.EXTERNAL
    assert str(settings.auth_issuer_url) == "https://identity.example.test/"
    assert settings.auth_audience == "selene-service"
    assert str(settings.database_url).startswith("postgresql+psycopg://selene:local@")


@pytest.mark.unit
def test_factory_metadata_and_system_endpoints_are_json() -> None:
    app = create_app(_settings())

    assert app.title == SERVICE_TITLE
    assert app.version == "1.2.3"
    assert app.openapi()["info"]["title"] == SERVICE_TITLE
    assert app.openapi()["info"]["version"] == "1.2.3"

    with TestClient(app) as client:
        health_response = client.get("/healthz")
        version_response = client.get("/api/v1/version")

    assert health_response.status_code == 200
    assert health_response.headers["content-type"] == "application/json"
    assert health_response.json() == {"status": "ok"}
    assert version_response.status_code == 200
    assert version_response.headers["content-type"] == "application/json"
    assert version_response.json() == {
        "service": "selene-service",
        "version": "1.2.3",
        "environment": "test",
    }


@pytest.mark.unit
def test_lifespan_builds_and_disposes_the_settings_backed_database_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Engine:
        def __init__(self) -> None:
            self.disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = _Engine()
    captured_settings: list[ServiceSettings] = []
    session_factory = object()

    def fake_create_engine(settings: ServiceSettings) -> _Engine:
        captured_settings.append(settings)
        return engine

    def fake_create_session_factory(created_engine: _Engine) -> object:
        assert created_engine is engine
        return session_factory

    monkeypatch.setattr("selene_service.app.create_engine_from_settings", fake_create_engine)
    monkeypatch.setattr("selene_service.app.create_session_factory", fake_create_session_factory)
    settings = _settings()
    app = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert app.state.session_factory is session_factory

    assert captured_settings == [settings]
    assert engine.disposed


@pytest.mark.unit
def test_readiness_checks_postgres_without_changing_dependency_free_liveness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Connection:
        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            assert str(statement) == "SELECT 1"

    class _Engine:
        def connect(self) -> _Connection:
            return _Connection()

        def dispose(self) -> None:
            return None

    engine = _Engine()
    monkeypatch.setattr("selene_service.app.create_engine_from_settings", lambda _: engine)
    monkeypatch.setattr("selene_service.app.create_session_factory", lambda _: object())
    app = create_app(_settings())

    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        readiness_response = client.get("/readyz")

    assert readiness_response.status_code == 200
    assert readiness_response.json() == {"status": "ok"}


@pytest.mark.unit
def test_readiness_hides_postgres_failures_in_the_standard_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _UnavailableEngine:
        def connect(self) -> object:
            raise OperationalError("SELECT 1", {}, RuntimeError("offline"))

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(
        "selene_service.app.create_engine_from_settings",
        lambda _: _UnavailableEngine(),
    )
    monkeypatch.setattr("selene_service.app.create_session_factory", lambda _: object())
    app = create_app(_settings())

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        readiness_response = client.get("/readyz")

    assert readiness_response.status_code == 503
    assert readiness_response.json() == {
        "error": {
            "code": "service_unavailable",
            "message": "The service is temporarily unavailable.",
        }
    }


@pytest.mark.unit
@pytest.mark.parametrize("bind_host", ["127.0.0.1", "127.0.0.42", "::1", "localhost"])
def test_unauthenticated_loopback_binds_are_allowed(bind_host: str) -> None:
    create_app(_settings(bind_host=bind_host))


@pytest.mark.unit
@pytest.mark.parametrize(
    "bind_host",
    [
        "0.0.0.0",  # noqa: S104 - exercises the loopback-bind rejection policy.
        "::",
        "192.168.1.10",
        "10.0.0.10",
        "203.0.113.10",
        "example.test",
    ],
)
def test_unauthenticated_non_loopback_binds_are_rejected(bind_host: str) -> None:
    with pytest.raises(ServiceConfigurationError, match="loopback"):
        create_app(_settings(bind_host=bind_host))


@pytest.mark.unit
def test_external_authentication_mode_allows_a_non_loopback_bind() -> None:
    app = create_app(
        _settings(
            bind_host="192.168.1.10",
            authentication_mode=AuthenticationMode.EXTERNAL,
        )
    )

    assert app.state.settings.authentication_mode is AuthenticationMode.EXTERNAL


@pytest.mark.unit
def test_controlled_launcher_uses_the_validated_settings_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("selene_service.launcher.uvicorn.run", fake_run)

    run_service(_settings(bind_host="::1", port=8123))

    assert len(calls) == 1
    arguments, keyword_arguments = calls[0]
    assert len(arguments) == 1
    assert keyword_arguments == {"host": "::1", "port": 8123}


@pytest.mark.unit
def test_controlled_launcher_refuses_unauthenticated_external_bind_before_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("selene_service.launcher.uvicorn.run", fake_run)

    with pytest.raises(ServiceConfigurationError, match="loopback"):
        run_service(_settings(bind_host="0.0.0.0"))  # noqa: S104 - policy test target

    assert calls == []


@pytest.mark.unit
def test_http_errors_use_the_stable_error_envelope() -> None:
    with TestClient(create_app(_settings())) as client:
        response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
        }
    }


@pytest.mark.unit
def test_validation_errors_use_the_stable_error_envelope() -> None:
    app = create_app(_settings())

    @app.get("/_test/validation")
    async def requires_integer(value: int) -> dict[str, int]:
        return {"value": value}

    with TestClient(app) as client:
        response = client.get("/_test/validation", params={"value": "not-an-integer"})

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "validation_error",
            "message": "The request failed validation.",
        }
    }


@pytest.mark.unit
def test_version_route_and_internal_errors_do_not_leak_configuration_or_exceptions() -> None:
    database_password = "database-secret-must-not-escape"  # noqa: S105 - test sentinel
    app = create_app(
        _settings(
            database_url=(
                f"postgresql+psycopg://service:{database_password}@127.0.0.1:5432/selene"
            ),
            auth_audience="internal-audience-secret",
        )
    )

    @app.get("/_test/unexpected-error")
    async def unexpected_error() -> None:
        raise RuntimeError(database_password)

    with TestClient(app, raise_server_exceptions=False) as client:
        version_response = client.get("/api/v1/version")
        error_response = client.get("/_test/unexpected-error")

    assert database_password not in version_response.text
    assert "internal-audience-secret" not in version_response.text
    assert error_response.status_code == 500
    assert error_response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "An unexpected internal error occurred.",
        }
    }
    assert database_password not in error_response.text


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
