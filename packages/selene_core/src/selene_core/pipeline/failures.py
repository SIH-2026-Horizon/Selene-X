"""Re-export shim: the failure taxonomy now lives in :mod:`selene_core.errors`.

Kept so the existing ``selene_core.pipeline.failures`` import surface (used
throughout ``pipeline/`` and by existing tests) needs no changes.
"""

from __future__ import annotations

from selene_core.errors import (
    FailureCategory,
    FailureCode,
    FailureDefinition,
    definition_for,
    is_retryable,
)

__all__ = [
    "FailureCategory",
    "FailureCode",
    "FailureDefinition",
    "definition_for",
    "is_retryable",
]
