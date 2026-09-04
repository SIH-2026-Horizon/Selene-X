"""Property-based tests for types using hypothesis.

Covers round-trip invariants and semantic properties across generated inputs.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from selene_core.types import (
    Covariance2D,
    CovarianceFrame,
    PixelConvention,
    PixelWindow,
    convert_pixel_coordinate,
)

pytestmark = pytest.mark.property

# Constrain floats to avoid extreme values that cause numerical issues
REASONABLE_FLOAT = st.floats(
    min_value=-1e6,
    max_value=1e6,
    allow_nan=False,
    allow_infinity=False,
)

SMALL_POSITIVE_FLOAT = st.floats(
    min_value=1e-6,
    max_value=1e3,
    allow_nan=False,
    allow_infinity=False,
)

POSITIVE_FLOAT = st.floats(
    min_value=1e-10,
    max_value=1e6,
    allow_nan=False,
    allow_infinity=False,
)


class TestPixelConversionRoundTrips:
    """Property tests for pixel coordinate conversions."""

    @given(value=REASONABLE_FLOAT)
    def test_pixel_conversion_identity_is_idempotent(self, value: float) -> None:
        """Converting to the same convention always gives the same value."""
        for convention in PixelConvention:
            result = convert_pixel_coordinate(value, source=convention, target=convention)
            assert result == pytest.approx(value, rel=1e-10, abs=1e-10)

    @given(value=REASONABLE_FLOAT)
    def test_pixel_conversion_round_trip_any_order(self, value: float) -> None:
        """Any sequence of conversions back to the source recovers the original."""
        conventions = list(PixelConvention)
        for source in conventions:
            for intermediate in conventions:
                for target in conventions:
                    # source -> intermediate -> target -> source
                    step1 = convert_pixel_coordinate(value, source=source, target=intermediate)
                    step2 = convert_pixel_coordinate(step1, source=intermediate, target=target)
                    step3 = convert_pixel_coordinate(step2, source=target, target=source)
                    assert step3 == pytest.approx(value, rel=1e-10, abs=1e-10), (
                        f"Round trip {source} -> {intermediate} -> {target} -> {source} "
                        f"failed for {value}"
                    )

    @given(value=REASONABLE_FLOAT)
    def test_pixel_conversion_direct_and_composed_equivalent(self, value: float) -> None:
        """Direct conversion equals composed conversions."""
        # For each pair of distinct conventions, direct and any path are equivalent
        conventions = list(PixelConvention)
        for source in conventions:
            for target in conventions:
                direct = convert_pixel_coordinate(value, source=source, target=target)
                # Route through any intermediate
                if conventions:
                    intermediate = conventions[0]
                    if intermediate != source and intermediate != target:
                        via_intermediate = convert_pixel_coordinate(
                            value, source=source, target=intermediate
                        )
                        via_target = convert_pixel_coordinate(
                            via_intermediate, source=intermediate, target=target
                        )
                        assert direct == pytest.approx(via_target, rel=1e-10, abs=1e-10)


class TestCovariance2DConstruction:
    """Property tests for Covariance2D positive-definite validity."""

    @given(
        xx=POSITIVE_FLOAT,
        yy=POSITIVE_FLOAT,
        xy=st.floats(allow_nan=False, allow_infinity=False),
    )
    def test_covariance_accepts_exactly_positive_definite(
        self, xx: float, yy: float, xy: float
    ) -> None:
        """Covariance construction succeeds iff the matrix is positive-definite."""
        determinant = xx * yy - xy * xy
        if determinant > 0.0:
            # Should construct successfully
            cov = Covariance2D(xx=xx, xy=xy, yy=yy, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
            # Verify it's constructible
            assert cov.xx == xx
            assert cov.xy == xy
            assert cov.yy == yy
        else:
            # Should raise
            with pytest.raises(ValueError, match=r"positive definite|diagonal must be positive"):
                Covariance2D(xx=xx, xy=xy, yy=yy, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")

    @given(sigma=SMALL_POSITIVE_FLOAT)
    def test_isotropic_covariance_always_positive_definite(self, sigma: float) -> None:
        """Isotropic covariance is always positive-definite."""
        cov = Covariance2D.isotropic(sigma=sigma, frame=CovarianceFrame.SOURCE_PIXEL)
        # Verify positive-definite: determinant > 0
        determinant = cov.xx * cov.yy - cov.xy * cov.xy
        assert determinant > 0.0
        # Verify construction succeeded
        assert cov.sigma_major >= cov.sigma_minor

    @given(
        xx=POSITIVE_FLOAT,
        yy=POSITIVE_FLOAT,
    )
    def test_diagonal_covariance_positive_definite(self, xx: float, yy: float) -> None:
        """Diagonal covariance (xy=0) is positive-definite."""
        cov = Covariance2D(xx=xx, xy=0.0, yy=yy, frame=CovarianceFrame.SOURCE_PIXEL, units="px2")
        # Diagonal covariance is PD iff diagonal elements are positive
        determinant = cov.xx * cov.yy
        assert determinant > 0.0


class TestPixelWindowIntersection:
    """Property tests for window intersection semantics."""

    @given(
        line_start1=st.integers(min_value=-1000, max_value=1000),
        sample_start1=st.integers(min_value=-1000, max_value=1000),
        line_count1=st.integers(min_value=1, max_value=500),
        sample_count1=st.integers(min_value=1, max_value=500),
        line_start2=st.integers(min_value=-1000, max_value=1000),
        sample_start2=st.integers(min_value=-1000, max_value=1000),
        line_count2=st.integers(min_value=1, max_value=500),
        sample_count2=st.integers(min_value=1, max_value=500),
    )
    def test_window_intersection_commutative(
        self,
        line_start1: int,
        sample_start1: int,
        line_count1: int,
        sample_count1: int,
        line_start2: int,
        sample_start2: int,
        line_count2: int,
        sample_count2: int,
    ) -> None:
        """Window intersection is commutative: A ∩ B = B ∩ A."""
        window1 = PixelWindow(
            line_start=line_start1,
            sample_start=sample_start1,
            line_count=line_count1,
            sample_count=sample_count1,
        )
        window2 = PixelWindow(
            line_start=line_start2,
            sample_start=sample_start2,
            line_count=line_count2,
            sample_count=sample_count2,
        )
        result1 = window1.intersection(window2)
        result2 = window2.intersection(window1)
        assert result1 == result2

    @given(
        line_start1=st.integers(min_value=-1000, max_value=1000),
        sample_start1=st.integers(min_value=-1000, max_value=1000),
        line_count1=st.integers(min_value=1, max_value=500),
        sample_count1=st.integers(min_value=1, max_value=500),
        line_start2=st.integers(min_value=-1000, max_value=1000),
        sample_start2=st.integers(min_value=-1000, max_value=1000),
        line_count2=st.integers(min_value=1, max_value=500),
        sample_count2=st.integers(min_value=1, max_value=500),
    )
    def test_window_intersection_is_contained(
        self,
        line_start1: int,
        sample_start1: int,
        line_count1: int,
        sample_count1: int,
        line_start2: int,
        sample_start2: int,
        line_count2: int,
        sample_count2: int,
    ) -> None:
        """Window intersection is contained in both input windows."""
        window1 = PixelWindow(
            line_start=line_start1,
            sample_start=sample_start1,
            line_count=line_count1,
            sample_count=sample_count1,
        )
        window2 = PixelWindow(
            line_start=line_start2,
            sample_start=sample_start2,
            line_count=line_count2,
            sample_count=sample_count2,
        )
        intersection = window1.intersection(window2)
        if intersection is not None:
            assert window1.contains(intersection)
            assert window2.contains(intersection)

    @given(
        line_start=st.integers(min_value=-1000, max_value=1000),
        sample_start=st.integers(min_value=-1000, max_value=1000),
        line_count=st.integers(min_value=1, max_value=500),
        sample_count=st.integers(min_value=1, max_value=500),
    )
    def test_window_self_intersection_is_identity(
        self,
        line_start: int,
        sample_start: int,
        line_count: int,
        sample_count: int,
    ) -> None:
        """A window's intersection with itself is itself."""
        window = PixelWindow(
            line_start=line_start,
            sample_start=sample_start,
            line_count=line_count,
            sample_count=sample_count,
        )
        intersection = window.intersection(window)
        assert intersection == window

    @given(
        line_start1=st.integers(min_value=-1000, max_value=1000),
        sample_start1=st.integers(min_value=-1000, max_value=1000),
        line_count1=st.integers(min_value=1, max_value=500),
        sample_count1=st.integers(min_value=1, max_value=500),
        line_start2=st.integers(min_value=-1000, max_value=1000),
        sample_start2=st.integers(min_value=-1000, max_value=1000),
        line_count2=st.integers(min_value=1, max_value=500),
        sample_count2=st.integers(min_value=1, max_value=500),
    )
    def test_window_intersection_half_open_semantics(
        self,
        line_start1: int,
        sample_start1: int,
        line_count1: int,
        sample_count1: int,
        line_start2: int,
        sample_start2: int,
        line_count2: int,
        sample_count2: int,
    ) -> None:
        """Window intersection respects half-open semantics [start, stop)."""
        window1 = PixelWindow(
            line_start=line_start1,
            sample_start=sample_start1,
            line_count=line_count1,
            sample_count=sample_count1,
        )
        window2 = PixelWindow(
            line_start=line_start2,
            sample_start=sample_start2,
            line_count=line_count2,
            sample_count=sample_count2,
        )

        # Compute expected intersection bounds
        line_start = max(line_start1, line_start2)
        line_stop = min(line_start1 + line_count1, line_start2 + line_count2)
        sample_start = max(sample_start1, sample_start2)
        sample_stop = min(sample_start1 + sample_count1, sample_start2 + sample_count2)

        intersection = window1.intersection(window2)

        if line_stop <= line_start or sample_stop <= sample_start:
            # No intersection in half-open semantics
            assert intersection is None
        else:
            # There is an intersection
            assert intersection is not None
            assert intersection.line_start == line_start
            assert intersection.line_stop == line_stop
            assert intersection.sample_start == sample_start
            assert intersection.sample_stop == sample_stop
