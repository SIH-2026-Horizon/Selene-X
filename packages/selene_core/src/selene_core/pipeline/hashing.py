"""Re-export shim: content hashing now lives in :mod:`selene_core.hashing`.

Kept so the existing ``selene_core.pipeline.hashing`` import surface (used
throughout ``pipeline/`` and by existing tests) needs no changes.
"""

from __future__ import annotations

from selene_core.hashing import (
    EMPTY_DIGEST,
    canonical_json,
    digest_file,
    digest_json,
    digest_many,
    is_sha256,
)

__all__ = [
    "EMPTY_DIGEST",
    "canonical_json",
    "digest_file",
    "digest_json",
    "digest_many",
    "is_sha256",
]
