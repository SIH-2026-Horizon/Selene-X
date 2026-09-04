"""Candidate verification (WP-07 tasks 1, 2, 3, and 5's NMS half).

**Scope ruling (read before extending this module).** ``select/__init__.py``'s
docstring describes the full WP-07 responsibility list, including an
eligibility mask (needs WP-03 terrain/illumination data, which does not exist
yet) and grid/quadtree coverage selection (a separate concern, Task 16). This
module is deliberately narrower: it operates purely on
``tuple[CorrespondenceRecord, ...]`` and implements

* duplicate removal (task 1),
* a robust affine outlier fit, RANSAC-style (task 2, minus prior-uncertainty
  gates — this build has no real geometric prior to gate against — and minus
  homography, which the plan uses only as a diagnostic baseline never as the
  final terrain-aware model),
* forward/backward consistency (also task 2), and
* spatial non-maximum suppression (task 3, and the NMS half of task 5 —
  quality *filtering* ahead of coverage scoring is Task 16's concern, this
  module only marks NMS status).

Every step that changes a :class:`CorrespondenceRecord`'s state returns a NEW
record via ``.model_copy(update=...)`` — the record is frozen (``extra=
"forbid"``, ``ConfigDict(frozen=True)``), so mutation is not just discouraged,
it is enforced to raise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from selene_core.errors import FailureCode
from selene_core.match.correspondence import CorrespondenceRecord, NmsStatus
from selene_core.types import ReferencePixel, SourcePixel

__all__ = [
    "AffineTransform2D",
    "RobustFitResult",
    "apply_robust_fit",
    "fit_robust_affine",
    "remove_duplicate_candidates",
    "suppress_non_maxima",
    "verify_candidates",
    "verify_forward_backward",
]

_AFFINE_MINIMAL_SAMPLE_SIZE = 3
"""A 2-D affine transform (2x2 linear map + 2-vector translation, 6 free
parameters) needs 3 non-collinear point correspondences to be exactly
determined; that is RANSAC's minimal sample size here."""


def _pixel_distance(a: SourcePixel | ReferencePixel, b: SourcePixel | ReferencePixel) -> float:
    """Euclidean distance between two pixel positions in line/sample space."""
    return math.hypot(a.line - b.line, a.sample - b.sample)


# ---------------------------------------------------------------------------
# Task 1: duplicate removal
# ---------------------------------------------------------------------------


def remove_duplicate_candidates(
    records: tuple[CorrespondenceRecord, ...], *, radius_px: float
) -> tuple[CorrespondenceRecord, ...]:
    """Collapse near-identical detections of the same point into one.

    Candidates whose ``source_pixel`` positions are within ``radius_px`` of
    each other are grouped, and only the highest-``raw_score`` record in each
    group survives — the rest are dropped entirely, not kept-but-marked-
    rejected, because a true duplicate is noise, not evidence.

    Grouping is **transitive** (computed with union-find over the pairwise
    "within radius_px" relation): if A is within radius of B, and B is within
    radius of C, all three are one duplicate cluster even though A and C
    might individually be farther apart than ``radius_px``. This keeps
    grouping symmetric and independent of input order, rather than a greedy
    pairwise merge whose result would depend on which record happened to be
    considered first.

    Ties on ``raw_score`` within a group are broken by the lexicographically
    smaller ``match_id`` — a documented, stable tie-break so that arbitrary
    Python iteration order never decides the outcome.

    The output preserves the relative input order of the records that
    survive.
    """
    n = len(records)
    parent = list(range(n))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i in range(n):
        for j in range(i + 1, n):
            if _pixel_distance(records[i].source_pixel, records[j].source_pixel) <= radius_px:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    kept_indices = sorted(
        min(members, key=lambda idx: (-records[idx].raw_score, records[idx].match_id))
        for members in groups.values()
    )
    return tuple(records[idx] for idx in kept_indices)


# ---------------------------------------------------------------------------
# Task 2: robust affine outlier fit (RANSAC-style)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AffineTransform2D:
    """A 2-D affine transform from source pixel space to reference pixel
    space: ``reference = A @ source + t``, expressed component-wise so no
    caller needs a NumPy dependency to read the fitted model.

    ``line``/``sample`` follow this project's internal (line, sample) =
    (row, column) axis convention (``selene_core.types``), so, given a
    ``SourcePixel`` with coordinates ``(line, sample)``::

        predicted_line   = a_line_line   * line + a_line_sample   * sample + t_line
        predicted_sample = a_sample_line * line + a_sample_sample * sample + t_sample
    """

    a_line_line: float
    a_line_sample: float
    a_sample_line: float
    a_sample_sample: float
    t_line: float
    t_sample: float

    def apply(self, source: SourcePixel) -> tuple[float, float]:
        """Predict ``(line, sample)`` in reference space for ``source``."""
        predicted_line = (
            self.a_line_line * source.line + self.a_line_sample * source.sample + self.t_line
        )
        predicted_sample = (
            self.a_sample_line * source.line + self.a_sample_sample * source.sample + self.t_sample
        )
        return (predicted_line, predicted_sample)


@dataclass(frozen=True, slots=True)
class RobustFitResult:
    """The outcome of a RANSAC-style robust affine fit.

    ``converged is False`` is an explicit, documented failure state (rather
    than ``None`` from a function with a richer return type) for "no usable
    model" — either too few input records to attempt a fit at all, or the
    best RANSAC trial never reached ``min_inliers``. In that case ``transform``
    is ``None``, ``inlier_indices`` and ``residuals_px`` are empty, and
    ``failure_code``/``failure_reason`` explain why.

    When ``converged is True``, ``transform`` is the affine fitted by a final
    least-squares refit over ALL of the best trial's inliers (not just the
    3-point minimal sample that found them — a minimal-sample fit is only
    used to *identify* the inlier set; the reported model is always the
    full-inlier refit, standard RANSAC practice). ``residuals_px`` is the
    residual of every input record (in input order) against that final
    refit model, so a caller can see outlier magnitude, not just the
    boolean inlier/outlier split. ``inlier_indices`` are indices into the
    records tuple that was fit, identifying the best trial's inlier set.
    """

    converged: bool
    transform: AffineTransform2D | None
    inlier_indices: tuple[int, ...]
    residuals_px: tuple[float, ...]
    iterations_used: int
    residual_threshold_px: float
    failure_code: FailureCode | None = None
    failure_reason: str | None = None


def _design_row(pixel: SourcePixel) -> tuple[float, float, float]:
    return (pixel.line, pixel.sample, 1.0)


def _affine_from_solution(solution: np.ndarray) -> AffineTransform2D:
    return AffineTransform2D(
        a_line_line=float(solution[0, 0]),
        a_line_sample=float(solution[1, 0]),
        t_line=float(solution[2, 0]),
        a_sample_line=float(solution[0, 1]),
        a_sample_sample=float(solution[1, 1]),
        t_sample=float(solution[2, 1]),
    )


def fit_robust_affine(
    records: tuple[CorrespondenceRecord, ...],
    *,
    residual_threshold_px: float,
    min_inliers: int,
    max_iterations: int,
    seed: int,
) -> RobustFitResult:
    """RANSAC-style robust fit of a 2-D affine transform (6 parameters:
    linear map + translation) from ``source_pixel`` to ``reference_pixel``.

    Deterministic given ``seed``: sampling uses
    ``numpy.random.default_rng(seed)``, so the same seed and inputs produce
    bit-identical results across independent calls.

    For each of ``max_iterations`` trials: draw 3 distinct records at random,
    fit the affine exactly through them (closed-form least squares — for an
    exactly-determined 3-point system this reproduces the exact solution),
    compute residuals for ALL input records against that candidate model,
    and count how many are within ``residual_threshold_px`` (that trial's
    inlier set). A minimal sample whose 3 points are collinear cannot
    determine an affine transform (the linear system is rank-deficient); such
    a trial is skipped without contributing a candidate model, but it still
    consumes one of the ``max_iterations`` draws.

    The trial with the largest inlier count wins; ties are broken by the
    lowest total residual summed over that trial's inliers — deterministic,
    not "whichever NumPy iterates to first".

    If the best trial's inlier count is below ``min_inliers`` (including the
    case where every trial was degenerate, or ``len(records) < 3`` so no
    trial could even run), this returns a failed ``RobustFitResult``
    (``converged=False``) rather than forcing a low-confidence fit.

    Otherwise, the affine is re-fit via least squares using ALL of the best
    trial's inliers (not just the 3-point minimal sample), and residuals for
    every input record are recomputed against that final, more accurate
    model.
    """
    n = len(records)
    if n < _AFFINE_MINIMAL_SAMPLE_SIZE:
        return RobustFitResult(
            converged=False,
            transform=None,
            inlier_indices=(),
            residuals_px=(),
            iterations_used=0,
            residual_threshold_px=residual_threshold_px,
            failure_code=FailureCode.MATCHING_INSUFFICIENT_CANDIDATES,
            failure_reason=(
                f"only {n} correspondence(s) supplied; an affine fit needs at least "
                f"{_AFFINE_MINIMAL_SAMPLE_SIZE} non-collinear points to be attempted at all"
            ),
        )

    rng = np.random.default_rng(seed)
    design = np.array([_design_row(r.source_pixel) for r in records], dtype=np.float64)
    targets = np.array(
        [(r.reference_pixel.line, r.reference_pixel.sample) for r in records], dtype=np.float64
    )

    best_inlier_mask: np.ndarray | None = None
    best_count = -1
    best_total_residual = math.inf
    iterations_used = 0

    for _ in range(max_iterations):
        iterations_used += 1
        sample_indices = rng.choice(n, size=_AFFINE_MINIMAL_SAMPLE_SIZE, replace=False)
        sample_design = design[sample_indices]
        if np.linalg.matrix_rank(sample_design) < _AFFINE_MINIMAL_SAMPLE_SIZE:
            continue  # collinear minimal sample: cannot determine an affine, skip this trial
        sample_targets = targets[sample_indices]
        solution, _resid, _rank, _sv = np.linalg.lstsq(sample_design, sample_targets, rcond=None)

        predicted = design @ solution
        residuals = np.hypot(targets[:, 0] - predicted[:, 0], targets[:, 1] - predicted[:, 1])
        inlier_mask = residuals <= residual_threshold_px
        count = int(inlier_mask.sum())
        total_residual = float(residuals[inlier_mask].sum()) if count else 0.0

        if count > best_count or (count == best_count and total_residual < best_total_residual):
            best_count = count
            best_total_residual = total_residual
            best_inlier_mask = inlier_mask

    if best_inlier_mask is None or best_count < min_inliers:
        return RobustFitResult(
            converged=False,
            transform=None,
            inlier_indices=(),
            residuals_px=(),
            iterations_used=iterations_used,
            residual_threshold_px=residual_threshold_px,
            failure_code=FailureCode.MATCHING_INSUFFICIENT_CANDIDATES,
            failure_reason=(
                f"best RANSAC trial found {max(best_count, 0)} inlier(s) among {n} "
                f"correspondence(s), below the required min_inliers={min_inliers}, after "
                f"{iterations_used} iterations"
            ),
        )

    inlier_indices = tuple(int(i) for i in np.flatnonzero(best_inlier_mask))
    refit_solution, _resid, _rank, _sv = np.linalg.lstsq(
        design[list(inlier_indices)], targets[list(inlier_indices)], rcond=None
    )
    transform = _affine_from_solution(refit_solution)

    final_predicted = design @ refit_solution
    final_residuals = np.hypot(
        targets[:, 0] - final_predicted[:, 0], targets[:, 1] - final_predicted[:, 1]
    )

    return RobustFitResult(
        converged=True,
        transform=transform,
        inlier_indices=inlier_indices,
        residuals_px=tuple(float(v) for v in final_residuals),
        iterations_used=iterations_used,
        residual_threshold_px=residual_threshold_px,
        failure_code=None,
        failure_reason=None,
    )


def apply_robust_fit(
    records: tuple[CorrespondenceRecord, ...], fit: RobustFitResult
) -> tuple[CorrespondenceRecord, ...]:
    """Apply a :class:`RobustFitResult` (fit on this same ``records`` tuple,
    in this same order) back onto the records.

    If ``fit.converged`` is ``False``, every record gets ``is_candidate=True``,
    ``is_inlier=False``, and a ``rejection_reason`` naming that the robust fit
    itself failed to converge — never a per-point residual reason, since
    there is no trustworthy model to measure any individual point against.

    Otherwise: inliers (indices in ``fit.inlier_indices``) get
    ``is_inlier=True``, ``is_candidate=True``, and
    ``robust_model_residual_px`` set to their fit residual. Outliers get
    ``is_inlier=False``, ``is_candidate=True`` (they were still candidates,
    just rejected by the geometric model), ``robust_model_residual_px`` set
    to their residual too (informative for a rejected point as well as an
    accepted one), and a ``rejection_reason`` that names both the measured
    residual and the threshold it exceeded.
    """
    if fit.converged and len(records) != len(fit.residuals_px):
        raise ValueError(
            f"apply_robust_fit: records has {len(records)} entries but fit.residuals_px has "
            f"{len(fit.residuals_px)}; fit must have been produced by fit_robust_affine on "
            "this exact records tuple"
        )

    if not fit.converged:
        reason = "robust affine fit did not converge: " + (
            fit.failure_reason or "no usable model was found"
        )
        return tuple(
            record.model_copy(
                update={
                    "is_candidate": True,
                    "is_inlier": False,
                    "rejection_reason": reason,
                }
            )
            for record in records
        )

    inlier_set = set(fit.inlier_indices)
    updated: list[CorrespondenceRecord] = []
    for index, record in enumerate(records):
        residual = fit.residuals_px[index]
        if index in inlier_set:
            updated.append(
                record.model_copy(
                    update={
                        "is_candidate": True,
                        "is_inlier": True,
                        "robust_model_residual_px": residual,
                        "rejection_reason": None,
                    }
                )
            )
        else:
            updated.append(
                record.model_copy(
                    update={
                        "is_candidate": True,
                        "is_inlier": False,
                        "robust_model_residual_px": residual,
                        "rejection_reason": (
                            f"robust affine fit residual {residual:.4f}px exceeds "
                            f"residual_threshold_px={fit.residual_threshold_px:.4f}"
                        ),
                    }
                )
            )
    return tuple(updated)


# ---------------------------------------------------------------------------
# Task 3 / task 5 (NMS half): spatial non-maximum suppression
# ---------------------------------------------------------------------------


def suppress_non_maxima(
    records: tuple[CorrespondenceRecord, ...], *, radius_px: float
) -> tuple[CorrespondenceRecord, ...]:
    """Spatial non-maximum suppression over ``source_pixel`` positions.

    Records are visited in descending ``raw_score`` order (ties broken by
    the lexicographically smaller ``match_id`` — the same documented,
    deterministic tie-break used by :func:`remove_duplicate_candidates`, so
    arbitrary Python iteration order never decides the outcome here either).

    For each record in that order: if it has not already been suppressed by
    a stronger, earlier record, it is marked ``NmsStatus.SURVIVED`` and every
    later, still-unprocessed record within ``radius_px`` of its
    ``source_pixel`` is marked ``NmsStatus.SUPPRESSED``. A record already
    marked suppressed by an earlier, stronger record is skipped when its own
    turn comes — it is not re-evaluated as a potential survivor.

    Every record this function is given gets its ``nms_status`` set (never
    left ``None``); ``NmsStatus.NOT_EVALUATED`` is reserved for records this
    function never touched at all, so it is never produced here. Records
    are returned in their original input order, with only ``nms_status``
    changed.
    """
    n = len(records)
    order = sorted(range(n), key=lambda i: (-records[i].raw_score, records[i].match_id))
    status: list[NmsStatus | None] = [None] * n

    for position, i in enumerate(order):
        if status[i] is not None:
            continue  # already suppressed by an earlier, stronger record
        status[i] = NmsStatus.SURVIVED
        anchor = records[i].source_pixel
        for j in order[position + 1 :]:
            if status[j] is not None:
                continue
            if _pixel_distance(anchor, records[j].source_pixel) <= radius_px:
                status[j] = NmsStatus.SUPPRESSED

    return tuple(
        record.model_copy(update={"nms_status": status[index]})
        for index, record in enumerate(records)
    )


# ---------------------------------------------------------------------------
# Task 2 (continued): forward/backward consistency
# ---------------------------------------------------------------------------


def verify_forward_backward(
    records: tuple[CorrespondenceRecord, ...],
    reverse_records: tuple[CorrespondenceRecord, ...] | None,
    *,
    max_error_px: float,
    reverse_lookup_tolerance_px: float,
) -> tuple[CorrespondenceRecord, ...]:
    """Annotate ``forward_backward_error_px`` from an optional reverse-
    direction candidate set.

    Forward/backward consistency needs correspondences computed in both
    directions. When ``reverse_records`` is ``None`` (the caller has no
    reverse-direction matches), this is a genuine no-op: ``records`` is
    returned completely unchanged, not a silent partial computation.

    When ``reverse_records`` is provided, a reverse record was produced by a
    matcher run with source and reference swapped, so by this project's
    field convention its ``source_pixel`` lands in what is physically the
    *reference* image, and its ``reference_pixel`` lands back in what is
    physically the *source* image.

    For a forward record F with ``source_pixel`` S and ``reference_pixel`` R,
    a mutual-nearest reverse partner is found in two steps:

    1. **Anchor lookup.** Consider every reverse record G whose
       ``source_pixel`` is within ``reverse_lookup_tolerance_px`` of R — this
       is "was G looking at roughly the same reference point F matched to".
       This is a separate, smaller tolerance from ``max_error_px`` (documented
       here as its own parameter, never a hardcoded magic number) because it
       answers a different question: "is this the same point at all", not
       "how consistent is the round trip". Among candidates that pass, the
       one with the smallest anchor distance wins (ties broken by lowest
       round-trip error, then lexicographically smaller ``match_id`` — fully
       deterministic).
    2. **Round-trip measurement.** For the chosen anchor G, the round-trip
       error is the distance between G's ``reference_pixel`` (mapped back
       into source space) and F's own ``source_pixel`` S. If that distance is
       at most ``max_error_px``, ``forward_backward_error_px`` is set to the
       actual measured distance.

    If no reverse record passes the anchor-lookup tolerance, or the chosen
    anchor's round-trip error exceeds ``max_error_px``, ``forward_backward_
    error_px`` is left ``None`` — absence of a consistency partner is not
    evidence of zero error, so it is never defaulted to ``0.0``.
    """
    if reverse_records is None:
        return records

    updated: list[CorrespondenceRecord] = []
    for record in records:
        best_key: tuple[float, float, str] | None = None
        best_round_trip_error: float | None = None

        for reverse in reverse_records:
            anchor_distance = _pixel_distance(reverse.source_pixel, record.reference_pixel)
            if anchor_distance > reverse_lookup_tolerance_px:
                continue
            round_trip_error = _pixel_distance(reverse.reference_pixel, record.source_pixel)
            key = (anchor_distance, round_trip_error, reverse.match_id)
            if best_key is None or key < best_key:
                best_key = key
                best_round_trip_error = round_trip_error

        if best_round_trip_error is not None and best_round_trip_error <= max_error_px:
            updated.append(
                record.model_copy(update={"forward_backward_error_px": best_round_trip_error})
            )
        else:
            updated.append(record)

    return tuple(updated)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def verify_candidates(
    records: tuple[CorrespondenceRecord, ...],
    *,
    reverse_records: tuple[CorrespondenceRecord, ...] | None,
    dedup_radius_px: float,
    nms_radius_px: float,
    fit_residual_threshold_px: float,
    fit_min_inliers: int,
    fit_max_iterations: int,
    fit_seed: int,
    forward_backward_max_error_px: float,
    forward_backward_anchor_tolerance_px: float | None = None,
) -> tuple[CorrespondenceRecord, ...]:
    """Run the full candidate-verification pipeline in this order:

    1. **Forward/backward consistency first.** It only *annotates*
       ``forward_backward_error_px``; it never removes or re-scores a
       record. Running it first means no later, removal-capable step can
       lose information it would have needed.
    2. **Duplicate removal.** Near-identical detections of the same point
       must not be allowed to multiply that point's influence over the
       steps that follow — in particular, several duplicates of the same
       true point could otherwise dominate the robust fit's inlier count
       relative to genuinely independent points.
    3. **Spatial NMS**, for the same reason as duplicate removal: a cluster
       of near-duplicate detections at slightly different locations should
       not out-vote one genuinely well-separated point in the fit.
    4. **Robust affine fit, on NMS survivors only.** Records ``NMS``
       suppressed are excluded from what the fit considers (they never got
       to compete as independent evidence), then the fit is applied.
       Suppressed records are passed through unchanged — they already carry
       their ``nms_status=SUPPRESSED`` explanation, and were never promoted
       to compete for inlier/outlier classification.

    ``verify_forward_backward``'s anchor-lookup tolerance ("is this reverse
    record even looking at the same reference point") is conceptually
    distinct from ``forward_backward_max_error_px`` (the round-trip
    consistency budget, which typically must be looser: it has to absorb
    drift across two independently-run matcher passes, not just matcher
    localization noise). ``forward_backward_anchor_tolerance_px`` exposes
    that as its own parameter. When left ``None``, it defaults to half of
    ``forward_backward_max_error_px`` — documented here as a deliberately
    tighter default (an anchor match should agree much more closely than the
    full round-trip error budget allows), not a hardcoded magic number
    reused for an unrelated purpose.

    Output preserves the record order established by the NMS step (which
    itself preserves duplicate-removal's order, which preserves input
    order minus the records it dropped).
    """
    anchor_tolerance_px = (
        forward_backward_max_error_px / 2.0
        if forward_backward_anchor_tolerance_px is None
        else forward_backward_anchor_tolerance_px
    )
    annotated = verify_forward_backward(
        records,
        reverse_records,
        max_error_px=forward_backward_max_error_px,
        reverse_lookup_tolerance_px=anchor_tolerance_px,
    )
    deduped = remove_duplicate_candidates(annotated, radius_px=dedup_radius_px)
    nms_evaluated = suppress_non_maxima(deduped, radius_px=nms_radius_px)

    survivor_indices = tuple(
        index
        for index, record in enumerate(nms_evaluated)
        if record.nms_status is NmsStatus.SURVIVED
    )
    survivors = tuple(nms_evaluated[index] for index in survivor_indices)

    fit = fit_robust_affine(
        survivors,
        residual_threshold_px=fit_residual_threshold_px,
        min_inliers=fit_min_inliers,
        max_iterations=fit_max_iterations,
        seed=fit_seed,
    )
    fitted_survivors = apply_robust_fit(survivors, fit)
    fitted_by_index = dict(zip(survivor_indices, fitted_survivors, strict=True))

    return tuple(fitted_by_index.get(index, record) for index, record in enumerate(nms_evaluated))
