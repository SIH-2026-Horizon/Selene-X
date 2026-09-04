"""Mask-safe, local structural feature channels for lunar-image matching.

The module deliberately uses only NumPy and makes no claim to implement phase
congruency.  Its ``phase_equivalent`` channel is instead a *local phase-balance
response*: the absolute, offset-invariant four-neighbour Laplacian divided by
the local first-difference energy.  It is a modest bounded indication of local
even/odd structural balance, not a multi-scale Fourier phase-congruency
measurement.  Consequently it has no illumination or physical-invariance
claim beyond additive-offset invariance.

All output masks have positive polarity (``True`` means usable).  A gradient
or phase response requires a complete axial cross of usable input cells.  The
self-similarity response requires its full patch-and-search square to be
usable.  Thus no result is interpolated across nodata, masked gaps, or image
borders; invalid output cells use the finite zero sentinel.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import numpy.typing as npt

from selene_core.features.local_radiometry import FeatureChannel

__all__ = [
    "StructuralFeatureBundle",
    "StructuralFeatureParameters",
    "extract_gradient_magnitude",
    "extract_gradient_orientation",
    "extract_local_self_similarity",
    "extract_phase_equivalent",
    "extract_structural_features",
]

_ALGORITHM_VERSION = "1.0"
_INVALID_FILL_VALUE = 0.0
_UNIT_RANGE = (0.0, 1.0)
_ORIENTATION_RANGE = (-math.pi, math.pi)
_MIN_POSITIVE_FLOAT64 = float.fromhex("0x0.0000000000001p-1022")
_MIN_NORMAL_FLOAT64 = float.fromhex("0x1.0p-1022")
_MAX_FINITE_FLOAT64 = float.fromhex("0x1.fffffffffffffp+1023")
_MAGNITUDE_RELATIVE_FLOOR = math.sqrt(float.fromhex("0x1.0p-53"))
_SQUARED_TERM_FLOOR = math.sqrt(_MIN_NORMAL_FLOAT64)
_CHANNEL_NAMES = (
    "gradient_magnitude",
    "gradient_orientation",
    "phase_equivalent",
    "local_self_similarity",
)


@dataclass(frozen=True, slots=True)
class StructuralFeatureParameters:
    """Validated settings shared by the independent structural extractors.

    ``gradient_percentile`` is the percentile of each usable cross stencil's
    four axial first differences used as its robust local magnitude scale.
    Values at or above that local scale saturate at one.  Orientation is only
    usable when the locally amplitude-scaled magnitude is strictly above
    ``orientation_min_magnitude``; its convention is ``atan2(dy, dx)`` where
    line/row ``y`` increases downward and sample/column ``x`` increases right.
    Hence an eastward increasing image has angle zero and a southward
    increasing image has angle ``+pi/2``.

    ``patch_radius`` gives the square comparison patch half-width and
    ``search_radius`` gives the maximum Chebyshev offset considered.  The
    latter must exceed twice the former so candidates cannot overlap the
    reference patch.  Self-similarity is the maximum over those candidates of
    ``exp(-MSE / max(local_RMS_contrast, similarity_scale)**2)``.  The entire
    patch-and-search square must be in-bounds and usable, preventing masked
    data from entering any comparison.
    """

    gradient_percentile: float = 95.0
    orientation_min_magnitude: float = 1e-12
    patch_radius: int = 1
    search_radius: int = 3
    similarity_scale: float = 1e-6

    def __post_init__(self) -> None:
        if (
            isinstance(self.gradient_percentile, bool)
            or not isinstance(self.gradient_percentile, (int, float))
            or not math.isfinite(self.gradient_percentile)
            or not 0.0 < self.gradient_percentile <= 100.0
        ):
            raise ValueError("gradient_percentile must be finite and in (0, 100]")
        if (
            isinstance(self.orientation_min_magnitude, bool)
            or not isinstance(self.orientation_min_magnitude, (int, float))
            or not math.isfinite(self.orientation_min_magnitude)
            or self.orientation_min_magnitude < 0.0
        ):
            raise ValueError("orientation_min_magnitude must be finite and non-negative")
        for name, value in (
            ("patch_radius", self.patch_radius),
            ("search_radius", self.search_radius),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer of at least 1")
        if self.search_radius <= 2 * self.patch_radius:
            raise ValueError("search_radius must be larger than twice patch_radius")
        if (
            isinstance(self.similarity_scale, bool)
            or not isinstance(self.similarity_scale, (int, float))
            or not math.isfinite(self.similarity_scale)
            or self.similarity_scale <= 0.0
        ):
            raise ValueError("similarity_scale must be finite and positive")


@dataclass(frozen=True, slots=True)
class StructuralFeatureBundle:
    """Immutable, independently selectable structural channels by name."""

    channels: Mapping[str, FeatureChannel]

    def __post_init__(self) -> None:
        copied = dict(self.channels)
        unknown = set(copied).difference(_CHANNEL_NAMES)
        if unknown:
            raise ValueError(f"StructuralFeatureBundle has unknown channels: {sorted(unknown)!r}")
        if not copied:
            raise ValueError("StructuralFeatureBundle requires at least one channel")
        if any(not isinstance(channel, FeatureChannel) for channel in copied.values()):
            raise ValueError("StructuralFeatureBundle channels must be FeatureChannel instances")
        object.__setattr__(self, "channels", MappingProxyType(copied))

    def __getitem__(self, name: str) -> FeatureChannel:
        """Return an individually selected channel."""
        return self.channels[name]


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


def _resolved(parameters: StructuralFeatureParameters | None) -> StructuralFeatureParameters:
    return parameters if parameters is not None else StructuralFeatureParameters()


def _cross_support(input_mask: npt.NDArray[np.bool_]) -> npt.NDArray[np.bool_]:
    """Require the centre and all four direct neighbours; borders fail closed."""
    support = np.zeros(input_mask.shape, dtype=np.bool_)
    if input_mask.shape[0] >= 3 and input_mask.shape[1] >= 3:
        support[1:-1, 1:-1] = (
            input_mask[1:-1, 1:-1]
            & input_mask[:-2, 1:-1]
            & input_mask[2:, 1:-1]
            & input_mask[1:-1, :-2]
            & input_mask[1:-1, 2:]
        )
    return support


def _local_amplitude_scale(values: Iterable[np.float64 | float]) -> float:
    """Return the finite local amplitude of values already known to be usable."""
    return max((abs(float(value)) for value in values), default=0.0)


def _scaled_value(value: np.float64, amplitude_scale: float) -> float:
    """Safely divide a finite value by the chosen finite amplitude scale."""
    if amplitude_scale == 0.0:
        return 0.0
    return float(value) / amplitude_scale


def _zero_unresolvable_squared_term(value: float) -> float:
    """Drop terms whose square has no normal float64 representation."""
    return 0.0 if abs(value) < _SQUARED_TERM_FLOOR else value


def _scaled_patch_values(
    patch: npt.NDArray[np.float64], amplitude_scale: float
) -> tuple[float, ...]:
    """Scale valid patch samples and floor terms before later squared operations."""
    return tuple(
        _zero_unresolvable_squared_term(_scaled_value(value, amplitude_scale))
        for value in patch.flat
    )


def _stable_gradient_magnitude(dx: float, dy: float) -> float:
    """Return a normal, bounded magnitude without subnormal NumPy arithmetic.

    A component smaller than ``sqrt(eps / 2)`` relative to the larger one
    cannot affect the correctly rounded value of ``sqrt(dx**2 + dy**2)``.
    Dropping it avoids a subnormal divide/square.  If both components are
    subnormal, the later normalisation cannot represent their magnitude
    reliably, so this conservative channel records zero instead.
    """
    largest = max(abs(dx), abs(dy))
    if largest < _MIN_NORMAL_FLOAT64:
        return 0.0
    smallest = min(abs(dx), abs(dy))
    if smallest < largest * _MAGNITUDE_RELATIVE_FLOOR:
        return largest
    relative = smallest / largest
    return largest * math.sqrt(1.0 + relative * relative)


def _stable_gradient_orientation(dx: float, dy: float) -> float:
    """Return orientation after removing physically unresolvable tiny components."""
    stable_dx = 0.0 if abs(dx) < _MIN_NORMAL_FLOAT64 else dx
    stable_dy = 0.0 if abs(dy) < _MIN_NORMAL_FLOAT64 else dy
    return math.atan2(stable_dy, stable_dx)


def _gradient_magnitudes(
    dx: npt.NDArray[np.float64],
    dy: npt.NDArray[np.float64],
    support: npt.NDArray[np.bool_],
) -> npt.NDArray[np.float64]:
    """Compute stable magnitudes only where the gradient stencil is usable."""
    magnitudes = np.zeros(dx.shape, dtype=np.float64)
    for line, sample in zip(*np.nonzero(support), strict=True):
        magnitudes[line, sample] = _stable_gradient_magnitude(
            float(dx[line, sample]), float(dy[line, sample])
        )
    return magnitudes


def _gradient_raw(
    image: npt.NDArray[np.float64],
    input_mask: npt.NDArray[np.bool_],
    gradient_percentile: float,
) -> tuple[
    npt.NDArray[np.float64],
    npt.NDArray[np.float64],
    npt.NDArray[np.bool_],
    npt.NDArray[np.float64],
]:
    """Compute locally scaled differences and axial robust normalisers only on crosses."""
    support = _cross_support(input_mask)
    dx = np.zeros(image.shape, dtype=np.float64)
    dy = np.zeros(image.shape, dtype=np.float64)
    normalizer = np.zeros(image.shape, dtype=np.float64)
    for line, sample in zip(*np.nonzero(support), strict=True):
        source_values = (
            image[line, sample],
            image[line - 1, sample],
            image[line + 1, sample],
            image[line, sample - 1],
            image[line, sample + 1],
        )
        amplitude_scale = _local_amplitude_scale(source_values)
        centre, north, south, west, east = (
            _scaled_value(value, amplitude_scale) for value in source_values
        )
        dx[line, sample] = (east - west) / 2.0
        dy[line, sample] = (south - north) / 2.0
        normalizer[line, sample] = float(
            np.percentile(
                (abs(centre - north), abs(centre - south), abs(centre - west), abs(centre - east)),
                gradient_percentile,
            )
        )
    return dx, dy, support, normalizer


def _base_parameters(
    resolved: StructuralFeatureParameters, valid_mask_supplied: bool
) -> dict[str, object]:
    return {
        "algorithm_version": _ALGORITHM_VERSION,
        "gradient_percentile": float(resolved.gradient_percentile),
        "orientation_min_magnitude": float(resolved.orientation_min_magnitude),
        "patch_radius": resolved.patch_radius,
        "search_radius": resolved.search_radius,
        "similarity_scale": float(resolved.similarity_scale),
        "invalid_fill_value": _INVALID_FILL_VALUE,
        "valid_mask_supplied": valid_mask_supplied,
        "border_policy": "fail_closed",
    }


def extract_gradient_magnitude(
    image: npt.NDArray[np.float64],
    *,
    valid_mask: npt.NDArray[np.bool_] | None = None,
    parameters: StructuralFeatureParameters | None = None,
) -> FeatureChannel:
    """Return robustly normalised central-difference gradient magnitude.

    A complete usable axial cross is required.  Each gradient is divided by
    the requested percentile of its own four axial first differences, then
    clipped to ``[0, 1]``.  This robust local scaling means a distant valid
    extreme cannot alter the feature.  Magnitudes too small to yield a normal
    float64 ratio are conservatively represented as zero.
    """
    input_mask = _validate_input(image, valid_mask)
    resolved = _resolved(parameters)
    dx, dy, support, local_normalizer = _gradient_raw(
        image, input_mask, resolved.gradient_percentile
    )
    raw_magnitude = _gradient_magnitudes(dx, dy, support)
    output = np.full(image.shape, _INVALID_FILL_VALUE, dtype=np.float64)
    underflow_floor = 0.0
    if np.any(support):
        for line, sample in zip(*np.nonzero(support), strict=True):
            magnitude = float(raw_magnitude[line, sample])
            normalizer = float(local_normalizer[line, sample])
            if normalizer < _MIN_NORMAL_FLOAT64:
                continue
            pixel_underflow_floor = _MIN_NORMAL_FLOAT64 * normalizer
            underflow_floor = max(underflow_floor, pixel_underflow_floor)
            if magnitude < pixel_underflow_floor:
                continue
            output[line, sample] = 1.0 if magnitude >= normalizer else magnitude / normalizer
    provenance = _base_parameters(resolved, valid_mask is not None)
    provenance.update(
        {
            "algorithm": "central_difference_gradient_magnitude",
            "normalization": "per_stencil_axial_difference_percentile_clip",
            "normalization_scale": "per_stencil",
            "maximum_underflow_floor": underflow_floor,
            "numerical_stability": "per_stencil_amplitude_rescaling",
            "output_range": _UNIT_RANGE,
            "support": "centre+north+south+west+east",
        }
    )
    return FeatureChannel(output, support, _ALGORITHM_VERSION, provenance, _UNIT_RANGE)


def extract_gradient_orientation(
    image: npt.NDArray[np.float64],
    *,
    valid_mask: npt.NDArray[np.bool_] | None = None,
    parameters: StructuralFeatureParameters | None = None,
) -> FeatureChannel:
    """Return central-difference orientation using the documented row/column convention."""
    input_mask = _validate_input(image, valid_mask)
    resolved = _resolved(parameters)
    dx, dy, support, _ = _gradient_raw(image, input_mask, resolved.gradient_percentile)
    raw_magnitude = _gradient_magnitudes(dx, dy, support)
    output_mask = support & (raw_magnitude > resolved.orientation_min_magnitude)
    output = np.full(image.shape, _INVALID_FILL_VALUE, dtype=np.float64)
    for line, sample in zip(*np.nonzero(output_mask), strict=True):
        output[line, sample] = _stable_gradient_orientation(
            float(dx[line, sample]), float(dy[line, sample])
        )
    provenance = _base_parameters(resolved, valid_mask is not None)
    provenance.update(
        {
            "algorithm": "central_difference_gradient_orientation",
            "coordinate_convention": "line_y_increases_downward;sample_x_increases_rightward",
            "orientation_convention": "atan2(dy_dx);east=0;south=+pi/2",
            "orientation_tiny_component_floor": _MIN_NORMAL_FLOAT64,
            "numerical_stability": "per_stencil_amplitude_rescaling",
            "output_range": _ORIENTATION_RANGE,
            "support": "centre+north+south+west+east;nonzero_signal_threshold",
        }
    )
    return FeatureChannel(output, output_mask, _ALGORITHM_VERSION, provenance, _ORIENTATION_RANGE)


def extract_phase_equivalent(
    image: npt.NDArray[np.float64],
    *,
    valid_mask: npt.NDArray[np.bool_] | None = None,
    parameters: StructuralFeatureParameters | None = None,
) -> FeatureChannel:
    """Return a bounded local phase-*equivalent* structural response.

    This is not phase congruency.  On a usable axial cross it computes
    ``abs(4*c - n - s - w - e) / (abs(c-n) + abs(c-s) + abs(c-w) + abs(c-e))``;
    a zero denominator maps to zero.  The triangle inequality bounds it to
    ``[0, 1]`` and cancelling the common additive offset makes it invariant to
    an additive radiometric shift.  It is a single-scale local contrast-shape
    cue, with none of phase congruency's multi-scale or physical guarantees.
    """
    input_mask = _validate_input(image, valid_mask)
    resolved = _resolved(parameters)
    support = _cross_support(input_mask)
    output = np.full(image.shape, _INVALID_FILL_VALUE, dtype=np.float64)
    for line, sample in zip(*np.nonzero(support), strict=True):
        source_values = (
            image[line, sample],
            image[line - 1, sample],
            image[line + 1, sample],
            image[line, sample - 1],
            image[line, sample + 1],
        )
        amplitude_scale = _local_amplitude_scale(source_values)
        centre, north, south, west, east = (
            _scaled_value(value, amplitude_scale) for value in source_values
        )
        north_difference = centre - north
        south_difference = centre - south
        west_difference = centre - west
        east_difference = centre - east
        numerator = abs(north_difference + south_difference + west_difference + east_difference)
        denominator = (
            abs(north_difference)
            + abs(south_difference)
            + abs(west_difference)
            + abs(east_difference)
        )
        if denominator > np.finfo(np.float64).eps:
            output[line, sample] = min(1.0, numerator / denominator)
    provenance = _base_parameters(resolved, valid_mask is not None)
    provenance.update(
        {
            "algorithm": "local_phase_balance_equivalent",
            "formulation": "abs(four_neighbour_laplacian)/axial_first_difference_l1",
            "not_phase_congruency": True,
            "invariance": "additive_radiometric_offset_only",
            "amplitude_scaling": "per_axial_stencil",
            "numerical_stability": "per_stencil_amplitude_rescaling",
            "output_range": _UNIT_RANGE,
            "support": "centre+north+south+west+east",
        }
    )
    return FeatureChannel(output, support, _ALGORITHM_VERSION, provenance, _UNIT_RANGE)


def _full_square_support(input_mask: npt.NDArray[np.bool_], radius: int) -> npt.NDArray[np.bool_]:
    """Mark cells whose complete square support is in-bounds and usable."""
    output = np.zeros(input_mask.shape, dtype=np.bool_)
    height, width = input_mask.shape
    if height <= 2 * radius or width <= 2 * radius:
        return output
    for line in range(radius, height - radius):
        for sample in range(radius, width - radius):
            local_mask = input_mask[
                line - radius : line + radius + 1,
                sample - radius : sample + radius + 1,
            ]
            output[line, sample] = bool(np.all(local_mask))
    return output


def extract_local_self_similarity(
    image: npt.NDArray[np.float64],
    *,
    valid_mask: npt.NDArray[np.bool_] | None = None,
    parameters: StructuralFeatureParameters | None = None,
) -> FeatureChannel:
    """Return maximum patch self-similarity over a local non-overlap search.

    The reference patch is compared with every square patch at offsets no more
    than ``search_radius`` in Chebyshev distance and farther than twice
    ``patch_radius``.  The maximum exponential score is emitted.  Because the
    entire outer ``patch_radius + search_radius`` square must be valid, every
    candidate and its reference have complete observed support; no masked
    samples, interpolation, or border extrapolation can affect the score.
    Terms whose squares cannot be represented as normal float64 values are
    deterministically treated as zero before any squared-error operation.
    """
    input_mask = _validate_input(image, valid_mask)
    resolved = _resolved(parameters)
    outer_radius = resolved.patch_radius + resolved.search_radius
    output_mask = _full_square_support(input_mask, outer_radius)
    output = np.full(image.shape, _INVALID_FILL_VALUE, dtype=np.float64)
    offsets = tuple(
        (line_offset, sample_offset)
        for line_offset in range(-resolved.search_radius, resolved.search_radius + 1)
        for sample_offset in range(-resolved.search_radius, resolved.search_radius + 1)
        if max(abs(line_offset), abs(sample_offset)) > 2 * resolved.patch_radius
    )
    patch_radius = resolved.patch_radius
    for line, sample in np.argwhere(output_mask):
        reference_patch = image[
            line - patch_radius : line + patch_radius + 1,
            sample - patch_radius : sample + patch_radius + 1,
        ]
        best_score = 0.0
        for line_offset, sample_offset in offsets:
            candidate_patch = image[
                line + line_offset - patch_radius : line + line_offset + patch_radius + 1,
                sample + sample_offset - patch_radius : sample + sample_offset + patch_radius + 1,
            ]
            amplitude_scale = _local_amplitude_scale(
                value for patch in (reference_patch, candidate_patch) for value in patch.flat
            )
            reference = _scaled_patch_values(reference_patch, amplitude_scale)
            candidate = _scaled_patch_values(candidate_patch, amplitude_scale)
            reference_mean = math.fsum(reference) / len(reference)
            reference_contrast = tuple(
                _zero_unresolvable_squared_term(value - reference_mean) for value in reference
            )
            similarity_floor = _scaled_value(np.float64(resolved.similarity_scale), amplitude_scale)
            scale = max(
                math.sqrt(
                    math.fsum(value * value for value in reference_contrast) / len(reference)
                ),
                similarity_floor,
                _MIN_POSITIVE_FLOAT64,
            )
            difference = tuple(
                _zero_unresolvable_squared_term(reference_value - candidate_value)
                for reference_value, candidate_value in zip(reference, candidate, strict=True)
            )
            mse = math.fsum(value * value for value in difference) / len(reference)
            if mse == 0.0 or math.isinf(scale):
                score = 1.0
            elif scale <= math.sqrt(mse / _MAX_FINITE_FLOAT64):
                score = 0.0
            else:
                score = math.exp(-(mse / scale) / scale)
            best_score = max(best_score, score)
        output[line, sample] = best_score
    provenance = _base_parameters(resolved, valid_mask is not None)
    provenance.update(
        {
            "algorithm": "max_local_patch_self_similarity",
            "score": "max(exp(-patch_mse/max(reference_rms_contrast,similarity_scale)^2))",
            "patch_shape": (2 * patch_radius + 1, 2 * patch_radius + 1),
            "search_metric": "chebyshev",
            "candidate_offsets": "2*patch_radius < chebyshev_offset <= search_radius",
            "amplitude_scaling": "per_reference_candidate_patch_pair",
            "numerical_stability": "per_patch_pair_amplitude_rescaling",
            "squared_term_floor": _SQUARED_TERM_FLOOR,
            "output_range": _UNIT_RANGE,
            "support": "full_patch_and_search_square",
        }
    )
    return FeatureChannel(output, output_mask, _ALGORITHM_VERSION, provenance, _UNIT_RANGE)


def _resolve_channel_names(channels: Iterable[str] | None) -> tuple[str, ...]:
    if channels is None:
        return _CHANNEL_NAMES
    if isinstance(channels, (str, bytes)):
        raise ValueError("channels must be an iterable of channel names, not a string")
    selected = tuple(channels)
    if not selected:
        raise ValueError("channels must request at least one known channel")
    unknown = set(selected).difference(_CHANNEL_NAMES)
    if unknown:
        raise ValueError(f"channels contains unknown feature names: {sorted(unknown)!r}")
    if len(set(selected)) != len(selected):
        raise ValueError("channels must not contain duplicate feature names")
    return selected


def extract_structural_features(
    image: npt.NDArray[np.float64],
    *,
    valid_mask: npt.NDArray[np.bool_] | None = None,
    parameters: StructuralFeatureParameters | None = None,
    channels: Iterable[str] | None = None,
) -> StructuralFeatureBundle:
    """Build exactly the independently requested mask-safe structural channels."""
    selected = _resolve_channel_names(channels)
    # Validate before dispatch so a selected subset has the same input contract.
    _validate_input(image, valid_mask)
    resolved = _resolved(parameters)
    extractors = {
        "gradient_magnitude": extract_gradient_magnitude,
        "gradient_orientation": extract_gradient_orientation,
        "phase_equivalent": extract_phase_equivalent,
        "local_self_similarity": extract_local_self_similarity,
    }
    return StructuralFeatureBundle(
        {
            name: extractors[name](image, valid_mask=valid_mask, parameters=resolved)
            for name in selected
        }
    )
