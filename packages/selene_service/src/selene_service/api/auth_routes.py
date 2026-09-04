"""Session-mode-only HTTP routes for login, logout, and session hydration.

Mounted by ``app.py`` only when ``authentication_mode is AuthenticationMode.SESSION``
— every other mode leaves these paths returning FastAPI's normal 404, which
the web console's session hook uses to tell "auth isn't configured here"
apart from "you're not logged in" (401).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from selene_service.api import auth_services
from selene_service.api.dependencies import CurrentIdentity, DatabaseSession
from selene_service.api.schemas import (
    LoginRequest,
    ProfileUpdateRequest,
    SessionUserResponse,
    UserAccountCreateRequest,
    UserAccountPageResponse,
    UserAccountResponse,
    UserAccountUpdateRequest,
)
from selene_service.settings import ServiceSettings


def build_auth_router(settings: ServiceSettings) -> APIRouter:
    """Return the auth router bound to *settings* for cookie configuration.

    ``router`` is created fresh on every call rather than at module scope:
    a module-level router shared across calls would accumulate duplicate
    routes each time ``build_auth_router`` (and therefore ``create_app``) is
    invoked, and each route's closure would stay bound to whichever
    ``settings`` was in scope the first time it was registered, silently
    ignoring the ``settings`` passed on later calls.
    """

    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

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
    def logout_route(request: Request, session: DatabaseSession, response: Response) -> None:
        """Revoke the current session (if any) and clear the cookie."""

        cookie_value = request.cookies.get(settings.session_cookie_name)
        if cookie_value:
            try:
                session_id: UUID | None = UUID(cookie_value)
            except ValueError:
                session_id = None
            if session_id is not None:
                auth_services.logout(session, session_id)
        response.delete_cookie(key=settings.session_cookie_name, path="/")

    @router.get("/session", response_model=SessionUserResponse, operation_id="get_session")
    def session_route(session: DatabaseSession, identity: CurrentIdentity) -> SessionUserResponse:
        """Hydrate the caller's own session identity."""

        return auth_services.current_session_user(session, identity)

    @router.patch(
        "/profile",
        response_model=SessionUserResponse,
        operation_id="update_current_profile",
    )
    def update_current_profile_route(
        request: ProfileUpdateRequest,
        session: DatabaseSession,
        identity: CurrentIdentity,
    ) -> SessionUserResponse:
        """Update the signed-in operator's display name and/or password."""

        return auth_services.update_current_profile(session, identity, request)

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

    @router.get(
        "/users",
        response_model=UserAccountPageResponse,
        operation_id="list_user_accounts",
    )
    def list_users_route(
        session: DatabaseSession, identity: CurrentIdentity
    ) -> UserAccountPageResponse:
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

    return router
