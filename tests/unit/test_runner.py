"""Tests for the stage runner, context, and cancellation contract.

Covers StageRunner, StageContext, and CancellationToken behaviours for
deterministic seeding, parameter validation, resume, cancellation, retry, and
downstream invalidation (WP-01 task 9, ADR-0013).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from selene_core.pipeline import (
    ArtifactStore,
    CancellationToken,
    StageContext,
    StageFailed,
    StageOutcome,
    StageOutput,
    StageRunner,
)
from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.noop import NoOpBehaviour, NoOpStage

pytestmark = pytest.mark.unit


class SimpleStage:
    """Minimal hand-written stage for testing specific behaviours."""

    def __init__(
        self,
        name: str = "test_stage",
        version: str = "1",
        depends_on: tuple[str, ...] = (),
        parameter_keys: tuple[str, ...] = (),
        algorithm: str | None = None,
        algorithm_version: str | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.depends_on = depends_on
        self.parameter_keys = parameter_keys
        self.algorithm = algorithm
        self.algorithm_version = algorithm_version
        self.ran = False
        self.run_seeds: list[int] = []

    def run(self, context: StageContext) -> StageOutput:
        """Record that this stage ran and capture its seed."""
        self.ran = True
        self.run_seeds.append(context.seed)
        return StageOutput()


class ParameterReadingStage:
    """A stage that reads parameters and records them."""

    def __init__(
        self,
        name: str = "param_stage",
        parameter_keys: tuple[str, ...] = ("value",),
    ) -> None:
        self.name = name
        self.version = "1"
        self.depends_on = ()
        self.parameter_keys = parameter_keys
        self.algorithm = None
        self.algorithm_version = None
        self.read_params: dict[str, Any] = {}

    def run(self, context: StageContext) -> StageOutput:
        """Read and record parameters."""
        for key in self.parameter_keys:
            self.read_params[key] = context.parameter(key)
        return StageOutput()


class CheckpointingStage:
    """A stage that calls checkpoint multiple times."""

    name: str
    version: str
    depends_on: tuple[str, ...]
    parameter_keys: tuple[str, ...]
    algorithm: str | None
    algorithm_version: str | None

    def __init__(self, name: str = "checkpoint_stage", checkpoints: int = 2) -> None:
        self.name = name
        self.version = "1"
        self.depends_on = ()
        self.parameter_keys = ()
        self.algorithm = None
        self.algorithm_version = None
        self.checkpoints = checkpoints
        self.checkpoint_count = 0

    def run(self, context: StageContext) -> StageOutput:
        """Call checkpoint multiple times."""
        for _ in range(self.checkpoints):
            context.checkpoint()
            self.checkpoint_count += 1
        return StageOutput()


class FailingStage:
    """A stage that always fails."""

    def __init__(self, name: str = "failing_stage") -> None:
        self.name = name
        self.version = "1"
        self.depends_on = ()
        self.parameter_keys = ()
        self.algorithm = None
        self.algorithm_version = None

    def run(self, context: StageContext) -> StageOutput:
        raise StageFailed(
            FailureCode.PRODUCT_SCHEMA_INVALID, "deliberate failure", {"stage": self.name}
        )


class Test_Unknown_Missing_Parameters:
    """Test case 1: Unknown/missing parameter validation."""

    def test_unknown_parameter_rejected(self, tmp_path: Path) -> None:
        """Runner raises StageFailed for unknown parameters."""
        store = ArtifactStore(tmp_path / "run")
        stage = SimpleStage(parameter_keys=("message",))
        runner = StageRunner(store, run_id="test-1", parameters={"extra": 1, "message": "hi"})

        with pytest.raises(StageFailed) as exc_info:
            runner.run([stage])

        assert exc_info.value.code == FailureCode.VALIDATION_UNKNOWN_PARAMETER
        assert not store.artifacts_root.exists()

    def test_missing_parameter_rejected(self, tmp_path: Path) -> None:
        """Runner raises StageFailed for missing parameters."""
        store = ArtifactStore(tmp_path / "run")
        stage = SimpleStage(parameter_keys=("required_param",))
        runner = StageRunner(store, run_id="test-2", parameters={})

        with pytest.raises(StageFailed) as exc_info:
            runner.run([stage])

        assert exc_info.value.code == FailureCode.VALIDATION_UNKNOWN_PARAMETER
        assert not store.artifacts_root.exists()


class Test_Happy_Path_Determinism:
    """Test case 2: Deterministic seeding across runs."""

    def test_deterministic_seeds(self, tmp_path: Path) -> None:
        """Same seed input produces same stage seeds across independent runs."""
        run1_seeds = []
        run2_seeds = []

        # First run
        store1 = ArtifactStore(tmp_path / "run1")
        stage1a = SimpleStage(name="stage_a", parameter_keys=())
        stage1b = SimpleStage(name="stage_b", depends_on=("stage_a",), parameter_keys=())
        runner1 = StageRunner(store1, run_id="test-seed-1", parameters={}, seed=42)
        runner1.run([stage1a, stage1b], resume=False)
        run1_seeds = stage1a.run_seeds + stage1b.run_seeds

        # Second independent run with same seed
        store2 = ArtifactStore(tmp_path / "run2")
        stage2a = SimpleStage(name="stage_a", parameter_keys=())
        stage2b = SimpleStage(name="stage_b", depends_on=("stage_a",), parameter_keys=())
        runner2 = StageRunner(store2, run_id="test-seed-2", parameters={}, seed=42)
        runner2.run([stage2a, stage2b], resume=False)
        run2_seeds = stage2a.run_seeds + stage2b.run_seeds

        assert len(run1_seeds) == 2
        assert len(run2_seeds) == 2
        assert run1_seeds == run2_seeds


class Test_Resume_Reuses_Verified:
    """Test case 3: Resume reuses verified stage results."""

    def test_resume_reuses_result(self, tmp_path: Path) -> None:
        """Second run with resume=True reuses manifest results without re-running."""
        store = ArtifactStore(tmp_path / "run")

        # First run: two stages
        stage1 = NoOpStage(name="noop_0", behaviour=NoOpBehaviour.SUCCEED)
        stage2 = NoOpStage(name="noop_1", depends_on=("noop_0",), behaviour=NoOpBehaviour.SUCCEED)
        runner = StageRunner(store, run_id="test-resume", parameters={"message": "hello"})
        manifest1 = runner.run([stage1, stage2])

        assert len(manifest1.stages) == 2
        assert manifest1.stages[0].attempt == 1
        assert manifest1.stages[1].attempt == 1

        # Second run with fresh runner instance, same store, resume=True
        stage3 = NoOpStage(name="noop_0", behaviour=NoOpBehaviour.SUCCEED)
        stage4 = NoOpStage(name="noop_1", depends_on=("noop_0",), behaviour=NoOpBehaviour.SUCCEED)
        runner2 = StageRunner(store, run_id="test-resume", parameters={"message": "hello"})
        manifest2 = runner2.run([stage3, stage4], resume=True)

        # Stages should have same attempt numbers (not re-run)
        assert len(manifest2.stages) == 2
        assert manifest2.stages[0].attempt == 1
        assert manifest2.stages[1].attempt == 1
        # Commit IDs should match (same verified result)
        assert manifest2.stages[0].commit_id == manifest1.stages[0].commit_id
        assert manifest2.stages[1].commit_id == manifest1.stages[1].commit_id


class Test_Resume_Retests_On_Tampering:
    """Test case 4: Resume re-runs when artifact is tampered with."""

    def test_resume_reruns_on_artifact_tampering(self, tmp_path: Path) -> None:
        """Corrupted artifact forces re-run instead of reuse."""
        store = ArtifactStore(tmp_path / "run")

        # First run
        stage1 = NoOpStage(name="noop_0", behaviour=NoOpBehaviour.SUCCEED)
        runner = StageRunner(store, run_id="test-tamper", parameters={"message": "hello"})
        manifest1 = runner.run([stage1])
        assert manifest1.stages[0].attempt == 1

        # Corrupt the artifact
        artifact = manifest1.stages[0].outputs[0]
        artifact_path = store.artifacts_root / artifact.relative_path
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        content = artifact_path.read_bytes()
        corrupted = content[:-1] + (b"X" if content[-1:] != b"X" else b"Y")
        artifact_path.write_bytes(corrupted)

        # Second run with resume=True
        stage2 = NoOpStage(name="noop_0", behaviour=NoOpBehaviour.SUCCEED)
        runner2 = StageRunner(store, run_id="test-tamper", parameters={"message": "hello"})
        manifest2 = runner2.run([stage2], resume=True)

        # Stage should have re-run (new attempt)
        assert len(manifest2.stages) == 2
        assert manifest2.stages[0].attempt == 1
        assert manifest2.stages[1].attempt == 2


class Test_Resume_Downstream_Invalidation:
    """Test case 5: Resume re-runs downstream when upstream changes."""

    def test_downstream_invalidation_on_parameter_change(self, tmp_path: Path) -> None:
        """Parameter change upstream invalidates downstream stages via digest.

        Stage 2 declares NO parameters, so it can only re-run if its input digest
        (which includes stage 1's output) changes. This proves downstream
        invalidation flows structurally through _input_digests, not direct parameter
        dependence.
        """
        store = ArtifactStore(tmp_path / "run")

        # First run: stage1 reads "message", stage2 reads nothing
        stage1 = NoOpStage(
            name="noop_0",
            parameter_keys=("message",),
            behaviour=NoOpBehaviour.SUCCEED,
        )
        # Use SimpleStage for stage2 (doesn't try to read any parameters)
        stage2 = SimpleStage(
            name="noop_1",
            depends_on=("noop_0",),
            parameter_keys=(),  # Stage 2 declares NO parameters
        )
        runner = StageRunner(store, run_id="test-inv", parameters={"message": "first"})
        manifest1 = runner.run([stage1, stage2])
        stage1_commit = manifest1.stages[0].commit_id
        stage2_commit = manifest1.stages[1].commit_id

        # Second run with changed parameter: only stage1 reads it
        stage3 = NoOpStage(
            name="noop_0",
            parameter_keys=("message",),
            behaviour=NoOpBehaviour.SUCCEED,
        )
        stage4 = SimpleStage(
            name="noop_1",
            depends_on=("noop_0",),
            parameter_keys=(),  # Still no parameters
        )
        runner2 = StageRunner(store, run_id="test-inv", parameters={"message": "second"})
        manifest2 = runner2.run([stage3, stage4], resume=True)

        # Stage 1 re-ran because its parameter changed
        assert manifest2.stages[2].attempt == 2
        assert manifest2.stages[2].commit_id != stage1_commit
        # Stage 2 re-ran ONLY because stage 1's output (its input) changed,
        # not because stage 2 directly reads the parameter
        assert manifest2.stages[3].attempt == 2
        assert manifest2.stages[3].commit_id != stage2_commit


class Test_Cancellation:
    """Test case 6: Cooperative cancellation behavior."""

    def test_cancellation_stops_at_checkpoint(self, tmp_path: Path) -> None:
        """CancellationToken.cancel() causes RunCancelled at next checkpoint."""
        store = ArtifactStore(tmp_path / "run")
        stage = CheckpointingStage(checkpoints=3)
        token = CancellationToken()
        token.cancel()

        runner = StageRunner(store, run_id="test-cancel", parameters={})
        manifest = runner.run([stage], cancellation=token)

        assert len(manifest.stages) == 1
        result = manifest.stages[0]
        assert result.outcome == StageOutcome.CANCELLED
        assert result.failure is not None
        assert result.failure.code == FailureCode.INTERNAL_CANCELLED

    def test_cancelled_scratch_abandoned(self, tmp_path: Path) -> None:
        """Scratch files from cancelled stage are abandoned, not published.

        Stage runs, writes scratch, hits first checkpoint successfully,
        then cancels at second checkpoint. Scratch must be abandoned.
        """
        store = ArtifactStore(tmp_path / "run")
        token = CancellationToken()

        # Cancel token BETWEEN checkpoints via wrapper
        def wrapped_run(context: StageContext) -> StageOutput:
            # Write scratch
            scratch_file = context.scratch_path("temp.txt")
            scratch_file.write_text("temporary content")
            # First checkpoint succeeds
            context.checkpoint()
            # Now cancel for second checkpoint
            token.cancel()
            # Second checkpoint raises RunCancelled
            context.checkpoint()
            return StageOutput()

        stage = SimpleStage(name="multi_checkpoint", parameter_keys=())
        stage.run = wrapped_run  # type: ignore[method-assign]

        runner = StageRunner(store, run_id="test-cancel-scratch", parameters={})
        manifest = runner.run([stage], cancellation=token)

        # Stage outcome is CANCELLED
        assert len(manifest.stages) == 1
        assert manifest.stages[0].outcome == StageOutcome.CANCELLED

        # Scratch directory was abandoned by ArtifactStore.abandon().
        # Check directly via pathlib without calling scratch_for() which
        # mutates the directory. ArtifactStore.abandon() removes the directory
        # via shutil.rmtree(), so it should not exist.
        scratch_dir = store.scratch_root / "multi_checkpoint" / "1"
        assert not scratch_dir.exists(), (
            f"scratch directory {scratch_dir} should have been removed by "
            "ArtifactStore.abandon(), but it still exists"
        )


class Test_Retry_Retryable:
    """Test case 7: Retry on retryable failure."""

    def test_retryable_failure_retries(self, tmp_path: Path) -> None:
        """FAIL_RETRYABLE re-runs up to max_attempts."""
        store = ArtifactStore(tmp_path / "run")
        stage = NoOpStage(
            name="noop_0",
            behaviour=NoOpBehaviour.FAIL_RETRYABLE,
            parameter_keys=("message",),
        )
        runner = StageRunner(
            store, run_id="test-retry", parameters={"message": "hi"}, max_attempts=3
        )

        manifest = runner.run([stage])

        # Manifest records one entry per stage, with attempt field showing the current attempt
        assert len(manifest.stages) == 1
        result = manifest.stages[0]
        assert result.stage_name == "noop_0"
        # All retries exhausted
        assert result.outcome == StageOutcome.FAILED
        assert result.attempt == 3


class Test_No_Retry_Non_Retryable:
    """Test case 8: No retry on non-retryable failure."""

    def test_non_retryable_failure_no_retry(self, tmp_path: Path) -> None:
        """FAIL with non-retryable code does not retry."""
        store = ArtifactStore(tmp_path / "run")
        stage = NoOpStage(name="noop_0", behaviour=NoOpBehaviour.FAIL, parameter_keys=("message",))
        runner = StageRunner(
            store, run_id="test-no-retry", parameters={"message": "hi"}, max_attempts=3
        )

        manifest = runner.run([stage])

        # Only one attempt, despite max_attempts=3
        assert len(manifest.stages) == 1
        assert manifest.stages[0].attempt == 1
        assert manifest.stages[0].outcome == StageOutcome.FAILED


class Test_Rejection_Not_Retried:
    """Test case 9: Rejection is not retried, and stops the chain."""

    def test_rejection_not_retried(self, tmp_path: Path) -> None:
        """REJECT does not retry and outcome is REJECTED."""
        store = ArtifactStore(tmp_path / "run")
        stage = NoOpStage(
            name="noop_0", behaviour=NoOpBehaviour.REJECT, parameter_keys=("message",)
        )
        runner = StageRunner(store, run_id="test-reject", parameters={"message": "hi"})

        manifest = runner.run([stage])

        assert len(manifest.stages) == 1
        assert manifest.stages[0].outcome == StageOutcome.REJECTED
        assert manifest.stages[0].attempt == 1

    def test_rejection_stops_chain(self, tmp_path: Path) -> None:
        """Rejection prevents downstream stages from running."""
        store = ArtifactStore(tmp_path / "run")
        stage1 = NoOpStage(
            name="noop_0", behaviour=NoOpBehaviour.REJECT, parameter_keys=("message",)
        )
        stage2 = SimpleStage(name="noop_1", depends_on=("noop_0",), parameter_keys=())
        runner = StageRunner(store, run_id="test-reject-stop", parameters={"message": "hi"})

        manifest = runner.run([stage1, stage2])

        # Only stage 1 ran; stage 2 never attempted
        assert len(manifest.stages) == 1
        assert manifest.stages[0].stage_name == "noop_0"
        assert not stage2.ran


class Test_Unhandled_Exception:
    """Test case 10: Unhandled exception becomes INTERNAL_UNEXPECTED_ERROR."""

    def test_unhandled_exception_becomes_error(self, tmp_path: Path) -> None:
        """Unhandled exception caught and recorded with INTERNAL_UNEXPECTED_ERROR."""
        store = ArtifactStore(tmp_path / "run")
        stage = NoOpStage(name="noop_0", behaviour=NoOpBehaviour.RAISE, parameter_keys=("message",))
        runner = StageRunner(store, run_id="test-raise", parameters={"message": "hi"})

        manifest = runner.run([stage])

        assert len(manifest.stages) == 1
        result = manifest.stages[0]
        assert result.outcome == StageOutcome.FAILED
        assert result.failure is not None
        assert result.failure.code == FailureCode.INTERNAL_UNEXPECTED_ERROR


class Test_Orphan_Not_Discoverable:
    """Test case 11: Orphan artifacts are never published."""

    def test_orphan_artifacts_not_published(self, tmp_path: Path) -> None:
        """ORPHAN_THEN_FAIL writes scratch but never publishes to artifacts.

        The scratch write must not become discoverable in artifacts_root.
        """
        store = ArtifactStore(tmp_path / "run")
        stage = NoOpStage(
            name="noop_0", behaviour=NoOpBehaviour.ORPHAN_THEN_FAIL, parameter_keys=("message",)
        )
        runner = StageRunner(store, run_id="test-orphan", parameters={"message": "hi"})

        manifest = runner.run([stage])

        # Stage failed
        assert len(manifest.stages) == 1
        result = manifest.stages[0]
        assert result.outcome == StageOutcome.FAILED

        # The critical check: no file matching the stage's expected output name
        # exists in artifacts_root. NoOpStage publishes "result.json" with path
        # "noop_0/1/result.json", so that file must not exist.
        expected_artifact_path = store.artifacts_root / "noop_0" / "1" / "result.json"
        assert not expected_artifact_path.exists(), (
            f"orphaned artifact was published to {expected_artifact_path} "
            "— scratch write must not become discoverable"
        )

        # Also verify no artifacts_root directory exists at all
        # (if store never wrote anything)
        if store.artifacts_root.exists():
            artifact_files = list(store.artifacts_root.rglob("*"))
            assert len(artifact_files) == 0, f"artifacts_root not empty: {artifact_files}"


class Test_Parameter_Undeclared:
    """Test case 12: Reading undeclared parameter raises KeyError."""

    def test_undeclared_parameter_raises_keyerror(self, tmp_path: Path) -> None:
        """Accessing undeclared parameter via context.parameter() raises KeyError.

        This test isolates the exact exception type, not just its conversion
        to FAILED by the runner's catch-all. The context must enforce that
        stages can only read declared parameters.
        """
        store = ArtifactStore(tmp_path / "run")
        token = CancellationToken()

        # Build StageContext directly (bypass runner's exception wrapping)
        context = StageContext(
            run_id="test-undeclared",
            stage_name="test_stage",
            attempt=1,
            scratch=store.scratch_for("test_stage", 1),
            store=store,
            parameters={"declared": "value"},  # Only this key exists
            seed=42,
            cancellation=token,
            inputs={},
        )

        # Accessing an undeclared parameter must raise KeyError specifically
        with pytest.raises(KeyError) as exc_info:
            context.parameter("undeclared")

        # Verify the error message is informative
        assert "undeclared" in str(exc_info.value)
        assert "parameter_keys" in str(exc_info.value)


class Test_Chain_Halts_On_Failure:
    """Test case 13: Runner halts the chain on first non-success."""

    def test_chain_halts_on_failure(self, tmp_path: Path) -> None:
        """Failing stage stops execution; downstream stages do not run."""
        store = ArtifactStore(tmp_path / "run")
        stage1 = NoOpStage(
            name="noop_0",
            behaviour=NoOpBehaviour.SUCCEED,
            parameter_keys=("message",),
        )
        stage2 = NoOpStage(
            name="noop_1",
            depends_on=("noop_0",),
            behaviour=NoOpBehaviour.FAIL,
            parameter_keys=("message",),
        )
        stage3 = SimpleStage(name="noop_2", depends_on=("noop_1",), parameter_keys=())
        runner = StageRunner(store, run_id="test-halt", parameters={"message": "hi"})

        manifest = runner.run([stage1, stage2, stage3])

        # Stage 1 succeeded, stage 2 failed, stage 3 never ran
        assert len(manifest.stages) == 2
        assert manifest.stages[0].stage_name == "noop_0"
        assert manifest.stages[0].outcome == StageOutcome.SUCCEEDED
        assert manifest.stages[1].stage_name == "noop_1"
        assert manifest.stages[1].outcome == StageOutcome.FAILED
        # Stage 3 never attempted
        assert not stage3.ran
