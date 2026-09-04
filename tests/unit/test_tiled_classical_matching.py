"""Regression tests for the tiled WP-04 orchestration and diagnostic runner."""

from __future__ import annotations

import numpy as np
import pytest
from benchmarks.scripts.controlled_shift import generate_controlled_shift_fixture

from selene_core.geometry.pyramid import build_paired_common_resolution_pyramid
from selene_core.match import (
    MatchParameters,
    MatchPrior,
    MatchTile,
    NccMatcher,
    RiftMatcher,
    VerificationParameters,
    deduplicate_tile_records,
    match_pyramid_tiles,
    run_classical_match,
)
from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.verification import verify_match_candidates
from selene_core.types import LocalWarpJacobian, PixelWindow, ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_SOURCE_DIGEST = "a" * 64
_REFERENCE_DIGEST = "b" * 64


class _ReciprocalMatcher:
    """Minimal matcher whose reciprocal anchors make the runner checkable."""

    def match(
        self,
        source: np.ndarray,
        reference: np.ndarray,
        *,
        source_mask: np.ndarray | None,
        reference_mask: np.ndarray | None,
        prior: MatchPrior,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
    ) -> tuple[CorrespondenceRecord, ...]:
        del source, reference, source_mask, reference_mask, prior
        return (
            CorrespondenceRecord(
                job_id=job_id,
                algorithm="reciprocal-test",
                algorithm_version="1",
                source_pixel=SourcePixel(10.0, 10.0),
                reference_pixel=ReferencePixel(10.0, 10.0),
                raw_score=1.0,
                is_candidate=True,
                point_role=PointRole.CANDIDATE,
                input_digest=input_digest,
                reference_digest=reference_digest,
                parameter_set_digest=parameters.parameter_set_digest,
            ),
        )


def _parameters() -> MatchParameters:
    return MatchParameters(
        values={"grid_spacing_px": 16, "template_half_size_px": 4, "search_radius_px": 8}
    )


def _record(*, match_id: str, score: float, line: float = 10.0) -> CorrespondenceRecord:
    return CorrespondenceRecord(
        match_id=match_id,
        job_id="tiled-job",
        algorithm="test",
        algorithm_version="1",
        tile_id="b" if match_id == "lower" else "a",
        pyramid_level=0,
        source_pixel=SourcePixel(line=line, sample=10.0),
        reference_pixel=ReferencePixel(line=line + 2.0, sample=7.0),
        raw_score=score,
        is_candidate=True,
        point_role=PointRole.CANDIDATE,
        input_digest=_SOURCE_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
        parameter_set_digest="c" * 64,
    )


def test_tiled_ncc_translates_coordinates_and_keeps_overlap_rejection() -> None:
    fixture = generate_controlled_shift_fixture((33, 33), dy_px=2.0, dx_px=-1.0, seed=211)
    level = build_paired_common_resolution_pyramid(
        fixture.base_image,
        fixture.shifted_image,
        source_native_gsd_m=1.0,
        reference_native_gsd_m=1.0,
    )[0]
    tile = MatchTile(
        tile_id="L0-0001",
        pyramid_level=0,
        level=level,
        source_window=PixelWindow(100, 200, 33, 33),
        reference_window=PixelWindow(102, 199, 33, 33),
    )

    result = match_pyramid_tiles(
        NccMatcher(),
        (tile,),
        prior=MatchPrior(displacement_px=(2.0, -1.0)),
        parameters=_parameters(),
        job_id="tiled-job",
        input_digest=_SOURCE_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )

    assert result.records
    assert all(record.tile_id == "L0-0001" for record in result.records)
    assert all(record.pyramid_level == 0 for record in result.records)
    assert all(record.source_pixel.line >= 100.0 for record in result.records)
    # Relative source/reference crop origins represent the same predicted
    # physical shift, so translated records retain that shift.
    first = result.records[0]
    assert first.reference_pixel.line - first.source_pixel.line == pytest.approx(4.0)
    assert first.reference_pixel.sample - first.source_pixel.sample == pytest.approx(-2.0)


def test_overlap_deduplication_is_deterministic_and_auditable() -> None:
    lower = _record(match_id="lower", score=0.5)
    higher = _record(match_id="higher", score=0.9)

    records = deduplicate_tile_records((lower, higher), radius_px=0.1)

    assert records[0].point_role is PointRole.REJECTED
    assert records[0].is_candidate is False
    assert records[0].rejection_reason is not None
    assert records[1].point_role is PointRole.CANDIDATE
    # Scheduling order must not decide the retained evidence.
    reversed_records = deduplicate_tile_records((higher, lower), radius_px=0.1)
    assert [r.match_id for r in reversed_records if r.rejection_reason is None] == ["higher"]


def test_affine_prior_changes_local_expected_displacement() -> None:
    prior = MatchPrior(
        displacement_px=(2.0, -1.0),
        local_warp_jacobian=LocalWarpJacobian(1.1, 0.0, 0.0, 0.9),
        anchor_source_pixel=SourcePixel(10.0, 10.0),
    )

    assert prior.displacement_at(SourcePixel(20.0, 20.0)) == pytest.approx((3.0, -2.0))
    assert prior.residual_at(SourcePixel(20.0, 20.0), (3.0, -2.0)) == (0.0, 0.0)


def test_runner_records_bidirectional_and_robust_diagnostics_without_benchmark_claim() -> None:
    fixture = generate_controlled_shift_fixture((63, 79), dy_px=5.0, dx_px=-3.0, seed=223)

    report = run_classical_match(
        _ReciprocalMatcher(),
        fixture.base_image,
        fixture.shifted_image,
        source_mask=np.ones((63, 79), dtype=bool),
        reference_mask=np.ones((63, 79), dtype=bool),
        prior=MatchPrior(),
        parameters=_parameters(),
        verification=VerificationParameters(),
        job_id="run-job",
        input_digest=_SOURCE_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )

    assert report.reverse_candidates is not None
    assert report.inlier_count == 0  # one point cannot fit an affine model
    assert report.evidence_status == "diagnostic_only_not_a_benchmark_claim"
    assert all(
        record.forward_backward_error_px == pytest.approx(0.0)
        for record in report.verified_candidates
    )


def test_missing_reverse_partner_is_a_structural_rejection_with_reason() -> None:
    verified = verify_match_candidates(
        (_record(match_id="forward", score=1.0),),
        reverse_records=(),
        residual_threshold_px=2.0,
        min_inliers=3,
        max_iterations=8,
        forward_backward_max_error_px=1.0,
    )

    assert verified[0].point_role is PointRole.REJECTED
    assert verified[0].is_candidate is False
    assert verified[0].rejection_reason is not None
    assert "forward/backward" in verified[0].rejection_reason


def test_builtin_rift_class_gradient_baseline_is_operational_and_declared() -> None:
    fixture = generate_controlled_shift_fixture((33, 33), dy_px=2.0, dx_px=-1.0, seed=227)
    matcher = RiftMatcher()

    records = matcher.match(
        fixture.base_image,
        fixture.shifted_image,
        source_mask=None,
        reference_mask=None,
        prior=MatchPrior(),
        parameters=_parameters(),
        job_id="rift-job",
        input_digest=_SOURCE_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )

    assert matcher.provenance.available is True
    assert matcher.provenance.license_expression == "Apache-2.0"
    assert records
    assert {record.algorithm for record in records} == {"rift_class_gradient_ncc"}
