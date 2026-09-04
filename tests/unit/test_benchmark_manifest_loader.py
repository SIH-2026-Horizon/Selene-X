"""Tests for ``benchmarks.scripts.manifest.load_manifest``.

Fixture manifests are written to ``tmp_path`` and use only obviously synthetic
values (fake product IDs, ``.invalid`` URLs, placeholder digests).
"""

import json
from pathlib import Path
from typing import Any

import pytest
from benchmarks.scripts.manifest import ManifestValidationError, SplitIntegrityError, load_manifest

pytestmark = pytest.mark.unit


def _valid_manifest_dict() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "manifest_id": "synthetic-loader-fixture",
        "interim": True,
        "created_utc": "2026-01-01T00:00:00Z",
        "products": [
            {
                "product_id": "synthetic-fixture-001",
                "mission": "synthetic-mission",
                "payload_family": "OTHER",
                "role": "source",
                "split_role": "train_development",
                "terrain_group": "synthetic-loader-terrain-a",
                "source_url": "https://example.invalid/fixture-001",
                "license": "CC0-synthetic-fixture",
                "credentials_required": [],
                "files": [
                    {
                        "relative_path": "fixtures/fixture-001.bin",
                        "sha256": "b" * 64,
                        "size_bytes": 16,
                        "media_type": "application/octet-stream",
                        "role": "data",
                    }
                ],
            }
        ],
    }


def _write_manifest(path: Path, document: dict[str, Any]) -> Path:
    manifest_path = path / "manifest.json"
    manifest_path.write_text(json.dumps(document))
    return manifest_path


class TestLoadManifestSuccess:
    def test_valid_manifest_returns_parsed_dict(self, tmp_path: Path) -> None:
        document = _valid_manifest_dict()
        manifest_path = _write_manifest(tmp_path, document)

        loaded = load_manifest(manifest_path)

        assert loaded == document


class TestLoadManifestFailure:
    def test_missing_required_field_raises_with_identifying_message(self, tmp_path: Path) -> None:
        document = _valid_manifest_dict()
        del document["manifest_id"]
        manifest_path = _write_manifest(tmp_path, document)

        with pytest.raises(ManifestValidationError) as excinfo:
            load_manifest(manifest_path)

        message = str(excinfo.value)
        assert "manifest_id" in message
        assert excinfo.value.validator_message
        assert "manifest_id" in excinfo.value.validator_message

    def test_conditional_rule_violation_raises_with_identifying_message(
        self, tmp_path: Path
    ) -> None:
        document = _valid_manifest_dict()
        document["products"][0]["control_uncertainty_m"] = None
        manifest_path = _write_manifest(tmp_path, document)

        with pytest.raises(ManifestValidationError) as excinfo:
            load_manifest(manifest_path)

        assert "control_uncertainty_reason" in str(excinfo.value)

    def test_ungrouped_protected_source_is_rejected(self, tmp_path: Path) -> None:
        document = _valid_manifest_dict()
        document["products"][0]["terrain_group"] = None
        manifest_path = _write_manifest(tmp_path, document)

        with pytest.raises(SplitIntegrityError, match="terrain_group"):
            load_manifest(manifest_path)

    def test_cross_split_terrain_group_is_rejected(self, tmp_path: Path) -> None:
        document = _valid_manifest_dict()
        duplicate = document["products"][0].copy()
        duplicate["product_id"] = "synthetic-fixture-002"
        duplicate["split_role"] = "held_out_test"
        duplicate["files"] = [
            {
                **duplicate["files"][0],
                "relative_path": "fixtures/fixture-002.bin",
            }
        ]
        document["products"].append(duplicate)
        manifest_path = _write_manifest(tmp_path, document)

        with pytest.raises(SplitIntegrityError, match="span protected"):
            load_manifest(manifest_path)

    def test_duplicate_product_id_is_rejected(self, tmp_path: Path) -> None:
        document = _valid_manifest_dict()
        document["products"].append(document["products"][0].copy())
        manifest_path = _write_manifest(tmp_path, document)

        with pytest.raises(SplitIntegrityError, match="product_id values must be unique"):
            load_manifest(manifest_path)
