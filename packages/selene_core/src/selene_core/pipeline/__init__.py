"""Local stage runner and immutable stage results (WP-01).

Responsibilities:

* The stage result protocol of plan section 6.5: input manifest hashes, the
  exact parameter subset read, typed outputs with checksums and CRS, warnings,
  a stable failure code with retryability and remediation hint, stage metrics,
  algorithm and dependency versions, deterministic seed, instrumentation, code
  revision, environment fingerprint, and publication state.
* Deterministic seed plumbing, cancellation checkpoints, and stable retry rules
  keyed by failure code. Deterministic validation and scientific gate failures
  do not retry automatically.
* Resume that reuses a completed stage only when its recorded input hashes,
  parameter subset, code and algorithm version, output checksums, and schemas
  all match, and that invalidates every downstream result when an upstream
  input changes (ADR-013).
* Temporary write, flush, checksum, schema validation, atomic publish, and
  orphan cleanup. A stale partial output is never discoverable as a successful
  artefact.
* Structured logging carrying run, product, route, stage, algorithm, and trace
  identifiers, and never imagery, tokens, credentials, or signed URLs.
"""

from selene_core.pipeline.artifacts import (
    ArtifactStore,
    ArtifactVerificationError,
    atomic_write,
)
from selene_core.pipeline.failures import (
    FailureCategory,
    FailureCode,
    FailureDefinition,
    definition_for,
    is_retryable,
)
from selene_core.pipeline.hashing import (
    canonical_json,
    digest_file,
    digest_json,
    digest_many,
    is_sha256,
)
from selene_core.pipeline.local_registration import (
    AdjustmentEvidence,
    ArrayArtifactHandles,
    CoverageEvidence,
    LocalRegistrationConfig,
    PipelineDisposition,
    PipelineOrigin,
    PipelineProvenance,
    PipelineResult,
    PipelineStageEvidence,
    RefinementEvidence,
    ResolvedPipelineParameters,
    run_local_registration,
)
from selene_core.pipeline.logging import configure_logging, get_logger, log_context
from selene_core.pipeline.manifest import RunManifest, capture_environment
from selene_core.pipeline.noop import NoOpBehaviour, NoOpStage
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
from selene_core.pipeline.runner import (
    CancellationToken,
    RunCancelled,
    Stage,
    StageContext,
    StageFailed,
    StageOutput,
    StageRejected,
    StageRunner,
)

__all__ = [
    "AdjustmentEvidence",
    "ArrayArtifactHandles",
    "ArtifactRef",
    "ArtifactStore",
    "ArtifactVerificationError",
    "CancellationToken",
    "CoverageEvidence",
    "EnvironmentFingerprint",
    "FailureCategory",
    "FailureCode",
    "FailureDefinition",
    "LocalRegistrationConfig",
    "NoOpBehaviour",
    "NoOpStage",
    "PipelineDisposition",
    "PipelineOrigin",
    "PipelineProvenance",
    "PipelineResult",
    "PipelineStageEvidence",
    "PublicationState",
    "RefinementEvidence",
    "ResolvedPipelineParameters",
    "ResourceUsage",
    "RunCancelled",
    "RunManifest",
    "Stage",
    "StageContext",
    "StageFailed",
    "StageFailure",
    "StageOutcome",
    "StageOutput",
    "StageRejected",
    "StageResult",
    "StageRunner",
    "StageWarning",
    "atomic_write",
    "canonical_json",
    "capture_environment",
    "configure_logging",
    "definition_for",
    "digest_file",
    "digest_json",
    "digest_many",
    "get_logger",
    "is_retryable",
    "is_sha256",
    "log_context",
    "run_local_registration",
    "stage_fingerprint",
]
