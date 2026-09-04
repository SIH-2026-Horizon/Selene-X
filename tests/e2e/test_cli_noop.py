"""End-to-end tests for the selene CLI noop and validate-run commands.

Exercises the full packaging, configuration, atomic result writing, resume,
cancellation, and error propagation chain as required by WP-01 task 11.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from selene_client.cli import app
from selene_core.pipeline import RunManifest

pytestmark = pytest.mark.e2e


@pytest.fixture
def cli_runner() -> CliRunner:
    """Typer CLI test runner."""
    return CliRunner()


class Test_Env_Command:
    """Test case 1: selene env command."""

    def test_env_exits_zero_prints_json(self, cli_runner: CliRunner) -> None:
        """selene env exits 0 and prints valid JSON with environment info."""
        result = cli_runner.invoke(app, ["env"])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "python_version" in output
        assert "platform" in output


class Test_Noop_Basic:
    """Test case 2: selene noop basic operation."""

    def test_noop_exits_zero_creates_manifest(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """selene noop succeeds, prints JSON with run_id, creates manifest."""
        run_dir = tmp_path / "noop_run"
        result = cli_runner.invoke(app, ["noop", str(run_dir)])

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "run_id" in output
        assert "manifest" in output
        assert "stages" in output

        # Manifest file should exist
        manifest_path = run_dir / "run.json"
        assert manifest_path.exists()
        manifest = RunManifest.read(manifest_path)
        assert manifest.run_id == output["run_id"]


class Test_Noop_Reject:
    """Test case 3: selene noop with reject behavior."""

    def test_noop_reject_exits_two(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """selene noop --behaviour reject exits with code 2 (_EXIT_REJECTED)."""
        run_dir = tmp_path / "reject_run"
        result = cli_runner.invoke(app, ["noop", str(run_dir), "--behaviour", "reject"])

        assert result.exit_code == 2
        output = json.loads(result.stdout)
        assert output["stages"][-1]["outcome"] == "rejected"


class Test_Noop_Fail:
    """Test case 4: selene noop with fail behavior."""

    def test_noop_fail_exits_three(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """selene noop --behaviour fail exits with code 3 (_EXIT_FAILED)."""
        run_dir = tmp_path / "fail_run"
        result = cli_runner.invoke(app, ["noop", str(run_dir), "--behaviour", "fail"])

        assert result.exit_code == 3
        output = json.loads(result.stdout)
        assert output["stages"][-1]["outcome"] == "failed"
        assert output["stages"][-1]["failure_code"] is not None


class Test_Noop_Cancellation:
    """Test case 5: selene noop with cancellation."""

    def test_noop_cancel_before_stage(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """selene noop --stages 3 --cancel-before-stage 2 exits with code 4 (_EXIT_CANCELLED)."""
        run_dir = tmp_path / "cancel_run"
        result = cli_runner.invoke(
            app, ["noop", str(run_dir), "--stages", "3", "--cancel-before-stage", "2"]
        )

        assert result.exit_code == 4
        output = json.loads(result.stdout)
        stages = output["stages"]
        # Stage 2 should be cancelled
        assert any(s["outcome"] == "cancelled" for s in stages)
        # Stage 3 should not appear
        assert len(stages) < 3


class Test_Resume_Across_Invocations:
    """Test case 6: Resume across two CLI invocations."""

    def test_resume_reuses_results(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """Second invocation with same run_id reuses results without re-running."""
        run_dir = tmp_path / "resume_run"

        # First invocation
        result1 = cli_runner.invoke(app, ["noop", str(run_dir), "--stages", "2"])
        assert result1.exit_code == 0
        output1 = json.loads(result1.stdout)
        run_id = output1["run_id"]

        # Second invocation with same run_id
        result2 = cli_runner.invoke(
            app, ["noop", str(run_dir), "--run-id", run_id, "--stages", "2"]
        )
        assert result2.exit_code == 0

        # Check manifest: stages should still have one attempt each
        manifest = RunManifest.read(run_dir / "run.json")
        stage_names = [r.stage_name for r in manifest.stages]
        assert stage_names.count("noop_0") == 1
        assert stage_names.count("noop_1") == 1
        # Each stage should have only one attempt
        for stage_name in ["noop_0", "noop_1"]:
            attempts = [r.attempt for r in manifest.stages if r.stage_name == stage_name]
            assert attempts == [1]


class Test_Interrupted_Then_Restarted:
    """Test case 7: Interrupted-then-restarted proof (WP-01 task 11 requirement)."""

    def test_interrupted_restarted_flow(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """First run cancels mid-chain; second run completes from where it left."""
        run_dir = tmp_path / "interrupt_run"

        # First invocation: cancel before stage 2
        result1 = cli_runner.invoke(
            app,
            ["noop", str(run_dir), "--stages", "3", "--cancel-before-stage", "2"],
        )
        assert result1.exit_code == 4

        # Read manifest to capture stage 1's state
        manifest1 = RunManifest.read(run_dir / "run.json")
        stage1_first_result = next(r for r in manifest1.stages if r.stage_name == "noop_0")
        stage1_commit_id = stage1_first_result.commit_id
        stage1_artifact_paths = [a.relative_path for a in stage1_first_result.outputs]

        # Second invocation: same run_dir, let it complete
        result2 = cli_runner.invoke(app, ["noop", str(run_dir), "--stages", "3"])
        assert result2.exit_code == 0

        # Read final manifest
        manifest2 = RunManifest.read(run_dir / "run.json")

        # Stage 1 should still have only one attempt and same commit_id (reused)
        stage1_results = [r for r in manifest2.stages if r.stage_name == "noop_0"]
        assert len(stage1_results) == 1
        assert stage1_results[0].attempt == 1
        assert stage1_results[0].commit_id == stage1_commit_id
        # Verify stage 1's artifact is unchanged
        stage1_artifact_paths_after = [a.relative_path for a in stage1_results[0].outputs]
        assert stage1_artifact_paths_after == stage1_artifact_paths

        # Stages 2 and 3 should now show succeeded
        stage2_results = [r for r in manifest2.stages if r.stage_name == "noop_1"]
        stage3_results = [r for r in manifest2.stages if r.stage_name == "noop_2"]
        assert len(stage2_results) > 0
        assert len(stage3_results) > 0
        assert stage2_results[-1].outcome == "succeeded"
        assert stage3_results[-1].outcome == "succeeded"


class Test_Validate_Run_Valid:
    """Test case 8: validate-run after successful noop run."""

    def test_validate_run_valid_exit_zero(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """selene validate-run after successful noop exits 0 with no invalid artifacts."""
        run_dir = tmp_path / "validate_run"

        # Run noop to completion
        result_noop = cli_runner.invoke(app, ["noop", str(run_dir)])
        assert result_noop.exit_code == 0

        # Validate
        result_validate = cli_runner.invoke(app, ["validate-run", str(run_dir)])

        assert result_validate.exit_code == 0
        output = json.loads(result_validate.stdout)
        assert output["artefacts_invalid"] == 0
        assert all(r["state"] == "verified" for r in output["results"])


class Test_Validate_Run_Corrupted:
    """Test case 9: validate-run detects corrupted artifacts."""

    def test_validate_run_corrupted_exit_three(self, tmp_path: Path, cli_runner: CliRunner) -> None:
        """selene validate-run detects corrupted artifact and exits with code 3."""
        run_dir = tmp_path / "corrupt_run"

        # Run noop
        result_noop = cli_runner.invoke(app, ["noop", str(run_dir)])
        assert result_noop.exit_code == 0

        # Corrupt an artifact
        manifest = RunManifest.read(run_dir / "run.json")
        artifact = manifest.stages[0].outputs[0]
        artifact_path = run_dir / "artifacts" / artifact.relative_path
        content = artifact_path.read_bytes()
        corrupted = content[:-1] + (b"X" if content[-1:] != b"X" else b"Y")
        artifact_path.write_bytes(corrupted)

        # Validate
        result_validate = cli_runner.invoke(app, ["validate-run", str(run_dir)])

        assert result_validate.exit_code == 3
        output = json.loads(result_validate.stdout)
        assert output["artefacts_invalid"] > 0
        assert any(r["state"] == "invalid" for r in output["results"])
        assert any(r.get("failure_code") for r in output["results"])


class Test_Validate_Run_Nonexistent:
    """Test case 10: validate-run on nonexistent directory."""

    def test_validate_run_nonexistent_exit_three(
        self, tmp_path: Path, cli_runner: CliRunner
    ) -> None:
        """selene validate-run on nonexistent dir exits 3 with error message."""
        nonexistent = tmp_path / "does_not_exist"
        result = cli_runner.invoke(app, ["validate-run", str(nonexistent)])

        assert result.exit_code == 3
        # Should have an error message in output
        assert "no run manifest" in result.output.lower() or result.stderr


class Test_Help_Advertises_Only_Implemented_Commands:
    """Test case 11: local registration is real; remaining stubs stay absent."""

    def test_help_advertises_local_registration_but_excludes_other_stubs(
        self, cli_runner: CliRunner
    ) -> None:
        result = cli_runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        help_text = result.stdout
        assert "validate-product" not in help_text
        assert "preflight" not in help_text
        assert "register-product" in help_text
        assert "benchmark" not in help_text
