"""Trusted-local product registration and immutable derived raster products.

This is intentionally a local-filesystem API.  It accepts a manifest path
only from the CLI running on the operator's machine; an HTTP upload endpoint
must not pass a user supplied server path here.  Registration verifies the
manifest before opening the raster and never writes to, converts, or moves an
input file.  Derived products are separately named outputs with an input
digest in their provenance record.

Actual pixel validation and preview generation require the optional
``selene-core[raster]`` extra.  The API reports that dependency as unavailable
instead of treating a label-only inspection as raster validation.
"""

# Manifest schema validation occurs before the local type-narrowing assertions
# below.  They are not authorization/security checks and cannot make invalid
# input acceptable when Python runs with optimizations.
# ruff: noqa: S101

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from selene_core.hashing import digest_file, digest_json, is_sha256
from selene_core.ingest.payload_adapter import (
    CalibrationState,
    PayloadAdapter,
    PayloadMetadata,
    UnrecognizedLabelFormatError,
)
from selene_core.ingest.pds4 import Pds4ParseError
from selene_core.ingest.pvl import PvlParseError
from selene_core.ingest.raster_drivers import (
    RasterioNotInstalledError,
    VirtualFilesystemPathRejectedError,
    open_raster_allowlisted,
)
from selene_core.schema_validation import validate_instance

__all__ = [
    "DerivedProduct",
    "ProductRegistrationError",
    "RegisteredProduct",
    "derive_normalized_preview",
    "register_local_product",
]


class ProductRegistrationError(ValueError):
    """A local product manifest or its declared local files did not validate.

    ``reason`` is deliberately stable enough for quarantine/revalidation UI
    handling without making this lower-level module responsible for creating a
    pipeline-stage failure envelope.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class _Raster(Protocol):
    width: int
    height: int
    count: int
    dtypes: tuple[str, ...]
    nodata: float | None

    def read(self) -> np.ndarray: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RegisteredProduct:
    """Validated immutable source product record.

    Paths are retained as resolved local paths for this trusted-local
    invocation. ``source_digests`` gives every source byte stream an immutable
    identity; callers must recompute them before reusing a record later.
    """

    manifest_path: Path
    product_id: str
    payload_family: str
    data_path: Path
    label_path: Path
    source_digests: Mapping[str, str]
    metadata: PayloadMetadata
    raster_shape: tuple[int, int, int]
    dtype: str
    nodata: float | None


@dataclass(frozen=True, slots=True)
class DerivedProduct:
    """A generated preview/working array plus immutable provenance."""

    array_path: Path
    provenance_path: Path
    source_data_sha256: str
    normalized_sha256: str
    low_percentile: float
    high_percentile: float


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "schemas" / "product-input-manifest.schema.json").is_file():
            return parent
    raise RuntimeError("could not locate the repository product manifest schema")


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant is not permitted: {value}")
            ),
        )
    except FileNotFoundError as exc:
        raise ProductRegistrationError(
            "input.missing_file", f"manifest does not exist: {path}"
        ) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ProductRegistrationError(
            "input.label_unparseable", f"cannot parse manifest {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ProductRegistrationError(
            "input.label_unparseable", "product manifest must be a JSON object"
        )
    schema = json.loads(
        (_repository_root() / "schemas" / "product-input-manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    try:
        validate_instance(raw, schema)
    except Exception as exc:  # jsonschema's public error base adds no useful contract here
        raise ProductRegistrationError(
            "input.label_unparseable", f"manifest does not meet schema: {exc}"
        ) from exc
    return raw


def _snapshot_verified(source: Path, expected_digest: str, snapshot_dir: Path) -> Path:
    """Copy exact bytes from one opened source into an immutable local snapshot."""
    snapshot_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(snapshot_dir, 0o700)
    target = snapshot_dir / expected_digest
    fd, temporary_name = tempfile.mkstemp(prefix=".incoming-", dir=snapshot_dir)
    temporary = Path(temporary_name)
    try:
        source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        source_fd = os.open(source, source_flags)
        with os.fdopen(source_fd, "rb") as input_handle, os.fdopen(fd, "wb") as output_handle:
            digest = sha256()
            while chunk := input_handle.read(1024 * 1024):
                digest.update(chunk)
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        if digest.hexdigest() != expected_digest:
            raise ProductRegistrationError(
                "input.checksum_mismatch",
                f"source checksum differs while snapshotting {source.name}",
            )
        os.link(temporary, target)
        os.chmod(target, 0o400)
        return target
    except OSError as exc:
        raise ProductRegistrationError(
            "input.missing_file", f"cannot snapshot {source}: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _safe_relative_path(manifest_dir: Path, relative_path: str) -> Path:
    candidate = (manifest_dir / relative_path).resolve()
    try:
        candidate.relative_to(manifest_dir.resolve())
    except ValueError as exc:
        raise ProductRegistrationError(
            "input.hostile_label", f"manifest path escapes its directory: {relative_path!r}"
        ) from exc
    return candidate


def _files_by_role(
    manifest: Mapping[str, Any], manifest_dir: Path
) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    output: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    files = manifest["files"]
    assert isinstance(files, list)
    for entry in files:
        assert isinstance(entry, dict)
        role = entry["role"]
        assert isinstance(role, str)
        if role in output:
            raise ProductRegistrationError(
                "input.label_unparseable", f"manifest has multiple {role!r} files"
            )
        relative_path = entry["relative_path"]
        assert isinstance(relative_path, str)
        output[role] = (_safe_relative_path(manifest_dir, relative_path), entry)
    return output


def _verify_files(files: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for role, (path, entry) in files.items():
        if not path.is_file():
            raise ProductRegistrationError(
                "input.missing_file", f"{role} file does not exist: {path}"
            )
        expected = entry["sha256"]
        assert isinstance(expected, str)
        if not is_sha256(expected):  # schema does this too; retain an API boundary check.
            raise ProductRegistrationError(
                "input.label_unparseable", f"invalid SHA-256 for {role}: {expected!r}"
            )
        actual = digest_file(path)
        if actual != expected:
            raise ProductRegistrationError(
                "input.checksum_mismatch", f"{role} checksum differs from manifest for {path.name}"
            )
        expected_size = entry["size_bytes"]
        assert isinstance(expected_size, int)
        if path.stat().st_size != expected_size:
            raise ProductRegistrationError(
                "input.checksum_mismatch", f"{role} size differs from manifest for {path.name}"
            )
        digests[role] = actual
    return digests


def _require_single(
    files: Mapping[str, tuple[Path, Mapping[str, Any]]], role: str
) -> tuple[Path, Mapping[str, Any]]:
    try:
        return files[role]
    except KeyError as exc:
        raise ProductRegistrationError(
            "input.missing_file", f"manifest requires exactly one {role!r} file"
        ) from exc


def _validate_raster(
    dataset: _Raster, manifest: Mapping[str, Any], metadata: PayloadMetadata
) -> tuple[tuple[int, int, int], str, float | None]:
    raster = manifest["raster"]
    assert isinstance(raster, dict)
    declared_shape = raster["shape"]
    assert isinstance(declared_shape, list)
    observed_shape = (dataset.count, dataset.height, dataset.width)
    expected_shape = tuple(declared_shape) if len(declared_shape) == 3 else (1, *declared_shape)
    if observed_shape != expected_shape:
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            f"manifest raster shape {expected_shape} differs from raster {observed_shape}",
        )
    dtype = dataset.dtypes[0]
    if any(item != dtype for item in dataset.dtypes) or dtype != raster["dtype"]:
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            f"manifest dtype {raster['dtype']!r} differs from raster dtypes {dataset.dtypes!r}",
        )
    expected_nodata = raster.get("nodata")
    if expected_nodata != dataset.nodata:
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            f"manifest nodata {expected_nodata!r} differs from raster nodata {dataset.nodata!r}",
        )
    if metadata.declared_lines is not None and metadata.declared_lines != dataset.height:
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "label lines differ from raster height"
        )
    if metadata.declared_samples is not None and metadata.declared_samples != dataset.width:
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "label samples differ from raster width"
        )
    if metadata.declared_bands is not None and metadata.declared_bands != dataset.count:
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "label bands differ from raster count"
        )
    bands = raster.get("bands", [])
    assert isinstance(bands, list)
    if bands and len(bands) != dataset.count:
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "manifest band metadata count differs from raster"
        )
    return observed_shape, dtype, dataset.nodata


def _validate_band_metadata(manifest: Mapping[str, Any], metadata: PayloadMetadata) -> None:
    raster = manifest["raster"]
    assert isinstance(raster, dict)
    declared = raster.get("bands", [])
    assert isinstance(declared, list)
    numbers = [item.get("band_number") for item in declared if isinstance(item, dict)]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            "manifest band numbers must be unique and ordered from 1",
        )
    if not metadata.bands:
        return
    if declared and len(declared) != len(metadata.bands):
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "manifest and label band metadata counts differ"
        )
    for declared_band, label_band in zip(declared, metadata.bands, strict=True):
        assert isinstance(declared_band, dict)
        if declared_band["band_number"] != label_band.band_number:
            raise ProductRegistrationError(
                "input.label_raster_disagreement", "label band order differs"
            )
        comparable = {
            "center_wavelength_nm": label_band.center_wavelength_nm,
            "fwhm_nm": label_band.fwhm_nm,
            "is_bad_band": label_band.is_bad_band,
            "spectral_regime": label_band.spectral_regime.value,
        }
        for key, label_value in comparable.items():
            manifest_value = declared_band.get(key)
            if (
                manifest_value is not None
                and label_value is not None
                and manifest_value != label_value
            ):
                raise ProductRegistrationError(
                    "input.label_raster_disagreement",
                    f"manifest {key} differs from label band metadata",
                )


def _manifest_instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ProductRegistrationError(
            "input.label_unparseable", "manifest acquisition timestamp is not text"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductRegistrationError(
            "input.label_unparseable", "manifest acquisition timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductRegistrationError(
            "input.label_unparseable", "manifest acquisition timestamp lacks offset"
        )
    return parsed.astimezone(UTC)


def _register_local_product(manifest_path: Path, adapter: PayloadAdapter) -> RegisteredProduct:
    """Validate a manifest, source bytes, label, and allow-listed local raster.

    This function has no copy or write side effect.  It is safe to invoke for
    a revalidation after replacing a corrupt local source with verified bytes.
    """
    manifest_path = manifest_path.resolve()
    manifest = _load_manifest(manifest_path)
    files = _files_by_role(manifest, manifest_path.parent)
    data_path, _ = _require_single(files, "data")
    label_path, _ = _require_single(files, "label")
    digests = _verify_files(files)
    # A private system temporary root is deliberately outside the manifest
    # directory, which may be writable by whoever supplied the local product.
    snapshot_dir = Path(tempfile.mkdtemp(prefix="selene-xr-ingest-"))
    os.chmod(snapshot_dir, 0o700)
    data_path = _snapshot_verified(data_path, digests["data"], snapshot_dir / "data")
    label_path = _snapshot_verified(label_path, digests["label"], snapshot_dir / "label")
    label_bytes = label_path.read_bytes()
    if sha256(label_bytes).hexdigest() != digests["label"]:
        raise ProductRegistrationError("input.checksum_mismatch", "label snapshot bytes changed")
    try:
        metadata = adapter.extract(label_bytes)
    except (Pds4ParseError, PvlParseError, UnrecognizedLabelFormatError) as exc:
        reason = getattr(exc, "code", "input.label_unparseable")
        raise ProductRegistrationError(str(reason), str(exc)) from exc
    declared_payload = manifest["payload_family"]
    assert isinstance(declared_payload, str)
    if metadata.payload_family.value != declared_payload:
        raise ProductRegistrationError(
            "input.unsupported_payload",
            "manifest payload family differs from the selected payload adapter",
        )
    declared_product_id = manifest["product_id"]
    assert isinstance(declared_product_id, str)
    if metadata.product_id is not None and metadata.product_id != declared_product_id:
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            "label product identifier differs from manifest",
        )
    mismatch_warnings = [
        warning for warning in metadata.warnings if warning.startswith("instrument-ID mismatch:")
    ]
    if mismatch_warnings:
        raise ProductRegistrationError("input.unsupported_payload", "; ".join(mismatch_warnings))
    _validate_band_metadata(manifest, metadata)
    expected_calibration = manifest["calibration_state"]
    assert isinstance(expected_calibration, str)
    if metadata.calibration_state is CalibrationState.UNKNOWN:
        if expected_calibration != CalibrationState.UNKNOWN.value:
            raise ProductRegistrationError(
                "input.not_calibrated",
                "manifest claims a calibration state that the label adapter cannot verify",
            )
    elif metadata.calibration_state.value != expected_calibration:
        raise ProductRegistrationError(
            "input.not_calibrated", "label calibration state differs from manifest"
        )
    acquisition = manifest["acquisition"]
    assert isinstance(acquisition, dict)
    if metadata.acquisition_interval is None:
        # The persisted product-input manifest has mandatory start/end UTC
        # fields.  There is no schema-level "unverified interval" state, so
        # accepting a missing, naive, or unsupported label timestamp would
        # silently turn required provenance into an unverified claim.
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            "manifest requires an acquisition interval that the label adapter cannot verify",
        )
    start = _manifest_instant(acquisition["start_utc"])
    stop = _manifest_instant(acquisition["end_utc"])
    if (
        start != metadata.acquisition_interval.start_utc
        or stop != metadata.acquisition_interval.stop_utc
    ):
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            "label acquisition interval differs from manifest",
        )
    try:
        dataset = open_raster_allowlisted(data_path)
    except RasterioNotInstalledError as exc:
        raise ProductRegistrationError("input.raster_driver_not_allowed", str(exc)) from exc
    except VirtualFilesystemPathRejectedError as exc:
        raise ProductRegistrationError("input.hostile_label", str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise ProductRegistrationError("input.raster_driver_not_allowed", str(exc)) from exc
    try:
        shape, dtype, nodata = _validate_raster(dataset, manifest, metadata)
    finally:
        dataset.close()
    product_id = manifest["product_id"]
    payload_family = manifest["payload_family"]
    assert isinstance(product_id, str) and isinstance(payload_family, str)
    return RegisteredProduct(
        manifest_path=manifest_path,
        product_id=product_id,
        payload_family=payload_family,
        data_path=data_path,
        label_path=label_path,
        source_digests=digests,
        metadata=metadata,
        raster_shape=shape,
        dtype=dtype,
        nodata=nodata,
    )


def register_local_product(manifest_path: Path, adapter: PayloadAdapter) -> RegisteredProduct:
    """Register local input, converting expected parser/I/O metadata failures.

    Programmer errors are deliberately not caught.  Bad local product bytes,
    adapters that reject their metadata, and filesystem failures are instead
    stable quarantine outcomes for both the CLI and future service wrapper.
    """
    try:
        return _register_local_product(manifest_path, adapter)
    except ProductRegistrationError:
        raise
    except (OSError, ValueError) as exc:
        raise ProductRegistrationError("input.label_unparseable", str(exc)) from exc


def derive_normalized_preview(
    registered: RegisteredProduct,
    output_dir: Path,
    *,
    low_percentile: float = 2.0,
    high_percentile: float = 98.0,
) -> DerivedProduct:
    """Write an 8-bit normalized first-band working preview and provenance.

    The source is opened read-only.  The output is ``.npy`` intentionally:
    unlike a claimed COG it needs no geospatial writer or unverified metadata
    propagation.  COG publication belongs to WP-09.
    """
    if not (0.0 <= low_percentile < high_percentile <= 100.0):
        raise ValueError("percentiles must satisfy 0 <= low < high <= 100")
    if digest_file(registered.data_path) != registered.source_digests["data"]:
        raise ProductRegistrationError(
            "input.checksum_mismatch", "source bytes changed since registration"
        )
    try:
        dataset = open_raster_allowlisted(registered.data_path)
    except RasterioNotInstalledError as exc:
        raise ProductRegistrationError("input.raster_driver_not_allowed", str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise ProductRegistrationError("input.raster_driver_not_allowed", str(exc)) from exc
    try:
        array = dataset.read()[0].astype(np.float32, copy=False)
    except (OSError, ValueError, IndexError) as exc:
        raise ProductRegistrationError("input.raster_driver_not_allowed", str(exc)) from exc
    finally:
        dataset.close()
    valid = np.isfinite(array)
    if registered.nodata is not None:
        valid &= array != registered.nodata
    if not valid.any():
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "raster contains no finite non-nodata pixels"
        )
    low, high = (
        float(item) for item in np.percentile(array[valid], [low_percentile, high_percentile])
    )
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "raster normalization interval is degenerate"
        )
    preview = np.zeros(array.shape, dtype=np.uint8)
    preview[valid] = np.clip((array[valid] - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Do not put a provider-controlled product_id into a filesystem name.  A
    # source digest is already a canonical, safe identity and makes derived
    # paths independent of punctuation, path separators, or traversal text in
    # the manifest identifier.
    request_key = digest_json(
        {
            "source_data_sha256": registered.source_digests["data"],
            "operation": "first_band_percentile_normalization",
            "low_percentile": low_percentile,
            "high_percentile": high_percentile,
        }
    )
    safe_stem = f"preview-{request_key[:24]}"
    resolved_output_dir = output_dir.resolve()
    bundle_path = (resolved_output_dir / f"{safe_stem}.bundle").resolve()
    array_path = bundle_path / "preview.npy"
    provenance_path = bundle_path / "provenance.json"
    try:
        array_path.relative_to(resolved_output_dir)
        provenance_path.relative_to(resolved_output_dir)
    except ValueError as exc:  # defensive invariant if output naming changes later
        raise ProductRegistrationError(
            "input.hostile_label", "derived output escaped output directory"
        ) from exc
    if bundle_path.exists():
        try:
            existing = json.loads(provenance_path.read_text(encoding="utf-8"))
            if existing.get("request_key") == request_key and digest_file(
                array_path
            ) == existing.get("output_sha256"):
                return DerivedProduct(
                    array_path,
                    provenance_path,
                    registered.source_digests["data"],
                    str(existing["output_sha256"]),
                    float(existing["low_value"]),
                    float(existing["high_value"]),
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ProductRegistrationError(
                "input.label_raster_disagreement",
                "existing derived preview provenance is invalid",
            ) from exc
        raise ProductRegistrationError(
            "input.label_raster_disagreement",
            "existing derived preview does not match requested provenance",
        )
    staging_path = Path(tempfile.mkdtemp(prefix=f".{safe_stem}-", dir=resolved_output_dir))
    staging_array = staging_path / "preview.npy"
    staging_provenance = staging_path / "provenance.json"
    try:
        with staging_array.open("xb") as handle:
            np.save(handle, preview, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        normalized_sha256 = digest_file(staging_array)
        provenance = {
            "schema_version": "1.0",
            "created_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "operation": "first_band_percentile_normalization",
            "source_path": str(registered.data_path),
            "source_data_sha256": registered.source_digests["data"],
            "source_label_sha256": registered.source_digests["label"],
            "output_sha256": normalized_sha256,
            "request_key": request_key,
            "low_percentile": low_percentile,
            "high_percentile": high_percentile,
            "low_value": low,
            "high_value": high,
            "nodata": registered.nodata,
        }
        provenance["provenance_sha256"] = digest_json(provenance)
        with staging_provenance.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(staging_path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.rename(staging_path, bundle_path)
        directory_fd = os.open(resolved_output_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise ProductRegistrationError(
            "input.label_raster_disagreement", "derived preview bundle already exists"
        ) from exc
    except OSError as exc:
        raise ProductRegistrationError("input.raster_driver_not_allowed", str(exc)) from exc
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path)
    return DerivedProduct(
        array_path, provenance_path, registered.source_digests["data"], normalized_sha256, low, high
    )
