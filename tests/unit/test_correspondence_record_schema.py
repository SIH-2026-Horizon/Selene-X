"""Tests for correspondence-record.schema.json.

Ensures that the committed schema file:
- Matches the CorrespondenceRecord.model_json_schema() output (regeneration check)
- Validates real CorrespondenceRecord instances, one per PointRole member and one
  per NmsStatus member
- Rejects an instance carrying an unknown top-level field
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, cast

import jsonschema
import pytest

from selene_core.match.correspondence import CorrespondenceRecord, NmsStatus, PointRole
from selene_core.types import ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_SCHEMA_PATH = pathlib.Path("schemas/correspondence-record.schema.json")

_VALID_SHA256 = "a" * 64
_VALID_SHA256_B = "b" * 64
_VALID_SHA256_C = "c" * 64


def _load_schema() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_SCHEMA_PATH.read_text()))


def _minimal_kwargs() -> dict[str, Any]:
    return {
        "job_id": "job-1",
        "algorithm": "phase_correlation",
        "algorithm_version": "1.0",
        "source_pixel": SourcePixel(line=10.0, sample=20.0),
        "reference_pixel": ReferencePixel(line=11.0, sample=21.0),
        "raw_score": 0.9,
        "input_digest": _VALID_SHA256,
        "reference_digest": _VALID_SHA256_B,
        "parameter_set_digest": _VALID_SHA256_C,
    }


class TestSchemaStructure:
    """Coverage that ``tests/unit/test_schemas.py`` no longer provides once this
    schema is removed from its ``REQUIRED_SCHEMAS`` placeholder list."""

    def test_schema_is_valid_json_schema(self) -> None:
        from jsonschema.validators import validator_for

        document = _load_schema()
        validator_for(document).check_schema(document)

    def test_schema_declares_identity(self) -> None:
        document = _load_schema()
        assert document["$id"].endswith("correspondence-record.schema.json")
        assert document["title"]
        assert document["description"]


class TestCorrespondenceRecordSchemaConsistency:
    """Verify the committed schema file stays in sync with the model."""

    def test_schema_file_matches_model_json_schema(self) -> None:
        """The committed schema is exactly equal to model_json_schema() output."""
        generated_schema: dict[str, Any] = CorrespondenceRecord.model_json_schema()
        committed_schema: dict[str, Any] = _load_schema()

        expected_schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://selene-xr.invalid/schemas/correspondence-record.schema.json",
            "title": "Correspondence record",
            "description": (
                "The canonical match record: identity, position, evidence, geometry, "
                "refinement, uncertainty, quality, coverage, and provenance groups. "
                "Training points, fitting inliers, and withheld check points must be "
                "disjoint and explicitly flagged. Implementation plan section 6.4."
            ),
        }
        for key in generated_schema:
            if key not in {"$schema", "$id", "title", "description"}:
                expected_schema[key] = generated_schema[key]

        assert committed_schema == expected_schema, (
            "Committed schema does not match model_json_schema() output. The schema file "
            "must not drift from the model. Regenerate from CorrespondenceRecord."
        )

    def test_schema_has_additional_properties_false(self) -> None:
        """Root CorrespondenceRecord schema forbids additional properties."""
        schema = _load_schema()
        assert schema.get("additionalProperties") is False


class TestCorrespondenceRecordSchemaValidation:
    """Validate real CorrespondenceRecord instances against the committed schema."""

    def test_minimal_record_validates(self) -> None:
        record = CorrespondenceRecord(**_minimal_kwargs())
        schema = _load_schema()

        jsonschema.validate(record.model_dump(mode="json"), schema)

    @pytest.mark.parametrize("role", list(PointRole))
    def test_each_point_role_member_validates(self, role: PointRole) -> None:
        is_candidate = role in {
            PointRole.TRAINING,
            PointRole.FITTING_INLIER,
            PointRole.WITHHELD_CHECK_POINT,
        }
        record = CorrespondenceRecord(
            is_candidate=is_candidate, point_role=role, **_minimal_kwargs()
        )
        schema = _load_schema()

        jsonschema.validate(record.model_dump(mode="json"), schema)

    @pytest.mark.parametrize("status", list(NmsStatus))
    def test_each_nms_status_member_validates(self, status: NmsStatus) -> None:
        record = CorrespondenceRecord(nms_status=status, **_minimal_kwargs())
        schema = _load_schema()

        jsonschema.validate(record.model_dump(mode="json"), schema)


class TestCorrespondenceRecordSchemaRejectsUnknownFields:
    def test_unknown_root_field_is_rejected(self) -> None:
        record = CorrespondenceRecord(**_minimal_kwargs())
        instance = record.model_dump(mode="json")
        instance["unknown_scientific_field"] = "some_value"

        schema = _load_schema()

        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance, schema)
