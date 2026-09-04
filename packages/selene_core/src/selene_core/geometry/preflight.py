"""Conservative route qualification before a matcher is allowed to run."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from selene_core.geometry.contracts import (
    Footprint,
    GeometryValidation,
    LocalGeometry,
    SensorGeometry,
    WarpPrior,
)
from selene_core.geometry.crs import LunarCrs, select_lunar_crs

__all__ = ["PreflightPolicy", "PreflightReport", "RouteAdmissibility", "preflight_route"]


class RouteAdmissibility(StrEnum):
    ADMISSIBLE = "admissible"
    LIMITED = "limited"
    INADMISSIBLE = "inadmissible"


@dataclass(frozen=True, slots=True)
class PreflightReport:
    admissibility: RouteAdmissibility
    overlap_fraction: float
    source_gsd_m: float
    reference_gsd_m: float
    search_radius_px: float
    control_limitations: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreflightPolicy:
    """Conservative gates; routes do not run merely because structures exist."""

    minimum_overlap_fraction: float = 0.05
    maximum_gsd_ratio: float = 8.0
    maximum_search_radius_px: float = 512.0
    require_external_geometry: bool = True
    require_geodetic_control: bool = True

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.minimum_overlap_fraction)
            or not 0 < self.minimum_overlap_fraction <= 1
        ):
            raise ValueError("minimum_overlap_fraction must be in (0, 1]")
        if (
            not math.isfinite(self.maximum_gsd_ratio)
            or not math.isfinite(self.maximum_search_radius_px)
            or self.maximum_gsd_ratio < 1
            or self.maximum_search_radius_px <= 0
        ):
            raise ValueError("preflight maxima must be positive and GSD ratio at least one")


class ControlInventory(Protocol):
    """Minimal lower-layer view of a reference bundle's control evidence."""

    @property
    def has_geodetic_control(self) -> bool:
        """Whether a named control realisation is present."""

    def has_geodetic_control_for_latitudes(self, latitude_bounds_deg: tuple[float, float]) -> bool:
        """Whether control covers the complete source footprint latitude span."""

    def has_qualified_geodetic_control_for_latitudes(
        self, latitude_bounds_deg: tuple[float, float]
    ) -> bool:
        """Whether control has coverage and a finite positive uncertainty."""


def _bbox_overlap(first: Footprint, second: Footprint, *, crs: LunarCrs | None = None) -> float:
    """Conservative convex polygon overlap in an appropriate lunar projection.

    This avoids the optimistic bounding-box approximation.  It is a local,
    sampled approximation (not a global-area claim) and is rejected for a
    degenerate source boundary.
    """
    if first.boundary == second.boundary:
        return 1.0
    if crs is None:
        crs = select_lunar_crs(
            latitude_bounds_deg=(
                min(first.latitude_bounds_deg[0], second.latitude_bounds_deg[0]),
                max(first.latitude_bounds_deg[1], second.latitude_bounds_deg[1]),
            ),
            longitude_anchor_deg=first.longitude_anchor_deg,
        )

    def polygon(footprint: Footprint) -> list[tuple[float, float]]:
        return [(crs.project(point).x_m, crs.project(point).y_m) for point in footprint.boundary]

    def signed_area(vertices: list[tuple[float, float]]) -> float:
        return 0.5 * sum(
            first_vertex[0] * second_vertex[1] - second_vertex[0] * first_vertex[1]
            for first_vertex, second_vertex in zip(
                vertices, vertices[1:] + vertices[:1], strict=True
            )
        )

    def cross(
        origin: tuple[float, float], end: tuple[float, float], point: tuple[float, float]
    ) -> float:
        return (end[0] - origin[0]) * (point[1] - origin[1]) - (end[1] - origin[1]) * (
            point[0] - origin[0]
        )

    def intersection(
        start: tuple[float, float],
        end: tuple[float, float],
        clip_start: tuple[float, float],
        clip_end: tuple[float, float],
    ) -> tuple[float, float]:
        denominator = (end[0] - start[0]) * (clip_end[1] - clip_start[1]) - (end[1] - start[1]) * (
            clip_end[0] - clip_start[0]
        )
        if abs(denominator) < 1e-15:
            return end
        scale = (
            (clip_start[0] - start[0]) * (clip_end[1] - clip_start[1])
            - (clip_start[1] - start[1]) * (clip_end[0] - clip_start[0])
        ) / denominator
        return (start[0] + scale * (end[0] - start[0]), start[1] + scale * (end[1] - start[1]))

    subject = polygon(first)
    clip = polygon(second)
    subject_area = abs(signed_area(subject))
    if subject_area < 1e-12 or abs(signed_area(clip)) < 1e-12:
        return 0.0

    def convex(vertices: list[tuple[float, float]]) -> bool:
        turns = [
            cross(first_vertex, second_vertex, third_vertex)
            for first_vertex, second_vertex, third_vertex in zip(
                vertices, vertices[1:] + vertices[:1], vertices[2:] + vertices[:2], strict=True
            )
        ]
        return all(turn >= -1e-12 for turn in turns) or all(turn <= 1e-12 for turn in turns)

    if not convex(subject) or not convex(clip):
        return 0.0
    orientation = 1.0 if signed_area(clip) > 0 else -1.0
    output = subject
    for clip_start, clip_end in zip(clip, clip[1:] + clip[:1], strict=True):
        input_vertices, output = output, []
        if not input_vertices:
            break
        previous = input_vertices[-1]
        previous_inside = orientation * cross(clip_start, clip_end, previous) >= 0
        for current in input_vertices:
            current_inside = orientation * cross(clip_start, clip_end, current) >= 0
            if current_inside != previous_inside:
                output.append(intersection(previous, current, clip_start, clip_end))
            if current_inside:
                output.append(current)
            previous, previous_inside = current, current_inside
    return min(1.0, abs(signed_area(output)) / subject_area) if output else 0.0


def preflight_route(
    *,
    source_sensor: SensorGeometry,
    source_footprint: Footprint,
    source_local: LocalGeometry,
    reference_footprint: Footprint,
    reference_local: LocalGeometry,
    reference_bundle: ControlInventory,
    prior_uncertainty_px: float | None = None,
    warp_prior: WarpPrior | None = None,
    overlap_crs: LunarCrs | None = None,
    policy: PreflightPolicy | None = None,
) -> PreflightReport:
    """Emit qualified/limited/rejected route evidence; unknown geometry is never admitted."""
    policy = policy or PreflightPolicy()
    reasons: list[str] = []
    limitations: list[str] = list(source_sensor.limitations)
    overlap = _bbox_overlap(source_footprint, reference_footprint, crs=overlap_crs)
    validations = (
        source_sensor.validation,
        source_footprint.validation,
        reference_footprint.validation,
        source_local.validation,
        reference_local.validation,
    )
    if any(
        value in (GeometryValidation.UNAVAILABLE, GeometryValidation.INVALID)
        for value in validations
    ):
        reasons.append("source or reference geometry is unavailable or invalid")
    if policy.require_external_geometry and any(
        value is not GeometryValidation.EXTERNALLY_VALIDATED for value in validations
    ):
        reasons.append("route requires independently validated sensor and footprint geometry")
    if overlap < policy.minimum_overlap_fraction:
        reasons.append("sampled projected overlap is below the route threshold")
    if not reference_bundle.has_geodetic_control:
        message = "no named geodetic control: absolute metre claims are prohibited"
        limitations.append(message)
        if policy.require_geodetic_control:
            reasons.append(message)
    elif not reference_bundle.has_qualified_geodetic_control_for_latitudes(
        source_footprint.latitude_bounds_deg
    ):
        message = "named geodetic control lacks complete coverage or finite positive uncertainty"
        limitations.append(message)
        if policy.require_geodetic_control:
            reasons.append(message)
    scale = max(source_local.gsd_line_m, source_local.gsd_sample_m) / min(
        reference_local.gsd_line_m, reference_local.gsd_sample_m
    )
    if warp_prior is not None:
        if (
            warp_prior.validation is not GeometryValidation.EXTERNALLY_VALIDATED
            or warp_prior.validation_evidence is None
            or not warp_prior.uncertainty_provenance.strip()
        ):
            reasons.append("warp prior is not independently validated with uncertainty provenance")
        uncertainty = warp_prior.displacement_uncertainty_px
    else:
        uncertainty = (
            prior_uncertainty_px
            if prior_uncertainty_px is not None
            else 3.0
            * (
                source_local.gsd_uncertainty_m
                / max(reference_local.gsd_line_m, reference_local.gsd_sample_m)
            )
        )
    if not math.isfinite(uncertainty) or uncertainty < 0:
        reasons.append("search uncertainty is not finite and non-negative")
    search_radius = max(2.0, uncertainty * max(1.0, scale))
    gsd_ratio = max(
        source_local.gsd_line_m,
        source_local.gsd_sample_m,
        reference_local.gsd_line_m,
        reference_local.gsd_sample_m,
    ) / min(
        source_local.gsd_line_m,
        source_local.gsd_sample_m,
        reference_local.gsd_line_m,
        reference_local.gsd_sample_m,
    )
    if gsd_ratio > policy.maximum_gsd_ratio:
        reasons.append("source/reference GSD ratio exceeds route limit")
    if search_radius > policy.maximum_search_radius_px:
        reasons.append("geometry uncertainty implies a search radius above route limit")
    exploratory = any(value is not GeometryValidation.EXTERNALLY_VALIDATED for value in validations)
    state = (
        RouteAdmissibility.INADMISSIBLE
        if reasons
        else RouteAdmissibility.LIMITED
        if exploratory
        else RouteAdmissibility.ADMISSIBLE
    )
    return PreflightReport(
        state,
        overlap,
        (source_local.gsd_line_m + source_local.gsd_sample_m) / 2,
        (reference_local.gsd_line_m + reference_local.gsd_sample_m) / 2,
        search_radius,
        tuple(limitations),
        tuple(reasons),
    )
