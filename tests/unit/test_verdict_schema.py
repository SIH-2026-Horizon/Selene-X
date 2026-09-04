"""Tests for verdict.schema.json.

Ensures that the committed schema file:
- Matches the SceneVerdict.model_json_schema() output (regeneration check)
- Validates a real SceneVerdict instance for each of the three verdict
  outcomes (accept, review, reject)
- Rejects an instance carrying an unknown top-level field
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime
from typing import Any, cast

import jsonschema
import pytest

from selene_core.metrics.verdict import (
    GateKind,
    GateSpec,
    SceneEvidence,
    SceneVerdict,
    compute_scene_verdict,
    evaluate_gate,
)

pytestmark = pytest.mark.unit

_SCHEMA_PATH = pathlib.Path("schemas/verdict.schema.json")


def _load_schema() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_SCHEMA_PATH.read_text()))


def _evidence(**overrides: object) -> SceneEvidence:
    defaults: dict[str, object] = {
        "route_qualified": True,
        "route_id": "route-1",
        "is_synthetic": False,
        "has_independent_control": True,
        "control_uncertainty_m": 1.5,
        "metrics": {"m": 0.9},
    }
    defaults.update(overrides)
    return SceneEvidence(**defaults)  # type: ignore[arg-type]


class TestVerdictSchemaConsistency:
    """Verify the committed schema file stays in sync with the model."""

    def test_schema_file_matches_model_json_schema(self) -> None:
        """The committed schema is exactly equal to model_json_schema() output."""
        generated_schema: dict[str, Any] = SceneVerdict.model_json_schema()
        committed_schema: dict[str, Any] = _load_schema()

        expected_schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://selene-xr.invalid/schemas/verdict.schema.json",
            "title": "Computed verdict and effective disposition",
            "description": (
                "The immutable computed verdict accept, review, or reject with per-gate "
                "observed value, threshold, applicability, pass state, and evidence source. "
                "Implementation plan sections 8 and 10."
            ),
        }
        for key in generated_schema:
            if key not in {"$schema", "$id", "title", "description"}:
                expected_schema[key] = generated_schema[key]

        assert committed_schema == expected_schema, (
            "Committed schema does not match model_json_schema() output. The schema file "
            "must not drift from the model. Regenerate from SceneVerdict."
        )

    def test_schema_has_additional_properties_false(self) -> None:
        """Root SceneVerdict schema forbids additional properties."""
        schema = _load_schema()
        assert schema.get("additionalProperties") is False

    def test_gate_result_def_has_additional_properties_false(self) -> None:
        schema = _load_schema()
        gate_result = schema["$defs"]["GateResult"]
        assert gate_result.get("additionalProperties") is False

    def test_schema_is_valid_json_schema(self) -> None:
        from jsonschema.validators import validator_for

        document = _load_schema()
        validator_for(document).check_schema(document)

    def test_schema_declares_identity(self) -> None:
        document = _load_schema()
        assert document["$id"].endswith("verdict.schema.json")
        assert document["title"]
        assert document["description"]


class TestVerdictSchemaValidation:
    """Validate real SceneVerdict instances against the committed schema, one
    per verdict outcome."""

    def test_accept_verdict_validates(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="hard_gate",
                kind=GateKind.HARD,
                metric_name="m",
                comparison="ge",
                threshold=0.5,
            ),
            _evidence(metrics={"m": 0.9}),
        )
        verdict = compute_scene_verdict(
            (gate,),
            route_qualified=True,
            route_id="route-1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert verdict.verdict == "accept"

        schema = _load_schema()
        jsonschema.validate(verdict.model_dump(mode="json"), schema)

    def test_review_verdict_validates(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="soft_gate",
                kind=GateKind.SOFT,
                metric_name="m",
                comparison="ge",
                threshold=0.99,
            ),
            _evidence(metrics={"m": 0.1}),
        )
        verdict = compute_scene_verdict(
            (gate,),
            route_qualified=True,
            route_id="route-1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert verdict.verdict == "review"

        schema = _load_schema()
        jsonschema.validate(verdict.model_dump(mode="json"), schema)

    def test_reject_verdict_validates(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="hard_gate",
                kind=GateKind.HARD,
                metric_name="m",
                comparison="ge",
                threshold=0.99,
            ),
            _evidence(metrics={"m": 0.1}),
        )
        verdict = compute_scene_verdict(
            (gate,),
            route_qualified=True,
            route_id="route-1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert verdict.verdict == "reject"

        schema = _load_schema()
        jsonschema.validate(verdict.model_dump(mode="json"), schema)

    def test_reject_verdict_from_unqualified_route_validates(self) -> None:
        verdict = compute_scene_verdict(
            (),
            route_qualified=False,
            route_id="route-1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert verdict.verdict == "reject"

        schema = _load_schema()
        jsonschema.validate(verdict.model_dump(mode="json"), schema)


class TestVerdictSchemaRejectsUnknownFields:
    def test_unknown_root_field_is_rejected(self) -> None:
        verdict = compute_scene_verdict(
            (),
            route_qualified=True,
            route_id="route-1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        instance = verdict.model_dump(mode="json")
        instance["unknown_scientific_field"] = "some_value"

        schema = _load_schema()

        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance, schema)

    def test_unknown_gate_result_field_is_rejected(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="hard_gate",
                kind=GateKind.HARD,
                metric_name="m",
                comparison="ge",
                threshold=0.5,
            ),
            _evidence(metrics={"m": 0.9}),
        )
        verdict = compute_scene_verdict(
            (gate,),
            route_qualified=True,
            route_id="route-1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        instance = verdict.model_dump(mode="json")
        instance["gate_results"][0]["unknown_field"] = "value"

        schema = _load_schema()

        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance, schema)
