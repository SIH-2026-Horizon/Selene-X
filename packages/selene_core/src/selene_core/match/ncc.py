"""Mask- and prior-aware local normalized cross-correlation (WP-04 task 3).

This is an intentionally direct NumPy baseline.  It searches integer-pixel
reference patch centres for templates sampled on a regular source grid; it
does not claim or perform sub-pixel refinement (WP-08).  With no displacement
prior, equal source/reference coordinates are the expected location.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.protocol import MatchParameters, MatchPrior
from selene_core.types import ReferencePixel, SourcePixel

__all__ = ["NccMatcher"]

_ALGORITHM = "normalized_cross_correlation"
_ALGORITHM_VERSION = "1.0"
_MIN_VALID_FRACTION = 0.5


@dataclass(frozen=True, slots=True)
class _NccConfiguration:
    grid_spacing_px: int
    template_half_size_px: int
    search_radius_px: int


@dataclass(frozen=True, slots=True)
class _ScoredLocation:
    line: int
    sample: int
    score: float


def _positive_int(parameters: MatchParameters, name: str) -> int:
    value = parameters.values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"NCC parameter {name!r} must be a positive integer, got {value!r}")
    return value


def _configuration(parameters: MatchParameters) -> _NccConfiguration:
    return _NccConfiguration(
        grid_spacing_px=_positive_int(parameters, "grid_spacing_px"),
        template_half_size_px=_positive_int(parameters, "template_half_size_px"),
        search_radius_px=_positive_int(parameters, "search_radius_px"),
    )


def _validate_inputs(
    source: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    source_mask: npt.NDArray[np.bool_] | None,
    reference_mask: npt.NDArray[np.bool_] | None,
) -> None:
    for name, image in (("source", source), ("reference", reference)):
        if image.ndim != 2:
            raise ValueError(f"{name} must be a 2D array, got shape {image.shape!r}")
        if image.size == 0:
            raise ValueError(f"{name} must not be empty")
        if not np.all(np.isfinite(image)):
            raise ValueError(f"{name} must contain only finite values")
    for name, mask, image in (
        ("source_mask", source_mask, source),
        ("reference_mask", reference_mask, reference),
    ):
        if mask is not None and mask.shape != image.shape:
            raise ValueError(
                f"{name} shape {mask.shape!r} does not match image shape {image.shape!r}"
            )


def _patch(
    image: npt.NDArray[np.float64], line: int, sample: int, radius: int
) -> npt.NDArray[np.float64] | None:
    if (
        line - radius < 0
        or sample - radius < 0
        or line + radius >= image.shape[0]
        or sample + radius >= image.shape[1]
    ):
        return None
    return image[line - radius : line + radius + 1, sample - radius : sample + radius + 1]


def _mask_patch(
    mask: npt.NDArray[np.bool_] | None, line: int, sample: int, radius: int
) -> npt.NDArray[np.bool_]:
    width = 2 * radius + 1
    if mask is None:
        return np.ones((width, width), dtype=np.bool_)
    return mask[line - radius : line + radius + 1, sample - radius : sample + radius + 1]


def _ncc_score(
    source_patch: npt.NDArray[np.float64],
    reference_patch: npt.NDArray[np.float64],
    valid: npt.NDArray[np.bool_],
) -> float | None:
    if float(np.mean(valid)) <= _MIN_VALID_FRACTION:
        return None
    source_values = source_patch[valid]
    reference_values = reference_patch[valid]
    source_zero_mean = source_values - float(np.mean(source_values))
    reference_zero_mean = reference_values - float(np.mean(reference_values))
    denominator = float(np.linalg.norm(source_zero_mean) * np.linalg.norm(reference_zero_mean))
    if denominator <= np.finfo(np.float64).eps:
        return None
    return float(np.dot(source_zero_mean, reference_zero_mean) / denominator)


def _uniqueness_ratio(best: _ScoredLocation, scores: list[_ScoredLocation]) -> float:
    # Adjacent pixels are part of the same broad correlation peak, not a
    # competing match. Suppress that 3x3 neighbourhood before finding the
    # next-best local peak. A lone peak has unknown uniqueness and scores 0.
    competitors = [
        item
        for item in scores
        if max(abs(item.line - best.line), abs(item.sample - best.sample)) > 1
    ]
    if not competitors or best.score <= 0.0:
        return 0.0
    second_score = max(item.score for item in competitors)
    ratio = (best.score - second_score) / max(abs(best.score), np.finfo(np.float64).eps)
    return float(np.clip(ratio, 0.0, 1.0))


def _peak_sharpness(best: _ScoredLocation, scores: list[_ScoredLocation]) -> float:
    """Peak separation from its immediate correlation neighbourhood, [0, 1]."""
    neighbours = [
        item.score
        for item in scores
        if item is not best and max(abs(item.line - best.line), abs(item.sample - best.sample)) <= 1
    ]
    if not neighbours or best.score <= 0.0:
        return 0.0
    shoulder = float(np.mean(neighbours))
    return float(np.clip((best.score - shoulder) / best.score, 0.0, 1.0))


class NccMatcher:
    """Match regular-grid templates by direct, mask-aware local NCC."""

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
        """Return one coarse record for every evaluable source-grid point."""
        _validate_inputs(source, reference, source_mask, reference_mask)
        config = _configuration(parameters)
        template_width = 2 * config.template_half_size_px + 1
        template_area = template_width * template_width

        search_radius = float(config.search_radius_px)
        if prior.displacement_px is not None and prior.search_radius_px is not None:
            search_radius = min(search_radius, prior.search_radius_px)

        records: list[CorrespondenceRecord] = []
        for source_line in range(0, source.shape[0], config.grid_spacing_px):
            for source_sample in range(0, source.shape[1], config.grid_spacing_px):
                source_patch = _patch(
                    source,
                    source_line,
                    source_sample,
                    config.template_half_size_px,
                )
                if source_patch is None:
                    continue
                source_valid = _mask_patch(
                    source_mask,
                    source_line,
                    source_sample,
                    config.template_half_size_px,
                )
                if int(np.count_nonzero(source_valid)) <= template_area * _MIN_VALID_FRACTION:
                    continue

                source_pixel = SourcePixel(line=float(source_line), sample=float(source_sample))
                prior_dy, prior_dx = prior.displacement_at(source_pixel)
                expected_line = source_line + prior_dy
                expected_sample = source_sample + prior_dx
                line_min = int(np.ceil(expected_line - search_radius))
                line_max = int(np.floor(expected_line + search_radius))
                sample_min = int(np.ceil(expected_sample - search_radius))
                sample_max = int(np.floor(expected_sample + search_radius))
                scores: list[_ScoredLocation] = []
                for reference_line in range(line_min, line_max + 1):
                    for reference_sample in range(sample_min, sample_max + 1):
                        if (reference_line - expected_line) ** 2 + (
                            reference_sample - expected_sample
                        ) ** 2 > search_radius**2:
                            continue
                        reference_patch = _patch(
                            reference,
                            reference_line,
                            reference_sample,
                            config.template_half_size_px,
                        )
                        if reference_patch is None:
                            continue
                        reference_valid = _mask_patch(
                            reference_mask,
                            reference_line,
                            reference_sample,
                            config.template_half_size_px,
                        )
                        score = _ncc_score(
                            source_patch,
                            reference_patch,
                            source_valid & reference_valid,
                        )
                        if score is not None:
                            scores.append(
                                _ScoredLocation(
                                    line=reference_line,
                                    sample=reference_sample,
                                    score=score,
                                )
                            )
                if not scores:
                    # A usable source template that found no usable reference
                    # support is evidence of a failed attempt, not something
                    # silently erased from an auditable candidate catalogue.
                    expected_reference = ReferencePixel(
                        line=float(expected_line), sample=float(expected_sample)
                    )
                    records.append(
                        CorrespondenceRecord(
                            job_id=job_id,
                            algorithm=_ALGORITHM,
                            algorithm_version=_ALGORITHM_VERSION,
                            selection_reason="regular-grid NCC search had no valid reference peak",
                            source_pixel=source_pixel,
                            reference_pixel=expected_reference,
                            raw_score=-1.0,
                            prior_displacement_px=prior.displacement_px,
                            local_warp_jacobian=prior.local_warp_jacobian,
                            is_candidate=False,
                            point_role=PointRole.REJECTED,
                            rejection_reason="no valid NCC score in the bounded search region",
                            input_digest=input_digest,
                            reference_digest=reference_digest,
                            parameter_set_digest=parameters.parameter_set_digest,
                        )
                    )
                    continue

                best = max(scores, key=lambda item: item.score)
                displacement = (
                    float(best.line - source_line),
                    float(best.sample - source_sample),
                )
                residual = prior.residual_at(source_pixel, displacement)
                records.append(
                    CorrespondenceRecord(
                        job_id=job_id,
                        algorithm=_ALGORITHM,
                        algorithm_version=_ALGORITHM_VERSION,
                        selection_reason="regular-grid local NCC peak",
                        source_pixel=source_pixel,
                        reference_pixel=ReferencePixel(
                            line=float(best.line), sample=float(best.sample)
                        ),
                        raw_score=best.score,
                        # The schema has no dedicated peak-sharpness field.
                        # This uncalibrated structural quality score captures
                        # both distant ambiguity and local peak shoulders,
                        # without falsely claiming calibrated confidence.
                        descriptor_channel_agreement=min(
                            _uniqueness_ratio(best, scores), _peak_sharpness(best, scores)
                        ),
                        prior_displacement_px=prior.displacement_px,
                        residual_from_prior_px=residual,
                        local_warp_jacobian=prior.local_warp_jacobian,
                        is_candidate=True,
                        point_role=PointRole.CANDIDATE,
                        input_digest=input_digest,
                        reference_digest=reference_digest,
                        parameter_set_digest=parameters.parameter_set_digest,
                    )
                )
        return tuple(records)
