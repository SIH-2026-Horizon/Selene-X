"""Tests for conservative, mask-safe source dark/shadow estimation."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pytest

from selene_core.features import (
    FeatureChannel,
    ShadowEstimate,
    ShadowEstimationParameters,
    estimate_source_shadows,
)

pytestmark = pytest.mark.unit


def _scene_with_dark_core_and_penumbra() -> np.ndarray:
    image = np.full((20, 20), 0.72, dtype=np.float64)
    image += np.indices(image.shape, dtype=np.float64)[0] * 0.001
    image[2:7, 2:7] = 0.10
    image[2:7, 7:12] = 0.35
    return image


def _broad_normal_dark_terrain() -> np.ndarray:
    """A textured dark terrain distribution without a separated dark mode."""
    line, sample = np.indices((40, 40), dtype=np.float64)
    return 0.18 + 0.025 * np.sin(line * 0.31) + 0.018 * np.cos(sample * 0.23)


def _two_level_scene(dark_count: int) -> np.ndarray:
    image = np.ones((10, 10), dtype=np.float64)
    image.flat[:dark_count] = 0.0
    return image


def test_clear_dark_region_is_conservative_candidate_not_normal_bright_terrain() -> None:
    result = estimate_source_shadows(_scene_with_dark_core_and_penumbra())

    assert np.all(result.shadow_mask[2:7, 2:7])
    assert not np.any(result.shadow_mask[10:, 10:])
    assert result.provenance["status"] == "ok"
    assert np.all(result.confidence.values[result.shadow_mask] == 1.0)


def test_penumbra_is_separate_from_shadow_and_has_nonbinary_confidence() -> None:
    result = estimate_source_shadows(_scene_with_dark_core_and_penumbra())

    assert np.all(result.penumbra_mask[2:7, 7:12])
    assert not np.any(result.shadow_mask & result.penumbra_mask)
    penumbra_confidence = result.confidence.values[result.penumbra_mask]
    assert np.all((0.0 < penumbra_confidence) & (penumbra_confidence < 1.0))


def test_broad_normal_dark_terrain_is_not_claimed_as_confident_shadow() -> None:
    result = estimate_source_shadows(_broad_normal_dark_terrain())

    assert not np.any(result.shadow_mask)
    assert result.provenance["status"] == "no_confident_shadow:no_separated_dark_tail"


def test_quantile_boundary_bright_tie_plateau_is_not_promoted() -> None:
    image = _two_level_scene(10)
    result = estimate_source_shadows(image)

    assert np.count_nonzero(result.shadow_mask) == 10
    assert not np.any(result.shadow_mask[image == 1.0])
    assert not np.any(result.penumbra_mask[image == 1.0])
    selection = result.provenance["selection"]
    assert isinstance(selection, Mapping)
    assert selection["semantics"] == (
        "include_global_minimum_plateau_when_quantile_equals_minimum;"
        "otherwise_strictly_below_quantile_to_avoid_boundary_tie_expansion"
    )


def test_compact_one_percent_dark_mode_is_detected_conservatively() -> None:
    image = _two_level_scene(1)
    result = estimate_source_shadows(image)

    assert result.shadow_mask[0, 0]
    assert np.count_nonzero(result.shadow_mask) == 1
    assert not np.any(result.shadow_mask[image == 1.0])


def test_masked_extremes_and_gaps_never_contaminate_or_become_candidates() -> None:
    image = _scene_with_dark_core_and_penumbra()
    usable = np.ones(image.shape, dtype=np.bool_)
    usable[8:12, 8:12] = False
    contaminated = image.copy()
    contaminated[~usable] = -1.0e300

    clean = estimate_source_shadows(image, usable_mask=usable)
    result = estimate_source_shadows(contaminated, usable_mask=usable)

    assert np.array_equal(clean.shadow_mask, result.shadow_mask)
    assert np.array_equal(clean.penumbra_mask, result.penumbra_mask)
    assert not np.any(result.usable_mask[~usable])
    assert not np.any(result.shadow_mask[~usable])
    assert not np.any(result.penumbra_mask[~usable])
    assert not np.any(result.confidence.valid_mask[~usable])
    assert np.all(result.confidence.values[~usable] == 0.0)


@pytest.mark.parametrize(
    "image",
    [
        np.full((12, 12), 3.0, dtype=np.float64),
        np.linspace(1.0, 1.000001, 144, dtype=np.float64).reshape(12, 12),
    ],
)
def test_constant_or_low_contrast_scene_emits_no_confident_shadow_with_reason(
    image: np.ndarray,
) -> None:
    result = estimate_source_shadows(image)

    assert not np.any(result.shadow_mask)
    assert str(result.provenance["status"]).startswith("no_confident_shadow:")


def test_positive_affine_radiometry_preserves_masks_and_confidence() -> None:
    image = _scene_with_dark_core_and_penumbra()
    baseline = estimate_source_shadows(image)
    transformed = estimate_source_shadows(image * 7.25 + 42.0)

    assert np.array_equal(baseline.usable_mask, transformed.usable_mask)
    assert np.array_equal(baseline.shadow_mask, transformed.shadow_mask)
    assert np.array_equal(baseline.penumbra_mask, transformed.penumbra_mask)
    assert np.allclose(baseline.confidence.values, transformed.confidence.values, atol=1e-12)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"dark_percentile": 0.0}, "dark_percentile"),
        ({"penumbra_percentile": 50.0}, "penumbra_percentile"),
        ({"dark_percentile": 10.0, "penumbra_percentile": 10.0}, "larger"),
        ({"shadow_mad_multiplier": 0.0}, "shadow_mad_multiplier"),
        ({"min_tail_gap_fraction": 1.1}, "min_tail_gap_fraction"),
        ({"min_valid_count": 0}, "min_valid_count"),
    ],
)
def test_parameter_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ShadowEstimationParameters(**kwargs)  # type: ignore[arg-type]


def test_input_alignment_bounds_immutability_and_determinism() -> None:
    image = _scene_with_dark_core_and_penumbra()
    first = estimate_source_shadows(image)
    second = estimate_source_shadows(image)

    assert first.usable_mask.shape == image.shape
    assert first.shadow_mask.shape == image.shape
    assert first.penumbra_mask.shape == image.shape
    assert first.confidence.values.shape == image.shape
    assert first.confidence.value_range == (0.0, 1.0)
    assert np.all(np.isfinite(first.confidence.values))
    assert np.all((0.0 <= first.confidence.values) & (first.confidence.values <= 1.0))
    assert np.array_equal(first.shadow_mask, second.shadow_mask)
    assert np.array_equal(first.penumbra_mask, second.penumbra_mask)
    assert np.array_equal(first.confidence.values, second.confidence.values)
    assert isinstance(first.provenance, Mapping)
    thresholds = first.provenance["thresholds_normalized"]
    assert isinstance(thresholds, Mapping)
    assert set(thresholds) == {
        "shadow",
        "penumbra",
        "shadow_selection",
        "next_after_shadow",
        "median",
        "mad",
        "high_percentile_95",
        "dark_separation",
        "tail_gap",
        "dark_mode_gap",
        "distribution_span",
    }
    assert all(isinstance(value, float) and np.isfinite(value) for value in thresholds.values())
    assert isinstance(first.provenance["normalization_amplitude"], float)
    decision_state = first.provenance["decision_state"]
    assert decision_state == {"robust_tail": True, "discrete_tail": False}
    with pytest.raises(ValueError):
        first.shadow_mask[0, 0] = False
    with pytest.raises(ValueError):
        first.confidence.values[0, 0] = 0.0
    with pytest.raises(TypeError):
        first.provenance["status"] = "changed"  # type: ignore[index]
    parameters = first.provenance["parameters"]
    assert isinstance(parameters, Mapping)
    with pytest.raises(TypeError):
        parameters["dark_percentile"] = 99.0  # type: ignore[index]
    assert parameters["dark_percentile"] == 5.0
    with pytest.raises(TypeError):
        thresholds["shadow"] = 99.0  # type: ignore[index]
    assert thresholds["shadow"] != 99.0


@pytest.mark.parametrize(
    ("shadow_value", "penumbra_value", "background_value", "match"),
    [
        (0.0, 0.5, 0.0, "shadow cells"),
        (1.0, 0.0, 0.0, "penumbra cells"),
        (1.0, 1.0, 0.0, "penumbra cells"),
        (1.0, 0.5, 0.2, "non-candidate"),
    ],
)
def test_constructor_rejects_confidence_that_disagrees_with_masks(
    shadow_value: float, penumbra_value: float, background_value: float, match: str
) -> None:
    usable = np.ones((2, 2), dtype=np.bool_)
    shadow = np.zeros((2, 2), dtype=np.bool_)
    penumbra = np.zeros((2, 2), dtype=np.bool_)
    shadow[0, 0] = True
    penumbra[0, 1] = True
    confidence_values = np.full((2, 2), background_value, dtype=np.float64)
    confidence_values[0, 0] = shadow_value
    confidence_values[0, 1] = penumbra_value
    confidence = FeatureChannel(
        confidence_values,
        usable,
        "test",
        {},
        value_range=(0.0, 1.0),
    )

    with pytest.raises(ValueError, match=match):
        ShadowEstimate(usable, shadow, penumbra, confidence, {})


@pytest.mark.parametrize(
    ("image", "mask", "match"),
    [
        (np.ones((3, 3), dtype=np.float32), None, "float64"),
        (np.ones((3, 3, 1), dtype=np.float64), None, "2D"),
        (np.array([[np.nan]], dtype=np.float64), None, "finite"),
        (np.ones((3, 3), dtype=np.float64), np.ones((2, 2), dtype=np.bool_), "shape"),
        (np.ones((3, 3), dtype=np.float64), np.ones((3, 3), dtype=np.int8), "boolean"),
    ],
)
def test_input_validation(image: np.ndarray, mask: np.ndarray | None, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        estimate_source_shadows(image, usable_mask=mask)
