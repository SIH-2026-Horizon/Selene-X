"""Tests for the GDAL driver allow-list and /vsi virtual-filesystem guard
(WP-02 task 4).

`rasterio` is not installed in this environment (confirmed in the task
brief); tests that genuinely require opening a real raster through it are
marked `@pytest.mark.integration` and skipped via
`_RASTERIO_AVAILABLE`-guarded `skipif`, so they document what should be
verified once the optional `raster` extras group is installed, without
silently vanishing from the suite. Every other test here — including the
`/vsi`-prefix guard — runs unconditionally in this environment, since it is
pure string logic that does not depend on `rasterio` being present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from selene_core.ingest.raster_drivers import (
    _RASTERIO_AVAILABLE,
    ALLOWED_GDAL_DRIVERS,
    RasterioNotInstalledError,
    VirtualFilesystemPathRejectedError,
    open_raster_allowlisted,
    reject_virtual_filesystem_path,
)

pytestmark = pytest.mark.security


# --------------------------------------------------------------------------
# Driver allow-list contents
# --------------------------------------------------------------------------


def test_vrt_is_not_in_the_driver_allowlist() -> None:
    assert "VRT" not in ALLOWED_GDAL_DRIVERS


def test_allowlist_contains_the_expected_baseline_drivers() -> None:
    assert ALLOWED_GDAL_DRIVERS == frozenset({"GTiff", "ENVI", "ISIS3", "PDS4"})


# --------------------------------------------------------------------------
# /vsi guard: must run and reject regardless of whether rasterio is installed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vsi_path",
    [
        "/vsicurl/http://example.com/evil.tif",
        "/vsizip/some/archive.zip/inner.tif",
        "/vsimem/in_memory.tif",
    ],
)
def test_vsi_prefixed_path_is_rejected_by_the_guard_directly(vsi_path: str) -> None:
    with pytest.raises(VirtualFilesystemPathRejectedError):
        reject_virtual_filesystem_path(vsi_path)


@pytest.mark.parametrize(
    "vsi_path",
    [
        "/vsicurl/http://example.com/evil.tif",
        "/vsizip/some/archive.zip/inner.tif",
        "/vsimem/in_memory.tif",
    ],
)
def test_vsi_prefixed_path_is_rejected_via_open_raster_allowlisted(vsi_path: str) -> None:
    """The guard runs first inside `open_raster_allowlisted`, so this must
    reject with `VirtualFilesystemPathRejectedError` — never
    `RasterioNotInstalledError` — even though `rasterio` is unavailable in
    this environment. This is the direct proof that the test is not skipped
    and genuinely exercises the guard here.
    """
    with pytest.raises(VirtualFilesystemPathRejectedError):
        open_raster_allowlisted(Path(vsi_path))


def test_vsi_guard_test_actually_runs_in_this_environment() -> None:
    """Sanity check: `rasterio` really is unavailable here, so the two tests
    above are proof the guard fires independently of `rasterio`, not proof
    of something rasterio-specific.
    """
    assert _RASTERIO_AVAILABLE is False


# --------------------------------------------------------------------------
# Plain local path: /vsi guard itself must not fire
# --------------------------------------------------------------------------


def test_plain_local_path_is_not_rejected_by_the_vsi_guard_itself(tmp_path: Path) -> None:
    # The guard function directly: a plain path never raises from it at all.
    reject_virtual_filesystem_path(str(tmp_path / "not-vsi-prefixed.tif"))


def test_plain_local_path_through_open_raster_allowlisted_fails_for_a_different_reason(
    tmp_path: Path,
) -> None:
    """A plain (non-`/vsi`) path must not be rejected by the `/vsi` guard.
    In this environment (no `rasterio`), `open_raster_allowlisted` still
    raises — but as `RasterioNotInstalledError`, a distinct exception type
    from `VirtualFilesystemPathRejectedError`, proving the vsi guard itself
    did not fire for this path.
    """
    with pytest.raises(RasterioNotInstalledError):
        open_raster_allowlisted(tmp_path / "not-vsi-prefixed.tif")


# --------------------------------------------------------------------------
# rasterio-unavailable behaviour: a clear, specific exception
# --------------------------------------------------------------------------


@pytest.mark.skipif(_RASTERIO_AVAILABLE, reason="only meaningful when rasterio is NOT installed")
def test_open_raster_allowlisted_raises_clear_error_when_rasterio_unavailable(
    tmp_path: Path,
) -> None:
    with pytest.raises(RasterioNotInstalledError) as excinfo:
        open_raster_allowlisted(tmp_path / "plain-local-path.tif")

    message = str(excinfo.value)
    assert "raster" in message
    assert "install" in message.lower()


# --------------------------------------------------------------------------
# Integration tests requiring a real rasterio install (skipped here)
# --------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(not _RASTERIO_AVAILABLE, reason="requires rasterio to be installed")
def test_open_raster_allowlisted_opens_an_allowlisted_local_geotiff(tmp_path: Path) -> None:
    """Once `rasterio` is installed: opening a real, plain local GeoTIFF
    through `open_raster_allowlisted` with the default allow-list should
    succeed and return an open dataset whose driver is in
    `ALLOWED_GDAL_DRIVERS`.
    """
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    tif_path = tmp_path / "sample.tif"
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 4, 1, 1),
    ) as dst:
        dst.write(np.zeros((4, 4), dtype="uint8"), 1)

    with open_raster_allowlisted(tif_path) as dataset:
        assert dataset.driver in ALLOWED_GDAL_DRIVERS


@pytest.mark.integration
@pytest.mark.skipif(not _RASTERIO_AVAILABLE, reason="requires rasterio to be installed")
def test_open_raster_allowlisted_rejects_a_disallowed_driver(tmp_path: Path) -> None:
    """Once `rasterio` is installed: a real VRT file (a format outside
    `ALLOWED_GDAL_DRIVERS`) referencing a plain local GeoTIFF should fail to
    open via `open_raster_allowlisted`'s restricted `driver=` allow-list,
    proving the restriction rejects a disallowed driver rather than silently
    succeeding. Uses `rasterio.errors.RasterioIOError`, GDAL's documented
    exception when `GDALOpenEx`'s `papszAllowedDrivers` excludes every
    driver capable of opening the file.
    """
    import numpy as np
    import rasterio
    from rasterio.errors import RasterioIOError
    from rasterio.transform import from_origin

    tif_path = tmp_path / "sample_for_vrt.tif"
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(0, 4, 1, 1),
    ) as dst:
        dst.write(np.zeros((4, 4), dtype="uint8"), 1)

    vrt_path = tmp_path / "sample.vrt"
    with rasterio.open(tif_path) as src, rasterio.vrt.WarpedVRT(src) as vrt:
        vrt_path.write_bytes(vrt.to_vrt_string().encode("utf-8"))

    with pytest.raises(RasterioIOError):
        open_raster_allowlisted(vrt_path)
