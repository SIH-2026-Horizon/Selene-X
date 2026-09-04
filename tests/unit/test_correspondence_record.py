"""Tests for CorrespondenceRecord (plan section 6.4, WP-01 task 5, WP-04 task 1)."""

from __future__ import annotations

from typing import Any

import pytest

from selene_core.match.correspondence import CorrespondenceRecord, NmsStatus, PointRole
from selene_core.types import (
    Covariance2D,
    CovarianceFrame,
    LocalWarpJacobian,
    MapCoordinate,
    ReferencePixel,
    SourcePixel,
)

pytestmark = pytest.mark.unit

_VALID_SHA256 = "a" * 64
_VALID_SHA256_B = "b" * 64
_VALID_SHA256_C = "c" * 64


def _minimal_kwargs() -> dict[str, Any]:
    return {
        "job_id": "job-1",
        "algorithm": "phase_correlation",
        "algorithm_version": "1.0",
        "source_pixel": SourcePixel(line=10.0, sample=20.0),
        "reference_pixel": ReferencePixel(line=11.0, sample=21.0),
        "raw_score": 0.9,
        "selected_for_coverage": False,
        "input_digest": _VALID_SHA256,
        "reference_digest": _VALID_SHA256_B,
        "parameter_set_digest": _VALID_SHA256_C,
    }


class TestMinimalConstruction:
    def test_minimal_valid_record_succeeds(self) -> None:
        record = CorrespondenceRecord(**_minimal_kwargs())

        assert record.job_id == "job-1"
        assert record.algorithm == "phase_correlation"
        assert record.point_role is PointRole.CANDIDATE
        assert record.is_candidate is False
        assert record.is_inlier is False
        assert record.tile_id is None
        assert record.pyramid_level is None

    def test_match_id_is_auto_generated_when_omitted(self) -> None:
        record = CorrespondenceRecord(**_minimal_kwargs())

        assert isinstance(record.match_id, str)
        assert record.match_id != ""

    def test_match_id_can_be_caller_supplied(self) -> None:
        record = CorrespondenceRecord(match_id="caller-chosen-id", **_minimal_kwargs())

        assert record.match_id == "caller-chosen-id"


class TestIsInlierRequiresCandidate:
    def test_inlier_true_with_candidate_false_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="is_inlier=True requires is_candidate=True"):
            CorrespondenceRecord(is_candidate=False, is_inlier=True, **_minimal_kwargs())

    def test_inlier_true_with_candidate_true_succeeds(self) -> None:
        record = CorrespondenceRecord(is_candidate=True, is_inlier=True, **_minimal_kwargs())

        assert record.is_candidate is True
        assert record.is_inlier is True


class TestPointRoleRequiresCandidate:
    def test_fitting_inlier_with_candidate_false_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires is_candidate=True"):
            CorrespondenceRecord(
                is_candidate=False,
                point_role=PointRole.FITTING_INLIER,
                **_minimal_kwargs(),
            )

    def test_fitting_inlier_with_candidate_true_succeeds(self) -> None:
        record = CorrespondenceRecord(
            is_candidate=True,
            point_role=PointRole.FITTING_INLIER,
            **_minimal_kwargs(),
        )

        assert record.point_role is PointRole.FITTING_INLIER

    def test_training_with_candidate_false_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires is_candidate=True"):
            CorrespondenceRecord(
                is_candidate=False, point_role=PointRole.TRAINING, **_minimal_kwargs()
            )

    def test_withheld_check_point_with_candidate_false_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires is_candidate=True"):
            CorrespondenceRecord(
                is_candidate=False,
                point_role=PointRole.WITHHELD_CHECK_POINT,
                **_minimal_kwargs(),
            )

    def test_rejected_role_does_not_require_candidate(self) -> None:
        """REJECTED is deliberately not in the role/candidate coupling: a point
        can be rejected without ever having been marked a candidate."""
        record = CorrespondenceRecord(
            is_candidate=False, point_role=PointRole.REJECTED, **_minimal_kwargs()
        )

        assert record.point_role is PointRole.REJECTED

    def test_candidate_role_does_not_require_is_candidate(self) -> None:
        """CANDIDATE is the not-yet-classified role and is the default."""
        record = CorrespondenceRecord(
            is_candidate=False, point_role=PointRole.CANDIDATE, **_minimal_kwargs()
        )

        assert record.point_role is PointRole.CANDIDATE


class TestCovarianceCalibratedRequiresCovariance:
    def test_calibrated_true_with_no_covariance_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="covariance_calibrated=True requires covariance"):
            CorrespondenceRecord(covariance_calibrated=True, covariance=None, **_minimal_kwargs())

    def test_calibrated_true_with_real_covariance_succeeds(self) -> None:
        covariance = Covariance2D(
            xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
        )
        record = CorrespondenceRecord(
            covariance_calibrated=True, covariance=covariance, **_minimal_kwargs()
        )

        assert record.covariance_calibrated is True
        assert record.covariance == covariance

    def test_calibrated_false_with_no_covariance_is_the_default(self) -> None:
        record = CorrespondenceRecord(**_minimal_kwargs())

        assert record.covariance_calibrated is False
        assert record.covariance is None


class TestDigestValidation:
    @pytest.mark.parametrize(
        "field_name", ["input_digest", "reference_digest", "parameter_set_digest"]
    )
    def test_non_sha256_digest_is_rejected(self, field_name: str) -> None:
        kwargs = _minimal_kwargs()
        kwargs[field_name] = "not-a-real-digest"

        with pytest.raises(ValueError, match=f"{field_name} must be a SHA-256 hex digest"):
            CorrespondenceRecord(**kwargs)

    @pytest.mark.parametrize(
        "field_name", ["input_digest", "reference_digest", "parameter_set_digest"]
    )
    def test_real_sha256_digest_is_accepted(self, field_name: str) -> None:
        kwargs = _minimal_kwargs()
        kwargs[field_name] = "f" * 64

        record = CorrespondenceRecord(**kwargs)

        assert getattr(record, field_name) == "f" * 64


class TestRoundTrip:
    def test_full_round_trip_preserves_every_field(self) -> None:
        covariance = Covariance2D(
            xx=2.0, xy=0.5, yy=3.0, frame=CovarianceFrame.REFERENCE_PIXEL, units="px2"
        )
        jacobian = LocalWarpJacobian(
            d_ref_line_d_src_line=1.0,
            d_ref_line_d_src_sample=0.01,
            d_ref_sample_d_src_line=-0.01,
            d_ref_sample_d_src_sample=1.0,
        )
        ground = MapCoordinate(x_m=100.0, y_m=200.0, crs_wkt="EPSG:104903")

        original = CorrespondenceRecord(
            match_id="round-trip-id",
            job_id="job-42",
            algorithm="ncc",
            algorithm_version="2.1",
            tile_id=None,
            pyramid_level=None,
            selection_reason="highest score in cell",
            source_pixel=SourcePixel(line=5.0, sample=6.0),
            reference_pixel=ReferencePixel(line=5.5, sample=6.5),
            ground_coordinate=ground,
            raw_score=0.87,
            calibrated_confidence=0.75,
            descriptor_channel_agreement=0.6,
            forward_backward_error_px=0.2,
            prior_displacement_px=(0.5, -0.5),
            residual_from_prior_px=(0.1, -0.1),
            robust_model_residual_px=0.3,
            local_warp_jacobian=jacobian,
            coarse_location=SourcePixel(line=4.9, sample=5.9),
            refined_location=SourcePixel(line=5.0, sample=6.0),
            estimator_identities=("ransac", "lmeds"),
            estimator_disagreement_px=0.05,
            covariance=covariance,
            covariance_method="monte_carlo",
            covariance_calibrated=True,
            is_candidate=True,
            is_inlier=True,
            point_role=PointRole.FITTING_INLIER,
            rejection_reason=None,
            nms_status=NmsStatus.SURVIVED,
            eligible_cell_id="cell-3-4",
            grid_level=2,
            selected_for_coverage=True,
            coverage_selection_rationale="best in cell",
            input_digest=_VALID_SHA256,
            reference_digest=_VALID_SHA256_B,
            parameter_set_digest=_VALID_SHA256_C,
            code_revision="deadbeef",
        )

        restored = CorrespondenceRecord.model_validate_json(original.model_dump_json())

        assert restored == original
        assert restored.ground_coordinate == ground
        assert restored.local_warp_jacobian == jacobian
        assert restored.covariance == covariance


class TestEnumMembersAreAllConstructible:
    @pytest.mark.parametrize("role", list(PointRole))
    def test_every_point_role_member_is_constructible_in_a_valid_record(
        self, role: PointRole
    ) -> None:
        is_candidate = role in {
            PointRole.TRAINING,
            PointRole.FITTING_INLIER,
            PointRole.WITHHELD_CHECK_POINT,
        }
        record = CorrespondenceRecord(
            is_candidate=is_candidate, point_role=role, **_minimal_kwargs()
        )

        assert record.point_role is role

    @pytest.mark.parametrize("status", list(NmsStatus))
    def test_every_nms_status_member_is_constructible_in_a_valid_record(
        self, status: NmsStatus
    ) -> None:
        record = CorrespondenceRecord(nms_status=status, **_minimal_kwargs())

        assert record.nms_status is status
