"""Synthetic checks for WP-03 contracts; no real SPICE/ISIS claim is made here."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from selene_core.geometry import (
    Footprint,
    FootprintValidationReport,
    GeometryValidation,
    GroundPoint,
    KernelFurnishingEvidence,
    PoseAvailability,
    PreflightPolicy,
    SensorGeometry,
    SpicePoseProvider,
    ValidationEvidence,
    WarpPrior,
    estimate_local_geometry,
    estimate_warp_prior,
    preflight_route,
    sample_footprint,
    sample_local_geometry,
    sample_provider_geometry,
    select_lunar_crs,
    validate_footprint,
    validated_footprint,
)
from selene_core.geometry.crs import Projection
from selene_core.geometry.preflight import _bbox_overlap
from selene_core.geometry.pyramid import (
    build_common_resolution_pyramid,
    build_paired_common_resolution_pyramid,
    combine_eligibility_masks,
    derive_eligibility_masks,
)
from selene_core.reference import (
    ReferenceBundle,
    control_network_adapter,
    lroc_nac_adapter,
    polar_dem_adapter,
    select_terrain_reference,
    sldem2015_adapter,
)
from selene_core.types import MapCoordinate, SourcePixel


class _WrapModel:
    def ground_at(self, pixel: SourcePixel) -> GroundPoint:
        return GroundPoint(pixel.line / 50.0, 179.0 + pixel.sample / 5.0)


class _ReferenceProjector:
    def pixel_at(self, ground: GroundPoint) -> tuple[float, float]:
        wrapped_delta = (ground.longitude_deg - 179.0 + 180.0) % 360.0 - 180.0
        return (ground.latitude_deg * 50.0 + 3.0, wrapped_delta * 5.0 + 4.0)


class _PoleModel:
    def ground_at(self, pixel: SourcePixel) -> GroundPoint:
        return GroundPoint(85.0 + pixel.line / 100.0, -179.0 + pixel.sample / 20.0)


def _footprint() -> Footprint:
    return sample_footprint(_WrapModel(), image_shape=(11, 11))


def _evidence() -> ValidationEvidence:
    return ValidationEvidence("independent-control", "a" * 64, "checkpoint-v1", 4.0)


def _footprint_evidence(points: tuple[GroundPoint, ...]) -> ValidationEvidence:
    payload = [[point.latitude_deg, point.longitude_deg, point.height_m] for point in points]
    digest = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return ValidationEvidence("independent-footprint", digest, "checkpoint-v1", 4.0)


def _validated_footprint(model: _WrapModel | _PoleModel | None = None) -> Footprint:
    sampled = sample_footprint(model or _WrapModel(), image_shape=(11, 11))
    independent = tuple(
        GroundPoint(point.latitude_deg + 0.000001, point.longitude_deg, point.height_m)
        for point in sampled.boundary
    )
    report = validate_footprint(
        sampled,
        expected_boundary=independent,
        tolerance_m=1.0,
        evidence=_footprint_evidence(independent),
    )
    return validated_footprint(sampled, report)


def test_sampled_footprint_preserves_antimeridian_continuity() -> None:
    footprint = _footprint()
    low, high = footprint.longitude_bounds_deg
    assert high - low == pytest.approx(2.0)
    assert len(footprint.interior) == 9


def test_polar_crs_serializes_moon_not_earth() -> None:
    crs = select_lunar_crs(latitude_bounds_deg=(76.0, 89.0), longitude_anchor_deg=12.0)
    assert crs.projection is Projection.NORTH_POLAR_STEREOGRAPHIC
    assert "Moon" in crs.to_wkt()
    assert "EPSG" not in crs.to_wkt()
    original = GroundPoint(82.0, -179.0)
    restored = crs.unproject(crs.project(original))
    assert restored.latitude_deg == pytest.approx(original.latitude_deg)
    assert restored.longitude_deg == pytest.approx(original.longitude_deg)
    footprint = sample_footprint(_PoleModel(), image_shape=(11, 11))
    assert footprint.is_polar
    assert (
        select_lunar_crs(latitude_bounds_deg=footprint.latitude_bounds_deg).projection
        is Projection.NORTH_POLAR_STEREOGRAPHIC
    )


def test_local_geometry_and_blurred_pyramid() -> None:
    local = estimate_local_geometry(line_neighbor_m=(3.0, 4.0), sample_neighbor_m=(0.0, 2.0))
    assert local.gsd_line_m == pytest.approx(5.0)
    checkerboard = np.indices((16, 16)).sum(axis=0) % 2
    level = build_common_resolution_pyramid(checkerboard, native_gsd_m=1.0, target_gsd_m=4.0)
    assert level.decimation == 4
    assert level.psf_source == "gaussian_fallback"
    assert level.image.shape == (4, 4)
    assert np.all(level.image > 0.1)
    assert np.all(level.image < 0.9)
    paired = build_paired_common_resolution_pyramid(
        checkerboard,
        checkerboard,
        source_native_gsd_m=1.0,
        reference_native_gsd_m=2.0,
        levels=2,
    )
    assert [entry.target_gsd_m for entry in paired] == [2.0, 4.0]
    assert paired[0].source.pixel_size_m == paired[0].reference.pixel_size_m == 2.0


def test_paired_pyramid_uses_centre_aligned_grids_and_conservative_masks() -> None:
    gradient = np.add.outer(np.arange(16, dtype=float) * 16, np.arange(16, dtype=float))
    source_mask = np.ones((16, 16), dtype=bool)
    reference_mask = np.ones((16, 16), dtype=bool)
    source_mask[3, 3] = False
    reference_mask[3, 3] = False
    paired = build_paired_common_resolution_pyramid(
        gradient,
        gradient,
        source_native_gsd_m=1.0,
        reference_native_gsd_m=2.0,
        levels=2,
        source_eligibility_mask=source_mask,
        reference_eligibility_mask=reference_mask,
    )
    source = paired[0].source
    assert source.grid_origin_x_m == pytest.approx(0.5)
    assert source.grid_origin_y_m == pytest.approx(0.5)
    assert source.affine[2] == pytest.approx(-0.5)
    assert source.affine[5] == pytest.approx(1.5)
    assert source.extent_m == pytest.approx((16.0, 16.0))
    assert source.image[2, 2] == pytest.approx(76.5)
    assert not source.eligibility_mask[1, 1]
    assert not paired[1].reference.eligibility_mask[1, 1]
    source_mask[3, 3] = True
    reference_mask[3, 3] = True
    assert not source.eligibility_mask[1, 1]
    assert not paired[1].reference.eligibility_mask[1, 1]
    assert not source.eligibility_mask.flags.writeable
    assert not paired[1].reference.eligibility_mask.flags.writeable
    with pytest.raises(ValueError, match="eligibility mask"):
        build_paired_common_resolution_pyramid(
            gradient,
            gradient,
            source_native_gsd_m=1.0,
            reference_native_gsd_m=2.0,
            source_eligibility_mask=np.ones((2, 2), dtype=bool),
        )


def test_eligibility_requires_every_physical_mask() -> None:
    valid = np.ones((2, 2), dtype=bool)
    illumination = np.array([[True, False], [True, True]])
    masks = combine_eligibility_masks(
        valid_source=valid,
        valid_reference=valid,
        overlap=valid,
        terrain_supported=valid,
        illumination_supported=illumination,
    )
    assert not masks.eligible[0, 1]
    derived = derive_eligibility_masks(
        source_valid=valid,
        reference_valid=valid,
        projected_overlap=valid,
        terrain_available=valid,
        illumination_acceptable=illumination,
    )
    assert np.array_equal(derived.eligible, masks.eligible)


def test_terrain_selection_does_not_use_sldem_at_poles() -> None:
    sldem = sldem2015_adapter(
        identifier="sldem",
        version="2015",
        horizontal_uncertainty_m=15.0,
        vertical_uncertainty_m=5.0,
    )
    polar = polar_dem_adapter(
        identifier="polar",
        version="v1",
        native_gsd_m=30.0,
        horizontal_uncertainty_m=10.0,
        vertical_uncertainty_m=4.0,
        latitude_coverage_deg=(75.0, 90.0),
    )
    assert select_terrain_reference((sldem, polar), latitude_deg=85.0).asset is polar
    selection = select_terrain_reference((sldem,), latitude_deg=85.0)
    assert not selection.available


def test_preflight_rejects_unvalidated_geometry_or_missing_control() -> None:
    footprint = _footprint()
    image = lroc_nac_adapter(identifier="M123", version="v1", footprint=footprint, native_gsd_m=2.0)
    bundle = ReferenceBundle("reference", "1", (image,))
    local = estimate_local_geometry(line_neighbor_m=(2.0, 0.0), sample_neighbor_m=(0.0, 2.0))
    report = preflight_route(
        source_sensor=SensorGeometry("TMC-2", "synthetic", GeometryValidation.SYNTHETIC),
        source_footprint=footprint,
        source_local=local,
        reference_footprint=footprint,
        reference_local=local,
        reference_bundle=bundle,
    )
    assert report.admissibility == "inadmissible"
    assert report.overlap_fraction == pytest.approx(1.0)
    assert any("absolute metre" in value for value in report.control_limitations)


def test_sampled_geometry_prior_and_footprint_validation() -> None:
    model = _WrapModel()
    local = sample_local_geometry(
        model,
        pixel=SourcePixel(5.0, 5.0),
        pose_position_m=(2_000_000.0, 0.0, 0.0),
        reference_pose_position_m=(-2_000_000.0, 0.0, 0.0),
        pose_covariance_m2=16.0,
    )
    assert local.gsd_line_m > 0
    assert local.emission_deg is not None
    assert local.view_zenith_deg != local.emission_deg
    assert local.geometry_uncertainty_deg is not None
    prior = estimate_warp_prior(
        model,
        _ReferenceProjector(),
        sample_pixels=(
            SourcePixel(1.0, 1.0),
            SourcePixel(1.0, 8.0),
            SourcePixel(8.0, 1.0),
            SourcePixel(8.0, 8.0),
        ),
        source_covariance_px2=0.25,
        reference_covariance_px2=0.25,
    )
    assert prior.scale_line == pytest.approx(1.0)
    assert prior.scale_sample == pytest.approx(1.0)
    footprint = _footprint()
    report: FootprintValidationReport = validate_footprint(
        footprint,
        expected_boundary=footprint.boundary,
        tolerance_m=1.0,
        evidence=_footprint_evidence(footprint.boundary),
    )
    assert report.validation is GeometryValidation.EXTERNALLY_VALIDATED
    shifted = tuple(
        GroundPoint(point.latitude_deg, point.longitude_deg + 1.0) for point in footprint.boundary
    )
    assert (
        validate_footprint(
            footprint,
            expected_boundary=shifted,
            tolerance_m=1.0,
            evidence=_footprint_evidence(shifted),
        ).validation
        is GeometryValidation.INVALID
    )


def test_pose_provider_unavailability_is_explicit() -> None:
    provider = SpicePoseProvider(
        KernelFurnishingEvidence(
            PoseAvailability.UNAVAILABLE,
            GeometryValidation.UNAVAILABLE,
            (),
            "SPICE is not installed",
        )
    )
    report = sample_provider_geometry(provider, image_shape=(4, 5))
    assert report.validation is GeometryValidation.UNAVAILABLE
    assert report.pose_samples == report.ground_samples == 0


def test_external_status_cannot_be_fabricated_without_evidence() -> None:
    with pytest.raises(ValueError, match="independent evidence"):
        SensorGeometry(
            "TMC-2", "claimed", GeometryValidation.EXTERNALLY_VALIDATED, pose_source="text"
        )
    with pytest.raises(ValueError, match="validated_footprint"):
        sample_footprint(
            _WrapModel(), image_shape=(11, 11), validation=GeometryValidation.EXTERNALLY_VALIDATED
        )
    with pytest.raises(ValueError, match="covariances or residual"):
        estimate_warp_prior(
            _WrapModel(),
            _ReferenceProjector(),
            sample_pixels=(SourcePixel(1.0, 1.0), SourcePixel(1.0, 8.0), SourcePixel(8.0, 1.0)),
        )
    with pytest.raises(ValueError, match="strictly positive"):
        estimate_warp_prior(
            _WrapModel(),
            _ReferenceProjector(),
            sample_pixels=(SourcePixel(1.0, 1.0), SourcePixel(1.0, 8.0), SourcePixel(8.0, 1.0)),
            source_covariance_px2=0.0,
            reference_covariance_px2=0.0,
        )
    with pytest.raises(ValueError, match="measurable uncertainty floor"):
        estimate_warp_prior(
            _WrapModel(),
            _ReferenceProjector(),
            sample_pixels=(
                SourcePixel(1.0, 1.0),
                SourcePixel(1.0, 8.0),
                SourcePixel(8.0, 1.0),
                SourcePixel(8.0, 8.0),
            ),
        )
    with pytest.raises(ValueError, match="uncertainty provenance"):
        WarpPrior(0.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0, GeometryValidation.SYNTHETIC)


def test_preflight_admits_external_geometry_and_control() -> None:
    control = control_network_adapter(
        identifier="control",
        version="v1",
        horizontal_uncertainty_m=3.0,
        latitude_coverage_deg=(-90.0, 90.0),
    )
    bundle = ReferenceBundle("reference", "1", (control,))
    local = estimate_local_geometry(
        line_neighbor_m=(2.0, 0.0),
        sample_neighbor_m=(0.0, 2.0),
        validation=GeometryValidation.EXTERNALLY_VALIDATED,
        validation_evidence=_evidence(),
    )
    report = preflight_route(
        source_sensor=SensorGeometry(
            "TMC-2",
            "real",
            GeometryValidation.EXTERNALLY_VALIDATED,
            pose_source="test",
            validation_evidence=_evidence(),
        ),
        source_footprint=_validated_footprint(),
        source_local=local,
        reference_footprint=_validated_footprint(),
        reference_local=local,
        reference_bundle=bundle,
        policy=PreflightPolicy(minimum_overlap_fraction=0.5),
    )
    assert report.admissibility == "admissible"


def test_preflight_rejects_control_that_does_not_cover_footprint() -> None:
    control = control_network_adapter(
        identifier="narrow-control",
        version="v1",
        horizontal_uncertainty_m=3.0,
        latitude_coverage_deg=(20.0, 30.0),
    )
    local = estimate_local_geometry(
        line_neighbor_m=(2.0, 0.0),
        sample_neighbor_m=(0.0, 2.0),
        validation=GeometryValidation.EXTERNALLY_VALIDATED,
        validation_evidence=_evidence(),
    )
    footprint = _validated_footprint()
    report = preflight_route(
        source_sensor=SensorGeometry(
            "TMC-2",
            "real",
            GeometryValidation.EXTERNALLY_VALIDATED,
            pose_source="test",
            validation_evidence=_evidence(),
        ),
        source_footprint=footprint,
        source_local=local,
        reference_footprint=footprint,
        reference_local=local,
        reference_bundle=ReferenceBundle("reference", "1", (control,)),
    )
    assert report.admissibility == "inadmissible"
    assert any("lacks complete coverage" in reason for reason in report.reasons)


def test_polar_projected_overlap_and_zero_control_uncertainty_are_gated() -> None:
    footprint = _validated_footprint(_PoleModel())
    local = estimate_local_geometry(
        line_neighbor_m=(2.0, 0.0),
        sample_neighbor_m=(0.0, 2.0),
        validation=GeometryValidation.EXTERNALLY_VALIDATED,
        validation_evidence=_evidence(),
    )
    zero_uncertainty_control = control_network_adapter(
        identifier="zero-budget",
        version="v1",
        horizontal_uncertainty_m=0.0,
        latitude_coverage_deg=(-90.0, 90.0),
    )
    report = preflight_route(
        source_sensor=SensorGeometry(
            "TMC-2",
            "real",
            GeometryValidation.EXTERNALLY_VALIDATED,
            pose_source="test",
            validation_evidence=_evidence(),
        ),
        source_footprint=footprint,
        source_local=local,
        reference_footprint=footprint,
        reference_local=local,
        reference_bundle=ReferenceBundle("reference", "1", (zero_uncertainty_control,)),
    )
    assert report.overlap_fraction == pytest.approx(1.0)
    assert report.admissibility == "inadmissible"
    assert any("positive uncertainty" in reason for reason in report.reasons)


def test_projected_polar_clip_and_nonconvex_fail_closed() -> None:
    crs = select_lunar_crs(latitude_bounds_deg=(80.0, 90.0))

    def footprint_from_xy(vertices: tuple[tuple[float, float], ...]) -> Footprint:
        boundary = tuple(
            crs.unproject(MapCoordinate(x_m, y_m, crs.to_wkt())) for x_m, y_m in vertices
        )
        return Footprint(boundary, (), GeometryValidation.SYNTHETIC, 0.0, True)

    first = footprint_from_xy(
        (
            (-10_000.0, -100_000.0),
            (10_000.0, -100_000.0),
            (10_000.0, -80_000.0),
            (-10_000.0, -80_000.0),
        )
    )
    second = footprint_from_xy(
        (
            (-5_000.0, -100_000.0),
            (15_000.0, -100_000.0),
            (15_000.0, -80_000.0),
            (-5_000.0, -80_000.0),
        )
    )
    overlap = _bbox_overlap(first, second, crs=crs)
    assert 0.0 < overlap < 1.0
    nonconvex = footprint_from_xy(
        (
            (-10_000.0, -100_000.0),
            (10_000.0, -100_000.0),
            (0.0, -90_000.0),
            (10_000.0, -80_000.0),
            (-10_000.0, -80_000.0),
        )
    )
    assert _bbox_overlap(nonconvex, second, crs=crs) == 0.0
