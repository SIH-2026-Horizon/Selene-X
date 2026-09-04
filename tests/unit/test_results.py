"""Tests for stage result protocol and related types.

Covers ArtifactRef, StageWarning, StageFailure, StageResult, StageOutcome,
ResourceUsage, EnvironmentFingerprint, and stage_fingerprint.
"""

from datetime import UTC, datetime, timedelta

import pytest

from selene_core.pipeline.failures import FailureCode, definition_for
from selene_core.pipeline.results import (
    ArtifactRef,
    EnvironmentFingerprint,
    PublicationState,
    ResourceUsage,
    StageFailure,
    StageOutcome,
    StageResult,
    StageWarning,
    stage_fingerprint,
)

pytestmark = pytest.mark.unit


class TestArtifactRef:
    """Tests for ArtifactRef model."""

    def test_artifact_ref_creation(self) -> None:
        """ArtifactRef can be created with valid fields."""
        ref = ArtifactRef(
            kind="data",
            relative_path="output.txt",
            media_type="text/plain",
            sha256="a" * 64,
            size_bytes=100,
        )
        assert ref.kind == "data"
        assert ref.relative_path == "output.txt"

    def test_artifact_ref_rejects_invalid_sha256(self) -> None:
        """ArtifactRef rejects non-SHA-256 sha256 field."""
        with pytest.raises(ValueError, match="SHA-256 hex digest"):
            ArtifactRef(
                kind="data",
                relative_path="output.txt",
                media_type="text/plain",
                sha256="invalid",
                size_bytes=100,
            )

    def test_artifact_ref_rejects_uppercase_sha256(self) -> None:
        """ArtifactRef rejects uppercase SHA-256."""
        with pytest.raises(ValueError, match="SHA-256 hex digest"):
            ArtifactRef(
                kind="data",
                relative_path="output.txt",
                media_type="text/plain",
                sha256="A" * 64,
                size_bytes=100,
            )

    def test_artifact_ref_rejects_leading_slash_path(self) -> None:
        """ArtifactRef rejects absolute paths."""
        with pytest.raises(ValueError, match="must stay inside"):
            ArtifactRef(
                kind="data",
                relative_path="/etc/passwd",
                media_type="text/plain",
                sha256="a" * 64,
                size_bytes=100,
            )

    def test_artifact_ref_rejects_dotdot_path(self) -> None:
        """ArtifactRef rejects paths with .. segments."""
        with pytest.raises(ValueError, match="must stay inside"):
            ArtifactRef(
                kind="data",
                relative_path="../../etc/passwd",
                media_type="text/plain",
                sha256="a" * 64,
                size_bytes=100,
            )

    def test_artifact_ref_round_trip_json(self) -> None:
        """ArtifactRef round-trips through model_dump_json/model_validate_json."""
        ref = ArtifactRef(
            kind="data",
            relative_path="output.txt",
            media_type="text/plain",
            sha256="a" * 64,
            size_bytes=100,
        )
        json_str = ref.model_dump_json()
        ref2 = ArtifactRef.model_validate_json(json_str)
        assert ref == ref2

    def test_artifact_ref_accepts_valid_relative_paths(self) -> None:
        """ArtifactRef accepts valid relative paths."""
        valid_paths = [
            "output.txt",
            "subdir/output.txt",
            "a/b/c/output.txt",
            "file with spaces.txt",
        ]
        for path in valid_paths:
            ref = ArtifactRef(
                kind="data",
                relative_path=path,
                media_type="text/plain",
                sha256="a" * 64,
                size_bytes=100,
            )
            assert ref.relative_path == path


class TestStageWarning:
    """Tests for StageWarning model."""

    def test_stage_warning_creation(self) -> None:
        """StageWarning can be created."""
        warning = StageWarning(code="W001", message="Warning message")
        assert warning.code == "W001"
        assert warning.message == "Warning message"

    def test_stage_warning_with_context(self) -> None:
        """StageWarning can include context."""
        warning = StageWarning(
            code="W001",
            message="Warning",
            context={"region": "a", "count": 5},
        )
        assert warning.context == {"region": "a", "count": 5}


class TestStageFailure:
    """Tests for StageFailure model."""

    def test_stage_failure_creation(self) -> None:
        """StageFailure can be created."""
        failure = StageFailure(
            code=FailureCode.GEOMETRY_NO_OVERLAP,
            message="Overlap failed",
        )
        assert failure.code == FailureCode.GEOMETRY_NO_OVERLAP

    def test_stage_failure_category_from_code(self) -> None:
        """StageFailure.category is derived from code."""
        failure = StageFailure(
            code=FailureCode.INPUT_MISSING_FILE,
            message="File missing",
        )
        definition = definition_for(FailureCode.INPUT_MISSING_FILE)
        assert failure.category == definition.category

    def test_stage_failure_retryable_from_code(self) -> None:
        """StageFailure.retryable is derived from code."""
        failure_retryable = StageFailure(
            code=FailureCode.PRODUCT_WRITE_FAILED,
            message="Write failed",
        )
        assert failure_retryable.retryable is True
        failure_not_retryable = StageFailure(
            code=FailureCode.INPUT_MISSING_FILE,
            message="File missing",
        )
        assert failure_not_retryable.retryable is False

    def test_stage_failure_remediation_from_code(self) -> None:
        """StageFailure.remediation is derived from code."""
        failure = StageFailure(
            code=FailureCode.INPUT_MISSING_FILE,
            message="File missing",
        )
        definition = definition_for(FailureCode.INPUT_MISSING_FILE)
        assert failure.remediation == definition.remediation

    def test_stage_failure_summary_from_code(self) -> None:
        """StageFailure.summary is derived from code."""
        failure = StageFailure(
            code=FailureCode.INPUT_MISSING_FILE,
            message="File missing",
        )
        definition = definition_for(FailureCode.INPUT_MISSING_FILE)
        assert failure.summary == definition.summary


class TestStageOutcome:
    """Tests for StageOutcome enum."""

    def test_stage_outcome_is_success_for_succeeded(self) -> None:
        """SUCCEEDED.is_success is True."""
        assert StageOutcome.SUCCEEDED.is_success is True

    def test_stage_outcome_is_success_for_succeeded_with_warnings(self) -> None:
        """SUCCEEDED_WITH_WARNINGS.is_success is True."""
        assert StageOutcome.SUCCEEDED_WITH_WARNINGS.is_success is True

    def test_stage_outcome_is_success_for_failed(self) -> None:
        """FAILED.is_success is False."""
        assert StageOutcome.FAILED.is_success is False

    def test_stage_outcome_is_success_for_rejected(self) -> None:
        """REJECTED.is_success is False."""
        assert StageOutcome.REJECTED.is_success is False

    def test_stage_outcome_is_success_for_cancelled(self) -> None:
        """CANCELLED.is_success is False."""
        assert StageOutcome.CANCELLED.is_success is False

    def test_stage_outcome_is_reusable_on_resume(self) -> None:
        """is_reusable_on_resume returns True only for success outcomes."""
        assert StageOutcome.SUCCEEDED.is_reusable_on_resume is True
        assert StageOutcome.SUCCEEDED_WITH_WARNINGS.is_reusable_on_resume is True
        assert StageOutcome.REJECTED.is_reusable_on_resume is False
        assert StageOutcome.FAILED.is_reusable_on_resume is False
        assert StageOutcome.CANCELLED.is_reusable_on_resume is False


class TestStageResultValidation:
    """Tests for StageResult._check invariants."""

    def test_stage_result_success_with_failure_rejected(self) -> None:
        """A SUCCEEDED stage with failure is rejected."""
        with pytest.raises(ValueError, match="disagree"):
            StageResult(
                stage_name="test",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
                failure=StageFailure(
                    code=FailureCode.GEOMETRY_NO_OVERLAP,
                    message="test",
                ),
            )

    def test_stage_result_failure_without_code_rejected(self) -> None:
        """A FAILED stage without failure is rejected."""
        with pytest.raises(ValueError, match="must carry a failure"):
            StageResult(
                stage_name="test",
                stage_version="1",
                outcome=StageOutcome.FAILED,
            )

    def test_stage_result_succeeded_with_warnings_rejected(self) -> None:
        """SUCCEEDED outcome with warnings is rejected."""
        with pytest.raises(ValueError, match="SUCCEEDED_WITH_WARNINGS"):
            StageResult(
                stage_name="test",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
                warnings=(StageWarning(code="W1", message="warning"),),
            )

    def test_stage_result_succeeded_with_warnings_accepted(self) -> None:
        """SUCCEEDED_WITH_WARNINGS with warnings is accepted."""
        result = StageResult(
            stage_name="test",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED_WITH_WARNINGS,
            warnings=(StageWarning(code="W1", message="warning"),),
        )
        assert result.outcome == StageOutcome.SUCCEEDED_WITH_WARNINGS

    def test_stage_result_success_with_unpublished_output_rejected(self) -> None:
        """Success outcome with unpublished output is rejected."""
        with pytest.raises(ValueError, match="unpublished"):
            StageResult(
                stage_name="test",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
                outputs=(
                    ArtifactRef(
                        kind="data",
                        relative_path="output.txt",
                        media_type="text/plain",
                        sha256="a" * 64,
                        size_bytes=100,
                        publication_state=PublicationState.SCRATCH,
                    ),
                ),
            )

    def test_stage_result_success_with_published_output_accepted(self) -> None:
        """Success outcome with published output is accepted."""
        result = StageResult(
            stage_name="test",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            outputs=(
                ArtifactRef(
                    kind="data",
                    relative_path="output.txt",
                    media_type="text/plain",
                    sha256="a" * 64,
                    size_bytes=100,
                    publication_state=PublicationState.PUBLISHED,
                ),
            ),
        )
        assert result.outcome == StageOutcome.SUCCEEDED

    def test_stage_result_invalid_input_digest_rejected(self) -> None:
        """Invalid SHA-256 in input_digests is rejected."""
        with pytest.raises(ValueError, match="not a SHA-256"):
            StageResult(
                stage_name="test",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
                input_digests={"input": "invalid"},
            )

    def test_stage_result_ended_before_started_rejected(self) -> None:
        """ended_utc < started_utc is rejected."""
        now = datetime.now(tz=UTC)
        later = now + timedelta(hours=1)
        with pytest.raises(ValueError, match="precedes"):
            StageResult(
                stage_name="test",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
                started_utc=later,
                ended_utc=now,
            )


class TestStageResultProperties:
    """Tests for StageResult properties."""

    def test_stage_result_fingerprint_matches_stage_fingerprint(self) -> None:
        """StageResult.fingerprint matches stage_fingerprint(...)."""
        result = StageResult(
            stage_name="test",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            input_digests={"input": "a" * 64},
            parameter_subset={"param": "value"},
        )
        expected = stage_fingerprint(
            stage_name="test",
            stage_version="1",
            algorithm=None,
            algorithm_version=None,
            input_digests={"input": "a" * 64},
            parameter_subset={"param": "value"},
        )
        assert result.fingerprint == expected

    def test_stage_result_output_digests(self) -> None:
        """StageResult.output_digests maps path -> sha256."""
        digest1 = "a" * 64
        digest2 = "b" * 64
        result = StageResult(
            stage_name="test",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            outputs=(
                ArtifactRef(
                    kind="data1",
                    relative_path="output1.txt",
                    media_type="text/plain",
                    sha256=digest1,
                    size_bytes=100,
                    publication_state=PublicationState.PUBLISHED,
                ),
                ArtifactRef(
                    kind="data2",
                    relative_path="output2.txt",
                    media_type="text/plain",
                    sha256=digest2,
                    size_bytes=200,
                    publication_state=PublicationState.PUBLISHED,
                ),
            ),
        )
        expected = {"output1.txt": digest1, "output2.txt": digest2}
        assert result.output_digests == expected

    def test_stage_result_output_single_match(self) -> None:
        """StageResult.output(kind) returns single match."""
        result = StageResult(
            stage_name="test",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            outputs=(
                ArtifactRef(
                    kind="data",
                    relative_path="output.txt",
                    media_type="text/plain",
                    sha256="a" * 64,
                    size_bytes=100,
                    publication_state=PublicationState.PUBLISHED,
                ),
            ),
        )
        artifact = result.output("data")
        assert artifact.kind == "data"

    def test_stage_result_output_no_match_raises(self) -> None:
        """StageResult.output(kind) raises KeyError when no match."""
        result = StageResult(
            stage_name="test",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            outputs=(
                ArtifactRef(
                    kind="data",
                    relative_path="output.txt",
                    media_type="text/plain",
                    sha256="a" * 64,
                    size_bytes=100,
                    publication_state=PublicationState.PUBLISHED,
                ),
            ),
        )
        with pytest.raises(KeyError):
            result.output("nonexistent")

    def test_stage_result_output_multiple_matches_raises(self) -> None:
        """StageResult.output(kind) raises KeyError with multiple matches."""
        result = StageResult(
            stage_name="test",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            outputs=(
                ArtifactRef(
                    kind="data",
                    relative_path="output1.txt",
                    media_type="text/plain",
                    sha256="a" * 64,
                    size_bytes=100,
                    publication_state=PublicationState.PUBLISHED,
                ),
                ArtifactRef(
                    kind="data",
                    relative_path="output2.txt",
                    media_type="text/plain",
                    sha256="b" * 64,
                    size_bytes=100,
                    publication_state=PublicationState.PUBLISHED,
                ),
            ),
        )
        with pytest.raises(KeyError):
            result.output("data")


class TestStageFingerprintFunction:
    """Tests for stage_fingerprint function."""

    def test_stage_fingerprint_produces_sha256(self) -> None:
        """stage_fingerprint produces a valid SHA-256 digest."""
        from selene_core.pipeline.hashing import is_sha256

        fingerprint = stage_fingerprint(
            stage_name="test",
            stage_version="1",
            algorithm=None,
            algorithm_version=None,
            input_digests={},
            parameter_subset={},
        )
        assert is_sha256(fingerprint)

    def test_stage_fingerprint_same_inputs_same_output(self) -> None:
        """stage_fingerprint produces same output for same inputs."""
        fp1 = stage_fingerprint(
            stage_name="test",
            stage_version="1",
            algorithm=None,
            algorithm_version=None,
            input_digests={"input": "a" * 64},
            parameter_subset={"param": "value"},
        )
        fp2 = stage_fingerprint(
            stage_name="test",
            stage_version="1",
            algorithm=None,
            algorithm_version=None,
            input_digests={"input": "a" * 64},
            parameter_subset={"param": "value"},
        )
        assert fp1 == fp2

    def test_stage_fingerprint_different_version_different_output(self) -> None:
        """stage_fingerprint changes when stage_version changes."""
        fp1 = stage_fingerprint(
            stage_name="test",
            stage_version="1",
            algorithm=None,
            algorithm_version=None,
            input_digests={},
            parameter_subset={},
        )
        fp2 = stage_fingerprint(
            stage_name="test",
            stage_version="2",
            algorithm=None,
            algorithm_version=None,
            input_digests={},
            parameter_subset={},
        )
        assert fp1 != fp2


class TestResourceUsage:
    """Tests for ResourceUsage model."""

    def test_resource_usage_all_none(self) -> None:
        """ResourceUsage can be created with all None."""
        usage = ResourceUsage()
        assert usage.wall_time_s is None
        assert usage.cpu_time_s is None
        assert usage.peak_memory_bytes is None

    def test_resource_usage_with_values(self) -> None:
        """ResourceUsage can be created with values."""
        usage = ResourceUsage(
            wall_time_s=1.5,
            cpu_time_s=1.0,
            peak_memory_bytes=1024,
        )
        assert usage.wall_time_s == 1.5
        assert usage.cpu_time_s == 1.0
        assert usage.peak_memory_bytes == 1024


class TestEnvironmentFingerprint:
    """Tests for EnvironmentFingerprint model."""

    def test_environment_fingerprint_creation(self) -> None:
        """EnvironmentFingerprint can be created."""
        env = EnvironmentFingerprint(
            python_version="3.11.0",
            platform="Linux-5.10.0",
        )
        assert env.python_version == "3.11.0"
        assert env.platform == "Linux-5.10.0"

    def test_environment_fingerprint_with_revision(self) -> None:
        """EnvironmentFingerprint can include code_revision."""
        env = EnvironmentFingerprint(
            python_version="3.11.0",
            platform="Linux-5.10.0",
            code_revision="abc123",
        )
        assert env.code_revision == "abc123"

    def test_environment_fingerprint_with_dependencies(self) -> None:
        """EnvironmentFingerprint can include dependency_versions."""
        env = EnvironmentFingerprint(
            python_version="3.11.0",
            platform="Linux-5.10.0",
            dependency_versions={"numpy": "1.24.0"},
        )
        assert env.dependency_versions == {"numpy": "1.24.0"}
