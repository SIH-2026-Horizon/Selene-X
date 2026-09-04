"""SPICE kernel inventory validation without loading SPICE.

Coverage is declarative metadata, not evidence that a kernel was furnished or
that ``spiceypy`` successfully loaded it.  Loading/furnishing happens only in
the geometry work package.  This module makes missing time coverage a stable,
early rejection and prevents kernel paths from escaping an approved inventory
directory.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from selene_core.hashing import digest_file, is_sha256
from selene_core.types import AcquisitionInterval

__all__ = ["KernelInventoryError", "KernelRecord", "validate_kernel_inventory"]


class KernelInventoryError(ValueError):
    """A declared kernel is unsafe, differs from inventory bytes, or lacks coverage."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class KernelRecord:
    name: str
    path: Path
    sha256: str
    coverage: AcquisitionInterval
    priority: int
    status: str


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise KernelInventoryError(
            "geometry.kernel_coverage_gap", f"kernel {field} must be RFC3339 text"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KernelInventoryError(
            "geometry.kernel_coverage_gap", f"invalid kernel {field}: {value!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KernelInventoryError(
            "geometry.kernel_coverage_gap", f"kernel {field} is missing an offset"
        )
    return parsed.astimezone(UTC)


def _under(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise KernelInventoryError(
            "input.hostile_label", f"kernel path escapes inventory: {name!r}"
        ) from exc
    return candidate


def validate_kernel_inventory(
    entries: Sequence[Mapping[str, Any]], kernel_root: Path, product_time: AcquisitionInterval
) -> tuple[KernelRecord, ...]:
    """Verify local kernel bytes and require inventory coverage of product time.

    Each entry requires ``name``, ``sha256``, ``coverage_start_utc``,
    ``coverage_end_utc``, ``priority``, and ``status``. ``status`` is exactly
    ``predicted`` or ``reconstructed`` so route qualification can distinguish
    planning kernels from reconstructed orbit/attitude kernels later.
    """
    records: list[KernelRecord] = []
    names: set[str] = set()
    paths: set[Path] = set()
    for entry in entries:
        name = entry.get("name")
        sha = entry.get("sha256")
        priority = entry.get("priority")
        status = entry.get("status")
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise KernelInventoryError(
                "input.hostile_label", "kernel name must be a non-empty relative path"
            )
        if name in names:
            raise KernelInventoryError("input.label_unparseable", f"duplicate kernel name: {name}")
        if not isinstance(sha, str) or not is_sha256(sha):
            raise KernelInventoryError(
                "input.label_unparseable", f"kernel {name!r} has invalid SHA-256"
            )
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise KernelInventoryError(
                "input.label_unparseable", f"kernel {name!r} priority must be an integer"
            )
        if status not in ("predicted", "reconstructed"):
            raise KernelInventoryError(
                "input.label_unparseable",
                f"kernel {name!r} status must be predicted or reconstructed",
            )
        path = _under(kernel_root, name)
        if path in paths:
            raise KernelInventoryError(
                "input.label_unparseable", f"duplicate resolved kernel path: {name}"
            )
        if not path.is_file():
            raise KernelInventoryError("input.missing_file", f"kernel does not exist: {name}")
        if digest_file(path) != sha:
            raise KernelInventoryError(
                "input.checksum_mismatch", f"kernel checksum differs: {name}"
            )
        try:
            coverage = AcquisitionInterval(
                start_utc=_parse_time(entry.get("coverage_start_utc"), "coverage_start_utc"),
                stop_utc=_parse_time(entry.get("coverage_end_utc"), "coverage_end_utc"),
            )
        except ValueError as exc:
            raise KernelInventoryError("geometry.kernel_coverage_gap", str(exc)) from exc
        if coverage.start_utc > product_time.start_utc or coverage.stop_utc < product_time.stop_utc:
            raise KernelInventoryError(
                "geometry.kernel_coverage_gap",
                f"kernel {name!r} does not cover the product acquisition interval",
            )
        records.append(KernelRecord(name, path, sha, coverage, priority, status))
        names.add(name)
        paths.add(path)
    if not records:
        raise KernelInventoryError(
            "geometry.kernel_coverage_gap", "no SPICE kernels were furnished in the inventory"
        )
    return tuple(sorted(records, key=lambda record: (-record.priority, record.name)))
