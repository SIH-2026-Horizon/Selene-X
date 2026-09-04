"""Mask-aware patch sub-pixel refinement (WP-08 tasks 1-3).

Two independent classical estimators refine a coarse, integer-pixel-accurate
correspondence (Task 14's matchers, verified by Task 15, selected by Task 16)
to genuine sub-pixel accuracy:

* **Inverse-compositional ECC** (:func:`refine_ecc`) — Evangelidis & Psarakis
  (2008)-style enhanced correlation coefficient maximization, translation-only
  warp, using the *fixed template's* gradient (computed once) rather than the
  re-warped reference's gradient (recomputed every iteration) — the IC
  efficiency trick. No ``scipy``/``opencv`` is available, so bilinear
  resampling and the Gauss-Newton normal equations are plain ``numpy``.
* **Fourier-upsampled phase correlation** (:func:`refine_fourier_upsampled`)
  — zero-pads the normalized cross-power spectrum before the inverse FFT,
  which is exactly sinc interpolation of the spatial-domain correlation
  surface (the "band-limited" assumption WP-08 task 2 names).

Both estimators share one seeding convention (see ``_split_shift`` below):
``initial_shift_px`` is the caller's best *full* estimate of the shift
mapping ``source_patch`` into ``reference_patch``'s frame, and the two
patches are assumed to already be extracted such that ``reference_patch``'s
local pixel grid is offset from ``source_patch``'s by
``round(initial_shift_px)`` (component-wise) — exactly what
:func:`extract_patch` produces when called at ``record.source_pixel`` and
``record.reference_pixel`` respectively, since each independently rounds to
its own nearest integer centre. Each estimator therefore only ever has to
search a small sub-pixel *residual* near zero, which is what keeps the
warp/upsampling math well-posed for small patches, and adds the rounded
integer part back into the value it returns.

:func:`refine_correspondence` composes patch extraction, a texture gate, and
both estimators into one entry point that updates a
:class:`~selene_core.match.correspondence.CorrespondenceRecord`. When a
caller supplies ``noise_variance``, it also populates that record's
``covariance``/``covariance_calibrated`` fields from the ECC estimator's
local Hessian, via :mod:`selene_core.refine.covariance` (Task 18, WP-08
tasks 4-5) -- optional and additive, so a caller that omits it gets exactly
Task 17's original behaviour.

Out of scope here (see the plan and WP-08 tasks 6, 8-13): tiling/pyramids
and terrain-aware adjustment.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord
from selene_core.refine.covariance import CalibrationResult, apply_calibrated_covariance
from selene_core.types import SourcePixel

__all__ = [
    "EccRefinementResult",
    "FourierRefinementResult",
    "PatchExtractionResult",
    "extract_patch",
    "patch_texture_score",
    "refine_correspondence",
    "refine_ecc",
    "refine_fourier_upsampled",
]

_EPS = float(np.finfo(np.float64).eps)

# How far (in original-resolution pixels) the Fourier-upsampled peak search is
# allowed to range from the seeded residual anchor before a candidate is
# rejected as the wrong wraparound copy. The seeding convention above bounds
# the true residual to within +-0.5px of zero in each axis (half the width of
# each patch's own rounding bin); 2.0px gives generous slack for the
# estimator's own error without risking picking a different aliased period of
# the (period-H, period-W) circular correlation surface.
_WRAPAROUND_SEARCH_RADIUS_PX = 2.0

_ALGORITHM_ECC = "ecc_inverse_compositional"
_ALGORITHM_FOURIER = "fourier_upsampled"

# Task 18 (WP-08 tasks 4-5): the name recorded in CorrespondenceRecord.
# covariance_method when refine_correspondence populates a covariance. It
# names the estimator whose normal_matrix the covariance is derived from
# (see refine_correspondence's docstring for why ECC and not Fourier).
_COVARIANCE_METHOD_ECC_HESSIAN = "ecc_local_hessian"


# ---------------------------------------------------------------------------
# Patch extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatchExtractionResult:
    """The outcome of one :func:`extract_patch` call.

    ``reason`` is non-empty exactly when ``valid`` is ``False`` — extraction
    failure is an explicit, inspectable state, never a silently-clipped or
    fabricated patch.
    """

    patch: npt.NDArray[np.float64] | None
    valid: bool
    reason: str | None


def extract_patch(
    image: npt.NDArray[np.float64],
    *,
    center: tuple[float, float],
    half_size: int,
    mask: npt.NDArray[np.bool_] | None,
    min_valid_fraction: float = 0.5,
) -> PatchExtractionResult:
    """Extract a ``(2*half_size+1, 2*half_size+1)`` patch centred on ``center``.

    ``center`` (line, sample) is rounded to the nearest integer pixel before
    extraction: patch extraction itself lives on the integer grid, sub-pixel
    centring is what :func:`refine_ecc`/:func:`refine_fourier_upsampled` do.
    Python's banker's-rounding ``round()`` is used; the rare exact-half-pixel
    tie is not a case this project's fixtures or real geolocation ever land
    on exactly, and either rounding choice is an equally valid integer centre.

    If the requested window falls partially or fully outside ``image``'s
    bounds, or the corresponding ``mask`` region has a valid-pixel fraction
    below ``min_valid_fraction``, extraction fails explicitly (``valid=False``,
    ``patch=None``, ``reason`` set) rather than clipping the window or
    fabricating fill values for the missing part.
    """
    if image.ndim != 2:
        raise ValueError(f"image must be a 2D array, got shape {image.shape!r}")
    if half_size < 1:
        raise ValueError(f"half_size must be >= 1, got {half_size!r}")
    if not (0.0 < min_valid_fraction <= 1.0):
        raise ValueError(f"min_valid_fraction must be in (0, 1], got {min_valid_fraction!r}")
    if mask is not None and mask.shape != image.shape:
        raise ValueError(f"mask shape {mask.shape!r} does not match image shape {image.shape!r}")

    center_line = round(center[0])
    center_sample = round(center[1])
    line0, line1 = center_line - half_size, center_line + half_size
    sample0, sample1 = center_sample - half_size, center_sample + half_size
    height, width = image.shape

    if line0 < 0 or sample0 < 0 or line1 >= height or sample1 >= width:
        return PatchExtractionResult(
            patch=None,
            valid=False,
            reason=(
                f"patch window rows [{line0}, {line1}] cols [{sample0}, {sample1}] "
                f"exceeds image bounds {image.shape!r} for center {center!r}"
            ),
        )

    if mask is not None:
        mask_patch = mask[line0 : line1 + 1, sample0 : sample1 + 1]
        valid_fraction = float(np.mean(mask_patch))
        if valid_fraction < min_valid_fraction:
            return PatchExtractionResult(
                patch=None,
                valid=False,
                reason=(
                    f"mask valid fraction {valid_fraction:.4f} is below "
                    f"min_valid_fraction={min_valid_fraction!r} for center {center!r}"
                ),
            )

    patch = image[line0 : line1 + 1, sample0 : sample1 + 1].copy()
    return PatchExtractionResult(patch=patch, valid=True, reason=None)


def patch_texture_score(patch: npt.NDArray[np.float64]) -> float:
    """Mean squared gradient magnitude — a scalar texture/gradient-energy score.

    ``score = mean(dpatch/drow ** 2 + dpatch/dcol ** 2)``, both partials from
    ``numpy.gradient`` (central differences interior, one-sided at edges). A
    perfectly flat patch has zero gradient everywhere, so it scores exactly
    zero; real structure (edges, texture) produces non-zero local gradients,
    so higher scores mean more texture. Sub-pixel refinement fundamentally
    needs intensity variation to lock onto — a flat patch has none, which is
    exactly the scenario this score is meant to flag (see
    :func:`refine_correspondence`'s ``min_patch_texture`` gate).
    """
    if patch.ndim != 2 or patch.size == 0:
        raise ValueError(f"patch must be a non-empty 2D array, got shape {patch.shape!r}")
    grad_row, grad_col = np.gradient(patch)
    return float(np.mean(grad_row**2 + grad_col**2))


# ---------------------------------------------------------------------------
# Shared helpers (bilinear sampling, the base/residual seeding split)
# ---------------------------------------------------------------------------


def _bilinear_sample(
    image: npt.NDArray[np.float64],
    rows: npt.NDArray[np.float64],
    cols: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Sample ``image`` at fractional ``(rows, cols)`` via bilinear interpolation.

    Coordinates outside ``image``'s bounds are clamped to the nearest edge
    pixel (replicate boundary) rather than raising or fabricating an
    out-of-range fill value: the seeding convention here only ever asks for
    samples within roughly half a pixel of the patch's own bounds, so
    clamping only ever affects the immediate border by a fraction of a pixel.
    """
    height, width = image.shape
    rows_clamped = np.clip(rows, 0.0, height - 1)
    cols_clamped = np.clip(cols, 0.0, width - 1)
    row0 = np.floor(rows_clamped).astype(np.int64)
    col0 = np.floor(cols_clamped).astype(np.int64)
    row1 = np.clip(row0 + 1, 0, height - 1)
    col1 = np.clip(col0 + 1, 0, width - 1)
    frac_row = rows_clamped - row0
    frac_col = cols_clamped - col0

    top_left = image[row0, col0]
    top_right = image[row0, col1]
    bottom_left = image[row1, col0]
    bottom_right = image[row1, col1]

    top = top_left + frac_col * (top_right - top_left)
    bottom = bottom_left + frac_col * (bottom_right - bottom_left)
    result: npt.NDArray[np.float64] = top + frac_row * (bottom - top)
    return result


def _split_shift(shift_px: tuple[float, float]) -> tuple[tuple[int, int], tuple[float, float]]:
    """Split a full shift into its rounded integer base and sub-pixel residual.

    See the module docstring: ``reference_patch`` is assumed extracted such
    that its local grid is offset from ``source_patch``'s by
    ``round(shift_px)``, so only the residual needs to be searched.
    """
    base = (round(shift_px[0]), round(shift_px[1]))
    residual = (shift_px[0] - base[0], shift_px[1] - base[1])
    return base, residual


def _validate_patch_pair(
    source_patch: npt.NDArray[np.float64], reference_patch: npt.NDArray[np.float64]
) -> None:
    for name, patch in (("source_patch", source_patch), ("reference_patch", reference_patch)):
        if patch.ndim != 2 or patch.size == 0:
            raise ValueError(f"{name} must be a non-empty 2D array, got shape {patch.shape!r}")
        if not np.all(np.isfinite(patch)):
            raise ValueError(f"{name} must contain only finite values")
    if source_patch.shape != reference_patch.shape:
        raise ValueError(
            "source_patch and reference_patch must share a shape, got "
            f"{source_patch.shape!r} and {reference_patch.shape!r}"
        )


# ---------------------------------------------------------------------------
# ECC (inverse-compositional, translation-only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class EccRefinementResult:
    """The outcome of one :func:`refine_ecc` call.

    ``eq=False`` here: the dataclass-generated ``__eq__`` compares every
    field with plain ``==``, which for an ``ndarray`` field returns an
    elementwise array rather than a single ``bool`` (a ``ValueError`` when
    that array is then coerced to ``bool``, e.g. by ``assert a == b``). A
    custom ``__eq__`` below compares ``normal_matrix`` with
    ``numpy.array_equal`` instead, and every other field exactly as before —
    an additive fix, not a change to any pre-existing field's equality
    semantics. This also makes instances explicitly unhashable (Python sets
    ``__hash__ = None`` for a class that defines ``__eq__`` without also
    defining ``__hash__``), which is honest: an ``ndarray``-bearing instance
    was never safely hashable even under the old generated ``__eq__``/
    ``__hash__`` pair, and nothing in this codebase hashes one.
    """

    refined_shift_px: tuple[float, float]
    converged: bool
    iterations_used: int
    final_correlation: float
    normal_matrix: npt.NDArray[np.float64]
    """The ``(2, 2)`` Gauss-Newton normal matrix ``H - c c^T`` (see the
    docstring derivation above), evaluated at ``refined_shift_px`` (the
    *final* residual actually returned, recomputed after the loop for the
    same reason ``final_correlation`` is — the in-loop value is one
    iteration stale). This is the local curvature of the ECC objective at
    the converged shift: Task 18 (WP-08 tasks 4-5) uses it as the basis of a
    Hessian-based positional covariance estimate. Out of scope here; see
    :mod:`selene_core.refine.covariance`.
    """

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EccRefinementResult):
            return NotImplemented
        return (
            self.refined_shift_px == other.refined_shift_px
            and self.converged == other.converged
            and self.iterations_used == other.iterations_used
            and self.final_correlation == other.final_correlation
            and bool(np.array_equal(self.normal_matrix, other.normal_matrix))
        )


def refine_ecc(
    source_patch: npt.NDArray[np.float64],
    reference_patch: npt.NDArray[np.float64],
    *,
    initial_shift_px: tuple[float, float],
    max_iterations: int,
    convergence_threshold: float,
) -> EccRefinementResult:
    """Inverse-compositional ECC, translation-only warp (2 parameters: dy, dx).

    ``source_patch`` is the fixed template ``T``; ``reference_patch`` is
    resampled (bilinearly, since no ``scipy.ndimage`` is available) toward
    ``T`` at each iteration's current shift estimate. Both patches are
    zero-meaned; the correlation objective further unit-normalizes the
    (zero-mean) warped reference and the (zero-mean, unit-norm) template —
    ECC's enhanced correlation coefficient is scale/offset-invariant by
    construction, so this normalization is part of the algorithm, not
    optional preprocessing.

    **Derivation** (validated numerically against a finite-difference
    gradient before being trusted here — see the task report). Let
    ``t = T - mean(T)``, ``t_hat = t / ||t||`` (fixed). At shift ``p`` let
    ``w(p) = warp(reference_patch, p) - mean(warp(reference_patch, p))``
    (the zero-mean warped reference), ``n(p) = ||w(p)||``, and the objective
    ``rho(p) = t_hat . w(p) / n(p)`` (the enhanced correlation coefficient).
    Linearizing the warp to first order, ``w(p + dp) ~= w(p) + G dp``, where
    ``G``'s two columns are ``T``'s zero-meaned finite-difference gradient
    images (the *inverse-compositional* substitution: using the fixed
    template's gradient here, instead of re-differentiating the warped
    reference every iteration, is what makes ``G`` — and the 2x2
    ``H = G^T G`` below — computable once, outside the iteration loop; the
    approximation is exact when ``w(p)`` already matches ``T``, which is
    where the algorithm is converging to). Standard Gauss-Newton on the
    equivalent least-squares form (minimizing ``||t_hat - w(p)/n(p)||^2``,
    using the exact quotient-rule Jacobian of the unit-normalized
    ``w(p)/n(p)`` with respect to ``p``) gives the normal equations actually
    solved here:

    ``(H - c c^T) dp = n * G^T t_hat - rho(p) * G^T w(p)``,

    where ``c = G^T w(p) / n(p)``. (An earlier, more ad hoc derivation that
    froze ``n(p)`` and ``rho(p)`` inside the *unnormalized* stationarity
    condition looked numerically plausible — small ``dp`` steps that
    correlated well with the finite-difference gradient by cosine similarity
    — but its fixed point did not actually zero the true numerical gradient
    of ``rho``; this Gauss-Newton form was checked against finite differences
    at both near- and far-from-optimum shifts and its fixed point does match
    the numerical gradient, which is why it is the one implemented.)

    ``initial_shift_px`` is split into a rounded integer base and a small
    residual (see the module docstring); only the residual is iterated, and
    the base is added back into the returned ``refined_shift_px``. The
    update is additive (``residual += delta``): translations compose by
    addition, so no warp inversion/composition step is needed.
    """
    _validate_patch_pair(source_patch, reference_patch)
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {max_iterations!r}")
    if convergence_threshold <= 0.0:
        raise ValueError(f"convergence_threshold must be > 0, got {convergence_threshold!r}")

    template = source_patch
    template_zero_mean = template - template.mean()
    template_norm = float(np.linalg.norm(template_zero_mean))
    if template_norm <= _EPS:
        raise ValueError("source_patch has ~zero variance; ECC requires template texture")
    template_hat = (template_zero_mean / template_norm).ravel()

    grad_row, grad_col = np.gradient(template)
    g_row = (grad_row - grad_row.mean()).ravel()
    g_col = (grad_col - grad_col.mean()).ravel()
    g_bar = np.column_stack([g_row, g_col])  # (N, 2)
    hessian = g_bar.T @ g_bar  # (2, 2), constant across iterations (the IC trick)

    height, width = template.shape
    row_grid, col_grid = np.indices((height, width))
    row_grid = row_grid.astype(np.float64)
    col_grid = col_grid.astype(np.float64)

    base, residual_arr = _split_shift(initial_shift_px)
    residual = np.array(residual_arr, dtype=np.float64)

    converged = False
    iterations_used = 0
    correlation = float("nan")
    for _ in range(max_iterations):
        warped = _bilinear_sample(reference_patch, row_grid + residual[0], col_grid + residual[1])
        warped_zero_mean = warped - warped.mean()
        warped_norm = float(np.linalg.norm(warped_zero_mean))
        if warped_norm <= _EPS:
            iterations_used += 1
            break
        warped_zero_mean_flat = warped_zero_mean.ravel()
        numerator = float(np.dot(template_hat, warped_zero_mean_flat))
        correlation = numerator / warped_norm

        g_warped = g_bar.T @ warped_zero_mean_flat  # G^T w(p)
        g_template = g_bar.T @ template_hat  # G^T t_hat
        c_vec = g_warped / warped_norm
        normal_matrix = hessian - np.outer(c_vec, c_vec)
        rhs = warped_norm * g_template - correlation * g_warped

        try:
            delta = np.linalg.solve(normal_matrix, rhs)
        except np.linalg.LinAlgError:
            iterations_used += 1
            break

        residual = residual + delta
        iterations_used += 1
        if float(np.linalg.norm(delta)) < convergence_threshold:
            converged = True
            break

    # Recompute the final correlation (and, for Task 18, the final normal
    # matrix) at the residual actually returned -- the loop's last
    # `correlation`/`normal_matrix` are from *before* that iteration's update.
    warped_final = _bilinear_sample(reference_patch, row_grid + residual[0], col_grid + residual[1])
    warped_final_zero_mean = warped_final - warped_final.mean()
    warped_final_norm = float(np.linalg.norm(warped_final_zero_mean))
    if warped_final_norm > _EPS:
        warped_final_zero_mean_flat = warped_final_zero_mean.ravel()
        final_correlation = float(
            np.dot(template_hat, warped_final_zero_mean_flat) / warped_final_norm
        )
        c_vec_final = (g_bar.T @ warped_final_zero_mean_flat) / warped_final_norm
        normal_matrix_final = hessian - np.outer(c_vec_final, c_vec_final)
    else:
        # The warped reference at the final residual has ~zero variance: `c`
        # (and therefore the correction term) is not meaningfully computable
        # from it. Falling back to the fixed template Hessian alone (the
        # `c = 0` limit of the same formula) is the honest degenerate value,
        # matching `final_correlation`'s own fallback to the last in-loop
        # value for the same "warped reference is degenerate" condition.
        final_correlation = correlation
        normal_matrix_final = hessian.copy()

    refined_shift = (base[0] + float(residual[0]), base[1] + float(residual[1]))
    return EccRefinementResult(
        refined_shift_px=refined_shift,
        converged=converged,
        iterations_used=iterations_used,
        final_correlation=final_correlation,
        normal_matrix=normal_matrix_final,
    )


# ---------------------------------------------------------------------------
# Fourier-upsampled phase correlation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FourierRefinementResult:
    """The outcome of one :func:`refine_fourier_upsampled` call."""

    refined_shift_px: tuple[float, float]
    peak_value: float
    peak_ambiguity: float


def _signed_offsets(length: int) -> npt.NDArray[np.int64]:
    """The DFT shift-theorem's signed per-bin offsets for one axis of ``length``.

    Own, module-local equivalent of
    ``match.phase_correlation._signed_fft_offsets`` (not imported — that
    name is private to its module by this project's convention).
    """
    indices = np.arange(length, dtype=np.int64)
    return np.where(indices <= length // 2, indices, indices - length)


def refine_fourier_upsampled(
    source_patch: npt.NDArray[np.float64],
    reference_patch: npt.NDArray[np.float64],
    *,
    initial_shift_px: tuple[float, float],
    upsample_factor: int,
) -> FourierRefinementResult:
    """Band-limited Fourier-upsampled phase correlation, translation-only.

    Computes the normalized cross-power spectrum of the two patches (own
    implementation, same normalized-phase-correlation approach as
    ``match/phase_correlation.py`` but not importing its private helpers),
    then zero-pads that spectrum by ``upsample_factor`` before the inverse
    FFT. Padding in the frequency domain is equivalent to sinc-interpolating
    the spatial-domain correlation surface — the band-limited assumption —
    which produces a finer-resolution surface without needing any spatial
    interpolation of the patches themselves.

    A 2-D Hann window is applied to both zero-meaned patches before the FFT.
    This is necessary, not cosmetic: a real ``(2*half_size+1)`` patch is a
    *windowed* crop, not a circularly-periodic signal, so its un-apodized
    cross-power spectrum leaks energy across the whole spectrum (Gibbs-like
    edge discontinuities) and the zero-padded, un-windowed surface's peak can
    land a full patch-fraction away from the true sub-pixel shift. Tapering
    the patch edges before the FFT (verified against a controlled-shift
    fixture during development: recovery error dropped from spurious
    multi-pixel misses to error comfortably under ``1/upsample_factor`` once
    the window was added) removes that leakage.

    Following the module's shared seeding convention, ``initial_shift_px``
    is split into a rounded integer base and a small residual anchor; the
    peak search on the upsampled surface is restricted to within
    ``_WRAPAROUND_SEARCH_RADIUS_PX`` of that anchor so the correct
    (non-aliased) period of the circular correlation surface is chosen
    rather than blindly taking the global maximum — the surface is
    periodic with period ``(height, width)`` in original-pixel units
    regardless of ``upsample_factor``, so without this restriction a
    stronger peak one whole patch-period away could be picked instead of
    the true nearby one.
    """
    _validate_patch_pair(source_patch, reference_patch)
    if upsample_factor < 1:
        raise ValueError(f"upsample_factor must be >= 1, got {upsample_factor!r}")

    height, width = source_patch.shape
    base, residual_anchor = _split_shift(initial_shift_px)

    window = np.outer(np.hanning(height), np.hanning(width))
    source_zero_mean = (source_patch - source_patch.mean()) * window
    reference_zero_mean = (reference_patch - reference_patch.mean()) * window

    # Same sign convention as match/phase_correlation.py: reference * conj(source)
    # gives the displacement mapping a source coordinate into the reference frame.
    source_spectrum = np.fft.fft2(source_zero_mean)
    reference_spectrum = np.fft.fft2(reference_zero_mean)
    cross_power = reference_spectrum * np.conj(source_spectrum)
    magnitude = np.abs(cross_power)
    normalized = np.divide(
        cross_power, magnitude, out=np.zeros_like(cross_power), where=magnitude > _EPS
    )

    padded_height, padded_width = height * upsample_factor, width * upsample_factor
    shifted_spectrum = np.fft.fftshift(normalized)
    padded_spectrum = np.zeros((padded_height, padded_width), dtype=np.complex128)
    row_start = padded_height // 2 - height // 2
    col_start = padded_width // 2 - width // 2
    padded_spectrum[row_start : row_start + height, col_start : col_start + width] = (
        shifted_spectrum
    )
    upsampled_spectrum = np.fft.ifftshift(padded_spectrum)
    surface = np.abs(np.fft.ifft2(upsampled_spectrum))

    offsets_row = _signed_offsets(padded_height).astype(np.float64) / upsample_factor
    offsets_col = _signed_offsets(padded_width).astype(np.float64) / upsample_factor
    grid_row = offsets_row.reshape(-1, 1)
    grid_col = offsets_col.reshape(1, -1)

    eligible = (grid_row - residual_anchor[0]) ** 2 + (
        grid_col - residual_anchor[1]
    ) ** 2 <= _WRAPAROUND_SEARCH_RADIUS_PX**2
    if not np.any(eligible):
        eligible = np.ones_like(eligible)

    restricted_surface = np.where(eligible, surface, -np.inf)
    peak_index = np.unravel_index(int(np.argmax(restricted_surface)), surface.shape)
    peak_row, peak_col = int(peak_index[0]), int(peak_index[1])
    peak_value = float(surface[peak_row, peak_col])
    refined_residual = (
        float(grid_row[peak_row, 0]),
        float(grid_col[0, peak_col]),
    )

    # Peak ambiguity: suppress a 1-original-pixel neighbourhood around the
    # chosen peak, then take the strongest remaining value anywhere on the
    # (unrestricted) surface as the competing peak — this deliberately looks
    # at the whole surface, not just the wraparound-restricted region, so a
    # genuinely ambiguous (e.g. periodic) patch's competing peak is found
    # wherever it lives, the same "best vs. second-best" reasoning
    # match/ncc.py's _uniqueness_ratio uses.
    suppress_radius = max(upsample_factor, 1)
    row_indices, col_indices = np.indices(surface.shape)
    near_peak = (np.abs(row_indices - peak_row) <= suppress_radius) & (
        np.abs(col_indices - peak_col) <= suppress_radius
    )
    remaining = np.where(near_peak, -np.inf, surface)
    second_peak_value = float(np.max(remaining)) if np.any(np.isfinite(remaining)) else 0.0
    peak_ambiguity = peak_value / max(second_peak_value, _EPS)

    refined_shift = (base[0] + refined_residual[0], base[1] + refined_residual[1])
    return FourierRefinementResult(
        refined_shift_px=refined_shift,
        peak_value=peak_value,
        peak_ambiguity=peak_ambiguity,
    )


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def refine_correspondence(
    record: CorrespondenceRecord,
    source_image: npt.NDArray[np.float64],
    reference_image: npt.NDArray[np.float64],
    *,
    source_mask: npt.NDArray[np.bool_] | None,
    reference_mask: npt.NDArray[np.bool_] | None,
    patch_half_size: int,
    ecc_max_iterations: int,
    ecc_convergence_threshold: float,
    fourier_upsample_factor: int,
    min_patch_texture: float,
    noise_variance: float | None = None,
    condition_number_limit: float = 1e8,
    calibration: CalibrationResult | None = None,
) -> CorrespondenceRecord:
    """Refine one correspondence's location with both estimators, or explain why not.

    Three distinguishable outcomes (never conflated):

    1. **Patch extraction failed** (source or reference patch window falls
       outside image bounds, or its mask is majority-invalid) —
       ``refined_location=None``, ``estimator_identities=()``,
       ``rejection_reason`` starts with ``"refinement patch extraction
       failed"``.
    2. **Extraction succeeded but the source patch is too flat to refine**
       (``patch_texture_score`` below ``min_patch_texture``) —
       ``refined_location=None``, ``estimator_identities=()``,
       ``rejection_reason`` starts with ``"refinement skipped: low patch
       texture"``.
    3. **Refinement ran** — both estimators are seeded from the same coarse
       displacement (``record.reference_pixel - record.source_pixel``, per
       this module's shared seeding convention), ``refined_location`` is
       ``record.source_pixel`` shifted by the *average* of the two
       estimators' refined shifts (a simple, reasonable combination — a more
       sophisticated weighted combination belongs to a later task, not this
       one), ``estimator_identities`` names both, and
       ``estimator_disagreement_px`` is the Euclidean distance between their
       two refined shifts.

       If ``noise_variance`` is given, this outcome also populates
       ``covariance``/``covariance_method``/``covariance_calibrated`` from
       the ECC estimator's ``normal_matrix`` (Task 18, WP-08 tasks 4-5), via
       :func:`selene_core.refine.covariance.apply_calibrated_covariance`.
       The ECC estimator's Hessian is used rather than the Fourier
       estimator's peak/ambiguity statistics because it is the estimator
       whose local curvature this task's covariance formula derives from —
       the Fourier estimator has no analogous Gauss-Newton normal matrix.
       When ``noise_variance`` is ``None`` (the default), ``covariance``
       stays ``None`` and ``covariance_calibrated`` stays ``False``, exactly
       as Task 17 left them: this is a strictly additive, backward-compatible
       extension.

    In every case ``coarse_location`` is set to ``record.source_pixel``
    (WP-08's own name for the pre-refinement location), and the update is
    applied via ``record.model_copy(update=...)`` since ``CorrespondenceRecord``
    is frozen.

    Args:
        condition_number_limit: Forwarded to
            :func:`~selene_core.refine.covariance.estimate_hessian_covariance`
            when ``noise_variance`` is given. ``1e8`` is a permissive default
            for float64 arithmetic (whose own precision is roughly 1 part in
            ``1e16``): a Hessian conditioned worse than that has lost so much
            relative precision in its weaker eigen-direction that inverting
            it would report a "covariance" dominated by rounding error rather
            than the true local curvature, so it is rejected (``None``)
            instead of silently trusted.
        calibration: An empirical scale correction from
            :func:`~selene_core.refine.covariance.calibrate_covariance_scale`,
            or ``None`` to report the raw (uncalibrated) Hessian covariance.
    """
    source_extraction = extract_patch(
        source_image,
        center=(record.source_pixel.line, record.source_pixel.sample),
        half_size=patch_half_size,
        mask=source_mask,
    )
    reference_extraction = extract_patch(
        reference_image,
        center=(record.reference_pixel.line, record.reference_pixel.sample),
        half_size=patch_half_size,
        mask=reference_mask,
    )

    if not source_extraction.valid or not reference_extraction.valid:
        failure_reasons = [
            reason
            for reason in (source_extraction.reason, reference_extraction.reason)
            if reason is not None
        ]
        return record.model_copy(
            update={
                "coarse_location": record.source_pixel,
                "refined_location": None,
                "estimator_identities": (),
                "estimator_disagreement_px": None,
                "rejection_reason": "refinement patch extraction failed: "
                + "; ".join(failure_reasons),
            }
        )

    assert source_extraction.patch is not None  # noqa: S101 - guaranteed by valid=True
    texture = patch_texture_score(source_extraction.patch)
    if texture < min_patch_texture:
        return record.model_copy(
            update={
                "coarse_location": record.source_pixel,
                "refined_location": None,
                "estimator_identities": (),
                "estimator_disagreement_px": None,
                "rejection_reason": (
                    f"refinement skipped: low patch texture score={texture:.6g} "
                    f"< min_patch_texture={min_patch_texture!r}"
                ),
            }
        )

    assert reference_extraction.patch is not None  # noqa: S101 - guaranteed by valid=True
    full_shift = (
        record.reference_pixel.line - record.source_pixel.line,
        record.reference_pixel.sample - record.source_pixel.sample,
    )

    ecc_result = refine_ecc(
        source_extraction.patch,
        reference_extraction.patch,
        initial_shift_px=full_shift,
        max_iterations=ecc_max_iterations,
        convergence_threshold=ecc_convergence_threshold,
    )
    fourier_result = refine_fourier_upsampled(
        source_extraction.patch,
        reference_extraction.patch,
        initial_shift_px=full_shift,
        upsample_factor=fourier_upsample_factor,
    )

    average_shift = (
        (ecc_result.refined_shift_px[0] + fourier_result.refined_shift_px[0]) / 2.0,
        (ecc_result.refined_shift_px[1] + fourier_result.refined_shift_px[1]) / 2.0,
    )
    disagreement = float(
        np.hypot(
            ecc_result.refined_shift_px[0] - fourier_result.refined_shift_px[0],
            ecc_result.refined_shift_px[1] - fourier_result.refined_shift_px[1],
        )
    )
    refined_location = SourcePixel(
        line=record.source_pixel.line + average_shift[0],
        sample=record.source_pixel.sample + average_shift[1],
    )

    covariance = None
    covariance_calibrated = False
    covariance_method = None
    if noise_variance is not None:
        covariance, covariance_calibrated = apply_calibrated_covariance(
            ecc_result.normal_matrix,
            noise_variance=noise_variance,
            condition_number_limit=condition_number_limit,
            calibration=calibration,
        )
        covariance_method = _COVARIANCE_METHOD_ECC_HESSIAN

    return record.model_copy(
        update={
            "coarse_location": record.source_pixel,
            "refined_location": refined_location,
            "estimator_identities": (_ALGORITHM_ECC, _ALGORITHM_FOURIER),
            "estimator_disagreement_px": disagreement,
            "rejection_reason": None,
            "covariance": covariance,
            "covariance_method": covariance_method,
            "covariance_calibrated": covariance_calibrated,
        }
    )
