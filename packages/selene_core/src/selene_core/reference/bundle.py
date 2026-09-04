"""Versioned lunar image, terrain, and control reference declarations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from selene_core.geometry.contracts import Footprint

__all__ = [
    "ReferenceAsset",
    "ReferenceBundle",
    "ReferenceKind",
    "ReferenceRole",
    "TerrainSelection",
    "lroc_nac_adapter",
    "select_terrain_reference",
    "selene_tc_adapter",
]


class ReferenceKind(StrEnum):
    LROC_NAC = "lroc_nac"
    SELENE_TC = "selene_tc"
    SLDEM2015 = "sldem2015"
    LOLA = "lola"
    POLAR_DEM = "polar_dem"
    NAC_DTM = "nac_dtm"
    CONTROLLED_MOSAIC = "controlled_mosaic"
    CONTROL_NETWORK = "control_network"


class ReferenceRole(StrEnum):
    IMAGE = "image"
    TERRAIN = "terrain"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class ReferenceAsset:
    """Reference metadata, including its authority boundary and known coverage."""

    identifier: str
    kind: ReferenceKind
    role: ReferenceRole
    version: str
    footprint: Footprint | None
    native_gsd_m: float | None
    horizontal_uncertainty_m: float | None
    vertical_uncertainty_m: float | None
    controlled: bool
    coverage_description: str
    resampling_history: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    latitude_coverage_deg: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if (
            not self.identifier.strip()
            or not self.version.strip()
            or not self.coverage_description.strip()
        ):
            raise ValueError("identifier, version, and coverage_description must be non-empty")
        for name in ("native_gsd_m", "horizontal_uncertainty_m", "vertical_uncertainty_m"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be None or a non-negative finite value")
        if self.role is ReferenceRole.CONTROL and not self.controlled:
            raise ValueError("a control asset must be explicitly controlled")
        if self.latitude_coverage_deg is not None:
            low, high = self.latitude_coverage_deg
            if (
                not all(math.isfinite(value) for value in self.latitude_coverage_deg)
                or not -90 <= low <= high <= 90
            ):
                raise ValueError("latitude_coverage_deg must be ordered and within [-90, 90]")

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "kind": self.kind.value,
            "role": self.role.value,
            "version": self.version,
            "native_gsd_m": self.native_gsd_m,
            "horizontal_uncertainty_m": self.horizontal_uncertainty_m,
            "vertical_uncertainty_m": self.vertical_uncertainty_m,
            "controlled": self.controlled,
            "coverage_description": self.coverage_description,
            "resampling_history": list(self.resampling_history),
            "limitations": list(self.limitations),
            "footprint_validation": self.footprint.validation.value
            if self.footprint
            else "unavailable",
            "latitude_coverage_deg": list(self.latitude_coverage_deg)
            if self.latitude_coverage_deg
            else None,
        }

    def covers_latitude(self, latitude_deg: float) -> bool:
        """Return declared latitude coverage, never infer it from a text label."""
        return self.latitude_coverage_deg is not None and (
            self.latitude_coverage_deg[0] <= latitude_deg <= self.latitude_coverage_deg[1]
        )


@dataclass(frozen=True, slots=True)
class ReferenceBundle:
    """Immutable, versioned input bundle required by route qualification."""

    bundle_id: str
    version: str
    assets: tuple[ReferenceAsset, ...]
    manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.bundle_id.strip() or not self.version.strip() or not self.assets:
            raise ValueError("bundle_id, version, and at least one asset are required")
        identifiers = [asset.identifier for asset in self.assets]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("reference bundle asset identifiers must be unique")
        if self.manifest_sha256 is not None and (
            len(self.manifest_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.manifest_sha256.lower())
        ):
            raise ValueError("manifest_sha256 must be a lower/upper hexadecimal SHA-256")

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "version": self.version,
            "manifest_sha256": self.manifest_sha256,
            "assets": [asset.to_dict() for asset in self.assets],
        }

    @property
    def has_geodetic_control(self) -> bool:
        """True only for an explicitly designated control reference."""
        return any(
            asset.role is ReferenceRole.CONTROL and asset.controlled for asset in self.assets
        )

    def has_geodetic_control_for_latitudes(self, latitude_bounds_deg: tuple[float, float]) -> bool:
        """Require one named control asset to cover the complete route latitude span."""
        low, high = latitude_bounds_deg
        return any(
            asset.role is ReferenceRole.CONTROL
            and asset.controlled
            and asset.latitude_coverage_deg is not None
            and asset.latitude_coverage_deg[0] <= low <= high <= asset.latitude_coverage_deg[1]
            for asset in self.assets
        )

    def has_qualified_geodetic_control_for_latitudes(
        self, latitude_bounds_deg: tuple[float, float]
    ) -> bool:
        """Require coverage plus a stated positive horizontal uncertainty budget."""
        low, high = latitude_bounds_deg
        return any(
            asset.role is ReferenceRole.CONTROL
            and asset.controlled
            and asset.horizontal_uncertainty_m is not None
            and math.isfinite(asset.horizontal_uncertainty_m)
            and asset.horizontal_uncertainty_m > 0
            and asset.latitude_coverage_deg is not None
            and asset.latitude_coverage_deg[0] <= low <= high <= asset.latitude_coverage_deg[1]
            for asset in self.assets
        )


def lroc_nac_adapter(
    *,
    identifier: str,
    version: str,
    footprint: Footprint | None,
    native_gsd_m: float | None,
    controlled: bool = False,
    horizontal_uncertainty_m: float | None = None,
) -> ReferenceAsset:
    """Declare an LROC NAC image; it remains image evidence, not a datum."""
    return ReferenceAsset(
        identifier,
        ReferenceKind.LROC_NAC,
        ReferenceRole.IMAGE,
        version,
        footprint,
        native_gsd_m,
        horizontal_uncertainty_m,
        None,
        controlled,
        "catalogue-provided LROC NAC footprint",
        limitations=("image reference is not geodetic control",),
    )


def selene_tc_adapter(
    *,
    identifier: str,
    version: str,
    footprint: Footprint | None,
    native_gsd_m: float | None,
    controlled: bool = False,
    horizontal_uncertainty_m: float | None = None,
) -> ReferenceAsset:
    """Declare a SELENE/Kaguya Terrain Camera image with its control status."""
    return ReferenceAsset(
        identifier,
        ReferenceKind.SELENE_TC,
        ReferenceRole.IMAGE,
        version,
        footprint,
        native_gsd_m,
        horizontal_uncertainty_m,
        None,
        controlled,
        "catalogue-provided SELENE TC footprint",
        limitations=("image reference is not geodetic control",),
    )


def sldem2015_adapter(
    *, identifier: str, version: str, horizontal_uncertainty_m: float, vertical_uncertainty_m: float
) -> ReferenceAsset:
    """Declare SLDEM2015 as coarse terrain support only within its stated coverage."""
    return ReferenceAsset(
        identifier,
        ReferenceKind.SLDEM2015,
        ReferenceRole.TERRAIN,
        version,
        None,
        60.0,
        horizontal_uncertainty_m,
        vertical_uncertainty_m,
        True,
        "approximately 60S to 60N",
        limitations=("coarse terrain support only; never fine matching texture",),
        latitude_coverage_deg=(-60.0, 60.0),
    )


def lola_adapter(
    *,
    identifier: str,
    version: str,
    horizontal_uncertainty_m: float,
    vertical_uncertainty_m: float,
    latitude_coverage_deg: tuple[float, float] = (-90.0, 90.0),
) -> ReferenceAsset:
    """Declare LOLA terrain/control support with explicit coverage and uncertainty."""
    return ReferenceAsset(
        identifier,
        ReferenceKind.LOLA,
        ReferenceRole.TERRAIN,
        version,
        None,
        None,
        horizontal_uncertainty_m,
        vertical_uncertainty_m,
        True,
        "declared LOLA coverage",
        limitations=("terrain/control support, not image texture",),
        latitude_coverage_deg=latitude_coverage_deg,
    )


def polar_dem_adapter(
    *,
    identifier: str,
    version: str,
    native_gsd_m: float,
    horizontal_uncertainty_m: float,
    vertical_uncertainty_m: float,
    latitude_coverage_deg: tuple[float, float],
) -> ReferenceAsset:
    """Declare a polar DEM; coverage must actually include one polar cap."""
    if latitude_coverage_deg[0] > -75.0 and latitude_coverage_deg[1] < 75.0:
        raise ValueError("polar DEM coverage must include a polar latitude")
    return ReferenceAsset(
        identifier,
        ReferenceKind.POLAR_DEM,
        ReferenceRole.TERRAIN,
        version,
        None,
        native_gsd_m,
        horizontal_uncertainty_m,
        vertical_uncertainty_m,
        True,
        "declared polar DEM coverage",
        limitations=("terrain support only",),
        latitude_coverage_deg=latitude_coverage_deg,
    )


def control_network_adapter(
    *,
    identifier: str,
    version: str,
    horizontal_uncertainty_m: float,
    latitude_coverage_deg: tuple[float, float],
) -> ReferenceAsset:
    """Declare a named geodetic control realisation for absolute-accuracy routes."""
    return ReferenceAsset(
        identifier,
        ReferenceKind.CONTROL_NETWORK,
        ReferenceRole.CONTROL,
        version,
        None,
        None,
        horizontal_uncertainty_m,
        None,
        True,
        "declared control-network coverage",
        latitude_coverage_deg=latitude_coverage_deg,
    )


@dataclass(frozen=True, slots=True)
class TerrainSelection:
    asset: ReferenceAsset | None
    available: bool
    reason: str


def select_terrain_reference(
    assets: tuple[ReferenceAsset, ...], *, latitude_deg: float
) -> TerrainSelection:
    """Choose terrain conservatively; SLDEM is not fine image texture.

    SLDEM2015 is accepted only inside its stated approximately ±60° latitude
    coverage and is labelled terrain support, never a high-frequency matching
    channel.  Outside that range, a polar DEM is preferred, then LOLA.
    """
    if not math.isfinite(latitude_deg) or not -90 <= latitude_deg <= 90:
        raise ValueError("latitude_deg must be finite and in [-90, 90]")
    terrain = tuple(
        asset
        for asset in assets
        if asset.role is ReferenceRole.TERRAIN and asset.covers_latitude(latitude_deg)
    )
    if abs(latitude_deg) <= 60:
        candidate = next(
            (asset for asset in terrain if asset.kind is ReferenceKind.SLDEM2015), None
        )
        if candidate:
            return TerrainSelection(
                candidate, True, "SLDEM2015 selected for terrain support only; not fine texture"
            )
    polar = next((asset for asset in terrain if asset.kind is ReferenceKind.POLAR_DEM), None)
    if polar:
        return TerrainSelection(polar, True, "polar terrain product selected")
    lola = next((asset for asset in terrain if asset.kind is ReferenceKind.LOLA), None)
    if lola:
        return TerrainSelection(lola, True, "LOLA selected as available terrain/control support")
    return TerrainSelection(
        None,
        False,
        "no terrain asset covers requested latitude; terrain-dependent route is unavailable",
    )
