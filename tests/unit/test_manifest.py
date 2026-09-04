"""Tests for immutable run manifests and environment capture.

Covers RunManifest, capture_environment, and related functionality.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from selene_core.pipeline.hashing import digest_json
from selene_core.pipeline.manifest import (
    MANIFEST_SCHEMA_VERSION,
    RunManifest,
    capture_environment,
)
from selene_core.pipeline.results import (
    EnvironmentFingerprint,
    StageOutcome,
    StageResult,
)

pytestmark = pytest.mark.unit


class TestCaptureEnvironment:
    """Tests for capture_environment function."""

    def test_capture_environment_returns_fingerprint(self) -> None:
        """capture_environment returns an EnvironmentFingerprint."""
        env = capture_environment()
        assert isinstance(env, EnvironmentFingerprint)

    def test_capture_environment_python_version_nonempty(self) -> None:
        """capture_environment includes a non-empty python_version."""
        env = capture_environment()
        assert len(env.python_version) > 0
        assert "." in env.python_version

    def test_capture_environment_platform_nonempty(self) -> None:
        """capture_environment includes a non-empty platform."""
        env = capture_environment()
        assert len(env.platform) > 0

    def test_capture_environment_dependency_versions_present(self) -> None:
        """capture_environment includes entries for recorded dependencies."""
        env = capture_environment()
        assert "numpy" in env.dependency_versions
        assert "pydantic" in env.dependency_versions

    def test_capture_environment_code_revision_none_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """capture_environment returns None for code_revision when env var unset."""
        monkeypatch.delenv("SELENE_CODE_REVISION", raising=False)
        env = capture_environment()
        assert env.code_revision is None

    def test_capture_environment_code_revision_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """capture_environment reads code_revision from SELENE_CODE_REVISION."""
        monkeypatch.setenv("SELENE_CODE_REVISION", "abc123def")
        env = capture_environment()
        assert env.code_revision == "abc123def"


class TestRunManifestCreation:
    """Tests for RunManifest creation and properties."""

    def test_run_manifest_creation(self) -> None:
        """RunManifest can be created."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        assert manifest.run_id == "run1"
        assert manifest.environment == env

    def test_run_manifest_schema_version(self) -> None:
        """RunManifest includes the correct schema_version."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        assert manifest.schema_version == MANIFEST_SCHEMA_VERSION

    def test_run_manifest_parameter_digest(self) -> None:
        """RunManifest.parameter_digest matches digest_json(parameters)."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        parameters = {"param1": "value1", "param2": 42}
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
            parameters=parameters,
        )
        expected = digest_json(parameters)
        assert manifest.parameter_digest == expected


class TestRunManifestStage:
    """Tests for RunManifest.stage access."""

    def test_run_manifest_stage_returns_most_recent(self) -> None:
        """RunManifest.stage returns the most recent result for a name."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        result1 = StageResult(
            stage_name="stage1",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            attempt=1,
        )
        result2 = StageResult(
            stage_name="stage1",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            attempt=2,
        )
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
            stages=(result1, result2),
        )
        retrieved = manifest.stage("stage1")
        assert retrieved == result2
        assert retrieved.attempt == 2

    def test_run_manifest_stage_returns_none_for_absent(self) -> None:
        """RunManifest.stage returns None for absent stage name."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        assert manifest.stage("nonexistent") is None


class TestRunManifestWithStage:
    """Tests for RunManifest.with_stage."""

    def test_run_manifest_with_stage_appends_result(self) -> None:
        """RunManifest.with_stage returns a new manifest with result appended."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest1 = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        result = StageResult(
            stage_name="stage1",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
        )
        manifest2 = manifest1.with_stage(result)
        assert len(manifest2.stages) == 1
        assert manifest2.stages[0] == result

    def test_run_manifest_with_stage_advances_timestamp(self) -> None:
        """RunManifest.with_stage advances updated_utc."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest1 = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        result = StageResult(
            stage_name="stage1",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
        )
        manifest2 = manifest1.with_stage(result)
        assert manifest2.updated_utc > manifest1.updated_utc

    def test_run_manifest_with_stage_original_unchanged(self) -> None:
        """RunManifest.with_stage leaves original manifest unchanged (frozen)."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest1 = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        result = StageResult(
            stage_name="stage1",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
        )
        manifest2 = manifest1.with_stage(result)
        assert len(manifest1.stages) == 0
        assert len(manifest2.stages) == 1

    def test_run_manifest_with_stage_multiple_appends(self) -> None:
        """Multiple with_stage calls append in order."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        result1 = StageResult(
            stage_name="stage1",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
        )
        result2 = StageResult(
            stage_name="stage2",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
        )
        manifest = manifest.with_stage(result1)
        manifest = manifest.with_stage(result2)
        assert len(manifest.stages) == 2
        assert manifest.stages[0].stage_name == "stage1"
        assert manifest.stages[1].stage_name == "stage2"


class TestRunManifestReadWrite:
    """Tests for RunManifest.write and RunManifest.read."""

    def test_run_manifest_write_creates_file(self, tmp_path: Path) -> None:
        """RunManifest.write creates a file at the given path."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        path = tmp_path / "run.json"
        manifest.write(path)
        assert path.exists()

    def test_run_manifest_write_produces_valid_json(self, tmp_path: Path) -> None:
        """RunManifest.write produces valid JSON."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        path = tmp_path / "run.json"
        manifest.write(path)
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_run_manifest_read_roundtrip(self, tmp_path: Path) -> None:
        """RunManifest.read recovers manifest written by write."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest1 = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
            parameters={"param": "value"},
        )
        path = tmp_path / "run.json"
        manifest1.write(path)
        manifest2 = RunManifest.read(path)
        assert manifest2.run_id == manifest1.run_id
        assert manifest2.parameters == manifest1.parameters
        assert manifest2.environment.python_version == manifest1.environment.python_version

    def test_run_manifest_read_wrong_schema_version_raises(self, tmp_path: Path) -> None:
        """RunManifest.read raises ValueError for wrong schema_version."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        path = tmp_path / "run.json"
        manifest.write(path)
        # Corrupt the schema version
        data = json.loads(path.read_text())
        data["schema_version"] = "999"
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="schema version"):
            RunManifest.read(path)

    def test_run_manifest_read_rejects_unknown_field(self, tmp_path: Path) -> None:
        """RunManifest.read rejects JSON with unknown top-level fields."""
        path = tmp_path / "run.json"
        data = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": "run1",
            "created_utc": datetime.now(tz=UTC).isoformat(),
            "updated_utc": datetime.now(tz=UTC).isoformat(),
            "environment": {
                "python_version": "3.11.0",
                "platform": "Linux",
            },
            "unknown_field": "value",
        }
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError):
            RunManifest.read(path)

    def test_run_manifest_with_stages_roundtrip(self, tmp_path: Path) -> None:
        """RunManifest with stages round-trips correctly."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        result = StageResult(
            stage_name="stage1",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
        )
        manifest1 = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
            stages=(result,),
        )
        path = tmp_path / "run.json"
        manifest1.write(path)
        manifest2 = RunManifest.read(path)
        assert len(manifest2.stages) == 1
        assert manifest2.stages[0].stage_name == "stage1"


class TestRunManifestFrozen:
    """Tests for RunManifest immutability."""

    def test_run_manifest_is_frozen(self) -> None:
        """RunManifest is frozen and cannot be modified."""
        env = capture_environment()
        now = datetime.now(tz=UTC)
        manifest = RunManifest(
            run_id="run1",
            created_utc=now,
            updated_utc=now,
            environment=env,
        )
        with pytest.raises((AttributeError, ValueError)):
            manifest.run_id = "run2"

    def test_run_manifest_extra_forbid(self, tmp_path: Path) -> None:
        """RunManifest rejects unknown fields."""
        path = tmp_path / "run.json"
        data = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": "run1",
            "created_utc": datetime.now(tz=UTC).isoformat(),
            "updated_utc": datetime.now(tz=UTC).isoformat(),
            "environment": {
                "python_version": "3.11.0",
                "platform": "Linux",
            },
            "extra_field": "should_fail",
        }
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError):
            RunManifest.read(path)
