"""Tests for ground coordinate types.

Covers MapCoordinate, BodyFixedCoordinate, SelenographicCoordinate, and
LocalWarpJacobian validation and semantics.
"""

import math

import pytest

from selene_core.types import (
    BodyFixedCoordinate,
    LocalWarpJacobian,
    MapCoordinate,
    SelenographicCoordinate,
)

pytestmark = pytest.mark.unit


class TestMapCoordinate:
    """Tests for MapCoordinate projection coordinates."""

    def test_map_coordinate_creation(self) -> None:
        """MapCoordinate can be created with x, y, and CRS WKT."""
        coord = MapCoordinate(x_m=1000.0, y_m=2000.0, crs_wkt="EPSG:4326")
        assert coord.x_m == 1000.0
        assert coord.y_m == 2000.0
        assert coord.crs_wkt == "EPSG:4326"

    def test_map_coordinate_is_frozen(self) -> None:
        """MapCoordinate is immutable."""
        coord = MapCoordinate(x_m=1000.0, y_m=2000.0, crs_wkt="EPSG:4326")
        with pytest.raises(AttributeError):
            coord.x_m = 1500.0  # type: ignore

    def test_map_coordinate_has_slots(self) -> None:
        """MapCoordinate uses slots, not __dict__."""
        coord = MapCoordinate(x_m=1000.0, y_m=2000.0, crs_wkt="EPSG:4326")
        assert not hasattr(coord, "__dict__")

    def test_map_coordinate_requires_crs_wkt(self) -> None:
        """MapCoordinate rejects empty crs_wkt."""
        with pytest.raises(ValueError, match=r"crs_wkt must name a CRS"):
            MapCoordinate(x_m=1000.0, y_m=2000.0, crs_wkt="")

    def test_map_coordinate_rejects_whitespace_crs_wkt(self) -> None:
        """MapCoordinate rejects whitespace-only crs_wkt."""
        with pytest.raises(ValueError, match=r"crs_wkt must name a CRS"):
            MapCoordinate(x_m=1000.0, y_m=2000.0, crs_wkt="   ")

    def test_map_coordinate_rejects_nan_x(self) -> None:
        """MapCoordinate rejects NaN x coordinate."""
        with pytest.raises(ValueError, match=r"MapCoordinate.x_m must be finite"):
            MapCoordinate(x_m=math.nan, y_m=2000.0, crs_wkt="EPSG:4326")

    def test_map_coordinate_rejects_nan_y(self) -> None:
        """MapCoordinate rejects NaN y coordinate."""
        with pytest.raises(ValueError, match=r"MapCoordinate.y_m must be finite"):
            MapCoordinate(x_m=1000.0, y_m=math.nan, crs_wkt="EPSG:4326")

    def test_map_coordinate_rejects_inf_x(self) -> None:
        """MapCoordinate rejects infinite x coordinate."""
        with pytest.raises(ValueError, match=r"MapCoordinate.x_m must be finite"):
            MapCoordinate(x_m=math.inf, y_m=2000.0, crs_wkt="EPSG:4326")

    def test_map_coordinate_rejects_inf_y(self) -> None:
        """MapCoordinate rejects infinite y coordinate."""
        with pytest.raises(ValueError, match=r"MapCoordinate.y_m must be finite"):
            MapCoordinate(x_m=1000.0, y_m=math.inf, crs_wkt="EPSG:4326")


class TestBodyFixedCoordinate:
    """Tests for BodyFixedCoordinate rectangular coordinates."""

    def test_body_fixed_coordinate_creation(self) -> None:
        """BodyFixedCoordinate can be created with x, y, z, and frame."""
        coord = BodyFixedCoordinate(x_m=1000.0, y_m=2000.0, z_m=3000.0, frame="MOON_ME")
        assert coord.x_m == 1000.0
        assert coord.y_m == 2000.0
        assert coord.z_m == 3000.0
        assert coord.frame == "MOON_ME"

    def test_body_fixed_coordinate_is_frozen(self) -> None:
        """BodyFixedCoordinate is immutable."""
        coord = BodyFixedCoordinate(x_m=1000.0, y_m=2000.0, z_m=3000.0, frame="MOON_ME")
        with pytest.raises(AttributeError):
            coord.x_m = 1500.0  # type: ignore

    def test_body_fixed_coordinate_has_slots(self) -> None:
        """BodyFixedCoordinate uses slots, not __dict__."""
        coord = BodyFixedCoordinate(x_m=1000.0, y_m=2000.0, z_m=3000.0, frame="MOON_ME")
        assert not hasattr(coord, "__dict__")

    def test_body_fixed_coordinate_requires_frame(self) -> None:
        """BodyFixedCoordinate rejects empty frame."""
        with pytest.raises(ValueError, match=r"frame must be named"):
            BodyFixedCoordinate(x_m=1000.0, y_m=2000.0, z_m=3000.0, frame="")

    def test_body_fixed_coordinate_rejects_whitespace_frame(self) -> None:
        """BodyFixedCoordinate rejects whitespace-only frame."""
        with pytest.raises(ValueError, match=r"frame must be named"):
            BodyFixedCoordinate(x_m=1000.0, y_m=2000.0, z_m=3000.0, frame="   ")

    def test_body_fixed_coordinate_rejects_nan_x(self) -> None:
        """BodyFixedCoordinate rejects NaN x coordinate."""
        with pytest.raises(ValueError, match=r"BodyFixedCoordinate.x_m must be finite"):
            BodyFixedCoordinate(x_m=math.nan, y_m=2000.0, z_m=3000.0, frame="MOON_ME")

    def test_body_fixed_coordinate_rejects_nan_y(self) -> None:
        """BodyFixedCoordinate rejects NaN y coordinate."""
        with pytest.raises(ValueError, match=r"BodyFixedCoordinate.y_m must be finite"):
            BodyFixedCoordinate(x_m=1000.0, y_m=math.nan, z_m=3000.0, frame="MOON_ME")

    def test_body_fixed_coordinate_rejects_nan_z(self) -> None:
        """BodyFixedCoordinate rejects NaN z coordinate."""
        with pytest.raises(ValueError, match=r"BodyFixedCoordinate.z_m must be finite"):
            BodyFixedCoordinate(x_m=1000.0, y_m=2000.0, z_m=math.nan, frame="MOON_ME")

    def test_body_fixed_coordinate_rejects_inf_x(self) -> None:
        """BodyFixedCoordinate rejects infinite x coordinate."""
        with pytest.raises(ValueError, match=r"BodyFixedCoordinate.x_m must be finite"):
            BodyFixedCoordinate(x_m=math.inf, y_m=2000.0, z_m=3000.0, frame="MOON_ME")


class TestSelenographicCoordinate:
    """Tests for SelenographicCoordinate spherical coordinates."""

    def test_selenographic_coordinate_creation(self) -> None:
        """SelenographicCoordinate can be created with lon, lat, radius, and frame."""
        coord = SelenographicCoordinate(
            longitude_deg=0.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )
        assert coord.longitude_deg == 0.0
        assert coord.latitude_deg == 0.0
        assert coord.radius_m == 1737400.0
        assert coord.frame == "MOON_ME"

    def test_selenographic_coordinate_is_frozen(self) -> None:
        """SelenographicCoordinate is immutable."""
        coord = SelenographicCoordinate(
            longitude_deg=0.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )
        with pytest.raises(AttributeError):
            coord.longitude_deg = 90.0  # type: ignore

    def test_selenographic_coordinate_has_slots(self) -> None:
        """SelenographicCoordinate uses slots, not __dict__."""
        coord = SelenographicCoordinate(
            longitude_deg=0.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )
        assert not hasattr(coord, "__dict__")

    def test_selenographic_coordinate_requires_frame(self) -> None:
        """SelenographicCoordinate rejects empty frame."""
        with pytest.raises(ValueError, match=r"frame must be named"):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=0.0, radius_m=1737400.0, frame=""
            )

    def test_selenographic_coordinate_rejects_whitespace_frame(self) -> None:
        """SelenographicCoordinate rejects whitespace-only frame."""
        with pytest.raises(ValueError, match=r"frame must be named"):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=0.0, radius_m=1737400.0, frame="   "
            )

    def test_selenographic_latitude_valid_range(self) -> None:
        """Latitude must be in [-90, 90]."""
        # Valid at boundaries
        SelenographicCoordinate(
            longitude_deg=0.0, latitude_deg=-90.0, radius_m=1737400.0, frame="MOON_ME"
        )
        SelenographicCoordinate(
            longitude_deg=0.0, latitude_deg=90.0, radius_m=1737400.0, frame="MOON_ME"
        )

    def test_selenographic_latitude_below_range(self) -> None:
        """Latitude below -90 is rejected."""
        with pytest.raises(ValueError, match=r"latitude_deg must be within"):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=-90.1, radius_m=1737400.0, frame="MOON_ME"
            )

    def test_selenographic_latitude_above_range(self) -> None:
        """Latitude above 90 is rejected."""
        with pytest.raises(ValueError, match=r"latitude_deg must be within"):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=90.1, radius_m=1737400.0, frame="MOON_ME"
            )

    def test_selenographic_longitude_valid_range_before_normalization(self) -> None:
        """Longitude must be in [-360, 360] before normalization."""
        # Valid at boundaries
        SelenographicCoordinate(
            longitude_deg=-360.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )
        SelenographicCoordinate(
            longitude_deg=360.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )

    def test_selenographic_longitude_below_range(self) -> None:
        """Longitude below -360 is rejected."""
        with pytest.raises(ValueError, match=r"longitude_deg must be within"):
            SelenographicCoordinate(
                longitude_deg=-360.1, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
            )

    def test_selenographic_longitude_above_range(self) -> None:
        """Longitude above 360 is rejected."""
        with pytest.raises(ValueError, match=r"longitude_deg must be within"):
            SelenographicCoordinate(
                longitude_deg=360.1, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
            )

    def test_selenographic_requires_positive_radius(self) -> None:
        """Radius must be positive."""
        with pytest.raises(ValueError, match=r"radius_m must be positive"):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=0.0, radius_m=0.0, frame="MOON_ME"
            )

    def test_selenographic_rejects_negative_radius(self) -> None:
        """Negative radius is rejected."""
        with pytest.raises(ValueError, match=r"radius_m must be positive"):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=0.0, radius_m=-100.0, frame="MOON_ME"
            )

    def test_selenographic_rejects_nan_longitude(self) -> None:
        """SelenographicCoordinate rejects NaN longitude."""
        msg = r"SelenographicCoordinate.longitude_deg must be finite"
        with pytest.raises(ValueError, match=msg):
            SelenographicCoordinate(
                longitude_deg=math.nan, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
            )

    def test_selenographic_rejects_nan_latitude(self) -> None:
        """SelenographicCoordinate rejects NaN latitude."""
        msg = r"SelenographicCoordinate.latitude_deg must be finite"
        with pytest.raises(ValueError, match=msg):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=math.nan, radius_m=1737400.0, frame="MOON_ME"
            )

    def test_selenographic_rejects_nan_radius(self) -> None:
        """SelenographicCoordinate rejects NaN radius."""
        with pytest.raises(ValueError, match=r"SelenographicCoordinate.radius_m must be finite"):
            SelenographicCoordinate(
                longitude_deg=0.0, latitude_deg=0.0, radius_m=math.nan, frame="MOON_ME"
            )

    def test_selenographic_longitude_east_positive_normalization(self) -> None:
        """Longitude can be normalized to [0, 360) east-positive."""
        # Negative longitude wraps around
        coord = SelenographicCoordinate(
            longitude_deg=-180.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )
        assert coord.longitude_deg_east_positive == pytest.approx(180.0)

        # Already in range
        coord = SelenographicCoordinate(
            longitude_deg=180.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )
        assert coord.longitude_deg_east_positive == pytest.approx(180.0)

        # Zero stays zero
        coord = SelenographicCoordinate(
            longitude_deg=0.0, latitude_deg=0.0, radius_m=1737400.0, frame="MOON_ME"
        )
        assert coord.longitude_deg_east_positive == pytest.approx(0.0)


class TestLocalWarpJacobian:
    """Tests for LocalWarpJacobian mapping linearization."""

    def test_local_warp_jacobian_creation(self) -> None:
        """LocalWarpJacobian can be created with four derivative components."""
        jacobian = LocalWarpJacobian(
            d_ref_line_d_src_line=1.0,
            d_ref_line_d_src_sample=0.1,
            d_ref_sample_d_src_line=0.05,
            d_ref_sample_d_src_sample=1.0,
        )
        assert jacobian.d_ref_line_d_src_line == 1.0
        assert jacobian.d_ref_line_d_src_sample == 0.1
        assert jacobian.d_ref_sample_d_src_line == 0.05
        assert jacobian.d_ref_sample_d_src_sample == 1.0

    def test_local_warp_jacobian_is_frozen(self) -> None:
        """LocalWarpJacobian is immutable."""
        jacobian = LocalWarpJacobian(1.0, 0.1, 0.05, 1.0)
        with pytest.raises(AttributeError):
            jacobian.d_ref_line_d_src_line = 1.5  # type: ignore

    def test_local_warp_jacobian_has_slots(self) -> None:
        """LocalWarpJacobian uses slots, not __dict__."""
        jacobian = LocalWarpJacobian(1.0, 0.1, 0.05, 1.0)
        assert not hasattr(jacobian, "__dict__")

    def test_identity_jacobian(self) -> None:
        """Identity Jacobian has determinant 1."""
        jacobian = LocalWarpJacobian.identity()
        assert jacobian.d_ref_line_d_src_line == 1.0
        assert jacobian.d_ref_line_d_src_sample == 0.0
        assert jacobian.d_ref_sample_d_src_line == 0.0
        assert jacobian.d_ref_sample_d_src_sample == 1.0
        assert jacobian.determinant == pytest.approx(1.0)

    def test_determinant_calculation(self) -> None:
        """Determinant is correct 2x2 matrix determinant."""
        jacobian = LocalWarpJacobian(
            d_ref_line_d_src_line=2.0,
            d_ref_line_d_src_sample=0.5,
            d_ref_sample_d_src_line=0.0,
            d_ref_sample_d_src_sample=3.0,
        )
        # det = 2*3 - 0.5*0 = 6
        assert jacobian.determinant == pytest.approx(6.0)

    def test_inverse_jacobian(self) -> None:
        """Jacobian inverse is the matrix inverse."""
        jacobian = LocalWarpJacobian(
            d_ref_line_d_src_line=2.0,
            d_ref_line_d_src_sample=0.5,
            d_ref_sample_d_src_line=0.0,
            d_ref_sample_d_src_sample=3.0,
        )
        inverse = jacobian.inverse()
        # Determinant is 6
        # Inverse of [[2, 0.5], [0, 3]] is [[3/6, -0.5/6], [0, 2/6]]
        assert inverse.d_ref_line_d_src_line == pytest.approx(3.0 / 6.0)
        assert inverse.d_ref_line_d_src_sample == pytest.approx(-0.5 / 6.0)
        assert inverse.d_ref_sample_d_src_line == pytest.approx(0.0)
        assert inverse.d_ref_sample_d_src_sample == pytest.approx(2.0 / 6.0)

    def test_jacobian_inverse_round_trip(self) -> None:
        """Jacobian times its inverse is identity."""
        jacobian = LocalWarpJacobian(1.2, 0.1, 0.05, 1.1)
        inverse = jacobian.inverse()

        # A residual round-tripped should be restored
        d_line, d_sample = 5.0, 3.0
        mapped = jacobian.apply(d_line, d_sample)
        restored = inverse.apply(*mapped)
        assert restored[0] == pytest.approx(d_line)
        assert restored[1] == pytest.approx(d_sample)

    def test_jacobian_singular_determinant_rejected(self) -> None:
        """Singular Jacobian (determinant 0) cannot be inverted."""
        # Singular matrix: columns are linearly dependent
        jacobian = LocalWarpJacobian(1.0, 2.0, 2.0, 4.0)
        # det = 1*4 - 2*2 = 0
        with pytest.raises(ValueError, match=r"singular"):
            jacobian.inverse()

    def test_jacobian_near_singular_rejected(self) -> None:
        """Nearly singular Jacobian (determinant < 1e-12) cannot be inverted."""
        # Create a nearly singular matrix
        jacobian = LocalWarpJacobian(1.0, 2.0, 2.0, 4.0 + 1e-13)
        # det ≈ 1e-13, which is < 1e-12
        with pytest.raises(ValueError, match=r"singular"):
            jacobian.inverse()

    def test_jacobian_apply_displacement(self) -> None:
        """Jacobian can map a displacement vector."""
        jacobian = LocalWarpJacobian(2.0, 0.5, 0.0, 3.0)
        d_line, d_sample = 1.0, 1.0
        mapped_line, mapped_sample = jacobian.apply(d_line, d_sample)
        # mapped_line = 2*1 + 0.5*1 = 2.5
        # mapped_sample = 0*1 + 3*1 = 3
        assert mapped_line == pytest.approx(2.5)
        assert mapped_sample == pytest.approx(3.0)

    def test_jacobian_rejects_nan(self) -> None:
        """LocalWarpJacobian rejects NaN components."""
        with pytest.raises(ValueError, match=r"LocalWarpJacobian.*must be finite"):
            LocalWarpJacobian(math.nan, 0.0, 0.0, 1.0)

    def test_jacobian_rejects_inf(self) -> None:
        """LocalWarpJacobian rejects infinite components."""
        with pytest.raises(ValueError, match=r"LocalWarpJacobian.*must be finite"):
            LocalWarpJacobian(math.inf, 0.0, 0.0, 1.0)

    def test_jacobian_inverse_nan_determinant_rejected(self) -> None:
        """Jacobian cannot be created with NaN component."""
        # NaN is rejected at construction time
        with pytest.raises(ValueError, match=r"LocalWarpJacobian.*must be finite"):
            LocalWarpJacobian(1.0, 0.0, 0.0, math.nan)

    def test_jacobian_inverse_inf_determinant_rejected(self) -> None:
        """Jacobian cannot be created with infinite component."""
        # Inf is rejected at construction time
        with pytest.raises(ValueError, match=r"LocalWarpJacobian.*must be finite"):
            LocalWarpJacobian(1.0, 0.0, 0.0, math.inf)
