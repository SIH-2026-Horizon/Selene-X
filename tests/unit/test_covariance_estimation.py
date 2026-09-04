"""Tests for local-Hessian covariance estimation and empirical calibration (WP-08 tasks 4, 5)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from benchmarks.scripts.controlled_shift import generate_controlled_shift_fixture

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.refine.covariance import (
    NOMINAL_TWO_PARAMETER_1SIGMA_COVERAGE,
    CalibrationResult,
    apply_calibrated_covariance,
    calibrate_covariance_scale,
    estimate_hessian_covariance,
    estimate_residual_noise_variance,
)
from selene_core.refine.patch_refinement import extract_patch, refine_correspondence, refine_ecc
from selene_core.types import CovarianceFrame, ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_INPUT_DIGEST = "1" * 64
_REFERENCE_DIGEST = "2" * 64
_PARAMETER_DIGEST = "3" * 64
_UPSAMPLE_FACTOR = 20

# calibrate_covariance_scale's trial count. This is a genuine bootstrap-style
# statistical procedure (see the module docstring and the calibration test
# below), so its coverage fractions carry real sampling noise: with a true
# per-trial "success" probability p, the standard error of the observed
# fraction is sqrt(p(1-p)/n_trials) -- for p ~ 0.35-0.4 and n_trials=400,
# that is ~0.024 (2.4 percentage points), small enough for a meaningful
# before/after comparison while keeping this a `unit` test (~1.3s measured
# locally), not a `science`-marked long-running one.
_CALIBRATION_N_TRIALS = 400
_CALIBRATION_SEED = 42

# Pass-condition margin for the calibration test (see its own docstring for
# the exact condition and why this value). Chosen from development
# measurements: across 8 different seeds at these same shape/shift/noise_std
# parameters, calibration improved coverage in 7/8 cases (gap shrinking by
# 0.02-0.05) and, in the one case where the uncalibrated estimate was already
# almost exactly nominal (gap 0.0015), calibration made it very slightly
# worse (gap grew to 0.019, a 0.0175 regression) -- exactly the brief's
# documented "already close" exception. 0.05 comfortably covers that
# observed worst-case regression with margin to spare, without being so
# loose that a genuinely broken calibration (e.g. scale_factor with the
# wrong sign or magnitude) would still pass.
_CALIBRATION_COVERAGE_MARGIN = 0.05


def _record(
    *,
    source_pixel: SourcePixel,
    reference_pixel: ReferencePixel,
) -> CorrespondenceRecord:
    return CorrespondenceRecord(
        job_id="covariance-job",
        algorithm="ncc",
        algorithm_version="1.0",
        source_pixel=source_pixel,
        reference_pixel=reference_pixel,
        raw_score=1.0,
        is_candidate=True,
        point_role=PointRole.CANDIDATE,
        input_digest=_INPUT_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
        parameter_set_digest=_PARAMETER_DIGEST,
    )


# ---------------------------------------------------------------------------
# estimate_residual_noise_variance
# ---------------------------------------------------------------------------


def test_estimate_residual_noise_variance_zero_residual_is_exactly_zero() -> None:
    patch = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])

    assert estimate_residual_noise_variance(patch, patch) == 0.0


def test_estimate_residual_noise_variance_hand_computable_value_matches_exactly() -> None:
    template = np.zeros((2, 2))
    warped_reference = np.array([[1.0, -1.0], [2.0, -2.0]])
    # residual = template - warped_reference = [[-1, 1], [-2, 2]], mean 0.
    # sum of squares = 1 + 1 + 4 + 4 = 10; ddof=1 divides by (4 - 1) = 3.
    expected = 10.0 / 3.0

    result = estimate_residual_noise_variance(template, warped_reference)

    assert result == pytest.approx(expected, rel=1e-12)


def test_estimate_residual_noise_variance_shape_mismatch_raises_value_error() -> None:
    with pytest.raises(ValueError, match="must share a shape"):
        estimate_residual_noise_variance(np.zeros((3, 3)), np.zeros((3, 4)))


# ---------------------------------------------------------------------------
# estimate_hessian_covariance
# ---------------------------------------------------------------------------


def test_estimate_hessian_covariance_happy_path_matches_formula_on_a_real_normal_matrix() -> None:
    shape = (81, 81)
    dy_px, dx_px = 0.6, -0.3
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=501)
    base = (round(dy_px), round(dx_px))
    source_extraction = extract_patch(
        fixture.base_image, center=(40.0, 40.0), half_size=15, mask=None
    )
    reference_extraction = extract_patch(
        fixture.shifted_image,
        center=(40.0 + base[0], 40.0 + base[1]),
        half_size=15,
        mask=None,
    )
    assert source_extraction.patch is not None
    assert reference_extraction.patch is not None

    ecc_result = refine_ecc(
        source_extraction.patch,
        reference_extraction.patch,
        initial_shift_px=(float(base[0]), float(base[1])),
        max_iterations=25,
        convergence_threshold=1e-8,
    )
    assert ecc_result.converged
    # A well-conditioned Hessian is the precondition this happy-path test is
    # meant to exercise, not something to silently tolerate failing.
    assert np.linalg.cond(ecc_result.normal_matrix) < 100.0

    noise_variance = 1e-4
    covariance = estimate_hessian_covariance(
        ecc_result.normal_matrix, noise_variance=noise_variance, condition_number_limit=1e8
    )

    assert covariance is not None
    assert covariance.frame == CovarianceFrame.SOURCE_PIXEL
    assert covariance.units == "px2"
    expected_matrix = noise_variance * np.linalg.inv(ecc_result.normal_matrix)
    assert covariance.xx == pytest.approx(float(expected_matrix[0, 0]), rel=1e-9)
    assert covariance.yy == pytest.approx(float(expected_matrix[1, 1]), rel=1e-9)
    expected_xy = float(0.5 * (expected_matrix[0, 1] + expected_matrix[1, 0]))
    assert covariance.xy == pytest.approx(expected_xy, rel=1e-9)


def test_estimate_hessian_covariance_ill_conditioned_normal_matrix_is_rejected() -> None:
    # Deliberately near-singular: eigenvalues 1.0 and 1e-10, condition number
    # ~1e10, far beyond the 1e6 limit below.
    normal_matrix = np.array([[1.0, 0.0], [0.0, 1e-10]])

    result = estimate_hessian_covariance(
        normal_matrix, noise_variance=1e-4, condition_number_limit=1e6
    )

    assert result is None


def test_estimate_hessian_covariance_degenerate_result_returns_none_not_an_exception() -> None:
    # Symmetric and well-conditioned (condition number exactly 1.0 -- it
    # passes both the symmetry and condition-number checks), but indefinite:
    # its inverse times a positive noise_variance has yy <= 0, which
    # Covariance2D's own constructor must reject. This exercises the
    # constructor-ValueError-catching path specifically, distinct from the
    # condition-number rejection above.
    normal_matrix = np.array([[1.0, 0.0], [0.0, -1.0]])

    result = estimate_hessian_covariance(
        normal_matrix, noise_variance=1.0, condition_number_limit=1e8
    )

    assert result is None


# ---------------------------------------------------------------------------
# calibrate_covariance_scale
# ---------------------------------------------------------------------------


def test_calibrate_covariance_scale_improves_or_does_not_meaningfully_worsen_coverage() -> None:
    """See module-level `_CALIBRATION_N_TRIALS`/`_CALIBRATION_COVERAGE_MARGIN`
    for the trial count and margin, and why they were chosen.

    Exact pass condition: `scale_factor` is positive and finite, and
    `|calibrated_coverage - nominal| <= |empirical_coverage - nominal| +
    _CALIBRATION_COVERAGE_MARGIN` -- i.e. calibration is not required to
    strictly improve coverage (the brief explicitly allows "at least not
    meaningfully worse" when the uncalibrated estimate already happens to be
    close), but it may not regress by more than the documented margin.
    """
    result = calibrate_covariance_scale(
        shape=(81, 81),
        true_shift_px=(0.6, -0.3),
        noise_std=0.04,
        n_trials=_CALIBRATION_N_TRIALS,
        seed=_CALIBRATION_SEED,
        ecc_max_iterations=25,
        ecc_convergence_threshold=1e-8,
    )

    assert isinstance(result, CalibrationResult)
    assert result.n_trials == _CALIBRATION_N_TRIALS
    assert result.scale_factor > 0.0
    assert math.isfinite(result.scale_factor)

    uncalibrated_gap = abs(
        result.empirical_coverage_at_1sigma - NOMINAL_TWO_PARAMETER_1SIGMA_COVERAGE
    )
    calibrated_gap = abs(
        result.calibrated_coverage_at_1sigma - NOMINAL_TWO_PARAMETER_1SIGMA_COVERAGE
    )
    assert calibrated_gap <= uncalibrated_gap + _CALIBRATION_COVERAGE_MARGIN

    # With these fixed parameters, calibration is also known (from
    # development measurements) to genuinely improve coverage, not just stay
    # within the safety margin -- assert that stronger, specific fact too.
    assert calibrated_gap < uncalibrated_gap


def test_calibrate_covariance_scale_is_deterministic() -> None:
    shape = (81, 81)
    true_shift_px = (0.6, -0.3)
    noise_std = 0.04
    n_trials = 50
    seed = 7
    ecc_max_iterations = 25
    ecc_convergence_threshold = 1e-8

    first = calibrate_covariance_scale(
        shape=shape,
        true_shift_px=true_shift_px,
        noise_std=noise_std,
        n_trials=n_trials,
        seed=seed,
        ecc_max_iterations=ecc_max_iterations,
        ecc_convergence_threshold=ecc_convergence_threshold,
    )
    second = calibrate_covariance_scale(
        shape=shape,
        true_shift_px=true_shift_px,
        noise_std=noise_std,
        n_trials=n_trials,
        seed=seed,
        ecc_max_iterations=ecc_max_iterations,
        ecc_convergence_threshold=ecc_convergence_threshold,
    )

    assert first == second


# ---------------------------------------------------------------------------
# apply_calibrated_covariance
# ---------------------------------------------------------------------------


def _well_conditioned_normal_matrix() -> np.ndarray:
    return np.array([[4.0, 0.5], [0.5, 3.0]])


def test_apply_calibrated_covariance_without_calibration_returns_raw_uncalibrated() -> None:
    normal_matrix = _well_conditioned_normal_matrix()
    noise_variance = 1e-4

    covariance, is_calibrated = apply_calibrated_covariance(
        normal_matrix,
        noise_variance=noise_variance,
        condition_number_limit=1e8,
        calibration=None,
    )

    assert covariance is not None
    assert is_calibrated is False
    expected_matrix = noise_variance * np.linalg.inv(normal_matrix)
    assert covariance.xx == pytest.approx(float(expected_matrix[0, 0]), rel=1e-9)
    assert covariance.yy == pytest.approx(float(expected_matrix[1, 1]), rel=1e-9)


def test_apply_calibrated_covariance_with_calibration_scales_raw_covariance_exactly() -> None:
    normal_matrix = _well_conditioned_normal_matrix()
    noise_variance = 1e-4
    calibration = CalibrationResult(
        scale_factor=2.5,
        n_trials=100,
        empirical_coverage_at_1sigma=0.3,
        calibrated_coverage_at_1sigma=0.39,
    )

    raw_covariance, _raw_is_calibrated = apply_calibrated_covariance(
        normal_matrix,
        noise_variance=noise_variance,
        condition_number_limit=1e8,
        calibration=None,
    )
    scaled_covariance, is_calibrated = apply_calibrated_covariance(
        normal_matrix,
        noise_variance=noise_variance,
        condition_number_limit=1e8,
        calibration=calibration,
    )

    assert raw_covariance is not None
    assert scaled_covariance is not None
    assert is_calibrated is True
    assert scaled_covariance.xx == pytest.approx(raw_covariance.xx * 2.5, rel=1e-12)
    assert scaled_covariance.yy == pytest.approx(raw_covariance.yy * 2.5, rel=1e-12)
    assert scaled_covariance.xy == pytest.approx(raw_covariance.xy * 2.5, rel=1e-12)


def test_apply_calibrated_covariance_degenerate_normal_matrix_returns_none_regardless() -> None:
    # Same indefinite-but-well-conditioned matrix as the estimate_hessian_covariance
    # degenerate-result test above.
    normal_matrix = np.array([[1.0, 0.0], [0.0, -1.0]])
    calibration = CalibrationResult(
        scale_factor=2.0,
        n_trials=10,
        empirical_coverage_at_1sigma=0.3,
        calibrated_coverage_at_1sigma=0.35,
    )

    without_calibration = apply_calibrated_covariance(
        normal_matrix, noise_variance=1.0, condition_number_limit=1e8, calibration=None
    )
    with_calibration = apply_calibrated_covariance(
        normal_matrix, noise_variance=1.0, condition_number_limit=1e8, calibration=calibration
    )

    assert without_calibration == (None, False)
    assert with_calibration == (None, False)


# ---------------------------------------------------------------------------
# refine_correspondence extended (covariance) behaviour
# ---------------------------------------------------------------------------


def test_refine_correspondence_with_noise_variance_populates_a_real_covariance() -> None:
    shape = (121, 121)
    dy_px, dx_px = 1.7, -0.4
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=401)
    base = (round(dy_px), round(dx_px))
    source_pixel = SourcePixel(line=60.0, sample=60.0)
    reference_pixel = ReferencePixel(line=60.0 + base[0], sample=60.0 + base[1])
    record = _record(source_pixel=source_pixel, reference_pixel=reference_pixel)

    refined = refine_correspondence(
        record,
        fixture.base_image,
        fixture.shifted_image,
        source_mask=None,
        reference_mask=None,
        patch_half_size=20,
        ecc_max_iterations=50,
        ecc_convergence_threshold=1e-8,
        fourier_upsample_factor=_UPSAMPLE_FACTOR,
        min_patch_texture=1e-6,
        noise_variance=1e-4,
    )

    assert refined.rejection_reason is None
    assert refined.covariance is not None
    assert refined.covariance.frame == CovarianceFrame.SOURCE_PIXEL
    assert refined.covariance.units == "px2"
    assert refined.covariance_method == "ecc_local_hessian"
    assert refined.covariance_calibrated is False  # no calibration was passed


def test_refine_correspondence_with_noise_variance_and_calibration_reports_calibrated() -> None:
    shape = (121, 121)
    dy_px, dx_px = 1.7, -0.4
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=401)
    base = (round(dy_px), round(dx_px))
    source_pixel = SourcePixel(line=60.0, sample=60.0)
    reference_pixel = ReferencePixel(line=60.0 + base[0], sample=60.0 + base[1])
    record = _record(source_pixel=source_pixel, reference_pixel=reference_pixel)
    calibration = CalibrationResult(
        scale_factor=1.5,
        n_trials=100,
        empirical_coverage_at_1sigma=0.3,
        calibrated_coverage_at_1sigma=0.39,
    )

    uncalibrated = refine_correspondence(
        record,
        fixture.base_image,
        fixture.shifted_image,
        source_mask=None,
        reference_mask=None,
        patch_half_size=20,
        ecc_max_iterations=50,
        ecc_convergence_threshold=1e-8,
        fourier_upsample_factor=_UPSAMPLE_FACTOR,
        min_patch_texture=1e-6,
        noise_variance=1e-4,
    )
    calibrated = refine_correspondence(
        record,
        fixture.base_image,
        fixture.shifted_image,
        source_mask=None,
        reference_mask=None,
        patch_half_size=20,
        ecc_max_iterations=50,
        ecc_convergence_threshold=1e-8,
        fourier_upsample_factor=_UPSAMPLE_FACTOR,
        min_patch_texture=1e-6,
        noise_variance=1e-4,
        calibration=calibration,
    )

    assert uncalibrated.covariance is not None
    assert calibrated.covariance is not None
    assert calibrated.covariance_calibrated is True
    assert calibrated.covariance.xx == pytest.approx(uncalibrated.covariance.xx * 1.5, rel=1e-9)
    assert calibrated.covariance.yy == pytest.approx(uncalibrated.covariance.yy * 1.5, rel=1e-9)


def test_refine_correspondence_without_noise_variance_matches_task_17_behaviour_exactly() -> None:
    """Strictly additive check: every field Task 17's own equivalent happy-path
    test asserts must match exactly when `noise_variance` is omitted, and the
    new covariance fields must be at their Task-17-era defaults.
    """
    shape = (121, 121)
    dy_px, dx_px = 1.7, -0.4
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=401)
    base = (round(dy_px), round(dx_px))
    source_pixel = SourcePixel(line=60.0, sample=60.0)
    reference_pixel = ReferencePixel(line=60.0 + base[0], sample=60.0 + base[1])
    record = _record(source_pixel=source_pixel, reference_pixel=reference_pixel)

    refined = refine_correspondence(
        record,
        fixture.base_image,
        fixture.shifted_image,
        source_mask=None,
        reference_mask=None,
        patch_half_size=20,
        ecc_max_iterations=50,
        ecc_convergence_threshold=1e-8,
        fourier_upsample_factor=_UPSAMPLE_FACTOR,
        min_patch_texture=1e-6,
    )

    # Task 17's own non-covariance assertions, unchanged (see
    # test_refine_correspondence_happy_path_recovers_true_shift in
    # test_patch_refinement.py).
    assert refined.coarse_location == source_pixel
    assert refined.refined_location is not None
    true_line = 60.0 + dy_px
    true_sample = 60.0 + dx_px
    assert (
        np.hypot(
            refined.refined_location.line - true_line, refined.refined_location.sample - true_sample
        )
        < 0.1
    )
    assert refined.estimator_identities == ("ecc_inverse_compositional", "fourier_upsampled")
    assert refined.estimator_disagreement_px is not None
    assert refined.estimator_disagreement_px < 0.2
    assert refined.rejection_reason is None

    # The strictly additive part: covariance fields stay at their defaults.
    assert refined.covariance is None
    assert refined.covariance_calibrated is False
    assert refined.covariance_method is None
