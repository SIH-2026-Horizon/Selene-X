"""Tests for the scene verdict engine and immutable review records (plan
sections 8, 10; WP-09 tasks 9-11).

One (or more) test per numbered verdict rule, plus dedicated coverage of
``compute_scene_verdict``'s outcome-combination logic, ``derive_scene_metrics``'s
per-metric arithmetic, the injectable clock, and the ``GateResult``
applicability pairing validator.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.metrics.verdict import (
    GateKind,
    GateResult,
    GateSpec,
    ReviewRecord,
    SceneEvidence,
    compute_scene_verdict,
    derive_scene_metrics,
    effective_disposition,
    evaluate_gate,
)
from selene_core.select.coverage import CoverageMetrics
from selene_core.types import ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64


def _record(**overrides: object) -> CorrespondenceRecord:
    defaults: dict[str, object] = {
        "job_id": "job-1",
        "algorithm": "phase_correlation",
        "algorithm_version": "1.0",
        "source_pixel": SourcePixel(line=1.0, sample=2.0),
        "reference_pixel": ReferencePixel(line=1.0, sample=2.0),
        "raw_score": 0.9,
        "input_digest": _SHA_A,
        "reference_digest": _SHA_B,
        "parameter_set_digest": _SHA_C,
    }
    defaults.update(overrides)
    return CorrespondenceRecord(**defaults)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> SceneEvidence:
    defaults: dict[str, object] = {
        "route_qualified": True,
        "route_id": "route-1",
        "is_synthetic": False,
        "has_independent_control": True,
        "control_uncertainty_m": 1.5,
        "metrics": {},
    }
    defaults.update(overrides)
    return SceneEvidence(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Rule 1: applicability first
# ---------------------------------------------------------------------------


class TestRule1ApplicabilityFirst:
    def test_route_qualification_only_gate_inapplicable_on_synthetic_scene(self) -> None:
        spec = GateSpec(
            name="real_data_claim",
            kind=GateKind.HARD,
            metric_name="some_metric",
            comparison="ge",
            threshold=0.5,
            route_qualification_only=True,
        )
        evidence = _evidence(is_synthetic=True, metrics={"some_metric": 0.9})

        result = evaluate_gate(spec, evidence)

        assert result.applicable is False
        assert result.applicability_reason
        assert result.passed is None

    def test_same_gate_applicable_on_non_synthetic_scene_with_metric_present(self) -> None:
        spec = GateSpec(
            name="real_data_claim",
            kind=GateKind.HARD,
            metric_name="some_metric",
            comparison="ge",
            threshold=0.5,
            route_qualification_only=True,
        )
        evidence = _evidence(is_synthetic=False, metrics={"some_metric": 0.9})

        result = evaluate_gate(spec, evidence)

        assert result.applicable is True
        assert result.applicability_reason is None
        assert result.passed is True


# ---------------------------------------------------------------------------
# Rule 2: missing applicable hard-gate metric is a rejection, not a pass
# ---------------------------------------------------------------------------


class TestRule2MissingHardGateMetric:
    def test_missing_metric_on_applicable_hard_gate_is_not_passed(self) -> None:
        spec = GateSpec(
            name="eligible_occupancy",
            kind=GateKind.HARD,
            metric_name="eligible_occupancy",
            comparison="ge",
            threshold=0.7,
        )
        evidence = _evidence(metrics={"eligible_occupancy": None})

        result = evaluate_gate(spec, evidence)

        assert result.applicable is True
        assert result.passed is False

    def test_missing_hard_gate_metric_rejects_the_scene(self) -> None:
        spec = GateSpec(
            name="eligible_occupancy",
            kind=GateKind.HARD,
            metric_name="eligible_occupancy",
            comparison="ge",
            threshold=0.7,
        )
        evidence = _evidence(metrics={"eligible_occupancy": None})
        result = evaluate_gate(spec, evidence)

        verdict = compute_scene_verdict((result,), route_qualified=True, route_id="route-1")

        assert verdict.verdict == "reject"
        assert "eligible_occupancy" in verdict.reason

    def test_missing_metric_on_applicable_soft_gate_is_also_not_passed(self) -> None:
        """Rule 2 applies to BOTH hard and soft gates: a SOFT gate that
        cannot be evaluated is not silently treated as passing."""
        spec = GateSpec(
            name="diagnostic_gate",
            kind=GateKind.SOFT,
            metric_name="diagnostic_metric",
            comparison="ge",
            threshold=0.7,
        )
        evidence = _evidence(metrics={"diagnostic_metric": None})

        result = evaluate_gate(spec, evidence)

        assert result.applicable is True
        assert result.passed is False

        verdict = compute_scene_verdict((result,), route_qualified=True, route_id="route-1")
        assert verdict.verdict == "review"  # forces review, not accept -- and not reject by itself


# ---------------------------------------------------------------------------
# Rule 3: no independent control -> no independent-accuracy claim
# ---------------------------------------------------------------------------


class TestRule3NoIndependentControl:
    def test_inapplicable_regardless_of_metric_presence(self) -> None:
        """Applicability must be decided BEFORE the value lookup: construct a
        case where the metric IS present but the gate is still inapplicable."""
        spec = GateSpec(
            name="withheld_rmse",
            kind=GateKind.HARD,
            metric_name="withheld_rmse_2d_px",
            comparison="le",
            threshold=5.0,
            requires_independent_control=True,
        )
        evidence = _evidence(
            has_independent_control=False,
            metrics={"withheld_rmse_2d_px": 0.1},  # present, and would easily pass
        )

        result = evaluate_gate(spec, evidence)

        assert result.applicable is False
        assert result.applicability_reason
        assert result.passed is None

    def test_applicable_when_independent_control_present(self) -> None:
        spec = GateSpec(
            name="withheld_rmse",
            kind=GateKind.HARD,
            metric_name="withheld_rmse_2d_px",
            comparison="le",
            threshold=5.0,
            requires_independent_control=True,
        )
        evidence = _evidence(
            has_independent_control=True,
            metrics={"withheld_rmse_2d_px": 0.1},
        )

        result = evaluate_gate(spec, evidence)

        assert result.applicable is True
        assert result.passed is True


# ---------------------------------------------------------------------------
# Rule 4: fit residuals can't satisfy an independent-accuracy gate
# ---------------------------------------------------------------------------


class TestRule4FitResidualsCannotSatisfyIndependentAccuracy:
    def test_withheld_rmse_is_none_when_only_fit_role_records_exist(self) -> None:
        records = (
            _record(
                is_candidate=True,
                point_role=PointRole.FITTING_INLIER,
                robust_model_residual_px=0.5,
            ),
            _record(
                is_candidate=True,
                point_role=PointRole.TRAINING,
                robust_model_residual_px=0.7,
            ),
        )
        coverage = CoverageMetrics(
            eligible_cell_occupancy=0.5,
            convex_hull_to_eligible_area_ratio=None,
            largest_empty_run=0,
            per_cell_candidate_counts=np.zeros((8, 8), dtype=np.int64),
        )

        metrics = derive_scene_metrics(records, coverage)

        assert metrics["withheld_rmse_2d_px"] is None


# ---------------------------------------------------------------------------
# Rule 5: synthetic can't pass a real-data route gate
# ---------------------------------------------------------------------------


class TestRule5SyntheticCannotPassRealDataRouteGate:
    def test_inapplicable_gate_does_not_force_reject_and_overall_is_accept(self) -> None:
        spec = GateSpec(
            name="real_data_claim",
            kind=GateKind.HARD,
            metric_name="some_metric",
            comparison="ge",
            threshold=0.9,
            route_qualification_only=True,
        )
        # An otherwise-passing metric value: if this gate were (incorrectly)
        # applicable it would pass; the point is that it must be inapplicable.
        evidence = _evidence(is_synthetic=True, metrics={"some_metric": 0.99})

        result = evaluate_gate(spec, evidence)
        assert result.applicable is False

        verdict = compute_scene_verdict((result,), route_qualified=True, route_id="route-1")
        assert verdict.verdict == "accept"


# ---------------------------------------------------------------------------
# Rule 6: absolute metre claim needs control uncertainty
# ---------------------------------------------------------------------------


class TestRule6AbsoluteMetreClaimNeedsControlUncertainty:
    def test_inapplicable_when_control_uncertainty_missing(self) -> None:
        spec = GateSpec(
            name="absolute_error_m",
            kind=GateKind.HARD,
            metric_name="absolute_error_m",
            comparison="le",
            threshold=10.0,
            requires_absolute_control_uncertainty=True,
        )
        evidence = _evidence(control_uncertainty_m=None, metrics={"absolute_error_m": 3.0})

        result = evaluate_gate(spec, evidence)

        assert result.applicable is False
        assert result.applicability_reason

    def test_applicable_when_control_uncertainty_present(self) -> None:
        spec = GateSpec(
            name="absolute_error_m",
            kind=GateKind.HARD,
            metric_name="absolute_error_m",
            comparison="le",
            threshold=10.0,
            requires_absolute_control_uncertainty=True,
        )
        evidence = _evidence(control_uncertainty_m=2.0, metrics={"absolute_error_m": 3.0})

        result = evaluate_gate(spec, evidence)

        assert result.applicable is True
        assert result.passed is True


# ---------------------------------------------------------------------------
# Rule 7: review can't override reject or rewrite the verdict
# ---------------------------------------------------------------------------


class TestRule7ReviewCannotOverrideRejectOrRewrite:
    def test_reject_verdict_stays_rejected_even_with_accepting_review(self) -> None:
        verdict = compute_scene_verdict((), route_qualified=False, route_id="route-1")
        adversarial_review = ReviewRecord(
            actor="reviewer-1",
            decision="accepted",
            reason_code="looks_fine_to_me",
            note=None,
            input_verdict="reject",
            reviewed_utc=datetime(2026, 1, 1, tzinfo=UTC),
        )

        disposition = effective_disposition(verdict, (adversarial_review,))

        assert disposition == "rejected"

    def test_review_verdict_with_accepted_review_is_accepted(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="soft_gate",
                kind=GateKind.SOFT,
                metric_name="m",
                comparison="ge",
                threshold=1.0,
            ),
            _evidence(metrics={"m": 0.0}),
        )
        verdict = compute_scene_verdict((gate,), route_qualified=True, route_id="route-1")
        assert verdict.verdict == "review"

        review = ReviewRecord(
            actor="reviewer-1",
            decision="accepted",
            reason_code="manual_check_ok",
            note=None,
            input_verdict="review",
            reviewed_utc=datetime(2026, 1, 1, tzinfo=UTC),
        )

        disposition = effective_disposition(verdict, (review,))
        assert disposition == "accepted"

    def test_review_verdict_with_rejected_review_is_rejected(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="soft_gate",
                kind=GateKind.SOFT,
                metric_name="m",
                comparison="ge",
                threshold=1.0,
            ),
            _evidence(metrics={"m": 0.0}),
        )
        verdict = compute_scene_verdict((gate,), route_qualified=True, route_id="route-1")
        review = ReviewRecord(
            actor="reviewer-1",
            decision="rejected",
            reason_code="manual_check_failed",
            note=None,
            input_verdict="review",
            reviewed_utc=datetime(2026, 1, 1, tzinfo=UTC),
        )

        disposition = effective_disposition(verdict, (review,))
        assert disposition == "rejected"

    def test_review_verdict_with_no_review_is_pending(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="soft_gate",
                kind=GateKind.SOFT,
                metric_name="m",
                comparison="ge",
                threshold=1.0,
            ),
            _evidence(metrics={"m": 0.0}),
        )
        verdict = compute_scene_verdict((gate,), route_qualified=True, route_id="route-1")

        disposition = effective_disposition(verdict, ())
        assert disposition == "pending"

    def test_effective_disposition_does_not_mutate_inputs(self) -> None:
        gate = evaluate_gate(
            GateSpec(
                name="soft_gate",
                kind=GateKind.SOFT,
                metric_name="m",
                comparison="ge",
                threshold=1.0,
            ),
            _evidence(metrics={"m": 0.0}),
        )
        verdict = compute_scene_verdict(
            (gate,),
            route_qualified=True,
            route_id="route-1",
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        )
        review = ReviewRecord(
            actor="reviewer-1",
            decision="accepted",
            reason_code="manual_check_ok",
            note=None,
            input_verdict="review",
            reviewed_utc=datetime(2026, 1, 2, tzinfo=UTC),
        )

        verdict_before = verdict.model_copy(deep=True)
        review_before = review.model_copy(deep=True)

        effective_disposition(verdict, (review,))

        assert verdict == verdict_before
        assert review == review_before


# ---------------------------------------------------------------------------
# compute_scene_verdict combination logic
# ---------------------------------------------------------------------------


class TestComputeSceneVerdictCombination:
    def test_hard_gate_fails_wins_over_soft_gate_passes(self) -> None:
        hard = evaluate_gate(
            GateSpec(
                name="hard_gate",
                kind=GateKind.HARD,
                metric_name="hard_metric",
                comparison="ge",
                threshold=0.7,
            ),
            _evidence(metrics={"hard_metric": 0.1, "soft_metric": 1.0}),
        )
        soft = evaluate_gate(
            GateSpec(
                name="soft_gate",
                kind=GateKind.SOFT,
                metric_name="soft_metric",
                comparison="ge",
                threshold=0.5,
            ),
            _evidence(metrics={"hard_metric": 0.1, "soft_metric": 1.0}),
        )

        verdict = compute_scene_verdict((hard, soft), route_qualified=True, route_id="route-1")

        assert verdict.verdict == "reject"

    def test_soft_gate_fails_with_no_hard_gate_fails_yields_review(self) -> None:
        hard = evaluate_gate(
            GateSpec(
                name="hard_gate",
                kind=GateKind.HARD,
                metric_name="hard_metric",
                comparison="ge",
                threshold=0.7,
            ),
            _evidence(metrics={"hard_metric": 0.9, "soft_metric": 0.1}),
        )
        soft = evaluate_gate(
            GateSpec(
                name="soft_gate",
                kind=GateKind.SOFT,
                metric_name="soft_metric",
                comparison="ge",
                threshold=0.5,
            ),
            _evidence(metrics={"hard_metric": 0.9, "soft_metric": 0.1}),
        )

        verdict = compute_scene_verdict((hard, soft), route_qualified=True, route_id="route-1")

        assert verdict.verdict == "review"

    def test_everything_applicable_passes_with_some_inapplicable_yields_accept(self) -> None:
        evidence = _evidence(
            is_synthetic=True,
            metrics={"hard_metric": 0.9, "route_only_metric": 0.9},
        )
        hard = evaluate_gate(
            GateSpec(
                name="hard_gate",
                kind=GateKind.HARD,
                metric_name="hard_metric",
                comparison="ge",
                threshold=0.7,
            ),
            evidence,
        )
        inapplicable_soft = evaluate_gate(
            GateSpec(
                name="route_only_gate",
                kind=GateKind.SOFT,
                metric_name="route_only_metric",
                comparison="ge",
                threshold=0.7,
                route_qualification_only=True,
            ),
            evidence,
        )
        assert inapplicable_soft.applicable is False

        verdict = compute_scene_verdict(
            (hard, inapplicable_soft), route_qualified=True, route_id="route-1"
        )

        assert verdict.verdict == "accept"

    def test_route_not_qualified_rejects_regardless_of_gate_results(self) -> None:
        passing_gate = evaluate_gate(
            GateSpec(
                name="hard_gate",
                kind=GateKind.HARD,
                metric_name="hard_metric",
                comparison="ge",
                threshold=0.1,
            ),
            _evidence(metrics={"hard_metric": 0.99}),
        )
        assert passing_gate.passed is True

        verdict = compute_scene_verdict((passing_gate,), route_qualified=False, route_id="route-1")

        assert verdict.verdict == "reject"
        assert "route" in verdict.reason.lower()


# ---------------------------------------------------------------------------
# Injectable clock
# ---------------------------------------------------------------------------


class TestInjectableClock:
    def test_compute_scene_verdict_uses_injected_clock(self) -> None:
        fixed = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)

        verdict = compute_scene_verdict(
            (), route_qualified=True, route_id="route-1", clock=lambda: fixed
        )

        assert verdict.computed_utc == fixed


# ---------------------------------------------------------------------------
# derive_scene_metrics
# ---------------------------------------------------------------------------


class TestDeriveSceneMetrics:
    def test_exact_values_on_hand_constructed_scenario(self) -> None:

        from selene_core.types import Covariance2D, CovarianceFrame

        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

        records = (
            # a rejected, non-candidate record: excluded from candidate-based metrics
            _record(is_candidate=False, is_inlier=False, point_role=PointRole.REJECTED),
            # two candidates, one inlier one not, for verified_inlier_fraction = 1/2
            _record(
                is_candidate=True,
                is_inlier=True,
                point_role=PointRole.FITTING_INLIER,
                covariance=cov,
                covariance_calibrated=True,
                estimator_disagreement_px=0.3,
            ),
            _record(is_candidate=True, is_inlier=False, point_role=PointRole.REJECTED),
            # an inlier with no covariance at all -> invalid_covariance_fraction
            _record(
                is_candidate=True,
                is_inlier=True,
                point_role=PointRole.FITTING_INLIER,
                covariance=None,
            ),
            # two withheld check points with usable residuals -> RMSE
            _record(
                is_candidate=True,
                point_role=PointRole.WITHHELD_CHECK_POINT,
                robust_model_residual_px=3.0,
            ),
            _record(
                is_candidate=True,
                point_role=PointRole.WITHHELD_CHECK_POINT,
                robust_model_residual_px=4.0,
            ),
        )
        per_cell = np.zeros((2, 2), dtype=np.int64)  # 4 total grid cells
        coverage = CoverageMetrics(
            eligible_cell_occupancy=0.75,
            convex_hull_to_eligible_area_ratio=None,
            largest_empty_run=1,
            per_cell_candidate_counts=per_cell,
        )

        metrics = derive_scene_metrics(records, coverage)

        assert metrics["eligible_occupancy"] == 0.75
        assert metrics["largest_empty_run_fraction"] == pytest.approx(1 / 4)
        # candidates: record2 (inlier), record3, record4 (inlier), and the two
        # withheld check points (candidates by construction, not inliers here) = 5
        # total; inliers among them = 2 (record2, record4) -> 2/5
        assert metrics["verified_inlier_fraction"] == pytest.approx(2 / 5)
        assert metrics["max_estimator_disagreement_px"] == pytest.approx(0.3)
        # inliers: two FITTING_INLIER records above (cov, no-cov); invalid = 1/2
        assert metrics["invalid_covariance_fraction"] == pytest.approx(1 / 2)
        assert metrics["uncalibrated_covariance_fraction"] == pytest.approx(0 / 2)
        # RMSE of [3.0, 4.0] = sqrt((9+16)/2) = sqrt(12.5)
        assert metrics["withheld_rmse_2d_px"] == pytest.approx((12.5) ** 0.5)

    def test_zero_candidates_yields_none_verified_inlier_fraction(self) -> None:

        records = (_record(is_candidate=False),)
        coverage = CoverageMetrics(
            eligible_cell_occupancy=0.0,
            convex_hull_to_eligible_area_ratio=None,
            largest_empty_run=0,
            per_cell_candidate_counts=np.zeros((2, 2), dtype=np.int64),
        )

        metrics = derive_scene_metrics(records, coverage)

        assert metrics["verified_inlier_fraction"] is None

    def test_zero_inliers_yields_none_covariance_fractions(self) -> None:

        records = (_record(is_candidate=True, is_inlier=False),)
        coverage = CoverageMetrics(
            eligible_cell_occupancy=0.0,
            convex_hull_to_eligible_area_ratio=None,
            largest_empty_run=0,
            per_cell_candidate_counts=np.zeros((2, 2), dtype=np.int64),
        )

        metrics = derive_scene_metrics(records, coverage)

        assert metrics["invalid_covariance_fraction"] is None
        assert metrics["uncalibrated_covariance_fraction"] is None

    def test_no_records_at_all_yields_none_max_estimator_disagreement(self) -> None:

        records: tuple[CorrespondenceRecord, ...] = ()
        coverage = CoverageMetrics(
            eligible_cell_occupancy=0.0,
            convex_hull_to_eligible_area_ratio=None,
            largest_empty_run=0,
            per_cell_candidate_counts=np.zeros((2, 2), dtype=np.int64),
        )

        metrics = derive_scene_metrics(records, coverage)

        assert metrics["max_estimator_disagreement_px"] is None
        assert metrics["withheld_rmse_2d_px"] is None


# ---------------------------------------------------------------------------
# GateResult applicable/applicability_reason pairing validator
# ---------------------------------------------------------------------------


class TestGateResultPairingValidator:
    def test_inapplicable_without_reason_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            GateResult(
                name="g",
                metric_name="m",
                observed_value=None,
                threshold=1.0,
                comparison="ge",
                kind=GateKind.HARD,
                applicable=False,
                applicability_reason=None,
                passed=None,
                evidence_source="scene_observed",
            )

    def test_applicable_with_reason_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            GateResult(
                name="g",
                metric_name="m",
                observed_value=1.0,
                threshold=1.0,
                comparison="ge",
                kind=GateKind.HARD,
                applicable=True,
                applicability_reason="should not be here",
                passed=True,
                evidence_source="scene_observed",
            )

    def test_applicable_with_passed_none_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            GateResult(
                name="g",
                metric_name="m",
                observed_value=1.0,
                threshold=1.0,
                comparison="ge",
                kind=GateKind.HARD,
                applicable=True,
                applicability_reason=None,
                passed=None,
                evidence_source="scene_observed",
            )

    def test_inapplicable_with_passed_not_none_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            GateResult(
                name="g",
                metric_name="m",
                observed_value=None,
                threshold=1.0,
                comparison="ge",
                kind=GateKind.HARD,
                applicable=False,
                applicability_reason="inapplicable for a reason",
                passed=False,
                evidence_source="scene_observed",
            )
