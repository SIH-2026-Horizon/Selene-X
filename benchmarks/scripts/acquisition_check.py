"""Benchmark product acquisition and integrity checker (WP-00 task 1).

Given a schema-valid manifest (see ``manifest.load_manifest``) and the local
directory the referenced products were acquired into, this module checks that
every file the manifest describes actually exists, has the recorded size, and
hashes to the recorded SHA-256 digest. It never raises on an individual file's
problem: a checker that crashes on the first missing file defeats its own
purpose. It checks everything and reports per-file status, the same
"record failed and rejected scenes rather than dropping them" ethos the
pipeline runner applies to scenes.

A malformed ``relative_path`` (path traversal) is a different class of
problem: it is not a filesystem state to report on, it is an attempt (or bug)
that could resolve outside ``base_dir``. That is rejected immediately with a
``PathTraversalError``, mirroring the guard in
``selene_core.pipeline.artifacts.ArtifactStore._checked_destination``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from selene_core.pipeline.hashing import digest_file, is_sha256

__all__ = [
    "FileCheckResult",
    "FileCheckStatus",
    "PathTraversalError",
    "check_manifest_integrity",
]


class FileCheckStatus(StrEnum):
    """The outcome of checking one manifest file entry against the filesystem."""

    OK = "ok"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    CHECKSUM_MISMATCH = "checksum_mismatch"


@dataclass(frozen=True, slots=True)
class FileCheckResult:
    """The result of checking a single manifest file entry.

    ``recorded_*``/``actual_*`` fields are populated only for the mismatch
    they explain; they stay ``None`` otherwise.
    """

    product_id: str
    relative_path: str
    status: FileCheckStatus
    recorded_size_bytes: int | None = None
    actual_size_bytes: int | None = None
    recorded_sha256: str | None = None
    actual_sha256: str | None = None


class PathTraversalError(ValueError):
    """Raised when a manifest ``relative_path`` attempts to escape ``base_dir``."""

    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        super().__init__(
            f"relative_path {relative_path!r} escapes base_dir; refusing to check "
            "outside the acquisition directory"
        )


def _checked_destination(base_dir: Path, relative_path: str) -> Path:
    """Resolve ``relative_path`` against ``base_dir``, rejecting escapes.

    Rejects before any filesystem resolution if ``relative_path`` is absolute
    or contains a ``..`` path component, then confirms with a resolve-based
    check as defence in depth (the same two-layer pattern used by
    ``ArtifactStore._checked_destination``).
    """
    if relative_path.startswith("/") or ".." in Path(relative_path).parts:
        raise PathTraversalError(relative_path)
    base = base_dir.resolve()
    destination = (base / relative_path).resolve()
    if not destination.is_relative_to(base):
        raise PathTraversalError(relative_path)
    return destination


def _check_file(product_id: str, base_dir: Path, file_entry: dict[str, Any]) -> FileCheckResult:
    relative_path: str = file_entry["relative_path"]
    recorded_size: int = file_entry["size_bytes"]
    recorded_sha256: str = file_entry["sha256"]
    assert is_sha256(recorded_sha256), (
        f"manifest file entry for {relative_path!r} carries a malformed sha256; "
        "load_manifest should have rejected this before check_manifest_integrity ran"
    )

    destination = _checked_destination(base_dir, relative_path)

    if not destination.is_file():
        return FileCheckResult(product_id, relative_path, FileCheckStatus.MISSING)

    actual_size = destination.stat().st_size
    if actual_size != recorded_size:
        return FileCheckResult(
            product_id,
            relative_path,
            FileCheckStatus.SIZE_MISMATCH,
            recorded_size_bytes=recorded_size,
            actual_size_bytes=actual_size,
        )

    actual_sha256 = digest_file(destination)
    assert is_sha256(actual_sha256)
    if actual_sha256 != recorded_sha256:
        return FileCheckResult(
            product_id,
            relative_path,
            FileCheckStatus.CHECKSUM_MISMATCH,
            recorded_sha256=recorded_sha256,
            actual_sha256=actual_sha256,
        )

    return FileCheckResult(product_id, relative_path, FileCheckStatus.OK)


def check_manifest_integrity(
    manifest: dict[str, Any], base_dir: Path
) -> tuple[FileCheckResult, ...]:
    """Check every product file a manifest references against the filesystem.

    Args:
        manifest: A manifest dict already validated by ``manifest.load_manifest``
            (this function trusts its shape: it does not re-run schema
            validation, and only reports on the referenced files' filesystem
            state).
        base_dir: The local directory the manifest's products were acquired
            into. Every ``relative_path`` is resolved against this directory.

    Returns:
        One :class:`FileCheckResult` per file entry across all products, in
        manifest order.

    Raises:
        PathTraversalError: If any file entry's ``relative_path`` attempts to
            escape ``base_dir``. Raised as soon as such an entry is reached,
            unlike missing/size/checksum problems, which are per-file
            filesystem states reported in the returned tuple rather than
            raised.
    """
    results: list[FileCheckResult] = []
    for product in manifest["products"]:
        product_id: str = product["product_id"]
        for file_entry in product["files"]:
            results.append(_check_file(product_id, base_dir, file_entry))
    return tuple(results)
