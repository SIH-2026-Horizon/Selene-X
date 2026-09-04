"""The immutable stage result protocol (plan section 6.5, ADR-0013).

Every scientific stage returns one of these, whether it succeeded, warned,
refused on scientific grounds, failed, or was cancelled. A single contract is
what lets the CLI, the service, and the benchmark runner report the same thing
without any of them inventing a state.

Two distinctions carry weight here:

* **Rejection is not failure.** ``REJECTED`` means the stage ran correctly and
  concluded that the evidence does not support a result. ``FAILED`` means the
  stage could not run. Conflating them turns a scientific refusal into a bug
  report, and turns a bug into an apparent scientific finding.
* **Published is not written.** An artefact is ``SCRATCH`` until it has been
  checksummed, schema-validated, and atomically moved into place. A stale
  partial output is never discoverable as a successful artefact.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from selene_core.contracts import Contract
from selene_core.pipeline.failures import FailureCategory, FailureCode, definition_for
from selene_core.pipeline.hashing import digest_json, is_sha256

_Contract = Contract
"""Local private alias, kept so every base-class reference below needs no edit."""

__all__ = [
    "ArtifactRef",
    "EnvironmentFingerprint",
    "PublicationState",
    "ResourceUsage",
    "StageFailure",
    "StageOutcome",
    "StageResult",
    "StageWarning",
    "stage_fingerprint",
]


def stage_fingerprint(
    *,
    stage_name: str,
    stage_version: str,
    algorithm: str | None,
    algorithm_version: str | None,
    input_digests: Mapping[str, str],
    parameter_subset: Mapping[str, Any],
) -> str:
    """The identity a resume compares against.

    Covers the stage and algorithm versions, every input digest, and the exact
    parameter subset read. It deliberately excludes ``code_revision``,
    wall-clock times, and attempt number: a commit that does not change a
    stage's behaviour should not invalidate its cached result, and a stage whose
    behaviour does change is required to bump ``stage_version``. ADR-0013
    records that trade-off.

    Defined as a free function, not only as a property of
    :class:`StageResult`, because the runner must compute it *before* a stage
    runs in order to decide whether to run it at all. One formula in one place
    is what keeps the planned and the recorded fingerprint from disagreeing.
    """
    return digest_json(
        {
            "stage_name": stage_name,
            "stage_version": stage_version,
            "algorithm": algorithm,
            "algorithm_version": algorithm_version,
            "input_digests": dict(input_digests),
            "parameter_subset": dict(parameter_subset),
        }
    )


class PublicationState(StrEnum):
    """Where an artefact sits in the write-validate-publish sequence."""

    SCRATCH = "scratch"
    """Written to a temporary location. Not discoverable as a result."""

    PUBLISHED = "published"
    """Checksummed, validated, and atomically moved into place."""

    ORPHANED = "orphaned"
    """Abandoned by a cancellation or failure. Eligible for cleanup, never for
    reuse."""


class StageOutcome(StrEnum):
    """How a stage ended."""

    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_WARNINGS = "succeeded_with_warnings"

    REJECTED = "rejected"
    """The stage ran correctly and refused on scientific grounds. This is a
    result, not a malfunction."""

    FAILED = "failed"
    """The stage could not run to completion."""

    CANCELLED = "cancelled"
    """Cooperative cancellation. Completed prior stages remain reusable."""

    @property
    def is_success(self) -> bool:
        """Whether downstream stages may consume this result."""
        return self in {StageOutcome.SUCCEEDED, StageOutcome.SUCCEEDED_WITH_WARNINGS}

    @property
    def is_reusable_on_resume(self) -> bool:
        """Whether a resume may skip re-running this stage.

        Only a successful stage is reusable. A rejection is cheap to recompute
        and may change once its inputs are corrected, so it is not cached.
        """
        return self.is_success


class ArtifactRef(_Contract):
    """A reference to one output file, with everything needed to verify it."""

    kind: str = Field(description="Role of this artefact within the stage, for example 'matches'.")
    relative_path: str = Field(
        description="Path relative to the run root. Never absolute, so a run directory can be "
        "relocated or archived without rewriting its manifest."
    )
    media_type: str = Field(description="IANA media type, for example 'image/tiff'.")
    sha256: str = Field(description="SHA-256 of the artefact's bytes.")
    size_bytes: int = Field(ge=0, description="Artefact size in bytes.")
    publication_state: PublicationState = PublicationState.SCRATCH

    schema_id: str | None = Field(
        default=None, description="Identifier of the JSON Schema this artefact validates against."
    )
    crs_wkt: str | None = Field(
        default=None, description="Full CRS for a georeferenced artefact. Required for rasters."
    )
    shape: tuple[int, ...] | None = Field(
        default=None, description="Raster shape, band-major, for a raster artefact."
    )
    nodata: float | None = Field(
        default=None,
        description="Nodata value in the artefact's own pixel units, which is why this field "
        "carries no unit suffix.",
    )
    units: str | None = Field(default=None, description="Physical units of the pixel values.")

    @model_validator(mode="after")
    def _check(self) -> ArtifactRef:
        if not is_sha256(self.sha256):
            raise ValueError(
                f"ArtifactRef.sha256 must be a SHA-256 hex digest, got {self.sha256!r}"
            )
        if self.relative_path.startswith("/") or ".." in self.relative_path.split("/"):
            raise ValueError(
                f"ArtifactRef.relative_path must stay inside the run root, got "
                f"{self.relative_path!r}"
            )
        return self


class StageWarning(_Contract):
    """A non-fatal concern that a reviewer must be able to see."""

    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class StageFailure(_Contract):
    """Why a stage failed or refused, and what to do about it.

    ``category``, ``retryable``, and ``remediation`` are derived from the code
    rather than supplied, so that the same code cannot be reported as retryable
    in one stage and not in another.
    """

    code: FailureCode
    message: str
    context: dict[str, Any] = Field(default_factory=dict)

    @property
    def category(self) -> FailureCategory:
        """The stage family this failure belongs to."""
        return definition_for(self.code).category

    @property
    def retryable(self) -> bool:
        """Whether an automatic retry can plausibly succeed."""
        return definition_for(self.code).retryable

    @property
    def remediation(self) -> str:
        """What the user should do next."""
        return definition_for(self.code).remediation

    @property
    def summary(self) -> str:
        """The stable description of this failure code."""
        return definition_for(self.code).summary


class ResourceUsage(_Contract):
    """Measured cost of a stage.

    Recorded so that resource behaviour is characterised rather than claimed
    (R-013). Every field is optional because a measurement that was not taken is
    ``None`` with the rest of the record intact, never zero.
    """

    wall_time_s: float | None = Field(default=None, ge=0.0)
    cpu_time_s: float | None = Field(default=None, ge=0.0)
    peak_memory_bytes: int | None = Field(default=None, ge=0)
    read_bytes: int | None = Field(default=None, ge=0)
    written_bytes: int | None = Field(default=None, ge=0)
    device: str | None = Field(default=None, description="Accelerator used, if any.")


class EnvironmentFingerprint(_Contract):
    """What the stage ran on.

    Reproducibility is reported at the tolerance actually measured, and that
    report is meaningless without knowing what changed between two runs.
    """

    python_version: str
    platform: str
    code_revision: str | None = Field(
        default=None, description="Repository revision, when the run is from a checkout."
    )
    dependency_versions: dict[str, str] = Field(default_factory=dict)


class StageResult(_Contract):
    """The immutable record one stage produces."""

    # Identity
    stage_name: str
    stage_version: str = Field(
        description="Bumped whenever the stage's behaviour changes. Resume compares this, not "
        "the source bytes, so a behavioural change that does not bump it will be wrongly "
        "reused. ADR-0013 records that trade-off."
    )
    algorithm: str | None = None
    algorithm_version: str | None = None
    attempt: int = Field(default=1, ge=1)

    # Outcome
    outcome: StageOutcome
    warnings: tuple[StageWarning, ...] = ()
    failure: StageFailure | None = None

    # Provenance
    input_digests: dict[str, str] = Field(
        default_factory=dict,
        description="Digest of every input this stage read, keyed by logical name.",
    )
    parameter_subset: dict[str, Any] = Field(
        default_factory=dict,
        description="Exactly the parameters this stage read, not the whole parameter set. "
        "Recording the whole set would invalidate resume whenever an unrelated parameter "
        "changed.",
    )

    # Outputs and observations
    outputs: tuple[ArtifactRef, ...] = ()
    metrics: dict[str, Any] = Field(default_factory=dict)
    validity_mask_summary: dict[str, Any] = Field(default_factory=dict)

    # Execution
    seed: int | None = None
    started_utc: datetime | None = None
    ended_utc: datetime | None = None
    resources: ResourceUsage = Field(default_factory=ResourceUsage)
    environment: EnvironmentFingerprint | None = None

    # Publication
    publication_state: PublicationState = PublicationState.SCRATCH
    commit_id: str | None = Field(
        default=None, description="Identifier of the atomic publication that made this durable."
    )

    @model_validator(mode="after")
    def _check(self) -> StageResult:
        if self.outcome.is_success and self.failure is not None:
            raise ValueError(
                f"a {self.outcome} stage must not carry a failure; outcome and failure "
                "disagree about what happened"
            )
        if not self.outcome.is_success and self.failure is None:
            raise ValueError(
                f"a {self.outcome} stage must carry a failure with a stable code, so that "
                "retry policy and remediation are determined rather than guessed"
            )
        if self.outcome is StageOutcome.SUCCEEDED and self.warnings:
            raise ValueError(
                "a stage with warnings must report SUCCEEDED_WITH_WARNINGS, so that a warned "
                "result is not filtered away as an unqualified success"
            )
        if self.outcome.is_success and any(
            artifact.publication_state is not PublicationState.PUBLISHED
            for artifact in self.outputs
        ):
            raise ValueError(
                "a successful stage cannot report an unpublished output; publish artefacts "
                "before recording success"
            )
        for name, digest in self.input_digests.items():
            if not is_sha256(digest):
                raise ValueError(f"input digest for {name!r} is not a SHA-256 hex digest")
        if (
            self.started_utc is not None
            and self.ended_utc is not None
            and self.ended_utc < self.started_utc
        ):
            raise ValueError("StageResult.ended_utc precedes started_utc")
        return self

    @property
    def fingerprint(self) -> str:
        """This result's resume identity. See :func:`stage_fingerprint`."""
        return stage_fingerprint(
            stage_name=self.stage_name,
            stage_version=self.stage_version,
            algorithm=self.algorithm,
            algorithm_version=self.algorithm_version,
            input_digests=self.input_digests,
            parameter_subset=self.parameter_subset,
        )

    @property
    def output_digests(self) -> dict[str, str]:
        """Published output digests, keyed by relative path."""
        return {artifact.relative_path: artifact.sha256 for artifact in self.outputs}

    def output(self, kind: str) -> ArtifactRef:
        """Return the single output of the given ``kind``.

        Raises:
            KeyError: If no output, or more than one, has that kind. Ambiguity
                here would mean a downstream stage silently consuming the wrong
                artefact.
        """
        matches = [artifact for artifact in self.outputs if artifact.kind == kind]
        if len(matches) != 1:
            raise KeyError(
                f"stage {self.stage_name!r} has {len(matches)} outputs of kind {kind!r}, "
                "expected exactly one"
            )
        return matches[0]
