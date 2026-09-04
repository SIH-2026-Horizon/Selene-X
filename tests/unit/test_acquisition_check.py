"""Tests for ``benchmarks.scripts.acquisition_check``.

All fixture files are a few synthetic bytes created in this test module —
never anything resembling real mission data — and manifests reference them by
their real, freshly computed SHA-256 digests and sizes.
"""

from pathlib import Path
from typing import Any

import pytest
from benchmarks.scripts.acquisition_check import (
    FileCheckStatus,
    PathTraversalError,
    check_manifest_integrity,
)

from selene_core.pipeline.hashing import digest_file

pytestmark = pytest.mark.unit

_FIXTURE_A = b"synthetic fixture content alpha"
_FIXTURE_B = b"synthetic fixture content beta"


def _manifest_for(base_dir: Path, files: dict[str, bytes]) -> dict[str, Any]:
    """Build a manifest referencing files already written under base_dir."""
    file_entries = []
    for relative_name, content in files.items():
        written_path = base_dir / relative_name
        file_entries.append(
            {
                "relative_path": relative_name,
                "sha256": digest_file(written_path),
                "size_bytes": len(content),
                "media_type": "application/octet-stream",
                "role": "data",
            }
        )
    return {
        "schema_version": "1.0.0",
        "manifest_id": "synthetic-integrity-fixture",
        "interim": True,
        "created_utc": "2026-01-01T00:00:00Z",
        "products": [
            {
                "product_id": "synthetic-fixture-001",
                "mission": "synthetic-mission",
                "payload_family": "OTHER",
                "role": "source",
                "split_role": "train_development",
                "source_url": "https://example.invalid/fixture-001",
                "license": "CC0-synthetic-fixture",
                "credentials_required": [],
                "files": file_entries,
            }
        ],
    }


def _write(base_dir: Path, relative_name: str, content: bytes) -> Path:
    path = base_dir / relative_name
    path.write_bytes(content)
    return path


class TestAllFilesOk:
    def test_all_present_and_correct_are_ok(self, tmp_path: Path) -> None:
        _write(tmp_path, "alpha.bin", _FIXTURE_A)
        _write(tmp_path, "beta.bin", _FIXTURE_B)
        manifest = _manifest_for(tmp_path, {"alpha.bin": _FIXTURE_A, "beta.bin": _FIXTURE_B})

        results = check_manifest_integrity(manifest, tmp_path)

        assert len(results) == 2
        assert {result.status for result in results} == {FileCheckStatus.OK}


class TestMissingFile:
    def test_deleted_file_is_missing_others_stay_ok(self, tmp_path: Path) -> None:
        _write(tmp_path, "alpha.bin", _FIXTURE_A)
        _write(tmp_path, "beta.bin", _FIXTURE_B)
        manifest = _manifest_for(tmp_path, {"alpha.bin": _FIXTURE_A, "beta.bin": _FIXTURE_B})

        (tmp_path / "alpha.bin").unlink()

        results = check_manifest_integrity(manifest, tmp_path)
        by_path = {result.relative_path: result for result in results}

        assert by_path["alpha.bin"].status == FileCheckStatus.MISSING
        assert by_path["beta.bin"].status == FileCheckStatus.OK


class TestSizeMismatch:
    def test_truncated_file_is_size_mismatch(self, tmp_path: Path) -> None:
        _write(tmp_path, "alpha.bin", _FIXTURE_A)
        manifest = _manifest_for(tmp_path, {"alpha.bin": _FIXTURE_A})

        (tmp_path / "alpha.bin").write_bytes(_FIXTURE_A[:5])

        results = check_manifest_integrity(manifest, tmp_path)

        assert len(results) == 1
        assert results[0].status == FileCheckStatus.SIZE_MISMATCH
        assert results[0].recorded_size_bytes == len(_FIXTURE_A)
        assert results[0].actual_size_bytes == 5

    def test_extended_file_is_size_mismatch(self, tmp_path: Path) -> None:
        _write(tmp_path, "alpha.bin", _FIXTURE_A)
        manifest = _manifest_for(tmp_path, {"alpha.bin": _FIXTURE_A})

        (tmp_path / "alpha.bin").write_bytes(_FIXTURE_A + b"extra-synthetic-bytes")

        results = check_manifest_integrity(manifest, tmp_path)

        assert len(results) == 1
        assert results[0].status == FileCheckStatus.SIZE_MISMATCH


class TestChecksumMismatch:
    def test_flipped_byte_same_length_is_checksum_mismatch(self, tmp_path: Path) -> None:
        _write(tmp_path, "alpha.bin", _FIXTURE_A)
        _write(tmp_path, "beta.bin", _FIXTURE_B)
        manifest = _manifest_for(tmp_path, {"alpha.bin": _FIXTURE_A, "beta.bin": _FIXTURE_B})

        original_digest = digest_file(tmp_path / "alpha.bin")
        flipped = bytearray(_FIXTURE_A)
        flipped[0] ^= 0xFF
        assert len(flipped) == len(_FIXTURE_A)
        (tmp_path / "alpha.bin").write_bytes(bytes(flipped))
        flipped_digest = digest_file(tmp_path / "alpha.bin")
        assert flipped_digest != original_digest

        results = check_manifest_integrity(manifest, tmp_path)
        by_path = {result.relative_path: result for result in results}

        assert by_path["alpha.bin"].status == FileCheckStatus.CHECKSUM_MISMATCH
        assert by_path["alpha.bin"].recorded_sha256 == original_digest
        assert by_path["alpha.bin"].actual_sha256 == flipped_digest
        assert by_path["beta.bin"].status == FileCheckStatus.OK


class TestPathTraversalGuard:
    def test_dotdot_relative_path_is_rejected(self, tmp_path: Path) -> None:
        manifest = {
            "schema_version": "1.0.0",
            "manifest_id": "synthetic-traversal-fixture",
            "interim": True,
            "created_utc": "2026-01-01T00:00:00Z",
            "products": [
                {
                    "product_id": "synthetic-fixture-001",
                    "mission": "synthetic-mission",
                    "payload_family": "OTHER",
                    "role": "source",
                    "split_role": "train_development",
                    "source_url": "https://example.invalid/fixture-001",
                    "license": "CC0-synthetic-fixture",
                    "credentials_required": [],
                    "files": [
                        {
                            "relative_path": "../escape.bin",
                            "sha256": "c" * 64,
                            "size_bytes": 4,
                            "media_type": "application/octet-stream",
                            "role": "data",
                        }
                    ],
                }
            ],
        }

        with pytest.raises(PathTraversalError):
            check_manifest_integrity(manifest, tmp_path)

    def test_traversal_guard_does_not_resolve_outside_base_dir(self, tmp_path: Path) -> None:
        """Prove the guard actually fires rather than silently resolving.

        Plant a real file one directory above ``base_dir`` at the exact path
        ``../escape.bin`` would resolve to, so that if the guard were absent
        the check would happily report ``missing`` (or worse, ``ok``) instead
        of raising.
        """
        base_dir = tmp_path / "acquired"
        base_dir.mkdir()
        outside_file = tmp_path / "escape.bin"
        outside_file.write_bytes(b"synthetic outside content")

        manifest = {
            "schema_version": "1.0.0",
            "manifest_id": "synthetic-traversal-fixture-2",
            "interim": True,
            "created_utc": "2026-01-01T00:00:00Z",
            "products": [
                {
                    "product_id": "synthetic-fixture-002",
                    "mission": "synthetic-mission",
                    "payload_family": "OTHER",
                    "role": "source",
                    "split_role": "train_development",
                    "source_url": "https://example.invalid/fixture-002",
                    "license": "CC0-synthetic-fixture",
                    "credentials_required": [],
                    "files": [
                        {
                            "relative_path": "../escape.bin",
                            "sha256": digest_file(outside_file),
                            "size_bytes": len(b"synthetic outside content"),
                            "media_type": "application/octet-stream",
                            "role": "data",
                        }
                    ],
                }
            ],
        }

        with pytest.raises(PathTraversalError):
            check_manifest_integrity(manifest, base_dir)

    def test_absolute_relative_path_is_rejected(self, tmp_path: Path) -> None:
        manifest = {
            "schema_version": "1.0.0",
            "manifest_id": "synthetic-traversal-fixture-3",
            "interim": True,
            "created_utc": "2026-01-01T00:00:00Z",
            "products": [
                {
                    "product_id": "synthetic-fixture-003",
                    "mission": "synthetic-mission",
                    "payload_family": "OTHER",
                    "role": "source",
                    "split_role": "train_development",
                    "source_url": "https://example.invalid/fixture-003",
                    "license": "CC0-synthetic-fixture",
                    "credentials_required": [],
                    "files": [
                        {
                            "relative_path": "/etc/passwd",
                            "sha256": "d" * 64,
                            "size_bytes": 4,
                            "media_type": "application/octet-stream",
                            "role": "data",
                        }
                    ],
                }
            ],
        }

        with pytest.raises(PathTraversalError):
            check_manifest_integrity(manifest, tmp_path)
