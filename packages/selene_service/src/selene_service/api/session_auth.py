"""Server-side operator sessions, login, lockout, and Admin bootstrap.

Mirrors ``selene_service.api.local_auth``'s bootstrap pattern: an idempotent
upsert driven by env-configured settings, called from the app's lifespan
hook. Unlike that module, credentials here are human-chosen passwords, so
they are Argon2-hashed (``password_auth``), never SHA-256-digested.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from selene_service.api.errors import APIProblem
from selene_service.api.password_auth import hash_password, verify_password
from selene_service.persistence.models import Subject, UserAccount, UserSession
from selene_service.settings import ServiceSettings

_UNAUTHORIZED_MESSAGE = "The username or password is incorrect."
_BOOTSTRAP_SUBJECT_TYPE = "user"


def bootstrap_admin_user(
    session_factory: Callable[[], Session],
    settings: ServiceSettings,
) -> None:
    """Idempotently create the first Admin account from configured settings.

    A no-op unless both ``bootstrap_admin_username`` and
    ``bootstrap_admin_password`` are set. Never overwrites an existing
    account's password or role on a later restart with different env values
    — that would silently change a live account out from under an operator
    who has since changed it. Rotate a bootstrap admin's password through
    the normal Admin-reset path, not by editing the environment.
    """

    if settings.bootstrap_admin_username is None or settings.bootstrap_admin_password is None:
        return

    username = settings.bootstrap_admin_username.strip().casefold()
    session = session_factory()
    try:
        with session.begin():
            existing = session.scalar(select(UserAccount).where(UserAccount.username == username))
            if existing is not None:
                return

            subject = Subject(
                subject_name=f"user:{username}",
                subject_type=_BOOTSTRAP_SUBJECT_TYPE,
                is_active=True,
            )
            session.add(subject)
            session.flush()
            session.add(
                UserAccount(
                    subject_id=subject.id,
                    username=username,
                    password_hash=hash_password(
                        settings.bootstrap_admin_password.get_secret_value()
                    ),
                    role="admin",
                    display_name=settings.bootstrap_admin_username,
                )
            )
    finally:
        session.close()


def authenticate_with_password(
    session: Session,
    username: str,
    password: str,
    settings: ServiceSettings,
) -> UserAccount:
    """Return the matching active, unlocked account or raise 401.

    The failure message never reveals whether the username exists, whether
    the password was wrong, or whether the account is locked — all three
    return the identical 401 (ADR-0016 Verification: no username
    enumeration).
    """

    normalized = username.strip().casefold()
    account = session.scalar(select(UserAccount).where(UserAccount.username == normalized))
    if account is None:
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)
    if not account.is_active:
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)
    if account.locked_until is not None and account.locked_until > datetime.now(UTC):
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)

    if not verify_password(password, account.password_hash):
        record_login_failure(session, account, settings)
        raise APIProblem(401, "unauthorized", _UNAUTHORIZED_MESSAGE)

    record_login_success(session, account)
    return account


def record_login_failure(
    session: Session, user_account: UserAccount, settings: ServiceSettings
) -> None:
    """Increment the failure counter and lock the account past the threshold."""

    user_account.failed_login_count += 1
    if user_account.failed_login_count >= settings.login_lockout_threshold:
        user_account.locked_until = datetime.now(UTC) + timedelta(
            seconds=settings.login_lockout_seconds
        )
    session.add(user_account)
    session.flush()


def record_login_success(session: Session, user_account: UserAccount) -> None:
    """Reset lockout state and stamp the login time."""

    user_account.failed_login_count = 0
    user_account.locked_until = None
    user_account.last_login_at = datetime.now(UTC)
    session.add(user_account)
    session.flush()


def create_session(
    session: Session, user_account: UserAccount, settings: ServiceSettings
) -> UserSession:
    """Create and persist one new server-side session for *user_account*."""

    row = UserSession(
        user_account_id=user_account.id,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.session_ttl_seconds),
    )
    session.add(row)
    session.flush()
    return row


def resolve_session(session: Session, session_id: UUID) -> tuple[UserAccount, Subject] | None:
    """Return the (account, subject) pair for a live session, else ``None``."""

    row = session.get(UserSession, session_id)
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        return None
    account = session.get(UserAccount, row.user_account_id)
    if account is None or not account.is_active:
        return None
    subject = session.get(Subject, account.subject_id)
    if subject is None or not subject.is_active:
        return None
    return account, subject


def revoke_session(session: Session, session_id: UUID) -> None:
    """Revoke a session; a no-op if it does not exist or is already revoked."""

    row = session.get(UserSession, session_id)
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = datetime.now(UTC)
    session.add(row)
    session.flush()
