"""PayloadAdapter protocol, OHRC/TMC-2/IIRS metadata adapters, and quarantine
(WP-02 tasks 7, 9, 11; task 8 metadata-only).

## Scope ruling (read this before extending anything here)

Plan WP-02 task 8 asks for OHRC/TMC-2 adapters "using documented ISIS/ALE/
usgscsm or equivalent validated paths." None of ISIS, ALE, or usgscsm is
installed or available in this environment, and this codebase has no
verified access to real Chandrayaan-2 archive products or their exact label
field layouts. This module therefore builds exactly one thing: three
**metadata** adapters that parse labels using only the two parsers already
built on this branch (:mod:`selene_core.ingest.pds4`,
:mod:`selene_core.ingest.pvl`) and extract fields defined by the **public
PDS4 Information Model** and the **public ISIS3 cube-label convention** —
both open, documented standards, not ISRO-internal or mission-specific
knowledge.

**Every `PayloadMetadata` this module can produce has `geometry_validated =
False`, unconditionally.** This is enforced twice, deliberately: every
adapter below hardcodes the literal `False` when constructing the result
(never derives it from anything in the label), and
`PayloadMetadata.__post_init__` independently raises if it is ever `True` —
so there is no code path, in this module or a future one reusing this
dataclass, by which a "good" input can flip it. `geometry_validation_note`
is a required, non-empty, adapter-specific reason (also enforced in
`__post_init__`), not a placeholder to apologize for: it is the honest,
machine-readable status plan WP-02's exit criteria explicitly require —
"IIRS preprocessing metadata is available and its geometry validation status
is honest and machine-readable" — and the same honesty is applied to OHRC
and TMC-2 here: metadata-ready, not geometry-ready, in this build.

## What is extracted from the standard, and what is deliberately left `None`

This module reads only the label locations named below, chosen because they
are documented, general-purpose parts of the public PDS4 Information Model
or the public ISIS3 cube-label convention (not something inferred because it
"sounds plausible" for a Chandrayaan-2 product specifically). Anything a
label might carry outside these locations is left `None`, with a warning
explaining why, never guessed:

PDS4 path (built on `parse_pds4_label`; element lookup matches by **local
tag name only**, ignoring any XML namespace prefix — this is a defensive
choice made because this build has no real, namespace-qualified PDS4 label
to verify a namespace-aware lookup against; it works whether or not the
input declares the PDS4 namespace):

* `Identification_Area/logical_identifier` -> `product_id`.
* `Observation_Area/Time_Coordinates/start_date_time` and
  `stop_date_time` -> `acquisition_interval` (parsed as ISO 8601 with an
  explicit UTC offset; a naive or unparseable timestamp is `None` with a
  warning, matching `AcquisitionInterval`'s own tz-aware requirement).
* `Observation_Area/Investigation_Area/name` -> `mission`, falling back to
  a direct `name` child of `Observation_Area/Mission_Area` if
  `Investigation_Area` is absent. `Investigation_Area` is a core, generally
  structured PDS4 IM class; `Mission_Area`'s *internal* structure is a
  mission-specific discipline extension with no single documented shape, so
  the `Mission_Area` fallback is explicitly best-effort, not a claim that
  `Mission_Area/name` is itself a standardized path.
* `File_Area_Observational/Array_2D_Image/Axis_Array` elements, matched by
  their `axis_name` child (`Line`, `Sample`, and sometimes `Band`) ->
  `declared_lines` / `declared_samples` / `declared_bands`.

**Deliberately left `None` on the PDS4 path:** `instrument_id` and
`calibration_state` (always `CalibrationState.UNKNOWN`). Neither has a
location named in this task's authorized scope above; guessing one (for
example, assuming `Observation_Area/Primary_Result_Summary/processing_level`
carries calibration state, which is plausible PDS4 IM structure this author
recalls but cannot verify against a real label in this environment) would
be exactly the "sounds-plausible" guess this task's scope ruling forbids.

ISIS3/PVL path (built on `parse_pvl_label`):

* `IsisCube/Instrument/SpacecraftName` -> `mission`.
* `IsisCube/Instrument/InstrumentId` -> `instrument_id`.
* `IsisCube/Instrument/StartTime` and `StopTime` -> `acquisition_interval`
  (same ISO-8601-with-explicit-UTC-offset rule as above; real ISIS
  `StartTime`/`StopTime` values conventionally have no explicit UTC marker,
  so a naive value here is the common case, not a bug, and correctly
  produces `None` with a warning rather than an assumed-UTC guess).
* `IsisCube/Core/Dimensions/Samples`, `Lines`, `Bands` -> `declared_samples`
  / `declared_lines` / `declared_bands`.
* `IsisCube/BandBin/FilterName`, `Center`, `Width` (and, defensively,
  `BadBand`) -> `BandInfo.center_wavelength_nm` / `.fwhm_nm` /
  `.is_bad_band`, only where a recognised unit (`nm`/`um`/micron variants)
  is attached to the value; an unrecognised or absent unit is `None` with a
  warning, since a bare number's unit cannot be assumed. `BadBand` is not a
  confirmed universal ISIS3 key across every instrument's `BandBin` group —
  this build has no real IIRS label to check it against — so it is read
  defensively under that literal key and is commonly absent, which is the
  expected, honest case.

**Deliberately left `None` on the ISIS3 path:** `product_id` and
`calibration_state` (always `UNKNOWN`) — the three groups this build reads
(`Instrument`, `Core/Dimensions`, `BandBin`) carry no field for either.

**Deliberately not implemented at all:** PDS4 per-band spectral
characteristics (center wavelength / FWHM) for an IIRS label shaped as
PDS4. The brief invites extracting these "from whichever standard location
the label actually provides them ... or PDS4's spectral characteristics
area if using a PDS4-shaped label," but this author could not name the
exact PDS4 IM class/attribute path for band spectral characteristics with
enough confidence to implement it without guessing, so a PDS4-shaped IIRS
label always yields `bands = ()` — never a fabricated value on that path.

## A known, inherited PVL-parser limitation this module works around by documenting it

`selene_core.ingest.pvl.parse_pvl_label` is explicitly a limited-subset PVL
reader (see its own module docstring), and its grammar subset cannot
tokenize an unquoted ISO-8601 date-time literal (e.g. `StartTime =
2021-06-01T12:00:00Z`, written bare, the way real ISIS labels conventionally
write it) as a single value — the embedded `-` and `:` characters break its
number/identifier tokenizing rules. A real-world-shaped ISIS3 label with
unquoted `StartTime`/`StopTime` would therefore fail to parse via
`parse_pvl_label` *entirely* (raising `PvlParseError` before this module's
extraction code ever runs), not merely lose those two fields. This is a
property of the already-reviewed parser this task must build on unchanged
(see "What you must NOT do" — `pvl.py` is not modified here), not a defect
introduced by this module. Every synthetic ISIS3-shaped fixture in this
module's own test suite quotes `StartTime`/`StopTime` as PVL strings (e.g.
`StartTime = "2021-06-01T12:00:00Z"`) precisely so it parses at all under
this constraint; that quoting is a fixture-construction necessity, not a
claim about how real Chandrayaan-2 ISIS labels are formatted.

## Format detection

Each adapter tries `parse_pds4_label` first, then `parse_pvl_label` if that
raises; if both reject the input, `extract()` raises
`UnrecognizedLabelFormatError` rather than returning a `PayloadMetadata`
full of silent `None`s pretending to have succeeded.

## File organization

Kept in one module rather than split into a second `payload_adapters.py`:
the three adapter classes are thin wrappers (a payload family, an expected
instrument-ID set, and a geometry note) around one shared `_build_metadata`
helper, and the quarantine layer is a small, tightly coupled consumer of
`PayloadAdapter`/`PayloadMetadata` defined right here. Splitting would
mostly separate code that reads as one unit into two files that import each
other.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable

from selene_core.errors import FailureCode
from selene_core.ingest.pds4 import Pds4ParseError, parse_pds4_label
from selene_core.ingest.pvl import PvlParseError, PvlQuantity, parse_pvl_label
from selene_core.types import AcquisitionInterval

__all__ = [
    "BandInfo",
    "CalibrationState",
    "IirsAdapter",
    "OhrcAdapter",
    "PayloadAdapter",
    "PayloadFamily",
    "PayloadMetadata",
    "PsfMtfMetadata",
    "QualityMaskMetadata",
    "QuarantineRecord",
    "SensorGeometryInputs",
    "SpectralRegime",
    "Tmc2Adapter",
    "UnrecognizedLabelFormatError",
    "revalidate",
    "validate_product",
]


# ---------------------------------------------------------------------------
# Core vocabulary
# ---------------------------------------------------------------------------


class PayloadFamily(StrEnum):
    """Which Chandrayaan-2 payload a `PayloadMetadata` describes.

    `TMC2`'s *value* is `"TMC-2"` (with a hyphen), matching the string
    spelling already used by `schemas/benchmark-manifest.schema.json`'s
    `payload_family` enum exactly. The member *name* cannot itself contain a
    hyphen, hence the name/value split.
    """

    OHRC = "OHRC"
    TMC2 = "TMC-2"
    IIRS = "IIRS"


class CalibrationState(StrEnum):
    """Whether a product declares itself calibrated, clearly, or not at all.

    A label that doesn't declare its calibration state unambiguously is
    `UNKNOWN`, never guessed into `CALIBRATED` or `UNCALIBRATED`.
    """

    CALIBRATED = "calibrated"
    UNCALIBRATED = "uncalibrated"
    UNKNOWN = "unknown"


class SpectralRegime(StrEnum):
    """How an IIRS band is labelled to be interpreted radiometrically.

    A value is assigned only from an explicit label term; wavelength alone is
    not sufficient evidence to infer reflected versus emitted signal.  This
    preserves the distinction needed by later IIRS processing while making
    absent/unsupported label vocabulary explicitly ``UNKNOWN``.
    """

    REFLECTED = "reflected"
    EMITTED = "emitted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BandInfo:
    """One band's metadata, as declared in a label.

    Every field beyond `band_number` is `None` when the label genuinely does
    not declare it — never a guessed or fabricated default.
    """

    band_number: int
    center_wavelength_nm: float | None
    fwhm_nm: float | None
    is_bad_band: bool | None
    spectral_regime: SpectralRegime = SpectralRegime.UNKNOWN

    def __post_init__(self) -> None:
        if self.band_number < 1:
            raise ValueError(f"BandInfo.band_number must be >= 1, got {self.band_number!r}")
        for name in ("center_wavelength_nm", "fwhm_nm"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"BandInfo.{name} must be finite when set, got {value!r}")


@dataclass(frozen=True, slots=True)
class SensorGeometryInputs:
    """Label-declared inputs needed by a later sensor-model implementation.

    These values are intentionally optional: a label parser may expose useful
    timing and line/sample dimensions while still lacking a validated camera
    model.  ``available`` must therefore never be interpreted as geometry
    validation; that decision remains ``PayloadMetadata.geometry_validated``.
    """

    available: bool = False
    fields: tuple[tuple[str, str], ...] = ()
    note: str = "No validated sensor-model extraction path is installed in this build."


@dataclass(frozen=True, slots=True)
class PsfMtfMetadata:
    """PSF/MTF metadata declared by a label, if any; never inferred."""

    available: bool = False
    note: str = "PSF/MTF metadata was not declared by the supported label paths."


@dataclass(frozen=True, slots=True)
class QualityMaskMetadata:
    """Quality-mask references/semantics declared by a label, if any."""

    available: bool = False
    note: str = "No quality-mask reference was declared by the supported label paths."


@dataclass(frozen=True, slots=True)
class PayloadMetadata:
    """What one adapter extracted from one label.

    `geometry_validated` is `False` in every instance this codebase can
    construct — enforced in `__post_init__` below, independently of every
    adapter already hardcoding the literal `False`. `geometry_validation_note`
    is the required, non-empty, stated reason.

    `declared_lines`/`declared_samples`/`declared_bands` are the raster shape
    **as declared in the label text** — this module never opens the raster
    itself (no raster library is available in this build; see the module
    docstring), so these are a claim about the label, not a claim about the
    pixel data.
    """

    payload_family: PayloadFamily
    product_id: str | None
    mission: str | None
    instrument_id: str | None
    calibration_state: CalibrationState
    acquisition_interval: AcquisitionInterval | None
    declared_lines: int | None
    declared_samples: int | None
    declared_bands: int | None
    bands: tuple[BandInfo, ...]
    geometry_validated: bool
    geometry_validation_note: str
    warnings: tuple[str, ...]
    geometry_inputs: SensorGeometryInputs = field(default_factory=SensorGeometryInputs)
    psf_mtf: PsfMtfMetadata = field(default_factory=PsfMtfMetadata)
    quality_masks: QualityMaskMetadata = field(default_factory=QualityMaskMetadata)

    def __post_init__(self) -> None:
        if self.geometry_validated:
            raise ValueError(
                "PayloadMetadata.geometry_validated must be False in this build; no "
                "adapter in this codebase has a validated geometry path (see the "
                "module docstring's scope ruling). This is enforced here, not only "
                "in adapter code, so nothing can construct a PayloadMetadata "
                "claiming otherwise."
            )
        if not self.geometry_validation_note.strip():
            raise ValueError(
                "PayloadMetadata.geometry_validation_note must be a non-empty stated "
                "reason; 'always False' without a reason is not honest reporting."
            )
        for name in ("declared_lines", "declared_samples", "declared_bands"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(
                    f"PayloadMetadata.{name} must be non-negative when set, got {value!r}"
                )


@runtime_checkable
class PayloadAdapter(Protocol):
    """Given raw label bytes, produce one `PayloadMetadata`.

    Deliberately minimal, following the same `@runtime_checkable` structural
    typing convention as `selene_core.pipeline.runner.Stage`. WP-02 task 7
    lists many responsibilities (timing, band information, sensor geometry
    inputs, PSF/MTF metadata, quality masks).  They are explicit fields on
    `PayloadMetadata`; unavailable values are machine-readable rather than
    silently omitted.  An adapter's only job is producing one complete
    metadata contract.
    """

    def extract(self, label_bytes: bytes) -> PayloadMetadata:
        """Parse `label_bytes` and return the metadata this adapter can extract.

        Raises:
            Pds4ParseError | PvlParseError: the label matched this adapter's
                attempted format but was rejected by that parser (hostile,
                over-limit, or malformed).
            UnrecognizedLabelFormatError: the label matched neither the PDS4
                nor the ISIS3/PVL format.
        """
        ...


class UnrecognizedLabelFormatError(Exception):
    """Neither the PDS4 XML parser nor the ISIS3/PVL parser accepted the input.

    Raised rather than returning a `PayloadMetadata` full of silent `None`s,
    per this module's scope ruling: label bytes that match neither format are
    a clear error, not a quiet "success" with nothing extracted.

    Carries a `FailureCode` chosen from the two underlying parser errors (see
    `_pick_failure_code`) so a caller building a `QuarantineRecord` does not
    have to re-derive one from a message string.
    """

    def __init__(
        self,
        message: str,
        *,
        code: FailureCode,
        pds4_error: Exception,
        pvl_error: Exception,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.pds4_error = pds4_error
        self.pvl_error = pvl_error


# ---------------------------------------------------------------------------
# Shared extraction plumbing
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ExtractedFields:
    """Mutable scratch record built up by the PDS4/ISIS3 extraction paths,
    then copied into an immutable `PayloadMetadata` by `_build_metadata`."""

    product_id: str | None = None
    mission: str | None = None
    instrument_id: str | None = None
    calibration_state: CalibrationState = CalibrationState.UNKNOWN
    acquisition_interval: AcquisitionInterval | None = None
    declared_lines: int | None = None
    declared_samples: int | None = None
    declared_bands: int | None = None
    bands: tuple[BandInfo, ...] = ()
    warnings: list[str] = field(default_factory=list)


def _local_tag(tag: str) -> str:
    """Strip an XML namespace, if any, returning only the local element name."""
    return tag.rsplit("}", 1)[-1]


def _find_child_local(parent: ET.Element, local_name: str) -> ET.Element | None:
    """Return the first direct child of `parent` matching `local_name`, ignoring
    namespace. `None` if there is no such child."""
    for child in parent:
        if _local_tag(child.tag) == local_name:
            return child
    return None


_KNOWN_LENGTH_UNITS_TO_NM: Final[dict[str, float]] = {
    "nm": 1.0,
    "nanometer": 1.0,
    "nanometers": 1.0,
    "um": 1000.0,
    "micron": 1000.0,
    "microns": 1000.0,
    "micrometer": 1000.0,
    "micrometers": 1000.0,
}


def _parse_iso8601_utc(text: str) -> datetime | None:
    """Parse an ISO 8601 timestamp that carries an explicit UTC offset.

    Returns `None` for blank, unparseable, or naive (offset-less) input,
    consistent with `AcquisitionInterval`'s own tz-aware requirement: a naive
    timestamp is never assumed to be UTC.
    """
    candidate = text.strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _build_acquisition_interval(
    start_text: str | None,
    stop_text: str | None,
    warnings: list[str],
    *,
    source: str,
) -> AcquisitionInterval | None:
    if not start_text or not stop_text:
        warnings.append(
            f"{source}: start and/or stop time not present; acquisition_interval is None"
        )
        return None
    start = _parse_iso8601_utc(start_text)
    stop = _parse_iso8601_utc(stop_text)
    if start is None or stop is None:
        warnings.append(
            f"{source}: start/stop time is not a timezone-aware ISO 8601 timestamp "
            f"(start={start_text!r}, stop={stop_text!r}); acquisition_interval is None"
        )
        return None
    try:
        return AcquisitionInterval(start_utc=start, stop_utc=stop)
    except ValueError as exc:
        warnings.append(f"{source}: {exc}; acquisition_interval is None")
        return None


def _pick_failure_code(pds4_error: Pds4ParseError, pvl_error: PvlParseError) -> FailureCode:
    """Choose one `FailureCode` for a label that matched neither format.

    Priority: a hostile-input finding from either parser wins outright (it is
    the most security-relevant signal); a resource-limit finding is next;
    otherwise this is simply not well-formed as either format.
    """
    codes = {pds4_error.code, pvl_error.code}
    if FailureCode.INPUT_HOSTILE_LABEL in codes:
        return FailureCode.INPUT_HOSTILE_LABEL
    if FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED in codes:
        return FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED
    return FailureCode.INPUT_LABEL_UNPARSEABLE


def _try_extract(label_bytes: bytes) -> _ExtractedFields:
    """Try the PDS4 path, then the ISIS3/PVL path.

    Raises `UnrecognizedLabelFormatError` if both parsers reject the input.
    Any `Pds4ParseError`/`PvlParseError` raised by the *matching* parser (the
    one that accepted the input's shape well enough to run, then rejected it
    for its own reasons) propagates unchanged.
    """
    try:
        root = parse_pds4_label(label_bytes)
    except Pds4ParseError as pds4_error:
        try:
            label = parse_pvl_label(label_bytes)
        except PvlParseError as pvl_error:
            raise UnrecognizedLabelFormatError(
                "label_bytes did not parse as either a PDS4 XML label or an "
                f"ISIS3/PVL label; PDS4 parser reported: {pds4_error}; PVL parser "
                f"reported: {pvl_error}",
                code=_pick_failure_code(pds4_error, pvl_error),
                pds4_error=pds4_error,
                pvl_error=pvl_error,
            ) from pvl_error
        return _extract_isis3_fields(label)
    return _extract_pds4_fields(root)


# -- PDS4 path ---------------------------------------------------------------


def _extract_pds4_fields(root: ET.Element) -> _ExtractedFields:
    result = _ExtractedFields()

    identification = _find_child_local(root, "Identification_Area")
    if identification is not None:
        logical_id = _find_child_local(identification, "logical_identifier")
        if logical_id is not None and logical_id.text and logical_id.text.strip():
            result.product_id = logical_id.text.strip()
        else:
            result.warnings.append(
                "PDS4 Identification_Area/logical_identifier not present or empty; "
                "product_id is None"
            )
    else:
        result.warnings.append("PDS4 Identification_Area not present; product_id is None")

    observation_area = _find_child_local(root, "Observation_Area")
    if observation_area is None:
        result.warnings.append(
            "PDS4 Observation_Area not present; acquisition_interval, mission, and "
            "declared raster shape are all None"
        )
    else:
        time_coords = _find_child_local(observation_area, "Time_Coordinates")
        if time_coords is None:
            result.warnings.append(
                "PDS4 Observation_Area/Time_Coordinates not present; acquisition_interval is None"
            )
        else:
            start_el = _find_child_local(time_coords, "start_date_time")
            stop_el = _find_child_local(time_coords, "stop_date_time")
            result.acquisition_interval = _build_acquisition_interval(
                start_el.text if start_el is not None else None,
                stop_el.text if stop_el is not None else None,
                result.warnings,
                source="PDS4 Observation_Area/Time_Coordinates",
            )

        mission_name = _extract_pds4_mission(observation_area, result.warnings)
        result.mission = mission_name

    file_area = _find_child_local(root, "File_Area_Observational")
    array_2d = _find_child_local(file_area, "Array_2D_Image") if file_area is not None else None
    axis_arrays = (
        [child for child in array_2d if _local_tag(child.tag) == "Axis_Array"]
        if array_2d is not None
        else []
    )
    if not axis_arrays:
        result.warnings.append(
            "PDS4 File_Area_Observational/Array_2D_Image/Axis_Array not present; "
            "declared_lines/declared_samples/declared_bands are None"
        )
    else:
        _apply_pds4_axis_arrays(axis_arrays, result)

    # instrument_id and calibration_state have no location named in this
    # task's authorized PDS4 scope (see module docstring); left None/UNKNOWN
    # rather than guessed.
    result.warnings.append(
        "PDS4 path: instrument_id has no location in this build's authorized "
        "extraction scope; instrument_id is None"
    )
    result.calibration_state = CalibrationState.UNKNOWN
    result.warnings.append(
        "PDS4 path: no field within this build's authorized extraction scope "
        "carries a calibration-level indicator; calibration_state is UNKNOWN"
    )

    return result


def _extract_pds4_mission(observation_area: ET.Element, warnings: list[str]) -> str | None:
    investigation_area = _find_child_local(observation_area, "Investigation_Area")
    if investigation_area is not None:
        name_el = _find_child_local(investigation_area, "name")
        if name_el is not None and name_el.text and name_el.text.strip():
            return name_el.text.strip()

    # Mission_Area's *internal* structure is a mission-specific discipline
    # extension, not itself standardized by the core PDS4 IM the way
    # Investigation_Area is; this is a best-effort fallback, not a claim that
    # Mission_Area/name is a documented standard path.
    mission_area = _find_child_local(observation_area, "Mission_Area")
    if mission_area is not None:
        name_el = _find_child_local(mission_area, "name")
        if name_el is not None and name_el.text and name_el.text.strip():
            return name_el.text.strip()

    warnings.append(
        "PDS4 Observation_Area/Investigation_Area/name not present, and no "
        "'name' child was found under Mission_Area either; mission is None"
    )
    return None


def _apply_pds4_axis_arrays(axis_arrays: list[ET.Element], result: _ExtractedFields) -> None:
    for axis in axis_arrays:
        name_el = _find_child_local(axis, "axis_name")
        elements_el = _find_child_local(axis, "elements")
        if name_el is None or name_el.text is None or elements_el is None or not elements_el.text:
            continue
        axis_name = name_el.text.strip()
        try:
            count = int(elements_el.text.strip())
        except ValueError:
            result.warnings.append(
                f"PDS4 Axis_Array elements value {elements_el.text!r} is not an "
                "integer; that axis was skipped"
            )
            continue
        if axis_name == "Line":
            result.declared_lines = count
        elif axis_name == "Sample":
            result.declared_samples = count
        elif axis_name == "Band":
            result.declared_bands = count


# -- ISIS3/PVL path -----------------------------------------------------------


def _extract_isis3_fields(label: dict[str, Any]) -> _ExtractedFields:
    result = _ExtractedFields()

    isis_cube = label.get("IsisCube")
    if not isinstance(isis_cube, dict):
        result.warnings.append(
            "ISIS3 IsisCube object not present at the top level; no fields extracted"
        )
        return result

    _apply_isis3_instrument(isis_cube.get("Instrument"), result)
    _apply_isis3_dimensions(isis_cube.get("Core"), result)
    result.bands = _extract_isis3_bandbin(
        isis_cube.get("BandBin"), result.declared_bands, result.warnings
    )

    # product_id and calibration_state have no field within the three groups
    # this build reads (Instrument, Core/Dimensions, BandBin).
    result.warnings.append(
        "ISIS3 path: no field within IsisCube/Instrument, Core/Dimensions, or "
        "BandBin carries a product identifier; product_id is None"
    )
    result.calibration_state = CalibrationState.UNKNOWN
    result.warnings.append(
        "ISIS3 path: no field within IsisCube/Instrument, Core/Dimensions, or "
        "BandBin carries a calibration-level indicator; calibration_state is "
        "UNKNOWN"
    )

    return result


def _apply_isis3_instrument(instrument: Any, result: _ExtractedFields) -> None:
    if not isinstance(instrument, dict):
        result.warnings.append(
            "ISIS3 IsisCube/Instrument group not present; mission, instrument_id, "
            "and acquisition_interval are all None"
        )
        return

    spacecraft = instrument.get("SpacecraftName")
    if isinstance(spacecraft, str) and spacecraft.strip():
        result.mission = spacecraft.strip()
    else:
        result.warnings.append(
            "ISIS3 IsisCube/Instrument/SpacecraftName not present; mission is None"
        )

    instrument_id = instrument.get("InstrumentId")
    if isinstance(instrument_id, str) and instrument_id.strip():
        result.instrument_id = instrument_id.strip()
    else:
        result.warnings.append(
            "ISIS3 IsisCube/Instrument/InstrumentId not present; instrument_id is None"
        )

    start_text = instrument.get("StartTime")
    stop_text = instrument.get("StopTime")
    result.acquisition_interval = _build_acquisition_interval(
        start_text if isinstance(start_text, str) else None,
        stop_text if isinstance(stop_text, str) else None,
        result.warnings,
        source="ISIS3 IsisCube/Instrument (StartTime/StopTime)",
    )


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, PvlQuantity) and isinstance(value.value, int):
        return value.value
    return None


def _apply_isis3_dimensions(core: Any, result: _ExtractedFields) -> None:
    dimensions = core.get("Dimensions") if isinstance(core, dict) else None
    if not isinstance(dimensions, dict):
        result.warnings.append(
            "ISIS3 IsisCube/Core/Dimensions not present; declared_lines/"
            "declared_samples/declared_bands are None"
        )
        return

    result.declared_samples = _coerce_int(dimensions.get("Samples"))
    result.declared_lines = _coerce_int(dimensions.get("Lines"))
    result.declared_bands = _coerce_int(dimensions.get("Bands"))
    if result.declared_samples is None or result.declared_lines is None:
        result.warnings.append(
            "ISIS3 IsisCube/Core/Dimensions Samples and/or Lines missing or non-integer"
        )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _index_or_none(items: list[Any], index: int) -> Any:
    return items[index] if index < len(items) else None


def _quantity_to_nm(
    value: Any, warnings: list[str], field_name: str, band_index: int
) -> float | None:
    """Convert a BandBin value to nanometers only if it carries a unit this
    module recognises. A bare, unitless number is never assumed to be
    nanometers."""
    if isinstance(value, PvlQuantity):
        factor = _KNOWN_LENGTH_UNITS_TO_NM.get(value.unit.strip().lower())
        if factor is None:
            warnings.append(
                f"ISIS3 BandBin {field_name}[{band_index}] has an unrecognized unit "
                f"{value.unit!r}; not converted to nm, value is None for this band"
            )
            return None
        return float(value.value) * factor
    if isinstance(value, int | float):
        warnings.append(
            f"ISIS3 BandBin {field_name}[{band_index}] has no declared unit; a bare "
            "number is not assumed to be nanometers, value is None for this band"
        )
        return None
    return None


def _to_bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("yes", "true", "1"):
            return True
        if lowered in ("no", "false", "0"):
            return False
    return None


def _spectral_regime(value: Any, warnings: list[str], band_index: int) -> SpectralRegime:
    """Map an explicit IIRS label regime term to the shared band vocabulary.

    The accepted terms are intentionally narrow and label-driven.  A bare
    wavelength, band number, or an arbitrary filter name is not physical
    evidence of an emitted/reflected regime and consequently remains unknown.
    """
    if not isinstance(value, str):
        return SpectralRegime.UNKNOWN
    term = value.strip().lower().replace("_", " ").replace("-", " ")
    if term in {"reflected", "reflectance", "solar reflected"}:
        return SpectralRegime.REFLECTED
    if term in {"emitted", "emission", "thermal", "thermal emitted"}:
        return SpectralRegime.EMITTED
    if term:
        warnings.append(
            f"ISIS3 BandBin SpectralRegime[{band_index}] has unsupported value {value!r}; "
            "spectral_regime is UNKNOWN"
        )
    return SpectralRegime.UNKNOWN


def _extract_isis3_bandbin(
    bandbin: Any, declared_bands: int | None, warnings: list[str]
) -> tuple[BandInfo, ...]:
    if not isinstance(bandbin, dict):
        warnings.append("ISIS3 IsisCube/BandBin group not present; bands is empty")
        return ()

    centers = _as_list(bandbin.get("Center"))
    widths = _as_list(bandbin.get("Width"))
    # "BadBand" is read defensively under this literal key; it is not a
    # confirmed universal ISIS3 BandBin key across every instrument (see
    # module docstring), so its absence is the expected, honest case.
    bad_bands = _as_list(bandbin.get("BadBand"))
    filter_names = _as_list(bandbin.get("FilterName"))
    # The literal key is deliberately explicit.  Other names that might be
    # used by an archive are not guessed from wavelength/filter labels.
    regimes = _as_list(bandbin.get("SpectralRegime"))

    band_count = declared_bands
    if band_count is None:
        candidates = [len(x) for x in (filter_names, centers, widths, bad_bands, regimes) if x]
        band_count = max(candidates, default=0)
        if band_count:
            warnings.append(
                "ISIS3 BandBin: declared_bands unavailable from Core/Dimensions; "
                f"band count inferred from the longest BandBin array ({band_count})"
            )

    if band_count == 0:
        warnings.append(
            "ISIS3 BandBin: band count could not be determined (no Core/Dimensions "
            "Bands value and no non-empty FilterName/Center/Width/BadBand array); "
            "bands is empty"
        )
        return ()

    bands: list[BandInfo] = []
    for i in range(band_count):
        center = _quantity_to_nm(_index_or_none(centers, i), warnings, "Center", i)
        width = _quantity_to_nm(_index_or_none(widths, i), warnings, "Width", i)
        bad = _to_bool_or_none(_index_or_none(bad_bands, i))
        regime = _spectral_regime(_index_or_none(regimes, i), warnings, i)
        bands.append(
            BandInfo(
                band_number=i + 1,
                center_wavelength_nm=center,
                fwhm_nm=width,
                is_bad_band=bad,
                spectral_regime=regime,
            )
        )
    return tuple(bands)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

_SENSOR_MODEL_NOTE: Final = (
    "no validated ISIS/ALE/usgscsm sensor model path is available in this build"
)
_IIRS_GEOMETRY_NOTE: Final = (
    f"{_SENSOR_MODEL_NOTE}; additionally, plan decision D-004 (rigorous IIRS "
    "camera/geometry support) is recorded as unresolved"
)

_INSTRUMENT_MISMATCH_MARKER: Final = "instrument-ID mismatch:"


def _build_metadata(
    label_bytes: bytes,
    *,
    payload_family: PayloadFamily,
    expected_instrument_ids: tuple[str, ...],
    geometry_note: str,
) -> PayloadMetadata:
    fields = _try_extract(label_bytes)
    warnings = list(fields.warnings)

    if fields.instrument_id is not None:
        expected_upper = {candidate.upper() for candidate in expected_instrument_ids}
        if fields.instrument_id.upper() not in expected_upper:
            warnings.append(
                f"{_INSTRUMENT_MISMATCH_MARKER} label declares "
                f"InstrumentId={fields.instrument_id!r}, which does not match the "
                f"{payload_family.value} adapter's expected instrument ID(s) "
                f"{expected_instrument_ids!r}"
            )

    return PayloadMetadata(
        payload_family=payload_family,
        product_id=fields.product_id,
        mission=fields.mission,
        instrument_id=fields.instrument_id,
        calibration_state=fields.calibration_state,
        acquisition_interval=fields.acquisition_interval,
        declared_lines=fields.declared_lines,
        declared_samples=fields.declared_samples,
        declared_bands=fields.declared_bands,
        bands=fields.bands,
        geometry_validated=False,
        geometry_validation_note=geometry_note,
        warnings=tuple(warnings),
    )


class OhrcAdapter:
    """Metadata adapter for the OHRC (Orbiter High Resolution Camera) payload."""

    payload_family: Final = PayloadFamily.OHRC
    _expected_instrument_ids: Final = ("OHRC",)

    def extract(self, label_bytes: bytes) -> PayloadMetadata:
        return _build_metadata(
            label_bytes,
            payload_family=self.payload_family,
            expected_instrument_ids=self._expected_instrument_ids,
            geometry_note=_SENSOR_MODEL_NOTE,
        )


class Tmc2Adapter:
    """Metadata adapter for the TMC-2 (Terrain Mapping Camera 2) payload."""

    payload_family: Final = PayloadFamily.TMC2
    _expected_instrument_ids: Final = ("TMC2", "TMC-2", "TMC 2")

    def extract(self, label_bytes: bytes) -> PayloadMetadata:
        return _build_metadata(
            label_bytes,
            payload_family=self.payload_family,
            expected_instrument_ids=self._expected_instrument_ids,
            geometry_note=_SENSOR_MODEL_NOTE,
        )


class IirsAdapter:
    """Metadata adapter for the IIRS (Imaging Infrared Spectrometer) payload.

    The only adapter that populates `BandInfo` beyond `band_number`; see the
    module docstring for exactly which BandBin sub-fields are read and which
    are deliberately left unimplemented.
    """

    payload_family: Final = PayloadFamily.IIRS
    _expected_instrument_ids: Final = ("IIRS",)

    def extract(self, label_bytes: bytes) -> PayloadMetadata:
        return _build_metadata(
            label_bytes,
            payload_family=self.payload_family,
            expected_instrument_ids=self._expected_instrument_ids,
            geometry_note=_IIRS_GEOMETRY_NOTE,
        )


def _adapter_payload_family(adapter: PayloadAdapter) -> PayloadFamily:
    """Best-effort `payload_family` lookup for building a `QuarantineRecord`.

    Not part of the `PayloadAdapter` Protocol (deliberately minimal — see the
    module docstring), but every adapter defined in this module carries a
    `payload_family` attribute; this reads it defensively rather than
    assuming every future implementer of the Protocol will.
    """
    candidate = getattr(adapter, "payload_family", None)
    if isinstance(candidate, PayloadFamily):
        return candidate
    raise TypeError(
        f"{type(adapter).__name__} has no payload_family: PayloadFamily attribute; "
        "validate_product cannot build a QuarantineRecord without one"
    )


# ---------------------------------------------------------------------------
# Quarantine and re-validation
# ---------------------------------------------------------------------------

# Whether a `QuarantineRecord` with a given `reason` may plausibly be fixed by
# resupplying corrected label bytes under the same record, versus the problem
# being structural. INPUT_HOSTILE_LABEL and INPUT_RESOURCE_LIMIT_EXCEEDED are
# both treated with suspicion (pds4.py's own remediation text for
# INPUT_HOSTILE_LABEL says "do not relax the parser to accept it"; for
# INPUT_RESOURCE_LIMIT_EXCEEDED, "the input may be a decompression bomb" — a
# limit is raised only deliberately, never implicitly via a revalidation
# retry). INPUT_LABEL_UNPARSEABLE and INPUT_UNSUPPORTED_PAYLOAD (used here
# for a blocking instrument-ID mismatch) are ordinary data-quality problems a
# corrected label can genuinely fix.
_REVALIDATABLE_REASONS: Final[dict[FailureCode, bool]] = {
    FailureCode.INPUT_LABEL_UNPARSEABLE: True,
    FailureCode.INPUT_UNSUPPORTED_PAYLOAD: True,
    FailureCode.INPUT_HOSTILE_LABEL: False,
    FailureCode.INPUT_RESOURCE_LIMIT_EXCEEDED: False,
}


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """A product that `validate_product` declined to accept as `PayloadMetadata`.

    `reason` reuses `FailureCode` (the enum is append-only project policy;
    see `_pick_failure_code` and `validate_product` for which codes are ever
    produced here — no new member is defined by this module).
    """

    product_id: str | None
    payload_family: PayloadFamily
    reason: FailureCode
    message: str
    quarantined_utc: datetime
    revalidatable: bool

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("QuarantineRecord.message must be a non-empty explanation")


def validate_product(
    adapter: PayloadAdapter,
    label_bytes: bytes,
    *,
    clock: Callable[[], datetime] | None = None,
) -> PayloadMetadata | QuarantineRecord:
    """Run `adapter` against `label_bytes`, quarantining rather than raising.

    Returns the extracted `PayloadMetadata` on success. Returns a
    `QuarantineRecord` instead of raising when the underlying parser rejects
    the label (`Pds4ParseError`/`PvlParseError`), when the label matches
    neither format (`UnrecognizedLabelFormatError`), or when the adapter
    recorded an instrument-ID-mismatch warning — a mismatch is a
    data-quality problem this layer treats as blocking, even though the
    adapter itself does not raise for it (see `OhrcAdapter`/`Tmc2Adapter`/
    `IirsAdapter`).

    `clock` defaults to `lambda: datetime.now(tz=UTC)` but is always called
    through this parameter (never `datetime.now()` directly), so tests can
    inject a fixed clock and assert `quarantined_utc` exactly.
    """
    resolved_clock = clock or (lambda: datetime.now(tz=UTC))
    payload_family = _adapter_payload_family(adapter)

    try:
        metadata = adapter.extract(label_bytes)
    except (Pds4ParseError, PvlParseError) as exc:
        return QuarantineRecord(
            product_id=None,
            payload_family=payload_family,
            reason=exc.code,
            message=exc.message,
            quarantined_utc=resolved_clock(),
            revalidatable=_REVALIDATABLE_REASONS.get(exc.code, False),
        )
    except UnrecognizedLabelFormatError as exc:
        return QuarantineRecord(
            product_id=None,
            payload_family=payload_family,
            reason=exc.code,
            message=str(exc),
            quarantined_utc=resolved_clock(),
            revalidatable=_REVALIDATABLE_REASONS.get(exc.code, False),
        )

    mismatch_warnings = [w for w in metadata.warnings if w.startswith(_INSTRUMENT_MISMATCH_MARKER)]
    if mismatch_warnings:
        reason = FailureCode.INPUT_UNSUPPORTED_PAYLOAD
        return QuarantineRecord(
            product_id=metadata.product_id,
            payload_family=payload_family,
            reason=reason,
            message="; ".join(mismatch_warnings),
            quarantined_utc=resolved_clock(),
            revalidatable=_REVALIDATABLE_REASONS.get(reason, False),
        )

    return metadata


def revalidate(
    record: QuarantineRecord,
    new_label_bytes: bytes,
    adapter: PayloadAdapter,
    *,
    clock: Callable[[], datetime] | None = None,
) -> PayloadMetadata | QuarantineRecord:
    """Re-run `validate_product` with corrected label bytes.

    If `record.revalidatable` is `False`, this returns `record` unchanged
    rather than attempting a revalidation the record itself says isn't
    possible, and rather than raising: the caller already has a valid,
    inspectable `QuarantineRecord` in hand, and handing back the same object
    lets the caller keep treating "was this revalidated" as a simple
    identity/equality check rather than having to catch an exception for an
    expected, documented case.
    """
    if not record.revalidatable:
        return record
    return validate_product(adapter, new_label_bytes, clock=clock)
