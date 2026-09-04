"""Focused tests for the deterministic, non-qualified local registration route."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from benchmarks.scripts.controlled_shift import generate_controlled_shift_fixture

from selene_core.adjust import (
    ObservationLinearization,
    fit_adjustment,
    translation_only_parameterization,
)
from selene_core.match import MatchParameters, MatchPrior
from selene_core.pipeline.local_registration import (
    LocalRegistrationConfig,
    PipelineDisposition,
    PipelineOrigin,
    PipelineProvenance,
    run_local_registration,
)
from selene_core.refine.covariance import CalibrationResult

pytestmark = pytest.mark.unit


def _provenance() -> PipelineProvenance:
    return PipelineProvenance(
        job_id="local-pipeline-test",
        input_digest="a" * 64,
        reference_digest="b" * 64,
        code_revision="test-revision",
    )


def _config() -> LocalRegistrationConfig:
    return LocalRegistrationConfig(
        origin=PipelineOrigin.SYNTHETIC_TEST,
        match_parameters=MatchParameters(
            values={"grid_spacing_px": 16, "template_half_size_px": 4, "search_radius_px": 8}
        ),
        prior=MatchPrior(displacement_px=(3.0, -2.0), search_radius_px=5.0),
        grid_shape=(3, 3),
        patch_half_size_px=3,
        noise_variance=0.01,
    )


def test_successful_synthetic_plumbing_is_review_only_and_never_accepted() -> None:
    fixture = generate_controlled_shift_fixture((63, 79), dy_px=3.0, dx_px=-2.0, seed=991)

    result = run_local_registration(
        fixture.base_image, fixture.shifted_image, provenance=_provenance(), config=_config()
    )

    assert result.disposition is PipelineDisposition.REVIEW
    assert result.origin is PipelineOrigin.SYNTHETIC_TEST
    assert result.route_qualified is False
    assert result.scene_verdict.verdict == "reject"
    assert result.verified_inlier_count >= 3
    assert result.coverage is not None
    assert len(result.candidates) == len(result.correspondences)
    assert any(record.selected_for_coverage for record in result.correspondences)
    assert result.artifacts.source["shape"] == (63, 79)
    assert all(record.point_role.value != "training" for record in result.correspondences)
    assert result.model_dump(mode="json")["route_qualified"] is False


def test_invalid_mask_and_nonfinite_usable_data_fail_closed() -> None:
    image = np.ones((17, 17), dtype=np.float64)

    bad_mask = run_local_registration(
        image,
        image,
        source_mask=np.ones((16, 17), dtype=bool),
        provenance=_provenance(),
        config=_config(),
    )
    assert bad_mask.disposition is PipelineDisposition.REJECTED
    assert bad_mask.failures[0].code.value == "input.unsupported_payload"

    nonfinite = image.copy()
    nonfinite[4, 4] = np.nan
    bad_values = run_local_registration(
        nonfinite, image, provenance=_provenance(), config=_config()
    )
    assert bad_values.disposition is PipelineDisposition.REJECTED
    assert bad_values.failures[0].code.value == "input.unsupported_payload"


def test_correspondence_and_coverage_selection_are_deterministic() -> None:
    fixture = generate_controlled_shift_fixture((63, 79), dy_px=3.0, dx_px=-2.0, seed=992)
    kwargs = dict(provenance=_provenance(), config=_config())

    first = run_local_registration(fixture.base_image, fixture.shifted_image, **kwargs)
    second = run_local_registration(fixture.base_image, fixture.shifted_image, **kwargs)

    def summary(result: object) -> list[tuple[float, float, str | None, bool]]:
        pipeline_result = result  # keep type checkers from widening the assertion expression
        return [
            (
                record.source_pixel.line,
                record.source_pixel.sample,
                record.eligible_cell_id,
                record.selected_for_coverage,
            )
            for record in pipeline_result.correspondences
        ]

    assert summary(first) == summary(second)
    assert first.coverage is not None and second.coverage is not None
    assert first.coverage.per_cell_candidate_counts == second.coverage.per_cell_candidate_counts
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_unequal_image_dimensions_use_normalized_mask_eligibility_safely() -> None:
    fixture = generate_controlled_shift_fixture((63, 79), dy_px=3.0, dx_px=-2.0, seed=993)
    larger_reference = np.pad(fixture.shifted_image, ((0, 12), (0, 12)))

    result = run_local_registration(
        fixture.base_image,
        larger_reference,
        provenance=_provenance(),
        config=_config(),
    )

    assert result.disposition is PipelineDisposition.REVIEW
    assert result.coverage is not None
    assert result.coverage.eligible_cell_count == 9
    assert "normalized_reference" in result.parameters.contents["coverage"]["eligibility_strategy"]


def test_resolved_parameter_provenance_changes_with_coverage_configuration() -> None:
    fixture = generate_controlled_shift_fixture((63, 79), dy_px=3.0, dx_px=-2.0, seed=994)
    baseline = run_local_registration(
        fixture.base_image, fixture.shifted_image, provenance=_provenance(), config=_config()
    )
    changed = run_local_registration(
        fixture.base_image,
        fixture.shifted_image,
        provenance=_provenance(),
        config=replace(_config(), quality_floor=0.25),
    )

    assert baseline.parameters.digest != changed.parameters.digest
    assert baseline.parameters.contents["coverage"]["quality_floor"] == 0.0
    assert changed.parameters.contents["coverage"]["quality_floor"] == 0.25
    baseline_coverage = next(
        stage for stage in baseline.stages if stage.name == "coverage_selection"
    )
    changed_coverage = next(stage for stage in changed.stages if stage.name == "coverage_selection")
    assert baseline_coverage.parameter_digest != changed_coverage.parameter_digest


def test_adjustment_uses_calibrated_refined_fractional_displacements() -> None:
    true_shift = (3.25, -2.25)
    fixture = generate_controlled_shift_fixture(
        (63, 79), dy_px=true_shift[0], dx_px=true_shift[1], seed=995
    )
    result = run_local_registration(
        fixture.base_image,
        fixture.shifted_image,
        provenance=_provenance(),
        config=replace(
            _config(),
            prior=MatchPrior(displacement_px=true_shift, search_radius_px=5.0),
            covariance_calibration=CalibrationResult(
                scale_factor=1.0,
                n_trials=10,
                empirical_coverage_at_1sigma=0.3,
                calibrated_coverage_at_1sigma=0.3,
            ),
        ),
    )

    fitting = tuple(
        record for record in result.correspondences if record.point_role.value == "fitting_inlier"
    )
    expected = fit_adjustment(
        fitting,
        tuple(
            ObservationLinearization(
                observation_id=record.match_id,
                source_residual_yx_px=(
                    record.refined_location.line - record.source_pixel.line,
                    record.refined_location.sample - record.source_pixel.sample,
                ),
                design_matrix_yx_by_parameter=np.eye(2, dtype=np.float64),
            )
            for record in fitting
        ),
        translation_only_parameterization(),
    )
    observed = result.adjustment.result["parameter_values"]

    assert result.adjustment.status == "accepted"
    assert expected.parameter_values is not None
    assert observed == pytest.approx(expected.parameter_values, abs=1e-12)
    assert observed != pytest.approx((3.0, -2.0), abs=0.05)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_config_rejects_nonfinite_refinement_thresholds(value: float) -> None:
    with pytest.raises(ValueError, match="ecc_convergence_threshold"):
        LocalRegistrationConfig(ecc_convergence_threshold=value)
    with pytest.raises(ValueError, match="min_patch_texture"):
        LocalRegistrationConfig(min_patch_texture=value)


def test_no_accepted_verdict_when_matching_cannot_produce_verified_geometry() -> None:
    image = np.ones((17, 17), dtype=np.float64)

    result = run_local_registration(image, image, provenance=_provenance(), config=_config())

    assert result.disposition is PipelineDisposition.REJECTED
    assert result.scene_verdict.verdict == "reject"
    assert any(
        failure.code.value == "matching.insufficient_candidates" for failure in result.failures
    )
