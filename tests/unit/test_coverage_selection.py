"""Tests for eligibility-grid input, deterministic grid coverage selection,
and coverage metrics (WP-07 task 4 (partial), task 6, task 9)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from selene_core.match.correspondence import CorrespondenceRecord
from selene_core.select.coverage import (
    CoverageMetrics,
    EligibilityGrid,
    compute_coverage_metrics,
    convex_hull,
    select_grid_coverage,
)
from selene_core.types import ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_VALID_SHA256 = "a" * 64
_VALID_SHA256_B = "b" * 64
_VALID_SHA256_C = "c" * 64


def _make_record(
    match_id: str,
    source: tuple[float, float],
    raw_score: float,
    *,
    is_inlier: bool = True,
    **overrides: Any,
) -> CorrespondenceRecord:
    kwargs: dict[str, Any] = {
        "match_id": match_id,
        "job_id": "job-1",
        "algorithm": "test",
        "algorithm_version": "1.0",
        "source_pixel": SourcePixel(line=source[0], sample=source[1]),
        "reference_pixel": ReferencePixel(line=source[0], sample=source[1]),
        "raw_score": raw_score,
        "is_candidate": True,
        "is_inlier": is_inlier,
        "input_digest": _VALID_SHA256,
        "reference_digest": _VALID_SHA256_B,
        "parameter_set_digest": _VALID_SHA256_C,
    }
    kwargs.update(overrides)
    return CorrespondenceRecord(**kwargs)


def _all_eligible(grid_shape: tuple[int, int]) -> EligibilityGrid:
    return EligibilityGrid(
        grid_shape=grid_shape,
        eligible=np.ones(grid_shape, dtype=np.bool_),
        exclusion_reason={},
    )


# ---------------------------------------------------------------------------
# EligibilityGrid validation
# ---------------------------------------------------------------------------


class TestEligibilityGrid:
    def test_missing_exclusion_reason_raises_naming_the_cell(self) -> None:
        eligible = np.ones((2, 2), dtype=np.bool_)
        eligible[1, 0] = False  # ineligible, but no exclusion_reason entry below

        with pytest.raises(ValueError, match=r"\(1, 0\)"):
            EligibilityGrid(grid_shape=(2, 2), eligible=eligible, exclusion_reason={})

    def test_fully_valid_grid_constructs_successfully(self) -> None:
        eligible = np.ones((2, 2), dtype=np.bool_)
        eligible[1, 0] = False

        grid = EligibilityGrid(
            grid_shape=(2, 2),
            eligible=eligible,
            exclusion_reason={(1, 0): "outside physical overlap"},
        )

        assert grid.grid_shape == (2, 2)
        assert bool(grid.eligible[1, 0]) is False

    def test_shape_mismatch_raises(self) -> None:
        eligible = np.ones((2, 2), dtype=np.bool_)

        with pytest.raises(ValueError, match="shape"):
            EligibilityGrid(grid_shape=(3, 3), eligible=eligible, exclusion_reason={})


# ---------------------------------------------------------------------------
# Convex hull
# ---------------------------------------------------------------------------


class TestConvexHull:
    def test_square_with_interior_point_excludes_interior_point(self) -> None:
        points = np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float64
        )

        hull = convex_hull(points)

        assert hull.shape == (4, 2)
        hull_set = {tuple(p) for p in hull}
        assert hull_set == {(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)}
        assert (0.5, 0.5) not in hull_set

    def test_hull_is_convex_via_cross_product_sign_consistency(self) -> None:
        points = np.array(
            [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [1.0, 1.0], [0.5, 1.5]],
            dtype=np.float64,
        )

        hull = convex_hull(points)

        n = hull.shape[0]
        assert n >= 3
        signs = []
        for i in range(n):
            a, b, c = hull[i], hull[(i + 1) % n], hull[(i + 2) % n]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            signs.append(cross > 0)
        assert all(signs) or not any(signs)  # every turn the same direction: convex

    def test_fewer_than_three_distinct_points_returns_points_themselves(self) -> None:
        points = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)

        hull = convex_hull(points)

        assert hull.shape == (2, 2)
        assert {tuple(p) for p in hull} == {(1.0, 2.0), (3.0, 4.0)}

    def test_empty_input_returns_empty_array(self) -> None:
        points = np.empty((0, 2), dtype=np.float64)

        hull = convex_hull(points)

        assert hull.shape == (0, 2)

    def test_all_collinear_points_collapse_to_two_endpoints(self) -> None:
        points = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]], dtype=np.float64)

        hull = convex_hull(points)

        assert hull.shape == (2, 2)
        assert {tuple(p) for p in hull} == {(0.0, 0.0), (3.0, 3.0)}

    def test_exactly_three_collinear_points_collapse_to_two_endpoints(self) -> None:
        points = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]], dtype=np.float64)

        hull = convex_hull(points)

        assert hull.shape == (2, 2)
        assert {tuple(p) for p in hull} == {(0.0, 0.0), (2.0, 2.0)}


# ---------------------------------------------------------------------------
# select_grid_coverage
# ---------------------------------------------------------------------------


class TestSelectGridCoverageBasic:
    def test_one_candidate_per_distinct_cell_all_selected(self) -> None:
        eligibility = _all_eligible((2, 2))
        # image_shape (100, 100), grid (2, 2): cell boundary at line/sample 50.
        record_00 = _make_record("a", (10.0, 10.0), 0.9)  # cell (0, 0)
        record_01 = _make_record("b", (10.0, 60.0), 0.9)  # cell (0, 1)
        record_10 = _make_record("c", (60.0, 10.0), 0.9)  # cell (1, 0)
        record_11 = _make_record("d", (60.0, 60.0), 0.9)  # cell (1, 1)

        result = select_grid_coverage(
            (record_00, record_01, record_10, record_11),
            eligibility=eligibility,
            image_shape=(100, 100),
            quality_floor=0.5,
        )

        by_id = {r.match_id: r for r in result}
        assert by_id["a"].selected_for_coverage is True
        assert by_id["a"].eligible_cell_id == "0_0"
        assert by_id["b"].eligible_cell_id == "0_1"
        assert by_id["c"].eligible_cell_id == "1_0"
        assert by_id["d"].eligible_cell_id == "1_1"
        for record in result:
            assert record.selected_for_coverage is True
            assert record.grid_level == 0
            assert isinstance(record.coverage_selection_rationale, str)
            assert record.coverage_selection_rationale != ""

    def test_competition_within_a_cell_higher_score_wins(self) -> None:
        eligibility = _all_eligible((2, 2))
        strong = _make_record("strong", (10.0, 10.0), 0.9)
        weak = _make_record("weak", (12.0, 12.0), 0.3)  # same cell (0, 0)

        result = select_grid_coverage(
            (strong, weak),
            eligibility=eligibility,
            image_shape=(100, 100),
            quality_floor=0.1,
        )

        by_id = {r.match_id: r for r in result}
        assert by_id["strong"].selected_for_coverage is True
        assert by_id["strong"].eligible_cell_id == "0_0"
        assert by_id["weak"].selected_for_coverage is False
        assert by_id["weak"].coverage_selection_rationale is not None
        assert "strong" in by_id["weak"].coverage_selection_rationale

    def test_quality_floor_blocks_selection_when_best_candidate_is_below_it(self) -> None:
        eligibility = _all_eligible((2, 2))
        below_floor = _make_record("lo", (10.0, 10.0), 0.2)

        result = select_grid_coverage(
            (below_floor,),
            eligibility=eligibility,
            image_shape=(100, 100),
            quality_floor=0.5,
        )

        assert len(result) == 1
        assert result[0].selected_for_coverage is False
        assert result[0].coverage_selection_rationale is not None
        assert "quality_floor" in result[0].coverage_selection_rationale

    def test_ineligible_cell_candidate_passes_through_completely_untouched(self) -> None:
        eligible = np.ones((2, 2), dtype=np.bool_)
        eligible[0, 0] = False
        eligibility = EligibilityGrid(
            grid_shape=(2, 2),
            eligible=eligible,
            exclusion_reason={(0, 0): "outside physical overlap"},
        )
        candidate = _make_record("x", (10.0, 10.0), 0.99)  # maps to (0, 0): ineligible

        result = select_grid_coverage(
            (candidate,),
            eligibility=eligibility,
            image_shape=(100, 100),
            quality_floor=0.1,
        )

        assert len(result) == 1
        assert result[0] == candidate  # full-record equality: byte-identical, untouched
        assert result[0].selected_for_coverage is False
        assert result[0].eligible_cell_id is None
        assert result[0].coverage_selection_rationale is None

    def test_non_inlier_never_selected_regardless_of_score(self) -> None:
        eligibility = _all_eligible((2, 2))
        non_inlier = _make_record("ni", (10.0, 10.0), 0.99, is_inlier=False)
        inlier = _make_record("in", (12.0, 12.0), 0.1)  # same cell, much lower score

        result = select_grid_coverage(
            (non_inlier, inlier),
            eligibility=eligibility,
            image_shape=(100, 100),
            quality_floor=0.05,
        )

        by_id = {r.match_id: r for r in result}
        # non-inlier is untouched (not even a rationale), never selected
        assert by_id["ni"] == non_inlier
        assert by_id["ni"].selected_for_coverage is False
        assert by_id["ni"].coverage_selection_rationale is None
        # the only is_inlier candidate wins its cell despite the low score
        assert by_id["in"].selected_for_coverage is True


# ---------------------------------------------------------------------------
# compute_coverage_metrics
# ---------------------------------------------------------------------------


class TestCoverageMetricsOccupancy:
    def test_exact_fraction_of_eligible_cells_selected(self) -> None:
        eligibility = _all_eligible((2, 2))  # 4 eligible cells
        record_a = _make_record(
            "a", (10.0, 10.0), 0.9, selected_for_coverage=True, eligible_cell_id="0_0"
        )
        record_b = _make_record(
            "b", (60.0, 60.0), 0.9, selected_for_coverage=True, eligible_cell_id="1_1"
        )

        metrics = compute_coverage_metrics(
            (record_a, record_b), eligibility=eligibility, image_shape=(100, 100)
        )

        assert metrics.eligible_cell_occupancy == pytest.approx(2 / 4)


class TestCoverageMetricsConvexHullRatio:
    def test_known_triangle_matches_hand_computed_ratio(self) -> None:
        eligibility = _all_eligible((2, 2))  # 4 eligible cells, 100x100 image
        # cell area = (100/2) * (100/2) = 2500 px^2; eligible area = 4 * 2500 = 10000 px^2
        # triangle (5,5), (95,5), (5,95) -> area = 0.5*90*90 = 4050 px^2 (shoelace, hand-verified)
        point_a = _make_record(
            "a", (5.0, 5.0), 0.9, selected_for_coverage=True, eligible_cell_id="0_0"
        )
        point_b = _make_record(
            "b", (95.0, 5.0), 0.9, selected_for_coverage=True, eligible_cell_id="1_0"
        )
        point_c = _make_record(
            "c", (5.0, 95.0), 0.9, selected_for_coverage=True, eligible_cell_id="0_1"
        )

        metrics = compute_coverage_metrics(
            (point_a, point_b, point_c), eligibility=eligibility, image_shape=(100, 100)
        )

        expected_ratio = 4050.0 / 10000.0
        assert metrics.convex_hull_to_eligible_area_ratio is not None
        # Exact rational arithmetic on these hand-picked integer coordinates;
        # a tight relative tolerance only guards float round-off in the
        # shoelace sum, not any real uncertainty in the expected value.
        assert metrics.convex_hull_to_eligible_area_ratio == pytest.approx(expected_ratio, rel=1e-9)

    def test_fewer_than_three_selected_points_is_none_not_zero(self) -> None:
        eligibility = _all_eligible((2, 2))
        point_a = _make_record(
            "a", (5.0, 5.0), 0.9, selected_for_coverage=True, eligible_cell_id="0_0"
        )
        point_b = _make_record(
            "b", (95.0, 5.0), 0.9, selected_for_coverage=True, eligible_cell_id="1_0"
        )

        metrics = compute_coverage_metrics(
            (point_a, point_b), eligibility=eligibility, image_shape=(100, 100)
        )

        assert metrics.convex_hull_to_eligible_area_ratio is None

    def test_zero_selected_points_is_none(self) -> None:
        eligibility = _all_eligible((2, 2))
        unselected = _make_record("a", (5.0, 5.0), 0.9, selected_for_coverage=False)

        metrics = compute_coverage_metrics(
            (unselected,), eligibility=eligibility, image_shape=(100, 100)
        )

        assert metrics.convex_hull_to_eligible_area_ratio is None


class TestCoverageMetricsLargestEmptyRun:
    def test_known_contiguous_block_of_eligible_unselected_cells(self) -> None:
        # 3x4 grid: column index 2 is entirely ineligible, splitting the
        # grid into a 3x2=6-cell left component and a 3x1=3-cell right
        # component. No records are selected, so the largest empty run is
        # the larger of the two eligible components: 6.
        eligible = np.ones((3, 4), dtype=np.bool_)
        eligible[:, 2] = False
        exclusion_reason = {(row, 2): "outside physical overlap" for row in range(3)}
        eligibility = EligibilityGrid(
            grid_shape=(3, 4), eligible=eligible, exclusion_reason=exclusion_reason
        )

        metrics = compute_coverage_metrics((), eligibility=eligibility, image_shape=(300, 400))

        assert metrics.largest_empty_run == 6

    def test_selecting_cells_shrinks_the_largest_run(self) -> None:
        # Same grid as above, but now select one record in the left
        # component (cell (0, 0)): the remaining left-side empty run drops
        # from 6 to 5 cells, still larger than the right side's 3, so the
        # largest empty run becomes exactly 5.
        eligible = np.ones((3, 4), dtype=np.bool_)
        eligible[:, 2] = False
        exclusion_reason = {(row, 2): "outside physical overlap" for row in range(3)}
        eligibility = EligibilityGrid(
            grid_shape=(3, 4), eligible=eligible, exclusion_reason=exclusion_reason
        )
        # image_shape (300, 400), grid (3, 4): cell height 100, cell width 100.
        selected = _make_record(
            "sel", (10.0, 10.0), 0.9, selected_for_coverage=True, eligible_cell_id="0_0"
        )

        metrics = compute_coverage_metrics(
            (selected,), eligibility=eligibility, image_shape=(300, 400)
        )

        assert metrics.largest_empty_run == 5


class TestCoverageMetricsPerCellCounts:
    def test_exact_count_array_for_small_scenario(self) -> None:
        eligibility = _all_eligible((2, 2))
        records = (
            _make_record("a", (10.0, 10.0), 0.9, selected_for_coverage=True),  # (0,0)
            _make_record("b", (12.0, 12.0), 0.3),  # (0,0), not selected
            _make_record("c", (60.0, 60.0), 0.8, selected_for_coverage=True),  # (1,1)
            _make_record("d", (10.0, 60.0), 0.99, is_inlier=False),  # non-inlier: not counted
        )

        metrics = compute_coverage_metrics(records, eligibility=eligibility, image_shape=(100, 100))

        expected = np.array([[2, 0], [0, 1]], dtype=np.int64)
        np.testing.assert_array_equal(metrics.per_cell_candidate_counts, expected)


# ---------------------------------------------------------------------------
# Sanity: CoverageMetrics is a plain, importable dataclass
# ---------------------------------------------------------------------------


def test_coverage_metrics_fields_are_directly_readable() -> None:
    metrics = CoverageMetrics(
        eligible_cell_occupancy=0.5,
        convex_hull_to_eligible_area_ratio=None,
        largest_empty_run=3,
        per_cell_candidate_counts=np.zeros((2, 2), dtype=np.int64),
    )
    assert metrics.eligible_cell_occupancy == 0.5
    assert metrics.convex_hull_to_eligible_area_ratio is None
    assert metrics.largest_empty_run == 3
    np.testing.assert_array_equal(metrics.per_cell_candidate_counts, np.zeros((2, 2)))
