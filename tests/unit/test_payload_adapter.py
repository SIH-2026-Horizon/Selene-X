"""Tests for the PayloadAdapter protocol, OHRC/TMC-2/IIRS metadata adapters,
and quarantine/re-validation (WP-02 tasks 7, 9, 11; task 8 metadata-only).

Every label fixture below is synthetic — literal bytes constructed in this
file, never read from or claimed to match a real Chandrayaan-2 archive
product. The ISIS3-shaped fixtures quote `StartTime`/`StopTime` as PVL
strings (e.g. `StartTime = "2021-06-01T12:00:00Z"`) because
`selene_core.ingest.pvl.parse_pvl_label` is a limited-subset parser that
cannot tokenize a bare, unquoted ISO-8601 date-time literal — see
`selene_core.ingest.payload_adapter`'s module docstring for the full
explanation. That quoting is a fixture-construction necessity to exercise
this already-reviewed, unmodified parser, not a claim about how real ISIS
labels are conventionally written.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from selene_core.ingest.payload_adapter import (
    BandInfo,
    CalibrationState,
    IirsAdapter,
    OhrcAdapter,
    PayloadAdapter,
    PayloadFamily,
    PayloadMetadata,
    QuarantineRecord,
    SpectralRegime,
    Tmc2Adapter,
    UnrecognizedLabelFormatError,
    revalidate,
    validate_product,
)
from selene_core.ingest.pds4 import Pds4ParseError
from selene_core.ingest.pvl import PvlParseError
from selene_core.pipeline.failures import FailureCode

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------

# A synthetic PDS4-shaped label. Not an instance of the real PDS4
# Product_Observational schema (no schema is available in this
# environment) — built only to exercise the standard Identification_Area /
# Observation_Area/Time_Coordinates / Investigation_Area /
# File_Area_Observational/Array_2D_Image locations this module reads.
PDS4_OHRC_LABEL = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<Product_Observational xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    b"<Identification_Area>"
    b"<logical_identifier>urn:selene-xr:synthetic:ohrc:0001</logical_identifier>"
    b"</Identification_Area>"
    b"<Observation_Area>"
    b"<Time_Coordinates>"
    b"<start_date_time>2021-06-01T12:00:00.000Z</start_date_time>"
    b"<stop_date_time>2021-06-01T12:00:05.000Z</stop_date_time>"
    b"</Time_Coordinates>"
    b"<Investigation_Area>"
    b"<name>Chandrayaan 2</name>"
    b"</Investigation_Area>"
    b"</Observation_Area>"
    b"<File_Area_Observational>"
    b"<Array_2D_Image>"
    b"<Axis_Array><axis_name>Line</axis_name><elements>4000</elements></Axis_Array>"
    b"<Axis_Array><axis_name>Sample</axis_name><elements>2000</elements></Axis_Array>"
    b"</Array_2D_Image>"
    b"</File_Area_Observational>"
    b"</Product_Observational>"
)

# A synthetic ISIS3-PVL-shaped label declaring InstrumentId = TMC2, with a
# populated BandBin group (wavelength/FWHM/bad-band data present).
ISIS_TMC2_LABEL_WITH_BANDBIN = b"""
Object = IsisCube
  Group = Instrument
    SpacecraftName = "Chandrayaan-2 Orbiter"
    InstrumentId = TMC2
    StartTime = "2021-06-01T12:00:00Z"
    StopTime = "2021-06-01T12:00:05Z"
  End_Group

  Object = Core
    Group = Dimensions
      Samples = 2000
      Lines = 4000
      Bands = 3
    End_Group
  End_Object

  Group = BandBin
    FilterName = ("Band1", "Band2", "Band3")
    Center = (620.5 <nm>, 700.2 <nm>, 810.9 <nm>)
    Width = (10.5 <nm>, 11.0 <nm>, 12.5 <nm>)
    BadBand = (0, 1, 0)
  End_Group
End_Object
End
"""

# Same shape, declaring InstrumentId = IIRS, with no BandBin group at all.
ISIS_IIRS_LABEL_NO_BANDBIN = b"""
Object = IsisCube
  Group = Instrument
    SpacecraftName = "Chandrayaan-2 Orbiter"
    InstrumentId = IIRS
    StartTime = "2021-07-15T03:20:00Z"
    StopTime = "2021-07-15T03:20:02Z"
  End_Group

  Object = Core
    Group = Dimensions
      Samples = 512
      Lines = 512
      Bands = 2
    End_Group
  End_Object
End_Object
End
"""

# A hostile PDS4 label (classic XXE shape, reused from the shape used by
# tests/security/test_pds4_parser_hostile.py) -- neither a valid PDS4 label
# (DOCTYPE is rejected) nor valid PVL (it is XML).
HOSTILE_LABEL = (
    b'<?xml version="1.0"?>\n'
    b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
    b"<foo><val>&xxe;</val></foo>"
)

# Genuinely malformed, non-hostile XML: mismatched tag, no DOCTYPE/entity
# markers. Rejected by the PDS4 parser as INPUT_LABEL_UNPARSEABLE, and also
# rejected by the PVL parser (it is not valid PVL either).
MALFORMED_NON_HOSTILE_LABEL = b"<a><b></a>"

# Bytes that are neither PDS4-XML-shaped nor PVL-shaped.
NEITHER_FORMAT_LABEL = b"\x00\x01\x02 not xml, not pvl, just junk bytes"


def _fixed_clock(moment: datetime) -> Callable[[], datetime]:
    def _clock() -> datetime:
        return moment

    return _clock


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_all_three_adapters_satisfy_the_protocol(self) -> None:
        assert isinstance(OhrcAdapter(), PayloadAdapter)
        assert isinstance(Tmc2Adapter(), PayloadAdapter)
        assert isinstance(IirsAdapter(), PayloadAdapter)

    def test_payload_family_enum_matches_benchmark_manifest_schema_spelling(self) -> None:
        """TMC2's *value* is 'TMC-2' (hyphenated), matching the schema's string
        exactly, even though the Python member name cannot contain a hyphen."""
        assert PayloadFamily.TMC2.value == "TMC-2"
        assert PayloadFamily.OHRC.value == "OHRC"
        assert PayloadFamily.IIRS.value == "IIRS"


# ---------------------------------------------------------------------------
# PDS4-shaped extraction
# ---------------------------------------------------------------------------


class TestPds4Extraction:
    def test_ohrc_adapter_extracts_exact_values_from_pds4_label(self) -> None:
        metadata = OhrcAdapter().extract(PDS4_OHRC_LABEL)

        assert metadata.payload_family is PayloadFamily.OHRC
        assert metadata.product_id == "urn:selene-xr:synthetic:ohrc:0001"
        assert metadata.mission == "Chandrayaan 2"
        assert metadata.declared_lines == 4000
        assert metadata.declared_samples == 2000
        assert metadata.declared_bands is None  # no Band Axis_Array in this fixture
        assert metadata.acquisition_interval is not None
        assert metadata.acquisition_interval.start_utc == datetime(2021, 6, 1, 12, 0, 0, tzinfo=UTC)
        assert metadata.acquisition_interval.stop_utc == datetime(2021, 6, 1, 12, 0, 5, tzinfo=UTC)

    def test_pds4_path_leaves_instrument_id_and_calibration_state_unextracted(self) -> None:
        """Neither has a location in this build's authorized PDS4 scope; both are
        None/UNKNOWN with a stated reason, never guessed."""
        metadata = OhrcAdapter().extract(PDS4_OHRC_LABEL)

        assert metadata.instrument_id is None
        assert metadata.calibration_state is CalibrationState.UNKNOWN
        assert any("instrument_id" in w for w in metadata.warnings)
        assert any("calibration-level" in w for w in metadata.warnings)

    def test_pds4_label_missing_time_coordinates_yields_none_with_warning(self) -> None:
        label = (
            b'<?xml version="1.0"?>'
            b"<Product_Observational>"
            b"<Identification_Area>"
            b"<logical_identifier>urn:selene-xr:synthetic:0002</logical_identifier>"
            b"</Identification_Area>"
            b"<Observation_Area></Observation_Area>"
            b"</Product_Observational>"
        )

        metadata = Tmc2Adapter().extract(label)

        assert metadata.acquisition_interval is None
        assert any("Time_Coordinates" in w for w in metadata.warnings)


# ---------------------------------------------------------------------------
# ISIS3/PVL-shaped extraction
# ---------------------------------------------------------------------------


class TestIsis3Extraction:
    def test_tmc2_adapter_extracts_exact_values_from_isis3_label(self) -> None:
        metadata = Tmc2Adapter().extract(ISIS_TMC2_LABEL_WITH_BANDBIN)

        assert metadata.payload_family is PayloadFamily.TMC2
        assert metadata.mission == "Chandrayaan-2 Orbiter"
        assert metadata.instrument_id == "TMC2"
        assert metadata.declared_samples == 2000
        assert metadata.declared_lines == 4000
        assert metadata.declared_bands == 3
        assert metadata.acquisition_interval is not None
        assert metadata.acquisition_interval.start_utc == datetime(2021, 6, 1, 12, 0, 0, tzinfo=UTC)
        assert metadata.acquisition_interval.stop_utc == datetime(2021, 6, 1, 12, 0, 5, tzinfo=UTC)

    def test_isis3_path_leaves_product_id_and_calibration_state_unextracted(self) -> None:
        metadata = Tmc2Adapter().extract(ISIS_TMC2_LABEL_WITH_BANDBIN)

        assert metadata.product_id is None
        assert metadata.calibration_state is CalibrationState.UNKNOWN
        assert any("product identifier" in w for w in metadata.warnings)
        assert any("calibration-level" in w for w in metadata.warnings)

    def test_naive_isis3_start_time_yields_none_acquisition_interval_with_warning(self) -> None:
        """A naive (offset-less) StartTime/StopTime is never assumed to be UTC."""
        label = b"""
Object = IsisCube
  Group = Instrument
    InstrumentId = OHRC
    StartTime = "2021-06-01T12:00:00"
    StopTime = "2021-06-01T12:00:05"
  End_Group
End_Object
End
"""
        metadata = OhrcAdapter().extract(label)

        assert metadata.acquisition_interval is None
        assert any("timezone-aware" in w for w in metadata.warnings)


# ---------------------------------------------------------------------------
# geometry_validated is unconditionally False
# ---------------------------------------------------------------------------


class TestGeometryValidatedIsAlwaysFalse:
    @pytest.mark.parametrize(
        ("adapter_cls", "label"),
        [
            (OhrcAdapter, PDS4_OHRC_LABEL),
            (Tmc2Adapter, ISIS_TMC2_LABEL_WITH_BANDBIN),
            (IirsAdapter, ISIS_IIRS_LABEL_NO_BANDBIN),
        ],
    )
    def test_geometry_validated_false_and_note_nonempty(
        self, adapter_cls: type[PayloadAdapter], label: bytes
    ) -> None:
        metadata = adapter_cls().extract(label)

        assert metadata.geometry_validated is False
        assert metadata.geometry_validation_note.strip() != ""

    def test_iirs_geometry_note_cites_d004(self) -> None:
        metadata = IirsAdapter().extract(ISIS_IIRS_LABEL_NO_BANDBIN)

        assert "D-004" in metadata.geometry_validation_note

    def test_payload_metadata_rejects_construction_with_geometry_validated_true(self) -> None:
        """Enforced independently of adapter code: no caller can construct a
        PayloadMetadata claiming a validated geometry, even directly."""
        with pytest.raises(ValueError, match="geometry_validated must be False"):
            PayloadMetadata(
                payload_family=PayloadFamily.OHRC,
                product_id=None,
                mission=None,
                instrument_id=None,
                calibration_state=CalibrationState.UNKNOWN,
                acquisition_interval=None,
                declared_lines=None,
                declared_samples=None,
                declared_bands=None,
                bands=(),
                geometry_validated=True,
                geometry_validation_note="claiming success",
                warnings=(),
            )

    def test_payload_metadata_rejects_empty_geometry_validation_note(self) -> None:
        with pytest.raises(ValueError, match="non-empty stated reason"):
            PayloadMetadata(
                payload_family=PayloadFamily.OHRC,
                product_id=None,
                mission=None,
                instrument_id=None,
                calibration_state=CalibrationState.UNKNOWN,
                acquisition_interval=None,
                declared_lines=None,
                declared_samples=None,
                declared_bands=None,
                bands=(),
                geometry_validated=False,
                geometry_validation_note="   ",
                warnings=(),
            )


# ---------------------------------------------------------------------------
# IIRS band info
# ---------------------------------------------------------------------------


class TestIirsBandInfo:
    def test_iirs_label_driven_spectral_regime_is_explicit_per_band(self) -> None:
        label = b"""
Object = IsisCube
  Object = Core
    Group = Dimensions
      Samples = 10
      Lines = 10
      Bands = 3
    End_Group
  End_Object
  Group = BandBin
    SpectralRegime = ("REFLECTED", "THERMAL", "unrecognised-term")
  End_Group
End_Object
End
"""
        metadata = IirsAdapter().extract(label)

        assert [band.spectral_regime for band in metadata.bands] == [
            SpectralRegime.REFLECTED,
            SpectralRegime.EMITTED,
            SpectralRegime.UNKNOWN,
        ]
        assert any("unsupported value" in warning for warning in metadata.warnings)

    def test_iirs_band_regime_is_unknown_without_label_evidence(self) -> None:
        metadata = IirsAdapter().extract(ISIS_IIRS_LABEL_NO_BANDBIN)
        assert metadata.bands == ()

    def test_bandbin_data_present_populates_exact_band_values(self) -> None:
        metadata = IirsAdapter().extract(ISIS_TMC2_LABEL_WITH_BANDBIN)

        assert metadata.bands == (
            BandInfo(band_number=1, center_wavelength_nm=620.5, fwhm_nm=10.5, is_bad_band=False),
            BandInfo(band_number=2, center_wavelength_nm=700.2, fwhm_nm=11.0, is_bad_band=True),
            BandInfo(band_number=3, center_wavelength_nm=810.9, fwhm_nm=12.5, is_bad_band=False),
        )

    def test_bandbin_absent_yields_empty_bands_not_a_crash_or_fabricated_default(self) -> None:
        metadata = IirsAdapter().extract(ISIS_IIRS_LABEL_NO_BANDBIN)

        assert metadata.bands == ()
        assert any("BandBin group not present" in w for w in metadata.warnings)

    def test_bandbin_value_without_a_unit_is_none_not_assumed_nanometers(self) -> None:
        label = b"""
Object = IsisCube
  Object = Core
    Group = Dimensions
      Samples = 10
      Lines = 10
      Bands = 1
    End_Group
  End_Object
  Group = BandBin
    Center = (620.5)
  End_Group
End_Object
End
"""
        metadata = IirsAdapter().extract(label)

        assert len(metadata.bands) == 1
        assert metadata.bands[0].center_wavelength_nm is None
        assert any("no declared unit" in w for w in metadata.warnings)


# ---------------------------------------------------------------------------
# Instrument-ID mismatch
# ---------------------------------------------------------------------------


class TestInstrumentIdMismatch:
    def test_ohrc_adapter_warns_on_tmc2_labeled_input(self) -> None:
        """A label declaring InstrumentId = TMC2 fed to OhrcAdapter records a
        warning naming the actual mismatch."""
        metadata = OhrcAdapter().extract(ISIS_TMC2_LABEL_WITH_BANDBIN)

        mismatches = [w for w in metadata.warnings if w.startswith("instrument-ID mismatch:")]
        assert len(mismatches) == 1
        assert "TMC2" in mismatches[0]
        assert "OHRC" in mismatches[0]

    def test_matching_instrument_id_produces_no_mismatch_warning(self) -> None:
        metadata = Tmc2Adapter().extract(ISIS_TMC2_LABEL_WITH_BANDBIN)

        assert not any(w.startswith("instrument-ID mismatch:") for w in metadata.warnings)

    def test_mismatch_does_not_raise(self) -> None:
        # A mismatched-but-otherwise-parseable label is a data-quality
        # observation, not a parse failure -- extract() must not raise.
        metadata = OhrcAdapter().extract(ISIS_TMC2_LABEL_WITH_BANDBIN)
        assert isinstance(metadata, PayloadMetadata)


# ---------------------------------------------------------------------------
# Neither format
# ---------------------------------------------------------------------------


class TestNeitherFormat:
    def test_bytes_matching_neither_format_raise_a_clear_error(self) -> None:
        with pytest.raises(UnrecognizedLabelFormatError):
            OhrcAdapter().extract(NEITHER_FORMAT_LABEL)

    def test_unrecognized_label_format_error_carries_both_underlying_errors(self) -> None:
        with pytest.raises(UnrecognizedLabelFormatError) as excinfo:
            IirsAdapter().extract(NEITHER_FORMAT_LABEL)

        assert isinstance(excinfo.value.pds4_error, Pds4ParseError)
        assert isinstance(excinfo.value.pvl_error, PvlParseError)


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


class TestValidateProduct:
    def test_valid_label_returns_payload_metadata(self) -> None:
        result = validate_product(OhrcAdapter(), PDS4_OHRC_LABEL)
        assert isinstance(result, PayloadMetadata)

    def test_hostile_label_returns_quarantine_record_not_an_exception(self) -> None:
        result = validate_product(OhrcAdapter(), HOSTILE_LABEL)

        assert isinstance(result, QuarantineRecord)
        assert result.reason is FailureCode.INPUT_HOSTILE_LABEL
        assert result.message.strip() != ""
        assert result.revalidatable is False
        assert result.payload_family is PayloadFamily.OHRC

    def test_malformed_non_hostile_label_returns_quarantine_record(self) -> None:
        result = validate_product(Tmc2Adapter(), MALFORMED_NON_HOSTILE_LABEL)

        assert isinstance(result, QuarantineRecord)
        assert result.reason is FailureCode.INPUT_LABEL_UNPARSEABLE
        assert result.message.strip() != ""
        assert result.revalidatable is True

    def test_instrument_mismatch_is_quarantined_as_unsupported_payload(self) -> None:
        result = validate_product(OhrcAdapter(), ISIS_TMC2_LABEL_WITH_BANDBIN)

        assert isinstance(result, QuarantineRecord)
        assert result.reason is FailureCode.INPUT_UNSUPPORTED_PAYLOAD
        assert "TMC2" in result.message
        assert result.revalidatable is True

    def test_injected_clock_determines_quarantined_utc_exactly(self) -> None:
        fixed_moment = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

        result = validate_product(OhrcAdapter(), HOSTILE_LABEL, clock=_fixed_clock(fixed_moment))

        assert isinstance(result, QuarantineRecord)
        assert result.quarantined_utc == fixed_moment

    def test_default_clock_is_not_used_directly_as_datetime_now(self) -> None:
        """A second injected fixed clock produces a different quarantined_utc than
        a fixed 2020 moment, and both are honored exactly -- proving clock is
        genuinely threaded through rather than datetime.now() being called."""
        moment_a = datetime(2020, 1, 1, tzinfo=UTC)
        moment_b = datetime(2030, 6, 15, 12, 0, 0, tzinfo=UTC)

        result_a = validate_product(OhrcAdapter(), HOSTILE_LABEL, clock=_fixed_clock(moment_a))
        result_b = validate_product(OhrcAdapter(), HOSTILE_LABEL, clock=_fixed_clock(moment_b))

        assert isinstance(result_a, QuarantineRecord)
        assert isinstance(result_b, QuarantineRecord)
        assert result_a.quarantined_utc == moment_a
        assert result_b.quarantined_utc == moment_b


class TestRevalidate:
    def test_revalidatable_record_with_corrected_bytes_succeeds(self) -> None:
        record = validate_product(Tmc2Adapter(), MALFORMED_NON_HOSTILE_LABEL)
        assert isinstance(record, QuarantineRecord)
        assert record.revalidatable is True

        result = revalidate(record, PDS4_OHRC_LABEL, Tmc2Adapter())

        assert isinstance(result, PayloadMetadata)
        assert result.product_id == "urn:selene-xr:synthetic:ohrc:0001"

    def test_non_revalidatable_record_is_returned_unchanged(self) -> None:
        record = validate_product(OhrcAdapter(), HOSTILE_LABEL)
        assert isinstance(record, QuarantineRecord)
        assert record.revalidatable is False

        result = revalidate(record, PDS4_OHRC_LABEL, OhrcAdapter())

        assert result is record

    def test_revalidate_with_injected_clock_on_success_path(self) -> None:
        record = validate_product(Tmc2Adapter(), MALFORMED_NON_HOSTILE_LABEL)
        assert isinstance(record, QuarantineRecord)

        result = revalidate(
            record,
            PDS4_OHRC_LABEL,
            Tmc2Adapter(),
            clock=_fixed_clock(datetime(2026, 1, 1, tzinfo=UTC)),
        )

        assert isinstance(result, PayloadMetadata)
