"""SELENE-XR scientific core.

This package holds the entire scientific implementation: ingestion, geometry,
reference preparation, preprocessing, feature channels, matching, verification
and selection, sub-pixel refinement, sensor adjustment, metrics, product
writing, and the local stage runner.

Architectural rules (implementation plan section 5.1, ADR-005):

* No dependency on HTTP, ORM, queues, Redis, object-store SDKs, or UI code.
* The CLI and the REST service both call these functions. Neither may contain a
  second scientific implementation.
* Original input bytes and geometry are immutable. Corrected geometry and
  registered rasters are named derived variants.
* Every raster-producing or raster-consuming stage is tiled and declares its
  memory, scratch, validity, and merge behaviour through a shared ``TileSpec``.

Only the names in ``__all__`` are a stable cross-package API. Service and
worker packages import this facade instead of implementation modules; the
import-linter contract in ADR-0005 enforces that separation.
"""

from selene_core.models import (
    LoadedModel,
    LocalModelRegistry,
    ModelArtifact,
    ModelRegistryError,
    load_local_model,
)
from selene_core.pipeline import (
    ArtifactRef,
    ArtifactStore,
    CancellationToken,
    EnvironmentFingerprint,
    FailureCategory,
    FailureCode,
    LocalRegistrationConfig,
    NoOpBehaviour,
    NoOpStage,
    PipelineDisposition,
    PipelineOrigin,
    PipelineProvenance,
    PipelineResult,
    PublicationState,
    ResolvedPipelineParameters,
    RunManifest,
    StageFailure,
    StageOutcome,
    StageResult,
    StageRunner,
    capture_environment,
    run_local_registration,
)
from selene_core.schema_validation import build_validator, validate_instance
from selene_core.types import (
    Covariance2D,
    CovarianceFrame,
    MapCoordinate,
    ReferencePixel,
    SourcePixel,
    TileSpec,
)

__all__ = [
    "ArtifactRef",
    "ArtifactStore",
    "CancellationToken",
    "Covariance2D",
    "CovarianceFrame",
    "EnvironmentFingerprint",
    "FailureCategory",
    "FailureCode",
    "LoadedModel",
    "LocalModelRegistry",
    "LocalRegistrationConfig",
    "MapCoordinate",
    "ModelArtifact",
    "ModelRegistryError",
    "NoOpBehaviour",
    "NoOpStage",
    "PipelineDisposition",
    "PipelineOrigin",
    "PipelineProvenance",
    "PipelineResult",
    "PublicationState",
    "ReferencePixel",
    "ResolvedPipelineParameters",
    "RunManifest",
    "SourcePixel",
    "StageFailure",
    "StageOutcome",
    "StageResult",
    "StageRunner",
    "TileSpec",
    "build_validator",
    "capture_environment",
    "load_local_model",
    "run_local_registration",
    "validate_instance",
]

__version__ = "0.0.0"
