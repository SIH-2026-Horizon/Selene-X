"""Runtime validation for the repository's Draft 2020-12 contracts.

``jsonschema`` intentionally leaves ``format`` annotations opt-in.  SELENE-XR
does not: a timestamp in a persisted failure or provenance record is scientific
provenance, so it is checked with the same validator wherever a schema document
is used at runtime.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

__all__ = ["RFC3339_FORMAT_CHECKER", "build_validator", "validate_instance"]

_RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)

RFC3339_FORMAT_CHECKER = FormatChecker()
"""The required format checker for every persisted JSON contract."""


@RFC3339_FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: object) -> bool:
    """Return whether ``value`` is an actual timezone-aware RFC3339 instant."""
    if not isinstance(value, str) or _RFC3339_DATETIME.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def build_validator(schema: Mapping[str, Any]) -> Draft202012Validator:
    """Build the only validator used for SELENE-XR JSON schema documents.

    Invalid schema documents fail before their instances are accepted, and
    ``date-time`` values are checked with :data:`RFC3339_FORMAT_CHECKER` rather
    than treated as advisory annotations.
    """
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=RFC3339_FORMAT_CHECKER)


def validate_instance(instance: object, schema: Mapping[str, Any]) -> None:
    """Validate one JSON-compatible instance with mandatory format checking."""
    build_validator(schema).validate(instance)
