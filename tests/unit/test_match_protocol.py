"""Tests for MatchPrior, MatchParameters, and the Matcher protocol (WP-04 task 1)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from selene_core.match.correspondence import CorrespondenceRecord
from selene_core.match.protocol import Matcher, MatchParameters, MatchPrior
from selene_core.types import ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_VALID_SHA256 = "a" * 64
_VALID_SHA256_B = "b" * 64


class TestMatchParametersDigest:
    def test_same_parameters_produce_the_same_digest_across_constructions(self) -> None:
        first = MatchParameters(values={"window_px": 32, "threshold": 0.5})
        second = MatchParameters(values={"window_px": 32, "threshold": 0.5})

        assert first.parameter_set_digest == second.parameter_set_digest

    def test_different_parameters_produce_a_different_digest(self) -> None:
        first = MatchParameters(values={"window_px": 32, "threshold": 0.5})
        second = MatchParameters(values={"window_px": 64, "threshold": 0.5})

        assert first.parameter_set_digest != second.parameter_set_digest

    def test_empty_parameters_still_produce_a_digest(self) -> None:
        parameters = MatchParameters()

        assert isinstance(parameters.parameter_set_digest, str)
        assert len(parameters.parameter_set_digest) == 64

    def test_values_is_immutable_after_construction(self) -> None:
        source = {"window_px": 32}
        parameters = MatchParameters(values=source)
        source["window_px"] = 999

        assert parameters.values["window_px"] == 32
        with pytest.raises(TypeError):
            parameters.values["window_px"] = 1  # type: ignore[index]


class TestMatchPriorValidation:
    def test_defaults_are_all_none(self) -> None:
        prior = MatchPrior()

        assert prior.displacement_px is None
        assert prior.displacement_uncertainty_px is None
        assert prior.search_radius_px is None

    def test_non_positive_search_radius_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="search_radius_px must be positive"):
            MatchPrior(search_radius_px=0.0)

    def test_non_finite_displacement_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="displacement_px must be finite"):
            MatchPrior(displacement_px=(float("nan"), 0.0))

    def test_valid_prior_round_trips_its_fields(self) -> None:
        prior = MatchPrior(
            displacement_px=(1.5, -2.5),
            displacement_uncertainty_px=(0.1, 0.2),
            search_radius_px=8.0,
        )

        assert prior.displacement_px == (1.5, -2.5)
        assert prior.displacement_uncertainty_px == (0.1, 0.2)
        assert prior.search_radius_px == 8.0


class _FakeMatcher:
    """A minimal hand-written class satisfying the Matcher protocol."""

    def match(
        self,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        *,
        source_mask: npt.NDArray[np.bool_] | None,
        reference_mask: npt.NDArray[np.bool_] | None,
        prior: MatchPrior,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
    ) -> tuple[CorrespondenceRecord, ...]:
        return (
            CorrespondenceRecord(
                job_id=job_id,
                algorithm="fake",
                algorithm_version="0.0",
                source_pixel=SourcePixel(line=0.0, sample=0.0),
                reference_pixel=ReferencePixel(line=0.0, sample=0.0),
                raw_score=1.0,
                input_digest=input_digest,
                reference_digest=reference_digest,
                parameter_set_digest=parameters.parameter_set_digest,
            ),
        )


class TestMatcherProtocolConformance:
    def test_fake_matcher_is_recognized_by_isinstance(self) -> None:
        assert isinstance(_FakeMatcher(), Matcher)

    def test_object_without_match_method_is_not_recognized(self) -> None:
        class NotAMatcher:
            pass

        assert not isinstance(NotAMatcher(), Matcher)

    def test_fake_matcher_satisfies_the_call_shape(self) -> None:
        matcher: Matcher = _FakeMatcher()
        source = np.zeros((4, 4), dtype=np.float64)
        reference = np.zeros((4, 4), dtype=np.float64)

        records = matcher.match(
            source,
            reference,
            source_mask=None,
            reference_mask=None,
            prior=MatchPrior(),
            parameters=MatchParameters(values={"k": 1}),
            job_id="job-9",
            input_digest=_VALID_SHA256,
            reference_digest=_VALID_SHA256_B,
        )

        assert len(records) == 1
        assert records[0].job_id == "job-9"
        assert records[0].input_digest == _VALID_SHA256
        assert records[0].reference_digest == _VALID_SHA256_B
