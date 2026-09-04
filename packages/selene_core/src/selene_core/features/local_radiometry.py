"""Mask-safe, local robust radiometric normalisation.

The normalised channel has the documented range ``[-1.0, 1.0]``.  Invalid
cells are filled with the finite sentinel ``0.0`` but always have a false
``valid_mask`` entry.  Local windows are clipped at image boundaries and use
only pixels whose input mask is true; they neither interpolate invalid cells
nor use their values in a statistic.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from numbers import Real
from types import MappingProxyType
from typing import TypeAlias, cast

import numpy as np
import numpy.typing as npt

__all__ = [
    "FeatureChannel",
    "LocalRadiometricNormalizationParameters",
    "normalize_local_radiometry",
]

_ALGORITHM_VERSION = "1.0"
_INVALID_FILL_VALUE = 0.0
_NORMALIZED_RANGE = (-1.0, 1.0)
_MAD_TO_SIGMA = 1.4826

ProvenanceValue: TypeAlias = object


def _freeze_provenance(value: ProvenanceValue) -> ProvenanceValue:
    """Recursively copy and freeze supported provenance values.

    Provenance is deliberately limited to JSON-like scalars and containers.
    NumPy arrays are rejected, including object arrays: a read-only array can
    be made writable again through its public API, so exposing one would not
    meet this contract's immutability guarantee.
    """
    if isinstance(value, np.ndarray):
        raise ValueError("FeatureChannel provenance does not support NumPy arrays")
    if isinstance(value, Mapping):
        frozen: dict[str, ProvenanceValue] = {}
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError("FeatureChannel parameter keys must be strings")
            frozen[key] = _freeze_provenance(nested_value)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_provenance(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_provenance(item) for item in value)
    if value is None or isinstance(value, (str, bytes, bool, int, float, np.generic)):
        return value
    raise ValueError(
        f"FeatureChannel provenance has unsupported mutable value {type(value).__name__}"
    )


def _normalise_value_range(value_range: object) -> tuple[float, float]:
    """Copy a caller-provided pair into the immutable channel bounds tuple."""
    if isinstance(value_range, (str, bytes)) or not isinstance(value_range, Iterable):
        raise ValueError("FeatureChannel.value_range must be a finite 2-item sequence")
    try:
        bounds = tuple(value_range)
    except TypeError as error:
        raise ValueError("FeatureChannel.value_range must be a finite 2-item sequence") from error
    if len(bounds) != 2:
        raise ValueError("FeatureChannel.value_range must be a finite 2-item sequence")
    lower, upper = bounds
    if (
        isinstance(lower, bool)
        or isinstance(upper, bool)
        or not isinstance(lower, Real)
        or not isinstance(upper, Real)
    ):
        raise ValueError("FeatureChannel.value_range must contain finite real values")
    normalised = (float(lower), float(upper))
    if not (
        math.isfinite(normalised[0])
        and math.isfinite(normalised[1])
        and normalised[0] <= normalised[1]
    ):
        raise ValueError("FeatureChannel.value_range must be finite and ordered")
    return normalised


@dataclass(frozen=True, slots=True)
class FeatureChannel:
    """An immutable, bounded 2D feature channel and its provenance.

    ``values`` and ``valid_mask`` are defensively copied and made read-only.
    ``valid_mask`` has explicit positive polarity: true means the pixel is
    usable.  Values, including invalid fill cells, must be finite and within
    ``value_range``.  This prevents a channel consumer from accidentally
    treating non-finite nodata as a legitimate numerical feature.
    """

    values: npt.NDArray[np.float64]
    valid_mask: npt.NDArray[np.bool_]
    algorithm_version: str
    parameters: Mapping[str, ProvenanceValue] = field(default_factory=dict)
    value_range: tuple[float, float] = _NORMALIZED_RANGE

    def __post_init__(self) -> None:
        if not isinstance(self.values, np.ndarray) or self.values.dtype != np.float64:
            raise ValueError("FeatureChannel.values must be a float64 NumPy array")
        if self.values.ndim != 2:
            raise ValueError("FeatureChannel.values must be a 2D array")
        if not isinstance(self.valid_mask, np.ndarray) or self.valid_mask.dtype != np.bool_:
            raise ValueError("FeatureChannel.valid_mask must be a boolean NumPy array")
        if self.valid_mask.shape != self.values.shape:
            raise ValueError("FeatureChannel.valid_mask shape must match values shape")
        if not self.algorithm_version:
            raise ValueError("FeatureChannel.algorithm_version must be non-empty")
        normalised_range = _normalise_value_range(self.value_range)
        lower, upper = normalised_range
        if not np.all(np.isfinite(self.values)):
            raise ValueError("FeatureChannel.values must be finite")
        if np.any(self.values < lower) or np.any(self.values > upper):
            raise ValueError("FeatureChannel.values must be bounded by value_range")

        values = self.values.copy()
        valid_mask = self.valid_mask.copy()
        values.setflags(write=False)
        valid_mask.setflags(write=False)
        frozen_parameters = _freeze_provenance(dict(self.parameters))
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "valid_mask", valid_mask)
        object.__setattr__(
            self, "parameters", cast(Mapping[str, ProvenanceValue], frozen_parameters)
        )
        object.__setattr__(self, "value_range", normalised_range)


@dataclass(frozen=True, slots=True)
class LocalRadiometricNormalizationParameters:
    """Validated configuration for :func:`normalize_local_radiometry`.

    ``min_valid_fraction`` is measured against the clipped, in-bounds local
    window.  The effective required support is the greater of that fraction
    and ``min_valid_count``.  ``clip_sigma`` is the symmetric robust-z score
    saturation threshold mapped onto the output range ``[-1, 1]``.
    """

    window_size: int = 15
    min_valid_fraction: float = 0.5
    min_valid_count: int = 9
    clip_sigma: float = 3.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.window_size, bool)
            or not isinstance(self.window_size, int)
            or self.window_size < 3
            or self.window_size % 2 == 0
        ):
            raise ValueError("window_size must be an odd integer of at least 3")
        if (
            isinstance(self.min_valid_fraction, bool)
            or not isinstance(self.min_valid_fraction, (float, int))
            or not math.isfinite(self.min_valid_fraction)
            or not 0.0 < self.min_valid_fraction <= 1.0
        ):
            raise ValueError("min_valid_fraction must be finite and in (0, 1]")
        if isinstance(self.min_valid_count, bool) or not isinstance(self.min_valid_count, int):
            raise ValueError("min_valid_count must be a positive integer")
        if self.min_valid_count < 1:
            raise ValueError("min_valid_count must be a positive integer")
        if (
            isinstance(self.clip_sigma, bool)
            or not isinstance(self.clip_sigma, (float, int))
            or not math.isfinite(self.clip_sigma)
            or self.clip_sigma <= 0.0
        ):
            raise ValueError("clip_sigma must be finite and positive")


def _validate_input(
    image: npt.NDArray[np.float64], valid_mask: npt.NDArray[np.bool_] | None
) -> npt.NDArray[np.bool_]:
    if not isinstance(image, np.ndarray) or image.dtype != np.float64:
        raise ValueError("image must be a float64 NumPy array")
    if image.ndim != 2 or image.size == 0:
        raise ValueError("image must be a non-empty 2D array")
    if not np.all(np.isfinite(image)):
        raise ValueError("image must contain only finite values")
    if valid_mask is None:
        return np.ones(image.shape, dtype=np.bool_)
    if not isinstance(valid_mask, np.ndarray) or valid_mask.dtype != np.bool_:
        raise ValueError("valid_mask must be a boolean NumPy array")
    if valid_mask.shape != image.shape:
        raise ValueError("valid_mask shape must match image shape")
    return valid_mask


def normalize_local_radiometry(
    image: npt.NDArray[np.float64],
    *,
    valid_mask: npt.NDArray[np.bool_] | None = None,
    parameters: LocalRadiometricNormalizationParameters | None = None,
) -> FeatureChannel:
    """Return a robust local-normalisation feature channel for ``image``.

    The local centre is the median and the scale is ``1.4826 * MAD``, both
    calculated solely from usable cells in each clipped window.  A usable
    centre pixel becomes invalid when its window has insufficient usable
    support.  A constant-support window is deterministically represented by
    zero rather than dividing by a negligible scale.
    """
    input_mask = _validate_input(image, valid_mask)
    resolved = parameters if parameters is not None else LocalRadiometricNormalizationParameters()
    radius = resolved.window_size // 2
    output = np.full(image.shape, _INVALID_FILL_VALUE, dtype=np.float64)
    output_mask = np.zeros(image.shape, dtype=np.bool_)

    for line in range(image.shape[0]):
        line_start = max(0, line - radius)
        line_stop = min(image.shape[0], line + radius + 1)
        for sample in range(image.shape[1]):
            if not input_mask[line, sample]:
                continue
            sample_start = max(0, sample - radius)
            sample_stop = min(image.shape[1], sample + radius + 1)
            local_mask = input_mask[line_start:line_stop, sample_start:sample_stop]
            local_area = local_mask.size
            required_count = max(
                resolved.min_valid_count,
                math.ceil(resolved.min_valid_fraction * local_area),
            )
            if int(np.count_nonzero(local_mask)) < required_count:
                continue
            local_values = image[line_start:line_stop, sample_start:sample_stop][local_mask]
            centre = float(np.median(local_values))
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                scale = _MAD_TO_SIGMA * float(np.median(np.abs(local_values - centre)))
                robust_z = (float(image[line, sample]) - centre) / scale
            if not math.isfinite(scale) or scale <= np.finfo(np.float64).eps:
                normalised = 0.0
            elif not math.isfinite(robust_z):
                normalised = 1.0 if robust_z > 0.0 else -1.0 if robust_z < 0.0 else 0.0
            else:
                normalised = float(np.clip(robust_z / resolved.clip_sigma, *_NORMALIZED_RANGE))
            output[line, sample] = normalised
            output_mask[line, sample] = True

    return FeatureChannel(
        values=output,
        valid_mask=output_mask,
        algorithm_version=_ALGORITHM_VERSION,
        parameters={
            "algorithm": "local_radiometric_normalization",
            "window_size": resolved.window_size,
            "min_valid_fraction": resolved.min_valid_fraction,
            "min_valid_count": resolved.min_valid_count,
            "clip_sigma": resolved.clip_sigma,
            "invalid_fill_value": _INVALID_FILL_VALUE,
            "output_range": _NORMALIZED_RANGE,
            "valid_mask_supplied": valid_mask is not None,
        },
    )
