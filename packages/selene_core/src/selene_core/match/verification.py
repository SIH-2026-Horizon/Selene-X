"""Matching-stage forward/backward and robust affine filtering.

This module intentionally sits in ``match`` rather than reusing the later
selection stage.  A matcher run must be independently auditable before any
coverage-selection policy is applied; the import boundary also prevents an
upstream matching stage from depending on a downstream selection stage.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.types import LocalWarpJacobian

__all__ = ["verify_match_candidates"]

FloatArray = npt.NDArray[np.float64]


def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _reject(record: CorrespondenceRecord, reason: str) -> CorrespondenceRecord:
    return record.model_copy(
        update={
            "is_candidate": False,
            "is_inlier": False,
            "point_role": PointRole.REJECTED,
            "rejection_reason": reason,
        }
    )


def _forward_backward(
    records: tuple[CorrespondenceRecord, ...],
    reverse_records: tuple[CorrespondenceRecord, ...] | None,
    *,
    max_error_px: float,
    anchor_tolerance_px: float,
) -> tuple[CorrespondenceRecord, ...]:
    if reverse_records is None:
        return records
    result: list[CorrespondenceRecord] = []
    for record in records:
        candidates = []
        for reverse in reverse_records:
            anchor = _distance(
                (record.reference_pixel.line, record.reference_pixel.sample),
                (reverse.source_pixel.line, reverse.source_pixel.sample),
            )
            if anchor <= anchor_tolerance_px:
                round_trip = _distance(
                    (record.source_pixel.line, record.source_pixel.sample),
                    (reverse.reference_pixel.line, reverse.reference_pixel.sample),
                )
                candidates.append((anchor, round_trip, reverse.match_id))
        if candidates:
            _anchor, error, _identity = min(candidates)
            if error <= max_error_px:
                result.append(record.model_copy(update={"forward_backward_error_px": error}))
                continue
            result.append(
                _reject(
                    record,
                    f"forward/backward round-trip error {error:.4f}px exceeds "
                    f"max_error_px={max_error_px:.4f}",
                )
            )
            continue
        result.append(
            _reject(
                record,
                "forward/backward reverse candidate is unavailable within "
                f"anchor_tolerance_px={anchor_tolerance_px:.4f}",
            )
        )
    return tuple(result)


def _fit_affine(
    records: tuple[CorrespondenceRecord, ...], indices: tuple[int, ...]
) -> FloatArray | None:
    design = np.array(
        [
            [records[index].source_pixel.line, records[index].source_pixel.sample, 1.0]
            for index in indices
        ],
        dtype=np.float64,
    )
    if np.linalg.matrix_rank(design) < 3:
        return None
    targets = np.array(
        [
            [records[index].reference_pixel.line, records[index].reference_pixel.sample]
            for index in indices
        ],
        dtype=np.float64,
    )
    solution, _residuals, _rank, _singular = np.linalg.lstsq(design, targets, rcond=None)
    return solution


def _residuals(records: tuple[CorrespondenceRecord, ...], solution: FloatArray) -> FloatArray:
    design = np.array(
        [[record.source_pixel.line, record.source_pixel.sample, 1.0] for record in records],
        dtype=np.float64,
    )
    targets = np.array(
        [[record.reference_pixel.line, record.reference_pixel.sample] for record in records],
        dtype=np.float64,
    )
    return np.asarray(
        np.sqrt(np.sum(np.square(targets - design @ solution), axis=1)), dtype=np.float64
    )


def _robust_affine(
    records: tuple[CorrespondenceRecord, ...],
    *,
    residual_threshold_px: float,
    min_inliers: int,
    max_iterations: int,
) -> tuple[CorrespondenceRecord, ...]:
    if len(records) < 3:
        reason = "robust affine fit did not converge: fewer than three candidate correspondences"
        return tuple(_reject(record, reason) for record in records)
    best: tuple[tuple[int, ...], FloatArray, FloatArray] | None = None
    for trial, sample in enumerate(itertools.combinations(range(len(records)), 3)):
        if trial >= max_iterations:
            break
        solution = _fit_affine(records, sample)
        if solution is None:
            continue
        residuals = _residuals(records, solution)
        inliers = tuple(int(index) for index in np.flatnonzero(residuals <= residual_threshold_px))
        rank = (len(inliers), -float(np.sum(residuals[list(inliers)])))
        if best is None or rank > (len(best[0]), -float(np.sum(best[2][list(best[0])]))):
            best = (inliers, solution, residuals)
    if best is None or len(best[0]) < min_inliers:
        reason = (
            "robust affine fit did not converge: insufficient geometrically consistent candidates"
        )
        return tuple(_reject(record, reason) for record in records)
    refit = _fit_affine(records, best[0])
    if refit is None:
        reason = "robust affine fit did not converge: inlier design is rank deficient"
        return tuple(_reject(record, reason) for record in records)
    residuals = _residuals(records, refit)
    inlier_set = set(int(index) for index in np.flatnonzero(residuals <= residual_threshold_px))
    jacobian = LocalWarpJacobian(
        d_ref_line_d_src_line=float(refit[0, 0]),
        d_ref_line_d_src_sample=float(refit[1, 0]),
        d_ref_sample_d_src_line=float(refit[0, 1]),
        d_ref_sample_d_src_sample=float(refit[1, 1]),
    )
    return tuple(
        record.model_copy(
            update={
                "is_inlier": True,
                "local_warp_jacobian": jacobian,
                "robust_model_residual_px": float(residuals[index]),
                "rejection_reason": None,
            }
        )
        if index in inlier_set
        else _reject(
            record.model_copy(
                update={
                    "local_warp_jacobian": jacobian,
                    "robust_model_residual_px": float(residuals[index]),
                }
            ),
            f"robust affine residual {residuals[index]:.4f}px exceeds "
            f"residual_threshold_px={residual_threshold_px:.4f}",
        )
        for index, record in enumerate(records)
    )


def verify_match_candidates(
    records: Iterable[CorrespondenceRecord],
    *,
    reverse_records: tuple[CorrespondenceRecord, ...] | None,
    residual_threshold_px: float,
    min_inliers: int,
    max_iterations: int,
    forward_backward_max_error_px: float,
    forward_backward_anchor_tolerance_px: float | None = None,
) -> tuple[CorrespondenceRecord, ...]:
    """Annotate reciprocal evidence then fit a deterministic RANSAC affine model."""
    if residual_threshold_px <= 0 or min_inliers < 3 or max_iterations < 1:
        raise ValueError(
            "robust verification parameters must be positive and min_inliers at least three"
        )
    if forward_backward_max_error_px <= 0:
        raise ValueError("forward_backward_max_error_px must be positive")
    anchor = (
        forward_backward_max_error_px / 2.0
        if forward_backward_anchor_tolerance_px is None
        else forward_backward_anchor_tolerance_px
    )
    if anchor <= 0:
        raise ValueError("forward_backward_anchor_tolerance_px must be positive")
    annotated = _forward_backward(
        tuple(records),
        reverse_records,
        max_error_px=forward_backward_max_error_px,
        anchor_tolerance_px=anchor,
    )
    active = tuple(record for record in annotated if record.is_candidate)
    fitted = _robust_affine(
        active,
        residual_threshold_px=residual_threshold_px,
        min_inliers=min_inliers,
        max_iterations=max_iterations,
    )
    fitted_by_id = {record.match_id: record for record in fitted}
    return tuple(fitted_by_id.get(record.match_id, record) for record in annotated)
