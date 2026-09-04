"""Checks over the concrete JSON Schema contracts in ``schemas/``."""

import json
import pathlib
from typing import Any

import jsonschema
import pytest
from jsonschema.validators import validator_for

from selene_core.errors import FailureCode, definition_for
from selene_core.schema_validation import validate_instance

SCHEMA_DIR = pathlib.Path(__file__).resolve().parents[2] / "schemas"

REQUIRED_SCHEMAS = [
    "failure-envelope",
    "metric-report",
    "parameter-set",
    "product-input-manifest",
    "provenance-manifest",
    "reference-bundle-manifest",
]

_SHA256 = "a" * 64

VALID_EXAMPLES: dict[str, dict[str, Any]] = {
    "parameter-set": {
        "schema_version": "1",
        "parameter_set_id": "phase-correlation-defaults",
        "version": "1.0.0",
        "parameters": {"matching": {"window_size_px": 32, "minimum_score": 0.8}},
    },
    "product-input-manifest": {
        "schema_version": "1",
        "product_id": "OHRC-demo-001",
        "payload_family": "OHRC",
        "files": [
            {
                "relative_path": "products/demo.tif",
                "sha256": _SHA256,
                "size_bytes": 1,
                "media_type": "image/tiff",
                "role": "data",
            }
        ],
        "calibration_state": "unknown",
        "acquisition": {"start_utc": "2026-08-29T00:00:00Z", "end_utc": "2026-08-29T00:01:00Z"},
        "raster": {"shape": [1024, 1024], "dtype": "uint16"},
        "geometry_adapter": {
            "name": "metadata-only",
            "version": "1",
            "status": "unvalidated",
            "note": "No validated sensor model yet.",
        },
        "frame": {"name": "MOON_ME", "status": "unknown", "note": "Label did not declare it."},
        "projection": {"name": "unprojected", "status": "not_applicable"},
        "datum_realisation": {"name": "unknown", "status": "unknown", "note": "No datum label."},
        "geometry_validation": {"validated": False, "note": "No validated sensor model yet."},
    },
    "reference-bundle-manifest": {
        "schema_version": "1",
        "bundle_id": "regional-reference-v1",
        "image_references": [
            {
                "source_id": "reference-image",
                "version": "v1",
                "uri": "archive/reference.tif",
                "sha256": _SHA256,
                "role": "image",
                "crs_wkt": 'LOCAL_CS["Moon"]',
                "units": "reflectance",
            }
        ],
        "coverage_masks": [
            {
                "source_id": "coverage-mask",
                "version": "v1",
                "uri": "archive/mask.tif",
                "sha256": _SHA256,
                "role": "coverage_mask",
                "crs_wkt": 'LOCAL_CS["Moon"]',
                "units": None,
            }
        ],
    },
    "metric-report": {
        "schema_version": "1",
        "report_id": "scene-001",
        "scope": "scene",
        "product_id": "OHRC-demo-001",
        "computed_utc": "2026-08-29T00:00:00Z",
        "metrics": [
            {
                "name": "withheld_rmse_2d_px",
                "value": None,
                "units": "px",
                "reason": "No withheld control points were available.",
                "evidence_source": "withheld_check_points",
            }
        ],
    },
    "provenance-manifest": {
        "schema_version": "1",
        "manifest_id": "run-001",
        "created_utc": "2026-08-29T00:00:00Z",
        "artifacts": [
            {
                "relative_path": "outputs/matches.json",
                "sha256": _SHA256,
                "size_bytes": 1,
                "media_type": "application/json",
            }
        ],
        "inputs": [{"input_id": "OHRC-demo-001", "version": "v1", "sha256": _SHA256}],
        "reference_bundle": {"id": "regional-reference-v1", "version": "v1"},
        "control": {"status": "unavailable", "none_reason": "No independent control is bundled."},
        "parameters": {
            "parameter_set_id": "phase-correlation-defaults",
            "version": "1.0.0",
            "values": {"matching": {"window_size_px": 32}},
        },
        "models": {"none_reason": "This route has no learned model."},
        "dependencies": [{"name": "numpy", "version": "2.0.0"}],
        "code_revision": "abc123",
        "environment": {
            "python_version": "3.12",
            "platform": "Linux",
            "dependency_versions": {"numpy": "2.0.0"},
        },
        "environment_id": _SHA256,
        "limitations": ["Geometry has not been validated."],
    },
    "failure-envelope": {
        "stage_name": "matching",
        "code": "matching.insufficient_candidates",
        "message": "No candidates survived filtering.",
        "retryable": False,
        "remediation": (
            "Check illumination difference, GSD ratio, and eligible area in the preflight "
            "report. This scene may be outside every qualified route."
        ),
        "occurred_utc": "2026-08-29T00:00:00Z",
    },
}


def _load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    return document


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_SCHEMAS)
def test_required_schema_file_exists(name: str) -> None:
    assert (SCHEMA_DIR / f"{name}.schema.json").is_file()


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_SCHEMAS)
def test_schema_is_a_valid_json_schema_document(name: str) -> None:
    document = _load(name)
    validator_for(document).check_schema(document)


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_SCHEMAS)
def test_schema_declares_identity(name: str) -> None:
    document = _load(name)
    assert str(document["$id"]).endswith(f"{name}.schema.json")
    assert document["title"]
    assert document["description"]


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_SCHEMAS)
def test_schema_accepts_a_minimal_real_contract(name: str) -> None:
    document = _load(name)
    validate_instance(VALID_EXAMPLES[name], document)


@pytest.mark.unit
@pytest.mark.parametrize("name", REQUIRED_SCHEMAS)
def test_schema_rejects_an_unknown_top_level_field(name: str) -> None:
    document = _load(name)
    instance = {**VALID_EXAMPLES[name], "unknown_scientific_parameter": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, document)


@pytest.mark.unit
def test_parameter_schema_rejects_unknown_nested_parameter() -> None:
    instance = {
        **VALID_EXAMPLES["parameter-set"],
        "parameters": {"matching": {"window_size_px": 32, "made_up_px": 1}},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("parameter-set"))


@pytest.mark.unit
def test_metric_schema_requires_a_reason_for_an_unavailable_metric() -> None:
    instance = {
        **VALID_EXAMPLES["metric-report"],
        "metrics": [
            {
                "name": "withheld_rmse_2d_px",
                "value": None,
                "units": "px",
                "evidence_source": "withheld_check_points",
            }
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("metric-report"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "scope, identifier", [("scene", "product_id"), ("route_qualification", "route_id")]
)
def test_metric_schema_requires_its_scope_identifier(scope: str, identifier: str) -> None:
    instance = {**VALID_EXAMPLES["metric-report"], "scope": scope}
    instance.pop(identifier, None)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("metric-report"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "parameters", [{}, {"matching": {}}, {"selection": {}}, {"refinement": {}}]
)
def test_parameter_schema_rejects_empty_scientific_configuration(
    parameters: dict[str, object],
) -> None:
    instance = {**VALID_EXAMPLES["parameter-set"], "parameters": parameters}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("parameter-set"))


@pytest.mark.unit
def test_failure_schema_is_exactly_the_typed_failure_taxonomy() -> None:
    schema = _load("failure-envelope")
    assert schema["$defs"]["failure_code"]["enum"] == [code.value for code in FailureCode]

    semantics = schema["$defs"]["failure_semantics"]["oneOf"]
    observed = {
        item["properties"]["code"]["const"]: (
            item["properties"]["retryable"]["const"],
            item["properties"]["remediation"]["const"],
        )
        for item in semantics
    }
    expected = {
        code.value: (definition_for(code).retryable, definition_for(code).remediation)
        for code in FailureCode
    }
    assert observed == expected

    instance = {**VALID_EXAMPLES["failure-envelope"], "code": "matching.invented_failure"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, schema)


@pytest.mark.unit
def test_failure_schema_rejects_mismatched_taxonomy_metadata_and_invalid_timestamp() -> None:
    schema = _load("failure-envelope")
    invalid_semantics = {**VALID_EXAMPLES["failure-envelope"], "retryable": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_semantics, schema)

    invalid_timestamp = {**VALID_EXAMPLES["failure-envelope"], "occurred_utc": "not-a-date"}
    with pytest.raises(jsonschema.ValidationError):
        validate_instance(invalid_timestamp, schema)

    impossible_timestamp = {
        **VALID_EXAMPLES["failure-envelope"],
        "occurred_utc": "2026-99-29T00:00:00Z",
    }
    with pytest.raises(jsonschema.ValidationError):
        validate_instance(impossible_timestamp, schema)


@pytest.mark.unit
@pytest.mark.parametrize("offset", ["+00:99", "-00:60"])
def test_runtime_validator_rejects_invalid_rfc3339_timezone_minutes(offset: str) -> None:
    instance = {
        **VALID_EXAMPLES["failure-envelope"],
        "occurred_utc": f"2026-08-29T00:00:00{offset}",
    }
    with pytest.raises(jsonschema.ValidationError):
        validate_instance(instance, _load("failure-envelope"))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("collection", "invalid_role"),
    [("image_references", "terrain"), ("terrain_sources", "image"), ("coverage_masks", "image")],
)
def test_reference_bundle_binds_source_role_to_its_collection(
    collection: str, invalid_role: str
) -> None:
    instance = {**VALID_EXAMPLES["reference-bundle-manifest"]}
    if collection == "terrain_sources":
        instance[collection] = [
            {**instance["image_references"][0], "source_id": "terrain", "role": invalid_role}
        ]
    else:
        instance[collection] = [{**instance[collection][0], "role": invalid_role}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("reference-bundle-manifest"))


@pytest.mark.unit
def test_reference_control_uncertainty_is_bound_to_accuracy_claim_support() -> None:
    source = {
        "source_id": "control-001",
        "version": "v1",
        "uri": "archive/control.gpkg",
        "sha256": _SHA256,
        "role": "control",
        "supports_accuracy_claims": True,
        "control_uncertainty_m": 2.5,
    }
    valid = {**VALID_EXAMPLES["reference-bundle-manifest"], "control_sources": [source]}
    jsonschema.validate(valid, _load("reference-bundle-manifest"))

    unavailable = {
        **source,
        "supports_accuracy_claims": False,
        "control_uncertainty_m": None,
        "control_uncertainty_reason": "This bundle has no independently surveyed control.",
    }
    jsonschema.validate(
        {**VALID_EXAMPLES["reference-bundle-manifest"], "control_sources": [unavailable]},
        _load("reference-bundle-manifest"),
    )

    for invalid_control in (
        {**source, "control_uncertainty_m": None},
        {**source, "supports_accuracy_claims": False},
    ):
        invalid = {
            **VALID_EXAMPLES["reference-bundle-manifest"],
            "control_sources": [invalid_control],
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, _load("reference-bundle-manifest"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    ["acquisition", "raster", "geometry_adapter", "frame", "projection", "datum_realisation"],
)
def test_product_manifest_rejects_missing_required_scientific_identity(field: str) -> None:
    instance = {**VALID_EXAMPLES["product-input-manifest"]}
    instance.pop(field)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("product-input-manifest"))


@pytest.mark.unit
def test_product_manifest_rejects_a_non_sha256_input_digest() -> None:
    instance = {**VALID_EXAMPLES["product-input-manifest"]}
    instance["files"] = [{**instance["files"][0], "sha256": "not-a-digest"}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("product-input-manifest"))


@pytest.mark.unit
def test_product_manifest_rejects_dishonest_geometry_status() -> None:
    instance = {**VALID_EXAMPLES["product-input-manifest"]}
    instance["geometry_adapter"] = {
        "name": "claimed-sensor-model",
        "version": "1",
        "status": "validated",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("product-input-manifest"))


@pytest.mark.unit
def test_provenance_manifest_rejects_an_incomplete_output_bundle() -> None:
    """A provenance record cannot be a bare artifact list with open parameters."""
    instance = {
        "schema_version": "1",
        "manifest_id": "incomplete-run",
        "created_utc": "2026-08-29T00:00:00Z",
        "artifacts": VALID_EXAMPLES["provenance-manifest"]["artifacts"],
        "parameters": {},
        "environment": {"python_version": "3.12", "platform": "Linux"},
        "limitations": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("provenance-manifest"))


@pytest.mark.unit
def test_provenance_manifest_rejects_open_or_empty_parameter_snapshot() -> None:
    instance = {**VALID_EXAMPLES["provenance-manifest"]}
    instance["parameters"] = {
        "parameter_set_id": "phase-correlation-defaults",
        "version": "1.0.0",
        "values": {"matching": {"made_up_px": 1}},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance, _load("provenance-manifest"))


@pytest.mark.unit
def test_provenance_parameter_snapshot_vocabulary_matches_parameter_set() -> None:
    """The embedded immutable snapshot may not drift from the published set vocabulary."""
    parameter_set_defs = _load("parameter-set")["$defs"]
    provenance_defs = _load("provenance-manifest")["$defs"]
    for name in ("matching_parameters", "selection_parameters", "refinement_parameters"):
        assert provenance_defs[name] == parameter_set_defs[name]

    parameter_categories = parameter_set_defs["parameters"]["properties"]
    snapshot_categories = provenance_defs["parameter_snapshot"]["properties"]["values"][
        "properties"
    ]
    assert snapshot_categories == parameter_categories
