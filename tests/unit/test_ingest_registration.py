"""Focused local-fixture coverage for WP-02 registration and derivation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from selene_core.ingest.payload_adapter import OhrcAdapter
from selene_core.ingest.registration import (
    ProductRegistrationError,
    derive_normalized_preview,
    register_local_product,
)

pytestmark = pytest.mark.unit


LABEL = (
    b"<Product_Observational><Identification_Area>"
    b"<logical_identifier>test-product</logical_identifier>"
    b"</Identification_Area><Observation_Area><Time_Coordinates>"
    b"<start_date_time>2021-01-01T00:00:00Z</start_date_time>"
    b"<stop_date_time>2021-01-01T00:00:01Z</stop_date_time>"
    b"</Time_Coordinates></Observation_Area><File_Area_Observational>"
    b"<Array_2D_Image><Axis_Array><axis_name>Line</axis_name>"
    b"<elements>2</elements></Axis_Array><Axis_Array>"
    b"<axis_name>Sample</axis_name><elements>3</elements></Axis_Array>"
    b"</Array_2D_Image></File_Area_Observational></Product_Observational>"
)


class _FakeRaster:
    def __init__(
        self,
        *,
        width: int = 3,
        height: int = 2,
        count: int = 1,
        dtypes: tuple[str, ...] = ("uint16",),
        nodata: float | None = 0.0,
    ) -> None:
        self.width = width
        self.height = height
        self.count = count
        self.dtypes = dtypes
        self.nodata = nodata

    def read(self) -> np.ndarray:
        return np.array([[[0, 10, 20], [30, 40, 50]]], dtype=np.uint16)

    def close(self) -> None:
        pass


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _manifest(tmp_path: Path, *, data_digest: str | None = None, label: bytes = LABEL) -> Path:
    data = b"not a real fixture raster; opening is injected"
    (tmp_path / "source.tif").write_bytes(data)
    (tmp_path / "label.xml").write_bytes(label)
    payload = {
        "schema_version": "1",
        "product_id": "test-product",
        "payload_family": "OHRC",
        "mission": None,
        "instrument_id": None,
        "files": [
            {
                "relative_path": "source.tif",
                "sha256": data_digest or _digest(data),
                "size_bytes": len(data),
                "media_type": "image/tiff",
                "role": "data",
            },
            {
                "relative_path": "label.xml",
                "sha256": _digest(label),
                "size_bytes": len(label),
                "media_type": "application/xml",
                "role": "label",
            },
        ],
        "acquisition": {"start_utc": "2021-01-01T00:00:00Z", "end_utc": "2021-01-01T00:00:01Z"},
        "calibration_state": "unknown",
        "raster": {"shape": [2, 3], "dtype": "uint16", "nodata": 0, "bands": [{"band_number": 1}]},
        "geometry_adapter": {
            "name": "metadata-only",
            "version": "1",
            "status": "unvalidated",
            "note": "No external sensor model installed.",
        },
        "frame": {"name": "unknown", "status": "unknown", "note": "Not validated."},
        "projection": {"name": "unknown", "status": "unknown", "note": "Not validated."},
        "datum_realisation": {"name": "unknown", "status": "unknown", "note": "Not validated."},
        "geometry_validation": {"validated": False, "note": "No external sensor model installed."},
        "warnings": [],
    }
    path = tmp_path / "product.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registration_verifies_manifest_source_bytes_and_label_raster_agreement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    registered = register_local_product(_manifest(tmp_path), OhrcAdapter())
    assert registered.raster_shape == (1, 2, 3)
    assert (
        tmp_path / "source.tif"
    ).read_bytes() == b"not a real fixture raster; opening is injected"


def test_registration_quarantines_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    with pytest.raises(ProductRegistrationError, match="checksum") as excinfo:
        register_local_product(_manifest(tmp_path, data_digest="0" * 64), OhrcAdapter())
    assert excinfo.value.reason == "input.checksum_mismatch"


def test_registration_rejects_declared_payload_that_does_not_match_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    manifest = _manifest(tmp_path)
    contents = json.loads(manifest.read_text(encoding="utf-8"))
    contents["payload_family"] = "IIRS"
    manifest.write_text(json.dumps(contents), encoding="utf-8")
    with pytest.raises(ProductRegistrationError) as excinfo:
        register_local_product(manifest, OhrcAdapter())
    assert excinfo.value.reason == "input.unsupported_payload"


@pytest.mark.parametrize(
    ("raster", "manifest_edit", "expected_reason"),
    [
        (
            _FakeRaster(height=3),
            lambda document: document["raster"].update({"shape": [3, 3]}),
            "input.label_raster_disagreement",
        ),
        (_FakeRaster(dtypes=("float32",)), None, "input.label_raster_disagreement"),
        (_FakeRaster(nodata=-9999.0), None, "input.label_raster_disagreement"),
        (
            _FakeRaster(count=2, dtypes=("uint16", "uint16")),
            None,
            "input.label_raster_disagreement",
        ),
        (
            _FakeRaster(),
            lambda document: document["acquisition"].update({"end_utc": "2021-01-01T00:00:02Z"}),
            "input.label_raster_disagreement",
        ),
        (
            _FakeRaster(),
            lambda document: document.update({"calibration_state": "calibrated"}),
            "input.not_calibrated",
        ),
    ],
)
def test_registration_quarantines_all_declared_mismatch_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raster: _FakeRaster,
    manifest_edit: object,
    expected_reason: str,
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: raster)
    manifest = _manifest(tmp_path)
    if manifest_edit is not None:
        assert callable(manifest_edit)
        document = json.loads(manifest.read_text(encoding="utf-8"))
        manifest_edit(document)
        manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProductRegistrationError) as excinfo:
        register_local_product(manifest, OhrcAdapter())
    assert excinfo.value.reason == expected_reason


def test_unknown_calibration_is_the_only_unverified_state_that_registers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    registered = register_local_product(_manifest(tmp_path), OhrcAdapter())
    assert registered.metadata.calibration_state.value == "unknown"


@pytest.mark.parametrize(
    "label",
    [
        (
            b"<Product_Observational><Identification_Area>"
            b"<logical_identifier>test-product</logical_identifier>"
            b"</Identification_Area><Observation_Area/>"
            b"<File_Area_Observational><Array_2D_Image>"
            b"<Axis_Array><axis_name>Line</axis_name><elements>2</elements></Axis_Array>"
            b"<Axis_Array><axis_name>Sample</axis_name><elements>3</elements></Axis_Array>"
            b"</Array_2D_Image></File_Area_Observational></Product_Observational>"
        ),
        b"""
Object = IsisCube
  Group = Instrument
    InstrumentId = OHRC
    StartTime = "2021-01-01T00:00:00"
    StopTime = "2021-01-01T00:00:01"
  End_Group
  Object = Core
    Group = Dimensions
      Samples = 3
      Lines = 2
      Bands = 1
    End_Group
  End_Object
End_Object
End
""",
    ],
)
def test_registration_rejects_missing_or_naive_label_acquisition_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: bytes
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    with pytest.raises(ProductRegistrationError, match="acquisition interval") as excinfo:
        register_local_product(_manifest(tmp_path, label=label), OhrcAdapter())
    assert excinfo.value.reason == "input.label_raster_disagreement"


def test_preview_is_derived_with_provenance_and_never_rewrites_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    registered = register_local_product(_manifest(tmp_path), OhrcAdapter())
    before = registered.data_path.read_bytes()
    derived = derive_normalized_preview(registered, tmp_path / "derived")
    assert derived.array_path.is_file()
    assert (
        json.loads(derived.provenance_path.read_text(encoding="utf-8"))["source_data_sha256"]
        == registered.source_digests["data"]
    )
    assert registered.data_path.read_bytes() == before


def test_preview_path_does_not_use_provider_controlled_product_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    registered = register_local_product(_manifest(tmp_path), OhrcAdapter())
    hostile_identity = replace(registered, product_id="../../outside")
    output_dir = tmp_path / "derived"
    derived = derive_normalized_preview(hostile_identity, output_dir)
    assert derived.array_path.is_relative_to(output_dir.resolve())
    assert "outside" not in derived.array_path.name


def test_preview_is_parameter_keyed_and_reuses_only_matching_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    registered = register_local_product(_manifest(tmp_path), OhrcAdapter())
    output_dir = tmp_path / "derived"
    first = derive_normalized_preview(registered, output_dir, low_percentile=2, high_percentile=98)
    repeat = derive_normalized_preview(registered, output_dir, low_percentile=2, high_percentile=98)
    changed = derive_normalized_preview(
        registered, output_dir, low_percentile=5, high_percentile=98
    )
    assert repeat.array_path == first.array_path
    assert changed.array_path != first.array_path


def test_manifest_nonfinite_number_is_rejected_before_schema_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    manifest = _manifest(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["raster"]["nodata"] = float("nan")
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProductRegistrationError) as excinfo:
        register_local_product(manifest, OhrcAdapter())
    assert excinfo.value.reason == "input.label_unparseable"


def test_preview_publish_failure_leaves_no_visible_partial_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    registered = register_local_product(_manifest(tmp_path), OhrcAdapter())
    output_dir = tmp_path / "derived"
    monkeypatch.setattr(os, "rename", lambda *_: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(ProductRegistrationError):
        derive_normalized_preview(registered, output_dir)
    assert not list(output_dir.glob("*.bundle"))
    assert not list(output_dir.glob(".*"))


def test_registration_snapshot_is_private_read_only_and_not_input_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import selene_core.ingest.registration as registration

    monkeypatch.setattr(registration, "open_raster_allowlisted", lambda _: _FakeRaster())
    registered = register_local_product(_manifest(tmp_path), OhrcAdapter())
    assert registered.data_path != tmp_path / "source.tif"
    assert not registered.data_path.is_symlink()
    assert stat.S_IMODE(registered.data_path.stat().st_mode) == 0o400
