"""Eligibility grid input, deterministic 8x8 coverage selection, and coverage
metrics (WP-07 task 4 (partial), task 6, task 9).

**Scope ruling (read before extending this module).** Plan task 4 defines
eligibility as "valid source and reference data inside physical overlap and
supported terrain/illumination regions" — computing that needs WP-03's
overlap/terrain/illumination masks, which do not exist in this repository.
This module therefore accepts an already-computed eligibility grid
(:class:`EligibilityGrid`) as an external input, the same pattern Task 13's
``MatchPrior`` and Task 15's optional ``reverse_records`` used for "the real
version of this input doesn't exist yet, so the function takes it as a
parameter instead of computing it itself". Nothing here derives eligibility
from real geometry.

Quadtree selection is explicitly out of scope (plan: add it "only after the
fixed grid is tested and only if it improves coverage/accuracy trade-offs",
which has not happened) — only the fixed 8x8-style grid is implemented here.

No ``scipy``/``shapely``/geometry library is installed, so the convex-hull-
ratio metric (task 9) uses a pure-NumPy 2-D convex hull (Andrew's monotone
chain) implemented in this module — see :func:`convex_hull`.

Every step that changes a :class:`CorrespondenceRecord`'s state returns a NEW
record via ``.model_copy(update=...)`` — the record is frozen, so mutation is
enforced to raise, not just discouraged.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord
from selene_core.types import SourcePixel

__all__ = [
    "CoverageMetrics",
    "EligibilityGrid",
    "compute_coverage_metrics",
    "convex_hull",
    "select_grid_coverage",
]


# ---------------------------------------------------------------------------
# Eligibility grid (task 4, external input)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EligibilityGrid:
    """An externally-computed eligibility grid over image space.

    ``grid_shape`` is ``(rows, cols)`` — plan task 6 specifies an 8x8 grid,
    but the type is kept general so a caller may use a different resolution.
    ``eligible`` is a boolean array of shape ``grid_shape``, ``True`` meaning
    the cell is eligible for coverage selection. ``exclusion_reason`` records
    why *every* ineligible cell was excluded (plan task 4: "record why every
    excluded cell is ineligible") — a cell with ``eligible[row, col] is
    False`` and no entry here is a violation of that requirement, not a
    permissible gap, so it is rejected at construction time.

    Note on equality/hashing: because ``eligible`` is a NumPy array, this
    dataclass's generated ``__eq__``/``__hash__`` are not meaningful for
    whole-instance comparison (NumPy array equality is elementwise, not a
    single bool) — compare individual fields instead. This mirrors how the
    codebase already treats array-carrying dataclasses; no test in this
    module compares two ``EligibilityGrid`` instances via ``==``.
    """

    grid_shape: tuple[int, int]
    eligible: npt.NDArray[np.bool_]
    exclusion_reason: Mapping[tuple[int, int], str]

    def __post_init__(self) -> None:
        if self.eligible.shape != self.grid_shape:
            raise ValueError(
                f"EligibilityGrid.eligible has shape {self.eligible.shape}, expected "
                f"grid_shape={self.grid_shape}"
            )
        rows, cols = self.grid_shape
        missing = [
            (row, col)
            for row in range(rows)
            for col in range(cols)
            if not bool(self.eligible[row, col]) and (row, col) not in self.exclusion_reason
        ]
        if missing:
            raise ValueError(
                f"EligibilityGrid: ineligible cell(s) {missing} have no exclusion_reason entry; "
                "every excluded cell must record why it is ineligible (plan task 4)"
            )


# ---------------------------------------------------------------------------
# Pure-NumPy 2-D convex hull (Andrew's monotone chain)
# ---------------------------------------------------------------------------


def convex_hull(points: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """The 2-D convex hull of ``points`` (shape ``(n, 2)``), via Andrew's
    monotone chain algorithm — O(n log n), no ``scipy``/``shapely`` dependency.

    Returns an array of shape ``(h, 2)`` holding the hull vertices in
    counter-clockwise order (per the standard cross-product sign convention;
    "counter-clockwise" assumes the first column increases rightward and the
    second increases upward — callers using (line, sample) = (row, column)
    pixel axes get a consistent, still-correctly-signed-area polygon, just
    not necessarily "counter-clockwise" in a row/column sense), starting
    from the lexicographically smallest point (smallest first coordinate,
    ties broken by smallest second coordinate). Duplicate input points are
    removed before the hull is computed.

    **Degenerate inputs are handled explicitly, not by raising:**

    * Zero points: returns an empty ``(0, 2)`` array.
    * Fewer than 3 *distinct* points (after de-duplication): returns the
      distinct points themselves, unchanged in position (order: sorted
      lexicographically), because no polygon can be formed.
    * All points collinear (including the exactly-3-collinear-points edge
      case): the monotone chain algorithm's collinearity test (``cross <=
      0`` triggers a pop, discarding a point that does not make a strict
      left turn) naturally collapses the hull to just the two extreme
      points of the segment — this function returns that 2-point result
      rather than fabricating a 3-point "hull" with zero area. Callers that
      need to distinguish "degenerate hull" from "a real >=3-vertex hull"
      should check ``len(convex_hull(points)) < 3``.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.size == 0:
        return np.empty((0, 2), dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError(f"convex_hull expects points of shape (n, 2), got {pts.shape}")

    unique_pts = np.unique(pts, axis=0)  # sorted lexicographically, duplicates removed
    n = unique_pts.shape[0]
    if n < 3:
        return unique_pts

    def cross(
        o: npt.NDArray[np.float64], a: npt.NDArray[np.float64], b: npt.NDArray[np.float64]
    ) -> float:
        return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))

    lower: list[npt.NDArray[np.float64]] = []
    for point in unique_pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[npt.NDArray[np.float64]] = []
    for point in unique_pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    hull_points = lower[:-1] + upper[:-1]
    return np.array(hull_points, dtype=np.float64)


def _polygon_area_px2(hull: npt.NDArray[np.float64]) -> float:
    """Shoelace-formula area of a (already convex, CCW-or-CW) polygon.

    Returns ``0.0`` for a degenerate hull (fewer than 3 vertices) — that is
    a genuine, correctly-computed zero area (a point or a line segment has
    no area), not a value this function refuses to compute.
    """
    if hull.shape[0] < 3:
        return 0.0
    x = hull[:, 0]
    y = hull[:, 1]
    return float(0.5 * abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)))


# ---------------------------------------------------------------------------
# Grid cell binning, shared by selection and metrics
# ---------------------------------------------------------------------------


def _cell_for_pixel(
    pixel: SourcePixel, image_shape: tuple[int, int], grid_shape: tuple[int, int]
) -> tuple[int, int]:
    """Map a ``source_pixel`` position to a ``(row, col)`` eligibility-grid
    cell.

    Binning formula: ``row = floor((pixel.line / image_shape[0]) *
    grid_shape[0])``, and symmetrically for ``col`` from ``pixel.sample`` /
    ``image_shape[1]`` / ``grid_shape[1]``. The result is clamped to
    ``[0, grid_shape[dim] - 1]`` — the clamp's documented purpose is the
    image's far edge (a pixel with ``line == image_shape[0]`` would
    otherwise floor-divide to exactly ``grid_shape[0]``, one past the last
    valid row); it is applied symmetrically at the near edge too as a
    defensive measure against any (unexpected, since ``SourcePixel`` does
    not itself forbid it) negative coordinate.
    """
    image_rows, image_cols = image_shape
    grid_rows, grid_cols = grid_shape
    row = math.floor((pixel.line / image_rows) * grid_rows)
    col = math.floor((pixel.sample / image_cols) * grid_cols)
    row = min(max(row, 0), grid_rows - 1)
    col = min(max(col, 0), grid_cols - 1)
    return (row, col)


# ---------------------------------------------------------------------------
# Task 6: deterministic grid coverage selection
# ---------------------------------------------------------------------------


def select_grid_coverage(
    records: tuple[CorrespondenceRecord, ...],
    *,
    eligibility: EligibilityGrid,
    image_shape: tuple[int, int],
    quality_floor: float,
) -> tuple[CorrespondenceRecord, ...]:
    """Deterministic fixed-grid coverage selection (plan task 6) over
    Task 15's *verified* candidates.

    Only records with ``is_inlier=True`` are considered — a candidate that
    never passed verification cannot win a coverage cell even if it
    geometrically falls inside one (Task 15's verification is a
    precondition, not something this function re-derives).

    Each considered record's ``source_pixel`` is mapped to a grid cell via
    :func:`_cell_for_pixel`. A record mapping to an ineligible cell
    (``eligibility.eligible[row, col] is False``) is skipped entirely: it
    is never a selection candidate, and it is returned **completely
    untouched** — not even ``coverage_selection_rationale`` is set — because
    this function's job is coverage selection among eligible inlier
    candidates, not universal annotation. The same is true of every
    non-``is_inlier`` record.

    Within each eligible cell with at least one eligible candidate,
    candidates are ranked by ``raw_score`` descending, ties broken by the
    lexicographically smaller ``match_id`` (the same deterministic tie-break
    ``select/verification.py`` already uses, so iteration order never
    decides the outcome). The top-ranked candidate is selected — via
    ``.model_copy(update={...})`` setting ``selected_for_coverage=True``,
    ``eligible_cell_id=f"{row}_{col}"``, ``grid_level=0``, and a specific
    ``coverage_selection_rationale`` — **only if** its ``raw_score >=
    quality_floor`` (plan task 6's "global quality floor": a cell whose best
    candidate is still below the floor gets NO selection, it is never
    forced to pick the best of a bad set).

    Every other eligible candidate in a cell that did get a selection is
    returned with ``selected_for_coverage=False`` (explicit, not merely
    Task 15's default carried through) and a rationale naming the winner.
    Every eligible candidate in a cell whose best candidate missed the
    quality floor is returned the same way, with a rationale naming the
    floor it missed.
    """
    grid_rows, grid_cols = eligibility.grid_shape

    cell_groups: dict[tuple[int, int], list[int]] = {}
    for index, record in enumerate(records):
        if not record.is_inlier:
            continue
        cell = _cell_for_pixel(record.source_pixel, image_shape, (grid_rows, grid_cols))
        if not bool(eligibility.eligible[cell]):
            continue
        cell_groups.setdefault(cell, []).append(index)

    updates: dict[int, CorrespondenceRecord] = {}
    for (row, col), indices in cell_groups.items():
        cell_id = f"{row}_{col}"
        ranked = sorted(indices, key=lambda i: (-records[i].raw_score, records[i].match_id))
        winner_index = ranked[0]
        winner_record = records[winner_index]
        winner_score = winner_record.raw_score
        candidate_count = len(indices)

        if winner_score >= quality_floor:
            updates[winner_index] = winner_record.model_copy(
                update={
                    "selected_for_coverage": True,
                    "eligible_cell_id": cell_id,
                    "grid_level": 0,
                    "coverage_selection_rationale": (
                        f"highest raw_score ({winner_score:.6f}) among {candidate_count} "
                        f"eligible candidate(s) in cell {cell_id}, meets quality_floor "
                        f"({quality_floor:.6f})"
                    ),
                }
            )
            for loser_index in ranked[1:]:
                loser_record = records[loser_index]
                updates[loser_index] = loser_record.model_copy(
                    update={
                        "selected_for_coverage": False,
                        "coverage_selection_rationale": (
                            f"outscored by match_id={winner_record.match_id} "
                            f"(raw_score={winner_score:.6f}) in cell {cell_id}"
                        ),
                    }
                )
        else:
            for index in ranked:
                record = records[index]
                updates[index] = record.model_copy(
                    update={
                        "selected_for_coverage": False,
                        "coverage_selection_rationale": (
                            f"best raw_score in cell {cell_id} is {winner_score:.6f}, below "
                            f"quality_floor ({quality_floor:.6f}); no candidate selected in "
                            "this cell"
                        ),
                    }
                )

    return tuple(updates.get(index, record) for index, record in enumerate(records))


# ---------------------------------------------------------------------------
# Task 9: coverage metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageMetrics:
    """Coverage-quality metrics computed over a set of verified,
    coverage-selected candidates (plan task 9).

    Note on equality: ``per_cell_candidate_counts`` is a NumPy array, so —
    as with :class:`EligibilityGrid` — this dataclass's generated
    ``__eq__``/``__hash__`` are not meaningful for whole-instance
    comparison; compare individual fields (and the array field via
    ``numpy.testing.assert_array_equal`` or elementwise ``==``) instead.
    """

    eligible_cell_occupancy: float
    """Fraction, in ``[0.0, 1.0]``, of ELIGIBLE cells that received a
    coverage selection. ``0.0`` (vacuously) if there are zero eligible
    cells."""

    convex_hull_to_eligible_area_ratio: float | None
    """Convex-hull area of the *selected* points' ``source_pixel``
    positions, divided by the total eligible-region area, both in px^2.
    ``None`` (never a fabricated ``0.0``) when fewer than 3 points were
    selected, since no hull area is computable from fewer than 3 points."""

    largest_empty_run: int
    """The size of the largest 4-connected group of ELIGIBLE-but-unselected
    cells on the grid (a cell counts as "empty" here whether it had zero
    candidates or had candidates that were not selected)."""

    per_cell_candidate_counts: npt.NDArray[np.int64]
    """Shape ``grid_shape``. Count of ``is_inlier`` candidates — selected or
    not — that mapped into each cell, independent of what got selected."""


def _cell_area_px2(image_shape: tuple[int, int], grid_shape: tuple[int, int]) -> float:
    """Area, in px^2, of one grid cell — ``image_shape`` divided evenly by
    ``grid_shape`` along each axis. Used as the unit for the eligible-area
    denominator of the convex-hull-ratio metric."""
    cell_height_px = image_shape[0] / grid_shape[0]
    cell_width_px = image_shape[1] / grid_shape[1]
    return cell_height_px * cell_width_px


def _largest_empty_run(
    grid_shape: tuple[int, int],
    eligible: npt.NDArray[np.bool_],
    selected_cells: set[tuple[int, int]],
) -> int:
    """Largest 4-connected component of cells that are eligible but not in
    ``selected_cells``, found by a direct flood fill (no library) — a small,
    well-defined graph search over a small grid."""
    rows, cols = grid_shape
    empty = np.zeros((rows, cols), dtype=bool)
    for row in range(rows):
        for col in range(cols):
            empty[row, col] = bool(eligible[row, col]) and (row, col) not in selected_cells

    visited = np.zeros((rows, cols), dtype=bool)
    largest = 0
    for start_row in range(rows):
        for start_col in range(cols):
            if not empty[start_row, start_col] or visited[start_row, start_col]:
                continue
            stack = [(start_row, start_col)]
            visited[start_row, start_col] = True
            size = 0
            while stack:
                cur_row, cur_col = stack.pop()
                size += 1
                for delta_row, delta_col in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    next_row, next_col = cur_row + delta_row, cur_col + delta_col
                    if (
                        0 <= next_row < rows
                        and 0 <= next_col < cols
                        and empty[next_row, next_col]
                        and not visited[next_row, next_col]
                    ):
                        visited[next_row, next_col] = True
                        stack.append((next_row, next_col))
            largest = max(largest, size)
    return largest


def compute_coverage_metrics(
    records: tuple[CorrespondenceRecord, ...],
    *,
    eligibility: EligibilityGrid,
    image_shape: tuple[int, int],
) -> CoverageMetrics:
    """Compute all four :class:`CoverageMetrics` fields from records that
    :func:`select_grid_coverage` has already annotated.

    Each ``is_inlier`` record's cell is re-derived with the exact same
    :func:`_cell_for_pixel` binning :func:`select_grid_coverage` used (for
    the density count in ``per_cell_candidate_counts``); ``selected_for_
    coverage`` and ``source_pixel`` are read directly to determine which
    cells/points were actually selected.

    The eligible-area denominator for ``convex_hull_to_eligible_area_ratio``
    is ``(number of eligible cells) * (image_shape / grid_shape cell
    area)`` in px^2 — see :func:`_cell_area_px2`.
    """
    grid_shape = eligibility.grid_shape
    grid_rows, grid_cols = grid_shape

    per_cell_counts = np.zeros(grid_shape, dtype=np.int64)
    selected_cells: set[tuple[int, int]] = set()
    selected_points: list[tuple[float, float]] = []

    for record in records:
        if not record.is_inlier:
            continue
        cell = _cell_for_pixel(record.source_pixel, image_shape, (grid_rows, grid_cols))
        per_cell_counts[cell] += 1
        if record.selected_for_coverage:
            selected_cells.add(cell)
            selected_points.append((record.source_pixel.line, record.source_pixel.sample))

    eligible_cell_count = int(np.count_nonzero(eligibility.eligible))
    occupancy = len(selected_cells) / eligible_cell_count if eligible_cell_count > 0 else 0.0

    if len(selected_points) < 3:
        hull_ratio: float | None = None
    else:
        hull = convex_hull(np.array(selected_points, dtype=np.float64))
        hull_area_px2 = _polygon_area_px2(hull)
        eligible_area_px2 = eligible_cell_count * _cell_area_px2(image_shape, grid_shape)
        hull_ratio = hull_area_px2 / eligible_area_px2 if eligible_area_px2 > 0 else None

    largest_empty_run = _largest_empty_run(grid_shape, eligibility.eligible, selected_cells)

    return CoverageMetrics(
        eligible_cell_occupancy=occupancy,
        convex_hull_to_eligible_area_ratio=hull_ratio,
        largest_empty_run=largest_empty_run,
        per_cell_candidate_counts=per_cell_counts,
    )
