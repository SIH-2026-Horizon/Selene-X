"""Tests for stage-result.schema.json schema file.

Ensures that the committed schema file:
- Matches the model_json_schema() output (regeneration check)
- Validates real StageResult instances for each outcome
- Rejects instances with unknown/extra fields
"""

import json
import pathlib
from datetime import UTC, datetime
from typing import Any, cast

import jsonschema
import pytest

from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.results import (
    ArtifactRef,
    EnvironmentFingerprint,
    PublicationState,
    ResourceUsage,
    StageFailure,
    StageOutcome,
    StageResult,
    StageWarning,
)

pytestmark = pytest.mark.unit


class TestStageResultSchemaConsistency:
    """Verify the committed schema file stays in sync with the model."""

    def test_schema_file_matches_model_json_schema(self) -> None:
        """The committed schema is exactly equal to model_json_schema() output."""
        # Generate fresh schema from the model
        generated_schema: dict[str, Any] = StageResult.model_json_schema()

        # Load the committed schema file
        schema_path = pathlib.Path("schemas/stage-result.schema.json")
        committed_schema: dict[str, Any] = json.loads(schema_path.read_text())

        # Build expected schema with repo convention fields
        expected_schema: dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://selene-xr.invalid/schemas/stage-result.schema.json",
            "title": "Stage result",
            "description": (
                "Input manifest hashes, the exact parameter subset read, typed outputs "
                "with checksum and CRS and units, warnings, failure code and retryability "
                "and remediation hint, stage metrics, algorithm and dependency versions, "
                "deterministic seed, instrumentation, code revision, environment fingerprint, "
                "and publication state. Implementation plan section 6.5."
            ),
        }
        # Add all other keys from generated schema
        for key in generated_schema:
            if key not in {"$schema", "$id", "title", "description"}:
                expected_schema[key] = generated_schema[key]

        # Assert exact equality
        assert committed_schema == expected_schema, (
            "Committed schema does not match model_json_schema() output. "
            "The schema file must not drift from the model. "
            "Regenerate with StageResult.model_json_schema()."
        )

    def test_schema_has_additional_properties_false(self) -> None:
        """Root StageResult schema forbids additional properties."""
        schema_path = pathlib.Path("schemas/stage-result.schema.json")
        schema: dict[str, Any] = json.loads(schema_path.read_text())
        assert schema.get("additionalProperties") is False, (
            "StageResult schema must have additionalProperties: false "
            "to reject unknown fields (extra='forbid')"
        )

    def test_nested_models_have_additional_properties_false(self) -> None:
        """All nested models in $defs forbid additional properties."""
        schema_path = pathlib.Path("schemas/stage-result.schema.json")
        schema: dict[str, Any] = json.loads(schema_path.read_text())

        # Models that should have additionalProperties: false
        models_with_forbid = [
            "ArtifactRef",
            "StageWarning",
            "StageFailure",
            "ResourceUsage",
            "EnvironmentFingerprint",
        ]

        defs = schema.get("$defs", {})
        for model_name in models_with_forbid:
            model_schema = defs.get(model_name)
            assert model_schema is not None, f"{model_name} not found in $defs"
            assert model_schema.get("additionalProperties") is False, (
                f"{model_name} must have additionalProperties: false"
            )


class TestStageResultSchemaValidation:
    """Validate real StageResult instances against the committed schema."""

    @staticmethod
    def load_schema() -> dict[str, Any]:
        """Load the committed schema file."""
        schema_path = pathlib.Path("schemas/stage-result.schema.json")
        return cast(dict[str, Any], json.loads(schema_path.read_text()))

    def test_succeeded_result_validates(self) -> None:
        """A SUCCEEDED result validates against the schema."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.SUCCEEDED,
            outputs=(
                ArtifactRef(
                    kind="result",
                    relative_path="output.tif",
                    media_type="image/tiff",
                    sha256="a" * 64,
                    size_bytes=1024,
                    publication_state=PublicationState.PUBLISHED,
                ),
            ),
        )
        schema = self.load_schema()
        instance = result.model_dump(mode="json")
        # Should not raise
        jsonschema.validate(instance, schema)

    def test_succeeded_with_warnings_result_validates(self) -> None:
        """A SUCCEEDED_WITH_WARNINGS result validates against the schema."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.SUCCEEDED_WITH_WARNINGS,
            warnings=(
                StageWarning(
                    code="W001",
                    message="Warning during processing",
                    context={"region": "test"},
                ),
            ),
        )
        schema = self.load_schema()
        instance = result.model_dump(mode="json")
        # Should not raise
        jsonschema.validate(instance, schema)

    def test_rejected_result_validates(self) -> None:
        """A REJECTED result validates against the schema."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.REJECTED,
            failure=StageFailure(
                code=FailureCode.GEOMETRY_NO_OVERLAP,
                message="No overlap found",
            ),
        )
        schema = self.load_schema()
        instance = result.model_dump(mode="json")
        # Should not raise
        jsonschema.validate(instance, schema)

    def test_failed_result_validates(self) -> None:
        """A FAILED result validates against the schema."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.FAILED,
            failure=StageFailure(
                code=FailureCode.RESOURCE_TIMEOUT,
                message="Stage timed out",
            ),
            started_utc=datetime.now(tz=UTC),
            ended_utc=datetime.now(tz=UTC),
        )
        schema = self.load_schema()
        instance = result.model_dump(mode="json")
        # Should not raise
        jsonschema.validate(instance, schema)

    def test_cancelled_result_validates(self) -> None:
        """A CANCELLED result validates against the schema."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.CANCELLED,
            failure=StageFailure(
                code=FailureCode.INTERNAL_CANCELLED,
                message="Stage was cancelled",
            ),
        )
        schema = self.load_schema()
        instance = result.model_dump(mode="json")
        # Should not raise
        jsonschema.validate(instance, schema)

    def test_result_with_environment_validates(self) -> None:
        """A result with environment fingerprint validates."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.SUCCEEDED,
            environment=EnvironmentFingerprint(
                python_version="3.11.0",
                platform="linux-x86_64",
                code_revision="abc123",
                dependency_versions={"numpy": "1.24.0", "pydantic": "2.0.0"},
            ),
        )
        schema = self.load_schema()
        instance = result.model_dump(mode="json")
        # Should not raise
        jsonschema.validate(instance, schema)

    def test_result_with_resources_validates(self) -> None:
        """A result with resource usage validates."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.SUCCEEDED,
            resources=ResourceUsage(
                wall_time_s=10.5,
                cpu_time_s=8.2,
                peak_memory_bytes=1024 * 1024 * 512,
                read_bytes=1024 * 1024,
                written_bytes=2048 * 1024,
                device="cuda:0",
            ),
        )
        schema = self.load_schema()
        instance = result.model_dump(mode="json")
        # Should not raise
        jsonschema.validate(instance, schema)


class TestStageResultSchemaRejectsUnknownFields:
    """Verify the schema rejects instances with unknown fields."""

    @staticmethod
    def load_schema() -> dict[str, Any]:
        """Load the committed schema file."""
        schema_path = pathlib.Path("schemas/stage-result.schema.json")
        return cast(dict[str, Any], json.loads(schema_path.read_text()))

    def test_unknown_root_field_rejected(self) -> None:
        """A valid instance with an extra root field is rejected."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.SUCCEEDED,
        )
        instance = result.model_dump(mode="json")

        # Add an unknown field to the instance
        instance["unknown_scientific_parameter"] = "some_value"

        schema = self.load_schema()

        # Should raise ValidationError due to additionalProperties: false
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance, schema)

    def test_unknown_nested_field_rejected(self) -> None:
        """A valid instance with an unknown nested field is rejected."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.SUCCEEDED,
            environment=EnvironmentFingerprint(
                python_version="3.11.0",
                platform="linux-x86_64",
            ),
        )
        instance = result.model_dump(mode="json")

        # Add an unknown field to the nested environment
        instance["environment"]["unknown_field"] = "value"

        schema = self.load_schema()

        # Should raise ValidationError
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance, schema)

    def test_unknown_artifact_field_rejected(self) -> None:
        """A valid instance with an unknown artifact field is rejected."""
        result = StageResult(
            stage_name="test_stage",
            stage_version="1.0",
            outcome=StageOutcome.SUCCEEDED,
            outputs=(
                ArtifactRef(
                    kind="result",
                    relative_path="output.tif",
                    media_type="image/tiff",
                    sha256="a" * 64,
                    size_bytes=1024,
                    publication_state=PublicationState.PUBLISHED,
                ),
            ),
        )
        instance = result.model_dump(mode="json")

        # Add an unknown field to the first artifact
        instance["outputs"][0]["unknown_artifact_field"] = "value"

        schema = self.load_schema()

        # Should raise ValidationError
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(instance, schema)
