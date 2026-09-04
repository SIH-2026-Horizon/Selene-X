"""Unit tests for mask-safe structural feature channels."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pytest

from selene_core.features import (
    StructuralFeatureParameters,
    extract_gradient_magnitude,
    extract_gradient_orientation,
    extract_local_self_similarity,
    extract_phase_equivalent,
    extract_structural_features,
)

pytestmark = pytest.mark.unit


def test_gradient_convention_is_east_zero_and_south_half_pi() -> None:
    line, sample = np.indices((11, 11), dtype=np.float64)

    east = extract_gradient_orientation(sample)
    south = extract_gradient_orientation(line)
    magnitude = extract_gradient_magnitude(sample)

    assert east.valid_mask[5, 5]
    assert south.valid_mask[5, 5]
    assert east.values[5, 5] == pytest.approx(0.0)
    assert south.values[5, 5] == pytest.approx(np.pi / 2.0)
    assert magnitude.valid_mask[5, 5]
    assert magnitude.values[5, 5] == pytest.approx(1.0)


def test_phase_equivalent_response_is_invariant_to_additive_offset() -> None:
    line, sample = np.indices((13, 15), dtype=np.float64)
    image = np.sin(line * 0.8) + np.cos(sample * 0.65)

    baseline = extract_phase_equivalent(image)
    shifted = extract_phase_equivalent(image + 1234.5)

    assert np.array_equal(baseline.valid_mask, shifted.valid_mask)
    assert np.allclose(
        baseline.values[baseline.valid_mask], shifted.values[shifted.valid_mask], atol=1e-12
    )


def test_channels_are_bounded_finite_aligned_and_record_provenance() -> None:
    line, sample = np.indices((15, 16), dtype=np.float64)
    image = np.sin(line) + np.cos(sample)

    result = extract_structural_features(image)

    assert set(result.channels) == {
        "gradient_magnitude",
        "gradient_orientation",
        "phase_equivalent",
        "local_self_similarity",
    }
    assert isinstance(result.channels, Mapping)
    for channel in result.channels.values():
        assert channel.values.shape == image.shape == channel.valid_mask.shape
        assert channel.values.dtype == np.float64
        assert channel.valid_mask.dtype == np.bool_
        assert np.all(np.isfinite(channel.values))
        assert np.all(channel.values >= channel.value_range[0])
        assert np.all(channel.values <= channel.value_range[1])
        assert channel.parameters["algorithm_version"] == channel.algorithm_version
        assert channel.parameters["invalid_fill_value"] == 0.0
    with pytest.raises(TypeError):
        result.channels["other"] = result.channels["gradient_magnitude"]  # type: ignore[index]


def test_masked_gap_and_border_fail_closed_without_value_leakage() -> None:
    line, sample = np.indices((17, 17), dtype=np.float64)
    image = line + sample
    mask = np.ones(image.shape, dtype=np.bool_)
    mask[:, 8] = False
    contaminated = image.copy()
    contaminated[:, 8] = 1e12

    clean = extract_structural_features(image, valid_mask=mask)
    result = extract_structural_features(contaminated, valid_mask=mask)

    for name, channel in result.channels.items():
        reference = clean.channels[name]
        assert not np.any(channel.valid_mask[:, 8])
        assert np.all(channel.values[~channel.valid_mask] == 0.0)
        assert not np.any(channel.valid_mask[0, :])
        assert not np.any(channel.valid_mask[-1, :])
        common = channel.valid_mask & reference.valid_mask
        assert np.array_equal(channel.valid_mask, reference.valid_mask)
        assert np.array_equal(channel.values[common], reference.values[common])


def test_gradient_and_phase_never_evaluate_masked_extremes() -> None:
    line, sample = np.indices((11, 11), dtype=np.float64)
    image = line + sample
    mask = np.ones(image.shape, dtype=np.bool_)
    mask[4, 4] = False
    mask[6, 7] = False
    contaminated = image.copy()
    contaminated[4, 4] = np.finfo(np.float64).max
    contaminated[6, 7] = -np.finfo(np.float64).max

    with np.errstate(all="raise"):
        clean = extract_structural_features(
            image,
            valid_mask=mask,
            channels=[
                "gradient_magnitude",
                "gradient_orientation",
                "phase_equivalent",
                "local_self_similarity",
            ],
        )
        result = extract_structural_features(
            contaminated,
            valid_mask=mask,
            channels=[
                "gradient_magnitude",
                "gradient_orientation",
                "phase_equivalent",
                "local_self_similarity",
            ],
        )

    for name, channel in result.channels.items():
        reference = clean.channels[name]
        assert np.array_equal(channel.valid_mask, reference.valid_mask)
        assert np.array_equal(channel.values, reference.values)


def test_fully_usable_finite_extremes_are_bounded_or_fail_closed() -> None:
    image = np.zeros((11, 11), dtype=np.float64)
    maximum = np.finfo(np.float64).max
    image[5, 5] = maximum
    image[4, 5] = -maximum
    image[6, 5] = maximum
    image[5, 4] = -maximum
    image[5, 6] = maximum

    with np.errstate(all="raise"):
        result = extract_structural_features(image)

    for channel in result.channels.values():
        assert np.all(np.isfinite(channel.values))
        assert np.all(channel.values >= channel.value_range[0])
        assert np.all(channel.values <= channel.value_range[1])


def test_mixed_maximum_and_subnormal_values_do_not_raise_underflow() -> None:
    line, sample = np.indices((15, 15), dtype=np.float64)
    maximum = np.finfo(np.float64).max
    image = np.where((line + sample) % 2 == 0, maximum, -maximum).astype(np.float64)
    image[7, 7] = np.nextafter(np.float64(0.0), np.float64(1.0))
    image[6:9, 6:9] = np.nextafter(np.float64(0.0), np.float64(1.0))

    with np.errstate(all="raise"):
        result = extract_structural_features(image)

    for channel in result.channels.values():
        assert np.all(np.isfinite(channel.values))
        assert np.all(channel.values >= channel.value_range[0])
        assert np.all(channel.values <= channel.value_range[1])


def test_full_bundle_handles_maximum_outlier_and_subnormal_sample() -> None:
    line, sample = np.indices((15, 15), dtype=np.float64)
    image = 1.0 + line + sample
    image[0, 0] = np.finfo(np.float64).max
    image[7, 7] = np.nextafter(np.float64(0.0), np.float64(1.0))

    with np.errstate(all="raise"):
        result = extract_structural_features(image)

    for channel in result.channels.values():
        assert np.all(np.isfinite(channel.values))
        assert np.all(channel.values >= channel.value_range[0])
        assert np.all(channel.values <= channel.value_range[1])


def test_distant_valid_extreme_does_not_change_unaffected_local_channels() -> None:
    line, sample = np.indices((25, 25), dtype=np.float64)
    image = np.sin(line * 0.31) + np.cos(sample * 0.43) + line * 0.05
    altered = image.copy()
    altered[0, 0] = np.finfo(np.float64).max
    target = (12, 12)

    with np.errstate(all="raise"):
        baseline = extract_structural_features(image)
        result = extract_structural_features(altered)

    for name, channel in result.channels.items():
        reference = baseline.channels[name]
        assert channel.valid_mask[target] == reference.valid_mask[target]
        assert channel.values[target] == reference.values[target]


def test_orientation_handles_random_mixed_extreme_components_without_underflow() -> None:
    generator = np.random.default_rng(7)
    image = generator.normal(size=(17, 17)).astype(np.float64)
    image[8, 8] = np.finfo(np.float64).max
    image[3, 13] = np.nextafter(np.float64(0.0), np.float64(1.0))

    with np.errstate(all="raise"):
        result = extract_gradient_orientation(image)

    assert np.all(np.isfinite(result.values))
    assert np.all(result.values >= result.value_range[0])
    assert np.all(result.values <= result.value_range[1])


def test_self_similarity_scores_repeated_patches_above_unique_structure() -> None:
    image = np.zeros((25, 25), dtype=np.float64)
    motif = np.array([[0.0, 1.0, 0.0], [1.0, 4.0, 1.0], [0.0, 1.0, 0.0]])
    image[8:11, 8:11] = motif
    image[8:11, 14:17] = motif
    image[15:18, 8:11] = np.array([[0.0, 2.0, 0.0], [3.0, 9.0, 2.0], [0.0, 1.0, 0.0]])
    parameters = StructuralFeatureParameters(patch_radius=1, search_radius=7)

    result = extract_local_self_similarity(image, parameters=parameters)

    assert result.valid_mask[9, 9]
    assert result.valid_mask[16, 9]
    assert result.values[9, 9] > result.values[16, 9]
    assert result.values[9, 9] == pytest.approx(1.0)


def test_self_similarity_requires_genuinely_non_overlapping_patch_offsets() -> None:
    with pytest.raises(ValueError, match="twice"):
        StructuralFeatureParameters(patch_radius=1, search_radius=2)

    image = np.arange(121, dtype=np.float64).reshape(11, 11)
    result = extract_local_self_similarity(
        image, parameters=StructuralFeatureParameters(patch_radius=1, search_radius=3)
    )

    assert result.valid_mask[5, 5]
    assert (
        result.parameters["candidate_offsets"]
        == "2*patch_radius < chebyshev_offset <= search_radius"
    )


@pytest.mark.parametrize(
    ("image", "mask", "parameters", "match"),
    [
        (np.ones((3, 3), dtype=np.float32), None, None, "float64"),
        (np.ones((3, 3, 1), dtype=np.float64), None, None, "2D"),
        (np.array([[np.nan]], dtype=np.float64), None, None, "finite"),
        (np.ones((3, 3), dtype=np.float64), np.ones((3, 3), dtype=np.int8), None, "boolean"),
    ],
)
def test_input_and_parameter_validation(image, mask, parameters, match) -> None:
    if match:
        with pytest.raises(ValueError, match=match):
            extract_structural_features(image, valid_mask=mask, parameters=parameters)
    with pytest.raises(ValueError, match="percentile"):
        StructuralFeatureParameters(gradient_percentile=0.0)
    with pytest.raises(ValueError, match="larger"):
        StructuralFeatureParameters(patch_radius=2, search_radius=2)


def test_channel_selection_is_independent_and_deterministic() -> None:
    image = np.arange(225, dtype=np.float64).reshape(15, 15)

    selected = extract_structural_features(
        image, channels=["gradient_magnitude", "phase_equivalent"]
    )
    first = extract_structural_features(image, channels=["phase_equivalent"])
    second = extract_structural_features(image, channels=["phase_equivalent"])

    assert set(selected.channels) == {"gradient_magnitude", "phase_equivalent"}
    assert set(first.channels) == {"phase_equivalent"}
    assert np.array_equal(
        first.channels["phase_equivalent"].values,
        second.channels["phase_equivalent"].values,
    )
    assert np.array_equal(
        first.channels["phase_equivalent"].valid_mask,
        second.channels["phase_equivalent"].valid_mask,
    )
    with pytest.raises(ValueError, match="unknown"):
        extract_structural_features(image, channels=["unknown"])
