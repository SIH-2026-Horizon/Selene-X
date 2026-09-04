"""Conservative, mask-safe source darkness and shadow-candidate estimation.

This module identifies a statistically separated dark tail in one source
image.  A ``shadow_mask`` entry therefore means *confident dark/shadow
candidate*, not that physical shadow has been proven.  Pixels in the broader
``penumbra_mask`` are explicitly ambiguous and are never included in the
confident mask.  The estimator is an auxiliary feature only; it does not
modify image matching or sensor geometry.

All masks have positive polarity: ``True`` means the stated property holds.
Input cells outside ``usable_mask`` are excluded from every statistic and are
false in every result mask.  No local interpolation is performed, so invalid
gaps cannot influence or be bridged by the result.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np
import numpy.typing as npt

from selene_core.features.local_radiometry import FeatureChannel

__all__ = [
    "ShadowEstimate",
    "ShadowEstimationParameters",
    "estimate_source_shadows",
]

_ALGORITHM_VERSION = "1.0"
_INVALID_FILL_VALUE = 0.0
_CONFIDENCE_RANGE = (0.0, 1.0)
_SCALE_FLOOR = float.fromhex("0x1.0p-1022")
_LOWER_TAIL_SELECTION_SEMANTICS = (
    "include_global_minimum_plateau_when_quantile_equals_minimum;"
    "otherwise_strictly_below_quantile_to_avoid_boundary_tie_expansion"
)


def _freeze_provenance(value: object) -> object:
    """Defensively copy JSON-like provenance into immutable containers."""
    if isinstance(value, np.ndarray):
        raise ValueError("ShadowEstimate provenance does not support NumPy arrays")
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError("ShadowEstimate provenance keys must be strings")
            frozen[key] = _freeze_provenance(nested_value)
        return MappingProxyType(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_provenance(item) for item in value)
    if value is None or isinstance(value, (str, bytes, bool, int, float, np.generic)):
        return value
    raise ValueError(f"ShadowEstimate provenance has unsupported value {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class ShadowEstimationParameters:
    """Validated, conservative dark-tail thresholds.

    ``dark_percentile`` limits confident candidates to the darkest global
    tail. ``shadow_mad_multiplier`` additionally requires that tail to be
    clearly separated from the usable scene median.  When the median absolute
    deviation is zero, ``min_tail_gap_fraction`` permits only a visibly
    discrete lower mode. ``penumbra_percentile`` bounds the independent
    ambiguous band; it must be larger than ``dark_percentile``.
    """

    dark_percentile: float = 5.0
    penumbra_percentile: float = 20.0
    shadow_mad_multiplier: float = 3.5
    min_tail_gap_fraction: float = 0.5
    min_valid_count: int = 32

    def __post_init__(self) -> None:
        for name, value in (
            ("dark_percentile", self.dark_percentile),
            ("penumbra_percentile", self.penumbra_percentile),
        ):
            if (
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or not 0.0 < float(value) < 50.0
            ):
                raise ValueError(f"{name} must be finite and in (0, 50)")
        if float(self.penumbra_percentile) <= float(self.dark_percentile):
            raise ValueError("penumbra_percentile must be larger than dark_percentile")
        if (
            type(self.shadow_mad_multiplier) not in (int, float)
            or not math.isfinite(float(self.shadow_mad_multiplier))
            or float(self.shadow_mad_multiplier) <= 0.0
        ):
            raise ValueError("shadow_mad_multiplier must be finite and positive")
        if (
            type(self.min_tail_gap_fraction) not in (int, float)
            or not math.isfinite(float(self.min_tail_gap_fraction))
            or not 0.0 < float(self.min_tail_gap_fraction) <= 1.0
        ):
            raise ValueError("min_tail_gap_fraction must be finite and in (0, 1]")
        if type(self.min_valid_count) is not int or self.min_valid_count < 1:
            raise ValueError("min_valid_count must be a positive integer")


@dataclass(frozen=True, slots=True)
class ShadowEstimate:
    """Immutable source-darkness estimate with explicit confidence semantics.

    ``usable_mask`` is the input usability mask after validation.  A true
    ``shadow_mask`` cell is a conservative, statistically separated dark
    candidate only. A true ``penumbra_mask`` cell is an ambiguous dark-band
    candidate and is guaranteed disjoint from ``shadow_mask``.  The bounded
    ``confidence`` channel uses zero for no dark evidence, values strictly
    between zero and one for penumbra ambiguity, and one for a confident dark
    candidate. Its valid mask exactly equals ``usable_mask``.
    """

    usable_mask: npt.NDArray[np.bool_]
    shadow_mask: npt.NDArray[np.bool_]
    penumbra_mask: npt.NDArray[np.bool_]
    confidence: FeatureChannel
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        masks = (self.usable_mask, self.shadow_mask, self.penumbra_mask)
        if any(not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ for mask in masks):
            raise ValueError("ShadowEstimate masks must be boolean NumPy arrays")
        if self.usable_mask.ndim != 2 or self.usable_mask.size == 0:
            raise ValueError("ShadowEstimate masks must be non-empty 2D arrays")
        if any(mask.shape != self.usable_mask.shape for mask in masks[1:]):
            raise ValueError("ShadowEstimate masks must share a shape")
        if self.confidence.values.shape != self.usable_mask.shape:
            raise ValueError("ShadowEstimate confidence shape must match masks")
        if self.confidence.value_range != _CONFIDENCE_RANGE:
            raise ValueError("ShadowEstimate confidence must use range [0, 1]")
        if not np.array_equal(self.confidence.valid_mask, self.usable_mask):
            raise ValueError("ShadowEstimate confidence valid_mask must equal usable_mask")
        if np.any(self.shadow_mask & self.penumbra_mask):
            raise ValueError("ShadowEstimate shadow_mask and penumbra_mask must be disjoint")
        if np.any((self.shadow_mask | self.penumbra_mask) & ~self.usable_mask):
            raise ValueError("ShadowEstimate candidates must be usable")
        confidence_values = self.confidence.values
        if np.any(confidence_values[self.shadow_mask] != 1.0):
            raise ValueError("ShadowEstimate shadow cells must have confidence 1")
        if np.any(
            (confidence_values[self.penumbra_mask] <= 0.0)
            | (confidence_values[self.penumbra_mask] >= 1.0)
        ):
            raise ValueError("ShadowEstimate penumbra cells must have confidence in (0, 1)")
        other_cells = ~(self.shadow_mask | self.penumbra_mask)
        if np.any(confidence_values[other_cells] != 0.0):
            raise ValueError("ShadowEstimate non-candidate cells must have confidence 0")

        copied_masks = []
        for mask in masks:
            copied = mask.copy()
            copied.setflags(write=False)
            copied_masks.append(copied)
        object.__setattr__(self, "usable_mask", copied_masks[0])
        object.__setattr__(self, "shadow_mask", copied_masks[1])
        object.__setattr__(self, "penumbra_mask", copied_masks[2])
        object.__setattr__(self, "provenance", _freeze_provenance(dict(self.provenance)))


def _validate_input(
    image: npt.NDArray[np.float64], usable_mask: npt.NDArray[np.bool_] | None
) -> npt.NDArray[np.bool_]:
    if not isinstance(image, np.ndarray) or image.dtype != np.float64:
        raise ValueError("image must be a float64 NumPy array")
    if image.ndim != 2 or image.size == 0:
        raise ValueError("image must be a non-empty 2D array")
    if not np.all(np.isfinite(image)):
        raise ValueError("image must contain only finite values")
    if usable_mask is None:
        return np.ones(image.shape, dtype=np.bool_)
    if not isinstance(usable_mask, np.ndarray) or usable_mask.dtype != np.bool_:
        raise ValueError("usable_mask must be a boolean NumPy array")
    if usable_mask.shape != image.shape:
        raise ValueError("usable_mask shape must match image shape")
    return usable_mask


def _normalisation_amplitude(values: npt.NDArray[np.float64]) -> float:
    """Return the finite positive scale derived exclusively from usable values."""
    return float(np.max(np.abs(values)))


def _scaled_values(values: npt.NDArray[np.float64], amplitude: float) -> npt.NDArray[np.float64]:
    """Scale values by a valid-only scale without changing relative tail tests."""
    if amplitude == 0.0:
        return values.copy()
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        return values / amplitude


def _lower_tail_selection(
    values: npt.NDArray[np.float64], quantile_threshold: float
) -> npt.NDArray[np.bool_]:
    """Select a conservative low tail without expanding a boundary tie plateau.

    A quantile equal to the global minimum represents an observed lowest mode,
    so that complete plateau is retained. Otherwise selection is strict: a
    large plateau at the quantile boundary is not silently promoted merely
    because interpolation placed the percentile inside it.
    """
    minimum = float(np.min(values))
    if quantile_threshold == minimum:
        return np.asarray(values == minimum, dtype=np.bool_)
    return np.asarray(values < quantile_threshold, dtype=np.bool_)


def _provenance(
    resolved: ShadowEstimationParameters,
    *,
    valid_count: int,
    usable_mask_supplied: bool,
    status: str,
    normalization_amplitude: float | None,
    thresholds: Mapping[str, float | None],
    decision_state: Mapping[str, bool | None],
    selection: Mapping[str, object],
) -> dict[str, object]:
    return {
        "algorithm": "conservative_source_darkness",
        "algorithm_version": _ALGORITHM_VERSION,
        "status": status,
        "valid_input_count": valid_count,
        "usable_mask_supplied": usable_mask_supplied,
        "normalization_amplitude": normalization_amplitude,
        "parameters": {
            "dark_percentile": float(resolved.dark_percentile),
            "penumbra_percentile": float(resolved.penumbra_percentile),
            "shadow_mad_multiplier": float(resolved.shadow_mad_multiplier),
            "min_tail_gap_fraction": float(resolved.min_tail_gap_fraction),
            "min_valid_count": resolved.min_valid_count,
        },
        "thresholds_normalized": dict(thresholds),
        "decision_state": dict(decision_state),
        "selection": dict(selection),
        "invalid_fill_value": _INVALID_FILL_VALUE,
        "semantics": "statistical_darkness_only_not_physical_shadow_proof",
    }


def estimate_source_shadows(
    image: npt.NDArray[np.float64],
    *,
    usable_mask: npt.NDArray[np.bool_] | None = None,
    parameters: ShadowEstimationParameters | None = None,
) -> ShadowEstimate:
    """Estimate conservative dark candidates and a separate ambiguous band.

    Statistics use only usable input samples. The dark percentile is accepted
    as confident only when it is a robustly separated lower tail, which avoids
    treating a broad, normally varying dark terrain distribution as certain
    shadow. The result remains invariant to positive affine radiometry except
    for unavoidable floating-point representation differences.
    """
    input_mask = _validate_input(image, usable_mask)
    resolved = parameters if parameters is not None else ShadowEstimationParameters()
    valid_values = image[input_mask]
    valid_count = int(valid_values.size)
    shadow_mask = np.zeros(image.shape, dtype=np.bool_)
    penumbra_mask = np.zeros(image.shape, dtype=np.bool_)
    confidence_values = np.full(image.shape, _INVALID_FILL_VALUE, dtype=np.float64)
    normalization_amplitude: float | None = None
    decision_state: dict[str, bool | None] = {
        "robust_tail": None,
        "discrete_tail": None,
    }
    selection: dict[str, object] = {
        "semantics": _LOWER_TAIL_SELECTION_SEMANTICS,
        "shadow_candidate_count": 0,
        "penumbra_candidate_count": 0,
    }

    if valid_count < resolved.min_valid_count:
        status = "no_confident_shadow:insufficient_valid_samples"
        thresholds: dict[str, float | None] = {
            "shadow": None,
            "penumbra": None,
            "median": None,
            "mad": None,
        }
    else:
        normalization_amplitude = _normalisation_amplitude(valid_values)
        scaled_values = _scaled_values(valid_values, normalization_amplitude)
        shadow_threshold = float(np.percentile(scaled_values, resolved.dark_percentile))
        penumbra_threshold = float(np.percentile(scaled_values, resolved.penumbra_percentile))
        median = float(np.median(scaled_values))
        mad = float(np.median(np.abs(scaled_values - median)))
        high_threshold = float(np.percentile(scaled_values, 95.0))
        shadow_selection = _lower_tail_selection(scaled_values, shadow_threshold)
        penumbra_selection = _lower_tail_selection(scaled_values, penumbra_threshold)
        selected_shadow_values = scaled_values[shadow_selection]
        shadow_selection_threshold = (
            float(np.max(selected_shadow_values)) if selected_shadow_values.size else None
        )
        remaining_values = scaled_values[~shadow_selection]
        next_after_shadow = float(np.min(remaining_values)) if remaining_values.size else None
        dark_mode_gap = (
            next_after_shadow - shadow_selection_threshold
            if next_after_shadow is not None and shadow_selection_threshold is not None
            else 0.0
        )
        dark_separation = (
            median - shadow_selection_threshold if shadow_selection_threshold is not None else 0.0
        )
        tail_gap = penumbra_threshold - shadow_threshold
        distribution_span = (
            high_threshold - shadow_selection_threshold
            if shadow_selection_threshold is not None
            else 0.0
        )
        thresholds = {
            "shadow": shadow_threshold,
            "penumbra": penumbra_threshold,
            "shadow_selection": shadow_selection_threshold,
            "next_after_shadow": next_after_shadow,
            "median": median,
            "mad": mad,
            "high_percentile_95": high_threshold,
            "dark_separation": dark_separation,
            "tail_gap": tail_gap,
            "dark_mode_gap": dark_mode_gap,
            "distribution_span": distribution_span,
        }
        selection = {
            "semantics": _LOWER_TAIL_SELECTION_SEMANTICS,
            "shadow_candidate_count": int(np.count_nonzero(shadow_selection)),
            "penumbra_candidate_count": int(np.count_nonzero(penumbra_selection)),
        }

        if not math.isfinite(distribution_span) or distribution_span <= _SCALE_FLOOR:
            status = "no_confident_shadow:constant_or_insufficient_distribution"
        else:
            robust_tail = (
                mad > _SCALE_FLOOR
                and dark_separation > 0.0
                and dark_separation / mad >= float(resolved.shadow_mad_multiplier)
            )
            discrete_tail = dark_mode_gap > 0.0 and dark_mode_gap / distribution_span >= float(
                resolved.min_tail_gap_fraction
            )
            decision_state = {
                "robust_tail": robust_tail,
                "discrete_tail": discrete_tail,
            }
            scaled_image = _scaled_values(image, normalization_amplitude)
            if penumbra_threshold > shadow_threshold:
                penumbra_mask[input_mask] = penumbra_selection
            if robust_tail or discrete_tail:
                shadow_mask[input_mask] = shadow_selection
                penumbra_mask &= ~shadow_mask
                status = "ok"
            else:
                status = "no_confident_shadow:no_separated_dark_tail"

            if penumbra_threshold > shadow_threshold:
                penumbra_confidence = 0.25 + 0.5 * (
                    (penumbra_threshold - scaled_image) / (penumbra_threshold - shadow_threshold)
                )
                confidence_values[penumbra_mask] = np.clip(
                    penumbra_confidence[penumbra_mask], 0.25, 0.75
                )
            confidence_values[shadow_mask] = 1.0

    confidence = FeatureChannel(
        values=confidence_values,
        valid_mask=input_mask,
        algorithm_version=_ALGORITHM_VERSION,
        parameters={
            "algorithm": "conservative_source_darkness_confidence",
            "confidence_semantics": "0=none, (0,1)=ambiguous_penumbra, 1=dark_candidate",
            "invalid_fill_value": _INVALID_FILL_VALUE,
        },
        value_range=_CONFIDENCE_RANGE,
    )
    return ShadowEstimate(
        usable_mask=input_mask,
        shadow_mask=shadow_mask,
        penumbra_mask=penumbra_mask,
        confidence=confidence,
        provenance=_provenance(
            resolved,
            valid_count=valid_count,
            usable_mask_supplied=usable_mask is not None,
            status=status,
            normalization_amplitude=normalization_amplitude,
            thresholds=thresholds,
            decision_state=decision_state,
            selection=selection,
        ),
    )
