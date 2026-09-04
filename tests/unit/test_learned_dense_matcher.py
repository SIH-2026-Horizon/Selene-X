"""Tests for the compact, registry-backed grouped dense-flow matcher adapter."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from selene_core.match import (
    ConfidenceCalibration,
    GroupedDenseFlowMatcher,
    LearnedMatcherConfigurationError,
    LearnedMatcherInferenceError,
    LearnedMatcherInputError,
    LearnedMatcherLoadError,
    Matcher,
    MatchParameters,
    MatchPrior,
    NccMatcher,
)
from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.models import LoadedModel, LocalModelRegistry
from selene_core.types import LocalWarpJacobian, ReferencePixel, SourcePixel

pytestmark = pytest.mark.unit

_INPUT_DIGEST = "a" * 64
_REFERENCE_DIGEST = "b" * 64


def _as_numpy(value: Any) -> np.ndarray:
    """Accept the adapter's NumPy test path and a torch tensor when installed."""
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach().cpu().numpy()
    return np.asarray(value)


@dataclass
class _DeterministicDenseModel:
    """Small checkpoint substitute: return prior flow plus a fixed residual."""

    groups: int = 5
    residual_dy_dx: tuple[float, float] = (0.0, 0.0)
    log_variance: float = math.log(4.0)
    received_prior: np.ndarray | None = field(default=None, init=False)

    def __call__(
        self, source: Any, reference: Any, prior_flow: Any
    ) -> tuple[np.ndarray, np.ndarray]:
        del source, reference
        prior = _as_numpy(prior_flow).astype(np.float64, copy=True)
        self.received_prior = prior
        prior[:, 0] += self.residual_dy_dx[0]
        prior[:, 1] += self.residual_dy_dx[1]
        log_variance = np.full((1, 1, *prior.shape[-2:]), self.log_variance, dtype=np.float64)
        return prior, log_variance


@dataclass
class _SpyFallback:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def match(
        self, source: np.ndarray, reference: np.ndarray, **kwargs: Any
    ) -> tuple[CorrespondenceRecord, ...]:
        self.calls.append({"source": source, "reference": reference, **kwargs})
        return (
            CorrespondenceRecord(
                job_id=str(kwargs["job_id"]),
                algorithm="fallback_classical",
                algorithm_version="9.1",
                source_pixel=SourcePixel(line=1.0, sample=1.0),
                reference_pixel=ReferencePixel(line=1.0, sample=1.0),
                raw_score=0.75,
                input_digest=str(kwargs["input_digest"]),
                reference_digest=str(kwargs["reference_digest"]),
                parameter_set_digest=kwargs["parameters"].parameter_set_digest,
            ),
        )


class _FailingDenseModel(_DeterministicDenseModel):
    def __call__(
        self, source: Any, reference: Any, prior_flow: Any
    ) -> tuple[np.ndarray, np.ndarray]:
        del source, reference, prior_flow
        raise RuntimeError("synthetic inference failure")


@dataclass
class _FixedFlowDenseModel:
    """Return a dense field independent of the model input prior."""

    flow_dy_dx: tuple[float, float]
    groups: int = 5
    log_variance: float = math.log(4.0)

    def __call__(
        self, source: Any, reference: Any, prior_flow: Any
    ) -> tuple[np.ndarray, np.ndarray]:
        del source, reference
        prior = _as_numpy(prior_flow)
        flow = np.empty_like(prior, dtype=np.float64)
        flow[:, 0] = self.flow_dy_dx[0]
        flow[:, 1] = self.flow_dy_dx[1]
        log_variance = np.full((1, 1, *prior.shape[-2:]), self.log_variance, dtype=np.float64)
        return flow, log_variance


def _write_registry(root: Path) -> LocalModelRegistry:
    artifact = root / "selene_matcher" / "test" / "weights.pt"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"deterministic-test-artifact")
    document = {
        "schema_version": "1.0.0",
        "models": {
            "selene_matcher": {
                "active_version": "test",
                "versions": {
                    "test": {
                        "path": "selene_matcher/test/weights.pt",
                        "format": "pytorch_state_dict",
                        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                        "metadata": {"groups": 5},
                    }
                },
            }
        },
    }
    (root / "registry.json").write_text(json.dumps(document), encoding="utf-8")
    return LocalModelRegistry(root)


def _install_registry_backed_fake_loader(
    monkeypatch: pytest.MonkeyPatch,
    model_registry: LocalModelRegistry,
    model: Any,
) -> None:
    import selene_core.match.learned as learned

    def loader(
        model_name: str,
        *,
        registry: LocalModelRegistry | None = None,
        version: str | None = None,
        device: str = "cpu",
    ) -> LoadedModel:
        del device
        assert model_name == "selene_matcher"
        selected_registry = registry or model_registry
        assert selected_registry is not None
        artifact = selected_registry.resolve(model_name, version=version, verify=True)
        return LoadedModel(artifact=artifact, value=model)

    monkeypatch.setattr(learned, "load_local_model", loader)


def _inputs() -> tuple[np.ndarray, np.ndarray]:
    source = np.arange(36, dtype=np.float64).reshape(6, 6)
    return source, source.copy()


def _parameters() -> MatchParameters:
    return MatchParameters(values={"candidate_stride_px": 2, "max_candidates": 12})


def _match(matcher: GroupedDenseFlowMatcher, **overrides: Any) -> tuple[CorrespondenceRecord, ...]:
    source, reference = _inputs()
    arguments: dict[str, Any] = {
        "source_mask": None,
        "reference_mask": None,
        "prior": MatchPrior(),
        "parameters": _parameters(),
        "job_id": "learned-job",
        "input_digest": _INPUT_DIGEST,
        "reference_digest": _REFERENCE_DIGEST,
    }
    arguments.update(overrides)
    return matcher.match(source, reference, **arguments)


def test_registry_backed_inference_emits_canonical_uncalibrated_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    model = _DeterministicDenseModel()
    _install_registry_backed_fake_loader(monkeypatch, registry, model)
    matcher = GroupedDenseFlowMatcher(registry=registry)

    records = _match(matcher)

    assert isinstance(matcher, Matcher)
    assert len(records) == 9
    first = records[0]
    assert first.algorithm == "selene_matcher_grouped_dense_flow"
    assert "artifact=test" in first.algorithm_version
    assert "channel_policy=normalized-image-v1" in first.algorithm_version
    assert first.source_pixel == SourcePixel(line=0.0, sample=0.0)
    assert first.reference_pixel == ReferencePixel(line=0.0, sample=0.0)
    assert first.raw_score == pytest.approx(-math.log(4.0))
    assert first.calibrated_confidence is None
    assert first.covariance is not None
    assert first.covariance.xx == pytest.approx(4.0)
    assert first.covariance_method == "model_log_variance_uncalibrated"
    assert not first.covariance_calibrated
    assert first.is_candidate
    assert first.point_role is PointRole.CANDIDATE
    assert first.input_digest == _INPUT_DIGEST
    assert first.reference_digest == _REFERENCE_DIGEST


def test_dense_prior_uses_nonzero_translation_and_local_jacobian(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    model = _DeterministicDenseModel()
    _install_registry_backed_fake_loader(monkeypatch, registry, model)
    matcher = GroupedDenseFlowMatcher(registry=registry)
    prior = MatchPrior(
        displacement_px=(0.1, 0.1),
        local_warp_jacobian=LocalWarpJacobian(1.1, 0.0, 0.0, 1.1),
        anchor_source_pixel=SourcePixel(line=0.0, sample=0.0),
    )

    records = _match(matcher, prior=prior)

    record = next(item for item in records if item.source_pixel == SourcePixel(2.0, 2.0))
    expected = prior.displacement_at(record.source_pixel)
    assert record.prior_displacement_px == pytest.approx(expected)
    assert record.reference_pixel.line == pytest.approx(record.source_pixel.line + expected[0])
    assert record.reference_pixel.sample == pytest.approx(record.source_pixel.sample + expected[1])
    assert record.residual_from_prior_px == pytest.approx((0.0, 0.0))
    assert model.received_prior is not None
    assert tuple(model.received_prior[0, :, 2, 2]) == pytest.approx(expected)


def test_masks_exclude_invalid_source_and_predicted_reference_pixels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _DeterministicDenseModel())
    matcher = GroupedDenseFlowMatcher(registry=registry)
    source_mask = np.ones((6, 6), dtype=np.bool_)
    reference_mask = np.ones((6, 6), dtype=np.bool_)
    source_mask[0, 0] = False
    reference_mask[2, 2] = False

    records = _match(matcher, source_mask=source_mask, reference_mask=reference_mask)

    coordinates = {(item.source_pixel.line, item.source_pixel.sample) for item in records}
    assert (0.0, 0.0) not in coordinates
    assert (2.0, 2.0) not in coordinates
    assert all(
        reference_mask[int(item.reference_pixel.line), int(item.reference_pixel.sample)]
        for item in records
    )


def test_explicit_calibration_contract_is_the_only_source_of_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _DeterministicDenseModel())
    matcher = GroupedDenseFlowMatcher(
        registry=registry,
        confidence_calibration=ConfidenceCalibration(
            contract_id="validation-contract-7", log_variance_offset=0.0, scale=1.0
        ),
    )

    records = _match(matcher)

    assert records[0].calibrated_confidence == pytest.approx(0.2)
    assert not records[0].covariance_calibrated
    assert "confidence_contract=validation-contract-7" in records[0].algorithm_version


def test_missing_artifact_raises_a_stable_adapter_error(tmp_path: Path) -> None:
    matcher = GroupedDenseFlowMatcher(registry=LocalModelRegistry(tmp_path))

    with pytest.raises(LearnedMatcherLoadError, match=r"^learned matcher model load failed:"):
        _match(matcher)


def test_checksum_mismatch_is_not_loaded_as_an_unverified_model(tmp_path: Path) -> None:
    registry = _write_registry(tmp_path)
    artifact = tmp_path / "selene_matcher" / "test" / "weights.pt"
    artifact.write_bytes(b"modified-after-registry-write")
    matcher = GroupedDenseFlowMatcher(registry=registry)

    with pytest.raises(LearnedMatcherLoadError, match="checksum mismatch"):
        _match(matcher)


def test_invalid_input_is_rejected_before_model_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _DeterministicDenseModel())
    matcher = GroupedDenseFlowMatcher(registry=registry)
    source, reference = _inputs()

    with pytest.raises(LearnedMatcherInputError, match="source must have dtype float64"):
        matcher.match(
            source.astype(np.float32),
            reference,
            source_mask=None,
            reference_mask=None,
            prior=MatchPrior(),
            parameters=_parameters(),
            job_id="learned-job",
            input_digest=_INPUT_DIGEST,
            reference_digest=_REFERENCE_DIGEST,
        )


def test_explicit_fallback_receives_original_arguments_and_marks_provenance(tmp_path: Path) -> None:
    fallback = _SpyFallback()
    matcher = GroupedDenseFlowMatcher(registry=LocalModelRegistry(tmp_path), fallback=fallback)
    source, reference = _inputs()
    parameters = _parameters()
    prior = MatchPrior(displacement_px=(1.0, -1.0))

    records = matcher.match(
        source,
        reference,
        source_mask=None,
        reference_mask=None,
        prior=prior,
        parameters=parameters,
        job_id="fallback-job",
        input_digest=_INPUT_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )

    assert len(fallback.calls) == 1
    assert fallback.calls[0]["source"] is source
    assert fallback.calls[0]["reference"] is reference
    assert fallback.calls[0]["prior"] is prior
    assert fallback.calls[0]["parameters"] is parameters
    assert records[0].algorithm == "fallback_classical:fallback"
    assert "original_algorithm=fallback_classical@9.1" in records[0].algorithm_version
    assert "learned_adapter=selene_matcher_grouped_dense_flow" in records[0].algorithm_version
    assert "fallback after learned matcher load failure" in str(records[0].selection_reason)


def test_namespaced_fallback_parameters_drive_a_real_ncc_matcher(tmp_path: Path) -> None:
    fallback_parameters = {
        "grid_spacing_px": 2,
        "template_half_size_px": 1,
        "search_radius_px": 1,
    }
    parameters = MatchParameters(
        values={
            "candidate_stride_px": 2,
            "max_candidates": 12,
            "fallback_parameters": fallback_parameters,
        }
    )
    matcher = GroupedDenseFlowMatcher(
        registry=LocalModelRegistry(tmp_path),
        fallback=NccMatcher(),
    )

    records = _match(matcher, parameters=parameters)

    assert records
    assert all(record.algorithm == "normalized_cross_correlation:fallback" for record in records)
    expected_digest = MatchParameters(values=fallback_parameters).parameter_set_digest
    assert all(record.parameter_set_digest == expected_digest for record in records)


def test_prior_search_radius_rejects_dense_flow_residuals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(
        monkeypatch, registry, _DeterministicDenseModel(residual_dy_dx=(1.0, 0.0))
    )
    matcher = GroupedDenseFlowMatcher(registry=registry)

    records = _match(matcher, prior=MatchPrior(search_radius_px=0.5))

    assert records == ()


def test_prior_radius_uses_per_pixel_local_jacobian_in_line_sample_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _FixedFlowDenseModel((1.0, 0.0)))
    matcher = GroupedDenseFlowMatcher(registry=registry)
    prior = MatchPrior(
        displacement_px=(0.0, 0.0),
        search_radius_px=0.01,
        local_warp_jacobian=LocalWarpJacobian(1.0, 0.5, 0.0, 1.0),
        anchor_source_pixel=SourcePixel(line=0.0, sample=0.0),
    )

    records = _match(matcher, prior=prior)

    source_coordinates = {
        (record.source_pixel.line, record.source_pixel.sample) for record in records
    }
    assert (0.0, 2.0) in source_coordinates
    assert (2.0, 0.0) not in source_coordinates
    accepted = next(record for record in records if record.source_pixel == SourcePixel(0.0, 2.0))
    assert accepted.prior_displacement_px == pytest.approx((1.0, 0.0))


def test_match_identity_changes_for_parameters_priors_and_masks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _DeterministicDenseModel())
    matcher = GroupedDenseFlowMatcher(registry=registry)

    baseline = _match(matcher)
    changed_parameters = _match(
        matcher,
        parameters=MatchParameters(values={"candidate_stride_px": 2, "max_candidates": 11}),
    )
    changed_prior = _match(matcher, prior=MatchPrior(displacement_px=(0.1, 0.0)))
    source_mask = np.ones((6, 6), dtype=np.bool_)
    source_mask[5, 5] = False
    changed_mask = _match(matcher, source_mask=source_mask)

    def first_at_origin(records: tuple[CorrespondenceRecord, ...]) -> CorrespondenceRecord:
        return next(record for record in records if record.source_pixel == SourcePixel(0.0, 0.0))

    baseline_origin = first_at_origin(baseline)
    assert baseline_origin.match_id != first_at_origin(changed_parameters).match_id
    assert baseline_origin.match_id != first_at_origin(changed_prior).match_id
    assert baseline_origin.match_id != first_at_origin(changed_mask).match_id
    assert baseline_origin.reference_pixel != first_at_origin(changed_prior).reference_pixel


def test_mask_aware_channel_derivatives_do_not_leak_through_invalid_holes() -> None:
    import selene_core.match.learned as learned

    valid = np.ones((5, 5), dtype=np.bool_)
    valid[2, 2] = False
    constant = np.full((5, 5), 7.0, dtype=np.float64)
    constant_channels = learned._channel_groups(constant, valid, groups=5)
    assert np.all(constant_channels[0, 1:4] == 0.0)

    ramp = np.tile(np.arange(5, dtype=np.float64), (5, 1))
    channels = learned._channel_groups(ramp, valid, groups=5)
    # The sample-derivative stencils centred immediately beside the hole are
    # incomplete and must not be created by treating that invalid input as zero.
    assert channels[0, 2, 2, 1] == 0.0
    assert channels[0, 2, 2, 3] == 0.0


def test_bounded_top_k_selection_is_deterministic_and_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _DeterministicDenseModel())
    matcher = GroupedDenseFlowMatcher(registry=registry)
    source = np.arange(100, dtype=np.float64).reshape(10, 10)
    parameters = MatchParameters(values={"candidate_stride_px": 1, "max_candidates": 3})

    first = matcher.match(
        source,
        source.copy(),
        source_mask=None,
        reference_mask=None,
        prior=MatchPrior(),
        parameters=parameters,
        job_id="top-k-job",
        input_digest=_INPUT_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )
    second = matcher.match(
        source,
        source.copy(),
        source_mask=None,
        reference_mask=None,
        prior=MatchPrior(),
        parameters=parameters,
        job_id="top-k-job",
        input_digest=_INPUT_DIGEST,
        reference_digest=_REFERENCE_DIGEST,
    )

    assert len(first) == 3
    assert [(record.source_pixel.line, record.source_pixel.sample) for record in first] == [
        (0.0, 0.0),
        (0.0, 1.0),
        (0.0, 2.0),
    ]
    assert [record.match_id for record in first] == [record.match_id for record in second]


def test_inference_failure_uses_the_same_explicit_fallback_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _FailingDenseModel())
    fallback = _SpyFallback()
    matcher = GroupedDenseFlowMatcher(registry=registry, fallback=fallback)

    records = _match(matcher)

    assert len(fallback.calls) == 1
    assert records[0].algorithm.endswith(":fallback")
    assert "fallback after learned matcher inference failure" in str(records[0].selection_reason)

    strict_matcher = GroupedDenseFlowMatcher(registry=registry)
    with pytest.raises(LearnedMatcherInferenceError, match="model invocation raised RuntimeError"):
        _match(strict_matcher)


def test_fractional_near_edge_flow_skips_unsupported_pixels_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(
        monkeypatch,
        registry,
        _DeterministicDenseModel(residual_dy_dx=(1.75, 0.0)),
    )
    fallback = _SpyFallback()
    fallback_matcher = GroupedDenseFlowMatcher(registry=registry, fallback=fallback)

    records = _match(fallback_matcher)

    assert fallback.calls == []
    assert records
    assert all(-0.5 < item.reference_pixel.line < 5.5 for item in records)
    assert all(item.source_pixel.line != 4.0 for item in records)

    strict_matcher = GroupedDenseFlowMatcher(registry=registry)
    strict_records = _match(strict_matcher)
    assert [(item.source_pixel, item.reference_pixel) for item in strict_records] == [
        (item.source_pixel, item.reference_pixel) for item in records
    ]


def test_exact_negative_half_pixel_flow_skips_only_unsupported_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(
        monkeypatch,
        registry,
        _DeterministicDenseModel(residual_dy_dx=(-0.5, 0.0)),
    )
    fallback = _SpyFallback()
    matcher = GroupedDenseFlowMatcher(registry=registry, fallback=fallback)

    records = _match(matcher)

    assert fallback.calls == []
    assert records
    assert all(record.source_pixel.line != 0.0 for record in records)
    assert all(-0.5 < record.reference_pixel.line < 5.5 for record in records)


def test_unknown_parameters_are_rejected_without_falling_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _write_registry(tmp_path)
    _install_registry_backed_fake_loader(monkeypatch, registry, _DeterministicDenseModel())
    fallback = _SpyFallback()
    matcher = GroupedDenseFlowMatcher(registry=registry, fallback=fallback)

    with pytest.raises(LearnedMatcherConfigurationError, match="unknown keys"):
        _match(
            matcher,
            parameters=MatchParameters(
                values={"candidate_stride_px": 2, "max_candidates": 12, "unrecorded_default": 1}
            ),
        )

    assert fallback.calls == []
