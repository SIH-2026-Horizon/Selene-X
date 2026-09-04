"""Tests for the coarse local normalized-cross-correlation matcher (WP-04 task 3)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest
from benchmarks.scripts.controlled_shift import generate_controlled_shift_fixture

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.ncc import NccMatcher
from selene_core.match.protocol import Matcher, MatchParameters, MatchPrior

pytestmark = pytest.mark.unit

_SHAPE = (63, 79)
_INPUT_DIGEST = "c" * 64
_REFERENCE_DIGEST = "d" * 64
_INTEGER_PIXEL_ATOL = 1e-12


def _parameters(
    *, grid_spacing_px: int = 16, template_half_size_px: int = 5, search_radius_px: int = 8
) -> MatchParameters:
    return MatchParameters(
        values={
            "grid_spacing_px": grid_spacing_px,
            "template_half_size_px": template_half_size_px,
            "search_radius_px": search_radius_px,
        }
    )


def _match(
    source: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    *,
    source_mask: npt.NDArray[np.bool_] | None = None,
    reference_mask: npt.NDArray[np.bool_] | None = None,
    prior: MatchPrior | None = None,
    parameters: MatchParameters | None = None,
) -> tuple[CorrespondenceRecord, ...]:
    return NccMatcher().match(
        source,
        reference,
        source_mask=source_mask,
        reference_mask=reference_mask,
        prior=prior or MatchPrior(),
        parameters=parameters or _parameters(),
        job_id="ncc-job",
        input_digest=_INPUT_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )


def _displacement(record: CorrespondenceRecord) -> tuple[float, float]:
    return (
        record.reference_pixel.line - record.source_pixel.line,
        record.reference_pixel.sample - record.source_pixel.sample,
    )


def test_every_grid_match_recovers_the_integer_controlled_shift() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=5.0, dx_px=-3.0, seed=43)

    records = _match(fixture.base_image, fixture.shifted_image)

    assert len(records) == 12
    # Direct NCC searches whole-pixel patch centres. 1e-12 px permits only
    # float representation noise, not a neighbouring coarse-pixel solution.
    for record in records:
        assert np.allclose(_displacement(record), (5.0, -3.0), atol=_INTEGER_PIXEL_ATOL)
        assert record.raw_score == pytest.approx(1.0, abs=1e-12)


def test_grid_points_whose_templates_cross_the_border_are_skipped() -> None:
    fixture = generate_controlled_shift_fixture((33, 33), dy_px=0.0, dx_px=0.0, seed=47)
    parameters = _parameters(grid_spacing_px=16, template_half_size_px=4, search_radius_px=3)

    records = _match(fixture.base_image, fixture.shifted_image, parameters=parameters)

    full_grid_count = 9
    assert len(records) == 1
    assert len(records) < full_grid_count
    assert records[0].source_pixel.line == 16.0
    assert records[0].source_pixel.sample == 16.0


def test_majority_invalid_source_template_is_skipped() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=5.0, dx_px=-3.0, seed=53)
    source_mask = np.ones(_SHAPE, dtype=np.bool_)
    # This exactly covers the 11x11 template centred on (16, 16).
    source_mask[11:22, 11:22] = False

    records = _match(
        fixture.base_image,
        fixture.shifted_image,
        source_mask=source_mask,
    )

    assert len(records) == 11
    assert all(
        (record.source_pixel.line, record.source_pixel.sample) != (16.0, 16.0) for record in records
    )


def test_periodic_template_has_worse_uniqueness_than_controlled_texture() -> None:
    parameters = _parameters(grid_spacing_px=20, template_half_size_px=4, search_radius_px=8)
    controlled = generate_controlled_shift_fixture((41, 41), dy_px=3.0, dx_px=-2.0, seed=59)
    controlled_record = next(
        record
        for record in _match(
            controlled.base_image,
            controlled.shifted_image,
            parameters=parameters,
        )
        if (record.source_pixel.line, record.source_pixel.sample) == (20.0, 20.0)
    )

    line, sample = np.indices((41, 41))
    periodic = ((line + sample) % 4).astype(np.float64)
    periodic_record = next(
        record
        for record in _match(periodic, periodic, parameters=parameters)
        if (record.source_pixel.line, record.source_pixel.sample) == (20.0, 20.0)
    )

    assert periodic_record.descriptor_channel_agreement == 0.0
    assert controlled_record.descriptor_channel_agreement is not None
    assert controlled_record.descriptor_channel_agreement > (
        periodic_record.descriptor_channel_agreement
    )


def test_prior_centres_and_bounds_the_local_search() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=5.0, dx_px=-3.0, seed=61)
    prior = MatchPrior(displacement_px=(5.0, -3.0), search_radius_px=1.0)

    records = _match(fixture.base_image, fixture.shifted_image, prior=prior)

    assert records
    assert all(_displacement(record) == (5.0, -3.0) for record in records)
    assert all(record.residual_from_prior_px == (0.0, 0.0) for record in records)


def test_records_are_auditable_candidates_with_expected_provenance() -> None:
    fixture = generate_controlled_shift_fixture(_SHAPE, dy_px=2.0, dx_px=1.0, seed=67)
    parameters = _parameters()
    matcher = NccMatcher()

    records = _match(
        fixture.base_image,
        fixture.shifted_image,
        parameters=parameters,
    )

    assert isinstance(matcher, Matcher)
    assert records
    for record in records:
        assert record.point_role == PointRole.CANDIDATE
        assert record.is_candidate is True
        assert record.algorithm == "normalized_cross_correlation"
        assert record.job_id == "ncc-job"
        assert record.input_digest == _INPUT_DIGEST
        assert record.reference_digest == _REFERENCE_DIGEST
        assert record.parameter_set_digest == parameters.parameter_set_digest
