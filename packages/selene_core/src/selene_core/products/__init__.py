"""Raster, geometry, catalogue, report, and manifest writers (WP-09).

Responsibilities:

* Registered imagery as tiled COG/GeoTIFF with the full lunar CRS, nodata,
  overviews, source and job identifiers, and quality status.
* An adjusted CSM/ISIS-compatible geometry variant, written only where D-009
  has a passing round trip, leaving the original geometry intact.
* The correspondence catalogue as GeoPackage and CSV using the canonical schema,
  with GeoJSON as a convenience for bounded result sizes only.
* Validity, overlap, shadow and illumination, coverage, residual, and
  uncertainty layers with units and CRS. An offset raster is labelled
  ``three_sigma`` only when covariance is calibrated and its coverage
  assumption has been validated.
* Versioned JSON metric reports plus human-readable reports carrying the same
  values rather than recomputing them, and visualisations generated from the
  actual output files.
* A provenance manifest with hashes, sizes, media types, schemas, input and
  reference versions, control realisation, parameters, models, dependencies,
  code revision, environment, and limitations (ADR-006). An optional
  schema-validated STAC 1.0 export is an interoperability artefact, not the
  state authority.
"""

from selene_core.products.output_bundle import (
    BundleAlreadyExistsError,
    BundleArrayPayload,
    BundleConfig,
    BundleProvenance,
    BundleValidationResult,
    BundleWriteResult,
    OptionalProductStatus,
    ValidatedArtifact,
    validate_local_registration_bundle,
    write_local_registration_bundle,
)

__all__ = [
    "BundleAlreadyExistsError",
    "BundleArrayPayload",
    "BundleConfig",
    "BundleProvenance",
    "BundleValidationResult",
    "BundleWriteResult",
    "OptionalProductStatus",
    "ValidatedArtifact",
    "validate_local_registration_bundle",
    "write_local_registration_bundle",
]
