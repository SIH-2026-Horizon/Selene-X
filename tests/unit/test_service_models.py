"""Contracts for the operator account and session ORM mapping."""

from __future__ import annotations

from uuid import uuid4

import pytest

from selene_service.persistence.models import UserAccount, UserSession


@pytest.mark.unit
def test_user_account_constructs_with_required_fields() -> None:
    subject_id = uuid4()

    account = UserAccount(
        subject_id=subject_id,
        username="dijo.benelen",
        password_hash="$argon2id$fake",  # noqa: S106 - not a real credential
        role="reviewer",
        display_name="Dijo Benelen",
        is_active=True,
        failed_login_count=0,
    )

    assert account.subject_id == subject_id
    assert account.username == "dijo.benelen"
    assert account.role == "reviewer"
    assert account.is_active is True
    assert account.failed_login_count == 0
    assert account.locked_until is None


@pytest.mark.unit
def test_user_session_constructs_with_required_fields() -> None:
    account_id = uuid4()

    session = UserSession(user_account_id=account_id)

    assert session.user_account_id == account_id
    assert session.revoked_at is None
