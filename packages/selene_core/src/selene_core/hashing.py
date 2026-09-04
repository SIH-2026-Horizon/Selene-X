"""Content and provenance hashing (ADR-0006).

Resume, audit, and claim traceability all rest on one question: are two things
the same? This module answers it in exactly one way, so that a fingerprint
computed during a run and a fingerprint recomputed a year later agree.

The canonical form is UTF-8 JSON with sorted keys, no insignificant whitespace,
and no non-finite floats. Floats are serialised with ``repr`` round-tripping, so
a value that survives a JSON round trip hashes identically.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

__all__ = [
    "EMPTY_DIGEST",
    "canonical_json",
    "digest_file",
    "digest_json",
    "digest_many",
    "is_sha256",
]

_CHUNK_BYTES: Final = 1024 * 1024

EMPTY_DIGEST: Final = hashlib.sha256(b"").hexdigest()
"""The SHA-256 of zero bytes. An empty artefact still has an identity."""


def canonical_json(value: Any) -> str:
    """Serialise ``value`` to the canonical JSON form used for hashing.

    Args:
        value: Any JSON-serialisable structure.

    Returns:
        A deterministic JSON string.

    Raises:
        ValueError: If the structure contains a non-finite float. NaN and the
            infinities are not JSON, and accepting them would let two
            meaningfully different results share a fingerprint.
    """
    return json.dumps(
        _normalise(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _normalise(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"cannot hash the non-finite float {value!r}; represent a missing value as "
                "null with a reason instead"
            )
        return value
    if isinstance(value, str | int | bool) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [_normalise(item) for item in value]
    raise TypeError(f"cannot canonicalise {type(value).__name__} for hashing")


def digest_json(value: Any) -> str:
    """Return the SHA-256 hex digest of ``value`` in canonical JSON form."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes.

    Streamed, because mission products do not fit in memory and this function is
    used on them.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def digest_many(digests: Sequence[str]) -> str:
    """Combine several digests into one, order-independently.

    Used where a result depends on a *set* of inputs whose enumeration order is
    incidental. Sorting first means two runs that discovered the same inputs in
    different orders still resume from each other.
    """
    for digest in digests:
        if not is_sha256(digest):
            raise ValueError(f"not a SHA-256 hex digest: {digest!r}")
    return digest_json(sorted(digests))


def is_sha256(value: str) -> bool:
    """Whether ``value`` is a lowercase 64-character hex digest."""
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
