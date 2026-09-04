"""Auditable output bundles for local, explicitly non-qualified runs.

The product layer deliberately receives the pipeline result as a structural
object rather than importing ``selene_core.pipeline``: products sit below the
pipeline in the core layering contract.  This also makes validation entirely
independent of matching execution.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import numpy as np
import numpy.typing as npt
from pydantic import Field, model_validator

from selene_core.contracts import Contract
from selene_core.hashing import digest_file
from selene_core.products.correspondence_catalogue import (
    read_correspondence_csv,
    write_correspondence_csv,
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

_MANIFEST_NAME = "manifest.json"
_METRICS_NAME = "metrics.json"
_CATALOGUE_NAME = "correspondences.csv"
_BUNDLE_SCHEMA_VERSION = "local-registration-output-bundle/v1"
_REQUIRED_ARTIFACTS = frozenset(
    {
        _CATALOGUE_NAME,
        _METRICS_NAME,
        "source.npy",
        "reference.npy",
        "source-validity-mask.npy",
        "reference-validity-mask.npy",
        "coverage-mask.npy",
        "overlap-mask.unavailable.json",
    }
)


class BundleAlreadyExistsError(FileExistsError):
    """A destination has existing data and replacement was not explicitly allowed."""


@dataclass(frozen=True, slots=True)
class BundleArrayPayload:
    """Actual local arrays retained by the caller for output publication.

    ``PipelineResult`` deliberately holds only serializable handles, so this
    explicit companion prevents the product writer from fabricating pixels or
    masks. Omitted validity masks are derived from finite source/reference
    values and recorded as such. Overlap data is not accepted: a local result
    has no validated spatial relation through which to interpret it.
    """

    source: npt.NDArray[np.generic]
    reference: npt.NDArray[np.generic]
    source_validity_mask: npt.NDArray[np.bool_] | None = None
    reference_validity_mask: npt.NDArray[np.bool_] | None = None


class _LocalRegistrationResult(Protocol):
    """The product-facing structural surface of pipeline's ``PipelineResult``.

    Importing that concrete pipeline type would violate the products/pipeline
    layering boundary; the public writer nevertheless accepts it directly.
    """

    route_qualified: bool
    scene_verdict: Any
    correspondences: tuple[Any, ...]
    artifacts: Any
    coverage: Any
    stages: tuple[Any, ...]
    provenance: Any
    origin: Any
    disposition: Any
    verified_inlier_count: int
    failures: tuple[Any, ...]
    evidence_limitations: tuple[str, ...]
    parameters: Any


class BundleProvenance(Contract):
    """Explicit information about the publication itself, not scientific evidence."""

    producer: str = Field(min_length=1)
    created_utc: str = Field(min_length=1)
    output_configuration: dict[str, object] = Field(min_length=1)
    note: str | None = None


class BundleConfig(Contract):
    """Caller-declared output policy and publication provenance."""

    bundle_id: str = Field(min_length=1)
    provenance: BundleProvenance
    arrays: object


class OptionalProductStatus(Contract):
    """The status of a geospatial product that was deliberately not fabricated."""

    product: Literal["registered_source_cog", "correspondence_geopackage"]
    status: Literal["delivered", "partial", "unsupported"]
    reason: str | None = None

    @model_validator(mode="after")
    def _require_reason_when_not_delivered(self) -> OptionalProductStatus:
        if self.status != "delivered" and not self.reason:
            raise ValueError("an unavailable optional product requires an explicit reason")
        return self


class PublishedArtifact(Contract):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    record_count: int | None = Field(default=None, ge=0)


class BundleWriteResult(Contract):
    destination: str
    manifest_path: str
    status: Literal["complete", "partial"]
    route_qualified: bool
    scene_verdict: Literal["accept", "review", "reject"]
    artifacts: tuple[PublishedArtifact, ...]
    optional_products: tuple[OptionalProductStatus, ...]
    limitations: tuple[str, ...]


class ValidatedArtifact(Contract):
    relative_path: str
    valid: bool
    code: Literal[
        "ok",
        "missing",
        "checksum_mismatch",
        "size_mismatch",
        "invalid_csv",
        "invalid_content",
        "unknown",
    ]
    message: str | None = None


class BundleValidationResult(Contract):
    destination: str
    valid: bool
    manifest_valid: bool
    metrics_valid: bool
    artifacts: tuple[ValidatedArtifact, ...]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _StagedArtifact:
    name: str
    media_type: str
    record_count: int | None = None


def _write_json(path: Path, value: object) -> None:
    data = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    path.write_text(data, encoding="utf-8")
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish(stage: Path, destination: Path, artifacts: tuple[_StagedArtifact, ...]) -> None:
    """Publish complete, pre-validated staged files, with the manifest last."""
    published: list[Path] = []
    try:
        for artifact in artifacts:
            target = destination / artifact.name
            os.replace(stage / artifact.name, target)
            published.append(target)
            _fsync_directory(destination)
        # The manifest is the commit record.  It is never made discoverable
        # before every artifact it references has already been published.
        os.replace(stage / _MANIFEST_NAME, destination / _MANIFEST_NAME)
        _fsync_directory(destination)
    except BaseException:
        for path in published:
            path.unlink(missing_ok=True)
        (destination / _MANIFEST_NAME).unlink(missing_ok=True)
        _fsync_directory(destination)
        raise


def _optional_products(_result: _LocalRegistrationResult) -> tuple[OptionalProductStatus, ...]:
    # PipelineResult has handles/measurements, but it intentionally does not
    # retain a registered raster, CRS, affine transform, or map geometry.  A
    # TIFF/GPKG in this situation would be a misleading surrogate.
    return (
        OptionalProductStatus(
            product="registered_source_cog",
            status="unsupported",
            reason=(
                "no registered source imagery with a fully specified CRS and geotransform "
                "was supplied by this local in-memory result"
            ),
        ),
        OptionalProductStatus(
            product="correspondence_geopackage",
            status="unsupported",
            reason=(
                "local correspondences have no validated map geometry/CRS; GeoPackage output "
                "would falsely imply a geospatial product"
            ),
        ),
    )


def _shape(handle: dict[str, object], name: str) -> tuple[int, int]:
    value = handle.get("shape")
    if (
        not isinstance(value, tuple | list)
        or len(value) != 2
        or not all(isinstance(item, int) for item in value)
    ):
        raise ValueError(f"local result has no valid two-dimensional {name} shape handle")
    return (value[0], value[1])


def _normalise_mask(
    mask: npt.NDArray[np.bool_] | None,
    *,
    shape: tuple[int, int],
    fallback: npt.NDArray[np.bool_],
    name: str,
) -> tuple[npt.NDArray[np.bool_], str]:
    if mask is None:
        return fallback, "derived_from_finite_values"
    normalised = np.asarray(mask, dtype=bool)
    if normalised.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {normalised.shape}")
    if np.any(normalised & ~fallback):
        raise ValueError(f"{name} marks non-finite source/reference pixels as valid")
    return normalised, "caller_supplied"


def _coverage_mask(
    result: _LocalRegistrationResult, shape: tuple[int, int]
) -> npt.NDArray[np.bool_]:
    """Mark selected source-pixel locations; this is not an inferred footprint."""
    mask = np.zeros(shape, dtype=bool)
    for record in result.correspondences:
        if not record.selected_for_coverage:
            continue
        row = round(record.source_pixel.line)
        column = round(record.source_pixel.sample)
        if 0 <= row < shape[0] and 0 <= column < shape[1]:
            mask[row, column] = True
    return mask


def _write_npy(path: Path, array: npt.NDArray[np.generic]) -> None:
    with path.open("wb") as handle:
        np.save(handle, array, allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())


def _array_products(
    result: _LocalRegistrationResult, payload: BundleArrayPayload, stage: Path
) -> tuple[tuple[_StagedArtifact, ...], dict[str, object]]:
    source = np.asarray(payload.source)
    reference = np.asarray(payload.reference)
    source_shape = _shape(result.artifacts.source, "source")
    reference_shape = _shape(result.artifacts.reference, "reference")
    if source.ndim != 2 or source.shape != source_shape:
        raise ValueError(f"source array must have shape {source_shape}, got {source.shape}")
    if reference.ndim != 2 or reference.shape != reference_shape:
        raise ValueError(
            f"reference array must have shape {reference_shape}, got {reference.shape}"
        )
    if not np.issubdtype(source.dtype, np.number) or not np.issubdtype(reference.dtype, np.number):
        raise ValueError("source and reference arrays must be numeric")
    source_validity, source_validity_origin = _normalise_mask(
        payload.source_validity_mask,
        shape=source_shape,
        fallback=np.isfinite(source),
        name="source_validity_mask",
    )
    reference_validity, reference_validity_origin = _normalise_mask(
        payload.reference_validity_mask,
        shape=reference_shape,
        fallback=np.isfinite(reference),
        name="reference_validity_mask",
    )
    coverage = _coverage_mask(result, source_shape)
    named_arrays: tuple[tuple[str, npt.NDArray[np.generic]], ...] = (
        ("source.npy", source),
        ("reference.npy", reference),
        ("source-validity-mask.npy", source_validity),
        ("reference-validity-mask.npy", reference_validity),
        ("coverage-mask.npy", coverage),
    )
    staged: list[_StagedArtifact] = []
    for name, array in named_arrays:
        _write_npy(stage / name, array)
        staged.append(_StagedArtifact(name, "application/x-npy"))
    # No cross-image mask is accepted or guessed: its coordinate system would
    # be undefined without the mission geometry that this route lacks.
    overlap_name = "overlap-mask.unavailable.json"
    _write_json(
        stage / overlap_name,
        {
            "schema_version": _BUNDLE_SCHEMA_VERSION,
            "kind": "overlap_mask",
            "status": "unavailable",
            "reason": "validated geometry is required to define source/reference overlap",
        },
    )
    staged.append(_StagedArtifact(overlap_name, "application/json"))
    overlap_status: dict[str, object] = {"status": "unavailable", "artifact": overlap_name}
    return tuple(staged), {
        "source": {
            "artifact": "source.npy",
            "shape": list(source.shape),
            "dtype": str(source.dtype),
        },
        "reference": {
            "artifact": "reference.npy",
            "shape": list(reference.shape),
            "dtype": str(reference.dtype),
        },
        "source_validity_mask": {
            "artifact": "source-validity-mask.npy",
            "origin": source_validity_origin,
            "shape": list(source_validity.shape),
            "dtype": str(source_validity.dtype),
        },
        "reference_validity_mask": {
            "artifact": "reference-validity-mask.npy",
            "origin": reference_validity_origin,
            "shape": list(reference_validity.shape),
            "dtype": str(reference_validity.dtype),
        },
        "coverage_mask": {
            "artifact": "coverage-mask.npy",
            "semantics": "selected correspondence source-pixel locations only",
            "shape": list(coverage.shape),
            "dtype": str(coverage.dtype),
        },
        "overlap_mask": overlap_status,
    }


def _metrics(
    result: _LocalRegistrationResult,
    optional_products: tuple[OptionalProductStatus, ...],
    array_products: dict[str, object],
) -> dict[str, object]:
    coverage = result.coverage
    correspondences = result.correspondences
    stages = result.stages
    verdict = result.scene_verdict
    provenance = result.provenance
    return {
        "schema_version": _BUNDLE_SCHEMA_VERSION,
        "report_id": f"{provenance.job_id}:local-output",
        "scope": "scene",
        "product_id": provenance.job_id,
        "computed_utc": verdict.computed_utc.isoformat().replace("+00:00", "Z"),
        "origin": str(result.origin),
        "route_qualified": bool(result.route_qualified),
        "disposition": str(result.disposition),
        "correspondence_count": len(correspondences),
        "verified_inlier_count": int(result.verified_inlier_count),
        "coverage": None if coverage is None else coverage.model_dump(mode="json"),
        "stages": [stage.model_dump(mode="json") for stage in stages],
        "scene_verdict": verdict.model_dump(mode="json"),
        "failures": [failure.model_dump(mode="json") for failure in result.failures],
        "evidence_limitations": list(result.evidence_limitations),
        "optional_products": [item.model_dump(mode="json") for item in optional_products],
        "array_products": array_products,
        # These metric entries mirror already-computed facts above; they do
        # not turn internal local measurements into a scientific claim.
        "metrics": [
            {
                "name": "correspondence_count",
                "value": len(correspondences),
                "units": "count",
                "evidence_source": "local_pipeline_result",
            },
            {
                "name": "verified_inlier_count",
                "value": int(result.verified_inlier_count),
                "units": "count",
                "evidence_source": "local_pipeline_result",
            },
        ],
    }


def _artifact(path: Path, media_type: str, record_count: int | None = None) -> PublishedArtifact:
    return PublishedArtifact(
        relative_path=path.name,
        sha256=digest_file(path),
        size_bytes=path.stat().st_size,
        media_type=media_type,
        record_count=record_count,
    )


def write_local_registration_bundle(
    result: _LocalRegistrationResult, destination: Path, *, config: BundleConfig
) -> BundleWriteResult:
    """Write a complete local-result bundle, committing its manifest last.

    ``destination`` must exist and be empty. In-place replacement is never
    supported, including for an earlier bundle; publish to a new destination.
    GeoTIFF/COG and GeoPackage are explicitly
    reported unsupported because this result lacks the required registered
    imagery and validated geometry.
    """
    destination = Path(destination)
    if result.route_qualified or result.scene_verdict.verdict != "reject":
        raise ValueError(
            "the local output-bundle writer accepts only explicitly non-qualified, rejected "
            "local results"
        )
    if not isinstance(config.arrays, BundleArrayPayload):
        raise TypeError(
            "config.arrays must be a BundleArrayPayload with actual local array payloads"
        )
    if not destination.is_dir():
        raise FileNotFoundError(
            f"bundle destination must be a pre-existing directory: {destination}"
        )
    existing = tuple(destination.iterdir())
    if existing:
        raise BundleAlreadyExistsError(
            f"refusing to overwrite non-empty bundle destination {destination}; "
            "publish this immutable bundle to a new empty directory"
        )

    optional_products = _optional_products(result)
    stage = Path(tempfile.mkdtemp(prefix=".local-registration-bundle-", dir=destination))
    try:
        catalogue = stage / _CATALOGUE_NAME
        csv_outcome = write_correspondence_csv(tuple(result.correspondences), catalogue)
        array_staged, array_products = _array_products(result, config.arrays, stage)
        _write_json(stage / _METRICS_NAME, _metrics(result, optional_products, array_products))
        staged = (
            _StagedArtifact(_CATALOGUE_NAME, "text/csv", csv_outcome.row_count),
            _StagedArtifact(_METRICS_NAME, "application/json"),
            *array_staged,
        )
        artifacts = tuple(
            _artifact(stage / artifact.name, artifact.media_type, artifact.record_count)
            for artifact in staged
        )
        manifest = {
            "schema_version": _BUNDLE_SCHEMA_VERSION,
            "kind": "local_registration_output_bundle",
            "bundle_id": config.bundle_id,
            "status": "partial",
            "route_qualified": bool(result.route_qualified),
            "origin": str(result.origin),
            "disposition": str(result.disposition),
            "scene_verdict": result.scene_verdict.model_dump(mode="json"),
            "pipeline_provenance": result.provenance.model_dump(mode="json"),
            "publication_provenance": config.provenance.model_dump(mode="json"),
            "parameters": result.parameters.model_dump(mode="json"),
            "evidence_limitations": list(result.evidence_limitations),
            "optional_products": [item.model_dump(mode="json") for item in optional_products],
            "array_products": array_products,
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
        }
        _write_json(stage / _MANIFEST_NAME, manifest)

        # Validate the staged data before publishing.  This catches a malformed
        # CSV/metrics report before anything becomes visible to consumers.
        staged_validation = _validate(stage, include_unknown=False)
        if not staged_validation.valid:
            raise ValueError(f"staged output bundle failed validation: {staged_validation.errors}")
        _publish(
            stage,
            destination,
            staged,
        )
        return BundleWriteResult(
            destination=str(destination),
            manifest_path=str(destination / _MANIFEST_NAME),
            status="partial",
            route_qualified=bool(result.route_qualified),
            scene_verdict=result.scene_verdict.verdict,
            artifacts=artifacts,
            optional_products=optional_products,
            limitations=tuple(result.evidence_limitations),
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _record_invalid_content(
    failures: list[ValidatedArtifact], errors: list[str], relative_path: str, message: str
) -> None:
    errors.append(message)
    failures.append(
        ValidatedArtifact(
            relative_path=relative_path,
            valid=False,
            code="invalid_content",
            message=message,
        )
    )


def _array_product_spec(
    products: dict[str, object], key: str, expected_artifact: str
) -> dict[str, object] | None:
    value = products.get(key)
    if not isinstance(value, dict) or value.get("artifact") != expected_artifact:
        return None
    return cast(dict[str, object], value)


def _declared_shape(spec: dict[str, object]) -> tuple[int, int] | None:
    shape = spec.get("shape")
    if (
        not isinstance(shape, list)
        or len(shape) != 2
        or not all(isinstance(item, int) and item >= 0 for item in shape)
    ):
        return None
    return (shape[0], shape[1])


def _load_npy_for_validation(
    destination: Path,
    name: str,
    failures: list[ValidatedArtifact],
    errors: list[str],
) -> npt.NDArray[Any] | None:
    try:
        loaded = np.load(destination / name, allow_pickle=False)
    except (OSError, ValueError) as error:
        _record_invalid_content(failures, errors, name, f"invalid NPY payload {name}: {error}")
        return None
    if not isinstance(loaded, np.ndarray) or loaded.dtype.hasobject:
        _record_invalid_content(
            failures,
            errors,
            name,
            f"NPY payload {name} must be a non-object ndarray loaded without pickle support",
        )
        return None
    return loaded


def _validate_array_products(
    destination: Path,
    manifest: dict[str, object],
    failures: list[ValidatedArtifact],
    errors: list[str],
) -> None:
    raw_products = manifest.get("array_products")
    if not isinstance(raw_products, dict):
        _record_invalid_content(
            failures, errors, _MANIFEST_NAME, "manifest lacks an array_products object"
        )
        return
    products = cast(dict[str, object], raw_products)
    source_spec = _array_product_spec(products, "source", "source.npy")
    reference_spec = _array_product_spec(products, "reference", "reference.npy")
    if source_spec is None or reference_spec is None:
        _record_invalid_content(
            failures,
            errors,
            _MANIFEST_NAME,
            "manifest lacks stable source/reference array declarations",
        )
        return
    source_shape = _declared_shape(source_spec)
    reference_shape = _declared_shape(reference_spec)
    source_dtype = source_spec.get("dtype")
    reference_dtype = reference_spec.get("dtype")
    if (
        source_shape is None
        or reference_shape is None
        or not isinstance(source_dtype, str)
        or not isinstance(reference_dtype, str)
    ):
        _record_invalid_content(
            failures, errors, _MANIFEST_NAME, "manifest has invalid source/reference shape or dtype"
        )
        return
    source = _load_npy_for_validation(destination, "source.npy", failures, errors)
    reference = _load_npy_for_validation(destination, "reference.npy", failures, errors)
    if source is None or reference is None:
        return
    if (
        source.shape != source_shape
        or reference.shape != reference_shape
        or str(source.dtype) != source_dtype
        or str(reference.dtype) != reference_dtype
        or source.ndim != 2
        or reference.ndim != 2
        or not np.issubdtype(source.dtype, np.number)
        or not np.issubdtype(reference.dtype, np.number)
    ):
        _record_invalid_content(
            failures,
            errors,
            _MANIFEST_NAME,
            "source/reference NPY payload differs from manifest shape/dtype or is not numeric "
            "2D data",
        )
        return
    masks: tuple[tuple[str, str, tuple[int, int]], ...] = (
        ("source_validity_mask", "source-validity-mask.npy", source_shape),
        ("reference_validity_mask", "reference-validity-mask.npy", reference_shape),
        ("coverage_mask", "coverage-mask.npy", source_shape),
    )
    loaded_masks: dict[str, npt.NDArray[Any]] = {}
    for key, name, shape in masks:
        mask_spec = _array_product_spec(products, key, name)
        if mask_spec is None:
            _record_invalid_content(
                failures, errors, _MANIFEST_NAME, f"manifest lacks stable {key} declaration"
            )
            continue
        if _declared_shape(mask_spec) != shape or mask_spec.get("dtype") != "bool":
            _record_invalid_content(
                failures,
                errors,
                _MANIFEST_NAME,
                f"manifest has invalid {key} shape/dtype declaration",
            )
            continue
        mask = _load_npy_for_validation(destination, name, failures, errors)
        if mask is None:
            continue
        if (
            mask.shape != shape
            or mask.ndim != 2
            or mask.dtype != np.dtype(bool)
            or str(mask.dtype) != mask_spec["dtype"]
        ):
            _record_invalid_content(
                failures,
                errors,
                name,
                f"{name} must be a boolean two-dimensional array with shape {shape}",
            )
            continue
        loaded_masks[key] = mask
    source_mask = loaded_masks.get("source_validity_mask")
    reference_mask = loaded_masks.get("reference_validity_mask")
    coverage_mask = loaded_masks.get("coverage_mask")
    if source_mask is not None and np.any(source_mask & ~np.isfinite(source)):
        _record_invalid_content(
            failures,
            errors,
            "source-validity-mask.npy",
            "source validity mask marks non-finite source pixels as valid",
        )
    if reference_mask is not None and np.any(reference_mask & ~np.isfinite(reference)):
        _record_invalid_content(
            failures,
            errors,
            "reference-validity-mask.npy",
            "reference validity mask marks non-finite reference pixels as valid",
        )
    if (
        coverage_mask is not None
        and source_mask is not None
        and np.any(coverage_mask & ~source_mask)
    ):
        _record_invalid_content(
            failures,
            errors,
            "coverage-mask.npy",
            "coverage mask selects source pixels outside the source validity mask",
        )
    overlap_spec = _array_product_spec(products, "overlap_mask", "overlap-mask.unavailable.json")
    if overlap_spec is None or overlap_spec.get("status") != "unavailable":
        _record_invalid_content(
            failures,
            errors,
            _MANIFEST_NAME,
            "manifest must declare an unavailable overlap-mask payload for this local route",
        )
        return
    try:
        overlap = _load_json(destination / "overlap-mask.unavailable.json")
    except (OSError, json.JSONDecodeError) as error:
        _record_invalid_content(
            failures, errors, "overlap-mask.unavailable.json", f"invalid overlap payload: {error}"
        )
        return
    if (
        not isinstance(overlap, dict)
        or overlap.get("schema_version") != _BUNDLE_SCHEMA_VERSION
        or overlap.get("kind") != "overlap_mask"
        or overlap.get("status") != "unavailable"
        or not isinstance(overlap.get("reason"), str)
        or not overlap["reason"]
    ):
        _record_invalid_content(
            failures,
            errors,
            "overlap-mask.unavailable.json",
            "overlap unavailable payload must have a non-empty documented reason",
        )


def _validate(destination: Path, *, include_unknown: bool) -> BundleValidationResult:
    manifest_path = destination / _MANIFEST_NAME
    failures: list[ValidatedArtifact] = []
    errors: list[str] = []
    if not manifest_path.is_file():
        return BundleValidationResult(
            destination=str(destination),
            valid=False,
            manifest_valid=False,
            metrics_valid=False,
            artifacts=(
                ValidatedArtifact(
                    relative_path=_MANIFEST_NAME,
                    valid=False,
                    code="missing",
                    message="manifest missing",
                ),
            ),
            errors=("manifest missing",),
        )
    try:
        manifest = _load_json(manifest_path)
    except (OSError, json.JSONDecodeError) as error:
        return BundleValidationResult(
            destination=str(destination),
            valid=False,
            manifest_valid=False,
            metrics_valid=False,
            artifacts=(),
            errors=(f"invalid manifest JSON: {error}",),
        )
    required_manifest = {
        "bundle_id",
        "status",
        "route_qualified",
        "scene_verdict",
        "pipeline_provenance",
        "publication_provenance",
        "parameters",
        "array_products",
        "artifacts",
    }
    manifest_data: dict[str, object] | None = None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != _BUNDLE_SCHEMA_VERSION:
        errors.append("manifest has an unknown schema version or is not an object")
    else:
        manifest_data = cast(dict[str, object], manifest)
        if missing := required_manifest.difference(manifest_data):
            errors.append(f"manifest missing {sorted(missing)}")
        elif (
            manifest_data["status"] != "partial"
            or manifest_data["route_qualified"] is not False
            or not isinstance(manifest_data["scene_verdict"], dict)
            or manifest_data["scene_verdict"].get("verdict") != "reject"
        ):
            errors.append("manifest does not preserve the local non-qualified/rejected policy")
    entries = manifest_data.get("artifacts") if manifest_data is not None else None
    if not isinstance(entries, list) or not entries:
        errors.append("manifest has no artifact list")
        entries = []
    names: set[str] = set()
    expected_csv_count: int | None = None
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("relative_path"), str):
            errors.append("manifest contains an invalid artifact entry")
            continue
        name = entry["relative_path"]
        if Path(name).name != name or name in names:
            errors.append(f"invalid or duplicate artifact path: {name!r}")
            continue
        names.add(name)
        path = destination / name
        if not path.is_file():
            failures.append(
                ValidatedArtifact(
                    relative_path=name, valid=False, code="missing", message="artifact missing"
                )
            )
            continue
        if digest_file(path) != entry.get("sha256"):
            failures.append(
                ValidatedArtifact(
                    relative_path=name,
                    valid=False,
                    code="checksum_mismatch",
                    message="SHA-256 differs from manifest",
                )
            )
            continue
        if path.stat().st_size != entry.get("size_bytes"):
            failures.append(
                ValidatedArtifact(
                    relative_path=name,
                    valid=False,
                    code="size_mismatch",
                    message="size differs from manifest",
                )
            )
            continue
        failures.append(ValidatedArtifact(relative_path=name, valid=True, code="ok"))
        if name == _CATALOGUE_NAME:
            value = entry.get("record_count")
            expected_csv_count = value if isinstance(value, int) else None

    missing_required = _REQUIRED_ARTIFACTS.difference(names)
    unexpected_declared = names.difference(_REQUIRED_ARTIFACTS)
    if missing_required or unexpected_declared:
        errors.append(
            "manifest must declare exactly the fixed local artifact set; "
            f"missing={sorted(missing_required)}, unexpected={sorted(unexpected_declared)}"
        )
    reported_missing = {item.relative_path for item in failures if item.code == "missing"}
    for name in sorted(missing_required.difference(reported_missing)):
        failures.append(
            ValidatedArtifact(
                relative_path=name,
                valid=False,
                code="missing",
                message="required artifact is not declared by manifest",
            )
        )

    if manifest_data is not None:
        # Every declared NPY is loaded without pickle support, including any
        # unexpected one a tampered manifest attempts to legitimise.  Known
        # product names receive stricter shape/dtype checks below.
        for entry in entries:
            if (
                isinstance(entry, dict)
                and entry.get("media_type") == "application/x-npy"
                and isinstance(entry.get("relative_path"), str)
            ):
                _load_npy_for_validation(destination, entry["relative_path"], failures, errors)
        _validate_array_products(destination, manifest_data, failures, errors)

    metrics_valid = False
    metrics_path = destination / _METRICS_NAME
    try:
        raw_metrics = _load_json(metrics_path)
        if not isinstance(raw_metrics, dict):
            raise ValueError("metrics report is not an object")
        metrics = cast(dict[str, object], raw_metrics)
        required = {"route_qualified", "correspondence_count", "scene_verdict", "stages", "metrics"}
        missing = required.difference(metrics)
        if missing:
            raise ValueError(f"metrics report missing {sorted(missing)}")
        if not isinstance(metrics["route_qualified"], bool) or not isinstance(
            metrics["correspondence_count"], int
        ):
            raise ValueError("metrics report has invalid route/count types")
        if metrics["route_qualified"] or not isinstance(metrics["scene_verdict"], dict):
            raise ValueError("metrics report has invalid route qualification or verdict")
        if metrics["scene_verdict"].get("verdict") != "reject":
            raise ValueError("metrics report does not preserve the rejected local verdict")
        metrics_valid = True
    except (OSError, json.JSONDecodeError, ValueError) as error:
        errors.append(f"invalid metrics report: {error}")
        failures.append(
            ValidatedArtifact(
                relative_path=_METRICS_NAME,
                valid=False,
                code="invalid_content",
                message=str(error),
            )
        )

    csv_path = destination / _CATALOGUE_NAME
    if csv_path.is_file():
        try:
            parsed = read_correspondence_csv(csv_path)
            if expected_csv_count is not None and len(parsed) != expected_csv_count:
                errors.append("CSV record count differs from manifest")
            if metrics_valid and len(parsed) != metrics["correspondence_count"]:
                errors.append("CSV record count differs from metrics report")
        except (OSError, ValueError, KeyError) as error:
            errors.append(f"invalid canonical CSV: {error}")
            failures.append(
                ValidatedArtifact(
                    relative_path=_CATALOGUE_NAME,
                    valid=False,
                    code="invalid_csv",
                    message=str(error),
                )
            )

    if include_unknown:
        known = names | {_MANIFEST_NAME}
        for path in destination.iterdir():
            if path.name not in known:
                failures.append(
                    ValidatedArtifact(
                        relative_path=path.name,
                        valid=False,
                        code="unknown",
                        message="not declared by manifest",
                    )
                )
    manifest_valid = not errors and bool(names)
    return BundleValidationResult(
        destination=str(destination),
        valid=manifest_valid and metrics_valid and all(item.valid for item in failures),
        manifest_valid=manifest_valid,
        metrics_valid=metrics_valid,
        artifacts=tuple(failures),
        errors=tuple(errors),
    )


def validate_local_registration_bundle(destination: Path) -> BundleValidationResult:
    """Validate an already-written bundle without invoking any matching code."""
    destination = Path(destination)
    if not destination.is_dir():
        return BundleValidationResult(
            destination=str(destination),
            valid=False,
            manifest_valid=False,
            metrics_valid=False,
            artifacts=(),
            errors=("bundle destination does not exist",),
        )
    return _validate(destination, include_unknown=True)
