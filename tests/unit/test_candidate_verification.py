"""Tests for candidate verification (WP-07 tasks 1, 2, 3, and 5's NMS half)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from selene_core.match.correspondence import CorrespondenceRecord, NmsStatus
from selene_core.select.verification import (
    apply_robust_fit,
    fit_robust_affine,
    remove_duplicate_candidates,
    suppress_non_maxima,
    verify_candidates,
    verify_forward_backward,
)
from selene_core.types import ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_VALID_SHA256 = "a" * 64
_VALID_SHA256_B = "b" * 64
_VALID_SHA256_C = "c" * 64

# A fixed small rotation (theta=0.1 rad) plus translation, used throughout as
# the "known" affine transform that synthetic inlier fixtures are built to
# satisfy exactly.
_THETA = 0.1
_A_LL = math.cos(_THETA)
_A_LS = -math.sin(_THETA)
_A_SL = math.sin(_THETA)
_A_SS = math.cos(_THETA)
_T_LINE = 5.0
_T_SAMPLE = -3.0


def _true_affine(line: float, sample: float) -> tuple[float, float]:
    """Apply the known test affine transform: (line, sample) -> (line, sample)."""
    return (
        _A_LL * line + _A_LS * sample + _T_LINE,
        _A_SL * line + _A_SS * sample + _T_SAMPLE,
    )


def _make_record(
    match_id: str,
    source: tuple[float, float],
    reference: tuple[float, float],
    raw_score: float,
    **overrides: Any,
) -> CorrespondenceRecord:
    kwargs: dict[str, Any] = {
        "match_id": match_id,
        "job_id": "job-1",
        "algorithm": "test",
        "algorithm_version": "1.0",
        "source_pixel": SourcePixel(line=source[0], sample=source[1]),
        "reference_pixel": ReferencePixel(line=reference[0], sample=reference[1]),
        "raw_score": raw_score,
        "input_digest": _VALID_SHA256,
        "reference_digest": _VALID_SHA256_B,
        "parameter_set_digest": _VALID_SHA256_C,
    }
    kwargs.update(overrides)
    return CorrespondenceRecord(**kwargs)


# A spread of 10 non-collinear source points that exactly satisfy _true_affine.
_CLEAN_SOURCES: tuple[tuple[float, float], ...] = (
    (0, 0),
    (10, 0),
    (0, 10),
    (10, 10),
    (5, 5),
    (20, 0),
    (0, 20),
    (15, 8),
    (8, 15),
    (3, 17),
)


def _clean_records(prefix: str = "clean", score: float = 0.9) -> tuple[CorrespondenceRecord, ...]:
    return tuple(
        _make_record(f"{prefix}-{i}", src, _true_affine(*src), score)
        for i, src in enumerate(_CLEAN_SOURCES)
    )


class TestRemoveDuplicateCandidates:
    def test_higher_raw_score_survives_within_radius(self) -> None:
        strong = _make_record("hi", (10.0, 10.0), (0.0, 0.0), 0.9)
        weak = _make_record("lo", (10.2, 10.1), (0.0, 0.0), 0.1)

        result = remove_duplicate_candidates((strong, weak), radius_px=1.0)

        assert len(result) == 1
        assert result[0].match_id == "hi"

    def test_tie_on_raw_score_breaks_by_smaller_match_id(self) -> None:
        record_m2 = _make_record("m2", (10.0, 10.0), (0.0, 0.0), 0.9)
        record_m1 = _make_record("m1", (10.2, 10.1), (0.0, 0.0), 0.9)

        result = remove_duplicate_candidates((record_m2, record_m1), radius_px=1.0)

        assert len(result) == 1
        assert result[0].match_id == "m1"

    def test_records_farther_than_radius_both_survive(self) -> None:
        near = _make_record("near", (10.0, 10.0), (0.0, 0.0), 0.9)
        far = _make_record("far", (100.0, 100.0), (0.0, 0.0), 0.1)

        result = remove_duplicate_candidates((near, far), radius_px=1.0)

        assert len(result) == 2
        assert {r.match_id for r in result} == {"near", "far"}

    def test_transitive_chain_collapses_to_one_survivor(self) -> None:
        """A-B within radius, B-C within radius, but A-C alone exceed it.

        Grouping is documented as transitive (union-find), which is the
        more surprising/less-obvious reading of "groups candidates whose
        source_pixel positions are within radius_px of each other" — this
        pins that behaviour down explicitly rather than leaving it only
        implied by the pairwise tests above.
        """
        record_a = _make_record("A", (0.0, 0.0), (0.0, 0.0), 0.9)  # highest score
        record_b = _make_record("B", (1.5, 0.0), (0.0, 0.0), 0.5)  # bridges A and C
        record_c = _make_record("C", (3.0, 0.0), (0.0, 0.0), 0.6)

        # distance(A, B) == 1.5 <= 2.0, distance(B, C) == 1.5 <= 2.0,
        # distance(A, C) == 3.0 > 2.0 (would NOT merge on a strict pairwise
        # reading with B absent).
        chained = remove_duplicate_candidates((record_a, record_b, record_c), radius_px=2.0)
        assert len(chained) == 1
        assert chained[0].match_id == "A"

        # Confirming the contrast: without the bridging B, A and C do NOT
        # merge, so the three-way collapse above is genuinely due to
        # transitivity through B, not some other radius coincidence.
        without_bridge = remove_duplicate_candidates((record_a, record_c), radius_px=2.0)
        assert len(without_bridge) == 2
        assert {r.match_id for r in without_bridge} == {"A", "C"}


class TestFitRobustAffine:
    def test_recovers_known_transform_and_identifies_exact_inliers(self) -> None:
        clean = _clean_records()
        outlier_sources = ((2.0, 2.0), (18.0, 3.0), (4.0, 19.0))
        outlier_offsets = ((60.0, 60.0), (-70.0, 40.0), (50.0, -55.0))
        outliers = tuple(
            _make_record(
                f"outlier-{i}",
                src,
                (_true_affine(*src)[0] + off[0], _true_affine(*src)[1] + off[1]),
                0.9,
            )
            for i, (src, off) in enumerate(zip(outlier_sources, outlier_offsets, strict=True))
        )
        records = clean + outliers

        fit = fit_robust_affine(
            records, residual_threshold_px=0.5, min_inliers=8, max_iterations=200, seed=42
        )

        assert fit.converged is True
        # Exactly the 10 clean records (indices 0..9), no outlier included.
        assert fit.inlier_indices == tuple(range(10))
        assert fit.transform is not None
        # A tight tolerance is justified: the clean points satisfy the true
        # affine exactly (zero synthetic noise), so the least-squares refit
        # over them should recover the true parameters to numerical
        # precision, not just approximately.
        assert fit.transform.a_line_line == pytest.approx(_A_LL, abs=1e-9)
        assert fit.transform.a_line_sample == pytest.approx(_A_LS, abs=1e-9)
        assert fit.transform.a_sample_line == pytest.approx(_A_SL, abs=1e-9)
        assert fit.transform.a_sample_sample == pytest.approx(_A_SS, abs=1e-9)
        assert fit.transform.t_line == pytest.approx(_T_LINE, abs=1e-9)
        assert fit.transform.t_sample == pytest.approx(_T_SAMPLE, abs=1e-9)

        # Residuals: near-zero for every clean record, large for every outlier.
        for index in range(10):
            assert fit.residuals_px[index] == pytest.approx(0.0, abs=1e-6)
        for index in range(10, 13):
            assert fit.residuals_px[index] > 10.0

        applied = apply_robust_fit(records, fit)
        for index in range(10):
            assert applied[index].is_inlier is True
            assert applied[index].rejection_reason is None
        for index in range(10, 13):
            assert applied[index].is_inlier is False
            assert applied[index].rejection_reason is not None
            reason = applied[index].rejection_reason
            assert reason is not None
            assert "residual" in reason
            assert "0.5" in reason

    def test_too_few_records_fails_to_converge(self) -> None:
        records = (
            _make_record("a", (0.0, 0.0), (0.0, 0.0), 0.5),
            _make_record("b", (1.0, 1.0), (1.0, 1.0), 0.5),
        )

        fit = fit_robust_affine(
            records, residual_threshold_px=0.5, min_inliers=2, max_iterations=10, seed=1
        )

        assert fit.converged is False
        assert fit.transform is None
        assert fit.inlier_indices == ()
        assert fit.residuals_px == ()
        assert fit.failure_reason is not None

    def test_incoherent_scatter_fails_to_reach_min_inliers(self) -> None:
        rng = np.random.default_rng(7)
        scatter_points = rng.uniform(0.0, 50.0, size=(8, 4))
        records = tuple(
            _make_record(
                f"scatter-{i}",
                (float(point[0]), float(point[1])),
                (float(point[2]), float(point[3])),
                0.5,
            )
            for i, point in enumerate(scatter_points)
        )

        fit = fit_robust_affine(
            records, residual_threshold_px=0.5, min_inliers=8, max_iterations=200, seed=3
        )

        assert fit.converged is False

        applied = apply_robust_fit(records, fit)
        assert all(record.is_inlier is False for record in applied)
        reasons = {record.rejection_reason for record in applied}
        # Every record shares the SAME "the fit itself failed" reason, not
        # individual per-point residual reasons (there is no trustworthy
        # model to measure a per-point residual against).
        assert len(reasons) == 1
        (reason,) = reasons
        assert reason is not None
        assert "did not converge" in reason

    def test_deterministic_given_same_seed(self) -> None:
        clean = _clean_records()
        outliers = tuple(
            _make_record(f"outlier-{i}", src, (src[0] + 90.0, src[1] - 90.0), 0.9)
            for i, src in enumerate(((2.0, 2.0), (18.0, 3.0)))
        )
        records = clean + outliers

        first = fit_robust_affine(
            records, residual_threshold_px=0.5, min_inliers=8, max_iterations=150, seed=99
        )
        second = fit_robust_affine(
            records, residual_threshold_px=0.5, min_inliers=8, max_iterations=150, seed=99
        )

        assert first.converged == second.converged
        assert first.transform == second.transform
        assert first.inlier_indices == second.inlier_indices
        assert first.residuals_px == second.residuals_px
        assert first.iterations_used == second.iterations_used


class TestSuppressNonMaxima:
    def test_far_record_and_stronger_near_record_survive_weaker_near_suppressed(self) -> None:
        strong = _make_record("strong", (5.0, 5.0), (0.0, 0.0), 0.9)
        weak_near = _make_record("weak", (5.1, 5.1), (0.0, 0.0), 0.5)
        far = _make_record("far", (50.0, 50.0), (0.0, 0.0), 0.3)

        result = suppress_non_maxima((strong, weak_near, far), radius_px=1.0)
        by_id = {r.match_id: r for r in result}

        assert by_id["strong"].nms_status is NmsStatus.SURVIVED
        assert by_id["far"].nms_status is NmsStatus.SURVIVED
        assert by_id["weak"].nms_status is NmsStatus.SUPPRESSED
        # Every record this function touched has a set status, never None.
        assert all(r.nms_status is not None for r in result)


class TestVerifyForwardBackward:
    def test_none_reverse_records_returns_input_unchanged(self) -> None:
        records = (
            _make_record("f1", (0.0, 0.0), (10.0, 10.0), 0.9),
            _make_record("f2", (5.0, 5.0), (15.0, 15.0), 0.7),
        )

        result = verify_forward_backward(
            records, None, max_error_px=1.0, reverse_lookup_tolerance_px=0.5
        )

        assert result == records
        assert result is records or all(a is b for a, b in zip(result, records, strict=True))

    def test_consistent_pair_gets_a_small_specific_error(self) -> None:
        forward = _make_record("f", (0.0, 0.0), (10.0, 10.0), 0.9)
        # Reverse record: source_pixel near forward's reference_pixel (10, 10);
        # reference_pixel close to forward's own source_pixel (0, 0).
        reverse = _make_record("rev", (10.0, 10.0), (0.05, -0.05), 0.9)

        result = verify_forward_backward(
            (forward,), (reverse,), max_error_px=1.0, reverse_lookup_tolerance_px=0.5
        )

        expected_error = math.hypot(0.05 - 0.0, -0.05 - 0.0)
        assert result[0].forward_backward_error_px == pytest.approx(expected_error, abs=1e-9)
        assert expected_error < 0.1  # "small", as required by the test brief

    def test_no_consistent_partner_leaves_error_as_none_not_zero(self) -> None:
        forward = _make_record("f", (0.0, 0.0), (10.0, 10.0), 0.9)
        # Reverse record's source_pixel is nowhere near forward's reference_pixel.
        reverse = _make_record("rev", (500.0, 500.0), (0.0, 0.0), 0.9)

        result = verify_forward_backward(
            (forward,), (reverse,), max_error_px=1.0, reverse_lookup_tolerance_px=0.5
        )

        assert result[0].forward_backward_error_px is None


class TestVerifyCandidatesComposition:
    def test_mixed_scenario_produces_expected_final_state(self) -> None:
        clean = _clean_records(prefix="core")

        dup_strong = _make_record("dup_strong", (30.0, 30.0), _true_affine(30.0, 30.0), 0.95)
        dup_weak = _make_record(
            "dup_weak", (30.3, 30.2), _true_affine(30.3, 30.2), 0.5
        )  # within dedup_radius=1.0 of dup_strong, lower score: dropped entirely

        nms_strong = _make_record("nms_strong", (40.0, 40.0), _true_affine(40.0, 40.0), 0.85)
        nms_weak = _make_record(
            "nms_weak", (41.5, 40.5), _true_affine(41.5, 40.5), 0.4
        )  # distance ~1.58 from nms_strong: farther than dedup_radius=1.0 (survives
        # dedup) but within nms_radius=3.0 (suppressed by NMS)

        outlier_source = (70.0, 70.0)
        true_ref = _true_affine(*outlier_source)
        outlier = _make_record(
            "outlier", outlier_source, (true_ref[0] + 60.0, true_ref[1] + 60.0), 0.6
        )  # spatially isolated (no dedup/NMS neighbours); badly displaced reference,
        # so it must be rejected by the robust fit specifically, not by dedup/NMS

        records = (*clean, dup_strong, dup_weak, nms_strong, nms_weak, outlier)

        result = verify_candidates(
            records,
            reverse_records=None,
            dedup_radius_px=1.0,
            nms_radius_px=3.0,
            fit_residual_threshold_px=0.5,
            fit_min_inliers=10,
            fit_max_iterations=200,
            fit_seed=123,
            forward_backward_max_error_px=1.0,
        )

        # dup_weak was a true duplicate: dropped entirely, not just rejected.
        assert len(result) == len(records) - 1
        by_id = {r.match_id: r for r in result}
        assert "dup_weak" not in by_id

        # dup_strong: survived dedup (it was the higher-scoring one), survived
        # NMS (no other survivor within nms_radius), and satisfies the true
        # affine exactly, so the robust fit accepts it.
        assert by_id["dup_strong"].nms_status is NmsStatus.SURVIVED
        assert by_id["dup_strong"].is_inlier is True
        assert by_id["dup_strong"].rejection_reason is None
        assert by_id["dup_strong"].robust_model_residual_px == pytest.approx(0.0, abs=1e-6)

        # nms_strong: survives NMS (it is the stronger of the pair) and is a
        # clean affine point, so the fit accepts it too.
        assert by_id["nms_strong"].nms_status is NmsStatus.SURVIVED
        assert by_id["nms_strong"].is_inlier is True

        # nms_weak: suppressed by NMS in favour of nms_strong, so it never
        # reaches the fit at all; it keeps its default is_inlier=False and no
        # rejection_reason (nms_status is its own, sufficient explanation).
        assert by_id["nms_weak"].nms_status is NmsStatus.SUPPRESSED
        assert by_id["nms_weak"].is_inlier is False
        assert by_id["nms_weak"].rejection_reason is None

        # outlier: survives dedup and NMS (spatially isolated), reaches the
        # fit, and is rejected there specifically, with a residual/threshold
        # in the reason.
        outlier_result = by_id["outlier"]
        assert outlier_result.nms_status is NmsStatus.SURVIVED
        assert outlier_result.is_inlier is False
        assert outlier_result.rejection_reason is not None
        assert "residual" in outlier_result.rejection_reason
        assert outlier_result.robust_model_residual_px is not None
        assert outlier_result.robust_model_residual_px > 10.0

        # All 10 core clean points are accepted inliers.
        for i in range(10):
            record = by_id[f"core-{i}"]
            assert record.is_inlier is True
            assert record.nms_status is NmsStatus.SURVIVED


class TestVerifyCandidatesAnchorToleranceIndependence:
    """`verify_candidates` composes `verify_forward_backward` with two
    conceptually distinct tolerances: `forward_backward_max_error_px` (the
    round-trip consistency budget) and `forward_backward_anchor_tolerance_px`
    (how tightly a reverse record must anchor to the forward record's
    reference_pixel to even be considered a candidate partner). These must
    be genuinely independent knobs, not the same value doing double duty.
    """

    def _forward_and_reverse(self) -> tuple[CorrespondenceRecord, CorrespondenceRecord]:
        forward = _make_record("f", (0.0, 0.0), (10.0, 10.0), 0.9)
        # anchor distance to forward.reference_pixel (10, 10) is
        # hypot(0.8, 0.8) ~= 1.1314px; round-trip error back to forward's
        # source_pixel (0, 0) is hypot(0.05, 0.05) ~= 0.0707px (small).
        reverse = _make_record("rev", (10.8, 10.8), (0.05, -0.05), 0.9)
        return forward, reverse

    def _run(self, anchor_tolerance_px: float | None, max_error_px: float = 5.0) -> Any:
        forward, reverse = self._forward_and_reverse()
        result = verify_candidates(
            (forward,),
            reverse_records=(reverse,),
            dedup_radius_px=1.0,
            nms_radius_px=1.0,
            fit_residual_threshold_px=0.5,
            fit_min_inliers=3,
            fit_max_iterations=10,
            fit_seed=1,
            forward_backward_max_error_px=max_error_px,
            forward_backward_anchor_tolerance_px=anchor_tolerance_px,
        )
        return result[0].forward_backward_error_px

    def test_tight_anchor_tolerance_rejects_candidate_despite_loose_round_trip_budget(
        self,
    ) -> None:
        # Anchor distance (~1.1314px) exceeds this tight 0.5px tolerance, so
        # the reverse record is never even considered a candidate partner —
        # even though forward_backward_max_error_px=5.0 would happily accept
        # its small round-trip error if the anchor step had let it through.
        error = self._run(anchor_tolerance_px=0.5, max_error_px=5.0)
        assert error is None

    def test_loose_anchor_tolerance_with_same_round_trip_budget_accepts_it(self) -> None:
        # Same forward_backward_max_error_px=5.0 as above; only the anchor
        # tolerance changes (0.5 -> 2.0, which is above the ~1.1314px anchor
        # distance). This isolates the anchor tolerance as the sole cause of
        # the differing outcome, proving the two parameters are independent.
        error = self._run(anchor_tolerance_px=2.0, max_error_px=5.0)
        assert error is not None
        assert error == pytest.approx(math.hypot(0.05, 0.05), abs=1e-9)

    def test_default_anchor_tolerance_is_half_the_round_trip_budget(self) -> None:
        # forward_backward_anchor_tolerance_px omitted (None): defaults to
        # forward_backward_max_error_px / 2 == 2.5px, comfortably above the
        # ~1.1314px anchor distance, so the candidate is found.
        error = self._run(anchor_tolerance_px=None, max_error_px=5.0)
        assert error is not None
        assert error == pytest.approx(math.hypot(0.05, 0.05), abs=1e-9)
