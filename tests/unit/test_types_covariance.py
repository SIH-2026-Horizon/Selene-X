"""Tests for Covariance2D validation and properties.

Covers positive-definite enforcement, frame/units consistency, and
eigenvalue computation.
"""

import math

import pytest

from selene_core.types import Covariance2D, CovarianceFrame, LocalWarpJacobian

pytestmark = pytest.mark.unit


class TestCovariance2DValidation:
    """Tests for Covariance2D validity rules."""

    def test_covariance2d_creation(self) -> None:
        """Covariance2D can be created with valid parameters."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        assert cov.xx == 1.0
        assert cov.xy == 0.0
        assert cov.yy == 1.0
        assert cov.frame == CovarianceFrame.SOURCE_PIXEL
        assert cov.units == "px2"

    def test_covariance2d_is_frozen(self) -> None:
        """Covariance2D is immutable."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        with pytest.raises(AttributeError):
            cov.xx = 2.0  # type: ignore

    def test_covariance2d_has_slots(self) -> None:
        """Covariance2D uses slots, not __dict__."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        assert not hasattr(cov, "__dict__")

    def test_covariance2d_requires_positive_xx(self) -> None:
        """Diagonal element xx must be positive."""
        with pytest.raises(ValueError, match=r"diagonal must be positive"):
            Covariance2D(xx=0.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

    def test_covariance2d_requires_positive_yy(self) -> None:
        """Diagonal element yy must be positive."""
        with pytest.raises(ValueError, match=r"diagonal must be positive"):
            Covariance2D(xx=1.0, xy=0.0, yy=0.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

    def test_covariance2d_rejects_negative_xx(self) -> None:
        """Negative xx is rejected."""
        with pytest.raises(ValueError, match=r"diagonal must be positive"):
            Covariance2D(xx=-1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

    def test_covariance2d_rejects_negative_yy(self) -> None:
        """Negative yy is rejected."""
        with pytest.raises(ValueError, match=r"diagonal must be positive"):
            Covariance2D(xx=1.0, xy=0.0, yy=-1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

    def test_covariance2d_requires_positive_definite(self) -> None:
        """Determinant (xx*yy - xy^2) must be positive."""
        # xx=1, yy=1, xy=1: determinant = 1 - 1 = 0 (not positive definite)
        with pytest.raises(ValueError, match=r"must be positive definite"):
            Covariance2D(xx=1.0, xy=1.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

    def test_covariance2d_degenerate_boundary_rejected(self) -> None:
        """Covariance with xy^2 == xx*yy exactly is rejected (degenerate)."""
        # When xy^2 = xx*yy, the determinant is 0
        # For example: xx=1, yy=4, xy=2 => det = 4-4 = 0
        with pytest.raises(ValueError, match=r"must be positive definite"):
            Covariance2D(xx=1.0, xy=2.0, yy=4.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

    def test_covariance2d_rejects_nan_xx(self) -> None:
        """NaN xx is rejected."""
        with pytest.raises(ValueError, match=r"Covariance2D.xx must be finite"):
            Covariance2D(
                xx=math.nan, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
            )

    def test_covariance2d_rejects_nan_xy(self) -> None:
        """NaN xy is rejected."""
        with pytest.raises(ValueError, match=r"Covariance2D.xy must be finite"):
            Covariance2D(
                xx=1.0, xy=math.nan, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
            )

    def test_covariance2d_rejects_nan_yy(self) -> None:
        """NaN yy is rejected."""
        with pytest.raises(ValueError, match=r"Covariance2D.yy must be finite"):
            Covariance2D(
                xx=1.0, xy=0.0, yy=math.nan, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
            )

    def test_covariance2d_rejects_inf_xx(self) -> None:
        """Infinite xx is rejected."""
        with pytest.raises(ValueError, match=r"Covariance2D.xx must be finite"):
            Covariance2D(
                xx=math.inf, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
            )

    def test_covariance2d_rejects_inf_yy(self) -> None:
        """Infinite yy is rejected."""
        with pytest.raises(ValueError, match=r"Covariance2D.yy must be finite"):
            Covariance2D(
                xx=1.0, xy=0.0, yy=math.inf, frame=CovarianceFrame.SOURCE_PIXEL, units="px2"
            )


class TestCovariance2DFrameUnits:
    """Tests for frame/units consistency."""

    def test_source_pixel_frame_requires_px2_units(self) -> None:
        """SOURCE_PIXEL frame requires px2 units."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        assert cov.units == "px2"

    def test_source_pixel_frame_rejects_wrong_units(self) -> None:
        """SOURCE_PIXEL frame rejects non-px2 units."""
        with pytest.raises(ValueError, match=r"must use units 'px2'"):
            Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="m2")

    def test_reference_pixel_frame_requires_px2_units(self) -> None:
        """REFERENCE_PIXEL frame requires px2 units."""
        cov = Covariance2D(
            xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.REFERENCE_PIXEL, units="px2"
        )
        assert cov.units == "px2"

    def test_reference_pixel_frame_rejects_wrong_units(self) -> None:
        """REFERENCE_PIXEL frame rejects non-px2 units."""
        with pytest.raises(ValueError, match=r"must use units 'px2'"):
            Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.REFERENCE_PIXEL, units="m2")

    def test_map_frame_requires_m2_units(self) -> None:
        """MAP frame requires m2 units."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.MAP, units="m2")
        assert cov.units == "m2"

    def test_map_frame_rejects_wrong_units(self) -> None:
        """MAP frame rejects non-m2 units."""
        with pytest.raises(ValueError, match=r"must use units 'm2'"):
            Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.MAP, units="px2")


class TestCovariance2DIsotropic:
    """Tests for isotropic covariance construction."""

    def test_isotropic_covariance_creation(self) -> None:
        """Isotropic covariance can be created with sigma."""
        cov = Covariance2D.isotropic(sigma=2.0, frame=CovarianceFrame.SOURCE_PIXEL)
        assert cov.xx == pytest.approx(4.0)
        assert cov.xy == pytest.approx(0.0)
        assert cov.yy == pytest.approx(4.0)
        assert cov.frame == CovarianceFrame.SOURCE_PIXEL
        assert cov.units == "px2"

    def test_isotropic_covariance_zero_sigma(self) -> None:
        """Isotropic covariance with sigma=0 is rejected."""
        with pytest.raises(ValueError, match=r"diagonal must be positive"):
            Covariance2D.isotropic(sigma=0.0, frame=CovarianceFrame.SOURCE_PIXEL)

    def test_isotropic_covariance_negative_sigma_treated_as_positive(self) -> None:
        """Isotropic covariance with negative sigma squares to positive."""
        # Negative sigma squared gives positive variance, so it's accepted
        cov = Covariance2D.isotropic(sigma=-1.0, frame=CovarianceFrame.SOURCE_PIXEL)
        # (-1)^2 = 1, so xx and yy should be 1
        assert cov.xx == pytest.approx(1.0)
        assert cov.yy == pytest.approx(1.0)


class TestCovariance2DEigenvalues:
    """Tests for eigenvalue and orientation computation."""

    def test_isotropic_covariance_eigenvalues(self) -> None:
        """Isotropic covariance has equal eigenvalues."""
        cov = Covariance2D.isotropic(sigma=2.0, frame=CovarianceFrame.SOURCE_PIXEL)
        lambda1, lambda2 = cov.eigenvalues
        assert lambda1 == pytest.approx(4.0)
        assert lambda2 == pytest.approx(4.0)

    def test_diagonal_covariance_eigenvalues(self) -> None:
        """Diagonal covariance has diagonal elements as eigenvalues."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=4.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        lambda1, lambda2 = cov.eigenvalues
        assert lambda1 == pytest.approx(1.0)
        assert lambda2 == pytest.approx(4.0)

    def test_sigma_minor_isotropic(self) -> None:
        """Isotropic covariance sigma_minor equals sigma."""
        cov = Covariance2D.isotropic(sigma=2.5, frame=CovarianceFrame.SOURCE_PIXEL)
        assert cov.sigma_minor == pytest.approx(2.5)

    def test_sigma_major_isotropic(self) -> None:
        """Isotropic covariance sigma_major equals sigma."""
        cov = Covariance2D.isotropic(sigma=2.5, frame=CovarianceFrame.SOURCE_PIXEL)
        assert cov.sigma_major == pytest.approx(2.5)

    def test_anisotropy_ratio_isotropic(self) -> None:
        """Isotropic covariance has anisotropy ratio of 1."""
        cov = Covariance2D.isotropic(sigma=2.5, frame=CovarianceFrame.SOURCE_PIXEL)
        assert cov.anisotropy_ratio == pytest.approx(1.0)

    def test_anisotropy_ratio_anisotropic(self) -> None:
        """Anisotropic covariance has ratio > 1."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=4.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        # sigma_minor = sqrt(1.0) = 1.0
        # sigma_major = sqrt(4.0) = 2.0
        # ratio = 2.0 / 1.0 = 2.0
        assert cov.anisotropy_ratio == pytest.approx(2.0)

    def test_orientation_diagonal_covariance(self) -> None:
        """Diagonal covariance with larger yy has orientation 90."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=4.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        # For diagonal: atan2(2*xy, xx - yy) = atan2(0, 1-4) = atan2(0, -3)
        # atan2(0, -3) ≈ π, so 0.5 * π = 90 degrees
        assert cov.orientation_deg == pytest.approx(90.0, abs=0.01)


class TestCovariance2DTransformation:
    """Tests for covariance transformation through Jacobians."""

    def test_covariance_transform_identity_jacobian(self) -> None:
        """Covariance transformed by identity Jacobian is unchanged."""
        cov = Covariance2D(xx=1.0, xy=0.5, yy=2.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        jacobian = LocalWarpJacobian.identity()
        transformed = cov.transformed(jacobian, CovarianceFrame.REFERENCE_PIXEL)
        assert transformed.xx == pytest.approx(cov.xx)
        assert transformed.xy == pytest.approx(cov.xy)
        assert transformed.yy == pytest.approx(cov.yy)

    def test_covariance_transform_scaling_jacobian(self) -> None:
        """Covariance transformed by scaling Jacobian scales quadratically."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        # Scale by 2 in both directions
        jacobian = LocalWarpJacobian(2.0, 0.0, 0.0, 2.0)
        transformed = cov.transformed(jacobian, CovarianceFrame.REFERENCE_PIXEL)
        # Variance scales as scale^2, so 1 -> 4
        assert transformed.xx == pytest.approx(4.0)
        assert transformed.xy == pytest.approx(0.0)
        assert transformed.yy == pytest.approx(4.0)

    def test_covariance_transform_frame_change(self) -> None:
        """Covariance transformation changes frame."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        jacobian = LocalWarpJacobian.identity()
        # Map frame to reference frame
        transformed = cov.transformed(jacobian, CovarianceFrame.REFERENCE_PIXEL)
        assert transformed.frame == CovarianceFrame.REFERENCE_PIXEL

    def test_covariance_transform_to_map_frame(self) -> None:
        """Covariance can be transformed to map frame with correct units."""
        cov = Covariance2D(xx=1.0, xy=0.0, yy=1.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        jacobian = LocalWarpJacobian(1.0, 0.0, 0.0, 1.0)
        # Transform to map frame (units should change to m2)
        transformed = cov.transformed(jacobian, CovarianceFrame.MAP)
        assert transformed.frame == CovarianceFrame.MAP
        assert transformed.units == "m2"

    def test_covariance_transform_maintains_positive_definite(self) -> None:
        """Covariance transformation preserves positive-definiteness."""
        cov = Covariance2D(xx=2.0, xy=0.5, yy=3.0, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        jacobian = LocalWarpJacobian(1.2, 0.1, 0.05, 1.1)
        transformed = cov.transformed(jacobian, CovarianceFrame.REFERENCE_PIXEL)
        # Should not raise
        determinant = transformed.xx * transformed.yy - transformed.xy * transformed.xy
        assert determinant > 0.0
