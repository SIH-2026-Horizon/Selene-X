"""Configuration and network-boundary policy for the SELENE-XR service."""

from __future__ import annotations

import ipaddress
from enum import StrEnum

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from selene_service import __version__


class ServiceEnvironment(StrEnum):
    """Named deployment environments exposed by the service metadata route."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


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


class ServiceConfigurationError(ValueError):
    """Raised when the service configuration would expose an unsafe API."""


def is_loopback_bind_host(host: str) -> bool:
    """Return whether *host* is an explicit loopback bind address.

    DNS is intentionally not consulted: an operator must request either the
    ``localhost`` name or an IP address that is itself classified as loopback.
    This keeps the development network boundary deterministic and fail closed.
    """

    normalized_host = host.strip()
    if normalized_host.casefold() == "localhost":
        return True

    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False


class ServiceSettings(BaseSettings):
    """Typed configuration for the service process.

    Values are read from ``SELENE_SERVICE_*`` environment variables. For
    example, ``SELENE_SERVICE_BIND_HOST`` overrides ``bind_host`` and
    ``SELENE_SERVICE_AUTH_ISSUER_URL`` sets the optional generic issuer URL.
    The defaults are intentionally suitable only for a local development
    process; no database connection is made while settings are constructed.
    """

    model_config = SettingsConfigDict(
        env_prefix="SELENE_SERVICE_",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    bind_host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    environment: ServiceEnvironment = ServiceEnvironment.DEVELOPMENT
    package_version: str = Field(default=__version__, min_length=1)

    authentication_mode: AuthenticationMode = AuthenticationMode.UNAUTHENTICATED
    auth_issuer_url: AnyHttpUrl | None = None
    auth_audience: str | None = Field(default=None, min_length=1)
    # Only the local Compose profile sets this private credential. The service
    # stores its SHA-256 digest at startup and Nginx injects the raw value only
    # on its private upstream hop; it never belongs in browser configuration.
    local_api_key: SecretStr | None = Field(default=None, min_length=32, max_length=512)
    local_api_key_subject: str = Field(
        default="local-platform-operator",
        min_length=1,
        max_length=255,
    )
    session_cookie_name: str = Field(default="selene_session", min_length=1, max_length=64)
    session_ttl_seconds: int = Field(default=43_200, ge=60)
    # Both must be set together to bootstrap the first Admin account; a
    # deployment that never sets them simply never gets an auto-created
    # Admin (ADR-0016).
    bootstrap_admin_username: str | None = Field(default=None, min_length=1, max_length=64)
    bootstrap_admin_password: SecretStr | None = Field(default=None, min_length=8)
    login_lockout_threshold: int = Field(default=5, ge=1)
    login_lockout_seconds: int = Field(default=30, ge=1)

    database_url: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://selene:selene@127.0.0.1:5432/selene"
    )

    def validate_network_boundary(self) -> None:
        """Reject an unauthenticated process that would listen beyond loopback."""

        if (
            self.authentication_mode is AuthenticationMode.UNAUTHENTICATED
            and not is_loopback_bind_host(self.bind_host)
        ):
            raise ServiceConfigurationError(
                "Unauthenticated SELENE-XR service binds must use an explicit "
                "loopback host (localhost, 127.0.0.0/8, or ::1)."
            )
