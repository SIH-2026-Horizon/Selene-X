"""The SELENE-XR command line interface.

The local ``register-product`` command is intentionally narrow: it validates a
manifest and existing local source files without uploading, moving, or mutating
them. Other scientific commands remain absent until their work packages exist.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

from selene_core.ingest.payload_adapter import IirsAdapter, OhrcAdapter, PayloadAdapter, Tmc2Adapter
from selene_core.ingest.registration import ProductRegistrationError, register_local_product
from selene_core.pipeline import (
    ArtifactStore,
    ArtifactVerificationError,
    CancellationToken,
    RunManifest,
    StageFailed,
    StageOutcome,
    StageRunner,
    capture_environment,
    configure_logging,
)
from selene_core.pipeline.noop import NoOpBehaviour, NoOpStage

app = typer.Typer(
    name="selene",
    help="SELENE-XR lunar image registration. Scientific commands are not implemented yet.",
    no_args_is_help=True,
    add_completion=False,
)

_EXIT_OK = 0
_EXIT_REJECTED = 2
_EXIT_FAILED = 3
_EXIT_CANCELLED = 4


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


@app.callback()
def _root(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Emit structured debug logs to stderr.")
    ] = False,
) -> None:
    configure_logging(logging.DEBUG if verbose else logging.WARNING, stream=sys.stderr)


@app.command()
def env() -> None:
    """Report the interpreter, platform, and dependency versions of this build."""
    _echo_json(capture_environment().model_dump())


@app.command("register-product")
def register_product(
    manifest: Annotated[Path, typer.Argument(help="Trusted-local product input manifest JSON.")],
    payload: Annotated[str, typer.Option(help="Payload adapter: OHRC, TMC-2, or IIRS.")],
) -> None:
    """Verify a local source product without changing any source bytes.

    Requires the optional ``selene-core[raster]`` extra to inspect the raster.
    This command deliberately accepts no URL, upload, or caller supplied
    storage path: server-side upload registration is a separate WP-10 concern.
    """
    adapters: dict[str, Callable[[], PayloadAdapter]] = {
        "OHRC": OhrcAdapter,
        "TMC-2": Tmc2Adapter,
        "IIRS": IirsAdapter,
    }
    adapter_cls = adapters.get(payload.upper())
    if adapter_cls is None:
        raise typer.BadParameter("must be one of OHRC, TMC-2, IIRS", param_hint="--payload")
    try:
        registered = register_local_product(manifest, adapter_cls())
    except ProductRegistrationError as error:
        _echo_json({"outcome": "quarantined", "reason": error.reason, "message": str(error)})
        raise typer.Exit(_EXIT_REJECTED) from error
    _echo_json(
        {
            "outcome": "registered",
            "product_id": registered.product_id,
            "payload_family": registered.payload_family,
            "source_digests": dict(registered.source_digests),
            "raster_shape": registered.raster_shape,
            "dtype": registered.dtype,
            "geometry_validated": registered.metadata.geometry_validated,
            "geometry_validation_note": registered.metadata.geometry_validation_note,
        }
    )


@app.command()
def noop(
    run_dir: Annotated[Path, typer.Argument(help="Run directory to create or resume.")],
    message: Annotated[str, typer.Option(help="Recorded in the published artefact.")] = "hello",
    stages: Annotated[int, typer.Option(min=1, max=16, help="How many no-op stages to chain.")] = 2,
    behaviour: Annotated[
        NoOpBehaviour, typer.Option(help="What the final stage should do.")
    ] = NoOpBehaviour.SUCCEED,
    cancel_before_stage: Annotated[
        int | None,
        typer.Option(min=1, help="Request cancellation before this 1-based stage index."),
    ] = None,
    resume: Annotated[
        bool, typer.Option(help="Reuse verified stage results from a previous run.")
    ] = True,
    run_id: Annotated[str | None, typer.Option(help="Reuse an existing run identifier.")] = None,
) -> None:
    """Run the no-op pipeline that proves the stage protocol.

    This performs no science. It exercises packaging, parameter resolution,
    deterministic seeding, atomic publication, resume, cancellation, retry, and
    error propagation end to end, which is WP-01's exit condition.
    """
    store = ArtifactStore(run_dir)
    existing = store.manifest_path
    resolved_run_id = run_id or (
        RunManifest.read(existing).run_id
        if resume and existing.is_file()
        else f"noop-{uuid.uuid4().hex[:12]}"
    )

    chain = [
        NoOpStage(
            name=f"noop_{index}",
            depends_on=() if index == 0 else (f"noop_{index - 1}",),
            behaviour=behaviour if index == stages - 1 else NoOpBehaviour.SUCCEED,
        )
        for index in range(stages)
    ]

    token = CancellationToken()
    if cancel_before_stage is not None:
        if cancel_before_stage > stages:
            raise typer.BadParameter(
                f"--cancel-before-stage {cancel_before_stage} exceeds --stages {stages}"
            )
        target = chain[cancel_before_stage - 1]
        original_run = target.run

        def cancelling_run(context: Any, _original: Any = original_run) -> Any:
            token.cancel()
            return _original(context)

        target.run = cancelling_run  # type: ignore[method-assign]

    runner = StageRunner(
        store,
        run_id=resolved_run_id,
        parameters={"message": message},
        seed=1,
    )
    try:
        manifest = runner.run(chain, cancellation=token, resume=resume)
    except StageFailed as error:
        _echo_json(
            {
                "run_id": resolved_run_id,
                "outcome": "failed",
                "failure_code": str(error.code),
                "message": str(error),
                "context": error.context,
            }
        )
        raise typer.Exit(_EXIT_FAILED) from error

    final = manifest.stages[-1] if manifest.stages else None
    _echo_json(
        {
            "run_id": manifest.run_id,
            "manifest": str(store.manifest_path),
            "stages": [
                {
                    "stage": result.stage_name,
                    "attempt": result.attempt,
                    "outcome": str(result.outcome),
                    "failure_code": str(result.failure.code) if result.failure else None,
                    "remediation": result.failure.remediation if result.failure else None,
                    "outputs": [artifact.relative_path for artifact in result.outputs],
                }
                for result in manifest.stages
            ],
        }
    )
    raise typer.Exit(_exit_code_for(final.outcome if final else StageOutcome.FAILED))


def _exit_code_for(outcome: StageOutcome) -> int:
    if outcome.is_success:
        return _EXIT_OK
    if outcome is StageOutcome.REJECTED:
        return _EXIT_REJECTED
    if outcome is StageOutcome.CANCELLED:
        return _EXIT_CANCELLED
    return _EXIT_FAILED


@app.command("validate-run")
def validate_run(
    run_dir: Annotated[Path, typer.Argument(help="Run directory to verify.")],
) -> None:
    """Recompute every published artefact's checksum without running anything.

    Answers one question: does this run bundle still contain exactly the bytes
    its manifest claims? A tampered, truncated, or missing artefact is reported
    per artefact rather than as one opaque failure.
    """
    store = ArtifactStore(run_dir)
    if not store.manifest_path.is_file():
        typer.echo(f"no run manifest at {store.manifest_path}", err=True)
        raise typer.Exit(_EXIT_FAILED)

    manifest = RunManifest.read(store.manifest_path)
    checked: list[dict[str, Any]] = []
    problems = 0
    # A stage that re-ran leaves its earlier attempts in the manifest and their
    # artefacts on disk. Those are history, not the run's current answer, so
    # they are verified but labelled, and a reader is never left guessing which
    # artefact a claim should cite.
    current_attempts = {result.stage_name: result.attempt for result in manifest.stages}
    for result in manifest.stages:
        superseded = result.attempt != current_attempts[result.stage_name]
        for artifact in result.outputs:
            entry: dict[str, Any] = {
                "stage": result.stage_name,
                "attempt": result.attempt,
                "role": "superseded" if superseded else "current",
                "artifact": artifact.relative_path,
                "sha256": artifact.sha256,
            }
            try:
                store.verify(artifact)
                entry["state"] = "verified"
            except ArtifactVerificationError as error:
                entry["state"] = "invalid"
                entry["failure_code"] = str(error.code)
                entry["detail"] = str(error)
                problems += 1
            checked.append(entry)

    _echo_json(
        {
            "run_id": manifest.run_id,
            "artefacts_checked": len(checked),
            "artefacts_invalid": problems,
            "results": checked,
        }
    )
    raise typer.Exit(_EXIT_OK if problems == 0 else _EXIT_FAILED)


def main() -> None:
    """Console script entry point declared in ``pyproject.toml``."""
    app()
