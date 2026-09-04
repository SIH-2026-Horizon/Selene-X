"""The correspondence catalogue as CSV (plan section 6.4, WP-09 task 3, CSV half).

**Scope note.** The plan's product is "matches as GeoPackage and CSV using the
canonical schema." GeoPackage needs a spatial library (``fiona``/GDAL) that is
not installed in this repository, so this module writes the CSV half only: a
flat, tabular serialisation of ``tuple[CorrespondenceRecord, ...]``. The
canonical schema is ``schemas/correspondence-record.schema.json``.

**Layering.** ``selene_core.products`` sits below ``selene_core.pipeline`` in
the ``core-layers`` import-linter contract, so this module may not import
``selene_core.pipeline`` (including its ``atomic_write`` helper). The small
"write to scratch, fsync, ``os.replace``, fsync the directory" pattern is
reimplemented locally below rather than imported, per that contract.

**Column layout.** One CSV row per :class:`~selene_core.match.correspondence.
CorrespondenceRecord`, columns following the record's own field-group order
(identity, position, evidence, geometry, refinement, uncertainty, quality,
coverage, provenance). A nested type is flattened into one column per
component, dotted with its field name, for example ``source_pixel.line`` /
``source_pixel.sample``, or ``covariance.xx`` / ``.xy`` / ``.yy`` / ``.frame``
/ ``.units``. When an optional nested value is ``None``, every one of its
component columns is written as an empty string; there is no partial-nested
case because every nested type here is all-or-nothing on the record (pydantic
requires every field of, say, ``Covariance2D`` together, never some subset).
``prior_displacement_px`` and ``residual_from_prior_px`` are each ``(dy, dx)``
tuples, split into two columns per field suffixed ``.dy`` / ``.dx`` (matching
this project's internal line/sample = row/column = y/x pixel convention).

``None`` is always an empty CSV field, never the literal string ``"None"`` or
a fabricated ``0``/``""``-meaning-something-else. Enum fields (``PointRole``,
``NmsStatus``) are written as their string value. Boolean fields are written
as the literal lowercase strings ``"true"`` / ``"false"``, never Python's
``"True"`` / ``"False"``, so the file stays unambiguous stdlib CSV rather than
a Python-specific rendering.

``estimator_identities`` (``tuple[str, ...]``) is written as a single column,
its elements joined with ``;`` (:data:`_IDENTITY_DELIMITER`). An empty tuple
is written as an empty string. Because ``;`` could in principle appear inside
a caller-supplied identity string, :func:`write_correspondence_csv` checks
every identity against the delimiter before writing anything and raises
:class:`IdentityDelimiterCollisionError` if one contains it, rather than
silently joining and producing a value that would not round-trip.
"""

from __future__ import annotations

import csv
import io
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from selene_core.hashing import digest_file
from selene_core.match.correspondence import CorrespondenceRecord, NmsStatus, PointRole
from selene_core.types import (
    Covariance2D,
    CovarianceFrame,
    LocalWarpJacobian,
    MapCoordinate,
    ReferencePixel,
    SourcePixel,
)

__all__ = [
    "CsvWriteResult",
    "DestinationDirectoryMissingError",
    "IdentityDelimiterCollisionError",
    "read_correspondence_csv",
    "write_correspondence_csv",
]

_IDENTITY_DELIMITER = ";"
"""Joins ``estimator_identities`` entries into one CSV field.

A semicolon is a reasonable choice because match IDs, algorithm names, and
digests in this project's other contracts do not contain one — but that is
verified, not assumed: :func:`write_correspondence_csv` rejects any identity
that contains this character instead of silently joining and corrupting it.
"""

_TRUE = "true"
_FALSE = "false"

_FIELDNAMES: tuple[str, ...] = (
    # -- Identity --------------------------------------------------------
    "match_id",
    "job_id",
    "algorithm",
    "algorithm_version",
    "tile_id",
    "pyramid_level",
    "selection_reason",
    # -- Position ----------------------------------------------------------
    "source_pixel.line",
    "source_pixel.sample",
    "reference_pixel.line",
    "reference_pixel.sample",
    "ground_coordinate.x_m",
    "ground_coordinate.y_m",
    "ground_coordinate.crs_wkt",
    # -- Evidence ------------------------------------------------------
    "raw_score",
    "calibrated_confidence",
    "descriptor_channel_agreement",
    "forward_backward_error_px",
    # -- Geometry --------------------------------------------------------
    "prior_displacement_px.dy",
    "prior_displacement_px.dx",
    "residual_from_prior_px.dy",
    "residual_from_prior_px.dx",
    "robust_model_residual_px",
    "local_warp_jacobian.d_ref_line_d_src_line",
    "local_warp_jacobian.d_ref_line_d_src_sample",
    "local_warp_jacobian.d_ref_sample_d_src_line",
    "local_warp_jacobian.d_ref_sample_d_src_sample",
    # -- Refinement ------------------------------------------------------
    "coarse_location.line",
    "coarse_location.sample",
    "refined_location.line",
    "refined_location.sample",
    "estimator_identities",
    "estimator_disagreement_px",
    # -- Uncertainty -----------------------------------------------------
    "covariance.xx",
    "covariance.xy",
    "covariance.yy",
    "covariance.frame",
    "covariance.units",
    "covariance_method",
    "covariance_calibrated",
    # -- Quality ---------------------------------------------------------
    "is_candidate",
    "is_inlier",
    "point_role",
    "rejection_reason",
    "nms_status",
    # -- Coverage ----------------------------------------------------------
    "eligible_cell_id",
    "grid_level",
    "selected_for_coverage",
    "coverage_selection_rationale",
    # -- Provenance ------------------------------------------------------
    "input_digest",
    "reference_digest",
    "parameter_set_digest",
    "code_revision",
)


class DestinationDirectoryMissingError(OSError):
    """``write_correspondence_csv``'s destination has no existing parent directory.

    Raised instead of silently creating one: whether a directory tree should
    be created is a policy decision above this function's scope.
    """


class IdentityDelimiterCollisionError(ValueError):
    """An ``estimator_identities`` entry contains :data:`_IDENTITY_DELIMITER`.

    Raised rather than silently joining and producing a value that would not
    parse back to the original tuple.
    """


@dataclass(frozen=True, slots=True)
class CsvWriteResult:
    """The outcome of a successful :func:`write_correspondence_csv` call."""

    destination: Path
    row_count: int
    sha256: str


# ---------------------------------------------------------------------------
# Local atomic-write helper.
#
# Modelled on selene_core.pipeline.artifacts.atomic_write's pattern (write to
# scratch in the destination's own directory, fsync, os.replace, fsync the
# directory, clean up scratch on any exception) but independently implemented
# here because selene_core.products may not import selene_core.pipeline (the
# core-layers import-linter contract). Unlike that helper, this one does NOT
# create the destination's parent directory: a missing parent is reported to
# the caller as DestinationDirectoryMissingError instead.
# ---------------------------------------------------------------------------


def _atomic_write_bytes(destination: Path, data: bytes) -> None:
    if not destination.parent.is_dir():
        raise DestinationDirectoryMissingError(
            f"cannot write {destination}: parent directory {destination.parent} does not exist"
        )
    handle, temporary_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".partial"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as file_object:
            file_object.write(data)
            file_object.flush()
            os.fsync(file_object.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# ---------------------------------------------------------------------------
# Scalar (de)serialisation helpers. None is always an empty field, never a
# fabricated value.
# ---------------------------------------------------------------------------


def _opt_str(value: str | None) -> str:
    return "" if value is None else value


def _parse_opt_str(value: str) -> str | None:
    return None if value == "" else value


def _opt_number(value: float | None) -> str:
    # str() on a float gives the shortest string that round-trips back to the
    # same float via float(), which is exactly what a lossless round trip
    # needs; int is handled the same way since str(int) round-trips via int().
    return "" if value is None else str(value)


def _parse_opt_float(value: str) -> float | None:
    return None if value == "" else float(value)


def _parse_opt_int(value: str) -> int | None:
    return None if value == "" else int(value)


def _bool_str(value: bool) -> str:
    return _TRUE if value else _FALSE


def _parse_bool(value: str) -> bool:
    if value == _TRUE:
        return True
    if value == _FALSE:
        return False
    raise ValueError(f"expected {_TRUE!r} or {_FALSE!r}, got {value!r}")


def _opt_pair(value: tuple[float, float] | None) -> tuple[str, str]:
    if value is None:
        return ("", "")
    dy, dx = value
    return (str(dy), str(dx))


def _parse_opt_pair(dy_raw: str, dx_raw: str) -> tuple[float, float] | None:
    if dy_raw == "" and dx_raw == "":
        return None
    if dy_raw == "" or dx_raw == "":
        raise ValueError(
            f"expected both components of a pixel-displacement pair to be present or both "
            f"empty, got dy={dy_raw!r}, dx={dx_raw!r}"
        )
    return (float(dy_raw), float(dx_raw))


def _identities_str(identities: tuple[str, ...]) -> str:
    for identity in identities:
        if _IDENTITY_DELIMITER in identity:
            raise IdentityDelimiterCollisionError(
                f"estimator_identities entry {identity!r} contains the delimiter "
                f"{_IDENTITY_DELIMITER!r}; choose an identity without it"
            )
    return _IDENTITY_DELIMITER.join(identities)


def _parse_identities(value: str) -> tuple[str, ...]:
    return () if value == "" else tuple(value.split(_IDENTITY_DELIMITER))


# ---------------------------------------------------------------------------
# Record <-> row.
# ---------------------------------------------------------------------------


def _record_to_row(record: CorrespondenceRecord) -> dict[str, str]:
    prior_dy, prior_dx = _opt_pair(record.prior_displacement_px)
    residual_dy, residual_dx = _opt_pair(record.residual_from_prior_px)

    ground = record.ground_coordinate
    jacobian = record.local_warp_jacobian
    coarse = record.coarse_location
    refined = record.refined_location
    covariance = record.covariance

    return {
        "match_id": record.match_id,
        "job_id": record.job_id,
        "algorithm": record.algorithm,
        "algorithm_version": record.algorithm_version,
        "tile_id": _opt_str(record.tile_id),
        "pyramid_level": _opt_number(record.pyramid_level),
        "selection_reason": _opt_str(record.selection_reason),
        "source_pixel.line": str(record.source_pixel.line),
        "source_pixel.sample": str(record.source_pixel.sample),
        "reference_pixel.line": str(record.reference_pixel.line),
        "reference_pixel.sample": str(record.reference_pixel.sample),
        "ground_coordinate.x_m": "" if ground is None else str(ground.x_m),
        "ground_coordinate.y_m": "" if ground is None else str(ground.y_m),
        "ground_coordinate.crs_wkt": "" if ground is None else ground.crs_wkt,
        "raw_score": str(record.raw_score),
        "calibrated_confidence": _opt_number(record.calibrated_confidence),
        "descriptor_channel_agreement": _opt_number(record.descriptor_channel_agreement),
        "forward_backward_error_px": _opt_number(record.forward_backward_error_px),
        "prior_displacement_px.dy": prior_dy,
        "prior_displacement_px.dx": prior_dx,
        "residual_from_prior_px.dy": residual_dy,
        "residual_from_prior_px.dx": residual_dx,
        "robust_model_residual_px": _opt_number(record.robust_model_residual_px),
        "local_warp_jacobian.d_ref_line_d_src_line": (
            "" if jacobian is None else str(jacobian.d_ref_line_d_src_line)
        ),
        "local_warp_jacobian.d_ref_line_d_src_sample": (
            "" if jacobian is None else str(jacobian.d_ref_line_d_src_sample)
        ),
        "local_warp_jacobian.d_ref_sample_d_src_line": (
            "" if jacobian is None else str(jacobian.d_ref_sample_d_src_line)
        ),
        "local_warp_jacobian.d_ref_sample_d_src_sample": (
            "" if jacobian is None else str(jacobian.d_ref_sample_d_src_sample)
        ),
        "coarse_location.line": "" if coarse is None else str(coarse.line),
        "coarse_location.sample": "" if coarse is None else str(coarse.sample),
        "refined_location.line": "" if refined is None else str(refined.line),
        "refined_location.sample": "" if refined is None else str(refined.sample),
        "estimator_identities": _identities_str(record.estimator_identities),
        "estimator_disagreement_px": _opt_number(record.estimator_disagreement_px),
        "covariance.xx": "" if covariance is None else str(covariance.xx),
        "covariance.xy": "" if covariance is None else str(covariance.xy),
        "covariance.yy": "" if covariance is None else str(covariance.yy),
        "covariance.frame": "" if covariance is None else covariance.frame.value,
        "covariance.units": "" if covariance is None else covariance.units,
        "covariance_method": _opt_str(record.covariance_method),
        "covariance_calibrated": _bool_str(record.covariance_calibrated),
        "is_candidate": _bool_str(record.is_candidate),
        "is_inlier": _bool_str(record.is_inlier),
        "point_role": record.point_role.value,
        "rejection_reason": _opt_str(record.rejection_reason),
        "nms_status": "" if record.nms_status is None else record.nms_status.value,
        "eligible_cell_id": _opt_str(record.eligible_cell_id),
        "grid_level": _opt_number(record.grid_level),
        "selected_for_coverage": _bool_str(record.selected_for_coverage),
        "coverage_selection_rationale": _opt_str(record.coverage_selection_rationale),
        "input_digest": record.input_digest,
        "reference_digest": record.reference_digest,
        "parameter_set_digest": record.parameter_set_digest,
        "code_revision": _opt_str(record.code_revision),
    }


def _row_to_record(row: dict[str, str]) -> CorrespondenceRecord:
    ground_x = row["ground_coordinate.x_m"]
    ground_y = row["ground_coordinate.y_m"]
    ground_crs = row["ground_coordinate.crs_wkt"]
    ground_coordinate: MapCoordinate | None = None
    if ground_x != "" or ground_y != "" or ground_crs != "":
        ground_coordinate = MapCoordinate(
            x_m=float(ground_x), y_m=float(ground_y), crs_wkt=ground_crs
        )

    jacobian_fields = (
        row["local_warp_jacobian.d_ref_line_d_src_line"],
        row["local_warp_jacobian.d_ref_line_d_src_sample"],
        row["local_warp_jacobian.d_ref_sample_d_src_line"],
        row["local_warp_jacobian.d_ref_sample_d_src_sample"],
    )
    local_warp_jacobian: LocalWarpJacobian | None = None
    if any(field != "" for field in jacobian_fields):
        (
            d_ref_line_d_src_line,
            d_ref_line_d_src_sample,
            d_ref_sample_d_src_line,
            d_ref_sample_d_src_sample,
        ) = (float(field) for field in jacobian_fields)
        local_warp_jacobian = LocalWarpJacobian(
            d_ref_line_d_src_line=d_ref_line_d_src_line,
            d_ref_line_d_src_sample=d_ref_line_d_src_sample,
            d_ref_sample_d_src_line=d_ref_sample_d_src_line,
            d_ref_sample_d_src_sample=d_ref_sample_d_src_sample,
        )

    coarse_line, coarse_sample = row["coarse_location.line"], row["coarse_location.sample"]
    coarse_location: SourcePixel | None = None
    if coarse_line != "" or coarse_sample != "":
        coarse_location = SourcePixel(line=float(coarse_line), sample=float(coarse_sample))

    refined_line, refined_sample = row["refined_location.line"], row["refined_location.sample"]
    refined_location: SourcePixel | None = None
    if refined_line != "" or refined_sample != "":
        refined_location = SourcePixel(line=float(refined_line), sample=float(refined_sample))

    covariance_fields = (
        row["covariance.xx"],
        row["covariance.xy"],
        row["covariance.yy"],
        row["covariance.frame"],
        row["covariance.units"],
    )
    covariance: Covariance2D | None = None
    if any(field != "" for field in covariance_fields):
        xx_raw, xy_raw, yy_raw, frame_raw, units_raw = covariance_fields
        covariance = Covariance2D(
            xx=float(xx_raw),
            xy=float(xy_raw),
            yy=float(yy_raw),
            frame=CovarianceFrame(frame_raw),
            units=units_raw,
        )

    nms_status_raw = row["nms_status"]
    nms_status = None if nms_status_raw == "" else NmsStatus(nms_status_raw)

    return CorrespondenceRecord(
        match_id=row["match_id"],
        job_id=row["job_id"],
        algorithm=row["algorithm"],
        algorithm_version=row["algorithm_version"],
        tile_id=_parse_opt_str(row["tile_id"]),
        pyramid_level=_parse_opt_int(row["pyramid_level"]),
        selection_reason=_parse_opt_str(row["selection_reason"]),
        source_pixel=SourcePixel(
            line=float(row["source_pixel.line"]), sample=float(row["source_pixel.sample"])
        ),
        reference_pixel=ReferencePixel(
            line=float(row["reference_pixel.line"]),
            sample=float(row["reference_pixel.sample"]),
        ),
        ground_coordinate=ground_coordinate,
        raw_score=float(row["raw_score"]),
        calibrated_confidence=_parse_opt_float(row["calibrated_confidence"]),
        descriptor_channel_agreement=_parse_opt_float(row["descriptor_channel_agreement"]),
        forward_backward_error_px=_parse_opt_float(row["forward_backward_error_px"]),
        prior_displacement_px=_parse_opt_pair(
            row["prior_displacement_px.dy"], row["prior_displacement_px.dx"]
        ),
        residual_from_prior_px=_parse_opt_pair(
            row["residual_from_prior_px.dy"], row["residual_from_prior_px.dx"]
        ),
        robust_model_residual_px=_parse_opt_float(row["robust_model_residual_px"]),
        local_warp_jacobian=local_warp_jacobian,
        coarse_location=coarse_location,
        refined_location=refined_location,
        estimator_identities=_parse_identities(row["estimator_identities"]),
        estimator_disagreement_px=_parse_opt_float(row["estimator_disagreement_px"]),
        covariance=covariance,
        covariance_method=_parse_opt_str(row["covariance_method"]),
        covariance_calibrated=_parse_bool(row["covariance_calibrated"]),
        is_candidate=_parse_bool(row["is_candidate"]),
        is_inlier=_parse_bool(row["is_inlier"]),
        point_role=PointRole(row["point_role"]),
        rejection_reason=_parse_opt_str(row["rejection_reason"]),
        nms_status=nms_status,
        eligible_cell_id=_parse_opt_str(row["eligible_cell_id"]),
        grid_level=_parse_opt_int(row["grid_level"]),
        selected_for_coverage=_parse_bool(row["selected_for_coverage"]),
        coverage_selection_rationale=_parse_opt_str(row["coverage_selection_rationale"]),
        input_digest=row["input_digest"],
        reference_digest=row["reference_digest"],
        parameter_set_digest=row["parameter_set_digest"],
        code_revision=_parse_opt_str(row["code_revision"]),
    )


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def write_correspondence_csv(
    records: tuple[CorrespondenceRecord, ...], destination: Path
) -> CsvWriteResult:
    """Serialise ``records`` to a CSV file, atomically published at ``destination``.

    An empty ``records`` tuple is not an error: it writes a valid CSV
    containing only the header row, because a scene with zero correspondences
    is a real, reportable outcome.

    Args:
        records: The correspondence records to write, in the order given.
        destination: The file path to publish the CSV to. Its parent
            directory must already exist.

    Returns:
        The published destination, row count, and SHA-256 of the published
        bytes.

    Raises:
        DestinationDirectoryMissingError: If ``destination``'s parent
            directory does not exist. This function never creates one.
        IdentityDelimiterCollisionError: If any record's
            ``estimator_identities`` contains :data:`_IDENTITY_DELIMITER`.
    """
    buffer = io.StringIO()
    writer: csv.DictWriter[str] = csv.DictWriter(
        buffer, fieldnames=list(_FIELDNAMES), lineterminator="\n"
    )
    writer.writeheader()
    for record in records:
        writer.writerow(_record_to_row(record))

    data = buffer.getvalue().encode("utf-8")
    _atomic_write_bytes(destination, data)

    return CsvWriteResult(
        destination=destination, row_count=len(records), sha256=digest_file(destination)
    )


def read_correspondence_csv(source: Path) -> tuple[CorrespondenceRecord, ...]:
    """Parse a CSV written by :func:`write_correspondence_csv` back into records.

    Args:
        source: The CSV file to read.

    Returns:
        The records in file order, each validated by
        :class:`~selene_core.match.correspondence.CorrespondenceRecord`'s own
        constructor.
    """
    with source.open("r", newline="", encoding="utf-8") as file_object:
        reader: csv.DictReader[str] = csv.DictReader(file_object)
        return tuple(_row_to_record(row) for row in reader)
