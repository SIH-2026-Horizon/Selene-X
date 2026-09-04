"""Round-trip tests for ``schemas/benchmark-manifest.schema.json``.

All fixture data here is deliberately synthetic: fake product IDs, fake
``.invalid`` source URLs, and hand-picked hex digests that do not correspond
to any real file. WP-00 task 1's scope ruling forbids inventing anything that
could be mistaken for a real mission product.
"""

import json
import pathlib
from typing import Any

import jsonschema
import pytest

pytestmark = pytest.mark.unit

SCHEMA_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "schemas" / "benchmark-manifest.schema.json"
)


def _load_schema() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())
    return document


def _synthetic_file(name: str, digest_char: str) -> dict[str, Any]:
    return {
        "relative_path": f"fixtures/{name}",
        "sha256": digest_char * 64,
        "size_bytes": 32,
        "media_type": "application/octet-stream",
        "role": "data",
    }


def _synthetic_product(product_id: str) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "mission": "synthetic-mission",
        "payload_family": "OTHER",
        "role": "source",
        "split_role": "train_development",
        "source_url": f"https://example.invalid/{product_id}",
        "license": "CC0-synthetic-fixture",
        "credentials_required": [],
        "files": [_synthetic_file(f"{product_id}.bin", "a")],
    }


def _valid_manifest() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "manifest_id": "synthetic-benchmark-manifest",
        "interim": True,
        "created_utc": "2026-01-01T00:00:00Z",
        "notes": "Synthetic fixture manifest for schema tests only.",
        "products": [
            _synthetic_product("synthetic-fixture-001"),
            _synthetic_product("synthetic-fixture-002"),
            _synthetic_product("synthetic-fixture-003"),
        ],
    }


class TestSchemaStructure:
    def test_schema_is_valid_json_schema(self) -> None:
        from jsonschema.validators import validator_for

        document = _load_schema()
        validator_for(document).check_schema(document)

    def test_schema_declares_identity(self) -> None:
        document = _load_schema()
        assert document["$id"].endswith("benchmark-manifest.schema.json")
        assert document["title"]
        assert document["description"]


class TestValidManifest:
    def test_minimal_valid_manifest_validates(self) -> None:
        schema = _load_schema()
        jsonschema.validate(_valid_manifest(), schema)


class TestRequiredTopLevelFields:
    @pytest.mark.parametrize(
        "field",
        ["schema_version", "manifest_id", "interim", "created_utc", "products"],
    )
    def test_missing_required_field_is_rejected(self, field: str) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        del manifest[field]
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_extra_top_level_field_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["unexpected_field"] = "synthetic"
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_interim_as_non_boolean_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["interim"] = "true"
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)


class TestFileEntryConstraints:
    def test_sha256_not_matching_pattern_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["files"][0]["sha256"] = "not-a-valid-digest"
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_sha256_uppercase_is_rejected(self) -> None:
        """The pattern requires lowercase hex; an otherwise-valid uppercase digest fails."""
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["files"][0]["sha256"] = "A" * 64
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)


class TestStressBinConstraints:
    def test_overlap_fraction_above_one_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["stress_bins"] = {"overlap_fraction": 1.5}
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_overlap_fraction_below_zero_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["stress_bins"] = {"overlap_fraction": -0.1}
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_overlap_fraction_in_range_validates(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["stress_bins"] = {"overlap_fraction": 0.5}
        jsonschema.validate(manifest, schema)


class TestEnumConstraints:
    def test_unknown_payload_family_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["payload_family"] = "NOT_A_REAL_PAYLOAD"
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_unknown_role_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["role"] = "not_a_real_role"
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_unknown_split_role_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["split_role"] = "not_a_real_split"
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)


class TestControlUncertaintyConditionalRule:
    """The one genuinely subtle part of the schema: an ``if``/``then`` rule.

    If ``control_uncertainty_m`` is explicitly ``null``, then
    ``control_uncertainty_reason`` must be present and a non-empty string.
    These tests are written to fail if the ``if``/``then`` block were removed
    from the schema (the null/null and null/absent cases would then validate).
    """

    def test_null_uncertainty_with_null_reason_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["control_uncertainty_m"] = None
        manifest["products"][0]["control_uncertainty_reason"] = None
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_null_uncertainty_with_absent_reason_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["control_uncertainty_m"] = None
        # control_uncertainty_reason intentionally left absent.
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_null_uncertainty_with_empty_string_reason_is_rejected(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["control_uncertainty_m"] = None
        manifest["products"][0]["control_uncertainty_reason"] = ""
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(manifest, schema)

    def test_null_uncertainty_with_nonempty_reason_validates(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["control_uncertainty_m"] = None
        manifest["products"][0]["control_uncertainty_reason"] = (
            "synthetic fixture: control uncertainty deliberately not computed"
        )
        jsonschema.validate(manifest, schema)

    def test_numeric_uncertainty_needs_no_reason(self) -> None:
        schema = _load_schema()
        manifest = _valid_manifest()
        manifest["products"][0]["control_uncertainty_m"] = 2.5
        jsonschema.validate(manifest, schema)
