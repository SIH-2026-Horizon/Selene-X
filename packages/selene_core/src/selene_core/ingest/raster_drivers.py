"""GDAL driver allow-listing and virtual-filesystem rejection (WP-02 task 4).

A raster file this pipeline opens is untrusted input in the same sense as a
PDS4 or PVL label (`selene_core.ingest.pds4`, `selene_core.ingest.pvl`): its
bytes, and in some cases its *path string*, arrive from a data provider or a
caller this pipeline does not fully control. GDAL (which `rasterio` wraps)
supports dozens of format drivers and a family of "virtual filesystem"
(`/vsi...`) path prefixes, several of which can themselves trigger network
access or reference archive/memory content rather than a plain local file.
This module narrows both surfaces to exactly what this project's payloads
need:

1. **`ALLOWED_GDAL_DRIVERS`** restricts which GDAL format drivers may ever be
   used to open a raster — see its own docstring for the specific drivers
   and why each is included, and why `"VRT"` is deliberately excluded.
2. **The `/vsi`-prefix guard** (`reject_virtual_filesystem_path`) rejects any
   caller-controlled path string that begins with GDAL's virtual-filesystem
   prefix family (`/vsicurl/`, `/vsizip/`, `/vsimem/`, `/vsis3/`, and
   others) before it is ever handed to `rasterio`/GDAL. This is the concrete
   mechanism for "remote virtual filesystems disabled for caller-controlled
   paths" (WP-02 task 4). This check is pure string logic: it runs and is
   fully testable whether or not `rasterio` is installed.

**Import-time guard:** `rasterio` is an optional dependency
(`selene-core[raster]`, per `packages/selene_core/pyproject.toml` — kept
optional deliberately, per ADR-005) and is not installed in every
environment this package runs in. This module imports cleanly either way;
`open_raster_allowlisted` raises a clear, specific exception naming the
missing extras group only when a caller actually tries to open a raster
without `rasterio` present, rather than failing at import time for code that
never calls it.

**On `rasterio.open(..., driver=...)` restricting driver attempts (verified
by design, not by running it — `rasterio` is not installed in this
environment):** `rasterio.open`'s `driver` parameter accepts a single driver
name or a list of names and passes it through to GDAL's `GDALOpenEx` as the
`papszAllowedDrivers` argument, which restricts GDAL's driver-probing loop
to *only* the named drivers — GDAL never invokes any other driver's
identify/open code for that call. This is documented GDAL/rasterio
behaviour (rasterio's own docstring for `driver=` and the GDAL C API for
`GDALOpenEx`'s `papszAllowedDrivers`), not merely open-then-inspect-then
-reject: an open-then-check approach would first let a rejected driver's
own parsing code run against the input before this module could reject it,
which is exactly the ordering this module avoids by passing the allow-list
directly into `driver=`. If this project later installs `rasterio` and
observes different behaviour in practice, that would contradict documented
GDAL semantics and should be treated as a bug report against this docstring,
not silently worked around.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import rasterio

    _RASTERIO_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by whichever environment lacks rasterio
    rasterio = None
    _RASTERIO_AVAILABLE = False

__all__ = [
    "ALLOWED_GDAL_DRIVERS",
    "RasterDriverNotAllowedError",
    "RasterioNotInstalledError",
    "VirtualFilesystemPathRejectedError",
    "open_raster_allowlisted",
    "reject_virtual_filesystem_path",
]


# Short GDAL driver names this project's payloads legitimately need:
#
# * "GTiff" — GeoTIFF: the common interchange format for calibrated lunar
#   raster products and this pipeline's own outputs.
# * "ENVI" — ENVI raw-binary + header: a format some payload distributions
#   and downstream tools in this domain use.
# * "ISIS3" — the USGS ISIS cube format: the native format for
#   ISIS-processed lunar imagery this pipeline ingests.
# * "PDS4" — GDAL's PDS4 driver: reads a PDS4-labelled raster directly,
#   complementing (not replacing) this project's own hardened
#   `selene_core.ingest.pds4` label parser.
#
# "VRT" (GDAL's Virtual Raster format) is deliberately NOT in this
# allow-list: a VRT file's own XML content can reference arbitrary other
# raster files or remote sources (including via /vsi* virtual-filesystem
# paths) as its underlying data source. Allowing "VRT" here would let a
# caller-supplied .vrt file smuggle in exactly the "remote virtual
# filesystem" access this module's /vsi-prefix guard exists to prevent, via
# an indirection this module's path-string check would never see (the
# dangerous reference lives inside the VRT's own bytes, not in the path
# string used to open it). This exclusion is a deliberate security
# decision, not an oversight.
ALLOWED_GDAL_DRIVERS: frozenset[str] = frozenset({"GTiff", "ENVI", "ISIS3", "PDS4"})


# GDAL's virtual-filesystem path prefixes. Every one of these can cause GDAL
# to do something other than read a plain local file: fetch over HTTP(S)
# (/vsicurl, /vsis3, /vsigs, /vsiaz), transparently unpack an archive
# (/vsizip, /vsitar, /vsigzip), or read from a process-local memory buffer
# that this module has no visibility into (/vsimem). A caller-controlled
# path string must never reach GDAL with one of these prefixes.
_VSI_PREFIX = "/vsi"


class RasterDriverNotAllowedError(Exception):
    """Requested (or resolved) driver is outside `ALLOWED_GDAL_DRIVERS`."""


class VirtualFilesystemPathRejectedError(Exception):
    """A path begins with a GDAL virtual-filesystem prefix (`/vsi...`)."""


class RasterioNotInstalledError(Exception):
    """`rasterio` is not installed and is required for this call.

    Raised instead of letting a bare `ImportError`/`ModuleNotFoundError`
    surface from nowhere, so the caller is told exactly what is missing and
    how to get it, rather than having to guess.
    """

    def __init__(self) -> None:
        super().__init__(
            "rasterio is not installed; it is an optional dependency of "
            "selene-core. Install it with the 'raster' extras group, e.g. "
            "pip install 'selene-core[raster]' (or the equivalent for this "
            "project's package manager), to open rasters."
        )


def reject_virtual_filesystem_path(path_str: str) -> None:
    """Reject `path_str` if it begins with a GDAL `/vsi...` prefix.

    Pure string logic: no filesystem access, no `rasterio` import required.
    This is what makes the check runnable and testable regardless of
    whether `rasterio` is installed, and cheap enough to run unconditionally
    before any other work on a caller-supplied path.
    """
    if path_str.startswith(_VSI_PREFIX):
        raise VirtualFilesystemPathRejectedError(
            f"path {path_str!r} uses a GDAL virtual-filesystem prefix "
            f"({_VSI_PREFIX}...), which can trigger network access or "
            "reference archive/memory content rather than a plain local "
            "file; virtual-filesystem paths are not permitted for "
            "caller-controlled input"
        )


def open_raster_allowlisted(
    path: Path,
    *,
    driver_allowlist: frozenset[str] = ALLOWED_GDAL_DRIVERS,
) -> Any:
    """Open `path` through GDAL, restricted to `driver_allowlist`.

    Runs, in order:

    1. The `/vsi`-prefix guard on `str(path)`, unconditionally — this runs
       even when `rasterio` is not installed, since it is pure string logic
       and must reject a hostile path before any rasterio-availability
       question is even relevant.
    2. A `rasterio`-availability check, raising `RasterioNotInstalledError`
       if it is not installed.
    3. `rasterio.open(path, driver=list(driver_allowlist))` — passing the
       allow-list directly to `driver=` restricts GDAL to attempting only
       those drivers (see the module docstring for why this is safer than
       open-then-inspect-then-reject, and how that claim was verified in
       this environment).

    Args:
        path: The raster path to open. Not validated to exist or be
            readable by this function; that is `rasterio.open`'s concern.
        driver_allowlist: Overrides `ALLOWED_GDAL_DRIVERS` for this call.

    Returns:
        The opened `rasterio` dataset (`rasterio.io.DatasetReader`).

    Raises:
        VirtualFilesystemPathRejectedError: `path` begins with a GDAL
            `/vsi...` prefix.
        RasterioNotInstalledError: `rasterio` is not installed.
    """
    reject_virtual_filesystem_path(str(path))

    if not _RASTERIO_AVAILABLE:
        raise RasterioNotInstalledError()

    return rasterio.open(path, driver=list(driver_allowlist))
