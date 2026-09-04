"""Tests for mask-aware patch sub-pixel refinement (WP-08 tasks 1-3)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest
from benchmarks.scripts.controlled_shift import (
    generate_base_pattern,
    generate_controlled_shift_fixture,
)

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.refine.patch_refinement import (
    EccRefinementResult,
    FourierRefinementResult,
    PatchExtractionResult,
    extract_patch,
    patch_texture_score,
    refine_correspondence,
    refine_ecc,
    refine_fourier_upsampled,
)
from selene_core.types import ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_INPUT_DIGEST = "e" * 64
_REFERENCE_DIGEST = "f" * 64
_PARAMETER_DIGEST = "0" * 64

# ECC recovery tolerance. Measured during development (see the task report's
# validation section): for a residual within the module's seeding convention
# (bounded to +-0.5px in each axis by construction), recovery error against a
# controlled-shift fixture was consistently 0.002-0.03px, the residual bias
# of using the fixed template's gradient (the inverse-compositional
# approximation, exact only once the warped reference already matches the
# template) combined with bilinear interpolation of a textured patch. 0.05px
# gives a safety margin over that measured range while still meaningfully
# proving sub-pixel (not merely integer-pixel) recovery.
_ECC_TOLERANCE_PX = 0.05

_UPSAMPLE_FACTOR = 20
# Fourier recovery tolerance: nominal grid resolution is 1/upsample_factor:
# assert comfortably under that bound, per the brief.
_FOURIER_TOLERANCE_PX = 1.0 / _UPSAMPLE_FACTOR


def _record(
    *,
    source_pixel: SourcePixel,
    reference_pixel: ReferencePixel,
) -> CorrespondenceRecord:
    return CorrespondenceRecord(
        job_id="refine-job",
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


def _extract_matching_patches(
    base_image: npt.NDArray[np.float64],
    shifted_image: npt.NDArray[np.float64],
    *,
    center: tuple[float, float],
    half_size: int,
    dy_px: float,
    dx_px: float,
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], tuple[int, int]]:
    """Extract a template/reference patch pair mimicking refine_correspondence's
    own extraction convention: the reference patch is centred at
    ``center + round(dy_px, dx_px)`` (the "correct nearby integer coarse
    estimate"), the source/template patch stays at ``center``.
    """
    source_extraction = extract_patch(base_image, center=center, half_size=half_size, mask=None)
    base = (round(dy_px), round(dx_px))
    reference_extraction = extract_patch(
        shifted_image,
        center=(center[0] + base[0], center[1] + base[1]),
        half_size=half_size,
        mask=None,
    )
    assert source_extraction.patch is not None
    assert reference_extraction.patch is not None
    return source_extraction.patch, reference_extraction.patch, base


# ---------------------------------------------------------------------------
# extract_patch
# ---------------------------------------------------------------------------


def test_extract_patch_well_inside_bounds_matches_source_region() -> None:
    image = np.arange(100.0).reshape(10, 10)

    result = extract_patch(image, center=(5.0, 5.0), half_size=2, mask=None)

    assert result.valid
    assert result.reason is None
    assert result.patch is not None
    assert result.patch.shape == (5, 5)
    np.testing.assert_array_equal(result.patch, image[3:8, 3:8])


def test_extract_patch_near_edge_fails_with_specific_reason() -> None:
    image = np.zeros((10, 10))

    result = extract_patch(image, center=(1.0, 5.0), half_size=2, mask=None)

    assert not result.valid
    assert result.patch is None
    assert result.reason is not None
    assert "exceeds image bounds" in result.reason


def test_extract_patch_majority_masked_invalid_fails() -> None:
    image = np.zeros((10, 10))
    mask = np.ones((10, 10), dtype=np.bool_)
    mask[3:8, 3:8] = False  # the whole requested window is invalid

    result = extract_patch(image, center=(5.0, 5.0), half_size=2, mask=mask)

    assert not result.valid
    assert result.patch is None
    assert result.reason is not None
    assert "valid fraction" in result.reason


def test_extract_patch_result_is_a_frozen_dataclass_with_reason_iff_invalid() -> None:
    valid = extract_patch(np.zeros((10, 10)), center=(5.0, 5.0), half_size=2, mask=None)
    invalid = extract_patch(np.zeros((10, 10)), center=(1.0, 1.0), half_size=5, mask=None)

    assert isinstance(valid, PatchExtractionResult)
    assert valid.valid and valid.reason is None
    assert not invalid.valid and invalid.reason


# ---------------------------------------------------------------------------
# patch_texture_score
# ---------------------------------------------------------------------------


def test_flat_patch_scores_at_or_near_zero() -> None:
    flat_patch = np.full((9, 9), 0.5)

    assert patch_texture_score(flat_patch) == pytest.approx(0.0, abs=1e-12)


def test_textured_patch_scores_meaningfully_higher_than_flat() -> None:
    flat_patch = np.full((21, 21), 0.5)
    textured_patch = generate_base_pattern((21, 21), seed=1)

    flat_score = patch_texture_score(flat_patch)
    textured_score = patch_texture_score(textured_patch)

    assert textured_score > flat_score
    assert textured_score > 1e-4


# ---------------------------------------------------------------------------
# refine_ecc
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dy_px", "dx_px", "seed"),
    [(1.7, -0.4, 101), (-0.35, 0.8, 102)],
)
def test_refine_ecc_recovers_fractional_shift(dy_px: float, dx_px: float, seed: int) -> None:
    shape = (121, 121)  # odd x odd: sidesteps the even-axis Nyquist-bin caveat
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=seed)
    source_patch, reference_patch, base = _extract_matching_patches(
        fixture.base_image,
        fixture.shifted_image,
        center=(60.0, 60.0),
        half_size=20,
        dy_px=dy_px,
        dx_px=dx_px,
    )

    result = refine_ecc(
        source_patch,
        reference_patch,
        initial_shift_px=(float(base[0]), float(base[1])),
        max_iterations=50,
        convergence_threshold=1e-8,
    )

    assert result.converged
    assert (
        np.hypot(result.refined_shift_px[0] - dy_px, result.refined_shift_px[1] - dx_px)
        < _ECC_TOLERANCE_PX
    )
    assert result.final_correlation > 0.99


def test_refine_ecc_convergence_failure_is_honestly_reported() -> None:
    shape = (121, 121)
    dy_px, dx_px = 2.4, -1.6  # residual after rounding the base is 0.4-ish, more than one
    # very-limited-iteration Newton step reliably closes from a zero start.
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=103)
    source_patch, reference_patch, base = _extract_matching_patches(
        fixture.base_image,
        fixture.shifted_image,
        center=(60.0, 60.0),
        half_size=20,
        dy_px=dy_px,
        dx_px=dx_px,
    )

    result = refine_ecc(
        source_patch,
        reference_patch,
        initial_shift_px=(float(base[0]), float(base[1])),
        max_iterations=1,
        convergence_threshold=1e-10,
    )

    assert result.iterations_used == 1
    assert not result.converged


def test_refine_ecc_is_deterministic() -> None:
    shape = (81, 81)
    fixture = generate_controlled_shift_fixture(shape, dy_px=0.6, dx_px=-0.3, seed=104)
    source_patch, reference_patch, base = _extract_matching_patches(
        fixture.base_image,
        fixture.shifted_image,
        center=(40.0, 40.0),
        half_size=15,
        dy_px=0.6,
        dx_px=-0.3,
    )

    initial_shift_px = (float(base[0]), float(base[1]))
    first = refine_ecc(
        source_patch,
        reference_patch,
        initial_shift_px=initial_shift_px,
        max_iterations=25,
        convergence_threshold=1e-8,
    )
    second = refine_ecc(
        source_patch,
        reference_patch,
        initial_shift_px=initial_shift_px,
        max_iterations=25,
        convergence_threshold=1e-8,
    )

    assert isinstance(first, EccRefinementResult)
    assert first == second


# ---------------------------------------------------------------------------
# refine_fourier_upsampled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dy_px", "dx_px", "seed"),
    [(1.7, -0.4, 201), (-0.35, 0.8, 202)],
)
def test_refine_fourier_upsampled_recovers_fractional_shift(
    dy_px: float, dx_px: float, seed: int
) -> None:
    shape = (121, 121)
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=seed)
    source_patch, reference_patch, base = _extract_matching_patches(
        fixture.base_image,
        fixture.shifted_image,
        center=(60.0, 60.0),
        half_size=20,
        dy_px=dy_px,
        dx_px=dx_px,
    )

    result = refine_fourier_upsampled(
        source_patch,
        reference_patch,
        initial_shift_px=(float(base[0]), float(base[1])),
        upsample_factor=_UPSAMPLE_FACTOR,
    )

    error = np.hypot(result.refined_shift_px[0] - dy_px, result.refined_shift_px[1] - dx_px)
    assert error < _FOURIER_TOLERANCE_PX


def test_refine_fourier_upsampled_is_deterministic() -> None:
    shape = (81, 81)
    fixture = generate_controlled_shift_fixture(shape, dy_px=0.6, dx_px=-0.3, seed=203)
    source_patch, reference_patch, base = _extract_matching_patches(
        fixture.base_image,
        fixture.shifted_image,
        center=(40.0, 40.0),
        half_size=15,
        dy_px=0.6,
        dx_px=-0.3,
    )

    initial_shift_px = (float(base[0]), float(base[1]))
    first = refine_fourier_upsampled(
        source_patch,
        reference_patch,
        initial_shift_px=initial_shift_px,
        upsample_factor=_UPSAMPLE_FACTOR,
    )
    second = refine_fourier_upsampled(
        source_patch,
        reference_patch,
        initial_shift_px=initial_shift_px,
        upsample_factor=_UPSAMPLE_FACTOR,
    )

    assert isinstance(first, FourierRefinementResult)
    assert first == second


def test_peak_ambiguity_is_worse_for_a_periodic_patch_than_a_well_textured_one() -> None:
    shape = (81, 81)
    half_size = 15
    center = (40.0, 40.0)
    dy_px, dx_px = 0.4, -0.3
    base = (round(dy_px), round(dx_px))

    # A well-textured, non-periodic patch (Task 7's generate_base_pattern
    # deliberately uses non-integer cycle counts so it is not periodic within
    # its own extent).
    textured_fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=301)
    textured_source, textured_reference, _ = _extract_matching_patches(
        textured_fixture.base_image,
        textured_fixture.shifted_image,
        center=center,
        half_size=half_size,
        dy_px=dy_px,
        dx_px=dx_px,
    )
    textured_result = refine_fourier_upsampled(
        textured_source,
        textured_reference,
        initial_shift_px=(float(base[0]), float(base[1])),
        upsample_factor=_UPSAMPLE_FACTOR,
    )

    # A genuinely periodic patch: an exact-integer-cycle-count sinusoid tiles
    # perfectly within its own extent, so shifting it by one period looks
    # identical to no shift at all -- a textbook ambiguous match.
    row = np.arange(shape[0], dtype=np.float64).reshape(-1, 1)
    col = np.arange(shape[1], dtype=np.float64).reshape(1, -1)
    periodic_base_image = np.sin(2.0 * np.pi * 4.0 * row / shape[0]) * np.sin(
        2.0 * np.pi * 4.0 * col / shape[1]
    )
    from benchmarks.scripts.controlled_shift import shift_image

    periodic_shifted_image = shift_image(periodic_base_image, dy_px=dy_px, dx_px=dx_px)
    periodic_source, periodic_reference, _ = _extract_matching_patches(
        periodic_base_image,
        periodic_shifted_image,
        center=center,
        half_size=half_size,
        dy_px=dy_px,
        dx_px=dx_px,
    )
    periodic_result = refine_fourier_upsampled(
        periodic_source,
        periodic_reference,
        initial_shift_px=(float(base[0]), float(base[1])),
        upsample_factor=_UPSAMPLE_FACTOR,
    )

    assert periodic_result.peak_ambiguity < textured_result.peak_ambiguity


# ---------------------------------------------------------------------------
# refine_correspondence
# ---------------------------------------------------------------------------


def test_refine_correspondence_happy_path_recovers_true_shift() -> None:
    shape = (121, 121)
    dy_px, dx_px = 1.7, -0.4
    fixture = generate_controlled_shift_fixture(shape, dy_px=dy_px, dx_px=dx_px, seed=401)
    base = (round(dy_px), round(dx_px))
    source_pixel = SourcePixel(line=60.0, sample=60.0)
    reference_pixel = ReferencePixel(
        line=60.0 + base[0],
        sample=60.0 + base[1],
    )
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


def test_refine_correspondence_patch_extraction_failure_is_explicit() -> None:
    shape = (60, 60)
    image = generate_base_pattern(shape, seed=402)
    source_pixel = SourcePixel(line=2.0, sample=30.0)  # too close to the top edge
    reference_pixel = ReferencePixel(line=2.0, sample=30.0)
    record = _record(source_pixel=source_pixel, reference_pixel=reference_pixel)

    refined = refine_correspondence(
        record,
        image,
        image,
        source_mask=None,
        reference_mask=None,
        patch_half_size=20,
        ecc_max_iterations=50,
        ecc_convergence_threshold=1e-8,
        fourier_upsample_factor=_UPSAMPLE_FACTOR,
        min_patch_texture=1e-6,
    )

    assert refined.refined_location is None
    assert refined.estimator_identities == ()
    assert refined.estimator_disagreement_px is None
    assert refined.rejection_reason is not None
    assert refined.rejection_reason.startswith("refinement patch extraction failed")


def test_refine_correspondence_low_texture_rejection_is_distinct_from_extraction_failure() -> None:
    shape = (60, 60)
    flat_image = np.full(shape, 0.5)
    source_pixel = SourcePixel(line=30.0, sample=30.0)  # well inside bounds
    reference_pixel = ReferencePixel(line=30.0, sample=30.0)
    record = _record(source_pixel=source_pixel, reference_pixel=reference_pixel)

    refined = refine_correspondence(
        record,
        flat_image,
        flat_image,
        source_mask=None,
        reference_mask=None,
        patch_half_size=10,
        ecc_max_iterations=50,
        ecc_convergence_threshold=1e-8,
        fourier_upsample_factor=_UPSAMPLE_FACTOR,
        min_patch_texture=1e-6,
    )

    assert refined.refined_location is None
    assert refined.estimator_identities == ()
    assert refined.estimator_disagreement_px is None
    assert refined.rejection_reason is not None
    assert refined.rejection_reason.startswith("refinement skipped: low patch texture")
    assert "extraction failed" not in refined.rejection_reason
