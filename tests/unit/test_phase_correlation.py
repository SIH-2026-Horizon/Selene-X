"""Tests for the coarse phase-correlation matcher (WP-04 task 2)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest
from benchmarks.scripts.controlled_shift import (
    generate_base_pattern,
    generate_controlled_shift_fixture,
    shift_image,
)

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.phase_correlation import PhaseCorrelationMatcher
from selene_core.match.protocol import Matcher, MatchParameters, MatchPrior

pytestmark = pytest.mark.unit

_SHAPE = (63, 79)  # odd and non-square, so neither Nyquist nor axis symmetry can hide a bug
_INPUT_DIGEST = "a" * 64
_REFERENCE_DIGEST = "b" * 64
_INTEGER_PIXEL_ATOL = 1e-12


def _match(
    source: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    *,
    source_mask: npt.NDArray[np.bool_] | None = None,
    reference_mask: npt.NDArray[np.bool_] | None = None,
    prior: MatchPrior | None = None,
) -> CorrespondenceRecord:
    return PhaseCorrelationMatcher().match(
        source,
        reference,
        source_mask=source_mask,
        reference_mask=reference_mask,
        prior=prior or MatchPrior(),
        parameters=MatchParameters(values={"normalization": "cross_power"}),
        job_id="phase-job",
        input_digest=_INPUT_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )[0]


def _displacement(record: CorrespondenceRecord) -> tuple[float, float]:
    return (
        record.reference_pixel.line - record.source_pixel.line,
        record.reference_pixel.sample - record.source_pixel.sample,
    )


@pytest.mark.parametrize(
    ("dy_px", "dx_px", "seed"),
    [(5.0, -3.0, 7), (-6.0, -4.0, 17), (0.0, 0.0, 23)],
)
def test_recovers_integer_controlled_shift_exactly(dy_px: float, dx_px: float, seed: int) -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=dy_px, dx_px=dx_px, seed=seed)

    record = _match(fixture.base_image, fixture.shifted_image)

    # The matcher searches integer FFT bins, so only float representation of
    # an exact integer coordinate is involved. 1e-12 px allows harmless
    # arithmetic roundoff while rejecting any wrong coarse-pixel result.
    assert np.allclose(_displacement(record), (dy_px, dx_px), atol=_INTEGER_PIXEL_ATOL)


def test_mismatched_shapes_raise_a_specific_error() -> None:
    with pytest.raises(ValueError, match="requires source and reference to have identical shapes"):
        _match(np.zeros((9, 11)), np.zeros((9, 13)))


def test_prior_that_excludes_true_peak_restricts_the_search() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=5.0, dx_px=-3.0, seed=29)
    prior = MatchPrior(displacement_px=(0.0, 0.0), search_radius_px=2.0)

    record = _match(fixture.base_image, fixture.shifted_image, prior=prior)
    recovered = _displacement(record)

    assert recovered != (5.0, -3.0)
    assert np.hypot(*recovered) <= 2.0


def test_prior_can_select_true_peak_over_stronger_out_of_radius_peak() -> None:
    source = generate_base_pattern(_SHAPE, seed=31)
    true_shift = (4.0, -3.0)
    false_shift = (-12.0, 9.0)
    reference = 0.35 * shift_image(source, dy_px=true_shift[0], dx_px=true_shift[1]) + shift_image(
        source, dy_px=false_shift[0], dx_px=false_shift[1]
    )

    unrestricted = _match(source, reference)
    restricted = _match(
        source,
        reference,
        prior=MatchPrior(displacement_px=true_shift, search_radius_px=2.0),
    )

    assert _displacement(unrestricted) == false_shift
    assert _displacement(restricted) == true_shift


def test_masked_region_does_not_become_the_match_feature() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=5.0, dx_px=-3.0, seed=37)
    source_mask = np.ones(_SHAPE, dtype=np.bool_)
    reference_mask = np.ones(_SHAPE, dtype=np.bool_)
    source_mask[:, :30] = False
    reference_mask[:, :30] = False

    record = _match(
        fixture.base_image,
        fixture.shifted_image,
        source_mask=source_mask,
        reference_mask=reference_mask,
    )

    assert np.allclose(_displacement(record), (5.0, -3.0), atol=_INTEGER_PIXEL_ATOL)


def test_record_is_auditable_candidate_with_expected_provenance() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=2.0, dx_px=1.0, seed=41)
    matcher = PhaseCorrelationMatcher()

    record = _match(fixture.base_image, fixture.shifted_image)

    assert isinstance(matcher, Matcher)
    assert record.point_role == PointRole.CANDIDATE
    assert record.is_candidate is True
    assert record.algorithm == "phase_correlation"
    assert record.job_id == "phase-job"
    assert record.input_digest == _INPUT_DIGEST
    assert record.reference_digest == _REFERENCE_DIGEST
    assert (
        record.parameter_set_digest
        == MatchParameters(values={"normalization": "cross_power"}).parameter_set_digest
    )
