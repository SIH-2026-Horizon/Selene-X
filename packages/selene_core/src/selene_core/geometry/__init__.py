"""Sensor models, SPICE, projections, and typed coordinate handling (WP-03).

Responsibilities:

* Contracts for line-scan sensor model instantiation and per-line/sampled pose
  providers. Mission camera-model implementation and real-scene validation are
  explicitly unavailable until adapters and evidence are supplied.
* Footprints by ray/terrain intersection over a boundary and interior grid;
  external validation is accepted only with independent evidence metadata.
* Explicit lunar body-fixed frame and per-scene projection selection, with the
  full CRS serialised into every raster and geometry artefact (ADR-002).
* Local GSD, view, and emission geometry computed across the scene rather than
  from a single scale constant.
* Forward-projected grids producing a coarse displacement, local-scale, and
  orientation prior with measured uncertainty.
* Named conversions between ISIS, GDAL, CSM, and internal pixel conventions
  (ADR-001). No inline half-pixel corrections.
"""

from selene_core.geometry.contracts import (
    Footprint,
    FootprintValidationReport,
    GeometryValidation,
    GroundPoint,
    LocalGeometry,
    SensorGeometry,
    SensorModel,
    ValidationEvidence,
    WarpPrior,
    estimate_local_geometry,
    estimate_warp_prior,
    ground_distance_m,
    normalize_longitude_deg,
    sample_footprint,
    sample_local_geometry,
    unwrap_longitudes_deg,
    validate_footprint,
    validated_footprint,
)
from selene_core.geometry.crs import LUNAR_MEAN_RADIUS_M, LunarCrs, Projection, select_lunar_crs
from selene_core.geometry.preflight import (
    PreflightPolicy,
    PreflightReport,
    RouteAdmissibility,
    preflight_route,
)
from selene_core.geometry.provider import (
    KernelFurnishingEvidence,
    PoseAvailability,
    PoseSamplingReport,
    SensorPose,
    SensorPoseProvider,
    SpicePoseProvider,
    furnish_spice_kernels,
    sample_provider_geometry,
)
from selene_core.geometry.pyramid import (
    EligibilityMasks,
    PairedPyramidLevel,
    PyramidLevel,
    build_common_resolution_pyramid,
    build_paired_common_resolution_pyramid,
    combine_eligibility_masks,
    derive_eligibility_masks,
    gaussian_blur,
)

__all__ = [
    "LUNAR_MEAN_RADIUS_M",
    "EligibilityMasks",
    "Footprint",
    "FootprintValidationReport",
    "GeometryValidation",
    "GroundPoint",
    "KernelFurnishingEvidence",
    "LocalGeometry",
    "LunarCrs",
    "PairedPyramidLevel",
    "PoseAvailability",
    "PoseSamplingReport",
    "PreflightPolicy",
    "PreflightReport",
    "Projection",
    "PyramidLevel",
    "RouteAdmissibility",
    "SensorGeometry",
    "SensorModel",
    "SensorPose",
    "SensorPoseProvider",
    "SpicePoseProvider",
    "ValidationEvidence",
    "WarpPrior",
    "build_common_resolution_pyramid",
    "build_paired_common_resolution_pyramid",
    "combine_eligibility_masks",
    "derive_eligibility_masks",
    "estimate_local_geometry",
    "estimate_warp_prior",
    "furnish_spice_kernels",
    "gaussian_blur",
    "ground_distance_m",
    "normalize_longitude_deg",
    "preflight_route",
    "sample_footprint",
    "sample_local_geometry",
    "sample_provider_geometry",
    "select_lunar_crs",
    "unwrap_longitudes_deg",
    "validate_footprint",
    "validated_footprint",
]
