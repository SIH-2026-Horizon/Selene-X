"""Tests for the CSV correspondence catalogue writer and reader (WP-09 task 3,
CSV half; plan section 6.4).

The central proof is exact round-trip equality: write a tuple of
CorrespondenceRecord, read it back, and the result must equal the original
records field-for-field, including every nested type, every enum member, and
every None left as None.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from selene_core.hashing import digest_file
from selene_core.match.correspondence import CorrespondenceRecord, NmsStatus, PointRole
from selene_core.products.correspondence_catalogue import (
    CsvWriteResult,
    DestinationDirectoryMissingError,
    IdentityDelimiterCollisionError,
    read_correspondence_csv,
    write_correspondence_csv,
)
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
        "input_digest": _VALID_SHA256,
        "reference_digest": _VALID_SHA256_B,
        "parameter_set_digest": _VALID_SHA256_C,
    }


def _fully_populated_record(**overrides: Any) -> CorrespondenceRecord:
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
    kwargs: dict[str, Any] = {
        "match_id": "round-trip-id",
        "job_id": "job-42",
        "algorithm": "ncc",
        "algorithm_version": "2.1",
        "tile_id": None,
        "pyramid_level": None,
        "selection_reason": "highest score in cell",
        "source_pixel": SourcePixel(line=5.0, sample=6.0),
        "reference_pixel": ReferencePixel(line=5.5, sample=6.5),
        "ground_coordinate": ground,
        "raw_score": 0.87,
        "calibrated_confidence": 0.75,
        "descriptor_channel_agreement": 0.6,
        "forward_backward_error_px": 0.2,
        "prior_displacement_px": (0.5, -0.5),
        "residual_from_prior_px": (0.1, -0.1),
        "robust_model_residual_px": 0.3,
        "local_warp_jacobian": jacobian,
        "coarse_location": SourcePixel(line=4.9, sample=5.9),
        "refined_location": SourcePixel(line=5.0, sample=6.0),
        "estimator_identities": ("ransac", "lmeds"),
        "estimator_disagreement_px": 0.05,
        "covariance": covariance,
        "covariance_method": "monte_carlo",
        "covariance_calibrated": True,
        "is_candidate": True,
        "is_inlier": True,
        "point_role": PointRole.FITTING_INLIER,
        "rejection_reason": "suppressed in favour of a stronger nearby candidate",
        "nms_status": NmsStatus.SURVIVED,
        "eligible_cell_id": "cell-3-4",
        "grid_level": 2,
        "selected_for_coverage": True,
        "coverage_selection_rationale": "best in cell",
        "input_digest": _VALID_SHA256,
        "reference_digest": _VALID_SHA256_B,
        "parameter_set_digest": _VALID_SHA256_C,
        "code_revision": "deadbeef",
    }
    kwargs.update(overrides)
    return CorrespondenceRecord(**kwargs)


class TestRoundTripMinimal:
    def test_minimal_record_round_trips_exactly(self, tmp_path: Path) -> None:
        original = CorrespondenceRecord(**_minimal_kwargs())
        destination = tmp_path / "catalogue.csv"

        write_correspondence_csv((original,), destination)
        restored = read_correspondence_csv(destination)

        assert restored == (original,)


class TestRoundTripFullyPopulated:
    def test_fully_populated_record_round_trips_exactly(self, tmp_path: Path) -> None:
        original = _fully_populated_record()
        destination = tmp_path / "catalogue.csv"

        write_correspondence_csv((original,), destination)
        restored = read_correspondence_csv(destination)

        assert restored == (original,)

    @pytest.mark.parametrize("role", list(PointRole))
    def test_every_point_role_member_round_trips(self, tmp_path: Path, role: PointRole) -> None:
        is_candidate = role in {
            PointRole.TRAINING,
            PointRole.FITTING_INLIER,
            PointRole.WITHHELD_CHECK_POINT,
        }
        original = _fully_populated_record(
            point_role=role, is_candidate=is_candidate, is_inlier=False
        )
        destination = tmp_path / f"catalogue-{role.value}.csv"

        write_correspondence_csv((original,), destination)
        restored = read_correspondence_csv(destination)

        assert restored == (original,)
        assert restored[0].point_role is role

    @pytest.mark.parametrize("status", list(NmsStatus))
    def test_every_nms_status_member_round_trips(self, tmp_path: Path, status: NmsStatus) -> None:
        original = _fully_populated_record(nms_status=status)
        destination = tmp_path / f"catalogue-{status.value}.csv"

        write_correspondence_csv((original,), destination)
        restored = read_correspondence_csv(destination)

        assert restored == (original,)
        assert restored[0].nms_status is status


class TestRoundTripMixedNonePatterns:
    def test_mixed_none_and_set_fields_do_not_cross_contaminate(self, tmp_path: Path) -> None:
        all_none = CorrespondenceRecord(**_minimal_kwargs())
        all_set = _fully_populated_record(match_id="all-set-id")
        partially_set = _fully_populated_record(
            match_id="partial-id",
            ground_coordinate=None,
            covariance=None,
            covariance_calibrated=False,
            local_warp_jacobian=None,
            coarse_location=None,
            refined_location=None,
            prior_displacement_px=None,
            residual_from_prior_px=None,
            estimator_identities=(),
            nms_status=None,
            tile_id="tile-9",
            pyramid_level=3,
        )
        destination = tmp_path / "catalogue.csv"

        result = write_correspondence_csv((all_none, all_set, partially_set), destination)
        restored = read_correspondence_csv(destination)

        assert result.row_count == 3
        assert restored == (all_none, all_set, partially_set)
        # No cross-contamination: each record's None/non-None pattern survives
        # independently in its own row.
        assert restored[0].ground_coordinate is None
        assert restored[0].covariance is None
        assert restored[1].ground_coordinate is not None
        assert restored[1].covariance is not None
        assert restored[2].ground_coordinate is None
        assert restored[2].covariance is None
        assert restored[2].tile_id == "tile-9"
        assert restored[2].pyramid_level == 3
        assert isinstance(restored[2].pyramid_level, int)
        assert restored[2].estimator_identities == ()


class TestEmptyTuple:
    def test_empty_records_writes_header_only_and_reads_back_empty(self, tmp_path: Path) -> None:
        destination = tmp_path / "catalogue.csv"

        result = write_correspondence_csv((), destination)

        assert result.row_count == 0
        assert destination.exists()
        lines = destination.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1  # header only
        assert read_correspondence_csv(destination) == ()


class TestAtomicity:
    def test_failure_mid_publish_leaves_stale_content_and_no_partial_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate a failure between temp-file creation and final publish by
        making os.replace (the step that performs the atomic rename) raise.
        The destination must keep its original stale content and no
        `.partial` scratch file must remain in the directory."""
        destination = tmp_path / "catalogue.csv"
        destination.write_text("stale content", encoding="utf-8")

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated failure during publish")

        monkeypatch.setattr("selene_core.products.correspondence_catalogue.os.replace", _boom)

        original = CorrespondenceRecord(**_minimal_kwargs())
        with pytest.raises(OSError, match="simulated failure during publish"):
            write_correspondence_csv((original,), destination)

        assert destination.read_text(encoding="utf-8") == "stale content"
        assert list(tmp_path.glob(".*partial")) == []


class TestMissingParentDirectory:
    def test_nonexistent_parent_directory_raises_documented_error(self, tmp_path: Path) -> None:
        destination = tmp_path / "does-not-exist" / "catalogue.csv"
        original = CorrespondenceRecord(**_minimal_kwargs())

        with pytest.raises(DestinationDirectoryMissingError, match="does not exist"):
            write_correspondence_csv((original,), destination)

        assert not destination.exists()


class TestCsvWriteResultChecksum:
    def test_sha256_matches_independently_computed_digest(self, tmp_path: Path) -> None:
        destination = tmp_path / "catalogue.csv"
        original = _fully_populated_record()

        result = write_correspondence_csv((original,), destination)

        assert isinstance(result, CsvWriteResult)
        assert result.sha256 == digest_file(destination)


class TestDelimiterCollision:
    def test_identity_containing_delimiter_is_rejected_explicitly(self, tmp_path: Path) -> None:
        """This module's documented behaviour is to reject rather than
        silently join-and-corrupt an estimator identity that contains the
        tuple delimiter (";")."""
        original = _fully_populated_record(estimator_identities=("ransac;evil", "lmeds"))
        destination = tmp_path / "catalogue.csv"

        with pytest.raises(IdentityDelimiterCollisionError, match="ransac;evil"):
            write_correspondence_csv((original,), destination)

        assert not destination.exists()
