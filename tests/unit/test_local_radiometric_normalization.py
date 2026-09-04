"""Unit tests for the mask-safe local radiometric feature normalizer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import numpy as np
import numpy.typing as npt
import pytest

from selene_core.features import (
    FeatureChannel,
    LocalRadiometricNormalizationParameters,
    normalize_local_radiometry,
)

pytestmark = pytest.mark.unit


def _textured_image(shape: tuple[int, int] = (17, 19)) -> np.ndarray:
    line, sample = np.indices(shape, dtype=np.float64)
    return np.sin(line * 0.41) + np.cos(sample * 0.29) + line * 0.03


def test_normalization_is_invariant_to_positive_affine_radiometry() -> None:
    image = _textured_image()
    mask = np.ones(image.shape, dtype=np.bool_)
    parameters = LocalRadiometricNormalizationParameters(window_size=7)

    baseline = normalize_local_radiometry(image, valid_mask=mask, parameters=parameters)
    transformed = normalize_local_radiometry(
        image * 7.25 - 42.0,
        valid_mask=mask,
        parameters=parameters,
    )

    assert np.array_equal(baseline.valid_mask, transformed.valid_mask)
    assert np.allclose(
        baseline.values[baseline.valid_mask],
        transformed.values[transformed.valid_mask],
        atol=1e-12,
    )


def test_invalid_values_never_contribute_or_become_usable() -> None:
    image = _textured_image((15, 15))
    mask = np.ones(image.shape, dtype=np.bool_)
    mask[5:10, 5:10] = False
    contaminated = image.copy()
    contaminated[~mask] = 1e12
    parameters = LocalRadiometricNormalizationParameters(
        window_size=5, min_valid_fraction=0.5, min_valid_count=5
    )

    clean = normalize_local_radiometry(image, valid_mask=mask, parameters=parameters)
    result = normalize_local_radiometry(contaminated, valid_mask=mask, parameters=parameters)

    assert not np.any(result.valid_mask[~mask])
    assert np.all(result.values[~result.valid_mask] == 0.0)
    assert np.allclose(clean.values[clean.valid_mask], result.values[clean.valid_mask], atol=0.0)


def test_insufficient_local_support_is_invalid_without_interpolation() -> None:
    image = _textured_image((9, 9))
    mask = np.zeros(image.shape, dtype=np.bool_)
    mask[4, 4] = True
    parameters = LocalRadiometricNormalizationParameters(
        window_size=5, min_valid_fraction=0.5, min_valid_count=2
    )

    result = normalize_local_radiometry(image, valid_mask=mask, parameters=parameters)

    assert not result.valid_mask[4, 4]
    assert not np.any(result.valid_mask)
    assert np.all(result.values == 0.0)


def test_support_threshold_is_inclusive_at_the_minimum_valid_count() -> None:
    image = _textured_image((5, 5))
    mask = np.zeros(image.shape, dtype=np.bool_)
    mask[1:4, 2] = True
    mask[2, 1:4] = True
    parameters = LocalRadiometricNormalizationParameters(
        window_size=3, min_valid_fraction=0.5, min_valid_count=5
    )

    at_threshold = normalize_local_radiometry(image, valid_mask=mask, parameters=parameters)
    below_threshold_mask = mask.copy()
    below_threshold_mask[1, 2] = False
    below_threshold = normalize_local_radiometry(
        image, valid_mask=below_threshold_mask, parameters=parameters
    )

    assert at_threshold.valid_mask[2, 2]
    assert not below_threshold.valid_mask[2, 2]


@pytest.mark.parametrize(
    ("image", "mask", "parameters", "match"),
    [
        (np.ones((3, 3), dtype=np.float32), None, None, "float64"),
        (np.ones((3, 3, 1), dtype=np.float64), None, None, "2D"),
        (np.array([[np.nan]], dtype=np.float64), None, None, "finite"),
        (np.ones((3, 3), dtype=np.float64), np.ones((2, 2), dtype=np.bool_), None, "shape"),
        (np.ones((3, 3), dtype=np.float64), np.ones((3, 3), dtype=np.int8), None, "boolean"),
    ],
)
def test_input_and_parameter_validation(
    image: npt.NDArray[np.generic],
    mask: npt.NDArray[np.generic] | None,
    parameters: LocalRadiometricNormalizationParameters | None,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        normalize_local_radiometry(image, valid_mask=mask, parameters=parameters)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="odd"):
        LocalRadiometricNormalizationParameters(window_size=4)


def test_result_contract_is_immutable_and_records_resolved_provenance() -> None:
    image = _textured_image((9, 9))
    result = normalize_local_radiometry(image)

    assert result.values.dtype == np.float64
    assert result.valid_mask.dtype == np.bool_
    assert result.values.shape == image.shape == result.valid_mask.shape
    assert np.all(np.isfinite(result.values))
    valid_values = result.values[result.valid_mask]
    assert np.all((-1.0 <= valid_values) & (valid_values <= 1.0))
    assert result.algorithm_version == "1.0"
    assert result.parameters["window_size"] == 15
    assert result.parameters["invalid_fill_value"] == 0.0
    assert isinstance(result.parameters, Mapping)
    with pytest.raises(ValueError):
        result.values[0, 0] = 1.0
    with pytest.raises(TypeError):
        result.parameters["window_size"] = 3  # type: ignore[index]


def test_feature_channel_rejects_invalid_contracts() -> None:
    values = np.zeros((2, 2), dtype=np.float64)
    mask = np.ones((2, 2), dtype=np.bool_)

    with pytest.raises(ValueError, match="bounded"):
        FeatureChannel(values + 2.0, mask, "test", {"nested": {"a": 1}})
    with pytest.raises(ValueError, match="finite"):
        FeatureChannel(np.array([[np.nan, 0.0], [0.0, 0.0]]), mask, "test", {})
    with pytest.raises(ValueError, match="shape"):
        FeatureChannel(values, np.ones((1, 2), dtype=np.bool_), "test", {})
    with pytest.raises(ValueError, match="2-item"):
        FeatureChannel(values, mask, "test", {}, value_range=(-1.0, 0.0, 1.0))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="NumPy arrays"):
        FeatureChannel(values, mask, "test", {"numeric": np.array([1.0])})
    with pytest.raises(ValueError, match="NumPy arrays"):
        FeatureChannel(values, mask, "test", {"object": np.array([{}], dtype=object)})
    with pytest.raises(ValueError, match="unsupported"):
        FeatureChannel(values, mask, "test", {"mutable": bytearray(b"bad")})


def test_feature_channel_defensively_freezes_mutable_metadata() -> None:
    values = np.zeros((2, 2), dtype=np.float64)
    mask = np.ones((2, 2), dtype=np.bool_)
    bounds = np.array([-1.0, 1.0], dtype=np.float64)
    nested = {"labels": ["original"]}
    channel = FeatureChannel(
        values,
        mask,
        "test",
        {"nested": nested},
        value_range=bounds,  # type: ignore[arg-type]
    )

    bounds[0] = -99.0
    nested["labels"][0] = "mutated"

    assert channel.value_range == (-1.0, 1.0)
    stored_nested = cast(Mapping[str, object], channel.parameters["nested"])
    assert stored_nested["labels"] == ("original",)


def test_normalization_is_deterministic() -> None:
    image = _textured_image()
    mask = np.ones(image.shape, dtype=np.bool_)
    mask[3:6, 7:10] = False

    first = normalize_local_radiometry(image, valid_mask=mask)
    second = normalize_local_radiometry(image, valid_mask=mask)

    assert np.array_equal(first.values, second.values)
    assert np.array_equal(first.valid_mask, second.valid_mask)
    assert dict(first.parameters) == dict(second.parameters)
