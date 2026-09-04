"""Limited robust source-frame adjustment from caller-supplied linearisations.

This module deliberately does not know how to create a physical sensor model.
Its narrow equation is, for each canonical correspondence record ``i``::

    observed_source_residual_yx_px[i] = A_yx_by_parameter[i] @ parameters + error[i]

``y/x`` means ``(line, sample)`` throughout this module.  The caller supplies
both the measured source-frame residual and its local design matrix ``A``.  A
real CSM/ISIS or pushbroom implementation can supply those quantities later;
this core neither invents one nor exports an adjusted sensor model.

For a fitting record, ``Covariance2D(xx, xy, yy)`` is interpreted as the full
``[[xx, xy], [xy, yy]]`` covariance in that same ``(line, sample)`` order.
The canonical pixel coordinates are retained for identity and diagnostics only;
this module does not derive a correction from source/reference coordinates.

Fitting uses the complete calibrated source-pixel covariance of every fitting
record.  The robust loss is Huber on the covariance-whitened residual norm.
Withheld check points never enter the weighted system or the robust-weight
updates, and are evaluated only after a fit has converged.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.types import CovarianceFrame

__all__ = [
    "AdjustmentInputError",
    "AdjustmentOptions",
    "AdjustmentParameter",
    "AdjustmentParameterization",
    "AdjustmentResult",
    "ObservationLinearization",
    "ParameterReduction",
    "ParameterizationAttempt",
    "ReductionPolicy",
    "ResidualDiagnostic",
    "ResidualMetrics",
    "ScanLineResidualCorrelation",
    "fit_adjustment",
    "translation_only_parameterization",
]

_YX_COMPONENT_COUNT: Final = 2
_LIMITATIONS: Final[tuple[str, ...]] = (
    "This is a limited in-memory source-frame linearized correction, not a physical sensor model.",
    "Residual vectors use (line, sample) = (y, x) order in source-pixel units.",
    "No scene-wide pixel-to-metre conversion or absolute metre accuracy is provided.",
    "No pushbroom geometry, terrain renderer, platform-jitter model, or graph adjustment "
    "is provided.",
    "A physical sensor-model exporter remains required.",
)


class AdjustmentInputError(ValueError):
    """A deterministic violation of the limited adjustment input contract."""


class ReductionPolicy(StrEnum):
    """How an unobservable requested parameterization is handled."""

    REJECT = "reject"
    """Reject rank-deficient or ill-conditioned requested models (the default)."""

    DROP_OPTIONAL_TERMS = "drop_optional_terms"
    """Drop documented optional terms in reverse declared order, then retry."""


@dataclass(frozen=True, slots=True)
class AdjustmentParameter:
    """One immutable correction parameter in a declared source-frame model.

    ``name``, ``unit``, and its position in :class:`AdjustmentParameterization`
    are the complete parameter convention.  ``optional`` is the only kind of
    term the explicit reduction policy may remove.
    """

    name: str
    unit: str
    optional: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise AdjustmentInputError("adjustment parameter name must not be empty")
        if not self.unit.strip():
            raise AdjustmentInputError(
                f"adjustment parameter {self.name!r} must declare a non-empty unit"
            )


@dataclass(frozen=True, slots=True)
class AdjustmentParameterization:
    """An ordered, immutable set of limited correction parameters."""

    parameters: tuple[AdjustmentParameter, ...]

    def __post_init__(self) -> None:
        parameters = tuple(self.parameters)
        if not parameters:
            raise AdjustmentInputError(
                "adjustment parameterization must contain at least one parameter"
            )
        names = tuple(parameter.name for parameter in parameters)
        if len(set(names)) != len(names):
            raise AdjustmentInputError(
                "adjustment parameterization contains duplicate parameter names"
            )
        object.__setattr__(self, "parameters", parameters)

    @property
    def parameter_names(self) -> tuple[str, ...]:
        """Names in the only valid design-matrix column order."""
        return tuple(parameter.name for parameter in self.parameters)

    @property
    def parameter_count(self) -> int:
        """The required number of columns in every observation design matrix."""
        return len(self.parameters)

    def select(self, indices: tuple[int, ...]) -> AdjustmentParameterization:
        """Return the declared subset in original order for reduction evidence."""
        return AdjustmentParameterization(tuple(self.parameters[index] for index in indices))


def translation_only_parameterization() -> AdjustmentParameterization:
    """The smallest supported correction: source line then sample translation.

    The parameter order is ``(line_translation_px, sample_translation_px)``.
    Corresponding observation vectors and residual vectors use the same
    ``(line, sample) = (y, x)`` order.
    """
    return AdjustmentParameterization(
        (
            AdjustmentParameter("line_translation_px", "px"),
            AdjustmentParameter("sample_translation_px", "px"),
        )
    )


@dataclass(frozen=True, slots=True)
class ObservationLinearization:
    """The caller-supplied numerical observation for one correspondence.

    ``source_residual_yx_px`` is a measured correction in source-pixel
    ``(line, sample) = (y, x)`` order.  ``design_matrix_yx_by_parameter`` has
    exactly two rows in that order, and columns in the immutable order of the
    parameterization supplied to :func:`fit_adjustment`.
    """

    observation_id: str
    source_residual_yx_px: tuple[float, float]
    design_matrix_yx_by_parameter: npt.NDArray[np.float64]

    def __post_init__(self) -> None:
        if not self.observation_id.strip():
            raise AdjustmentInputError("adjustment observation ID must not be empty")
        residual = tuple(float(value) for value in self.source_residual_yx_px)
        if len(residual) != _YX_COMPONENT_COUNT or not all(
            math.isfinite(value) for value in residual
        ):
            raise AdjustmentInputError(
                "adjustment source_residual_yx_px must contain two finite (line, sample) values"
            )
        matrix = np.asarray(self.design_matrix_yx_by_parameter, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[0] != _YX_COMPONENT_COUNT:
            raise AdjustmentInputError(
                "adjustment design_matrix_yx_by_parameter shape must be (2, parameter_count)"
            )
        if matrix.shape[1] == 0:
            raise AdjustmentInputError(
                "adjustment design_matrix_yx_by_parameter must contain at least one "
                "parameter column"
            )
        if not bool(np.all(np.isfinite(matrix))):
            raise AdjustmentInputError("adjustment design_matrix_yx_by_parameter must be finite")
        immutable_matrix = matrix.copy()
        immutable_matrix.setflags(write=False)
        object.__setattr__(self, "source_residual_yx_px", residual)
        object.__setattr__(self, "design_matrix_yx_by_parameter", immutable_matrix)


@dataclass(frozen=True, slots=True)
class AdjustmentOptions:
    """Explicit numerical tolerances and robust-loss settings for a fit."""

    huber_delta: float = 1.345
    max_iterations: int = 30
    parameter_tolerance: float = 1e-10
    robust_weight_tolerance: float = 1e-10
    rank_tolerance: float = 1e-12
    """Relative singular-value threshold used to determine numerical rank."""
    condition_number_limit: float = 1e10
    correlation_std_tolerance: float = 1e-12
    reduction_policy: ReductionPolicy = ReductionPolicy.REJECT

    def __post_init__(self) -> None:
        if not math.isfinite(self.huber_delta) or self.huber_delta <= 0.0:
            raise AdjustmentInputError("adjustment huber_delta must be finite and positive")
        max_iterations_value: object = self.max_iterations
        if isinstance(max_iterations_value, bool) or not isinstance(max_iterations_value, int):
            raise AdjustmentInputError(
                "adjustment max_iterations must be a finite integer at least one"
            )
        if self.max_iterations < 1:
            raise AdjustmentInputError("adjustment max_iterations must be at least one")
        for field_name in (
            "parameter_tolerance",
            "robust_weight_tolerance",
            "rank_tolerance",
            "correlation_std_tolerance",
        ):
            value = getattr(self, field_name)
            if not math.isfinite(value) or value <= 0.0:
                raise AdjustmentInputError(f"adjustment {field_name} must be finite and positive")
        if not math.isfinite(self.condition_number_limit) or self.condition_number_limit <= 1.0:
            raise AdjustmentInputError(
                "adjustment condition_number_limit must be finite and greater than one"
            )
        if not isinstance(self.reduction_policy, ReductionPolicy):
            raise AdjustmentInputError("adjustment reduction_policy must be a ReductionPolicy")


@dataclass(frozen=True, slots=True)
class ParameterReduction:
    """Evidence for an explicit, deterministic optional-term reduction."""

    dropped_parameter_names: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ParameterizationAttempt:
    """Immutable observability evidence for one requested parameter subset.

    The declared parameter names retain their original order.  An accepted
    attempt has ``rejection_reason=None``; a rejected attempt records its
    numerical rank and, where observable, its column-scaled whitened-system
    condition number.
    """

    parameter_names: tuple[str, ...]
    rejection_reason: str | None
    rank: int
    condition_number: float | None
    iteration_count: int


@dataclass(frozen=True, slots=True)
class ResidualMetrics:
    """Source-frame residual metrics, never expressed as metre accuracy.

    ``rmse_y_px`` is line RMSE and ``rmse_x_px`` is sample RMSE.  The fitting
    metrics are diagnostic only; ``independent=False`` prevents them being
    interpreted as an independent accuracy measure.  Withheld metrics have
    ``independent=True`` precisely because withheld records never enter fitting.
    """

    count: int
    rmse_y_px: float | None
    rmse_x_px: float | None
    rmse_2d_px: float | None
    median_endpoint_error_px: float | None
    p90_endpoint_error_px: float | None
    independent: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResidualDiagnostic:
    """One source-frame residual vector in ``(line, sample) = (y, x)`` order."""

    record_id: str
    point_role: PointRole
    source_line_px: float
    residual_yx_px: tuple[float, float]
    mahalanobis_norm: float | None
    robust_weight: float | None


@dataclass(frozen=True, slots=True)
class ScanLineResidualCorrelation:
    """Correlation of source scan line with line/sample residual components."""

    line_to_residual_y: float | None
    line_to_residual_x: float | None
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class AdjustmentResult:
    """Immutable evidence for a successful or explicitly rejected adjustment.

    A successful result is a numerical correction variant only.  It is not an
    adjusted CSM/ISIS file, and ``physical_sensor_model_export_required`` is
    always true to keep that boundary explicit.

    ``parameter_covariance`` is deliberately always ``None``.  This module
    does not yet estimate a calibrated Huber M-estimator sandwich covariance,
    so reporting the inverse final IRLS information matrix as a covariance
    would overstate uncertainty evidence.  The distinct
    ``conditional_information_inverse`` is retained for diagnostics only: it
    is the inverse of the final fixed-weight information matrix and conditions
    on the data-derived Huber weights.
    """

    accepted: bool
    converged: bool
    requested_parameterization: AdjustmentParameterization
    parameterization_used: AdjustmentParameterization | None
    parameter_values: tuple[float, ...] | None
    parameter_covariance: None
    conditional_information_inverse: tuple[tuple[float, ...], ...] | None
    iteration_count: int
    rank: int
    condition_number: float | None
    robust_weighted_loss: float | None
    residual_diagnostics: tuple[ResidualDiagnostic, ...]
    fitting_metrics: ResidualMetrics
    withheld_metrics: ResidualMetrics
    scan_line_residual_correlation: ScanLineResidualCorrelation
    rejection_reason: str | None
    reduction: ParameterReduction | None
    parameterization_attempts: tuple[ParameterizationAttempt, ...]
    limitations: tuple[str, ...] = _LIMITATIONS
    physical_sensor_model_export_required: bool = True


@dataclass(frozen=True, slots=True)
class _FitAttempt:
    accepted: bool
    converged: bool
    parameter_values: npt.NDArray[np.float64] | None
    conditional_information_inverse: npt.NDArray[np.float64] | None
    iteration_count: int
    rank: int
    condition_number: float | None
    robust_weights: npt.NDArray[np.float64] | None
    rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class _LinearSolve:
    """A stable weighted linear solve before IRLS convergence bookkeeping."""

    parameter_values: npt.NDArray[np.float64] | None
    conditional_information_inverse: npt.NDArray[np.float64] | None
    rank: int
    condition_number: float | None
    rejection_reason: str | None


def fit_adjustment(
    records: Sequence[CorrespondenceRecord],
    observations: Sequence[ObservationLinearization],
    parameterization: AdjustmentParameterization,
    *,
    options: AdjustmentOptions | None = None,
) -> AdjustmentResult:
    """Fit a limited robust source-frame correction from canonical records.

    Only :attr:`~selene_core.match.correspondence.PointRole.FITTING_INLIER`
    records with calibrated, positive-definite source-pixel covariance are
    allowed into the Huber IRLS weighted linear system.  Records marked
    ``WITHHELD_CHECK_POINT`` are deliberately omitted from every fit iteration
    and then evaluated using the accepted correction.

    Input identity errors raise :class:`AdjustmentInputError`.  Numerical
    unobservability, poor conditioning, and non-convergence instead return an
    immutable rejected :class:`AdjustmentResult` with a stable reason, so the
    caller can record scientific evidence without mistaking it for a solution.
    No pseudo-inverse is ever used.
    """
    fit_options = AdjustmentOptions() if options is None else options
    records_by_id, observations_by_id = _validate_inputs(records, observations, parameterization)
    fitting_ids = tuple(
        record_id
        for record_id, record in records_by_id.items()
        if record.point_role is PointRole.FITTING_INLIER
    )
    withheld_ids = tuple(
        record_id
        for record_id, record in records_by_id.items()
        if record.point_role is PointRole.WITHHELD_CHECK_POINT
    )
    if not fitting_ids:
        raise AdjustmentInputError("adjustment requires at least one fitting-inlier record")

    fitting_data = tuple(
        (records_by_id[record_id], observations_by_id[record_id]) for record_id in fitting_ids
    )
    active_indices = tuple(range(parameterization.parameter_count))
    dropped_parameter_names: list[str] = []
    parameterization_attempts: list[ParameterizationAttempt] = []
    while True:
        attempt = _fit_irls(fitting_data, active_indices, fit_options)
        attempted_parameterization = parameterization.select(active_indices)
        parameterization_attempts.append(
            ParameterizationAttempt(
                parameter_names=attempted_parameterization.parameter_names,
                rejection_reason=attempt.rejection_reason,
                rank=attempt.rank,
                condition_number=attempt.condition_number,
                iteration_count=attempt.iteration_count,
            )
        )
        can_reduce = (
            fit_options.reduction_policy is ReductionPolicy.DROP_OPTIONAL_TERMS
            and attempt.rejection_reason in {"rank_deficient", "ill_conditioned"}
        )
        optional_active_indices = tuple(
            index for index in active_indices if parameterization.parameters[index].optional
        )
        if not can_reduce or not optional_active_indices:
            break
        if len(active_indices) == 1:
            # A reduction may remove only optional terms, but a zero-parameter
            # model is not a correction model and cannot be fitted.
            break
        index_to_drop = optional_active_indices[-1]
        dropped_parameter_names.append(parameterization.parameters[index_to_drop].name)
        active_indices = tuple(index for index in active_indices if index != index_to_drop)

    parameterization_used = parameterization.select(active_indices) if attempt.accepted else None
    reduction = (
        ParameterReduction(
            dropped_parameter_names=tuple(dropped_parameter_names),
            reason=(
                "dropped optional terms in reverse declared order after the recorded rank or "
                "conditioning rejections; required terms were retained"
            ),
        )
        if dropped_parameter_names
        else None
    )
    if not attempt.accepted or attempt.parameter_values is None:
        return _rejected_result(
            parameterization,
            attempt,
            reduction,
            tuple(parameterization_attempts),
            fitting_count=len(fitting_ids),
            withheld_count=len(withheld_ids),
        )

    if (
        parameterization_used is None
        or attempt.robust_weights is None
        or attempt.conditional_information_inverse is None
    ):
        return _rejected_result(
            parameterization,
            _FitAttempt(
                accepted=False,
                converged=False,
                parameter_values=None,
                conditional_information_inverse=None,
                iteration_count=attempt.iteration_count,
                rank=attempt.rank,
                condition_number=attempt.condition_number,
                robust_weights=None,
                rejection_reason="internal_incomplete_fit",
            ),
            reduction,
            tuple(parameterization_attempts),
            fitting_count=len(fitting_ids),
            withheld_count=len(withheld_ids),
        )
    diagnostics = _diagnostics(
        records_by_id,
        observations_by_id,
        active_indices,
        attempt.parameter_values,
        fitting_ids,
        withheld_ids,
        attempt.robust_weights,
    )
    fitting_diagnostics = tuple(
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.point_role is PointRole.FITTING_INLIER
    )
    withheld_diagnostics = tuple(
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.point_role is PointRole.WITHHELD_CHECK_POINT
    )
    fitting_metrics = _metrics(fitting_diagnostics, independent=False)
    withheld_metrics = _metrics(
        withheld_diagnostics,
        independent=True,
        empty_reason="no withheld check-point records were supplied",
    )
    return AdjustmentResult(
        accepted=True,
        converged=True,
        requested_parameterization=parameterization,
        parameterization_used=parameterization_used,
        parameter_values=tuple(float(value) for value in attempt.parameter_values),
        parameter_covariance=None,
        conditional_information_inverse=_immutable_matrix_tuple(
            attempt.conditional_information_inverse
        ),
        iteration_count=attempt.iteration_count,
        rank=attempt.rank,
        condition_number=attempt.condition_number,
        robust_weighted_loss=_huber_loss(fitting_diagnostics, fit_options.huber_delta),
        residual_diagnostics=diagnostics,
        fitting_metrics=fitting_metrics,
        withheld_metrics=withheld_metrics,
        scan_line_residual_correlation=_scan_line_correlation(fitting_diagnostics, fit_options),
        rejection_reason=None,
        reduction=reduction,
        parameterization_attempts=tuple(parameterization_attempts),
    )


def _validate_inputs(
    records: Sequence[CorrespondenceRecord],
    observations: Sequence[ObservationLinearization],
    parameterization: AdjustmentParameterization,
) -> tuple[dict[str, CorrespondenceRecord], dict[str, ObservationLinearization]]:
    records_by_id: dict[str, CorrespondenceRecord] = {}
    for record in records:
        record_id = record.match_id
        if not record_id.strip():
            raise AdjustmentInputError("adjustment record ID must not be empty")
        if record_id in records_by_id:
            raise AdjustmentInputError(f"adjustment contains duplicate record ID {record_id!r}")
        if record.point_role not in {
            PointRole.FITTING_INLIER,
            PointRole.WITHHELD_CHECK_POINT,
        }:
            raise AdjustmentInputError(
                "adjustment records must be FITTING_INLIER or WITHHELD_CHECK_POINT; "
                f"record {record_id!r} has role {record.point_role.value!r}"
            )
        if record.point_role is PointRole.FITTING_INLIER:
            if record.covariance is None:
                raise AdjustmentInputError(
                    f"adjustment fitting record {record_id!r} has missing source-pixel covariance"
                )
            if not record.covariance_calibrated:
                raise AdjustmentInputError(
                    f"adjustment fitting record {record_id!r} has uncalibrated source-pixel "
                    "covariance"
                )
            if record.covariance.frame is not CovarianceFrame.SOURCE_PIXEL:
                raise AdjustmentInputError(
                    f"adjustment fitting record {record_id!r} covariance must be in "
                    "source_pixel frame"
                )
        records_by_id[record_id] = record

    observations_by_id: dict[str, ObservationLinearization] = {}
    for observation in observations:
        observation_id = observation.observation_id
        if observation_id in observations_by_id:
            raise AdjustmentInputError(
                f"adjustment contains duplicate observation ID {observation_id!r}"
            )
        if observation.design_matrix_yx_by_parameter.shape[1] != parameterization.parameter_count:
            raise AdjustmentInputError(
                "adjustment design_matrix_yx_by_parameter shape must be "
                f"(2, {parameterization.parameter_count}) for parameterization columns"
            )
        observations_by_id[observation_id] = observation

    record_ids = set(records_by_id)
    observation_ids = set(observations_by_id)
    missing_ids = tuple(sorted(record_ids - observation_ids))
    extra_ids = tuple(sorted(observation_ids - record_ids))
    if missing_ids:
        raise AdjustmentInputError(f"adjustment has missing observation IDs: {missing_ids!r}")
    if extra_ids:
        raise AdjustmentInputError(f"adjustment has unknown observation IDs: {extra_ids!r}")
    return records_by_id, observations_by_id


def _fit_irls(
    fitting_data: tuple[tuple[CorrespondenceRecord, ObservationLinearization], ...],
    active_indices: tuple[int, ...],
    options: AdjustmentOptions,
) -> _FitAttempt:
    parameter_count = len(active_indices)
    weights = np.ones(len(fitting_data), dtype=np.float64)
    parameters = np.zeros(parameter_count, dtype=np.float64)
    rank = 0
    condition_number: float | None = None

    for iteration in range(1, options.max_iterations + 1):
        solve = _solve_weighted_system(fitting_data, active_indices, weights, options)
        rank = solve.rank
        condition_number = solve.condition_number
        if solve.rejection_reason is not None:
            return _FitAttempt(
                accepted=False,
                converged=False,
                parameter_values=None,
                conditional_information_inverse=None,
                iteration_count=iteration - 1,
                rank=rank,
                condition_number=condition_number,
                robust_weights=None,
                rejection_reason=solve.rejection_reason,
            )
        if solve.parameter_values is None:
            raise RuntimeError("accepted weighted solve must contain parameter values")
        candidate_parameters = solve.parameter_values
        candidate_weights = _huber_weights(
            fitting_data, active_indices, candidate_parameters, options.huber_delta
        )
        parameter_change = float(np.linalg.norm(candidate_parameters - parameters))
        parameter_scale = max(1.0, float(np.linalg.norm(candidate_parameters)))
        weight_change = float(np.max(np.abs(candidate_weights - weights)))
        parameters = candidate_parameters
        weights = candidate_weights
        if (
            parameter_change <= options.parameter_tolerance * parameter_scale
            and weight_change <= options.robust_weight_tolerance
        ):
            final_solve = _solve_weighted_system(fitting_data, active_indices, weights, options)
            rank = final_solve.rank
            condition_number = final_solve.condition_number
            if final_solve.rejection_reason is not None:
                return _FitAttempt(
                    accepted=False,
                    converged=False,
                    parameter_values=None,
                    conditional_information_inverse=None,
                    iteration_count=iteration,
                    rank=rank,
                    condition_number=condition_number,
                    robust_weights=None,
                    rejection_reason=final_solve.rejection_reason,
                )
            if (
                final_solve.parameter_values is None
                or final_solve.conditional_information_inverse is None
            ):
                raise RuntimeError("accepted weighted solve must contain information evidence")
            final_parameters = final_solve.parameter_values
            return _FitAttempt(
                accepted=True,
                converged=True,
                parameter_values=final_parameters,
                conditional_information_inverse=final_solve.conditional_information_inverse,
                iteration_count=iteration,
                rank=rank,
                condition_number=condition_number,
                robust_weights=_huber_weights(
                    fitting_data, active_indices, final_parameters, options.huber_delta
                ),
                rejection_reason=None,
            )
    return _FitAttempt(
        accepted=False,
        converged=False,
        parameter_values=None,
        conditional_information_inverse=None,
        iteration_count=options.max_iterations,
        rank=rank,
        condition_number=condition_number,
        robust_weights=None,
        rejection_reason="did_not_converge",
    )


def _whitened_weighted_system(
    fitting_data: tuple[tuple[CorrespondenceRecord, ObservationLinearization], ...],
    active_indices: tuple[int, ...],
    robust_weights: npt.NDArray[np.float64],
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """Build a full-covariance-whitened system without forming ``AᵀA``."""
    weighted_design_rows: list[npt.NDArray[np.float64]] = []
    weighted_target_rows: list[npt.NDArray[np.float64]] = []
    for (record, observation), robust_weight in zip(fitting_data, robust_weights, strict=True):
        lower_covariance_factor = _source_covariance_cholesky(record)
        design = observation.design_matrix_yx_by_parameter[:, active_indices]
        target = np.asarray(observation.source_residual_yx_px, dtype=np.float64)
        robust_scale = math.sqrt(float(robust_weight))
        weighted_design_rows.append(robust_scale * np.linalg.solve(lower_covariance_factor, design))
        weighted_target_rows.append(robust_scale * np.linalg.solve(lower_covariance_factor, target))
    return np.vstack(weighted_design_rows), np.concatenate(weighted_target_rows)


def _solve_weighted_system(
    fitting_data: tuple[tuple[CorrespondenceRecord, ObservationLinearization], ...],
    active_indices: tuple[int, ...],
    robust_weights: npt.NDArray[np.float64],
    options: AdjustmentOptions,
) -> _LinearSolve:
    weighted_design, weighted_target = _whitened_weighted_system(
        fitting_data, active_indices, robust_weights
    )
    column_scales = np.max(np.abs(weighted_design), axis=0)
    column_scales = np.where(column_scales > 0.0, column_scales, 1.0)
    scaled_design = weighted_design / column_scales
    singular_values = np.linalg.svd(scaled_design, compute_uv=False)
    largest = float(singular_values[0])
    rank_threshold = options.rank_tolerance * largest
    rank = int(np.sum(singular_values > rank_threshold))
    parameter_count = scaled_design.shape[1]
    if rank < parameter_count:
        return _LinearSolve(None, None, rank, None, "rank_deficient")
    smallest = float(singular_values[-1])
    condition_number = math.inf if smallest <= rank_threshold else largest / smallest
    if not math.isfinite(condition_number) or condition_number > options.condition_number_limit:
        return _LinearSolve(None, None, rank, condition_number, "ill_conditioned")
    left_vectors, singular_values, right_vectors_transpose = np.linalg.svd(
        scaled_design, full_matrices=False
    )
    scaled_parameters = right_vectors_transpose.T @ (
        (left_vectors.T @ weighted_target) / singular_values
    )
    parameter_values = scaled_parameters / column_scales
    inverse_scaled_information = (
        right_vectors_transpose.T * (1.0 / singular_values**2)
    ) @ right_vectors_transpose
    conditional_information_inverse = inverse_scaled_information / column_scales[:, np.newaxis]
    conditional_information_inverse = conditional_information_inverse / column_scales[np.newaxis, :]
    return _LinearSolve(
        parameter_values,
        conditional_information_inverse,
        rank,
        condition_number,
        None,
    )


def _huber_weights(
    fitting_data: tuple[tuple[CorrespondenceRecord, ObservationLinearization], ...],
    active_indices: tuple[int, ...],
    parameters: npt.NDArray[np.float64],
    huber_delta: float,
) -> npt.NDArray[np.float64]:
    weights = np.empty(len(fitting_data), dtype=np.float64)
    for index, (record, observation) in enumerate(fitting_data):
        residual = _residual(observation, active_indices, parameters)
        whitened_residual = np.linalg.solve(_source_covariance_cholesky(record), residual)
        norm = float(np.linalg.norm(whitened_residual))
        weights[index] = 1.0 if norm <= huber_delta else huber_delta / norm
    return weights


def _residual(
    observation: ObservationLinearization,
    active_indices: tuple[int, ...],
    parameters: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    design = observation.design_matrix_yx_by_parameter[:, active_indices]
    target = np.asarray(observation.source_residual_yx_px, dtype=np.float64)
    return target - design @ parameters


def _diagnostics(
    records_by_id: dict[str, CorrespondenceRecord],
    observations_by_id: dict[str, ObservationLinearization],
    active_indices: tuple[int, ...],
    parameters: npt.NDArray[np.float64],
    fitting_ids: tuple[str, ...],
    withheld_ids: tuple[str, ...],
    fitting_weights: npt.NDArray[np.float64],
) -> tuple[ResidualDiagnostic, ...]:
    fitting_weight_by_id = dict(zip(fitting_ids, fitting_weights, strict=True))
    diagnostics: list[ResidualDiagnostic] = []
    for record_id, record in records_by_id.items():
        observation = observations_by_id[record_id]
        residual = _residual(observation, active_indices, parameters)
        mahalanobis_norm = _mahalanobis_norm(record, residual)
        robust_weight = (
            float(fitting_weight_by_id[record_id]) if record_id in fitting_weight_by_id else None
        )
        diagnostics.append(
            ResidualDiagnostic(
                record_id=record_id,
                point_role=record.point_role,
                source_line_px=record.source_pixel.line,
                residual_yx_px=(float(residual[0]), float(residual[1])),
                mahalanobis_norm=mahalanobis_norm,
                robust_weight=robust_weight,
            )
        )
    return tuple(diagnostics)


def _mahalanobis_norm(
    record: CorrespondenceRecord, residual: npt.NDArray[np.float64]
) -> float | None:
    if record.covariance is None or record.covariance.frame is not CovarianceFrame.SOURCE_PIXEL:
        return None
    whitened_residual = np.linalg.solve(_source_covariance_cholesky(record), residual)
    return float(np.linalg.norm(whitened_residual))


def _source_covariance_cholesky(record: CorrespondenceRecord) -> npt.NDArray[np.float64]:
    """Return a fitting record's full source-frame covariance Cholesky factor."""
    covariance = record.covariance
    if covariance is None or covariance.frame is not CovarianceFrame.SOURCE_PIXEL:
        raise AdjustmentInputError(
            f"adjustment fitting record {record.match_id!r} has invalid source-pixel covariance"
        )
    covariance_matrix = np.array(
        (
            (covariance.xx, covariance.xy),
            (covariance.xy, covariance.yy),
        ),
        dtype=np.float64,
    )
    try:
        return np.linalg.cholesky(covariance_matrix)
    except np.linalg.LinAlgError as error:
        raise AdjustmentInputError(
            f"adjustment fitting record {record.match_id!r} has unusable source-pixel covariance"
        ) from error


def _metrics(
    diagnostics: tuple[ResidualDiagnostic, ...],
    *,
    independent: bool,
    empty_reason: str | None = None,
) -> ResidualMetrics:
    if not diagnostics:
        return ResidualMetrics(
            count=0,
            rmse_y_px=None,
            rmse_x_px=None,
            rmse_2d_px=None,
            median_endpoint_error_px=None,
            p90_endpoint_error_px=None,
            independent=independent,
            unavailable_reason=empty_reason or "no residual diagnostics are available",
        )
    residuals = np.asarray(
        tuple(diagnostic.residual_yx_px for diagnostic in diagnostics), dtype=np.float64
    )
    endpoint_error = np.hypot(residuals[:, 0], residuals[:, 1])
    return ResidualMetrics(
        count=len(diagnostics),
        rmse_y_px=float(math.sqrt(float(np.mean(residuals[:, 0] ** 2)))),
        rmse_x_px=float(math.sqrt(float(np.mean(residuals[:, 1] ** 2)))),
        rmse_2d_px=float(math.sqrt(float(np.mean(endpoint_error**2)))),
        median_endpoint_error_px=float(np.percentile(endpoint_error, 50.0, method="linear")),
        p90_endpoint_error_px=float(np.percentile(endpoint_error, 90.0, method="linear")),
        independent=independent,
    )


def _scan_line_correlation(
    diagnostics: tuple[ResidualDiagnostic, ...], options: AdjustmentOptions
) -> ScanLineResidualCorrelation:
    if len(diagnostics) < 2:
        return ScanLineResidualCorrelation(
            line_to_residual_y=None,
            line_to_residual_x=None,
            unavailable_reason=(
                "at least two fitting residuals are required for scan-line correlation"
            ),
        )
    lines = np.asarray(
        tuple(diagnostic.source_line_px for diagnostic in diagnostics), dtype=np.float64
    )
    residuals = np.asarray(
        tuple(diagnostic.residual_yx_px for diagnostic in diagnostics), dtype=np.float64
    )
    correlation_y = _pearson_correlation(lines, residuals[:, 0], options.correlation_std_tolerance)
    correlation_x = _pearson_correlation(lines, residuals[:, 1], options.correlation_std_tolerance)
    unavailable_reason = (
        "scan-line coordinate or residual component has insufficient variation for correlation"
        if correlation_y is None and correlation_x is None
        else None
    )
    return ScanLineResidualCorrelation(
        line_to_residual_y=correlation_y,
        line_to_residual_x=correlation_x,
        unavailable_reason=unavailable_reason,
    )


def _pearson_correlation(
    first: npt.NDArray[np.float64], second: npt.NDArray[np.float64], std_tolerance: float
) -> float | None:
    centred_first = first - np.mean(first)
    centred_second = second - np.mean(second)
    first_norm = float(np.linalg.norm(centred_first))
    second_norm = float(np.linalg.norm(centred_second))
    if first_norm <= std_tolerance or second_norm <= std_tolerance:
        return None
    return float(np.dot(centred_first, centred_second) / (first_norm * second_norm))


def _huber_loss(diagnostics: tuple[ResidualDiagnostic, ...], huber_delta: float) -> float:
    loss = 0.0
    for diagnostic in diagnostics:
        if diagnostic.mahalanobis_norm is None:
            continue
        norm = diagnostic.mahalanobis_norm
        loss += (
            0.5 * norm * norm if norm <= huber_delta else huber_delta * (norm - 0.5 * huber_delta)
        )
    return float(loss)


def _immutable_matrix_tuple(matrix: npt.NDArray[np.float64]) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in matrix)


def _rejected_result(
    parameterization: AdjustmentParameterization,
    attempt: _FitAttempt,
    reduction: ParameterReduction | None,
    parameterization_attempts: tuple[ParameterizationAttempt, ...],
    *,
    fitting_count: int,
    withheld_count: int,
) -> AdjustmentResult:
    reason = attempt.rejection_reason or "unknown_rejection"
    unavailable_reason = f"adjustment was rejected: {reason}"
    return AdjustmentResult(
        accepted=False,
        converged=False,
        requested_parameterization=parameterization,
        parameterization_used=None,
        parameter_values=None,
        parameter_covariance=None,
        conditional_information_inverse=None,
        iteration_count=attempt.iteration_count,
        rank=attempt.rank,
        condition_number=attempt.condition_number,
        robust_weighted_loss=None,
        residual_diagnostics=(),
        fitting_metrics=ResidualMetrics(
            count=fitting_count,
            rmse_y_px=None,
            rmse_x_px=None,
            rmse_2d_px=None,
            median_endpoint_error_px=None,
            p90_endpoint_error_px=None,
            independent=False,
            unavailable_reason=unavailable_reason,
        ),
        withheld_metrics=ResidualMetrics(
            count=withheld_count,
            rmse_y_px=None,
            rmse_x_px=None,
            rmse_2d_px=None,
            median_endpoint_error_px=None,
            p90_endpoint_error_px=None,
            independent=True,
            unavailable_reason=unavailable_reason,
        ),
        scan_line_residual_correlation=ScanLineResidualCorrelation(
            line_to_residual_y=None,
            line_to_residual_x=None,
            unavailable_reason=unavailable_reason,
        ),
        rejection_reason=reason,
        reduction=reduction,
        parameterization_attempts=parameterization_attempts,
    )
