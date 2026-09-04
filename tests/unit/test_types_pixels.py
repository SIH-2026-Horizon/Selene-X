"""Tests for pixel conventions and coordinate conversions.

Covers ADR-0001: pixel-centre convention enforcement and named conversions
between ISIS, GDAL, CSM, and array indexing conventions.
"""

import math

import pytest

from selene_core.types import (
    INTERNAL_PIXEL_CONVENTION,
    PixelConvention,
    ReferencePixel,
    SourcePixel,
    convert_pixel_coordinate,
)

pytestmark = pytest.mark.unit


class TestInternalConvention:
    """Verify the declared internal pixel convention."""

    def test_internal_convention_is_selene_internal(self) -> None:
        """INTERNAL_PIXEL_CONVENTION must match the documented choice."""
        assert INTERNAL_PIXEL_CONVENTION == PixelConvention.SELENE_INTERNAL

    def test_internal_convention_is_zero_based_centre_referenced(self) -> None:
        """The internal convention has centre of first pixel at 0.0."""
        assert INTERNAL_PIXEL_CONVENTION.value == "selene_internal"


class TestPixelConventionConversion:
    """Test convert_pixel_coordinate across all convention pairs."""

    def test_convert_to_same_convention_is_identity(self) -> None:
        """Converting to the same convention changes nothing."""
        for convention in PixelConvention:
            assert convert_pixel_coordinate(
                42.5, source=convention, target=convention
            ) == pytest.approx(42.5)

    def test_round_trip_identity(self) -> None:
        """Converting through intermediate conventions is consistent."""
        conventions = list(PixelConvention)
        for source in conventions:
            for target in conventions:
                # Round trip: source -> target -> source
                value = 42.5
                converted = convert_pixel_coordinate(value, source=source, target=target)
                back = convert_pixel_coordinate(converted, source=target, target=source)
                assert back == pytest.approx(value), (
                    f"Round trip through {source} -> {target} -> {source} failed for {value}"
                )

    def test_isis_to_gdal_numeric_offset(self) -> None:
        """ISIS↔GDAL conversion offset must be from declared offsets."""
        # ISIS first pixel centre: 1.0
        # GDAL first pixel centre: 0.5
        # So ISIS coordinate 1.0 should convert to GDAL 0.5
        value_isis = 1.0
        value_gdal = convert_pixel_coordinate(
            value_isis, source=PixelConvention.ISIS, target=PixelConvention.GDAL_CORNER
        )
        assert value_gdal == pytest.approx(0.5)

        # Reverse: GDAL 0.5 -> ISIS 1.0
        value_isis_back = convert_pixel_coordinate(
            0.5, source=PixelConvention.GDAL_CORNER, target=PixelConvention.ISIS
        )
        assert value_isis_back == pytest.approx(1.0)

    def test_isis_to_internal_conversion(self) -> None:
        """ISIS (1.0 first pixel) to internal (0.0 first pixel) is -1.0."""
        # ISIS uses 1-based, so pixel 1.0 (first pixel centre) -> 0.0 (internal)
        value = convert_pixel_coordinate(
            1.0, source=PixelConvention.ISIS, target=PixelConvention.SELENE_INTERNAL
        )
        assert value == pytest.approx(0.0)

        # ISIS pixel 2.0 -> internal 1.0
        value = convert_pixel_coordinate(
            2.0, source=PixelConvention.ISIS, target=PixelConvention.SELENE_INTERNAL
        )
        assert value == pytest.approx(1.0)

    def test_csm_to_internal_conversion(self) -> None:
        """CSM (0.5 first pixel) to internal (0.0 first pixel) is -0.5."""
        # CSM pixel 0.5 (first pixel centre) -> 0.0 (internal)
        value = convert_pixel_coordinate(
            0.5, source=PixelConvention.CSM, target=PixelConvention.SELENE_INTERNAL
        )
        assert value == pytest.approx(0.0)

    def test_gdal_to_internal_conversion(self) -> None:
        """GDAL (0.5 first pixel) to internal (0.0 first pixel) is -0.5."""
        # GDAL pixel 0.5 (first pixel centre) -> 0.0 (internal)
        value = convert_pixel_coordinate(
            0.5, source=PixelConvention.GDAL_CORNER, target=PixelConvention.SELENE_INTERNAL
        )
        assert value == pytest.approx(0.0)

    def test_array_index_to_internal_conversion(self) -> None:
        """Array index (0.0 first pixel) to internal (0.0 first pixel) is identity."""
        # Array index pixel 0.0 (first pixel centre) -> 0.0 (internal)
        value = convert_pixel_coordinate(
            0.0, source=PixelConvention.ARRAY_INDEX, target=PixelConvention.SELENE_INTERNAL
        )
        assert value == pytest.approx(0.0)

    def test_all_convention_pairs_are_defined(self) -> None:
        """Every pair of conventions can be converted."""
        conventions = list(PixelConvention)
        for source in conventions:
            for target in conventions:
                # Should not raise
                convert_pixel_coordinate(0.0, source=source, target=target)

    def test_convert_rejects_nan(self) -> None:
        """NaN coordinate values are rejected."""
        with pytest.raises(ValueError, match=r"pixel coordinate must be finite"):
            convert_pixel_coordinate(
                math.nan, source=PixelConvention.ISIS, target=PixelConvention.SELENE_INTERNAL
            )

    def test_convert_rejects_inf(self) -> None:
        """Infinite coordinate values are rejected."""
        with pytest.raises(ValueError, match=r"pixel coordinate must be finite"):
            convert_pixel_coordinate(
                math.inf, source=PixelConvention.ISIS, target=PixelConvention.SELENE_INTERNAL
            )

    def test_convert_rejects_negative_inf(self) -> None:
        """Negative infinite coordinate values are rejected."""
        with pytest.raises(ValueError, match=r"pixel coordinate must be finite"):
            convert_pixel_coordinate(
                -math.inf, source=PixelConvention.ISIS, target=PixelConvention.SELENE_INTERNAL
            )


class TestSourcePixel:
    """Tests for SourcePixel type and conversions."""

    def test_source_pixel_creation(self) -> None:
        """SourcePixel can be created with line and sample."""
        pixel = SourcePixel(line=10.5, sample=20.5)
        assert pixel.line == 10.5
        assert pixel.sample == 20.5

    def test_source_pixel_is_frozen(self) -> None:
        """SourcePixel is immutable."""
        pixel = SourcePixel(line=10.5, sample=20.5)
        with pytest.raises(AttributeError):
            pixel.line = 15.0  # type: ignore

    def test_source_pixel_has_slots(self) -> None:
        """SourcePixel uses slots, not __dict__."""
        pixel = SourcePixel(line=10.5, sample=20.5)
        assert not hasattr(pixel, "__dict__")

    def test_source_pixel_from_isis(self) -> None:
        """SourcePixel can be created from ISIS coordinates."""
        pixel = SourcePixel.from_isis(line=1.0, sample=1.0)
        assert pixel.line == pytest.approx(0.0)
        assert pixel.sample == pytest.approx(0.0)

    def test_source_pixel_to_isis(self) -> None:
        """SourcePixel can be converted to ISIS coordinates."""
        pixel = SourcePixel(line=0.0, sample=0.0)
        line_isis, sample_isis = pixel.to_isis()
        assert line_isis == pytest.approx(1.0)
        assert sample_isis == pytest.approx(1.0)

    def test_source_pixel_from_csm(self) -> None:
        """SourcePixel can be created from CSM coordinates."""
        pixel = SourcePixel.from_csm(line=0.5, sample=0.5)
        assert pixel.line == pytest.approx(0.0)
        assert pixel.sample == pytest.approx(0.0)

    def test_source_pixel_to_csm(self) -> None:
        """SourcePixel can be converted to CSM coordinates."""
        pixel = SourcePixel(line=0.0, sample=0.0)
        line_csm, sample_csm = pixel.to_csm()
        assert line_csm == pytest.approx(0.5)
        assert sample_csm == pytest.approx(0.5)

    def test_source_pixel_from_gdal(self) -> None:
        """SourcePixel can be created from GDAL coordinates (x, y order)."""
        pixel = SourcePixel.from_gdal(pixel_x=0.5, line_y=0.5)
        assert pixel.line == pytest.approx(0.0)
        assert pixel.sample == pytest.approx(0.0)

    def test_source_pixel_to_gdal(self) -> None:
        """SourcePixel can be converted to GDAL coordinates (x, y order)."""
        pixel = SourcePixel(line=0.0, sample=0.0)
        pixel_x, line_y = pixel.to_gdal()
        assert pixel_x == pytest.approx(0.5)
        assert line_y == pytest.approx(0.5)

    def test_source_pixel_from_array_index(self) -> None:
        """SourcePixel can be created from array indices."""
        pixel = SourcePixel.from_array_index(row=0, column=0)
        assert pixel.line == pytest.approx(0.0)
        assert pixel.sample == pytest.approx(0.0)

    def test_source_pixel_to_array_index(self) -> None:
        """SourcePixel can be converted to array indices."""
        pixel = SourcePixel(line=0.3, sample=0.3)
        row, column = pixel.to_array_index()
        assert row == 0
        assert column == 0

    def test_source_pixel_to_array_index_round_half_away(self) -> None:
        """Array index conversion uses round-half-away-from-zero."""
        # 0.5 should round to 1 (away from zero)
        pixel = SourcePixel(line=0.5, sample=0.5)
        row, column = pixel.to_array_index()
        assert row == 1
        assert column == 1

        # -0.5 should round to -1 (away from zero)
        pixel = SourcePixel(line=-0.5, sample=-0.5)
        row, column = pixel.to_array_index()
        assert row == -1
        assert column == -1

    def test_source_pixel_rejects_nan_line(self) -> None:
        """SourcePixel rejects NaN line coordinate."""
        with pytest.raises(ValueError, match=r"SourcePixel.line must be finite"):
            SourcePixel(line=math.nan, sample=0.0)

    def test_source_pixel_rejects_nan_sample(self) -> None:
        """SourcePixel rejects NaN sample coordinate."""
        with pytest.raises(ValueError, match=r"SourcePixel.sample must be finite"):
            SourcePixel(line=0.0, sample=math.nan)

    def test_source_pixel_rejects_inf_line(self) -> None:
        """SourcePixel rejects infinite line coordinate."""
        with pytest.raises(ValueError, match=r"SourcePixel.line must be finite"):
            SourcePixel(line=math.inf, sample=0.0)

    def test_source_pixel_rejects_inf_sample(self) -> None:
        """SourcePixel rejects infinite sample coordinate."""
        with pytest.raises(ValueError, match=r"SourcePixel.sample must be finite"):
            SourcePixel(line=0.0, sample=math.inf)


class TestReferencePixel:
    """Tests for ReferencePixel type and conversions."""

    def test_reference_pixel_creation(self) -> None:
        """ReferencePixel can be created with line and sample."""
        pixel = ReferencePixel(line=10.5, sample=20.5)
        assert pixel.line == 10.5
        assert pixel.sample == 20.5

    def test_reference_pixel_is_frozen(self) -> None:
        """ReferencePixel is immutable."""
        pixel = ReferencePixel(line=10.5, sample=20.5)
        with pytest.raises(AttributeError):
            pixel.line = 15.0  # type: ignore

    def test_reference_pixel_has_slots(self) -> None:
        """ReferencePixel uses slots, not __dict__."""
        pixel = ReferencePixel(line=10.5, sample=20.5)
        assert not hasattr(pixel, "__dict__")

    def test_reference_pixel_rejects_nan_line(self) -> None:
        """ReferencePixel rejects NaN line coordinate."""
        with pytest.raises(ValueError, match=r"ReferencePixel.line must be finite"):
            ReferencePixel(line=math.nan, sample=0.0)

    def test_reference_pixel_rejects_nan_sample(self) -> None:
        """ReferencePixel rejects NaN sample coordinate."""
        with pytest.raises(ValueError, match=r"ReferencePixel.sample must be finite"):
            ReferencePixel(line=0.0, sample=math.nan)


class TestPixelTypeDictinctness:
    """Verify SourcePixel and ReferencePixel are distinct types."""

    def test_source_and_reference_pixels_are_different_classes(self) -> None:
        """SourcePixel and ReferencePixel must be different classes."""
        assert SourcePixel is not ReferencePixel  # type: ignore

    def test_source_pixel_not_instance_of_reference_pixel(self) -> None:
        """A SourcePixel is not an instance of ReferencePixel."""
        source = SourcePixel(line=10.0, sample=20.0)
        assert not isinstance(source, ReferencePixel)

    def test_reference_pixel_not_instance_of_source_pixel(self) -> None:
        """A ReferencePixel is not an instance of SourcePixel."""
        reference = ReferencePixel(line=10.0, sample=20.0)
        assert not isinstance(reference, SourcePixel)
