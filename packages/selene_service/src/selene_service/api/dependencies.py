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
    mutating request. Session-mode deployments accept only a live session
    cookie; they must never fall through to a shared proxy API key, which
    would bypass the account role attached to a browser request.
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
        raise APIProblem(401, "unauthorized", "Authentication is required.")

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
