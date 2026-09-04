"""Deterministic in-memory registration route for local diagnostics.

This is deliberately a *non-qualified* route.  It joins the established
array-level matcher, verification, coverage, refinement, adjustment, and
verdict contracts without inventing mission geometry, control, or route
qualification.  A completed local run is useful as a reproducible diagnostic,
but never an accepted scientific result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np
import numpy.typing as npt
from pydantic import Field

from selene_core.adjust import (
    AdjustmentInputError,
    AdjustmentResult,
    ObservationLinearization,
    fit_adjustment,
    translation_only_parameterization,
)
from selene_core.contracts import Contract
from selene_core.hashing import digest_json
from selene_core.match import (
    MatchParameters,
    MatchPrior,
    NccMatcher,
    VerificationParameters,
    run_classical_match,
)
from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.metrics.verdict import SceneVerdict, compute_scene_verdict
from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.results import StageFailure
from selene_core.refine.covariance import CalibrationResult
from selene_core.refine.patch_refinement import refine_correspondence
from selene_core.select.coverage import (
    EligibilityGrid,
    compute_coverage_metrics,
    select_grid_coverage,
)

__all__ = [
    "AdjustmentEvidence",
    "ArrayArtifactHandles",
    "CoverageEvidence",
    "LocalRegistrationConfig",
    "PipelineDisposition",
    "PipelineOrigin",
    "PipelineProvenance",
    "PipelineResult",
    "PipelineStageEvidence",
    "RefinementEvidence",
    "ResolvedPipelineParameters",
    "run_local_registration",
]


class PipelineOrigin(StrEnum):
    """What this local route's inputs represent, never mission qualification."""

    SYNTHETIC_TEST = "synthetic_test"
    LOCAL_NON_QUALIFIED = "local_non_qualified"


class PipelineDisposition(StrEnum):
    """Operational result, distinct from the always fail-closed scene verdict."""

    REVIEW = "review"
    REJECTED = "rejected"


class PipelineProvenance(Contract):
    """Caller-declared identities propagated to every generated record."""

    job_id: str = Field(min_length=1)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_revision: str | None = None


@dataclass(frozen=True, slots=True)
class LocalRegistrationConfig:
    """Immutable settings for the only local route currently supplied.

    ``covariance_calibration`` is optional independent calibration evidence
    for the numerical covariance estimator.  It does not qualify geometry or
    the route; it merely permits the limited source-frame adjustment to be run
    when its covariance preconditions are met.
    """

    origin: PipelineOrigin = PipelineOrigin.LOCAL_NON_QUALIFIED
    prior: MatchPrior = field(default_factory=MatchPrior)
    match_parameters: MatchParameters = field(
        default_factory=lambda: MatchParameters(
            values={"grid_spacing_px": 32, "template_half_size_px": 5, "search_radius_px": 16}
        )
    )
    verification: VerificationParameters = field(default_factory=VerificationParameters)
    grid_shape: tuple[int, int] = (8, 8)
    quality_floor: float = 0.0
    patch_half_size_px: int = 4
    ecc_max_iterations: int = 30
    ecc_convergence_threshold: float = 1e-4
    fourier_upsample_factor: int = 8
    min_patch_texture: float = 1e-8
    noise_variance: float | None = None
    covariance_calibration: CalibrationResult | None = None

    def __post_init__(self) -> None:
        rows, cols = self.grid_shape
        if rows < 1 or cols < 1:
            raise ValueError("grid_shape must contain positive row and column counts")
        if not math.isfinite(self.quality_floor):
            raise ValueError("quality_floor must be finite")
        if self.patch_half_size_px < 1:
            raise ValueError("patch_half_size_px must be at least one")
        if self.ecc_max_iterations < 1 or self.fourier_upsample_factor < 1:
            raise ValueError("refinement iteration and upsample settings must be positive")
        if (
            not math.isfinite(self.ecc_convergence_threshold)
            or self.ecc_convergence_threshold <= 0.0
        ):
            raise ValueError("ecc_convergence_threshold must be finite and positive")
        if not math.isfinite(self.min_patch_texture) or self.min_patch_texture < 0.0:
            raise ValueError("min_patch_texture must be finite and non-negative")
        if self.noise_variance is not None and (
            not math.isfinite(self.noise_variance) or self.noise_variance <= 0.0
        ):
            raise ValueError("noise_variance must be finite and positive when supplied")


class ArrayArtifactHandles(Contract):
    """Serializable handles for arrays retained by the caller/output layer."""

    source: dict[str, object]
    reference: dict[str, object]
    source_mask: dict[str, object]
    reference_mask: dict[str, object]


class CoverageEvidence(Contract):
    grid_shape: tuple[int, int]
    eligible_cell_count: int
    eligible_cell_occupancy: float
    convex_hull_to_eligible_area_ratio: float | None
    largest_empty_run: int
    per_cell_candidate_counts: tuple[tuple[int, ...], ...]
    limitations: tuple[str, ...] = ()


class RefinementEvidence(Contract):
    attempted_count: int
    refined_count: int
    covariance_count: int
    calibrated_covariance_count: int
    failed_count: int
    limitations: tuple[str, ...] = ()


class AdjustmentEvidence(Contract):
    status: str
    result: dict[str, object] | None = None
    reason: str | None = None


class PipelineStageEvidence(Contract):
    name: str
    outcome: str
    parameter_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameter_contents: dict[str, object]
    diagnostics: dict[str, object] = Field(default_factory=dict)
    failure: StageFailure | None = None
    limitations: tuple[str, ...] = ()


class PipelineResult(Contract):
    """Typed, JSON-serializable output of :func:`run_local_registration`."""

    disposition: PipelineDisposition
    origin: PipelineOrigin
    route_qualified: bool = False
    provenance: PipelineProvenance
    parameters: ResolvedPipelineParameters
    artifacts: ArrayArtifactHandles
    stages: tuple[PipelineStageEvidence, ...]
    candidates: tuple[CorrespondenceRecord, ...]
    correspondences: tuple[CorrespondenceRecord, ...]
    verified_inlier_count: int
    coverage: CoverageEvidence | None
    refinement: RefinementEvidence | None
    adjustment: AdjustmentEvidence
    scene_verdict: SceneVerdict
    evidence_limitations: tuple[str, ...]
    failures: tuple[StageFailure, ...] = ()


class ResolvedPipelineParameters(Contract):
    """Stable contents and identity of every local-route behavior setting."""

    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    contents: dict[str, object]


_ROUTE_LIMITATIONS = (
    "This in-memory route has no independently validated mission geometry, reference control, "
    "or route qualification.",
    "Mission-specific geometry adapters and real data acquisition remain out of scope and "
    "require independent external evidence.",
    "Local/synthetic execution is diagnostic only and cannot issue an accepted scientific verdict.",
    "The local verdict uses a fixed timestamp sentinel for deterministic serialization; it is not "
    "an execution-time claim.",
)

_LOCAL_VERDICT_TIME = datetime(1970, 1, 1, tzinfo=UTC)
"""Serialization sentinel; wall-clock execution time is not scientific evidence."""


def _resolved_parameters(config: LocalRegistrationConfig) -> ResolvedPipelineParameters:
    """Resolve every behavior-changing knob into canonical JSON-hashable evidence."""
    jacobian = config.prior.local_warp_jacobian
    calibration = config.covariance_calibration
    contents: dict[str, object] = {
        "route": {
            "matcher": "normalized_cross_correlation",
            "matcher_version": "1.0",
            "run_reverse": False,
            "origin": config.origin,
        },
        "matching": {
            "parameters": dict(config.match_parameters.values),
            "parameter_set_digest": config.match_parameters.parameter_set_digest,
            "prior": {
                "displacement_px": config.prior.displacement_px,
                "displacement_uncertainty_px": config.prior.displacement_uncertainty_px,
                "search_radius_px": config.prior.search_radius_px,
                "anchor_source_pixel": (
                    config.prior.anchor_source_pixel.line,
                    config.prior.anchor_source_pixel.sample,
                ),
                "local_warp_jacobian": None
                if jacobian is None
                else {
                    "d_ref_line_d_src_line": jacobian.d_ref_line_d_src_line,
                    "d_ref_line_d_src_sample": jacobian.d_ref_line_d_src_sample,
                    "d_ref_sample_d_src_line": jacobian.d_ref_sample_d_src_line,
                    "d_ref_sample_d_src_sample": jacobian.d_ref_sample_d_src_sample,
                },
            },
        },
        "verification": {
            "fit_residual_threshold_px": config.verification.fit_residual_threshold_px,
            "fit_min_inliers": config.verification.fit_min_inliers,
            "fit_max_iterations": config.verification.fit_max_iterations,
            "forward_backward_max_error_px": config.verification.forward_backward_max_error_px,
            "forward_backward_anchor_tolerance_px": (
                config.verification.forward_backward_anchor_tolerance_px
            ),
        },
        "coverage": {
            "grid_shape": config.grid_shape,
            "quality_floor": config.quality_floor,
            "eligibility_strategy": (
                "source_grid_cell_requires_usable_source_and_normalized_reference_cell"
            ),
        },
        "refinement": {
            "patch_half_size_px": config.patch_half_size_px,
            "ecc_max_iterations": config.ecc_max_iterations,
            "ecc_convergence_threshold": config.ecc_convergence_threshold,
            "fourier_upsample_factor": config.fourier_upsample_factor,
            "min_patch_texture": config.min_patch_texture,
            "noise_variance": config.noise_variance,
            "covariance_calibration": None
            if calibration is None
            else {
                "scale_factor": calibration.scale_factor,
                "n_trials": calibration.n_trials,
                "empirical_coverage_at_1sigma": calibration.empirical_coverage_at_1sigma,
                "calibrated_coverage_at_1sigma": calibration.calibrated_coverage_at_1sigma,
            },
        },
        "adjustment": {
            "parameterization": ("line_translation_px", "sample_translation_px"),
            "observation": "reference_minus_source_pixel_displacement_yx",
            "requires_calibrated_covariance": True,
        },
    }
    return ResolvedPipelineParameters(digest=digest_json(contents), contents=contents)


def _stage(
    name: str,
    outcome: str,
    parameters: ResolvedPipelineParameters,
    sections: str | tuple[str, ...],
    **kwargs: object,
) -> PipelineStageEvidence:
    section_names = (sections,) if isinstance(sections, str) else sections
    contents = {section: parameters.contents[section] for section in section_names}
    return PipelineStageEvidence(
        name=name,
        outcome=outcome,
        parameter_digest=digest_json(contents),
        parameter_contents=contents,
        **kwargs,
    )


def _artifact_handles(
    source: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    source_mask: npt.NDArray[np.bool_],
    reference_mask: npt.NDArray[np.bool_],
    provenance: PipelineProvenance,
) -> ArrayArtifactHandles:
    def handle(array: np.ndarray, digest: str | None = None) -> dict[str, object]:
        return {
            "shape": tuple(int(value) for value in array.shape),
            "dtype": str(array.dtype),
            "digest": digest,
        }

    return ArrayArtifactHandles(
        source=handle(source, provenance.input_digest),
        reference=handle(reference, provenance.reference_digest),
        source_mask=handle(source_mask),
        reference_mask=handle(reference_mask),
    )


def _rejected(
    *,
    provenance: PipelineProvenance,
    origin: PipelineOrigin,
    parameters: ResolvedPipelineParameters,
    source: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    source_mask: npt.NDArray[np.bool_],
    reference_mask: npt.NDArray[np.bool_],
    code: FailureCode,
    message: str,
    candidates: tuple[CorrespondenceRecord, ...] = (),
    stages: tuple[PipelineStageEvidence, ...] = (),
) -> PipelineResult:
    failure = StageFailure(code=code, message=message)
    verdict = compute_scene_verdict(
        (),
        route_qualified=False,
        route_id="local-in-memory-unqualified",
        clock=lambda: _LOCAL_VERDICT_TIME,
    )
    return PipelineResult(
        disposition=PipelineDisposition.REJECTED,
        origin=origin,
        provenance=provenance,
        parameters=parameters,
        artifacts=_artifact_handles(source, reference, source_mask, reference_mask, provenance),
        stages=(
            *stages,
            _stage(
                "pipeline",
                "rejected",
                parameters,
                "route",
                failure=failure,
            ),
        ),
        candidates=candidates,
        correspondences=candidates,
        verified_inlier_count=sum(record.is_inlier for record in candidates),
        coverage=None,
        refinement=None,
        adjustment=AdjustmentEvidence(
            status="not_attempted", reason="pipeline rejected before adjustment"
        ),
        scene_verdict=verdict,
        evidence_limitations=_ROUTE_LIMITATIONS,
        failures=(failure,),
    )


def _validate_inputs(
    source: object,
    reference: object,
    source_mask: object | None,
    reference_mask: object | None,
) -> tuple[
    npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.bool_], npt.NDArray[np.bool_]
]:
    source_array = np.asarray(source, dtype=np.float64)
    reference_array = np.asarray(reference, dtype=np.float64)
    if (
        source_array.ndim != 2
        or reference_array.ndim != 2
        or source_array.size == 0
        or reference_array.size == 0
    ):
        raise ValueError("source and reference must be non-empty 2-D arrays")
    source_valid = (
        np.ones(source_array.shape, dtype=np.bool_)
        if source_mask is None
        else np.asarray(source_mask, dtype=np.bool_)
    )
    reference_valid = (
        np.ones(reference_array.shape, dtype=np.bool_)
        if reference_mask is None
        else np.asarray(reference_mask, dtype=np.bool_)
    )
    if source_valid.shape != source_array.shape or reference_valid.shape != reference_array.shape:
        raise ValueError("mask shape must match its image shape")
    if not bool(np.any(source_valid)) or not bool(np.any(reference_valid)):
        raise RuntimeError("all regions are masked")
    if not bool(np.all(np.isfinite(source_array[source_valid]))) or not bool(
        np.all(np.isfinite(reference_array[reference_valid]))
    ):
        raise ValueError("non-finite usable pixels are not permitted")
    # Existing matchers require all finite values; discarded pixels are made inert after
    # checking that no usable sample is altered.
    return (
        np.where(source_valid, source_array, 0.0),
        np.where(reference_valid, reference_array, 0.0),
        source_valid,
        reference_valid,
    )


def _fallback_array(value: object) -> npt.NDArray[np.float64]:
    """Best-effort array only for a structured invalid-input result handle."""
    try:
        return np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return np.empty((0, 0), dtype=np.float64)


def _local_eligibility(
    source_mask: npt.NDArray[np.bool_],
    reference_mask: npt.NDArray[np.bool_],
    grid_shape: tuple[int, int],
) -> EligibilityGrid:
    eligible = np.ones(grid_shape, dtype=np.bool_)
    reasons: dict[tuple[int, int], str] = {}
    source_height, source_width = source_mask.shape
    reference_height, reference_width = reference_mask.shape
    for row in range(grid_shape[0]):
        for col in range(grid_shape[1]):
            source_row_slice = slice(
                row * source_height // grid_shape[0],
                (row + 1) * source_height // grid_shape[0],
            )
            source_col_slice = slice(
                col * source_width // grid_shape[1],
                (col + 1) * source_width // grid_shape[1],
            )
            # Coverage is defined in source pixel space.  With unequal image
            # dimensions there is no validated source-to-reference warp, so
            # the only safe local policy is normalized grid-cell co-occupancy:
            # each source cell and its same-index reference cell must contain
            # usable samples.  It is diagnostic mask evidence, never physical
            # overlap evidence, and avoids elementwise cross-image masking.
            reference_row_slice = slice(
                row * reference_height // grid_shape[0],
                (row + 1) * reference_height // grid_shape[0],
            )
            reference_col_slice = slice(
                col * reference_width // grid_shape[1],
                (col + 1) * reference_width // grid_shape[1],
            )
            source_usable = bool(np.any(source_mask[source_row_slice, source_col_slice]))
            reference_usable = bool(
                np.any(reference_mask[reference_row_slice, reference_col_slice])
            )
            if not source_usable or not reference_usable:
                eligible[row, col] = False
                reasons[(row, col)] = (
                    "source or normalized reference grid cell has no usable local pixels"
                )
    return EligibilityGrid(grid_shape=grid_shape, eligible=eligible, exclusion_reason=reasons)


def _coverage_evidence(
    records: tuple[CorrespondenceRecord, ...], eligibility: EligibilityGrid, shape: tuple[int, int]
) -> CoverageEvidence:
    metrics = compute_coverage_metrics(records, eligibility=eligibility, image_shape=shape)
    return CoverageEvidence(
        grid_shape=eligibility.grid_shape,
        eligible_cell_count=int(np.count_nonzero(eligibility.eligible)),
        eligible_cell_occupancy=metrics.eligible_cell_occupancy,
        convex_hull_to_eligible_area_ratio=metrics.convex_hull_to_eligible_area_ratio,
        largest_empty_run=metrics.largest_empty_run,
        per_cell_candidate_counts=tuple(
            tuple(int(value) for value in row) for row in metrics.per_cell_candidate_counts
        ),
        limitations=(
            "Eligibility is based only on supplied local validity masks, not validated physical "
            "overlap, terrain, or illumination.",
        ),
    )


def _refine(
    records: tuple[CorrespondenceRecord, ...],
    source: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    source_mask: npt.NDArray[np.bool_],
    reference_mask: npt.NDArray[np.bool_],
    config: LocalRegistrationConfig,
) -> tuple[tuple[CorrespondenceRecord, ...], RefinementEvidence]:
    refined: list[CorrespondenceRecord] = []
    attempted = 0
    for record in records:
        if not record.selected_for_coverage:
            refined.append(record)
            continue
        attempted += 1
        refined.append(
            refine_correspondence(
                record,
                source,
                reference,
                source_mask=source_mask,
                reference_mask=reference_mask,
                patch_half_size=config.patch_half_size_px,
                ecc_max_iterations=config.ecc_max_iterations,
                ecc_convergence_threshold=config.ecc_convergence_threshold,
                fourier_upsample_factor=config.fourier_upsample_factor,
                min_patch_texture=config.min_patch_texture,
                noise_variance=config.noise_variance,
                calibration=config.covariance_calibration,
            )
        )
    output = tuple(refined)
    successful = tuple(
        record
        for record in output
        if record.selected_for_coverage and record.refined_location is not None
    )
    return output, RefinementEvidence(
        attempted_count=attempted,
        refined_count=len(successful),
        covariance_count=sum(record.covariance is not None for record in successful),
        calibrated_covariance_count=sum(record.covariance_calibrated for record in successful),
        failed_count=attempted - len(successful),
        limitations=(
            "Refinement covariance is numerical local evidence; it does not calibrate a mission "
            "route or geometry.",
        ),
    )


def _adjust(
    records: tuple[CorrespondenceRecord, ...],
) -> tuple[tuple[CorrespondenceRecord, ...], AdjustmentEvidence]:
    selected = tuple(
        record
        for record in records
        if record.selected_for_coverage and record.refined_location is not None
    )
    ready = tuple(
        record
        for record in selected
        if record.covariance is not None and record.covariance_calibrated
    )
    if not ready:
        return records, AdjustmentEvidence(
            status="not_ready",
            reason=(
                "limited adjustment requires selected refined records with calibrated covariance"
            ),
        )
    fitting = tuple(
        record.model_copy(update={"point_role": PointRole.FITTING_INLIER}) for record in ready
    )
    observations = tuple(
        ObservationLinearization(
            observation_id=record.match_id,
            source_residual_yx_px=(
                record.refined_location.line - record.source_pixel.line,
                record.refined_location.sample - record.source_pixel.sample,
            ),
            design_matrix_yx_by_parameter=np.eye(2, dtype=np.float64),
        )
        for record in fitting
    )
    try:
        result: AdjustmentResult = fit_adjustment(
            fitting, observations, translation_only_parameterization()
        )
    except AdjustmentInputError as error:
        return records, AdjustmentEvidence(status="not_ready", reason=str(error))
    by_id = {record.match_id: record for record in fitting}
    updated = tuple(by_id.get(record.match_id, record) for record in records)
    return updated, AdjustmentEvidence(
        status="accepted" if result.accepted else "rejected",
        result={
            "accepted": result.accepted,
            "converged": result.converged,
            "rejection_reason": result.rejection_reason,
            "parameter_values": result.parameter_values,
            "limitations": result.limitations,
        },
        reason=result.rejection_reason,
    )


def run_local_registration(
    source: object,
    reference: object,
    *,
    provenance: PipelineProvenance,
    config: LocalRegistrationConfig | None = None,
    source_mask: object | None = None,
    reference_mask: object | None = None,
) -> PipelineResult:
    """Run deterministic local registration and return a non-qualified result.

    No argument can mark this route qualified.  Supply real geometry/reference
    evidence to a future validated route rather than relabelling this result.
    """
    active_config = config or LocalRegistrationConfig()
    parameters = _resolved_parameters(active_config)
    raw_source = _fallback_array(source)
    raw_reference = _fallback_array(reference)
    fallback_source_mask = np.ones(
        raw_source.shape if raw_source.ndim == 2 else (0, 0), dtype=np.bool_
    )
    fallback_reference_mask = np.ones(
        raw_reference.shape if raw_reference.ndim == 2 else (0, 0), dtype=np.bool_
    )
    try:
        source_array, reference_array, source_valid, reference_valid = _validate_inputs(
            source, reference, source_mask, reference_mask
        )
    except RuntimeError as error:
        return _rejected(
            provenance=provenance,
            origin=active_config.origin,
            parameters=parameters,
            source=raw_source,
            reference=raw_reference,
            source_mask=fallback_source_mask,
            reference_mask=fallback_reference_mask,
            code=FailureCode.MATCHING_ALL_REGIONS_MASKED,
            message=str(error),
        )
    except (TypeError, ValueError) as error:
        return _rejected(
            provenance=provenance,
            origin=active_config.origin,
            parameters=parameters,
            source=raw_source,
            reference=raw_reference,
            source_mask=fallback_source_mask,
            reference_mask=fallback_reference_mask,
            code=FailureCode.INPUT_UNSUPPORTED_PAYLOAD,
            message=str(error),
        )

    try:
        # Regular NCC grids are source-anchored.  A reverse grid will not in
        # general contain every forward reference location when the shift is
        # not an exact grid multiple, so claiming reciprocal absence there
        # would be an artefact of sampling, not evidence against a match.
        # The runner therefore records forward/backward evidence as
        # unavailable for this deterministic local route and still performs
        # its robust geometric verification.
        report = run_classical_match(
            NccMatcher(),
            source_array,
            reference_array,
            source_mask=source_valid,
            reference_mask=reference_valid,
            prior=active_config.prior,
            parameters=active_config.match_parameters,
            verification=active_config.verification,
            job_id=provenance.job_id,
            input_digest=provenance.input_digest,
            reference_digest=provenance.reference_digest,
            run_reverse=False,
        )
    except ValueError as error:
        return _rejected(
            provenance=provenance,
            origin=active_config.origin,
            parameters=parameters,
            source=source_array,
            reference=reference_array,
            source_mask=source_valid,
            reference_mask=reference_valid,
            code=FailureCode.VALIDATION_UNKNOWN_PARAMETER,
            message=str(error),
        )

    # Matchers intentionally use UUID defaults because they can be called by
    # concurrent/tiled orchestrators.  This single ordered local route has a
    # stronger reproducibility contract, so give its result records stable
    # identities before coverage's documented score/id tie-break is used.
    verified = tuple(
        record.model_copy(
            update={
                "match_id": "local-"
                + digest_json(
                    {
                        "job_id": provenance.job_id,
                        "input_digest": provenance.input_digest,
                        "reference_digest": provenance.reference_digest,
                        "parameter_set_digest": record.parameter_set_digest,
                        "index": index,
                        "source": (record.source_pixel.line, record.source_pixel.sample),
                        "reference": (record.reference_pixel.line, record.reference_pixel.sample),
                    }
                )[:24],
                "code_revision": provenance.code_revision,
            }
        )
        for index, record in enumerate(report.verified_candidates)
    )
    matching_stage = _stage(
        "classical_matching",
        "succeeded",
        parameters,
        ("route", "matching", "verification"),
        diagnostics={
            "algorithm": report.algorithm,
            "raw_candidate_count": report.candidate_count,
            "verified_inlier_count": report.inlier_count,
            "rejected_count": report.rejected_count,
            "evidence_status": report.evidence_status,
        },
    )
    if report.inlier_count == 0:
        return _rejected(
            provenance=provenance,
            origin=active_config.origin,
            parameters=parameters,
            source=source_array,
            reference=reference_array,
            source_mask=source_valid,
            reference_mask=reference_valid,
            code=FailureCode.MATCHING_INSUFFICIENT_CANDIDATES,
            message="classical route produced no verified inlier correspondences",
            candidates=verified,
            stages=(matching_stage,),
        )

    eligibility = _local_eligibility(source_valid, reference_valid, active_config.grid_shape)
    selected = select_grid_coverage(
        verified,
        eligibility=eligibility,
        image_shape=source_array.shape,
        quality_floor=active_config.quality_floor,
    )
    coverage = _coverage_evidence(selected, eligibility, source_array.shape)
    coverage_stage = _stage(
        "coverage_selection",
        "succeeded",
        parameters,
        "coverage",
        diagnostics={
            "eligible_cell_count": coverage.eligible_cell_count,
            "selected_count": sum(record.selected_for_coverage for record in selected),
        },
        limitations=coverage.limitations,
    )
    if not any(record.selected_for_coverage for record in selected):
        return _rejected(
            provenance=provenance,
            origin=active_config.origin,
            parameters=parameters,
            source=source_array,
            reference=reference_array,
            source_mask=source_valid,
            reference_mask=reference_valid,
            code=FailureCode.COVERAGE_INSUFFICIENT_OCCUPANCY,
            message="no verified correspondence passed local coverage selection",
            candidates=selected,
            stages=(matching_stage, coverage_stage),
        )
    refined, refinement = _refine(
        selected, source_array, reference_array, source_valid, reference_valid, active_config
    )
    refinement_stage = _stage(
        "patch_refinement",
        "succeeded" if refinement.refined_count else "review",
        parameters,
        "refinement",
        diagnostics=refinement.model_dump(mode="json"),
        limitations=refinement.limitations,
    )
    adjusted, adjustment = _adjust(refined)
    adjustment_stage = _stage(
        "limited_adjustment",
        adjustment.status,
        parameters,
        "adjustment",
        diagnostics=adjustment.model_dump(mode="json"),
        limitations=(
            "No physical sensor-model correction is exported by this limited adjustment.",
        ),
    )
    verdict = compute_scene_verdict(
        (),
        route_qualified=False,
        route_id="local-in-memory-unqualified",
        clock=lambda: _LOCAL_VERDICT_TIME,
    )
    return PipelineResult(
        disposition=PipelineDisposition.REVIEW,
        origin=active_config.origin,
        provenance=provenance,
        parameters=parameters,
        artifacts=_artifact_handles(
            source_array, reference_array, source_valid, reference_valid, provenance
        ),
        stages=(matching_stage, coverage_stage, refinement_stage, adjustment_stage),
        candidates=verified,
        correspondences=adjusted,
        verified_inlier_count=sum(record.is_inlier for record in adjusted),
        coverage=coverage,
        refinement=refinement,
        adjustment=adjustment,
        scene_verdict=verdict,
        evidence_limitations=_ROUTE_LIMITATIONS,
    )
