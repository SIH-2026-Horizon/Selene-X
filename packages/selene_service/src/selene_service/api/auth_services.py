"""Business logic for login, logout, session hydration, and account management."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from selene_service.api.dependencies import SubjectIdentity
from selene_service.api.errors import APIProblem, BadRequestProblem, NotFoundProblem
from selene_service.api.password_auth import hash_password, verify_password
from selene_service.api.schemas import (
    LoginRequest,
    ProfileUpdateRequest,
    SessionUserResponse,
    UserAccountCreateRequest,
    UserAccountPageResponse,
    UserAccountResponse,
    UserAccountUpdateRequest,
)
from selene_service.api.session_auth import (
    authenticate_with_password,
    create_session,
    revoke_session,
)
from selene_service.persistence.models import Subject, UserAccount
from selene_service.settings import ServiceSettings


def login(
    session: Session, request: LoginRequest, settings: ServiceSettings
) -> tuple[SessionUserResponse, UUID]:
    """Authenticate and return the public session-user view plus a new session id.

    A failed attempt's lockout bookkeeping (``record_login_failure``, inside
    ``authenticate_with_password``) must survive even though the request
    itself ends in a raised ``APIProblem`` — so that ``APIProblem`` is caught
    *inside* the ``with session.begin():`` block (letting the block exit
    normally and commit whatever was already flushed) and re-raised only
    after the transaction has closed. Letting the exception propagate
    straight out of the block would roll the whole transaction back,
    silently discarding the failure count and lockout timestamp along with
    it — see ADR-0016 Verification and the final-review finding this fixes.
    """

    auth_failure: APIProblem | None = None
    result: tuple[UserAccount, UUID] | None = None
    with session.begin():
        try:
            account = authenticate_with_password(
                session, request.username, request.password, settings
            )
        except APIProblem as problem:
            auth_failure = problem
        else:
            session_row = create_session(session, account, settings)
            session.flush()
            result = (account, session_row.id)

    if auth_failure is not None:
        raise auth_failure
    if result is None:
        # Unreachable in practice: authenticate_with_password either raises
        # or returns an account, so the transaction above always sets
        # exactly one of auth_failure or result. Guards against a silent
        # None return if that invariant is ever broken by a future edit.
        raise APIProblem(500, "internal_error", "Login failed unexpectedly.")
    account, session_id = result
    return _session_user_response(account), session_id


def current_session_user(session: Session, identity: SubjectIdentity) -> SessionUserResponse:
    """Return the caller's session identity, or 401 if this isn't a session caller."""

    if identity.role is None or identity.user_account_id is None:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    account = session.get(UserAccount, identity.user_account_id)
    if account is None:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    return _session_user_response(account)


def update_current_profile(
    session: Session,
    identity: SubjectIdentity,
    request: ProfileUpdateRequest,
) -> SessionUserResponse:
    """Persist the authenticated operator's editable profile fields.

    The role is intentionally absent from this operation.  Password changes
    additionally require the current password so a stolen but still-live
    browser session cannot silently replace an operator's credential.
    """

    if identity.user_account_id is None:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    with session.begin():
        account = session.get(UserAccount, identity.user_account_id)
        if account is None or not account.is_active:
            raise APIProblem(401, "unauthorized", "Authentication is required.")
        if request.new_password is not None:
            if request.current_password is None or not verify_password(
                request.current_password, account.password_hash
            ):
                raise APIProblem(401, "unauthorized", "Current password is incorrect.")
            account.password_hash = hash_password(request.new_password)
        if request.display_name is not None:
            account.display_name = request.display_name
        session.add(account)
        session.flush()
        session.refresh(account)
        return _session_user_response(account)


def logout(session: Session, session_id: UUID) -> None:
    """Revoke the caller's current session."""

    with session.begin():
        revoke_session(session, session_id)


def _session_user_response(account: UserAccount) -> SessionUserResponse:
    return SessionUserResponse(
        username=account.username,
        display_name=account.display_name,
        role=account.role,  # type: ignore[arg-type]
    )


def _require_admin(identity: SubjectIdentity) -> None:
    if identity.role != "admin":
        raise APIProblem(403, "forbidden", "The request is not permitted.")


def create_user_account(
    session: Session, identity: SubjectIdentity, request: UserAccountCreateRequest
) -> UserAccountResponse:
    """Create a new operator account; Admin-only, never self-service."""

    _require_admin(identity)
    with session.begin():
        normalized = request.username.strip().casefold()
        existing = session.scalar(select(UserAccount).where(UserAccount.username == normalized))
        if existing is not None:
            raise BadRequestProblem("That username is already taken.")
        subject = Subject(subject_name=f"user:{normalized}", subject_type="user", is_active=True)
        session.add(subject)
        session.flush()
        account = UserAccount(
            subject_id=subject.id,
            username=normalized,
            password_hash=hash_password(request.password),
            role=request.role,
            display_name=request.display_name,
            is_active=True,
            created_by_user_account_id=identity.user_account_id,
        )
        session.add(account)
        session.flush()
        session.refresh(account)
        return _account_response(account)


def list_user_accounts(session: Session, identity: SubjectIdentity) -> UserAccountPageResponse:
    """List every operator account; Admin-only."""

    _require_admin(identity)
    accounts = session.scalars(select(UserAccount).order_by(UserAccount.username)).all()
    return UserAccountPageResponse(items=[_account_response(account) for account in accounts])


def update_user_account(
    session: Session,
    identity: SubjectIdentity,
    target_account_id: UUID,
    request: UserAccountUpdateRequest,
) -> UserAccountResponse:
    """Update an account's role, activity, or password; Admin-only.

    Never permits a session to change its own role — a role change always
    targets a different account (ADR-0016 Alternatives considered: no
    endpoint lets a session change its own role). Self-targeted updates that
    do not touch ``role`` (e.g. an Admin rotating their own password, or
    toggling their own ``is_active``) are permitted.
    """

    _require_admin(identity)
    if target_account_id == identity.user_account_id and request.role is not None:
        raise APIProblem(403, "forbidden", "An account cannot change its own role.")
    with session.begin():
        account = session.get(UserAccount, target_account_id)
        if account is None:
            raise NotFoundProblem("No such operator account.")
        if request.role is not None:
            account.role = request.role
        if request.is_active is not None:
            account.is_active = request.is_active
        if request.new_password is not None:
            account.password_hash = hash_password(request.new_password)
        session.add(account)
        session.flush()
        session.refresh(account)
        return _account_response(account)


def _account_response(account: UserAccount) -> UserAccountResponse:
    return UserAccountResponse(
        id=account.id,
        username=account.username,
        display_name=account.display_name,
        role=account.role,  # type: ignore[arg-type]
        is_active=account.is_active,
    )
