"""Controlled-shift synthetic fixture generator (WP-00 task 7).

WP-00 requires "small controlled-shift fixtures with exact sub-pixel truth
for unit and calibration tests", clearly labelled synthetic, and its
Verification section requires that "synthetic fixtures round-trip to their
declared shifts within the fixture-generation tolerance." This module builds
exactly that: a deterministic synthetic image and a sub-pixel-shifted copy of
it, paired with the exact applied shift as ground truth. Later matcher work
(WP-04, not built yet) will use fixtures like this to check that a matcher
recovers a known sub-pixel translation within a stated tolerance; this module
only builds and verifies the generator, not a matcher.

Only ``numpy`` is available in this environment (no ``scipy``, no
``opencv``), so sub-pixel translation is implemented via the Fourier shift
theorem using ``numpy.fft`` directly.

This module never reads or references any real mission product, image, or
file: everything it produces is synthetic, in-memory, and generated from a
shape and an integer seed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

__all__ = [
    "ControlledShiftFixture",
    "generate_base_pattern",
    "generate_controlled_shift_fixture",
    "shift_image",
]

# Fixed spatial frequencies (in cycles across the full extent of each axis)
# used by generate_base_pattern. Each is deliberately non-integer: an
# integer cycle count would make the pattern exactly periodic within `shape`,
# so a shift by a multiple of the array size (or an axis-swapped/sign-flipped
# shift acting on a symmetric component) could accidentally reproduce the
# same values and let a bug pass a naive test. Non-integer cycle counts mean
# every distinct (dy_px, dx_px) genuinely changes the sampled values.
_FREQ_A_CYCLES_Y = 3.7
_FREQ_A_CYCLES_X = 2.3
_FREQ_B_CYCLES_Y = 5.1
_FREQ_B_CYCLES_X = 4.9
_FREQ_C_CYCLES_Y = 1.3
_FREQ_C_CYCLES_X = 6.2

# Amplitude of the seeded Gaussian noise term relative to the normalized
# [0, 1] pattern range. Small enough that the sinusoidal texture (which the
# shift theorem test needs to be able to measure a shift against) dominates.
_NOISE_STD = 0.02


def generate_base_pattern(shape: tuple[int, int], *, seed: int) -> npt.NDArray[np.float64]:
    """Build a deterministic synthetic image with real, non-degenerate texture.

    The pattern is a sum of three fixed-frequency 2-D sinusoids (chosen with
    non-integer cycle counts across ``shape`` — see the module-level
    frequency constants — so the pattern is not exactly periodic within
    ``shape`` and cannot trivially fool a shift-round-trip check) plus a
    small amount of seeded Gaussian noise, normalized to ``[0, 1]``. Real
    two-axis texture (not a flat field, not a trivial checkerboard) is
    required because ``shift_image``'s correctness tests need a pattern whose
    values genuinely vary with position along both axes to detect a wrong
    sign or a swapped axis.

    Determinism: the sinusoidal component depends only on ``shape``, and the
    noise component is drawn from ``numpy.random.default_rng(seed)``
    constructed fresh in this call — no module-level or other hidden global
    random state is read or mutated. Calling this twice with the same
    ``(shape, seed)`` always returns bit-identical arrays.

    Args:
        shape: ``(height, width)`` of the pattern, i.e. ``(rows, columns)``,
            matching NumPy's ``array[row, col]`` = ``array[y, x]`` indexing.
        seed: Seed for the deterministic noise component.

    Returns:
        A ``float64`` array of shape ``shape`` with values in ``[0, 1]``.
    """
    height, width = shape
    y = np.arange(height, dtype=np.float64).reshape(height, 1)
    x = np.arange(width, dtype=np.float64).reshape(1, width)

    two_pi = 2.0 * np.pi
    pattern = (
        1.0 * np.sin(two_pi * (_FREQ_A_CYCLES_Y * y / height + _FREQ_A_CYCLES_X * x / width))
        + 0.6
        * np.sin(two_pi * (_FREQ_B_CYCLES_Y * y / height - _FREQ_B_CYCLES_X * x / width) + 0.3)
        + 0.4 * np.cos(two_pi * (_FREQ_C_CYCLES_Y * y / height + _FREQ_C_CYCLES_X * x / width))
    )

    rng = np.random.default_rng(seed)
    noise = rng.normal(loc=0.0, scale=_NOISE_STD, size=shape)
    pattern = pattern + noise

    pattern_min = pattern.min()
    pattern_max = pattern.max()
    normalized: npt.NDArray[np.float64] = (pattern - pattern_min) / (pattern_max - pattern_min)
    return normalized


def _axis_phase_ramp(length: int, shift_px: float) -> npt.NDArray[np.complex128]:
    """Build the 1-D DFT shift-theorem phase vector for one axis.

    For a 1-D signal ``f[n]`` of length ``N``, the circularly-shifted signal
    ``g[n] = f[n - m]`` has DFT ``G[k] = F[k] * exp(-2*pi*i*k*m/N)`` (the
    standard DFT shift theorem, matching NumPy's forward-transform sign
    convention ``exp(-2*pi*i*k*n/N)``). ``numpy.fft.fftfreq(N)`` returns
    exactly ``k/N`` per bin, so the phase vector is ``exp(-2j*pi*fftfreq(N)*m)``.

    Nyquist special case: when ``N`` is even, bin index ``N/2`` is its own
    negation modulo ``N`` (``-N/2 == N/2 (mod N)``), so a real input signal's
    DFT is real at that bin, and staying real there is required for the
    *inverse* transform of ``G`` to stay real too (any other phase value
    for a non-integer ``m`` breaks the real signal's conjugate-symmetric DFT
    exactly at that one self-paired bin, which otherwise leaks a spurious
    imaginary component into every output pixel via the inverse transform).
    ``exp(-2j*pi*(-1/2)*m) = exp(1j*pi*m)`` is complex for non-integer ``m``;
    its real part, ``cos(pi*m)``, is the correct real-valued substitute (for
    integer ``m`` the two agree exactly, since ``exp(1j*pi*m) = cos(pi*m) =
    (-1)**m`` when ``m`` is an integer).
    """
    freq = np.fft.fftfreq(length)
    phase: npt.NDArray[np.complex128] = np.exp(-2j * np.pi * freq * shift_px)
    if length % 2 == 0:
        nyquist_bin = length // 2
        phase[nyquist_bin] = np.cos(np.pi * shift_px)
    return phase


def shift_image(
    image: npt.NDArray[np.float64], *, dy_px: float, dx_px: float
) -> npt.NDArray[np.float64]:
    """Translate ``image`` by ``(dy_px, dx_px)`` pixels via the FFT shift theorem.

    ``dy_px`` is the shift along axis 0 (rows / y), ``dx_px`` along axis 1
    (columns / x) — the same ``[row, col]`` = ``[y, x]`` convention
    ``generate_base_pattern`` uses.

    Method: 2-D FFT the image, multiply by the linear phase ramp
    ``phase_y[:, None] * phase_x[None, :]``, where ``phase_y``/``phase_x``
    are the 1-D per-axis shift-theorem phase vectors from
    ``_axis_phase_ramp`` (each ``exp(-2j*pi*fftfreq(N)*shift)``, real-valued
    at each axis's own Nyquist bin when that axis has even length — see
    ``_axis_phase_ramp`` for why), inverse FFT, and take the real part. The
    2-D ramp is the outer product of the two 1-D ramps because a 2-D shift is
    separable: ``exp(-2j*pi*(fy*dy_px + fx*dx_px)) = exp(-2j*pi*fy*dy_px) *
    exp(-2j*pi*fx*dx_px)``.

    Why this is the correct sign and axis assignment: for an integer ``m``,
    ``g[n] = f[n - m]`` (what the phase ramp above computes) is exactly what
    ``numpy.roll(f, shift=m)`` computes — with ``m = dy_px`` applied on the
    row axis and ``m = dx_px`` on the column axis. That equivalence is what
    the axis/sign-correctness test in ``test_controlled_shift.py`` checks
    directly, which is the test that would catch an axis swap or sign error.

    Boundary behaviour (read before interpreting results near the edges):
    the DFT treats ``image`` as one period of a circularly-periodic signal,
    so this shift is exact for a periodic signal but, for a finite image,
    means content shifted off one edge wraps onto the opposite edge — there
    is no "fill value", the wrapped-in content is real (aliased) image data.
    This is expected and unavoidable for an FFT-based shift with no other
    dependency available (no ``scipy`` padding/border modes). It is also
    harmless for this generator's purpose: ``generate_base_pattern`` uses
    non-integer cycle counts specifically so wrapped content differs from a
    trivial identity, and every correctness test in this module compares
    the *entire* array (border included) against an independently-computed
    reference (``numpy.roll`` for integer shifts, or the original image after
    a shift-and-inverse-shift round trip) rather than assuming a fill value,
    so the wrapped border is exercised, not excluded.

    Even-length-axis precision note: the Nyquist-bin realness fix in
    ``_axis_phase_ramp`` keeps a single ``shift_image`` call's result exactly
    real (no discarded-imaginary-part error), but it is not perfectly
    invertible for a *non-integer* shift on an even-length axis — applying a
    shift and then its exact negation multiplies that axis's Nyquist bin by
    ``cos(pi*m)**2`` rather than ``1``, a residual bounded by the pattern's
    energy at that axis's Nyquist frequency. This does not affect integer
    shifts (``cos(pi*m) = +-1`` exactly there) or odd-length axes (they have
    no self-paired Nyquist bin at all). Use odd height/width when a test
    needs the tightest possible round-trip precision for a non-integer
    shift; ``test_controlled_shift.py``'s round-trip tests do this.

    Args:
        image: A ``float64`` array of shape ``(height, width)``.
        dy_px: Shift along axis 0 (rows / y), in pixels. Positive shifts
            content toward increasing row index (downward, matching
            ``numpy.roll(image, shift=dy_px, axis=0)`` for integer values).
        dx_px: Shift along axis 1 (columns / x), in pixels. Positive shifts
            content toward increasing column index (rightward, matching
            ``numpy.roll(image, shift=dx_px, axis=1)`` for integer values).

    Returns:
        The shifted image as a ``float64`` array of the same shape as
        ``image`` (the imaginary part left over from floating-point FFT
        round-trip error is discarded via ``.real``).
    """
    height, width = image.shape
    phase_y = _axis_phase_ramp(height, dy_px).reshape(height, 1)
    phase_x = _axis_phase_ramp(width, dx_px).reshape(1, width)
    phase_ramp = phase_y * phase_x

    spectrum = np.fft.fft2(image)
    shifted_complex = np.fft.ifft2(spectrum * phase_ramp)
    shifted: npt.NDArray[np.float64] = shifted_complex.real
    return shifted


@dataclass(frozen=True, slots=True)
class ControlledShiftFixture:
    """A synthetic base image, a shifted copy, and the exact applied shift.

    ``synthetic`` is a literal ``True`` marker field, not just a docstring
    claim: WP-00 requires synthetic fixtures to be "clearly labelled
    synthetic", and this lets a downstream consumer check that
    programmatically rather than by inspecting where the array came from.
    """

    base_image: npt.NDArray[np.float64]
    shifted_image: npt.NDArray[np.float64]
    dy_px: float
    """The exact, known-true shift applied along axis 0 (rows / y), in pixels."""
    dx_px: float
    """The exact, known-true shift applied along axis 1 (columns / x), in pixels."""
    seed: int
    """The seed passed to ``generate_base_pattern`` for ``base_image``."""
    synthetic: bool = True
    """Always ``True``: this fixture is synthetic, never derived from real data."""


def generate_controlled_shift_fixture(
    shape: tuple[int, int], *, dy_px: float, dx_px: float, seed: int
) -> ControlledShiftFixture:
    """Build a base/shifted image pair with an exactly-known ground-truth shift.

    Composes :func:`generate_base_pattern` and :func:`shift_image`: generates
    the base image for ``(shape, seed)``, then shifts it by ``(dy_px,
    dx_px)``. This is a pure in-memory generator — no file is read or
    written; there is no consumer yet for a saved fixture format (that is
    WP-04's later, separate concern).

    Args:
        shape: ``(height, width)`` of the base and shifted images.
        dy_px: Ground-truth shift along axis 0 (rows / y), in pixels.
        dx_px: Ground-truth shift along axis 1 (columns / x), in pixels.
        seed: Seed for the base pattern's noise component.

    Returns:
        A :class:`ControlledShiftFixture` recording ``base_image``,
        ``shifted_image``, and the exact ``dy_px``/``dx_px``/``seed`` as
        passed (unrounded, untruncated).
    """
    base_image = generate_base_pattern(shape, seed=seed)
    shifted_image = shift_image(base_image, dy_px=dy_px, dx_px=dx_px)
    return ControlledShiftFixture(
        base_image=base_image,
        shifted_image=shifted_image,
        dy_px=dy_px,
        dx_px=dx_px,
        seed=seed,
        synthetic=True,
    )
