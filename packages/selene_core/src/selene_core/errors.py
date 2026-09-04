"""The stable failure taxonomy (WP-09 task 8).

Two properties make this taxonomy worth having:

* **Retry is keyed by code, not by exception type.** A deterministic validation
  failure and a scientific gate failure never retry, because retrying them burns
  resources to reach the same answer. A transient resource or device failure
  does (plan section 6.5).
* **Every code carries a remediation hint.** A failure that only says what went
  wrong leaves the user to guess what to do, which is the difference between a
  refusal and a dead end. Producing no answer with a specific diagnosis is
  preferable to emitting an unqualified registration (plan section 2).

Codes are append-only. Renaming one breaks every stored run that recorded it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "FailureCategory",
    "FailureCode",
    "FailureDefinition",
    "definition_for",
    "is_retryable",
]


class FailureCategory(StrEnum):
    """The stage family a failure belongs to."""

    INPUT = "input"
    REFERENCE = "reference"
    GEOMETRY = "geometry"
    MATCHING = "matching"
    REFINEMENT = "refinement"
    COVERAGE = "coverage"
    ADJUSTMENT = "adjustment"
    PRODUCT = "product"
    VALIDATION = "validation"
    RESOURCE = "resource"
    INTERNAL = "internal"


class FailureCode(StrEnum):
    """A stable, machine-readable failure identity."""

    # Input and ingestion (WP-02)
    INPUT_MISSING_FILE = "input.missing_file"
    INPUT_CHECKSUM_MISMATCH = "input.checksum_mismatch"
    INPUT_LABEL_UNPARSEABLE = "input.label_unparseable"
    INPUT_LABEL_RASTER_DISAGREEMENT = "input.label_raster_disagreement"
    INPUT_HOSTILE_LABEL = "input.hostile_label"
    INPUT_RASTER_DRIVER_NOT_ALLOWED = "input.raster_driver_not_allowed"
    INPUT_UNSUPPORTED_PAYLOAD = "input.unsupported_payload"
    INPUT_NOT_CALIBRATED = "input.not_calibrated"
    INPUT_RESOURCE_LIMIT_EXCEEDED = "input.resource_limit_exceeded"

    # Reference and control (WP-03)
    REFERENCE_NO_COVERAGE = "reference.no_coverage"
    REFERENCE_BUNDLE_INCOMPLETE = "reference.bundle_incomplete"
    REFERENCE_TERRAIN_OUT_OF_COVERAGE = "reference.terrain_out_of_coverage"
    REFERENCE_CONTROL_UNAVAILABLE = "reference.control_unavailable"

    # Geometry (WP-03)
    GEOMETRY_KERNEL_COVERAGE_GAP = "geometry.kernel_coverage_gap"
    GEOMETRY_MODEL_UNVALIDATED = "geometry.model_unvalidated"
    GEOMETRY_FOOTPRINT_DISAGREEMENT = "geometry.footprint_disagreement"
    GEOMETRY_NO_OVERLAP = "geometry.no_overlap"
    GEOMETRY_CRS_UNRESOLVED = "geometry.crs_unresolved"

    # Matching (WP-04, WP-06)
    MATCHING_INSUFFICIENT_CANDIDATES = "matching.insufficient_candidates"
    MATCHING_ALL_REGIONS_MASKED = "matching.all_regions_masked"
    MATCHING_PRIOR_EXCEEDED = "matching.prior_exceeded"
    MATCHING_MODEL_UNAVAILABLE = "matching.model_unavailable"

    # Refinement (WP-08)
    REFINEMENT_DID_NOT_CONVERGE = "refinement.did_not_converge"
    REFINEMENT_COVARIANCE_INVALID = "refinement.covariance_invalid"
    REFINEMENT_ESTIMATOR_DISAGREEMENT = "refinement.estimator_disagreement"

    # Coverage and selection (WP-07)
    COVERAGE_INSUFFICIENT_OCCUPANCY = "coverage.insufficient_occupancy"
    COVERAGE_ELIGIBLE_AREA_TOO_SMALL = "coverage.eligible_area_too_small"

    # Adjustment (WP-08)
    ADJUSTMENT_RANK_DEFICIENT = "adjustment.rank_deficient"
    ADJUSTMENT_DID_NOT_CONVERGE = "adjustment.did_not_converge"
    ADJUSTMENT_WITHHELD_ERROR_EXCEEDED = "adjustment.withheld_error_exceeded"

    # Product writing (WP-09)
    PRODUCT_WRITE_FAILED = "product.write_failed"
    PRODUCT_SCHEMA_INVALID = "product.schema_invalid"
    PRODUCT_CHECKSUM_MISMATCH = "product.checksum_mismatch"

    # Validation and gates (WP-09)
    VALIDATION_UNKNOWN_PARAMETER = "validation.unknown_parameter"
    VALIDATION_REQUIRED_METRIC_MISSING = "validation.required_metric_missing"
    VALIDATION_ROUTE_NOT_QUALIFIED = "validation.route_not_qualified"
    VALIDATION_UNITS_INCONSISTENT = "validation.units_inconsistent"

    # Resources (R-013)
    RESOURCE_MEMORY_BUDGET_EXCEEDED = "resource.memory_budget_exceeded"
    RESOURCE_STORAGE_EXHAUSTED = "resource.storage_exhausted"
    RESOURCE_TIMEOUT = "resource.timeout"
    RESOURCE_DEVICE_UNAVAILABLE = "resource.device_unavailable"

    # Runner
    INTERNAL_CANCELLED = "internal.cancelled"
    INTERNAL_UNEXPECTED_ERROR = "internal.unexpected_error"


@dataclass(frozen=True, slots=True)
class FailureDefinition:
    """What a failure code means, whether retrying it can help, and what to do."""

    code: FailureCode
    category: FailureCategory
    retryable: bool
    summary: str
    remediation: str


def _define(
    code: FailureCode,
    category: FailureCategory,
    retryable: bool,
    summary: str,
    remediation: str,
) -> tuple[FailureCode, FailureDefinition]:
    return code, FailureDefinition(code, category, retryable, summary, remediation)


_I = FailureCategory.INPUT
_R = FailureCategory.REFERENCE
_G = FailureCategory.GEOMETRY
_M = FailureCategory.MATCHING
_F = FailureCategory.REFINEMENT
_C = FailureCategory.COVERAGE
_A = FailureCategory.ADJUSTMENT
_P = FailureCategory.PRODUCT
_V = FailureCategory.VALIDATION
_S = FailureCategory.RESOURCE
_X = FailureCategory.INTERNAL

_DEFINITIONS: Final[dict[FailureCode, FailureDefinition]] = dict(
    [
        _define(
            FailureCode.INPUT_MISSING_FILE,
            _I,
            False,
            "A file named by the product manifest was not found.",
            "Re-run acquisition for this product, then re-validate it.",
        ),
        _define(
            FailureCode.INPUT_CHECKSUM_MISMATCH,
            _I,
            False,
            "A file's bytes do not match the SHA-256 recorded in the manifest.",
            "The file is truncated, corrupted, or a different version. Re-download it and "
            "compare against the acquisition manifest before re-validating.",
        ),
        _define(
            FailureCode.INPUT_LABEL_UNPARSEABLE,
            _I,
            False,
            "A PDS4 XML or ISIS PVL label could not be parsed within the configured limits.",
            "Check the label against the archive copy. If it is valid but exceeds a size or "
            "recursion limit, raise that limit deliberately rather than disabling it.",
        ),
        _define(
            FailureCode.INPUT_LABEL_RASTER_DISAGREEMENT,
            _I,
            False,
            "The label and the raster disagree on shape, dtype, band count, or nodata.",
            "Do not process this product. Establish which of the two is authoritative with "
            "the data provider and re-acquire.",
        ),
        _define(
            FailureCode.INPUT_HOSTILE_LABEL,
            _I,
            False,
            "A label attempted entity expansion, external entity resolution, or path escape.",
            "Treat the product as untrusted and quarantined. Report it; do not relax the "
            "parser to accept it.",
        ),
        _define(
            FailureCode.INPUT_RASTER_DRIVER_NOT_ALLOWED,
            _I,
            False,
            "The raster requires a GDAL driver outside the allow-list.",
            "Convert the product to an allow-listed format, or extend the allow-list only "
            "after reviewing that driver's parsing surface.",
        ),
        _define(
            FailureCode.INPUT_UNSUPPORTED_PAYLOAD,
            _I,
            False,
            "No payload adapter claims this product.",
            "Confirm the payload is one of OHRC, TMC-2, or IIRS. Other payloads are out of "
            "scope for the MVP.",
        ),
        _define(
            FailureCode.INPUT_NOT_CALIBRATED,
            _I,
            False,
            "The product is not at the calibration level the pipeline requires.",
            "Supply the calibrated product level named in the payload adapter documentation.",
        ),
        _define(
            FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED,
            _I,
            False,
            "Parsing or decompression exceeded a configured resource limit.",
            "The input may be a decompression bomb. Inspect it before raising any limit.",
        ),
        _define(
            FailureCode.REFERENCE_NO_COVERAGE,
            _R,
            False,
            "No configured reference product covers the source footprint.",
            "Acquire reference imagery for this region, or choose a different route.",
        ),
        _define(
            FailureCode.REFERENCE_BUNDLE_INCOMPLETE,
            _R,
            False,
            "The reference bundle is missing a required version, mask, or uncertainty layer.",
            "Complete the reference bundle manifest. An unversioned reference cannot support "
            "a reproducible claim.",
        ),
        _define(
            FailureCode.REFERENCE_TERRAIN_OUT_OF_COVERAGE,
            _R,
            False,
            "The scene lies outside the terrain source's valid coverage.",
            "SLDEM2015 is limited to roughly 60 degrees south to 60 degrees north. Select "
            "LOLA or an appropriate polar product for this latitude.",
        ),
        _define(
            FailureCode.REFERENCE_CONTROL_UNAVAILABLE,
            _R,
            False,
            "An absolute accuracy claim was requested without an independent control source.",
            "Either supply a named control realisation with its uncertainty, or request "
            "image-relative metrics only.",
        ),
        _define(
            FailureCode.GEOMETRY_KERNEL_COVERAGE_GAP,
            _G,
            False,
            "Furnished SPICE kernels do not cover the acquisition interval.",
            "Furnish reconstructed kernels spanning the interval and re-validate the product.",
        ),
        _define(
            FailureCode.GEOMETRY_MODEL_UNVALIDATED,
            _G,
            False,
            "The payload's sensor model has not passed geometry validation.",
            "IIRS geometry remains unvalidated pending D-004. Use a qualified route, or "
            "record the result as experimental.",
        ),
        _define(
            FailureCode.GEOMETRY_FOOTPRINT_DISAGREEMENT,
            _G,
            False,
            "The computed footprint disagrees with the published or independently computed one.",
            "Do not trust the prior. Investigate kernel priority, timing, and the sensor "
            "model before proceeding.",
        ),
        _define(
            FailureCode.GEOMETRY_NO_OVERLAP,
            _G,
            False,
            "Source and reference footprints do not overlap sufficiently to register.",
            "Select a reference product that covers the source scene.",
        ),
        _define(
            FailureCode.GEOMETRY_CRS_UNRESOLVED,
            _G,
            False,
            "A body-fixed frame or map projection could not be resolved for this scene.",
            "Resolve ADR-0002 for this latitude band before processing the scene.",
        ),
        _define(
            FailureCode.MATCHING_INSUFFICIENT_CANDIDATES,
            _M,
            False,
            "Too few candidate correspondences survived matching.",
            "Check illumination difference, GSD ratio, and eligible area in the preflight "
            "report. This scene may be outside every qualified route.",
        ),
        _define(
            FailureCode.MATCHING_ALL_REGIONS_MASKED,
            _M,
            False,
            "Every candidate region was masked as invalid, shadowed, or ineligible.",
            "Inspect the eligibility mask. A low-sun scene may have no mutually usable area.",
        ),
        _define(
            FailureCode.MATCHING_PRIOR_EXCEEDED,
            _M,
            False,
            "Observed displacement exceeded the metadata-bounded search envelope.",
            "The metadata prior is not bounding this scene (R-003). Widen the bounded coarse "
            "search deliberately, or add a coarse pre-alignment step.",
        ),
        _define(
            FailureCode.MATCHING_MODEL_UNAVAILABLE,
            _M,
            True,
            "The learned matcher's weights or device were unavailable.",
            "The classical fallback should have been used and recorded. Check device "
            "availability and the pinned weights hash.",
        ),
        _define(
            FailureCode.REFINEMENT_DID_NOT_CONVERGE,
            _F,
            False,
            "Sub-pixel refinement failed to converge on enough matches.",
            "Inspect patch texture and peak ambiguity. Low-texture terrain may not support "
            "sub-pixel refinement at this scale.",
        ),
        _define(
            FailureCode.REFINEMENT_COVARIANCE_INVALID,
            _F,
            False,
            "Estimated covariance was not positive definite.",
            "These matches are unusable for uncertainty-weighted adjustment and are dropped "
            "with a recorded reason.",
        ),
        _define(
            FailureCode.REFINEMENT_ESTIMATOR_DISAGREEMENT,
            _F,
            False,
            "The ECC and Fourier estimators disagreed beyond the configured tolerance.",
            "Disagreement means neither estimate is trustworthy here. Review the residual map "
            "before accepting the scene.",
        ),
        _define(
            FailureCode.COVERAGE_INSUFFICIENT_OCCUPANCY,
            _C,
            False,
            "Selected matches do not occupy enough of the eligible grid.",
            "Clustered matches cannot constrain a terrain-aware adjustment. Check the "
            "eligibility mask and the largest empty region.",
        ),
        _define(
            FailureCode.COVERAGE_ELIGIBLE_AREA_TOO_SMALL,
            _C,
            False,
            "The physically eligible overlap is too small to evaluate coverage over.",
            "Select a reference product with greater overlap.",
        ),
        _define(
            FailureCode.ADJUSTMENT_RANK_DEFICIENT,
            _A,
            False,
            "The adjustment is rank deficient: some parameters are not observable.",
            "Reduce the parameter set or regularise from documented priors (R-009). Do not "
            "accept an unobservable solution.",
        ),
        _define(
            FailureCode.ADJUSTMENT_DID_NOT_CONVERGE,
            _A,
            False,
            "The robust adjustment did not converge.",
            "Inspect outlier fraction and conditioning. Convergence failure often means the "
            "correspondence set is contaminated.",
        ),
        _define(
            FailureCode.ADJUSTMENT_WITHHELD_ERROR_EXCEEDED,
            _A,
            False,
            "Withheld check-point error exceeded the route gate.",
            "The route is not qualified for this stratum. This is a scientific result, not a "
            "malfunction.",
        ),
        _define(
            FailureCode.PRODUCT_WRITE_FAILED,
            _P,
            True,
            "An output artefact could not be written.",
            "Check storage availability and permissions, then retry the stage.",
        ),
        _define(
            FailureCode.PRODUCT_SCHEMA_INVALID,
            _P,
            False,
            "A written artefact failed schema validation before publication.",
            "This is a defect in the writer. The partial output was not published.",
        ),
        _define(
            FailureCode.PRODUCT_CHECKSUM_MISMATCH,
            _P,
            True,
            "An artefact's checksum did not match after writing.",
            "Storage may be faulty. Retry; if it recurs, the storage backend is suspect.",
        ),
        _define(
            FailureCode.VALIDATION_UNKNOWN_PARAMETER,
            _V,
            False,
            "A scientific parameter set contained a field the schema does not define.",
            "Unknown parameters are rejected rather than ignored, because an ignored "
            "parameter silently changes nothing while appearing to change something. Correct "
            "the parameter file.",
        ),
        _define(
            FailureCode.VALIDATION_REQUIRED_METRIC_MISSING,
            _V,
            False,
            "An applicable hard-gate metric could not be computed.",
            "A missing applicable hard-gate metric is a rejection, not a pass. Supply the "
            "missing evidence or accept the rejection.",
        ),
        _define(
            FailureCode.VALIDATION_ROUTE_NOT_QUALIFIED,
            _V,
            False,
            "No qualified route version covers this payload, reference, and parameter set.",
            "Qualify the route on the frozen benchmark before using it on a scene.",
        ),
        _define(
            FailureCode.VALIDATION_UNITS_INCONSISTENT,
            _V,
            False,
            "A value arrived in units the receiving contract does not accept.",
            "This is a defect. Use the named conversion functions rather than an inline "
            "correction.",
        ),
        _define(
            FailureCode.RESOURCE_MEMORY_BUDGET_EXCEEDED,
            _S,
            True,
            "A stage exceeded the memory budget declared in its TileSpec.",
            "Reduce the tile core size or raise the declared budget deliberately.",
        ),
        _define(
            FailureCode.RESOURCE_STORAGE_EXHAUSTED,
            _S,
            True,
            "Storage was exhausted while writing scratch or output.",
            "Free space or point the run at a larger volume, then resume from the last "
            "completed stage.",
        ),
        _define(
            FailureCode.RESOURCE_TIMEOUT,
            _S,
            True,
            "A stage or a subprocess exceeded its time limit.",
            "Retry. If it recurs at the same stage, the limit is too tight for this input "
            "size and should be raised deliberately.",
        ),
        _define(
            FailureCode.RESOURCE_DEVICE_UNAVAILABLE,
            _S,
            True,
            "A requested accelerator was unavailable.",
            "Retry, or run the classical CPU route, which remains a first-class path.",
        ),
        _define(
            FailureCode.INTERNAL_CANCELLED,
            _X,
            False,
            "The run was cancelled cooperatively.",
            "Completed stages remain reusable. Resume the run to continue from the last "
            "atomically completed stage.",
        ),
        _define(
            FailureCode.INTERNAL_UNEXPECTED_ERROR,
            _X,
            False,
            "An unhandled error escaped a stage.",
            "This is a defect. The stack trace is in the run log; the failure is not retried "
            "automatically because its cause is unknown.",
        ),
    ]
)


def definition_for(code: FailureCode) -> FailureDefinition:
    """Return the definition of ``code``."""
    return _DEFINITIONS[code]


def is_retryable(code: FailureCode) -> bool:
    """Whether an automatic retry of ``code`` can plausibly succeed.

    Deterministic validation failures and scientific gate failures are never
    retryable: the same inputs produce the same answer, so a retry only spends
    resources to be told the same thing (plan section 6.5).
    """
    return _DEFINITIONS[code].retryable
