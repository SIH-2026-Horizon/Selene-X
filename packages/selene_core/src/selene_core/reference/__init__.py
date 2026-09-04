"""Reference imagery, terrain, and control adapters (WP-03).

Responsibilities:

* LROC NAC and SELENE/Kaguya Terrain Camera image adapters with catalogued
  control status.
* Terrain and control adapters for SLDEM, LOLA, controlled mosaics, polar
  products, and regional NAC DTMs. SLDEM2015 is treated as roughly 60 m/pixel
  at the equator and limited to about 60 degrees south to 60 degrees north;
  LOLA or an appropriate polar product is selected outside that coverage.
* A versioned reference bundle recording exact versions, coverage, resolution,
  horizontal and vertical uncertainty, masks, and resampling history
  (plan section 6.3).
* A hard distinction between image reference and geodetic control. An
  uncontrolled image is never silently promoted to datum status (ADR-004).
"""

from selene_core.reference.bundle import (
    ReferenceAsset,
    ReferenceBundle,
    ReferenceKind,
    ReferenceRole,
    TerrainSelection,
    control_network_adapter,
    lola_adapter,
    lroc_nac_adapter,
    polar_dem_adapter,
    select_terrain_reference,
    selene_tc_adapter,
    sldem2015_adapter,
)

__all__ = [
    "ReferenceAsset",
    "ReferenceBundle",
    "ReferenceKind",
    "ReferenceRole",
    "TerrainSelection",
    "control_network_adapter",
    "lola_adapter",
    "lroc_nac_adapter",
    "polar_dem_adapter",
    "select_terrain_reference",
    "selene_tc_adapter",
    "sldem2015_adapter",
]
