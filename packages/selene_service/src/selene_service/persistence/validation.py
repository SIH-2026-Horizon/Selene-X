"""Validation shared by service command boundaries before persistence."""

from __future__ import annotations

import re

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class InvalidSha256(ValueError):
    """Raised when a durable SHA-256 field is not canonical lowercase hex."""


def validate_sha256(value: str, *, field_name: str) -> str:
    """Return a canonical SHA-256 value or reject it before a database write."""

    if _SHA256_PATTERN.fullmatch(value) is None:
        raise InvalidSha256(f"{field_name} must be 64 lowercase hexadecimal characters")
    return value
