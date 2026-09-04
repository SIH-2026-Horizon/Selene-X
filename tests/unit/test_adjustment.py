"""Tests for the limited robust source-frame adjustment core (WP-08)."""

from __future__ import annotations

import numpy as np
import pytest

from selene_core.adjust import (
    AdjustmentInputError,
    AdjustmentOptions,
    AdjustmentParameter,
    AdjustmentParameterization,
    ObservationLinearization,
    ReductionPolicy,
    fit_adjustment,
    translation_only_parameterization,
)
from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.types import Covariance2D, CovarianceFrame, ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_INPUT_DIGEST = "1" * 64
_REFERENCE_DIGEST = "2" * 64
_PARAMETER_DIGEST = "3" * 64


def _record(
    record_id: str,
    *,
    role: PointRole = PointRole.FITTING_INLIER,
    line: float = 0.0,
    covariance: Covariance2D | None = None,
    calibrated: bool = True,
    include_default_covariance: bool = True,
) -> CorrespondenceRecord:
    return CorrespondenceRecord(
        match_id=record_id,
        job_id="adjustment-test",
        algorithm="synthetic",
        algorithm_version="1",
        source_pixel=SourcePixel(line=line, sample=line + 0.25),
        reference_pixel=ReferencePixel(line=line, sample=line + 0.25),
        raw_score=1.0,
        covariance=(
            covariance
            if covariance is not None
            else (
                Covariance2D.isotropic(0.1, CovarianceFrame.SOURCE_PIXEL)
                if include_default_covariance
                else None
            )
        ),
        covariance_calibrated=calibrated,
        is_candidate=True,
        is_inlier=role is PointRole.FITTING_INLIER,
        point_role=role,
        input_digest=_INPUT_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
        parameter_set_digest=_PARAMETER_DIGEST,
    )


def _observation(
    record_id: str,
    residual_yx_px: tuple[float, float],
    parameter_count: int = 2,
    design_matrix: np.ndarray | None = None,
) -> ObservationLinearization:
    return ObservationLinearization(
        observation_id=record_id,
        source_residual_yx_px=residual_yx_px,
        design_matrix_yx_by_parameter=(
            np.eye(2, parameter_count) if design_matrix is None else design_matrix
        ),
    )


def test_exact_known_translation_is_recovered() -> None:
    expected = (1.25, -0.75)
    records = tuple(_record(f"fit-{index}", line=float(index)) for index in range(4))
    observations = tuple(_observation(record.match_id, expected) for record in records)

    result = fit_adjustment(
        records,
        observations,
        translation_only_parameterization(),
        options=AdjustmentOptions(huber_delta=100.0),
    )

    assert result.accepted
    assert result.converged
    assert result.parameter_values == pytest.approx(expected, abs=1e-12)
    assert result.fitting_metrics.rmse_2d_px == pytest.approx(0.0, abs=1e-12)
    assert result.parameterization_used == translation_only_parameterization()
    assert result.physical_sensor_model_export_required is True


def test_conditional_information_inverse_is_not_presented_as_robust_covariance() -> None:
    record = _record("fit")

    result = fit_adjustment(
        (record,), (_observation("fit", (1.0, -2.0)),), translation_only_parameterization()
    )

    assert result.accepted
    assert result.parameter_covariance is None
    assert result.conditional_information_inverse is not None


def test_anisotropic_full_covariance_is_used_without_scalar_collapse() -> None:
    covariance_a = Covariance2D(
        xx=1.0, xy=0.9, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
    )
    covariance_b = Covariance2D(
        xx=4.0, xy=0.0, yy=0.25, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
    )
    records = (
        _record("a", covariance=covariance_a),
        _record("b", covariance=covariance_b),
    )
    observations = (_observation("a", (3.0, 0.0)), _observation("b", (0.0, 1.0)))

    result = fit_adjustment(
        records,
        observations,
        translation_only_parameterization(),
        options=AdjustmentOptions(huber_delta=100.0),
    )

    covariance_matrix_a = np.array([[1.0, 0.9], [0.9, 1.0]])
    covariance_matrix_b = np.array([[4.0, 0.0], [0.0, 0.25]])
    weight_a = np.linalg.inv(covariance_matrix_a)
    weight_b = np.linalg.inv(covariance_matrix_b)
    expected = np.linalg.solve(
        weight_a + weight_b,
        weight_a @ np.array((3.0, 0.0)) + weight_b @ np.array((0.0, 1.0)),
    )
    diagonal_expected = np.linalg.solve(
        np.diag(np.diag(weight_a)) + np.diag(np.diag(weight_b)),
        np.diag(np.diag(weight_a)) @ np.array((3.0, 0.0))
        + np.diag(np.diag(weight_b)) @ np.array((0.0, 1.0)),
    )

    assert result.accepted
    assert result.parameter_values == pytest.approx(tuple(expected), abs=1e-12)
    assert result.parameter_values != pytest.approx(tuple(diagonal_expected), abs=1e-3)


def test_huber_fit_resists_a_gross_outlier() -> None:
    expected = (1.5, -0.75)
    records = (*(_record(f"inlier-{index}") for index in range(7)), _record("outlier"))
    observations = (
        *(_observation(record.match_id, expected) for record in records[:-1]),
        _observation("outlier", (40.0, -25.0)),
    )

    result = fit_adjustment(
        records,
        observations,
        translation_only_parameterization(),
        options=AdjustmentOptions(huber_delta=1.5, max_iterations=50),
    )

    assert result.accepted
    assert result.parameter_values == pytest.approx(expected, abs=0.05)
    outlier = next(
        diagnostic
        for diagnostic in result.residual_diagnostics
        if diagnostic.record_id == "outlier"
    )
    assert outlier.robust_weight is not None
    assert outlier.robust_weight < 0.1


def test_extreme_finite_design_and_observation_scale_remains_solvable() -> None:
    record = _record("large")
    scale = 1e155
    observation = _observation(
        "large",
        (2.0 * scale, -3.0 * scale),
        design_matrix=scale * np.eye(2),
    )

    result = fit_adjustment((record,), (observation,), translation_only_parameterization())

    assert result.accepted
    assert result.parameter_values == pytest.approx((2.0, -3.0), abs=1e-12)
    assert result.rank == 2
    assert result.condition_number == pytest.approx(1.0, abs=1e-12)


def test_withheld_points_are_not_fit_and_are_reported_independently() -> None:
    records = (
        _record("fit-a"),
        _record("fit-b"),
        _record("check", role=PointRole.WITHHELD_CHECK_POINT),
    )
    observations = (
        _observation("fit-a", (1.0, -2.0)),
        _observation("fit-b", (1.0, -2.0)),
        _observation("check", (4.0, 2.0)),
    )

    result = fit_adjustment(records, observations, translation_only_parameterization())

    assert result.accepted
    assert result.parameter_values == pytest.approx((1.0, -2.0), abs=1e-12)
    assert result.fitting_metrics.independent is False
    assert result.withheld_metrics.independent is True
    assert result.withheld_metrics.count == 1
    assert result.withheld_metrics.rmse_y_px == pytest.approx(3.0)
    assert result.withheld_metrics.rmse_x_px == pytest.approx(4.0)
    assert result.withheld_metrics.rmse_2d_px == pytest.approx(5.0)


def test_rank_deficient_requested_model_is_rejected_by_default() -> None:
    parameterization = AdjustmentParameterization(
        parameters=(
            AdjustmentParameter("line_translation_px", "px"),
            AdjustmentParameter("sample_translation_px", "px"),
            AdjustmentParameter("line_drift_px_per_line", "px/line", optional=True),
        )
    )
    records = tuple(_record(f"fit-{index}") for index in range(3))
    design = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    observations = tuple(
        _observation(record.match_id, (1.0, -1.0), 3, design) for record in records
    )

    result = fit_adjustment(records, observations, parameterization)

    assert not result.accepted
    assert result.rejection_reason == "rank_deficient"
    assert result.parameter_values is None


def test_explicit_reduction_drops_only_optional_terms_and_records_why() -> None:
    parameterization = AdjustmentParameterization(
        parameters=(
            AdjustmentParameter("line_translation_px", "px"),
            AdjustmentParameter("sample_translation_px", "px"),
            AdjustmentParameter("line_drift_px_per_line", "px/line", optional=True),
        )
    )
    records = tuple(_record(f"fit-{index}") for index in range(3))
    design = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    observations = tuple(
        _observation(record.match_id, (1.0, -1.0), 3, design) for record in records
    )

    result = fit_adjustment(
        records,
        observations,
        parameterization,
        options=AdjustmentOptions(reduction_policy=ReductionPolicy.DROP_OPTIONAL_TERMS),
    )

    assert result.accepted
    assert result.parameter_values == pytest.approx((1.0, -1.0), abs=1e-12)
    assert result.reduction is not None
    assert result.reduction.dropped_parameter_names == ("line_drift_px_per_line",)
    assert result.parameterization_used is not None
    assert result.parameterization_used.parameter_names == (
        "line_translation_px",
        "sample_translation_px",
    )
    assert len(result.parameterization_attempts) == 2
    assert result.parameterization_attempts[0].parameter_names == (
        "line_translation_px",
        "sample_translation_px",
        "line_drift_px_per_line",
    )
    assert result.parameterization_attempts[0].rejection_reason == "rank_deficient"
    assert result.parameterization_attempts[1].parameter_names == (
        "line_translation_px",
        "sample_translation_px",
    )
    assert result.parameterization_attempts[1].rejection_reason is None


def test_reduction_never_fabricates_an_empty_parameterization() -> None:
    parameterization = AdjustmentParameterization(
        parameters=(AdjustmentParameter("optional_line_term", "px", optional=True),)
    )
    record = _record("fit")
    observation = _observation("fit", (1.0, 1.0), parameter_count=1, design_matrix=np.zeros((2, 1)))

    result = fit_adjustment(
        (record,),
        (observation,),
        parameterization,
        options=AdjustmentOptions(reduction_policy=ReductionPolicy.DROP_OPTIONAL_TERMS),
    )

    assert not result.accepted
    assert result.rejection_reason == "rank_deficient"
    assert result.reduction is None


@pytest.mark.parametrize("value", [True, 1.5, float("nan"), float("inf")])
def test_max_iterations_rejects_non_finite_or_non_integer_values(value: object) -> None:
    with pytest.raises(AdjustmentInputError, match="max_iterations"):
        AdjustmentOptions(max_iterations=value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "record, expected",
    [
        (_record("missing", calibrated=False, include_default_covariance=False), "missing"),
        (_record("uncalibrated", calibrated=False), "uncalibrated"),
    ],
)
def test_missing_or_uncalibrated_fitting_covariance_is_rejected(
    record: CorrespondenceRecord, expected: str
) -> None:

    with pytest.raises(AdjustmentInputError, match=expected):
        fit_adjustment(
            (record,),
            (_observation(record.match_id, (1.0, 2.0)),),
            translation_only_parameterization(),
        )


def test_duplicate_and_mismatched_observations_are_rejected() -> None:
    record = _record("duplicate")
    with pytest.raises(AdjustmentInputError, match="duplicate record ID"):
        fit_adjustment(
            (record, record),
            (_observation("duplicate", (0.0, 0.0)),),
            translation_only_parameterization(),
        )
    with pytest.raises(AdjustmentInputError, match="design_matrix_yx_by_parameter shape"):
        ObservationLinearization(
            observation_id="duplicate",
            source_residual_yx_px=(0.0, 0.0),
            design_matrix_yx_by_parameter=np.zeros((1, 2)),
        )
    with pytest.raises(AdjustmentInputError, match="missing observation IDs"):
        fit_adjustment((record,), (), translation_only_parameterization())
    with pytest.raises(AdjustmentInputError, match="duplicate observation ID"):
        fit_adjustment(
            (record,),
            (_observation("duplicate", (0.0, 0.0)), _observation("duplicate", (0.0, 0.0))),
            translation_only_parameterization(),
        )


def test_fitting_covariance_must_be_in_the_source_pixel_frame() -> None:
    record = _record(
        "wrong-frame",
        covariance=Covariance2D.isotropic(0.1, CovarianceFrame.REFERENCE_PIXEL),
    )

    with pytest.raises(AdjustmentInputError, match="source_pixel frame"):
        fit_adjustment(
            (record,),
            (_observation("wrong-frame", (0.0, 0.0)),),
            translation_only_parameterization(),
        )


def test_results_are_deterministic_for_fixed_inputs() -> None:
    records = tuple(_record(f"fit-{index}", line=float(index)) for index in range(4))
    observations = tuple(
        _observation(record.match_id, (0.5 + index, -0.5)) for index, record in enumerate(records)
    )
    options = AdjustmentOptions(huber_delta=1.5, max_iterations=20)

    first = fit_adjustment(
        records, observations, translation_only_parameterization(), options=options
    )
    second = fit_adjustment(
        records, observations, translation_only_parameterization(), options=options
    )

    assert first == second


def test_withheld_metrics_are_explicitly_unavailable_without_check_points() -> None:
    record = _record("fit")

    result = fit_adjustment(
        (record,), (_observation("fit", (1.0, 2.0)),), translation_only_parameterization()
    )

    assert result.accepted
    assert result.withheld_metrics.count == 0
    assert result.withheld_metrics.rmse_2d_px is None
    assert (
        result.withheld_metrics.unavailable_reason
        == "no withheld check-point records were supplied"
    )


def test_fit_never_mutates_records_or_observation_arrays() -> None:
    record = _record("fit")
    original_record = record.model_dump()
    design = np.eye(2)
    original_design = design.copy()
    observation = _observation("fit", (1.0, 2.0), design_matrix=design)

    result = fit_adjustment((record,), (observation,), translation_only_parameterization())

    assert result.accepted
    assert record.model_dump() == original_record
    assert np.array_equal(design, original_design)
