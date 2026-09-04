"""Product ingestion, safe label parsing, and payload adapters (WP-02).

Responsibilities:

* Registration by manifest and local path for the trusted CLI only. API upload
  registration arrives in WP-10 through server-generated storage identifiers and
  never accepts a caller-supplied server path.
* PDS4 XML parsing with DTD loading, entity expansion, and external entity
  resolution disabled, under size and recursion limits.
* ISIS/PVL parsing under equivalent limits.
* Raster opening through a GDAL driver allow-list with remote virtual
  filesystems disabled for caller-controlled paths.
* Checksum, label, dimension, dtype, nodata, band, calibration-state, and
  acquisition-interval validation.
* A shared ``PayloadAdapter`` protocol plus OHRC, TMC-2, and IIRS adapters. The
  IIRS adapter carries an explicit machine-readable ``geometry_validated``
  state and stays incomplete until D-004 is resolved.
* SPICE kernel allow-listing with recorded names, hashes, coverage, priority,
  and reconstructed-versus-predicted status.
* Quarantine with stable reasons and re-validation after correction.
* Native tool invocation only through an argument-array, shell-disabled
  subprocess helper with an allow-listed environment and resource limits.
"""

__all__: list[str] = []
