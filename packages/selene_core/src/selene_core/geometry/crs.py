"""Lunar CRS serialization and projection choice without a pyproj dependency."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from selene_core.geometry.contracts import GroundPoint, normalize_longitude_deg
from selene_core.types import MapCoordinate

__all__ = ["LUNAR_MEAN_RADIUS_M", "LunarCrs", "Projection", "select_lunar_crs"]

LUNAR_MEAN_RADIUS_M = 1_737_400.0


class Projection(StrEnum):
    EQUIRECTANGULAR = "equirectangular"
    NORTH_POLAR_STEREOGRAPHIC = "north_polar_stereographic"
    SOUTH_POLAR_STEREOGRAPHIC = "south_polar_stereographic"


@dataclass(frozen=True, slots=True)
class LunarCrs:
    """Fully serializable Moon-only CRS declaration.

    The WKT is deliberately constructed locally so it stays available in base
    installs. Consumers that require authoritative transformation operations
    must use optional ``pyproj`` and retain this serialization unchanged.
    """

    projection: Projection
    central_meridian_deg: float
    latitude_of_origin_deg: float
    body_radius_m: float = LUNAR_MEAN_RADIUS_M
    body_fixed_frame: str = "MOON_ME"
    longitude_positive: str = "east"
    standard_parallel_deg: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "central_meridian_deg",
            "latitude_of_origin_deg",
            "standard_parallel_deg",
            "body_radius_m",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.body_radius_m <= 0 or self.longitude_positive != "east":
            raise ValueError("CRS must use a positive radius and east-positive lunar longitude")
        if not self.body_fixed_frame.strip():
            raise ValueError("body_fixed_frame must be non-empty")
        if (
            self.projection is Projection.EQUIRECTANGULAR
            and abs(self.standard_parallel_deg) >= 89.999
        ):
            raise ValueError("equirectangular standard parallel is singular near a pole")
        if self.projection is Projection.NORTH_POLAR_STEREOGRAPHIC and (
            self.latitude_of_origin_deg != 90.0 or self.standard_parallel_deg != 90.0
        ):
            raise ValueError(
                "north polar stereographic requires 90 degree origin and standard parallel"
            )
        if self.projection is Projection.SOUTH_POLAR_STEREOGRAPHIC and (
            self.latitude_of_origin_deg != -90.0 or self.standard_parallel_deg != -90.0
        ):
            raise ValueError(
                "south polar stereographic requires -90 degree origin and standard parallel"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "projection": self.projection.value,
            "central_meridian_deg": self.central_meridian_deg,
            "latitude_of_origin_deg": self.latitude_of_origin_deg,
            "standard_parallel_deg": self.standard_parallel_deg,
            "body_radius_m": self.body_radius_m,
            "body_fixed_frame": self.body_fixed_frame,
            "longitude_positive": self.longitude_positive,
            "wkt": self.to_wkt(),
        }

    def to_wkt(self) -> str:
        """Return an explicit Moon-only WKT2-like string (never an Earth EPSG CRS)."""
        method = {
            Projection.EQUIRECTANGULAR: "Equidistant Cylindrical",
            Projection.NORTH_POLAR_STEREOGRAPHIC: "Polar Stereographic (variant A)",
            Projection.SOUTH_POLAR_STEREOGRAPHIC: "Polar Stereographic (variant A)",
        }[self.projection]
        return (
            'PROJCRS["Moon ' + self.projection.value + '",'
            'BASEGEOGCRS["Moon ' + self.body_fixed_frame + '",DATUM["Moon",ELLIPSOID["Moon sphere",'
            f"{self.body_radius_m},0]],"
            'PRIMEM["Reference Meridian",0],'
            'ANGLEUNIT["degree",0.0174532925199433]],'
            f'CONVERSION["{method}",METHOD["{method}"],PARAMETER["Longitude of natural origin",'
            f"{self.central_meridian_deg}],"
            f'PARAMETER["Latitude of natural origin",{self.latitude_of_origin_deg}],'
            f'PARAMETER["Latitude of 1st standard parallel",{self.standard_parallel_deg}]],'
            'CS[Cartesian,2],AXIS["Easting",east],AXIS["Northing",north],LENGTHUNIT["metre",1]]'
        )

    def project(self, ground: GroundPoint) -> MapCoordinate:
        """Project a lunar coordinate with the declared spherical CRS parameters."""
        longitude = math.radians(
            normalize_longitude_deg(ground.longitude_deg - self.central_meridian_deg)
        )
        latitude = math.radians(ground.latitude_deg)
        if self.projection is Projection.EQUIRECTANGULAR:
            x_m = (
                self.body_radius_m * longitude * math.cos(math.radians(self.standard_parallel_deg))
            )
            y_m = self.body_radius_m * (latitude - math.radians(self.latitude_of_origin_deg))
        elif self.projection is Projection.NORTH_POLAR_STEREOGRAPHIC:
            rho = 2 * self.body_radius_m * math.tan(math.pi / 4 - latitude / 2)
            x_m, y_m = rho * math.sin(longitude), -rho * math.cos(longitude)
        else:
            rho = 2 * self.body_radius_m * math.tan(math.pi / 4 + latitude / 2)
            x_m, y_m = rho * math.sin(longitude), rho * math.cos(longitude)
        return MapCoordinate(x_m, y_m, self.to_wkt())

    def unproject(self, coordinate: MapCoordinate) -> GroundPoint:
        """Invert :meth:`project`; a foreign CRS is rejected rather than guessed."""
        if coordinate.crs_wkt != self.to_wkt():
            raise ValueError("coordinate CRS does not match this lunar CRS")
        if self.projection is Projection.EQUIRECTANGULAR:
            cosine = math.cos(math.radians(self.standard_parallel_deg))
            if abs(cosine) < 1e-12:
                raise ValueError("equirectangular standard parallel is singular at a pole")
            longitude = coordinate.x_m / (self.body_radius_m * cosine)
            latitude = coordinate.y_m / self.body_radius_m + math.radians(
                self.latitude_of_origin_deg
            )
        elif self.projection is Projection.NORTH_POLAR_STEREOGRAPHIC:
            rho = math.hypot(coordinate.x_m, coordinate.y_m)
            latitude = math.pi / 2 - 2 * math.atan2(rho, 2 * self.body_radius_m)
            longitude = math.atan2(coordinate.x_m, -coordinate.y_m)
        else:
            rho = math.hypot(coordinate.x_m, coordinate.y_m)
            latitude = -math.pi / 2 + 2 * math.atan2(rho, 2 * self.body_radius_m)
            longitude = math.atan2(coordinate.x_m, coordinate.y_m)
        return GroundPoint(
            math.degrees(latitude),
            normalize_longitude_deg(math.degrees(longitude) + self.central_meridian_deg),
        )


def select_lunar_crs(
    *, latitude_bounds_deg: tuple[float, float], longitude_anchor_deg: float = 0.0
) -> LunarCrs:
    """Select polar stereographic near either pole; otherwise equirectangular."""
    low, high = latitude_bounds_deg
    if not -90 <= low <= high <= 90:
        raise ValueError("latitude_bounds_deg must be ordered and within [-90, 90]")
    if not math.isfinite(longitude_anchor_deg):
        raise ValueError("longitude_anchor_deg must be finite")
    if high >= 75.0 and low <= -75.0:
        raise ValueError("footprint spans both polar caps; split it before projection selection")
    if high >= 75.0 and low < 0.0:
        raise ValueError(
            "north polar route crosses hemispheres; split it before projection selection"
        )
    if low <= -75.0 and high > 0.0:
        raise ValueError(
            "south polar route crosses hemispheres; split it before projection selection"
        )
    if high >= 75.0:
        return LunarCrs(
            Projection.NORTH_POLAR_STEREOGRAPHIC,
            longitude_anchor_deg,
            90.0,
            standard_parallel_deg=90.0,
        )
    if low <= -75.0:
        return LunarCrs(
            Projection.SOUTH_POLAR_STEREOGRAPHIC,
            longitude_anchor_deg,
            -90.0,
            standard_parallel_deg=-90.0,
        )
    return LunarCrs(
        Projection.EQUIRECTANGULAR,
        longitude_anchor_deg,
        0.0,
        standard_parallel_deg=0.0,
    )
