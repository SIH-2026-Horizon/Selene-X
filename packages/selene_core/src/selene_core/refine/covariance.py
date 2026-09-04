"""Local-Hessian positional covariance and its empirical calibration (WP-08 tasks 4, 5).

:mod:`selene_core.refine.patch_refinement`'s :func:`~selene_core.refine.
patch_refinement.refine_ecc` already derives, each iteration, the 2x2
Gauss-Newton normal matrix ``normal_matrix = H - c c^T`` (see that function's
docstring) that its update step solves against. At convergence, that matrix
*is* the local curvature of the ECC objective around the returned shift: a
well-conditioned, strongly-peaked normal matrix means the objective curves
sharply in every direction near the optimum (a tightly-constrained match), and
a weak or singular one means some direction is nearly flat (an
under-constrained match, most often a one-dimensional edge/line feature that
pins one axis but not the other).

**The formula and its assumption.** The classic Gauss-Newton asymptotic
covariance of a least-squares estimate is
``covariance = sigma^2 * inverse(J^T J)``, where ``J`` is the residual
Jacobian and ``sigma^2`` is the variance of the (assumed i.i.d., zero-mean)
residual noise. Here ``J^T J`` is exactly ``normal_matrix`` (see
``refine_ecc``'s derivation), so :func:`estimate_hessian_covariance` computes
``noise_variance * inverse(normal_matrix)``. This is only as good as its
assumption: the residual (``template - warped_reference`` at the converged
shift) must be well-approximated as independent, identically-distributed
noise near the optimum, not leftover structured signal from a bad match. That
is exactly why :func:`estimate_residual_noise_variance` is defined to consume
the *converged* residual (where, for a genuinely good match, structured
signal should have been squeezed out and only sensor/photometric noise
remains) rather than some a priori guess about sensor noise.

**Calibration.** The Hessian-based estimate above is a first-order asymptotic
approximation; nothing here proves it is unbiased or correctly scaled for
this project's actual patches, textures, and noise levels.
:func:`calibrate_covariance_scale` checks it empirically: it runs many
independent noisy trials of a *known* controlled shift through
:func:`~selene_core.refine.patch_refinement.refine_ecc`, compares the
analytic covariance's spread against the errors' *actual* observed scatter,
and reports a single multiplicative correction plus the before/after coverage
data a reliability diagram would plot (the underlying data, not a rendered
plot -- this is a numpy library, not a UI).

**Rejection, not fabrication.** Per WP-08 task 5, a covariance that would be
non-positive-definite (or that rests on a too-ill-conditioned Hessian) is
never forced to look valid. :class:`~selene_core.types.Covariance2D` already
enforces positive-definiteness at construction (its own docstring names this
as WP-08 task 5) -- this module never reimplements that check, it only
catches the ``ValueError`` :class:`~selene_core.types.Covariance2D` raises and
returns ``None``, so a degenerate estimate is an honest, typed absence, not
an exception every caller must remember to catch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from selene_core.types import Covariance2D, CovarianceFrame

__all__ = [
    "CalibrationResult",
    "apply_calibrated_covariance",
    "calibrate_covariance_scale",
    "estimate_hessian_covariance",
    "estimate_residual_noise_variance",
]

# Symmetry tolerance for the normal_matrix rejection check in
# estimate_hessian_covariance. normal_matrix = hessian - outer(c, c) is
# symmetric by construction (both hessian = G^T G and outer(c, c) are
# symmetric), so any real caller's matrix should satisfy this to within
# ordinary float64 rounding error; a matrix that fails it is not this
# module's normal_matrix at all (a caller error), not a borderline case.
_SYMMETRY_ATOL = 1e-8
_SYMMETRY_RTOL = 1e-5

# Default condition-number ceiling used internally by calibrate_covariance_scale
# when it needs *a* covariance to calibrate against, mirroring
# refine_correspondence's own default (see that function's docstring for the
# float64-precision justification). calibrate_covariance_scale has no
# condition_number_limit parameter of its own (see its docstring), so this is
# the one value it uses.
_DEFAULT_CONDITION_NUMBER_LIMIT = 1e8

# The nominal fraction of samples from a 2-D Gaussian that fall
# within their own 1-sigma (Mahalanobis distance <= 1) ellipse:
# P(chi2_2 <= 1) = 1 - exp(-1/2) ~= 0.3935. Documented here once; the
# calibration test compares both coverage fractions against this same value.
NOMINAL_TWO_PARAMETER_1SIGMA_COVERAGE: float = 1.0 - math.exp(-0.5)


def estimate_residual_noise_variance(
    template: npt.NDArray[np.float64],
    warped_reference: npt.NDArray[np.float64],
) -> float:
    """Sample variance of ``template - warped_reference``, a pixel-noise proxy.

    Both arrays are assumed already aligned -- ``warped_reference`` is the
    reference patch resampled at the estimator's converged shift, not the raw
    unaligned reference. After good alignment the residual should be close to
    sensor/photometric noise, not leftover signal, which is the assumption
    :func:`estimate_hessian_covariance`'s Gauss-Newton covariance formula
    depends on (see the module docstring).

    Uses ``numpy.var`` with ``ddof=1`` (the unbiased sample-variance
    estimator: dividing by ``n - 1`` rather than ``n``, appropriate here
    because the residual's own mean is estimated from the same sample, not
    assumed to be exactly zero a priori).

    Args:
        template: The fixed template patch/image.
        warped_reference: The reference patch/image resampled to align with
            ``template``. Must share ``template``'s shape.

    Returns:
        The scalar sample variance of the pixelwise residual.

    Raises:
        ValueError: If ``template`` and ``warped_reference`` do not share a
            shape.
    """
    if template.shape != warped_reference.shape:
        raise ValueError(
            "estimate_residual_noise_variance: template and warped_reference must share a "
            f"shape, got {template.shape!r} and {warped_reference.shape!r}"
        )
    residual = template - warped_reference
    return float(np.var(residual, ddof=1))


def estimate_hessian_covariance(
    normal_matrix: npt.NDArray[np.float64],
    *,
    noise_variance: float,
    condition_number_limit: float,
) -> Covariance2D | None:
    """Cramer-Rao-like positional covariance from a converged ECC normal matrix.

    ``covariance = noise_variance * inverse(normal_matrix)`` (the standard
    Gauss-Newton asymptotic covariance; see the module docstring for the
    derivation and the i.i.d.-residual-noise assumption it rests on).

    Three ways this legitimately reports "cannot estimate" as ``None`` rather
    than a fabricated number, all first-class outcomes, not error conditions:

    1. ``normal_matrix`` is not symmetric within floating-point tolerance --
       it is not a genuine ``H - c c^T`` normal matrix (a caller error, most
       likely passing the wrong array), so trusting its inverse would be
       trusting a shape it should never have.
    2. ``normal_matrix``'s condition number exceeds ``condition_number_limit``
       -- an ill-conditioned Hessian means the objective's curvature is too
       weak in some direction to trust (WP-08 task 5's "directionally weak"
       case). Inverting it anyway would report a huge but technically
       computed variance along that direction as if it were a trustworthy
       measurement, which is exactly the fabrication this function must not
       do.
    3. The resulting ``xx``/``yy``/determinant would fail
       :class:`~selene_core.types.Covariance2D`'s own positive-definiteness
       checks -- caught here as a plain ``ValueError`` from its constructor,
       not reimplemented.

    Args:
        normal_matrix: The ``(2, 2)`` Gauss-Newton normal matrix from
            :func:`~selene_core.refine.patch_refinement.refine_ecc`'s
            ``EccRefinementResult.normal_matrix``.
        noise_variance: The residual noise variance, typically from
            :func:`estimate_residual_noise_variance`.
        condition_number_limit: The maximum tolerable
            ``numpy.linalg.cond(normal_matrix)`` (2-norm condition number,
            numpy's default) before the Hessian is rejected as too
            directionally weak to trust.

    Returns:
        A :class:`~selene_core.types.Covariance2D` in
        ``CovarianceFrame.SOURCE_PIXEL`` with ``units="px2"``, or ``None`` if
        the estimate could not be trusted for any of the three reasons above.

    Raises:
        ValueError: If ``normal_matrix`` is not a ``(2, 2)`` array. This is a
            caller-contract violation (the wrong array was passed), distinct
            from the three legitimate-but-degenerate cases above that return
            ``None``.
    """
    if normal_matrix.shape != (2, 2):
        raise ValueError(
            f"estimate_hessian_covariance: normal_matrix must be (2, 2), got "
            f"{normal_matrix.shape!r}"
        )
    if not np.allclose(normal_matrix, normal_matrix.T, atol=_SYMMETRY_ATOL, rtol=_SYMMETRY_RTOL):
        return None

    condition_number = float(np.linalg.cond(normal_matrix))
    if not math.isfinite(condition_number) or condition_number > condition_number_limit:
        return None

    try:
        inverse_normal_matrix = np.linalg.inv(normal_matrix)
    except np.linalg.LinAlgError:
        return None

    covariance_matrix = noise_variance * inverse_normal_matrix
    # normal_matrix passed the symmetry check above only up to floating-point
    # tolerance, so its inverse's off-diagonal pair can differ by a similar
    # tiny amount; averaging them is the natural symmetric estimate rather
    # than arbitrarily preferring one triangle over the other.
    xy = float(0.5 * (covariance_matrix[0, 1] + covariance_matrix[1, 0]))

    try:
        return Covariance2D(
            xx=float(covariance_matrix[0, 0]),
            xy=xy,
            yy=float(covariance_matrix[1, 1]),
            frame=CovarianceFrame.SOURCE_PIXEL,
            units="px2",
        )
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """The outcome of one :func:`calibrate_covariance_scale` run.

    ``empirical_coverage_at_1sigma``/``calibrated_coverage_at_1sigma`` are
    the "before"/"after" data points a reliability diagram would plot: the
    fraction of independent trials whose true error actually fell within the
    analytically-predicted 1-sigma (Mahalanobis distance <= 1) ellipse,
    before and after applying ``scale_factor``. WP-08 task 4's "reliability
    diagrams" are scoped to exactly this underlying data, not a rendered
    plot.
    """

    scale_factor: float
    """Multiplicative correction applied to a raw Hessian-based covariance so
    that it matches the empirically observed scatter (see
    :func:`calibrate_covariance_scale` for exactly how this is computed, and
    the isotropic-correction simplification it documents)."""

    n_trials: int
    """Number of independent noisy trials the calibration was run over."""

    empirical_coverage_at_1sigma: float
    """Fraction of trials whose true error fell within the uncalibrated
    analytic covariance's 1-sigma ellipse."""

    calibrated_coverage_at_1sigma: float
    """Fraction of trials whose true error fell within ``scale_factor`` times
    the analytic covariance's 1-sigma ellipse. Not guaranteed to exactly hit
    :data:`NOMINAL_TWO_PARAMETER_1SIGMA_COVERAGE` (~0.393), only to be a
    legitimate empirical measurement -- the comparison between the two
    coverage fields is the reliability check, not a precise target."""


def _fraction_within_mahalanobis(
    errors: npt.NDArray[np.float64], covariance_matrix: npt.NDArray[np.float64]
) -> float:
    """Fraction of ``errors`` rows with squared Mahalanobis distance <= 1.

    ``errors`` is ``(n_trials, 2)``; ``covariance_matrix`` is the ``(2, 2)``
    covariance defining the ellipse. Uses the *actual* covariance matrix
    (including any off-diagonal correlation), not axis-aligned variances --
    ``distance_sq[i] = errors[i] @ inverse(covariance_matrix) @ errors[i]``,
    vectorized across all trials at once.
    """
    inverse_covariance = np.linalg.inv(covariance_matrix)
    distance_sq = np.einsum("ij,jk,ik->i", errors, inverse_covariance, errors)
    return float(np.mean(distance_sq <= 1.0))


def _patch_half_size(shape: tuple[int, int], base_offset: tuple[int, int]) -> int:
    """Largest patch half-size that keeps both extracted crops inside ``shape``.

    The source crop is centred at ``shape``'s own centre; the reference crop
    is centred ``base_offset`` pixels away from it (see
    :func:`calibrate_covariance_scale`). Both must stay inside ``shape``, so
    the usable half-size is reduced by the offset magnitude plus one pixel
    of slack.
    """
    margin = max(abs(base_offset[0]), abs(base_offset[1])) + 1
    return min(shape[0], shape[1]) // 2 - margin


def calibrate_covariance_scale(
    *,
    shape: tuple[int, int],
    true_shift_px: tuple[float, float],
    noise_std: float,
    n_trials: int,
    seed: int,
    ecc_max_iterations: int,
    ecc_convergence_threshold: float,
) -> CalibrationResult:
    """Empirically calibrate the Hessian covariance's scale against true error.

    Procedure (WP-08 task 4's "controlled shifts, bootstrap/perturbation
    tests, and reliability diagrams", scoped to its underlying numeric data):

    1. Build one fixed base pattern
       (``benchmarks.scripts.controlled_shift.generate_base_pattern``, of
       size ``shape``) and its exact ``true_shift_px``-shifted copy
       (``benchmarks.scripts.controlled_shift.shift_image``), once.
    2. For each of ``n_trials`` independent trials: add i.i.d.
       ``Normal(0, noise_std)`` noise to the base pattern AND, separately, to
       the shifted copy -- two independent draws from a per-trial
       :class:`numpy.random.Generator` (``numpy.random.default_rng(seed)
       .spawn(n_trials)``, which gives each trial its own independent bit
       stream, and each trial two independent ``.normal(...)`` calls off
       that stream) -- since real sensor noise on two different images is
       independent, and reusing one noise draw for both patches would make
       ``refine_ecc``'s recovered shift artificially exact by construction.

       From the two noisy images, extract a template/reference PATCH PAIR
       using ``refine_ecc``'s own established seeding convention (the same
       one ``patch_refinement.refine_correspondence`` and its tests use): the
       template patch is cropped from the noisy base pattern at ``shape``'s
       centre, and the reference patch is cropped from the noisy shifted copy
       at that same centre plus ``round(true_shift_px)`` -- so the two crops'
       own local grids already differ by the integer part of the shift, and
       only the small sub-pixel remainder needs iterative refinement. Passing
       the two RAW (uncropped) noisy images directly to ``refine_ecc`` with
       ``initial_shift_px=round(true_shift_px)`` would be wrong: with no
       actual crop-level offset baked into the arrays, ``refine_ecc`` would
       still only ever search a small residual around zero (see
       ``refine_ecc``'s derivation -- the loop only ever applies ``residual``,
       never ``base``, to the array it warps), while the two raw images
       actually differ by the FULL ``true_shift_px``, not just its fractional
       part; ``refine_ecc`` would silently converge to the wrong answer,
       offset by whole integer pixels. This was caught during development by
       comparing a manual re-implementation of ``refine_ecc``'s iteration
       against its actual output on raw, uncropped images and finding a
       systematic 1-pixel-scale discrepancy -- the fix is this patch
       extraction step, matching the module's real, tested seeding
       convention exactly.

       Run ``refine_ecc`` from ``initial_shift_px=round(true_shift_px)`` on
       that patch pair to get a refined shift and a ``normal_matrix``.
    3. Collect all ``n_trials`` errors (``refined_shift_px - true_shift_px``)
       as an ``(n_trials, 2)`` array, and the empirical residual noise
       variance of each trial's converged alignment (via
       :func:`estimate_residual_noise_variance`, using
       ``benchmarks.scripts.controlled_shift.shift_image`` to resample the
       reference patch by the converged sub-pixel residual so it aligns with
       the template patch).
    4. Compute ONE representative analytic covariance
       (:func:`estimate_hessian_covariance`) from the *average* normal
       matrix and *average* noise variance across all ``n_trials`` trials
       (not a per-trial covariance -- see the note below), and the empirical
       ``(2, 2)`` covariance of the errors themselves (``numpy.cov``,
       ``rowvar=False, ddof=1``).
    5. ``scale_factor`` is the ratio of the empirical covariance's trace to
       the analytic covariance's trace -- a simple, well-defined, and
       honestly approximate choice. This is a real simplification, stated
       plainly rather than implied away: it is an *isotropic* correction
       applied uniformly to an otherwise-anisotropic estimate (both axes get
       the same multiplicative correction), not a fully separate per-axis
       recalibration.
    6. Both coverage fractions use that SAME single representative analytic
       covariance for every trial's Mahalanobis check (not a per-trial
       analytic covariance) -- only each trial's own *error vector* differs.
       This function documents and uses this single-representative choice
       throughout (the module's docstring allows either; this is the one
       actually implemented here), for the same reason ``scale_factor``
       itself is one aggregate number: it keeps "the representative analytic
       covariance" one unambiguous thing across the whole calibration run.

    Args:
        shape: ``(height, width)`` of the synthetic base pattern. Must be
            large enough that a patch half-size of at least 1 remains after
            reserving room for ``round(true_shift_px)`` (see
            :func:`_patch_half_size`); a caller passing too small a ``shape``
            for the requested shift gets an explicit ``ValueError``, not a
            truncated or wrapped-around patch.
        true_shift_px: The exact ``(dy_px, dx_px)`` ground-truth shift.
        noise_std: Standard deviation of the i.i.d. Gaussian noise added
            independently to each trial's base and shifted-reference copy.
        n_trials: Number of independent trials. Must be large enough that a
            coverage-fraction claim is statistically meaningful; per the
            task brief this is the caller's explicit choice, not something
            silently guarded against here.
        seed: Seed for the base pattern's own noise texture AND (via
            ``numpy.random.default_rng(seed).spawn(n_trials)``) the
            per-trial calibration noise. Fully determines the result.
        ecc_max_iterations: Forwarded to ``refine_ecc``.
        ecc_convergence_threshold: Forwarded to ``refine_ecc``.

    Returns:
        A :class:`CalibrationResult`.

    Raises:
        ValueError: If ``shape`` leaves no room for a patch half-size of at
            least 1 pixel once ``round(true_shift_px)`` is reserved, or if
            the averaged normal matrix/noise variance across all trials does
            not yield a usable analytic covariance (ill conditioned or
            non-positive-definite) -- the calibration cannot proceed without
            either, so both are reported loudly rather than silently
            producing a meaningless ``CalibrationResult``.
    """
    # Local import: avoids a module-load-time circular import with
    # patch_refinement.py, which imports this module's apply_calibrated_covariance
    # for refine_correspondence's optional covariance path.
    from benchmarks.scripts.controlled_shift import generate_base_pattern, shift_image

    from selene_core.refine.patch_refinement import extract_patch, refine_ecc

    base_offset = (round(true_shift_px[0]), round(true_shift_px[1]))
    half_size = _patch_half_size(shape, base_offset)
    if half_size < 1:
        raise ValueError(
            f"calibrate_covariance_scale: shape {shape!r} is too small to fit a patch pair "
            f"offset by round(true_shift_px)={base_offset!r} -- use a larger shape"
        )
    center = (shape[0] // 2, shape[1] // 2)
    reference_center = (center[0] + base_offset[0], center[1] + base_offset[1])
    initial_shift_px = (float(base_offset[0]), float(base_offset[1]))

    base_pattern = generate_base_pattern(shape, seed=seed)
    true_shifted_reference = shift_image(
        base_pattern, dy_px=true_shift_px[0], dx_px=true_shift_px[1]
    )

    trial_rngs = np.random.default_rng(seed).spawn(n_trials)

    errors = np.empty((n_trials, 2), dtype=np.float64)
    normal_matrices = np.empty((n_trials, 2, 2), dtype=np.float64)
    noise_variances = np.empty(n_trials, dtype=np.float64)

    for trial_index, trial_rng in enumerate(trial_rngs):
        # Two independent draws from this trial's own stream: independent
        # noise realizations for the two different "images" (base vs.
        # shifted reference), matching real independent sensor noise.
        noisy_base = base_pattern + trial_rng.normal(loc=0.0, scale=noise_std, size=shape)
        noisy_reference = true_shifted_reference + trial_rng.normal(
            loc=0.0, scale=noise_std, size=shape
        )

        source_extraction = extract_patch(noisy_base, center=center, half_size=half_size, mask=None)
        reference_extraction = extract_patch(
            noisy_reference, center=reference_center, half_size=half_size, mask=None
        )
        assert source_extraction.patch is not None  # noqa: S101 - guaranteed by half_size check
        assert reference_extraction.patch is not None  # noqa: S101 - guaranteed by half_size check
        source_patch = source_extraction.patch
        reference_patch = reference_extraction.patch

        ecc_result = refine_ecc(
            source_patch,
            reference_patch,
            initial_shift_px=initial_shift_px,
            max_iterations=ecc_max_iterations,
            convergence_threshold=ecc_convergence_threshold,
        )
        errors[trial_index, 0] = ecc_result.refined_shift_px[0] - true_shift_px[0]
        errors[trial_index, 1] = ecc_result.refined_shift_px[1] - true_shift_px[1]
        normal_matrices[trial_index] = ecc_result.normal_matrix

        # Align reference_patch with source_patch by the converged SUB-PIXEL
        # residual only (refined_shift_px minus the integer base already
        # baked into reference_center's crop offset) -- not the full
        # refined_shift_px, which would double-count that integer part.
        residual_dy = ecc_result.refined_shift_px[0] - base_offset[0]
        residual_dx = ecc_result.refined_shift_px[1] - base_offset[1]
        aligned_reference_patch = shift_image(
            reference_patch, dy_px=-residual_dy, dx_px=-residual_dx
        )
        noise_variances[trial_index] = estimate_residual_noise_variance(
            source_patch, aligned_reference_patch
        )

    mean_normal_matrix = normal_matrices.mean(axis=0)
    mean_noise_variance = float(noise_variances.mean())

    analytic_covariance = estimate_hessian_covariance(
        mean_normal_matrix,
        noise_variance=mean_noise_variance,
        condition_number_limit=_DEFAULT_CONDITION_NUMBER_LIMIT,
    )
    if analytic_covariance is None:
        raise ValueError(
            "calibrate_covariance_scale: the averaged normal_matrix/noise_variance across "
            f"{n_trials} trials did not yield a usable analytic covariance (ill-conditioned "
            "or non-positive-definite); calibration cannot proceed without one"
        )

    analytic_matrix = np.array(
        [
            [analytic_covariance.xx, analytic_covariance.xy],
            [analytic_covariance.xy, analytic_covariance.yy],
        ],
        dtype=np.float64,
    )
    empirical_matrix = np.cov(errors, rowvar=False, ddof=1)

    scale_factor = float(np.trace(empirical_matrix) / np.trace(analytic_matrix))
    calibrated_matrix = scale_factor * analytic_matrix

    empirical_coverage = _fraction_within_mahalanobis(errors, analytic_matrix)
    calibrated_coverage = _fraction_within_mahalanobis(errors, calibrated_matrix)

    return CalibrationResult(
        scale_factor=scale_factor,
        n_trials=n_trials,
        empirical_coverage_at_1sigma=empirical_coverage,
        calibrated_coverage_at_1sigma=calibrated_coverage,
    )


def apply_calibrated_covariance(
    normal_matrix: npt.NDArray[np.float64],
    *,
    noise_variance: float,
    condition_number_limit: float,
    calibration: CalibrationResult | None,
) -> tuple[Covariance2D | None, bool]:
    """Raw or calibrated Hessian covariance, plus whether it is calibrated.

    This is the direct implementation of WP-08 task 5's "retain an otherwise
    valid match only with ``covariance_status = uncalibrated``" -- this
    project's actual field for that status is
    ``CorrespondenceRecord.covariance_calibrated: bool`` (not a separate
    status enum), so this function returns that boolean directly rather than
    a status value the caller has to translate.

    Args:
        normal_matrix: See :func:`estimate_hessian_covariance`.
        noise_variance: See :func:`estimate_hessian_covariance`.
        condition_number_limit: See :func:`estimate_hessian_covariance`.
        calibration: A :class:`CalibrationResult` to scale the raw covariance
            by, or ``None`` to report the raw (uncalibrated) covariance.

    Returns:
        ``(covariance, is_calibrated)``. If the raw Hessian covariance
        cannot be estimated, always ``(None, False)``, regardless of
        ``calibration`` -- there is nothing to calibrate. Otherwise, if
        ``calibration`` is given: ``(scaled_covariance, True)``, where
        ``scaled_covariance``'s ``xx``/``xy``/``yy`` are the raw covariance's
        multiplied by ``calibration.scale_factor``. If ``calibration`` is
        ``None``: ``(raw_covariance, False)``.
    """
    raw_covariance = estimate_hessian_covariance(
        normal_matrix, noise_variance=noise_variance, condition_number_limit=condition_number_limit
    )
    if raw_covariance is None:
        return None, False
    if calibration is None:
        return raw_covariance, False

    scale = calibration.scale_factor
    scaled_covariance = Covariance2D(
        xx=raw_covariance.xx * scale,
        xy=raw_covariance.xy * scale,
        yy=raw_covariance.yy * scale,
        frame=raw_covariance.frame,
        units=raw_covariance.units,
    )
    return scaled_covariance, True
