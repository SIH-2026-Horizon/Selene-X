"""Tests for ``benchmarks.scripts.controlled_shift``.

Every image here is synthetically generated in this module (or by the module
under test) from a shape and a seed — never anything resembling real mission
data.

Test images use odd height/width (``47 x 63``). ``shift_image``'s docstring
explains why: for a non-integer pixel shift, an *even*-length axis has a
Nyquist-frequency DFT bin with no phase value that is simultaneously exact
and real, which bounds (but does not eliminate) round-trip precision for
that axis. An odd-length axis has no such self-paired bin, so the FFT
shift-and-inverse-shift round trip is exact to float64 precision (empirically
observed ~1e-15 here) regardless of shift magnitude. Using an odd shape lets
the round-trip tests below use a tight tolerance that is actually justified,
rather than a loose one chosen just to make the test pass. This does not
weaken the axis/sign-correctness coverage: integer-pixel shifts (the
``numpy.roll`` comparison) and zero shift are exact regardless of axis
parity, so the odd shape is not hiding anything there either.
"""

from __future__ import annotations

import numpy as np
import pytest
from benchmarks.scripts.controlled_shift import (
    ControlledShiftFixture,
    generate_base_pattern,
    generate_controlled_shift_fixture,
    shift_image,
)

pytestmark = pytest.mark.unit

_SHAPE = (47, 63)  # odd x odd, and non-square so a row/column axis swap cannot hide

# FFT round-trip float64 tolerance: for an odd-dimensioned image, forward and
# inverse phase-ramp shifts are exact inverses of each other analytically
# (see shift_image's docstring), so the only error source is float64 rounding
# in the FFT itself. Measured residuals in this module's own verification
# were ~1e-15; 1e-9 gives a >1e5x margin above that measurement (enough to
# absorb BLAS/platform variation) while remaining tight enough that a real
# algorithmic bug (wrong sign, swapped axis, wrong normalization) — which
# produces errors of order the image's own amplitude, ~0.1-1.0 — would still
# fail it by many orders of magnitude.
_FFT_ROUNDTRIP_ATOL = 1e-9


def test_generate_base_pattern_is_deterministic() -> None:
    first = generate_base_pattern(_SHAPE, seed=7)
    second = generate_base_pattern(_SHAPE, seed=7)

    # Exact equality, not approximate: same (shape, seed) must be bit-identical.
    assert np.array_equal(first, second)


def test_generate_base_pattern_different_seeds_differ() -> None:
    pattern_a = generate_base_pattern(_SHAPE, seed=1)
    pattern_b = generate_base_pattern(_SHAPE, seed=2)

    assert not np.array_equal(pattern_a, pattern_b)


def test_generate_base_pattern_honors_shape() -> None:
    pattern = generate_base_pattern((31, 17), seed=0)

    assert pattern.shape == (31, 17)


def test_generate_base_pattern_is_non_degenerate() -> None:
    pattern = generate_base_pattern(_SHAPE, seed=7)

    # A regression to an accidentally-flat or near-constant pattern would
    # collapse std toward 0; 0.05 is far below the ~0.2 this pattern actually
    # produces (dominated by unit-amplitude sinusoids on a [0, 1] range) but
    # comfortably above what pure floating-point noise could produce.
    assert np.std(pattern) > 0.05


def test_shift_image_zero_shift_is_identity() -> None:
    image = generate_base_pattern(_SHAPE, seed=3)

    shifted = shift_image(image, dy_px=0.0, dx_px=0.0)

    # Not bit-exact: it still passes through a forward and inverse FFT.
    assert np.allclose(shifted, image, atol=_FFT_ROUNDTRIP_ATOL)


def test_shift_image_integer_shift_matches_numpy_roll() -> None:
    """The critical sign/axis-correctness test.

    ``numpy.roll(image, shift=(dy, dx), axis=(0, 1))[y, x] == image[(y - dy)
    % H, (x - dx) % W]`` is the reference definition of "shift by (dy, dx)
    pixels along (axis 0, axis 1)". If ``shift_image`` had the phase-ramp
    sign backwards, or swapped which axis ``dy_px``/``dx_px`` apply to, this
    would fail — a vaguer "produced *some* different image" test would not
    catch either mistake, which is why this compares against an independent,
    trusted reference (``numpy.roll``) rather than just checking the output
    changed.
    """
    image = generate_base_pattern(_SHAPE, seed=11)
    dy_px, dx_px = 3.0, -2.0

    shifted = shift_image(image, dy_px=dy_px, dx_px=dx_px)
    reference = np.roll(image, shift=(int(dy_px), int(dx_px)), axis=(0, 1))

    assert np.allclose(shifted, reference, atol=_FFT_ROUNDTRIP_ATOL)


def test_shift_image_integer_shift_positive_and_negative_both_axes() -> None:
    """A second integer case with a different sign per axis, for extra confidence.

    Uses distinct, asymmetric magnitudes on each axis (row shift 5, column
    shift 1) so a transposed dy/dx assignment could not coincidentally still
    match ``numpy.roll``.
    """
    image = generate_base_pattern(_SHAPE, seed=11)
    dy_px, dx_px = -5.0, 1.0

    shifted = shift_image(image, dy_px=dy_px, dx_px=dx_px)
    reference = np.roll(image, shift=(int(dy_px), int(dx_px)), axis=(0, 1))

    assert np.allclose(shifted, reference, atol=_FFT_ROUNDTRIP_ATOL)


def test_shift_image_roundtrip_recovers_original_subpixel() -> None:
    image = generate_base_pattern(_SHAPE, seed=5)
    dy_px, dx_px = 1.7, -0.4

    forward = shift_image(image, dy_px=dy_px, dx_px=dx_px)
    back = shift_image(forward, dy_px=-dy_px, dx_px=-dx_px)

    assert np.allclose(back, image, atol=_FFT_ROUNDTRIP_ATOL)


def test_shift_image_roundtrip_recovers_original_large_shift() -> None:
    image = generate_base_pattern(_SHAPE, seed=5)
    dy_px, dx_px = 15.3, 8.9

    forward = shift_image(image, dy_px=dy_px, dx_px=dx_px)
    back = shift_image(forward, dy_px=-dy_px, dx_px=-dx_px)

    assert np.allclose(back, image, atol=_FFT_ROUNDTRIP_ATOL)


def test_controlled_shift_fixture_synthetic_is_always_true() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=2.0, dx_px=1.0, seed=9)

    assert fixture.synthetic is True


def test_controlled_shift_fixture_synthetic_field_default_is_true() -> None:
    # The dataclass field itself defaults to True even if a caller only
    # supplies the other fields directly (defence against a future edit that
    # accidentally flips the default).
    fixture = ControlledShiftFixture(
        base_image=np.zeros((2, 2)),
        shifted_image=np.zeros((2, 2)),
        dy_px=0.0,
        dx_px=0.0,
        seed=0,
    )

    assert fixture.synthetic is True


def test_generate_controlled_shift_fixture_composes_correctly() -> None:
    shape = _SHAPE
    dy_px, dx_px, seed = 2.25, -1.75, 42

    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=seed)

    expected_base = generate_base_pattern(shape, seed=seed)
    expected_shifted = shift_image(expected_base, dy_px=dy_px, dx_px=dx_px)

    assert np.array_equal(fixture.base_image, expected_base)
    assert np.array_equal(fixture.shifted_image, expected_shifted)
    # Recorded exactly as passed: not rounded, not truncated.
    assert fixture.dy_px == dy_px
    assert fixture.dx_px == dx_px
    assert fixture.seed == seed
