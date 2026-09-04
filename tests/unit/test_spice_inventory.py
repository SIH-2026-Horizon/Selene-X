"""Local SPICE inventory checks; no kernel is furnished or loaded in tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from selene_core.ingest.spice_inventory import KernelInventoryError, validate_kernel_inventory
from selene_core.types import AcquisitionInterval

pytestmark = pytest.mark.unit


def _time() -> AcquisitionInterval:
    return AcquisitionInterval(
        start_utc=datetime(2021, 1, 1, 0, 0, tzinfo=UTC),
        stop_utc=datetime(2021, 1, 1, 0, 1, tzinfo=UTC),
    )


def test_inventory_checks_hash_status_priority_and_acquisition_coverage(tmp_path: Path) -> None:
    content = b"synthetic only; not an operational SPICE kernel"
    (tmp_path / "orbit.bsp").write_bytes(content)
    records = validate_kernel_inventory(
        [
            {
                "name": "orbit.bsp",
                "sha256": hashlib.sha256(content).hexdigest(),
                "coverage_start_utc": "2020-12-31T00:00:00Z",
                "coverage_end_utc": "2021-01-02T00:00:00Z",
                "priority": 10,
                "status": "reconstructed",
            }
        ],
        tmp_path,
        _time(),
    )
    assert records[0].status == "reconstructed"


def test_inventory_rejects_missing_coverage_interval(tmp_path: Path) -> None:
    content = b"synthetic"
    (tmp_path / "orbit.bsp").write_bytes(content)
    with pytest.raises(KernelInventoryError) as excinfo:
        validate_kernel_inventory(
            [
                {
                    "name": "orbit.bsp",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "coverage_start_utc": "2021-01-01T00:00:30Z",
                    "coverage_end_utc": "2021-01-01T00:02:00Z",
                    "priority": 1,
                    "status": "predicted",
                }
            ],
            tmp_path,
            _time(),
        )
    assert excinfo.value.reason == "geometry.kernel_coverage_gap"


def test_inventory_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(KernelInventoryError) as excinfo:
        validate_kernel_inventory(
            [
                {
                    "name": "../outside.bsp",
                    "sha256": "0" * 64,
                    "coverage_start_utc": "2020-12-31T00:00:00Z",
                    "coverage_end_utc": "2021-01-02T00:00:00Z",
                    "priority": 1,
                    "status": "predicted",
                }
            ],
            tmp_path,
            _time(),
        )
    assert excinfo.value.reason == "input.hostile_label"


def test_inventory_normalizes_offset_coverage_to_utc(tmp_path: Path) -> None:
    content = b"synthetic"
    (tmp_path / "orbit.bsp").write_bytes(content)
    records = validate_kernel_inventory(
        [
            {
                "name": "orbit.bsp",
                "sha256": hashlib.sha256(content).hexdigest(),
                "coverage_start_utc": "2021-01-01T05:00:00+05:00",
                "coverage_end_utc": "2021-01-01T06:01:00+05:00",
                "priority": 1,
                "status": "predicted",
            }
        ],
        tmp_path,
        _time(),
    )
    assert records[0].coverage.start_utc.tzinfo is UTC


def test_inventory_rejects_duplicate_resolved_kernel_path(tmp_path: Path) -> None:
    content = b"synthetic"
    kernel = tmp_path / "orbit.bsp"
    kernel.write_bytes(content)
    (tmp_path / "alias.bsp").symlink_to(kernel.name)
    entry = {
        "sha256": hashlib.sha256(content).hexdigest(),
        "coverage_start_utc": "2020-12-31T00:00:00Z",
        "coverage_end_utc": "2021-01-02T00:00:00Z",
        "priority": 1,
        "status": "predicted",
    }
    with pytest.raises(KernelInventoryError, match="duplicate resolved"):
        validate_kernel_inventory(
            [{**entry, "name": "orbit.bsp"}, {**entry, "name": "alias.bsp"}], tmp_path, _time()
        )
