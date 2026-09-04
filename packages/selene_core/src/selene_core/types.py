"""Shared coordinate, unit, covariance, and tiling types.

Implementation plan section 6.1. These contracts exist before the independent
algorithm branches so that their outputs are comparable.

Conventions enforced here:

* **Pixel centres.** The internal convention is zero-based and centre-referenced:
  the centre of the first pixel is ``line = 0.0, sample = 0.0`` (ADR-0001).
  ``SourcePixel`` and ``ReferencePixel`` always hold internal coordinates. The
  only way in or out of another convention is a named constructor or exporter.
  Inline half-pixel corrections are forbidden.
* **Units.** Angles carry ``_deg`` or ``_rad``. Distances carry ``_m``, ``_m2``,
  ``_px``, or ``_px2``. Durations carry ``_s``. Sizes carry ``_bytes``.
  ``tests/unit/test_unit_suffixes.py`` enforces this across every contract type.
* **Time.** UTC at interfaces, SPICE ephemeris time internally. The two are
  distinct types and this module deliberately provides no conversion between
  them, because that conversion needs furnished kernels (WP-03).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Self

__all__ = [
    "INTERNAL_PIXEL_CONVENTION",
    "AcquisitionInterval",
    "BodyFixedCoordinate",
    "Covariance2D",
    "CovarianceFrame",
    "EphemerisTime",
    "LocalWarpJacobian",
    "MapCoordinate",
    "MergeRule",
    "PixelConvention",
    "PixelWindow",
    "ReferencePixel",
    "SelenographicCoordinate",
    "SourcePixel",
    "TileSpec",
    "convert_pixel_coordinate",
]


# ---------------------------------------------------------------------------
# Pixel conventions (ADR-0001)
# ---------------------------------------------------------------------------


class PixelConvention(StrEnum):
    """A named image coordinate convention.

    The value of each member is the coordinate of the **centre of the first
    pixel** along one axis, expressed in that convention. That single number is
    all that distinguishes these conventions along an axis, so conversions are a
    documented table lookup rather than a literal sprinkled through the code.
    """

    SELENE_INTERNAL = "selene_internal"
    """Centre of the first pixel is 0.0. Zero-based and centre-referenced."""

    ARRAY_INDEX = "array_index"
    """NumPy indexing. Element ``[0]`` is the first pixel, so its centre is 0.0."""

    CSM = "csm"
    """Community Sensor Model image coordinates. First pixel centre is 0.5."""

    GDAL_CORNER = "gdal_corner"
    """GDAL geotransform pixel/line space, measured from the outer corner of the
    first pixel, so that pixel's centre is 0.5."""

    ISIS = "isis"
    """ISIS line/sample. One-based and centre-referenced, so the first pixel
    centre is 1.0."""


_FIRST_PIXEL_CENTRE: Final[dict[PixelConvention, float]] = {
    PixelConvention.SELENE_INTERNAL: 0.0,
    PixelConvention.ARRAY_INDEX: 0.0,
    PixelConvention.CSM: 0.5,
    PixelConvention.GDAL_CORNER: 0.5,
    PixelConvention.ISIS: 1.0,
}

INTERNAL_PIXEL_CONVENTION: Final = PixelConvention.SELENE_INTERNAL
"""The convention that every :class:`SourcePixel` and :class:`ReferencePixel`
holds. Declared once here so that no other module restates it."""


def convert_pixel_coordinate(
    value: float, *, source: PixelConvention, target: PixelConvention
) -> float:
    """Convert one axis of a pixel coordinate between conventions.

    Args:
        value: The coordinate in the ``source`` convention.
        source: The convention ``value`` is expressed in.
        target: The convention to express the result in.

    Returns:
        The same physical position expressed in ``target``.

    Raises:
        ValueError: If ``value`` is not finite.

    The offsets encoded here are the documented conventions of ISIS, CSM, and
    GDAL. WP-03 must confirm them against the real tools on a real product
    before any geometry claim depends on them; that verification is a stated
    exit criterion of WP-03, not an assumption this function may make.
    """
    if not math.isfinite(value):
        raise ValueError(f"pixel coordinate must be finite, got {value!r}")
    return value - _FIRST_PIXEL_CENTRE[source] + _FIRST_PIXEL_CENTRE[target]


@dataclass(frozen=True, slots=True)
class _Pixel:
    """Shared behaviour for image coordinates in the internal convention."""

    line: float
    sample: float

    def __post_init__(self) -> None:
        for name in ("line", "sample"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{type(self).__name__}.{name} must be finite, got {value!r}")

    @classmethod
    def from_convention(cls, line: float, sample: float, convention: PixelConvention) -> Self:
        """Build from a coordinate expressed in ``convention``."""
        return cls(
            line=convert_pixel_coordinate(
                line, source=convention, target=INTERNAL_PIXEL_CONVENTION
            ),
            sample=convert_pixel_coordinate(
                sample, source=convention, target=INTERNAL_PIXEL_CONVENTION
            ),
        )

    @classmethod
    def from_isis(cls, line: float, sample: float) -> Self:
        """Build from one-based, centre-referenced ISIS line/sample."""
        return cls.from_convention(line, sample, PixelConvention.ISIS)

    @classmethod
    def from_csm(cls, line: float, sample: float) -> Self:
        """Build from Community Sensor Model image coordinates."""
        return cls.from_convention(line, sample, PixelConvention.CSM)

    @classmethod
    def from_gdal(cls, pixel_x: float, line_y: float) -> Self:
        """Build from GDAL pixel/line space.

        GDAL orders its axes ``(x, y)``, the opposite of the ``(line, sample)``
        order used everywhere else here. The argument names make that reordering
        explicit at the call site instead of leaving it to be inferred.
        """
        return cls.from_convention(line_y, pixel_x, PixelConvention.GDAL_CORNER)

    @classmethod
    def from_array_index(cls, row: int, column: int) -> Self:
        """Build from a NumPy element index."""
        return cls.from_convention(float(row), float(column), PixelConvention.ARRAY_INDEX)

    def to_convention(self, convention: PixelConvention) -> tuple[float, float]:
        """Return ``(line, sample)`` expressed in ``convention``."""
        return (
            convert_pixel_coordinate(
                self.line, source=INTERNAL_PIXEL_CONVENTION, target=convention
            ),
            convert_pixel_coordinate(
                self.sample, source=INTERNAL_PIXEL_CONVENTION, target=convention
            ),
        )

    def to_isis(self) -> tuple[float, float]:
        """Return ``(line, sample)`` in ISIS convention."""
        return self.to_convention(PixelConvention.ISIS)

    def to_csm(self) -> tuple[float, float]:
        """Return ``(line, sample)`` in CSM convention."""
        return self.to_convention(PixelConvention.CSM)

    def to_gdal(self) -> tuple[float, float]:
        """Return ``(pixel_x, line_y)`` in GDAL convention, x first."""
        line, sample = self.to_convention(PixelConvention.GDAL_CORNER)
        return (sample, line)

    def to_array_index(self) -> tuple[int, int]:
        """Return the ``(row, column)`` of the pixel containing this position.

        Uses round-half-away-from-zero rather than Python's round-half-to-even,
        so that a coordinate exactly on a pixel boundary resolves consistently
        regardless of which pixel it borders.
        """
        return (_round_half_away(self.line), _round_half_away(self.sample))


def _round_half_away(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


@dataclass(frozen=True, slots=True)
class SourcePixel(_Pixel):
    """A position in the source (Chandrayaan-2) image, internal convention.

    Sub-pixel correspondence accuracy is evaluated in this frame (ADR-0003).
    """


@dataclass(frozen=True, slots=True)
class ReferencePixel(_Pixel):
    """A position in the reference (LRO or SELENE) image, internal convention."""


# ---------------------------------------------------------------------------
# Ground coordinates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MapCoordinate:
    """A projected coordinate, carrying the CRS it is meaningful in.

    The CRS travels with the coordinate because a bare easting and northing is
    indistinguishable between projections and between bodies. R-010 is the risk
    this guards against.
    """

    x_m: float
    y_m: float
    crs_wkt: str

    def __post_init__(self) -> None:
        _require_finite(self, "x_m", "y_m")
        if not self.crs_wkt.strip():
            raise ValueError("MapCoordinate.crs_wkt must name a CRS; an empty string is not one")


@dataclass(frozen=True, slots=True)
class BodyFixedCoordinate:
    """A rectangular body-fixed coordinate in a named lunar frame."""

    x_m: float
    y_m: float
    z_m: float
    frame: str

    def __post_init__(self) -> None:
        _require_finite(self, "x_m", "y_m", "z_m")
        if not self.frame.strip():
            raise ValueError("BodyFixedCoordinate.frame must be named, for example 'MOON_ME'")


@dataclass(frozen=True, slots=True)
class SelenographicCoordinate:
    """A planetocentric longitude, latitude, and radius in a named lunar frame.

    Radius, not elevation: an elevation is meaningless without also naming the
    vertical datum it is measured from, and that datum is unresolved (D-002).
    """

    longitude_deg: float
    latitude_deg: float
    radius_m: float
    frame: str

    def __post_init__(self) -> None:
        _require_finite(self, "longitude_deg", "latitude_deg", "radius_m")
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError(
                f"SelenographicCoordinate.latitude_deg must be within [-90, 90], "
                f"got {self.latitude_deg!r}"
            )
        if not -360.0 <= self.longitude_deg <= 360.0:
            raise ValueError(
                f"SelenographicCoordinate.longitude_deg must be within [-360, 360] before "
                f"normalisation, got {self.longitude_deg!r}"
            )
        if self.radius_m <= 0.0:
            raise ValueError(
                f"SelenographicCoordinate.radius_m must be positive, got {self.radius_m!r}"
            )
        if not self.frame.strip():
            raise ValueError("SelenographicCoordinate.frame must be named")

    @property
    def longitude_deg_east_positive(self) -> float:
        """Longitude normalised to ``[0, 360)`` east-positive.

        Products and reference archives disagree on whether longitude runs
        ``[-180, 180]`` or ``[0, 360)``. Normalising through a named property
        keeps the wrap in one tested place.
        """
        return self.longitude_deg % 360.0


# ---------------------------------------------------------------------------
# Local warp and uncertainty
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocalWarpJacobian:
    """The local linearisation of the source-to-reference mapping.

    Used to convert a residual or a covariance between the source and reference
    frames. A single scene-wide pixel scale is never substituted for this: local
    GSD varies with altitude, emission angle, and terrain across one pushbroom
    scene (WP-08 task 11).

    Entries are partial derivatives of reference pixel coordinates with respect
    to source pixel coordinates.
    """

    d_ref_line_d_src_line: float
    d_ref_line_d_src_sample: float
    d_ref_sample_d_src_line: float
    d_ref_sample_d_src_sample: float

    def __post_init__(self) -> None:
        _require_finite(
            self,
            "d_ref_line_d_src_line",
            "d_ref_line_d_src_sample",
            "d_ref_sample_d_src_line",
            "d_ref_sample_d_src_sample",
        )

    @property
    def determinant(self) -> float:
        """The local area scale factor from source to reference."""
        return (
            self.d_ref_line_d_src_line * self.d_ref_sample_d_src_sample
            - self.d_ref_line_d_src_sample * self.d_ref_sample_d_src_line
        )

    def inverse(self) -> LocalWarpJacobian:
        """Return the reference-to-source Jacobian.

        Raises:
            ValueError: If the Jacobian is singular or numerically close to it,
                in which case the local mapping is not invertible and a
                converted residual would be meaningless.
        """
        determinant = self.determinant
        if not math.isfinite(determinant) or abs(determinant) < 1e-12:
            raise ValueError(
                f"LocalWarpJacobian is singular (determinant {determinant!r}); "
                "the local mapping cannot be inverted"
            )
        return LocalWarpJacobian(
            d_ref_line_d_src_line=self.d_ref_sample_d_src_sample / determinant,
            d_ref_line_d_src_sample=-self.d_ref_line_d_src_sample / determinant,
            d_ref_sample_d_src_line=-self.d_ref_sample_d_src_line / determinant,
            d_ref_sample_d_src_sample=self.d_ref_line_d_src_line / determinant,
        )

    def apply(self, d_line_px: float, d_sample_px: float) -> tuple[float, float]:
        """Map a source-frame displacement into the reference frame."""
        return (
            self.d_ref_line_d_src_line * d_line_px + self.d_ref_line_d_src_sample * d_sample_px,
            self.d_ref_sample_d_src_line * d_line_px + self.d_ref_sample_d_src_sample * d_sample_px,
        )

    @classmethod
    def identity(cls) -> LocalWarpJacobian:
        """The unit Jacobian, meaning source and reference share a local frame."""
        return cls(1.0, 0.0, 0.0, 1.0)


class CovarianceFrame(StrEnum):
    """The frame a :class:`Covariance2D` is expressed in."""

    SOURCE_PIXEL = "source_pixel"
    REFERENCE_PIXEL = "reference_pixel"
    MAP = "map"


_COVARIANCE_UNITS: Final[dict[CovarianceFrame, str]] = {
    CovarianceFrame.SOURCE_PIXEL: "px2",
    CovarianceFrame.REFERENCE_PIXEL: "px2",
    CovarianceFrame.MAP: "m2",
}


@dataclass(frozen=True, slots=True)
class Covariance2D:
    """A two-dimensional positional covariance.

    Non-positive-definite covariance is rejected at construction (WP-08 task 5).
    A covariance that is merely *produced* is not calibrated; whether it has been
    validated against truth is tracked separately on the correspondence record,
    because R-008 is that a mathematically well-formed covariance can still be
    systematically wrong.

    The components are named ``xx``, ``xy``, and ``yy`` without a unit suffix
    because the ``units`` field carries the unit for all three; suffixing each
    component would duplicate it and allow the two to disagree.
    """

    xx: float
    xy: float
    yy: float
    frame: CovarianceFrame
    units: str

    def __post_init__(self) -> None:
        _require_finite(self, "xx", "xy", "yy")
        expected_units = _COVARIANCE_UNITS[self.frame]
        if self.units != expected_units:
            raise ValueError(
                f"Covariance2D in frame {self.frame} must use units {expected_units!r}, "
                f"got {self.units!r}"
            )
        if self.xx <= 0.0 or self.yy <= 0.0:
            raise ValueError(
                f"Covariance2D diagonal must be positive, got xx={self.xx!r}, yy={self.yy!r}"
            )
        determinant = self.xx * self.yy - self.xy * self.xy
        if determinant <= 0.0:
            raise ValueError(
                f"Covariance2D must be positive definite; determinant is {determinant!r}"
            )

    @classmethod
    def isotropic(cls, sigma: float, frame: CovarianceFrame) -> Covariance2D:
        """Build a circular covariance of standard deviation ``sigma``."""
        return cls(
            xx=sigma * sigma, xy=0.0, yy=sigma * sigma, frame=frame, units=_COVARIANCE_UNITS[frame]
        )

    @property
    def eigenvalues(self) -> tuple[float, float]:
        """The variances along the minor and major axes, ascending."""
        mean = 0.5 * (self.xx + self.yy)
        spread = math.hypot(0.5 * (self.xx - self.yy), self.xy)
        return (mean - spread, mean + spread)

    @property
    def sigma_minor(self) -> float:
        """Standard deviation along the best-constrained direction."""
        return math.sqrt(self.eigenvalues[0])

    @property
    def sigma_major(self) -> float:
        """Standard deviation along the worst-constrained direction."""
        return math.sqrt(self.eigenvalues[1])

    @property
    def anisotropy_ratio(self) -> float:
        """Major over minor standard deviation. One means circular.

        A large value means the measurement constrains one direction far better
        than the other, which is exactly the case that must be down-weighted
        directionally rather than collapsed to a scalar (WP-08 task 5).
        """
        return self.sigma_major / self.sigma_minor

    @property
    def orientation_deg(self) -> float:
        """Bearing of the major axis, in degrees, from the first axis."""
        return math.degrees(0.5 * math.atan2(2.0 * self.xy, self.xx - self.yy))

    def transformed(self, jacobian: LocalWarpJacobian, frame: CovarianceFrame) -> Covariance2D:
        """Propagate into another frame as ``J C Jᵀ``."""
        a, b = jacobian.d_ref_line_d_src_line, jacobian.d_ref_line_d_src_sample
        c, d = jacobian.d_ref_sample_d_src_line, jacobian.d_ref_sample_d_src_sample
        return Covariance2D(
            xx=a * a * self.xx + 2.0 * a * b * self.xy + b * b * self.yy,
            xy=a * c * self.xx + (a * d + b * c) * self.xy + b * d * self.yy,
            yy=c * c * self.xx + 2.0 * c * d * self.xy + d * d * self.yy,
            frame=frame,
            units=_COVARIANCE_UNITS[frame],
        )


# ---------------------------------------------------------------------------
# Tiling (WP-01 task 8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PixelWindow:
    """A half-open integer window in image space, in the internal convention.

    ``line_start`` and ``sample_start`` are inclusive; the stops are exclusive.
    """

    line_start: int
    sample_start: int
    line_count: int
    sample_count: int

    def __post_init__(self) -> None:
        if self.line_count <= 0 or self.sample_count <= 0:
            raise ValueError(
                f"PixelWindow must be non-empty, got line_count={self.line_count!r}, "
                f"sample_count={self.sample_count!r}"
            )

    @property
    def line_stop(self) -> int:
        """Exclusive upper bound on lines."""
        return self.line_start + self.line_count

    @property
    def sample_stop(self) -> int:
        """Exclusive upper bound on samples."""
        return self.sample_start + self.sample_count

    @property
    def area_px2(self) -> int:
        """Window area in pixels."""
        return self.line_count * self.sample_count

    def contains(self, other: PixelWindow) -> bool:
        """Whether ``other`` lies entirely within this window."""
        return (
            other.line_start >= self.line_start
            and other.sample_start >= self.sample_start
            and other.line_stop <= self.line_stop
            and other.sample_stop <= self.sample_stop
        )

    def intersection(self, other: PixelWindow) -> PixelWindow | None:
        """The overlap with ``other``, or ``None`` when they are disjoint."""
        line_start = max(self.line_start, other.line_start)
        sample_start = max(self.sample_start, other.sample_start)
        line_stop = min(self.line_stop, other.line_stop)
        sample_stop = min(self.sample_stop, other.sample_stop)
        if line_stop <= line_start or sample_stop <= sample_start:
            return None
        return PixelWindow(
            line_start=line_start,
            sample_start=sample_start,
            line_count=line_stop - line_start,
            sample_count=sample_stop - sample_start,
        )

    def padded(self, halo_px: int) -> PixelWindow:
        """This window grown by ``halo_px`` on every side."""
        if halo_px < 0:
            raise ValueError(f"halo_px must not be negative, got {halo_px!r}")
        return PixelWindow(
            line_start=self.line_start - halo_px,
            sample_start=self.sample_start - halo_px,
            line_count=self.line_count + 2 * halo_px,
            sample_count=self.sample_count + 2 * halo_px,
        )


class MergeRule(StrEnum):
    """How a tiled stage combines per-tile output into one result."""

    CORE_ONLY = "core_only"
    """Keep each tile's core window and discard its halo. The default for raster
    output, because halo pixels were computed with incomplete neighbourhoods."""

    FEATHER_HALO = "feather_halo"
    """Blend overlapping halos with a weight ramp. Only valid where the quantity
    is continuous and a blended value remains physically meaningful."""

    CONCATENATE = "concatenate"
    """Append per-tile records. For vector output where tiles cannot collide."""

    DEDUPLICATE_BY_POSITION = "deduplicate_by_position"
    """Append per-tile records, then resolve duplicates from overlapping halos
    deterministically. Required for tiled matching (WP-04 task 6)."""


@dataclass(frozen=True, slots=True)
class TileSpec:
    """The tiling, budget, and merge contract every raster stage declares.

    No stage may load a full OHRC frame (plan section 5.1). Declaring the budget
    alongside the geometry means a stage cannot quietly exceed it and blame the
    caller.
    """

    core_window: PixelWindow
    halo_px: int
    valid_window: PixelWindow
    merge_rule: MergeRule
    memory_budget_bytes: int
    scratch_budget_bytes: int

    def __post_init__(self) -> None:
        if self.halo_px < 0:
            raise ValueError(f"TileSpec.halo_px must not be negative, got {self.halo_px!r}")
        if self.memory_budget_bytes <= 0:
            raise ValueError(
                f"TileSpec.memory_budget_bytes must be positive, got {self.memory_budget_bytes!r}"
            )
        if self.scratch_budget_bytes < 0:
            raise ValueError(
                f"TileSpec.scratch_budget_bytes must not be negative, got "
                f"{self.scratch_budget_bytes!r}"
            )
        if not self.padded_window.contains(self.valid_window):
            raise ValueError(
                "TileSpec.valid_window must lie within the padded window; a stage cannot "
                "declare valid data it never read"
            )

    @property
    def padded_window(self) -> PixelWindow:
        """The core window plus its halo: the region the stage actually reads."""
        return self.core_window.padded(self.halo_px)

    @property
    def read_area_px2(self) -> int:
        """Pixels read, including halo."""
        return self.padded_window.area_px2

    @property
    def halo_overhead_ratio(self) -> float:
        """Read area divided by core area.

        Reported so that tiling overhead is measured rather than assumed
        (R-013).
        """
        return self.read_area_px2 / self.core_window.area_px2


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EphemerisTime:
    """SPICE ephemeris time, seconds past the J2000 epoch, in TDB.

    Kept distinct from :class:`datetime` so that the two cannot be mixed. This
    module provides no conversion to or from UTC: that requires furnished
    leapsecond kernels, which is WP-03's responsibility, not a type's.
    """

    et_s: float

    def __post_init__(self) -> None:
        _require_finite(self, "et_s")


@dataclass(frozen=True, slots=True)
class AcquisitionInterval:
    """The UTC interval an observation covers.

    Both bounds must be timezone-aware. A naive datetime is rejected rather than
    assumed to be UTC, because a silently wrong acquisition time produces a
    silently wrong pose.
    """

    start_utc: datetime
    stop_utc: datetime

    def __post_init__(self) -> None:
        for name in ("start_utc", "stop_utc"):
            value: datetime = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(
                    f"AcquisitionInterval.{name} must be timezone-aware; a naive datetime is "
                    "not assumed to be UTC"
                )
            if value.utcoffset() != UTC.utcoffset(None):
                raise ValueError(
                    f"AcquisitionInterval.{name} must be expressed in UTC, got offset "
                    f"{value.utcoffset()}"
                )
        if self.stop_utc < self.start_utc:
            raise ValueError(
                f"AcquisitionInterval must not end before it starts: "
                f"{self.start_utc.isoformat()} to {self.stop_utc.isoformat()}"
            )

    @property
    def duration_s(self) -> float:
        """Interval length in seconds."""
        return (self.stop_utc - self.start_utc).total_seconds()

    def contains(self, moment_utc: datetime) -> bool:
        """Whether ``moment_utc`` falls inside the closed interval."""
        if moment_utc.tzinfo is None:
            raise ValueError("moment_utc must be timezone-aware")
        return self.start_utc <= moment_utc <= self.stop_utc


def _require_finite(instance: object, *names: str) -> None:
    for name in names:
        value = getattr(instance, name)
        if not math.isfinite(value):
            raise ValueError(f"{type(instance).__name__}.{name} must be finite, got {value!r}")
