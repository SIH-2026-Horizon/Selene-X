"""Argon2 password hashing for operator accounts.

Never reuse ``selene_service.api.local_auth.digest_api_key`` (SHA-256) here —
that digest is for comparing a supplied API key against a stored value in
constant time, not for storing a human-chosen secret. Argon2id is memory-hard
and salted per call, which SHA-256 is neither.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_HASHER = PasswordHasher()


def hash_password(raw: str) -> str:
    """Return a salted Argon2id hash string; never the raw password."""

    return _HASHER.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """Return whether *raw* matches *hashed*, without raising on bad input."""

    try:
        return _HASHER.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
