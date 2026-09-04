"""The local stage runner (WP-01 tasks 9 and 11, ADR-0013).

The runner owns five behaviours that every interface depends on and that no
stage should reimplement:

* **Deterministic seeds.** Each stage receives a seed derived from the run seed
  and the stage's own identity, so adding a stage does not perturb the others.
* **Cooperative cancellation.** A stage checks a token at its own checkpoints.
  Cancellation abandons in-progress scratch and leaves every completed stage
  reusable.
* **Retry keyed by failure code.** Deterministic validation and scientific gate
  failures never retry.
* **Resume by fingerprint.** A stage is skipped only when its inputs,
  parameters, and versions match *and* every one of its recorded outputs still
  verifies byte for byte.
* **Downstream invalidation, structurally.** A stage's input digests are the
  output digests of the stages it depends on. If an upstream stage produces
  different bytes, every downstream fingerprint changes and those stages re-run.
  Invalidation is therefore a consequence of the data, not a bookkeeping step
  that can be forgotten.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from selene_core.pipeline.artifacts import ArtifactStore, ArtifactVerificationError
from selene_core.pipeline.failures import FailureCode, is_retryable
from selene_core.pipeline.hashing import digest_json, digest_many
from selene_core.pipeline.logging import get_logger, log_context
from selene_core.pipeline.manifest import RunManifest, capture_environment
from selene_core.pipeline.results import (
    ArtifactRef,
    PublicationState,
    ResourceUsage,
    StageFailure,
    StageOutcome,
    StageResult,
    StageWarning,
    stage_fingerprint,
)

__all__ = [
    "CancellationToken",
    "RunCancelled",
    "Stage",
    "StageContext",
    "StageFailed",
    "StageOutput",
    "StageRejected",
    "StageRunner",
]

_LOGGER = get_logger(__name__)

DEFAULT_MAX_ATTEMPTS: Final = 3


class RunCancelled(Exception):
    """Raised at a checkpoint after cancellation was requested."""


class StageRejected(Exception):
    """A stage ran correctly and refused on scientific grounds.

    This is a result. It is recorded as ``REJECTED`` with a stable code, and it
    is never retried: the same evidence will produce the same refusal.
    """

    def __init__(
        self, code: FailureCode, message: str, context: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


class StageFailed(Exception):
    """A stage could not run to completion.

    Whether the runner retries is decided by the code, not by the caller.
    """

    def __init__(
        self, code: FailureCode, message: str, context: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = dict(context or {})


class CancellationToken:
    """A cooperative cancellation flag.

    Cancellation is cooperative rather than pre-emptive because a stage killed
    mid-write cannot clean up after itself, and the guarantee that matters more
    than promptness is that no partial output survives.
    """

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation. Stages stop at their next checkpoint."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancelled

    def check(self) -> None:
        """Raise :class:`RunCancelled` if cancellation has been requested."""
        if self._cancelled:
            raise RunCancelled("cancellation requested")


@dataclass(frozen=True, slots=True)
class StageOutput:
    """What a stage returns on success."""

    outputs: tuple[ArtifactRef, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[StageWarning, ...] = ()
    validity_mask_summary: Mapping[str, Any] = field(default_factory=dict)


class StageContext:
    """Everything a stage is allowed to reach.

    A stage receives only the parameters it declared. Reading an undeclared
    parameter raises, which is what makes ``parameter_subset`` on the result an
    accurate record rather than an aspiration: a stage cannot depend on a
    parameter that its fingerprint does not cover.
    """

    def __init__(
        self,
        *,
        run_id: str,
        stage_name: str,
        attempt: int,
        scratch: Path,
        store: ArtifactStore,
        parameters: Mapping[str, Any],
        seed: int,
        cancellation: CancellationToken,
        inputs: Mapping[str, ArtifactRef],
    ) -> None:
        self.run_id = run_id
        self.stage_name = stage_name
        self.attempt = attempt
        self.scratch = scratch
        self.store = store
        self.seed = seed
        self.inputs = dict(inputs)
        self._parameters = dict(parameters)
        self._cancellation = cancellation

    def parameter(self, name: str) -> Any:
        """Return a declared parameter's resolved value."""
        if name not in self._parameters:
            raise KeyError(
                f"stage {self.stage_name!r} read undeclared parameter {name!r}; add it to the "
                "stage's parameter_keys so that it is covered by the resume fingerprint"
            )
        return self._parameters[name]

    @property
    def parameters(self) -> Mapping[str, Any]:
        """The declared parameter subset, read-only."""
        return dict(self._parameters)

    def checkpoint(self) -> None:
        """Yield to cancellation. Call between units of work."""
        self._cancellation.check()

    def scratch_path(self, name: str) -> Path:
        """Return a path inside this attempt's scratch directory."""
        return self.scratch / name

    def publish(self, source: Path, *, kind: str, media_type: str, **fields: Any) -> ArtifactRef:
        """Publish a scratch file under this stage attempt's own prefix.

        The attempt number is part of the path because published artefacts are
        immutable. A re-run with different parameters produces different bytes;
        writing them over the previous attempt's file would invalidate the
        earlier manifest record without leaving any trace that it happened.
        """
        return self.store.publish(
            source,
            relative_path=f"{self.stage_name}/{self.attempt}/{source.name}",
            kind=kind,
            media_type=media_type,
            **fields,
        )


@runtime_checkable
class Stage(Protocol):
    """One scientific step.

    A stage declares its identity, its dependencies, and the parameters it
    reads. Everything else about resume, retry, publication, and provenance is
    the runner's job.
    """

    name: str
    version: str
    """Bumped whenever behaviour changes. See :attr:`StageResult.stage_version`."""

    depends_on: tuple[str, ...]
    """Names of stages whose outputs this stage consumes."""

    parameter_keys: tuple[str, ...]
    """Parameters this stage may read."""

    algorithm: str | None
    algorithm_version: str | None
    """The configured algorithm this stage runs, declared before it runs because
    the resume fingerprint covers it. A stage that falls back to a different
    path at runtime records that in its metrics and per-record provenance; the
    fallback is an event within a configuration, not a different configuration.
    """

    def run(self, context: StageContext) -> StageOutput:
        """Do the work. Raise :class:`StageRejected` or :class:`StageFailed`."""
        ...


class StageRunner:
    """Executes a stage sequence against one run directory."""

    def __init__(
        self,
        store: ArtifactStore,
        *,
        run_id: str,
        parameters: Mapping[str, Any] | None = None,
        seed: int | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        external_inputs: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.run_id = run_id
        self.parameters = dict(parameters or {})
        self.seed = seed
        self.max_attempts = max(1, max_attempts)
        self.external_inputs = dict(external_inputs or {})
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    # -- public API --------------------------------------------------------

    def run(
        self,
        stages: Sequence[Stage],
        *,
        cancellation: CancellationToken | None = None,
        resume: bool = True,
    ) -> RunManifest:
        """Execute ``stages`` in order and return the final manifest.

        Stops at the first stage that rejects, fails, or is cancelled. The
        manifest is written after every stage, so an interrupted run leaves the
        last completed stage recorded and resumable.
        """
        self._reject_unknown_parameters(stages)
        token = cancellation or CancellationToken()
        self.store.initialise()
        manifest = self._load_or_create_manifest(resume=resume)

        published: dict[str, StageResult] = {}
        with log_context(run_id=self.run_id):
            for stage in stages:
                result, reused = self._execute(stage, manifest, published, token, resume=resume)
                if not reused:
                    # A reused result is already in the manifest. Appending it
                    # again would inflate the attempt count and make an
                    # untouched resume look like fresh work.
                    manifest = manifest.with_stage(result)
                    manifest.write(self.store.manifest_path)
                if not result.outcome.is_success:
                    break
                published[stage.name] = result
        return manifest

    # -- internals ---------------------------------------------------------

    def _reject_unknown_parameters(self, stages: Sequence[Stage]) -> None:
        declared = {key for stage in stages for key in stage.parameter_keys}
        unknown = sorted(set(self.parameters) - declared)
        if unknown:
            raise StageFailed(
                FailureCode.VALIDATION_UNKNOWN_PARAMETER,
                f"parameter set contains field(s) no stage declares: {unknown}. Unknown "
                "parameters are rejected rather than ignored, because an ignored parameter "
                "silently changes nothing while appearing to change something.",
                {"unknown_parameters": unknown, "declared_parameters": sorted(declared)},
            )
        missing = sorted(declared - set(self.parameters))
        if missing:
            raise StageFailed(
                FailureCode.VALIDATION_UNKNOWN_PARAMETER,
                f"parameter set is missing declared field(s): {missing}. Every parameter a "
                "stage reads must be resolved and recorded; there are no hidden defaults.",
                {"missing_parameters": missing},
            )

    def _load_or_create_manifest(self, *, resume: bool) -> RunManifest:
        path = self.store.manifest_path
        if resume and path.is_file():
            return RunManifest.read(path)
        now = self._clock()
        return RunManifest(
            run_id=self.run_id,
            created_utc=now,
            updated_utc=now,
            parameters=self.parameters,
            inputs=self.external_inputs,
            seed=self.seed,
            environment=capture_environment(),
        )

    def _input_digests(self, stage: Stage, published: Mapping[str, StageResult]) -> dict[str, str]:
        """Digest every input this stage depends on.

        Upstream outputs enter by digest, which is what makes downstream
        invalidation automatic.
        """
        digests = dict(self.external_inputs)
        for dependency in stage.depends_on:
            upstream = published.get(dependency)
            if upstream is None:
                raise StageFailed(
                    FailureCode.INTERNAL_UNEXPECTED_ERROR,
                    f"stage {stage.name!r} depends on {dependency!r}, which has not produced "
                    "a successful result in this run",
                    {"stage": stage.name, "dependency": dependency},
                )
            digests[dependency] = digest_many(sorted(upstream.output_digests.values()))
        return digests

    def _stage_seed(self, stage: Stage) -> int:
        """Derive a stable per-stage seed from the run seed and stage identity."""
        material = digest_json({"seed": self.seed, "stage": stage.name, "version": stage.version})
        return int(material[:16], 16)

    def _reusable(
        self, stage: Stage, manifest: RunManifest, fingerprint: str
    ) -> StageResult | None:
        """Return a prior result that may be reused, or ``None``.

        Every condition in plan section 6.5 is checked: outcome, fingerprint,
        publication state, and the byte-level integrity of each output. An
        artefact that has been edited or deleted since the run fails
        verification and forces a re-run.
        """
        prior = manifest.stage(stage.name)
        if prior is None or not prior.outcome.is_reusable_on_resume:
            return None
        if prior.fingerprint != fingerprint:
            return None
        for artifact in prior.outputs:
            if artifact.publication_state is not PublicationState.PUBLISHED:
                return None
            try:
                self.store.verify(artifact)
            except ArtifactVerificationError:
                _LOGGER.warning(
                    "stage output failed verification; re-running",
                    extra={"stage": stage.name, "artifact": artifact.relative_path},
                )
                return None
        return prior

    def _next_attempt(self, manifest: RunManifest, stage_name: str) -> int:
        return 1 + sum(1 for result in manifest.stages if result.stage_name == stage_name)

    def _execute(
        self,
        stage: Stage,
        manifest: RunManifest,
        published: Mapping[str, StageResult],
        token: CancellationToken,
        *,
        resume: bool,
    ) -> tuple[StageResult, bool]:
        """Return the stage's result and whether it was reused rather than run."""
        input_digests = self._input_digests(stage, published)
        parameter_subset = {key: self.parameters[key] for key in stage.parameter_keys}
        fingerprint = stage_fingerprint(
            stage_name=stage.name,
            stage_version=stage.version,
            algorithm=stage.algorithm,
            algorithm_version=stage.algorithm_version,
            input_digests=input_digests,
            parameter_subset=parameter_subset,
        )

        if resume:
            reusable = self._reusable(stage, manifest, fingerprint)
            if reusable is not None:
                _LOGGER.info("reusing verified stage result", extra={"stage": stage.name})
                return reusable, True

        base_attempt = self._next_attempt(manifest, stage.name)
        last: StageResult | None = None
        for offset in range(self.max_attempts):
            attempt = base_attempt + offset
            last = self._attempt(
                stage,
                attempt=attempt,
                input_digests=input_digests,
                parameter_subset=parameter_subset,
                token=token,
                fingerprint=fingerprint,
            )
            if last.outcome is not StageOutcome.FAILED:
                return last, False
            assert last.failure is not None  # noqa: S101 - guaranteed by StageResult validation
            if not is_retryable(last.failure.code):
                return last, False
            _LOGGER.warning(
                "retrying stage after a retryable failure",
                extra={
                    "stage": stage.name,
                    "attempt": attempt,
                    "failure_code": str(last.failure.code),
                },
            )
        assert last is not None  # noqa: S101 - max_attempts is at least one
        return last, False

    def _attempt(
        self,
        stage: Stage,
        *,
        attempt: int,
        input_digests: Mapping[str, str],
        parameter_subset: Mapping[str, Any],
        token: CancellationToken,
        fingerprint: str,
    ) -> StageResult:
        scratch = self.store.scratch_for(stage.name, attempt)
        context = StageContext(
            run_id=self.run_id,
            stage_name=stage.name,
            attempt=attempt,
            scratch=scratch,
            store=self.store,
            parameters=parameter_subset,
            seed=self._stage_seed(stage),
            cancellation=token,
            inputs={},
        )
        started = self._clock()
        monotonic_start = time.monotonic()
        cpu_start = time.process_time()

        outcome = StageOutcome.SUCCEEDED
        failure: StageFailure | None = None
        output = StageOutput()

        with log_context(stage=stage.name, attempt=attempt):
            try:
                token.check()
                output = stage.run(context)
                outcome = (
                    StageOutcome.SUCCEEDED_WITH_WARNINGS
                    if output.warnings
                    else StageOutcome.SUCCEEDED
                )
            except RunCancelled:
                outcome = StageOutcome.CANCELLED
                failure = StageFailure(
                    code=FailureCode.INTERNAL_CANCELLED,
                    message=f"stage {stage.name!r} was cancelled at a checkpoint",
                    context={"stage": stage.name, "attempt": attempt},
                )
            except StageRejected as rejection:
                outcome = StageOutcome.REJECTED
                failure = StageFailure(
                    code=rejection.code, message=str(rejection), context=rejection.context
                )
            except StageFailed as error:
                outcome = StageOutcome.FAILED
                failure = StageFailure(code=error.code, message=str(error), context=error.context)
            except Exception as error:
                # Every escape becomes a stable code, so no interface ever has to
                # render a bare traceback as if it were a scientific outcome.
                outcome = StageOutcome.FAILED
                failure = StageFailure(
                    code=FailureCode.INTERNAL_UNEXPECTED_ERROR,
                    message=f"{type(error).__name__}: {error}",
                    context={"stage": stage.name, "attempt": attempt},
                )
                _LOGGER.exception("unhandled error in stage", extra={"stage": stage.name})

        # Whatever the outcome, this attempt's scratch is finished with:
        # published artefacts have already been moved out of it, and anything
        # still in it was never published and is orphaned by definition.
        self.store.abandon(stage.name, attempt)

        ended = self._clock()
        result = StageResult(
            stage_name=stage.name,
            stage_version=stage.version,
            algorithm=stage.algorithm,
            algorithm_version=stage.algorithm_version,
            attempt=attempt,
            outcome=outcome,
            warnings=output.warnings,
            failure=failure,
            input_digests=dict(input_digests),
            parameter_subset=dict(parameter_subset),
            outputs=output.outputs if outcome.is_success else (),
            metrics=dict(output.metrics) if outcome.is_success else {},
            validity_mask_summary=dict(output.validity_mask_summary) if outcome.is_success else {},
            seed=context.seed,
            started_utc=started,
            ended_utc=ended,
            resources=ResourceUsage(
                wall_time_s=time.monotonic() - monotonic_start,
                cpu_time_s=time.process_time() - cpu_start,
            ),
            environment=capture_environment(),
            publication_state=PublicationState.PUBLISHED
            if outcome.is_success
            else PublicationState.ORPHANED,
            commit_id=fingerprint if outcome.is_success else None,
        )
        if result.fingerprint != fingerprint:
            # The runner decides reuse from a fingerprint computed before the
            # stage ran; the result recomputes it from what was recorded. If
            # those disagree, resume would silently reuse the wrong result.
            raise StageFailed(
                FailureCode.INTERNAL_UNEXPECTED_ERROR,
                f"fingerprint drift in stage {stage.name!r}: the runner planned "
                f"{fingerprint} but the recorded result yields {result.fingerprint}",
                {"stage": stage.name},
            )
        return result
