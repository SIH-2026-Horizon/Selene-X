"""Registry-backed compact grouped dense-flow matching (WP-06 task 1).

This adapter implements the common :class:`~selene_core.match.protocol.Matcher`
ABI for the existing ``selene_matcher`` artifact.  It is a compact grouped
dense-flow baseline, **not** a LoFTR/RoMa implementation or a claim of
validated matching accuracy.  It reads only a SHA-256-verified artifact from
the local model registry; it performs no network access.

The model consumes groups rather than the ABI's one image channel.  Channel
policy ``normalized-image-v1`` deterministically derives up to five groups
from each valid input image: mask-aware normalized intensity, line derivative,
sample derivative, gradient magnitude, and 3x3 local contrast.  Invalid pixels
are zeroed after each derivation.  The policy name is recorded in every output
record's ``algorithm_version``.
"""

from __future__ import annotations

import hashlib
import heapq
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import numpy.typing as npt

from selene_core.hashing import digest_json
from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.protocol import Matcher, MatchParameters, MatchPrior
from selene_core.models import LoadedModel, LocalModelRegistry, load_local_model
from selene_core.types import Covariance2D, CovarianceFrame, ReferencePixel, SourcePixel

__all__ = [
    "ConfidenceCalibration",
    "GroupedDenseFlowMatcher",
    "LearnedMatcherConfigurationError",
    "LearnedMatcherError",
    "LearnedMatcherInferenceError",
    "LearnedMatcherInputError",
    "LearnedMatcherLoadError",
]

_ALGORITHM: Final = "selene_matcher_grouped_dense_flow"
_ADAPTER_VERSION: Final = "1.0.0"
_CHANNEL_POLICY_VERSION: Final = "normalized-image-v1"
_MAX_CHANNEL_GROUPS: Final = 5
_FALLBACK_PARAMETERS_KEY: Final = "fallback_parameters"
_REQUIRED_PARAMETER_KEYS: Final = frozenset({"candidate_stride_px", "max_candidates"})
_ALLOWED_PARAMETER_KEYS: Final = frozenset(
    {*_REQUIRED_PARAMETER_KEYS, _FALLBACK_PARAMETERS_KEY}
)
_LOG_MIN_POSITIVE: Final = math.log(np.finfo(np.float64).tiny)
_LOG_MAX_FINITE: Final = math.log(np.finfo(np.float64).max)


class LearnedMatcherError(RuntimeError):
    """Base error for the compact learned matcher adapter."""


class LearnedMatcherConfigurationError(LearnedMatcherError):
    """Raised for unsupported, implicit, or malformed adapter configuration."""


class LearnedMatcherLoadError(LearnedMatcherError):
    """Raised when the verified local learned artifact cannot be loaded."""

    fallback_label: Final[str] = "learned matcher load failure"


class LearnedMatcherInputError(LearnedMatcherError):
    """Raised when an input cannot meet the learned model's array contract."""

    fallback_label: Final[str] = "learned matcher input-contract failure"


class LearnedMatcherInferenceError(LearnedMatcherError):
    """Raised when a loaded model cannot produce valid dense-flow outputs."""

    fallback_label: Final[str] = "learned matcher inference failure"


@dataclass(frozen=True, slots=True)
class ConfidenceCalibration:
    """An explicit caller-supplied transform from model log variance to confidence.

    ``selene_matcher``'s log variance is not calibrated by this adapter.  A
    caller may provide this named contract when it owns and has separately
    documented a calibration procedure; this adapter neither creates such a
    contract nor asserts held-out performance for it.  Model covariance remains
    explicitly uncalibrated in all cases.
    """

    contract_id: str
    log_variance_offset: float
    scale: float

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("ConfidenceCalibration.contract_id must not be empty")
        if not math.isfinite(self.log_variance_offset):
            raise ValueError("ConfidenceCalibration.log_variance_offset must be finite")
        if not math.isfinite(self.scale) or self.scale <= 0.0:
            raise ValueError("ConfidenceCalibration.scale must be finite and positive")

    def confidence_for(self, log_variance: float) -> float:
        """Apply the declared logistic transform without claiming its validity."""
        exponent = (log_variance - self.log_variance_offset) / self.scale
        if exponent >= 0.0:
            numerator = math.exp(-exponent)
            return numerator / (1.0 + numerator)
        return 1.0 / (1.0 + math.exp(exponent))


@dataclass(frozen=True, slots=True)
class _Configuration:
    candidate_stride_px: int
    max_candidates: int
    fallback_parameters: MatchParameters | None


@dataclass(frozen=True, slots=True)
class _Candidate:
    source_line: int
    source_sample: int
    reference_line: float
    reference_sample: float
    log_variance: float

    @property
    def raw_score(self) -> float:
        """The uncalibrated evidence score retained from the model output."""
        return -self.log_variance


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LearnedMatcherConfigurationError(
            f"learned matcher parameter {name!r} must be a positive integer, got {value!r}"
        )
    return value


def _configuration(parameters: MatchParameters) -> _Configuration:
    keys = set(parameters.values)
    unknown = sorted(keys - _ALLOWED_PARAMETER_KEYS)
    missing = sorted(_REQUIRED_PARAMETER_KEYS - keys)
    if unknown or missing:
        details: list[str] = []
        if unknown:
            details.append(f"unknown keys {unknown!r}")
        if missing:
            details.append(f"missing required keys {missing!r}")
        raise LearnedMatcherConfigurationError(
            "learned matcher parameters must explicitly contain only "
            "'candidate_stride_px', 'max_candidates', and optional "
            "'fallback_parameters': "
            + "; ".join(details)
        )
    fallback_parameters: MatchParameters | None = None
    fallback_values = parameters.values.get(_FALLBACK_PARAMETERS_KEY)
    if fallback_values is not None:
        if not isinstance(fallback_values, Mapping):
            raise LearnedMatcherConfigurationError(
                "learned matcher parameter 'fallback_parameters' must be a mapping"
            )
        if not all(isinstance(key, str) and key for key in fallback_values):
            raise LearnedMatcherConfigurationError(
                "learned matcher fallback parameter names must be non-empty strings"
            )
        fallback_parameters = MatchParameters(values=dict(fallback_values))
    return _Configuration(
        candidate_stride_px=_positive_int(
            parameters.values["candidate_stride_px"], name="candidate_stride_px"
        ),
        max_candidates=_positive_int(parameters.values["max_candidates"], name="max_candidates"),
        fallback_parameters=fallback_parameters,
    )


def _validate_image(name: str, image: object) -> npt.NDArray[np.float64]:
    if not isinstance(image, np.ndarray):
        raise LearnedMatcherInputError(f"{name} must be a NumPy array")
    if image.dtype != np.float64:
        raise LearnedMatcherInputError(f"{name} must have dtype float64, got {image.dtype!r}")
    if image.ndim != 2:
        raise LearnedMatcherInputError(f"{name} must be a 2D array, got shape {image.shape!r}")
    if image.size == 0:
        raise LearnedMatcherInputError(f"{name} must not be empty")
    if not np.all(np.isfinite(image)):
        raise LearnedMatcherInputError(f"{name} must contain only finite values")
    return image


def _validate_mask(
    name: str, mask: object, expected_shape: tuple[int, int]
) -> npt.NDArray[np.bool_] | None:
    if mask is None:
        return None
    if not isinstance(mask, np.ndarray):
        raise LearnedMatcherInputError(f"{name} must be a NumPy array or None")
    if mask.dtype != np.bool_:
        raise LearnedMatcherInputError(f"{name} must have dtype bool, got {mask.dtype!r}")
    if mask.shape != expected_shape:
        raise LearnedMatcherInputError(
            f"{name} shape {mask.shape!r} does not match image shape {expected_shape!r}"
        )
    return mask


def _valid_mask(
    mask: npt.NDArray[np.bool_] | None, shape: tuple[int, int]
) -> npt.NDArray[np.bool_]:
    return np.ones(shape, dtype=np.bool_) if mask is None else mask


def _normalise_valid(
    image: npt.NDArray[np.float64], valid: npt.NDArray[np.bool_]
) -> npt.NDArray[np.float64]:
    output = np.zeros(image.shape, dtype=np.float64)
    values = image[valid]
    if values.size == 0:
        return output
    mean = float(np.mean(values))
    standard_deviation = float(np.std(values))
    if standard_deviation > np.finfo(np.float64).eps:
        output[valid] = (values - mean) / standard_deviation
    return output


def _mask_aware_derivative(
    image: npt.NDArray[np.float64], valid: npt.NDArray[np.bool_], *, axis: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.bool_]]:
    """Differentiate only where the complete finite-difference stencil is usable."""
    derivative = np.zeros(image.shape, dtype=np.float64)
    supported = np.zeros(image.shape, dtype=np.bool_)
    extent = image.shape[axis]
    if extent < 2:
        return derivative, supported

    if axis == 0:
        first_supported = valid[0] & valid[1]
        derivative[0, first_supported] = image[1, first_supported] - image[0, first_supported]
        supported[0, first_supported] = True
        last_supported = valid[-2] & valid[-1]
        derivative[-1, last_supported] = image[-1, last_supported] - image[-2, last_supported]
        supported[-1, last_supported] = True
        if extent > 2:
            interior_supported = valid[:-2] & valid[1:-1] & valid[2:]
            derivative[1:-1] = np.where(
                interior_supported,
                0.5 * (image[2:] - image[:-2]),
                0.0,
            )
            supported[1:-1] = interior_supported
    else:
        first_supported = valid[:, 0] & valid[:, 1]
        derivative[first_supported, 0] = image[first_supported, 1] - image[first_supported, 0]
        supported[first_supported, 0] = True
        last_supported = valid[:, -2] & valid[:, -1]
        derivative[last_supported, -1] = image[last_supported, -1] - image[last_supported, -2]
        supported[last_supported, -1] = True
        if extent > 2:
            interior_supported = valid[:, :-2] & valid[:, 1:-1] & valid[:, 2:]
            derivative[:, 1:-1] = np.where(
                interior_supported,
                0.5 * (image[:, 2:] - image[:, :-2]),
                0.0,
            )
            supported[:, 1:-1] = interior_supported
    return derivative, supported


def _masked_box_mean(
    image: npt.NDArray[np.float64], valid: npt.NDArray[np.bool_]
) -> npt.NDArray[np.float64]:
    """Return a deterministic 3x3 mean that does not turn invalid data into signal."""
    values = np.where(valid, image, 0.0)
    padded_values = np.pad(values, 1, mode="constant")
    padded_valid = np.pad(valid.astype(np.float64), 1, mode="constant")
    total = np.zeros(image.shape, dtype=np.float64)
    count = np.zeros(image.shape, dtype=np.float64)
    for line_offset in range(3):
        for sample_offset in range(3):
            total += padded_values[
                line_offset : line_offset + image.shape[0],
                sample_offset : sample_offset + image.shape[1],
            ]
            count += padded_valid[
                line_offset : line_offset + image.shape[0],
                sample_offset : sample_offset + image.shape[1],
            ]
    return np.divide(total, count, out=np.zeros_like(total), where=count > 0.0)


def _channel_groups(
    image: npt.NDArray[np.float64],
    valid: npt.NDArray[np.bool_],
    *,
    groups: int,
) -> npt.NDArray[np.float64]:
    """Derive the documented fixed channels, taking the first ``groups`` only."""
    normalized = _normalise_valid(image, valid)
    line_raw, line_supported = _mask_aware_derivative(normalized, valid, axis=0)
    sample_raw, sample_supported = _mask_aware_derivative(normalized, valid, axis=1)
    line_derivative = _normalise_valid(line_raw, line_supported)
    sample_derivative = _normalise_valid(sample_raw, sample_supported)
    magnitude_supported = line_supported & sample_supported
    magnitude = _normalise_valid(
        np.hypot(line_derivative, sample_derivative), magnitude_supported
    )
    local_contrast = _normalise_valid(normalized - _masked_box_mean(normalized, valid), valid)
    channels = (normalized, line_derivative, sample_derivative, magnitude, local_contrast)
    output = np.stack(channels[:groups], axis=0)
    output[:, ~valid] = 0.0
    return np.ascontiguousarray(output[np.newaxis, ...], dtype=np.float64)


def _dense_prior(prior: MatchPrior, shape: tuple[int, int]) -> npt.NDArray[np.float64]:
    """Make the model's [dy, dx] initial flow without discarding local warp terms."""
    height, width = shape
    flow = np.empty((1, 2, height, width), dtype=np.float64)
    for line in range(height):
        for sample in range(width):
            dy_px, dx_px = prior.displacement_at(
                SourcePixel(line=float(line), sample=float(sample))
            )
            flow[0, 0, line, sample] = dy_px
            flow[0, 1, line, sample] = dx_px
    return flow


def _as_numpy_output(value: object, *, name: str) -> npt.NDArray[np.float64]:
    """Detach a torch tensor when present, without importing torch in this module."""
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach().cpu().numpy()
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as error:
        raise LearnedMatcherInferenceError(
            f"learned matcher inference failed: {name} is not a numeric array"
        ) from error
    return array


def _nearest_index(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)


def _covariance_from_log_variance(log_variance: float) -> Covariance2D | None:
    """Preserve a valid model variance as uncalibrated reference-pixel covariance."""
    if log_variance <= _LOG_MIN_POSITIVE or log_variance >= _LOG_MAX_FINITE:
        return None
    variance = math.exp(log_variance)
    if not math.isfinite(variance) or variance <= 0.0:
        return None
    return Covariance2D(
        xx=variance,
        xy=0.0,
        yy=variance,
        frame=CovarianceFrame.REFERENCE_PIXEL,
        units="px2",
    )


def _mask_identity(mask: npt.NDArray[np.bool_] | None) -> str | None:
    """Fingerprint a mask because its validity changes correspondence identity."""
    if mask is None:
        return None
    contiguous = np.ascontiguousarray(mask)
    content_digest = hashlib.sha256(contiguous.view(np.uint8)).hexdigest()
    return digest_json({"shape": list(mask.shape), "sha256": content_digest})


def _prior_identity(prior: MatchPrior) -> dict[str, object]:
    """Use every prior field that can alter learned inference in a match identity."""
    jacobian = prior.local_warp_jacobian
    return {
        "displacement_px": prior.displacement_px,
        "displacement_uncertainty_px": prior.displacement_uncertainty_px,
        "search_radius_px": prior.search_radius_px,
        "anchor_source_pixel": [prior.anchor_source_pixel.line, prior.anchor_source_pixel.sample],
        "local_warp_jacobian": (
            None
            if jacobian is None
            else [
                jacobian.d_ref_line_d_src_line,
                jacobian.d_ref_line_d_src_sample,
                jacobian.d_ref_sample_d_src_line,
                jacobian.d_ref_sample_d_src_sample,
            ]
        ),
    }


class GroupedDenseFlowMatcher:
    """Adapt verified ``selene_matcher`` dense flow to the array ``Matcher`` ABI.

    This is deliberately limited to the existing compact grouped dense-flow
    baseline.  It is neither a LoFTR/RoMa-style matcher nor a substitute for
    an evaluated scientific model.  Model log variance is retained as an
    *uncalibrated* raw score/covariance unless ``confidence_calibration`` is
    explicitly supplied by the caller.

    A ``fallback`` is opt-in.  It receives the original ``Matcher.match``
    arguments only after a learned model load, input-contract, or inference
    failure.  Its explicit parameters, when they differ from the learned
    adapter's ``candidate_stride_px`` and ``max_candidates``, belong in the
    ``MatchParameters.values['fallback_parameters']`` mapping.  That mapping
    is forwarded as a fresh parameter snapshot only on fallback; no fallback
    defaults are inferred.  Configuration errors never silently choose another
    algorithm.
    """

    def __init__(
        self,
        *,
        registry: LocalModelRegistry | None = None,
        model_version: str | None = None,
        device: str = "cpu",
        fallback: Matcher | None = None,
        confidence_calibration: ConfidenceCalibration | None = None,
    ) -> None:
        if fallback is not None and not isinstance(fallback, Matcher):
            raise TypeError("fallback must satisfy the Matcher protocol")
        if not device.strip():
            raise ValueError("device must not be empty")
        self._registry = registry
        self._model_version = model_version
        self._device = device
        self._fallback = fallback
        self._confidence_calibration = confidence_calibration
        self._loaded: LoadedModel | None = None

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
        """Return a deterministic, mask-valid bounded set of dense-flow candidates."""
        try:
            configuration = _configuration(parameters)
            checked_source = _validate_image("source", source)
            checked_reference = _validate_image("reference", reference)
            if checked_source.shape != checked_reference.shape:
                raise LearnedMatcherInputError(
                    "learned matcher requires source and reference to have identical shapes, "
                    f"got {checked_source.shape!r} and {checked_reference.shape!r}"
                )
            checked_source_mask = _validate_mask("source_mask", source_mask, checked_source.shape)
            checked_reference_mask = _validate_mask(
                "reference_mask", reference_mask, checked_reference.shape
            )
            return self._match_checked(
                checked_source,
                checked_reference,
                source_mask=checked_source_mask,
                reference_mask=checked_reference_mask,
                prior=prior,
                configuration=configuration,
                parameters=parameters,
                job_id=job_id,
                input_digest=input_digest,
                reference_digest=reference_digest,
            )
        except (
            LearnedMatcherLoadError,
            LearnedMatcherInputError,
            LearnedMatcherInferenceError,
        ) as error:
            return self._fallback_or_raise(
                error,
                source=source,
                reference=reference,
                source_mask=source_mask,
                reference_mask=reference_mask,
                prior=prior,
                parameters=parameters,
                job_id=job_id,
                input_digest=input_digest,
                reference_digest=reference_digest,
                fallback_parameters=configuration.fallback_parameters,
            )

    def _match_checked(
        self,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        *,
        source_mask: npt.NDArray[np.bool_] | None,
        reference_mask: npt.NDArray[np.bool_] | None,
        prior: MatchPrior,
        configuration: _Configuration,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
    ) -> tuple[CorrespondenceRecord, ...]:
        loaded = self._load()
        groups = self._model_groups(loaded)
        source_valid = _valid_mask(source_mask, source.shape)
        reference_valid = _valid_mask(reference_mask, reference.shape)
        source_groups = _channel_groups(source, source_valid, groups=groups)
        reference_groups = _channel_groups(reference, reference_valid, groups=groups)
        prior_flow = _dense_prior(prior, source.shape)
        flow, log_variance = self._run_model(
            loaded.value, source_groups, reference_groups, prior_flow, source.shape
        )
        candidates = self._candidates(
            flow,
            log_variance,
            source_valid=source_valid,
            reference_valid=reference_valid,
            prior=prior,
            stride=configuration.candidate_stride_px,
        )
        selected = heapq.nsmallest(
            configuration.max_candidates,
            candidates,
            key=lambda candidate: (
                -candidate.raw_score,
                candidate.source_line,
                candidate.source_sample,
            ),
        )
        algorithm_version = self._algorithm_version(loaded, groups)
        source_mask_identity = _mask_identity(source_mask)
        reference_mask_identity = _mask_identity(reference_mask)
        prior_identity = _prior_identity(prior)
        records: list[CorrespondenceRecord] = []
        for candidate in selected:
            source_pixel = SourcePixel(
                line=float(candidate.source_line), sample=float(candidate.source_sample)
            )
            observed_displacement = (
                candidate.reference_line - source_pixel.line,
                candidate.reference_sample - source_pixel.sample,
            )
            prior_displacement = prior.displacement_at(source_pixel)
            covariance = _covariance_from_log_variance(candidate.log_variance)
            records.append(
                CorrespondenceRecord(
                    match_id=digest_json(
                        {
                            "algorithm": _ALGORITHM,
                            "algorithm_version": algorithm_version,
                            "input_digest": input_digest,
                            "reference_digest": reference_digest,
                            "parameter_set_digest": parameters.parameter_set_digest,
                            "job_id": job_id,
                            "source_line": candidate.source_line,
                            "source_sample": candidate.source_sample,
                            "reference_line": candidate.reference_line,
                            "reference_sample": candidate.reference_sample,
                            "prior": prior_identity,
                            "source_mask_identity": source_mask_identity,
                            "reference_mask_identity": reference_mask_identity,
                        }
                    ),
                    job_id=job_id,
                    algorithm=_ALGORITHM,
                    algorithm_version=algorithm_version,
                    selection_reason=(
                        "bounded dense-flow candidate ranked by uncalibrated model log variance"
                    ),
                    source_pixel=source_pixel,
                    reference_pixel=ReferencePixel(
                        line=candidate.reference_line, sample=candidate.reference_sample
                    ),
                    raw_score=candidate.raw_score,
                    calibrated_confidence=(
                        self._confidence_calibration.confidence_for(candidate.log_variance)
                        if self._confidence_calibration is not None
                        else None
                    ),
                    prior_displacement_px=prior_displacement,
                    residual_from_prior_px=prior.residual_at(source_pixel, observed_displacement),
                    local_warp_jacobian=prior.local_warp_jacobian,
                    covariance=covariance,
                    covariance_method=(
                        "model_log_variance_uncalibrated" if covariance is not None else None
                    ),
                    covariance_calibrated=False,
                    is_candidate=True,
                    point_role=PointRole.CANDIDATE,
                    input_digest=input_digest,
                    reference_digest=reference_digest,
                    parameter_set_digest=parameters.parameter_set_digest,
                )
            )
        return tuple(records)

    def _load(self) -> LoadedModel:
        if self._loaded is not None:
            return self._loaded
        try:
            loaded = load_local_model(
                "selene_matcher",
                registry=self._registry,
                version=self._model_version,
                device=self._device,
            )
        except Exception as error:
            raise LearnedMatcherLoadError(f"learned matcher model load failed: {error}") from error
        self._loaded = loaded
        return loaded

    @staticmethod
    def _model_groups(loaded: LoadedModel) -> int:
        groups = getattr(loaded.value, "groups", None)
        if (
            isinstance(groups, bool)
            or not isinstance(groups, int)
            or not 1 <= groups <= _MAX_CHANNEL_GROUPS
        ):
            raise LearnedMatcherInferenceError(
                "learned matcher inference failed: model groups must be an integer from 1 through 5"
            )
        declared_groups = loaded.artifact.metadata.get("groups")
        if declared_groups is not None and declared_groups != groups:
            raise LearnedMatcherInferenceError(
                "learned matcher inference failed: artifact metadata groups do not match "
                "model groups"
            )
        return groups

    def _run_model(
        self,
        model: Any,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        prior_flow: npt.NDArray[np.float64],
        shape: tuple[int, int],
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        try:
            try:
                import torch
            except ImportError:
                outputs = model(source, reference, prior_flow)
            else:
                source_tensor = torch.from_numpy(
                    source.astype(np.float32, copy=False)
                ).to(self._device)
                reference_tensor = torch.from_numpy(reference.astype(np.float32, copy=False)).to(
                    self._device
                )
                prior_tensor = torch.from_numpy(
                    prior_flow.astype(np.float32, copy=False)
                ).to(self._device)
                with torch.no_grad():
                    outputs = model(source_tensor, reference_tensor, prior_tensor)
            if not isinstance(outputs, tuple) or len(outputs) != 2:
                raise LearnedMatcherInferenceError(
                    "learned matcher inference failed: model must return (flow, log_variance)"
                )
            flow = _as_numpy_output(outputs[0], name="flow")
            log_variance = _as_numpy_output(outputs[1], name="log_variance")
        except LearnedMatcherInferenceError:
            raise
        except Exception as error:
            raise LearnedMatcherInferenceError(
                f"learned matcher inference failed: model invocation raised {type(error).__name__}"
            ) from error
        expected_flow_shape = (1, 2, *shape)
        expected_variance_shape = (1, 1, *shape)
        if flow.shape != expected_flow_shape:
            raise LearnedMatcherInferenceError(
                "learned matcher inference failed: "
                f"flow shape must be {expected_flow_shape!r}, got {flow.shape!r}"
            )
        if log_variance.shape != expected_variance_shape:
            raise LearnedMatcherInferenceError(
                "learned matcher inference failed: "
                f"log_variance shape must be {expected_variance_shape!r}, "
                f"got {log_variance.shape!r}"
            )
        if not np.all(np.isfinite(flow)) or not np.all(np.isfinite(log_variance)):
            raise LearnedMatcherInferenceError(
                "learned matcher inference failed: model outputs must be finite"
            )
        return flow, log_variance

    @staticmethod
    def _candidates(
        flow: npt.NDArray[np.float64],
        log_variance: npt.NDArray[np.float64],
        *,
        source_valid: npt.NDArray[np.bool_],
        reference_valid: npt.NDArray[np.bool_],
        prior: MatchPrior,
        stride: int,
    ) -> Iterable[_Candidate]:
        """Yield only candidates with mask support at their nearest pixel centre.

        A floating reference coordinate is supported when it rounds half away
        from zero to a pixel centre inside the reference image:
        ``(-0.5, extent - 0.5)``.  Flow
        outside that support is a non-candidate, rather than an inference-wide
        failure, because other pixels in the dense field can still be valid.
        """
        height, width = source_valid.shape
        for source_line in range(0, height, stride):
            for source_sample in range(0, width, stride):
                if not source_valid[source_line, source_sample]:
                    continue
                reference_line = source_line + float(flow[0, 0, source_line, source_sample])
                reference_sample = source_sample + float(flow[0, 1, source_line, source_sample])
                source_pixel = SourcePixel(line=float(source_line), sample=float(source_sample))
                prior_dy_px, prior_dx_px = prior.displacement_at(source_pixel)
                if prior.search_radius_px is not None and (
                    (reference_line - source_line - prior_dy_px) ** 2
                    + (reference_sample - source_sample - prior_dx_px) ** 2
                    > prior.search_radius_px**2
                ):
                    continue
                if not (
                    -0.5 < reference_line < height - 0.5
                    and -0.5 < reference_sample < width - 0.5
                ):
                    continue
                nearest_line = _nearest_index(reference_line)
                nearest_sample = _nearest_index(reference_sample)
                if not (0 <= nearest_line < height and 0 <= nearest_sample < width):
                    continue
                if not reference_valid[nearest_line, nearest_sample]:
                    continue
                yield _Candidate(
                    source_line=source_line,
                    source_sample=source_sample,
                    reference_line=reference_line,
                    reference_sample=reference_sample,
                    log_variance=float(log_variance[0, 0, source_line, source_sample]),
                )

    def _algorithm_version(self, loaded: LoadedModel, groups: int) -> str:
        calibration = (
            self._confidence_calibration.contract_id
            if self._confidence_calibration is not None
            else "none"
        )
        return (
            f"adapter={_ADAPTER_VERSION}; artifact={loaded.artifact.version}; "
            f"artifact_sha256={loaded.artifact.sha256}; groups={groups}; "
            f"channel_policy={_CHANNEL_POLICY_VERSION}; confidence_contract={calibration}"
        )

    def _fallback_or_raise(
        self,
        error: LearnedMatcherLoadError | LearnedMatcherInputError | LearnedMatcherInferenceError,
        *,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        source_mask: npt.NDArray[np.bool_] | None,
        reference_mask: npt.NDArray[np.bool_] | None,
        prior: MatchPrior,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
        fallback_parameters: MatchParameters | None,
    ) -> tuple[CorrespondenceRecord, ...]:
        if self._fallback is None:
            raise error
        records = self._fallback.match(
            source,
            reference,
            source_mask=source_mask,
            reference_mask=reference_mask,
            prior=prior,
            parameters=fallback_parameters or parameters,
            job_id=job_id,
            input_digest=input_digest,
            reference_digest=reference_digest,
        )
        return tuple(self._fallback_record(record, error) for record in records)

    @staticmethod
    def _fallback_record(
        record: CorrespondenceRecord,
        error: LearnedMatcherLoadError | LearnedMatcherInputError | LearnedMatcherInferenceError,
    ) -> CorrespondenceRecord:
        original_reason = record.selection_reason or "no original selection reason was supplied"
        return record.model_copy(
            update={
                "algorithm": f"{record.algorithm}:fallback",
                "algorithm_version": (
                    f"original_algorithm={record.algorithm}@{record.algorithm_version}; "
                    f"learned_adapter={_ALGORITHM}; fallback_reason={error.fallback_label}"
                ),
                "selection_reason": f"fallback after {error.fallback_label}; {original_reason}",
            }
        )
