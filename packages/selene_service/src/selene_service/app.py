"""FastAPI application factory for the SELENE-XR service process."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Final, Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from selene_service.api.auth_routes import build_auth_router
from selene_service.api.errors import APIProblem
from selene_service.api.local_auth import bootstrap_local_api_key
from selene_service.api.routes import router as v1_router
from selene_service.api.session_auth import bootstrap_admin_user
from selene_service.persistence.session import create_engine_from_settings, create_session_factory
from selene_service.settings import AuthenticationMode, ServiceEnvironment, ServiceSettings

LOGGER = logging.getLogger(__name__)

SERVICE_TITLE = "SELENE-XR Service"
API_V1_PREFIX = "/api/v1"


class HealthResponse(BaseModel):
    """Liveness response that intentionally never probes external dependencies."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"] = "ok"


class VersionResponse(BaseModel):
    """Public build metadata; deliberately excludes all configuration values."""

    model_config = ConfigDict(frozen=True)

    service: Literal["selene-service"] = "selene-service"
    version: str
    environment: ServiceEnvironment


class APIError(BaseModel):
    """Stable public error detail without backend exception information."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str


class ErrorEnvelope(BaseModel):
    """The single error response shape for all service HTTP failures."""

    model_config = ConfigDict(frozen=True)

    error: APIError


HTTP_ERROR_CODES: Final[Mapping[int, tuple[str, str]]] = {
    400: ("bad_request", "The request could not be processed."),
    401: ("unauthorized", "Authentication is required."),
    403: ("forbidden", "The request is not permitted."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "The request method is not allowed."),
    409: ("conflict", "The request conflicts with the current resource state."),
    413: ("payload_too_large", "The request payload is too large."),
    415: ("unsupported_media_type", "The request media type is not supported."),
    422: ("validation_error", "The request failed validation."),
    429: ("rate_limited", "The request rate limit has been exceeded."),
    503: ("service_unavailable", "The service is temporarily unavailable."),
}


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Build an error response from the public, stable schema."""

    envelope = ErrorEnvelope(error=APIError(code=code, message=message))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


def _http_error_response(status_code: int) -> JSONResponse:
    """Map HTTP status codes to safe public messages."""

    code, message = HTTP_ERROR_CODES.get(
        status_code,
        ("http_error", "The request could not be completed."),
    )
    return _error_response(status_code, code, message)


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    """Create a configured FastAPI application without running a network server."""

    configured_settings = settings or ServiceSettings()
    configured_settings.validate_network_boundary()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        # Recheck at startup as a defence-in-depth guard for alternate ASGI
        # lifecycles. ServiceSettings itself is frozen after construction.
        configured_settings.validate_network_boundary()
        engine = create_engine_from_settings(configured_settings)
        application.state.db_engine = engine
        application.state.session_factory = create_session_factory(engine)
        try:
            bootstrap_local_api_key(application.state.session_factory, configured_settings)
            bootstrap_admin_user(application.state.session_factory, configured_settings)
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=SERVICE_TITLE,
        version=configured_settings.package_version,
        description="Persisted SELENE-XR product, run, and provenance service.",
        default_response_class=JSONResponse,
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = configured_settings
    app.include_router(v1_router)
    if configured_settings.authentication_mode is AuthenticationMode.SESSION:
        app.include_router(build_auth_router(configured_settings))

    @app.get("/healthz", response_model=HealthResponse, tags=["system"])
    async def healthz() -> HealthResponse:
        """Report process liveness without touching the database or network."""

        return HealthResponse()

    @app.get(
        "/readyz",
        response_model=HealthResponse,
        responses={503: {"model": ErrorEnvelope}},
        tags=["system"],
    )
    async def readyz(request: Request) -> HealthResponse | JSONResponse:
        """Report whether the required PostgreSQL dependency accepts a query.

        This deliberately stays separate from ``/healthz``: process liveness
        must not flap merely because a dependency is unavailable. The response
        uses the public error envelope rather than leaking database details.
        """

        engine = getattr(request.app.state, "db_engine", None)
        if engine is None:
            return _error_response(
                503,
                "service_unavailable",
                "The service is temporarily unavailable.",
            )
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return _error_response(
                503,
                "service_unavailable",
                "The service is temporarily unavailable.",
            )
        return HealthResponse()

    @app.get(
        f"{API_V1_PREFIX}/version",
        response_model=VersionResponse,
        tags=["system"],
    )
    async def version() -> VersionResponse:
        """Expose non-sensitive service metadata for clients and diagnostics."""

        return VersionResponse(
            version=configured_settings.package_version,
            environment=configured_settings.environment,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request,
        exception: StarletteHTTPException,
    ) -> JSONResponse:
        """Serialize expected HTTP failures using the public error envelope."""

        return _http_error_response(exception.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        _: Request,
        __: RequestValidationError,
    ) -> JSONResponse:
        """Hide request input while retaining a stable validation failure code."""

        return _http_error_response(422)

    @app.exception_handler(APIProblem)
    async def handle_api_problem(_: Request, exception: APIProblem) -> JSONResponse:
        """Serialize expected domain/persistence request failures safely."""

        return _error_response(exception.status_code, exception.code, exception.message)

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_: Request, __: IntegrityError) -> JSONResponse:
        """Hide database constraint details while reporting a resource conflict."""

        return _http_error_response(409)

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request,
        __: Exception,
    ) -> JSONResponse:
        """Do not leak unexpected exception details to service clients."""

        LOGGER.exception("Unhandled exception while serving %s", request.url.path)
        return _error_response(
            500,
            "internal_server_error",
            "An unexpected internal error occurred.",
        )

    return app
