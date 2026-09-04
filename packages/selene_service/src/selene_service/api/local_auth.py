"""Local API-key bootstrap and verification for the packaged single-user stack."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from selene_service.api.errors import APIProblem
from selene_service.persistence.models import ApiKey, Subject
from selene_service.settings import AuthenticationMode, ServiceSettings

LOCAL_PLATFORM_KEY_LABEL = "local-platform-web-proxy"
LOCAL_PLATFORM_SUBJECT_TYPE = "local"
SERVICE_WRITE_SCOPE = "service:write"


def digest_api_key(value: str) -> str:
    """Return the only representation of an API credential stored in PostgreSQL."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bootstrap_local_api_key(
    session_factory: Callable[[], Session],
    settings: ServiceSettings,
) -> None:
    """Idempotently bind the configured local secret to one durable subject.

    This is used exclusively by the loopback-only Compose profile. The raw key
    remains in the ignored Compose environment and is never persisted, logged,
    or returned by the service. Replacing the configured key revokes the prior
    active local-proxy key before adding the replacement digest.
    """

    if (
        settings.authentication_mode
        not in (AuthenticationMode.EXTERNAL, AuthenticationMode.SESSION)
        or settings.local_api_key is None
    ):
        return

    key_digest = digest_api_key(settings.local_api_key.get_secret_value())
    session = session_factory()
    try:
        with session.begin():
            subject = session.scalar(
                select(Subject).where(Subject.subject_name == settings.local_api_key_subject)
            )
            if subject is None:
                subject = Subject(
                    subject_name=settings.local_api_key_subject,
                    subject_type=LOCAL_PLATFORM_SUBJECT_TYPE,
                    is_active=True,
                )
                session.add(subject)
                session.flush()
            elif subject.subject_type != LOCAL_PLATFORM_SUBJECT_TYPE or not subject.is_active:
                raise RuntimeError("Configured local API subject is not an active local subject")

            existing = session.scalar(select(ApiKey).where(ApiKey.key_digest == key_digest))
            if existing is not None and (
                existing.subject_id != subject.id or existing.label != LOCAL_PLATFORM_KEY_LABEL
            ):
                raise RuntimeError(
                    "Configured local API key is already bound to another credential"
                )

            session.execute(
                update(ApiKey)
                .where(
                    ApiKey.label == LOCAL_PLATFORM_KEY_LABEL,
                    ApiKey.revoked_at.is_(None),
                    ApiKey.key_digest != key_digest,
                )
                .values(revoked_at=datetime.now(UTC))
            )
            if existing is None:
                session.add(
                    ApiKey(
                        subject_id=subject.id,
                        key_digest=key_digest,
                        label=LOCAL_PLATFORM_KEY_LABEL,
                        scopes=[SERVICE_WRITE_SCOPE],
                    )
                )
            else:
                session.execute(
                    update(ApiKey)
                    .where(ApiKey.id == existing.id)
                    .values(
                        scopes=[SERVICE_WRITE_SCOPE],
                        revoked_at=None,
                        expires_at=None,
                    )
                )
    finally:
        session.close()


def authenticate_api_key(session: Session, presented_key: str) -> tuple[str, str]:
    """Resolve an active write-capable local credential to its durable subject."""

    credential = session.scalar(
        select(ApiKey).where(ApiKey.key_digest == digest_api_key(presented_key))
    )
    if credential is None or credential.revoked_at is not None:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    if credential.expires_at is not None and credential.expires_at <= datetime.now(UTC):
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    if SERVICE_WRITE_SCOPE not in credential.scopes:
        raise APIProblem(403, "forbidden", "The request is not permitted.")

    subject = session.get(Subject, credential.subject_id)
    if subject is None or not subject.is_active:
        raise APIProblem(401, "unauthorized", "Authentication is required.")
    return subject.subject_name, subject.subject_type
