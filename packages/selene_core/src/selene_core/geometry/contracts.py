"""Dependency-light geometry contracts used before external sensor tooling is available.

These types deliberately separate *computed* geometry from an assertion that it
was validated against SPICE/ISIS.  A caller must carry the ``validation`` value
forward into qualification; synthetic transforms are useful for tests but are
never evidence for a real lunar scene.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from selene_core.types import SourcePixel

__all__ = [
    "MIN_MEASURABLE_WARP_UNCERTAINTY_PX",
    "Footprint",
    "FootprintValidationReport",
    "GeometryValidation",
    "GroundPoint",
    "LocalGeometry",
    "SensorGeometry",
    "SensorModel",
    "ValidationEvidence",
    "WarpPrior",
    "estimate_local_geometry",
    "estimate_warp_prior",
    "ground_distance_m",
    "normalize_longitude_deg",
    "sample_footprint",
    "sample_local_geometry",
    "unwrap_longitudes_deg",
    "validate_footprint",
    "validated_footprint",
]

MIN_MEASURABLE_WARP_UNCERTAINTY_PX = 1e-6
"""Smallest declared measurable prior uncertainty; zero is never evidence."""


class GeometryValidation(StrEnum):
    """How far a geometry result has been checked against authoritative data."""

    UNAVAILABLE = "unavailable"
    SYNTHETIC = "synthetic"
    INVENTORY_ONLY = "inventory_only"
    EXTERNALLY_VALIDATED = "externally_validated"
    INVALID = "invalid"


_FOOTPRINT_VALIDATION_ISSUER = object()


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    """Independent evidence needed before a result can be externally validated."""

    independent_reference_id: str
    independent_reference_sha256: str
    validation_process_id: str
    horizontal_covariance_m2: float

    def __post_init__(self) -> None:
        digest = self.independent_reference_sha256.lower()
        if not self.independent_reference_id.strip() or not self.validation_process_id.strip():
            raise ValueError("independent reference and process identifiers are required")
        if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
            raise ValueError("independent reference SHA-256 must be hexadecimal")
        if not math.isfinite(self.horizontal_covariance_m2) or self.horizontal_covariance_m2 <= 0:
            raise ValueError("independent validation covariance must be finite and positive")


def normalize_longitude_deg(longitude_deg: float) -> float:
    """Return longitude in the half-open east-positive interval ``[-180, 180)``."""
    if not math.isfinite(longitude_deg):
        raise ValueError("longitude_deg must be finite")
    normalized = (longitude_deg + 180.0) % 360.0 - 180.0
    return 0.0 if normalized == -0.0 else normalized


@dataclass(frozen=True, slots=True)
class GroundPoint:
    """Planetocentric lunar location, east-positive longitude in degrees."""

    latitude_deg: float
    longitude_deg: float
    height_m: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.latitude_deg) or not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("latitude_deg must be finite and in [-90, 90]")
        if not math.isfinite(self.longitude_deg):
            raise ValueError("longitude_deg must be finite")
        if not math.isfinite(self.height_m):
            raise ValueError("height_m must be finite")
        object.__setattr__(self, "longitude_deg", normalize_longitude_deg(self.longitude_deg))


class SensorModel(Protocol):
    """Small contract shared by real adapters and deterministic test doubles."""

    def ground_at(self, pixel: SourcePixel) -> GroundPoint | None:
        """Intersect a pixel ray with terrain, or return ``None`` when unavailable."""


class ReferenceProjector(Protocol):
    """A reference sensor/map projection evaluated at lunar ground points."""

    def pixel_at(self, ground: GroundPoint) -> tuple[float, float] | None:
        """Return internal (line, sample) or ``None`` when outside coverage."""


@dataclass(frozen=True, slots=True)
class SensorGeometry:
    """Sensor/pose availability, without manufacturing an unavailable pose."""

    instrument: str
    model_identifier: str
    validation: GeometryValidation
    pose_source: str | None = None
    kernel_set_id: str | None = None
    limitations: tuple[str, ...] = ()
    validation_evidence: ValidationEvidence | None = None

    def __post_init__(self) -> None:
        if not self.instrument.strip() or not self.model_identifier.strip():
            raise ValueError("instrument and model_identifier must be non-empty")
        if self.validation is GeometryValidation.EXTERNALLY_VALIDATED and (
            not self.pose_source or self.validation_evidence is None
        ):
            raise ValueError("external geometry requires pose source and independent evidence")


def unwrap_longitudes_deg(
    longitudes_deg: Sequence[float], *, anchor_deg: float | None = None
) -> tuple[float, ...]:
    """Unwrap longitudes around an anchor, preserving polygons across ±180°.

    The returned values are intentionally not normalized; their continuity is
    what makes footprint bounds and overlap calculations safe at the wrap.
    """
    if not longitudes_deg:
        return ()
    if any(not math.isfinite(value) for value in longitudes_deg):
        raise ValueError("longitudes_deg must all be finite")
    if anchor_deg is None:
        sin_sum = sum(math.sin(math.radians(value)) for value in longitudes_deg)
        cos_sum = sum(math.cos(math.radians(value)) for value in longitudes_deg)
        anchor_deg = (
            math.degrees(math.atan2(sin_sum, cos_sum)) if sin_sum or cos_sum else longitudes_deg[0]
        )
    output: list[float] = []
    for value in longitudes_deg:
        wrapped = normalize_longitude_deg(value)
        output.append(anchor_deg + ((wrapped - anchor_deg + 180.0) % 360.0 - 180.0))
    return tuple(output)


@dataclass(frozen=True, slots=True)
class Footprint:
    """Boundary plus interior ray/terrain samples for a scene footprint."""

    boundary: tuple[GroundPoint, ...]
    interior: tuple[GroundPoint, ...]
    validation: GeometryValidation
    longitude_anchor_deg: float
    is_polar: bool
    limitations: tuple[str, ...] = ()
    validation_evidence: ValidationEvidence | None = None
    validation_artifact: FootprintValidationReport | None = None

    def __post_init__(self) -> None:
        if len(self.boundary) < 3:
            raise ValueError("footprint requires at least three boundary points")
        if not math.isfinite(self.longitude_anchor_deg):
            raise ValueError("longitude_anchor_deg must be finite")
        if self.validation is GeometryValidation.EXTERNALLY_VALIDATED and (
            self.validation_evidence is None
            or self.validation_artifact is None
            or self.validation_artifact.validation is not GeometryValidation.EXTERNALLY_VALIDATED
            or self.validation_artifact.candidate_footprint_sha256
            != _footprint_digest(self.boundary)
            or self.validation_artifact.issuer is not _FOOTPRINT_VALIDATION_ISSUER
        ):
            raise ValueError("external footprint requires a bound independent validation artifact")

    @property
    def unwrapped_boundary_longitudes_deg(self) -> tuple[float, ...]:
        return unwrap_longitudes_deg(
            tuple(point.longitude_deg for point in self.boundary),
            anchor_deg=self.longitude_anchor_deg,
        )

    @property
    def latitude_bounds_deg(self) -> tuple[float, float]:
        values = [point.latitude_deg for point in self.boundary + self.interior]
        return (min(values), max(values))

    @property
    def longitude_bounds_deg(self) -> tuple[float, float]:
        values = self.unwrapped_boundary_longitudes_deg
        return (min(values), max(values))


@dataclass(frozen=True, slots=True)
class FootprintValidationReport:
    """Comparison against independent published/control footprint evidence."""

    validation: GeometryValidation
    mean_boundary_disagreement_m: float | None
    maximum_boundary_disagreement_m: float | None
    tolerance_m: float
    message: str
    evidence: ValidationEvidence | None = None
    candidate_footprint_sha256: str | None = None
    independent_footprint_sha256: str | None = None
    issuer: object | None = None


def ground_distance_m(
    first: GroundPoint, second: GroundPoint, *, radius_m: float = 1_737_400.0
) -> float:
    """Great-circle surface distance; height is intentionally excluded for footprints."""
    if not math.isfinite(radius_m) or radius_m <= 0:
        raise ValueError("radius_m must be finite and positive")
    phi1, phi2 = math.radians(first.latitude_deg), math.radians(second.latitude_deg)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(second.longitude_deg - first.longitude_deg)
    haversine = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius_m * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def _footprint_digest(points: Sequence[GroundPoint]) -> str:
    payload = [[point.latitude_deg, point.longitude_deg, point.height_m] for point in points]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_footprint(
    sampled: Footprint,
    *,
    expected_boundary: Sequence[GroundPoint],
    tolerance_m: float,
    evidence: ValidationEvidence | None = None,
) -> FootprintValidationReport:
    """Compare a sampled boundary with independent footprint/control points.

    The expected points must be independently sourced and ordered to correspond
    to the sampled boundary.  Missing or mismatched evidence is reported as
    unavailable rather than approximated through nearest-neighbour matching.
    """
    if not math.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("tolerance_m must be finite and positive")
    if len(expected_boundary) != len(sampled.boundary):
        return FootprintValidationReport(
            GeometryValidation.UNAVAILABLE,
            None,
            None,
            tolerance_m,
            "independent boundary is missing or has a different sample count",
            evidence,
            _footprint_digest(sampled.boundary),
            _footprint_digest(expected_boundary),
            _FOOTPRINT_VALIDATION_ISSUER,
        )
    distances = tuple(
        ground_distance_m(actual, expected)
        for actual, expected in zip(sampled.boundary, expected_boundary, strict=True)
    )
    mean = sum(distances) / len(distances)
    maximum = max(distances)
    independent_digest = _footprint_digest(expected_boundary)
    evidence_binds_independent = (
        evidence is not None and evidence.independent_reference_sha256 == independent_digest
    )
    state = (
        GeometryValidation.EXTERNALLY_VALIDATED
        if maximum <= tolerance_m and evidence_binds_independent
        else GeometryValidation.INVALID
    )
    message = (
        "footprint agrees with independent boundary"
        if state is GeometryValidation.EXTERNALLY_VALIDATED
        else (
            "footprint disagreement exceeds tolerance or evidence does not bind "
            "independent boundary"
        )
    )
    return FootprintValidationReport(
        state,
        mean,
        maximum,
        tolerance_m,
        message,
        evidence,
        _footprint_digest(sampled.boundary),
        independent_digest,
        _FOOTPRINT_VALIDATION_ISSUER,
    )


def validated_footprint(sampled: Footprint, report: FootprintValidationReport) -> Footprint:
    """Attach a comparison-created artifact; sampling itself cannot claim validation."""
    if (
        report.validation is not GeometryValidation.EXTERNALLY_VALIDATED
        or report.evidence is None
        or report.candidate_footprint_sha256 != _footprint_digest(sampled.boundary)
        or report.independent_footprint_sha256 is None
        or report.issuer is not _FOOTPRINT_VALIDATION_ISSUER
        or report.maximum_boundary_disagreement_m is None
        or report.maximum_boundary_disagreement_m > report.tolerance_m
    ):
        raise ValueError("footprint validation artifact is not a successful bound comparison")
    return replace(
        sampled,
        validation=GeometryValidation.EXTERNALLY_VALIDATED,
        validation_evidence=report.evidence,
        validation_artifact=report,
    )


def _boundary_pixels(rows: int, columns: int, samples_per_edge: int) -> tuple[SourcePixel, ...]:
    if rows < 2 or columns < 2 or samples_per_edge < 2:
        raise ValueError("rows, columns, and samples_per_edge must each be at least 2")

    def span(stop: int) -> list[float]:
        return [index * (stop - 1) / (samples_per_edge - 1) for index in range(samples_per_edge)]

    xs = span(columns)
    ys = span(rows)
    pixels = [SourcePixel(0.0, x) for x in xs]
    pixels.extend(SourcePixel(y, float(columns - 1)) for y in ys[1:])
    pixels.extend(SourcePixel(float(rows - 1), x) for x in reversed(xs[:-1]))
    pixels.extend(SourcePixel(y, 0.0) for y in reversed(ys[1:-1]))
    return tuple(pixels)


def sample_footprint(
    model: SensorModel,
    *,
    image_shape: tuple[int, int],
    boundary_samples_per_edge: int = 9,
    interior_grid: tuple[int, int] = (3, 3),
    validation: GeometryValidation = GeometryValidation.SYNTHETIC,
    validation_evidence: ValidationEvidence | None = None,
) -> Footprint:
    """Sample a footprint with boundary and interior rays, failing closed on gaps."""
    if validation is GeometryValidation.EXTERNALLY_VALIDATED:
        raise ValueError(
            "sample_footprint cannot claim external validation; use validated_footprint"
        )
    rows, columns = image_shape
    boundary_pixels = _boundary_pixels(rows, columns, boundary_samples_per_edge)
    boundary = tuple(model.ground_at(pixel) for pixel in boundary_pixels)
    if any(point is None for point in boundary):
        raise ValueError("footprint boundary ray/terrain intersection is unavailable")
    interior_rows, interior_columns = interior_grid
    if interior_rows < 1 or interior_columns < 1:
        raise ValueError("interior_grid dimensions must be positive")
    interior: list[GroundPoint] = []
    for row in range(interior_rows):
        for column in range(interior_columns):
            pixel = SourcePixel(
                (row + 1) * (rows - 1) / (interior_rows + 1),
                (column + 1) * (columns - 1) / (interior_columns + 1),
            )
            point = model.ground_at(pixel)
            if point is None:
                raise ValueError("footprint interior ray/terrain intersection is unavailable")
            interior.append(point)
    boundary_points = tuple(point for point in boundary if point is not None)
    all_points = boundary_points + tuple(interior)
    longitudes = tuple(point.longitude_deg for point in all_points)
    unwrapped = unwrap_longitudes_deg(longitudes)
    anchor = sum(unwrapped) / len(unwrapped)
    polar = any(abs(point.latitude_deg) >= 85.0 for point in all_points)
    return Footprint(
        boundary_points,
        tuple(interior),
        validation,
        anchor,
        polar,
        validation_evidence=validation_evidence,
    )


@dataclass(frozen=True, slots=True)
class LocalGeometry:
    """Locally measured imaging geometry, with explicit uncertainty."""

    gsd_line_m: float
    gsd_sample_m: float
    view_zenith_deg: float | None
    emission_deg: float | None
    gsd_uncertainty_m: float
    geometry_uncertainty_deg: float | None
    validation: GeometryValidation
    validation_evidence: ValidationEvidence | None = None

    def __post_init__(self) -> None:
        for name in ("gsd_line_m", "gsd_sample_m", "gsd_uncertainty_m"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        for name in ("view_zenith_deg", "emission_deg", "geometry_uncertainty_deg"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0.0):
                raise ValueError(f"{name} must be None or a non-negative finite value")
        if (
            self.validation is GeometryValidation.EXTERNALLY_VALIDATED
            and self.validation_evidence is None
        ):
            raise ValueError("external local geometry requires independent evidence")
        if (
            self.view_zenith_deg is not None or self.emission_deg is not None
        ) and self.geometry_uncertainty_deg is None:
            raise ValueError("view/emission values require explicit geometry uncertainty")


def estimate_local_geometry(
    *,
    line_neighbor_m: tuple[float, float],
    sample_neighbor_m: tuple[float, float],
    validation: GeometryValidation = GeometryValidation.SYNTHETIC,
    view_zenith_deg: float | None = None,
    emission_deg: float | None = None,
    validation_evidence: ValidationEvidence | None = None,
) -> LocalGeometry:
    """Estimate local GSD from two ground displacement vectors in metres."""
    line_gsd = math.hypot(*line_neighbor_m)
    sample_gsd = math.hypot(*sample_neighbor_m)
    # A conservative quantization/projection proxy; it is not a pose solution.
    uncertainty = 0.5 * max(line_gsd, sample_gsd)
    return LocalGeometry(
        line_gsd,
        sample_gsd,
        view_zenith_deg,
        emission_deg,
        uncertainty,
        None,
        validation,
        validation_evidence,
    )


def _surface_normal(point: GroundPoint) -> tuple[float, float, float]:
    latitude = math.radians(point.latitude_deg)
    longitude = math.radians(point.longitude_deg)
    return (
        math.cos(latitude) * math.cos(longitude),
        math.cos(latitude) * math.sin(longitude),
        math.sin(latitude),
    )


def sample_local_geometry(
    model: SensorModel,
    *,
    pixel: SourcePixel,
    pose_position_m: tuple[float, float, float] | None = None,
    reference_pose_position_m: tuple[float, float, float] | None = None,
    pose_covariance_m2: float | None = None,
    pixel_step: float = 1.0,
    validation: GeometryValidation = GeometryValidation.SYNTHETIC,
) -> LocalGeometry:
    """Sample GSD and view/emission at a pixel using actual model evaluations."""
    if not math.isfinite(pixel_step) or pixel_step <= 0:
        raise ValueError("pixel_step must be finite and positive")
    centre = model.ground_at(pixel)
    line = model.ground_at(SourcePixel(pixel.line + pixel_step, pixel.sample))
    sample = model.ground_at(SourcePixel(pixel.line, pixel.sample + pixel_step))
    if centre is None or line is None or sample is None:
        raise ValueError("local GSD is unavailable because one or more ground samples failed")
    line_gsd = ground_distance_m(centre, line) / pixel_step
    sample_gsd = ground_distance_m(centre, sample) / pixel_step
    view_zenith: float | None = None
    emission: float | None = None
    geometry_uncertainty: float | None = None
    normal = _surface_normal(centre)
    radius = 1_737_400.0 + centre.height_m
    surface = tuple(radius * value for value in normal)
    if pose_position_m is not None:
        if len(pose_position_m) != 3 or not all(math.isfinite(value) for value in pose_position_m):
            raise ValueError("pose_position_m must have three finite coordinates")
        view = tuple(
            sensor - ground for sensor, ground in zip(pose_position_m, surface, strict=True)
        )
        length = math.sqrt(sum(value * value for value in view))
        if length <= 0:
            raise ValueError("sensor position cannot equal the sampled surface point")
        cosine = sum(
            component * vector / length for component, vector in zip(normal, view, strict=True)
        )
        view_zenith = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
        if (
            pose_covariance_m2 is None
            or not math.isfinite(pose_covariance_m2)
            or pose_covariance_m2 < 0
        ):
            raise ValueError("view geometry requires finite non-negative pose covariance")
        geometry_uncertainty = math.degrees(math.atan2(math.sqrt(pose_covariance_m2), length))
    if reference_pose_position_m is not None:
        if pose_covariance_m2 is None:
            raise ValueError("reference emission geometry requires pose covariance")
        view = tuple(
            sensor - ground
            for sensor, ground in zip(reference_pose_position_m, surface, strict=True)
        )
        length = math.sqrt(sum(value * value for value in view))
        if length <= 0:
            raise ValueError("reference sensor position cannot equal sampled surface point")
        cosine = sum(
            component * vector / length for component, vector in zip(normal, view, strict=True)
        )
        emission = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    return LocalGeometry(
        line_gsd,
        sample_gsd,
        view_zenith,
        emission,
        0.5 * max(line_gsd, sample_gsd),
        geometry_uncertainty,
        validation,
    )


@dataclass(frozen=True, slots=True)
class WarpPrior:
    """Coarse source-to-reference prior, never a substitute for verification."""

    displacement_line_px: float
    displacement_sample_px: float
    scale_line: float
    scale_sample: float
    orientation_deg: float
    displacement_uncertainty_px: float
    orientation_uncertainty_deg: float
    validation: GeometryValidation
    uncertainty_provenance: str = ""
    validation_evidence: ValidationEvidence | None = None

    def __post_init__(self) -> None:
        for name in (
            "displacement_line_px",
            "displacement_sample_px",
            "scale_line",
            "scale_sample",
            "orientation_deg",
            "displacement_uncertainty_px",
            "orientation_uncertainty_deg",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.scale_line <= 0 or self.scale_sample <= 0:
            raise ValueError("local scales must be positive")
        if self.displacement_uncertainty_px <= 0 or self.orientation_uncertainty_deg <= 0:
            raise ValueError("prior measurement uncertainties must be strictly positive")
        if not self.uncertainty_provenance.strip():
            raise ValueError("warp prior uncertainty provenance is required")
        if (
            self.validation is GeometryValidation.EXTERNALLY_VALIDATED
            and self.validation_evidence is None
        ):
            raise ValueError("external warp prior requires independent evidence")


def estimate_warp_prior(
    source_model: SensorModel,
    reference_projector: ReferenceProjector,
    *,
    sample_pixels: Sequence[SourcePixel],
    source_covariance_px2: float | None = None,
    reference_covariance_px2: float | None = None,
    validation: GeometryValidation = GeometryValidation.SYNTHETIC,
) -> WarpPrior:
    """Fit an affine sampled projection prior with residual/covariance uncertainty."""
    if len(sample_pixels) < 3:
        raise ValueError("at least three sampled pixels are required for a warp prior")
    if (source_covariance_px2 is not None and source_covariance_px2 <= 0) or (
        reference_covariance_px2 is not None and reference_covariance_px2 <= 0
    ):
        raise ValueError("projection covariance values must be strictly positive")
    pairs: list[tuple[SourcePixel, tuple[float, float]]] = []
    for pixel in sample_pixels:
        ground = source_model.ground_at(pixel)
        reference = reference_projector.pixel_at(ground) if ground is not None else None
        if reference is not None and all(math.isfinite(value) for value in reference):
            pairs.append((pixel, reference))
    if len(pairs) < 3:
        raise ValueError("fewer than three source/reference projection samples are available")
    # Normal equations for a 2-D affine fit, solved by explicit 3x3 inversion
    # through Gaussian elimination to keep the core NumPy-free at this boundary.
    design = [[pixel.line, pixel.sample, 1.0] for pixel, _ in pairs]
    targets = [[reference[0], reference[1]] for _, reference in pairs]
    normal = [[sum(row[i] * row[j] for row in design) for j in range(3)] for i in range(3)]
    inverse = _invert_3x3(normal)
    coefficients = [
        [
            sum(
                inverse[i][k]
                * sum(row[k] * target[axis] for row, target in zip(design, targets, strict=True))
                for k in range(3)
            )
            for i in range(3)
        ]
        for axis in range(2)
    ]
    predicted = [
        (
            sum(coefficients[0][i] * row[i] for i in range(3)),
            sum(coefficients[1][i] * row[i] for i in range(3)),
        )
        for row in design
    ]
    residuals = [
        math.hypot(value[0] - target[0], value[1] - target[1])
        for value, target in zip(predicted, targets, strict=True)
    ]
    residual_rms = math.sqrt(sum(value * value for value in residuals) / len(residuals))
    degrees_of_freedom = 2 * len(pairs) - 6
    covariance_supplied = source_covariance_px2 is not None and reference_covariance_px2 is not None
    if degrees_of_freedom <= 0 and not covariance_supplied:
        raise ValueError("warp prior needs supplied covariances or residual degrees of freedom")
    covariance_uncertainty = math.sqrt(
        (source_covariance_px2 or 0.0) + (reference_covariance_px2 or 0.0)
    )
    measured_uncertainty = math.hypot(residual_rms, covariance_uncertainty)
    if measured_uncertainty <= MIN_MEASURABLE_WARP_UNCERTAINTY_PX:
        raise ValueError("warp uncertainty is at or below the measurable uncertainty floor")
    line_vector = (coefficients[0][0], coefficients[1][0])
    sample_vector = (coefficients[0][1], coefficients[1][1])
    orientation = math.degrees(math.atan2(line_vector[1], line_vector[0]))
    return WarpPrior(
        coefficients[0][2],
        coefficients[1][2],
        math.hypot(*line_vector),
        math.hypot(*sample_vector),
        orientation,
        measured_uncertainty,
        math.degrees(math.atan2(measured_uncertainty, max(1e-12, math.hypot(*line_vector)))),
        validation,
        "supplied_projection_covariances"
        if covariance_supplied
        else f"affine_residual_dof_{degrees_of_freedom}",
    )


def _invert_3x3(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    augmented = [
        list(row) + [1.0 if i == j else 0.0 for j in range(3)] for i, row in enumerate(matrix)
    ]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("sampled projection geometry is degenerate")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row != column:
                factor = augmented[row][column]
                augmented[row] = [
                    value - factor * base
                    for value, base in zip(augmented[row], augmented[column], strict=True)
                ]
    return [row[3:] for row in augmented]
