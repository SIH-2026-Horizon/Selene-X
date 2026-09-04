"""Output-bundle coverage for the non-qualified local registration route."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from benchmarks.scripts.controlled_shift import generate_controlled_shift_fixture

from selene_core.match import MatchParameters, MatchPrior
from selene_core.pipeline.local_registration import (
    LocalRegistrationConfig,
    PipelineOrigin,
    PipelineProvenance,
    PipelineResult,
    run_local_registration,
)
from selene_core.products.output_bundle import (
    BundleAlreadyExistsError,
    BundleArrayPayload,
    BundleConfig,
    BundleProvenance,
    validate_local_registration_bundle,
    write_local_registration_bundle,
)

pytestmark = pytest.mark.unit


def _result() -> tuple[PipelineResult, BundleArrayPayload]:
    fixture = generate_controlled_shift_fixture((63, 79), dy_px=3.0, dx_px=-2.0, seed=420)
    result = run_local_registration(
        fixture.base_image,
        fixture.shifted_image,
        provenance=PipelineProvenance(
            job_id="output-bundle-test",
            input_digest="a" * 64,
            reference_digest="b" * 64,
            code_revision="test-revision",
        ),
        config=LocalRegistrationConfig(
            origin=PipelineOrigin.SYNTHETIC_TEST,
            match_parameters=MatchParameters(
                values={"grid_spacing_px": 16, "template_half_size_px": 4, "search_radius_px": 8}
            ),
            prior=MatchPrior(displacement_px=(3.0, -2.0), search_radius_px=5.0),
            grid_shape=(3, 3),
            patch_half_size_px=3,
            noise_variance=0.01,
        ),
    )
    return result, BundleArrayPayload(
        source=fixture.base_image,
        reference=fixture.shifted_image,
        source_validity_mask=np.ones_like(fixture.base_image, dtype=bool),
        reference_validity_mask=np.ones_like(fixture.shifted_image, dtype=bool),
    )


def _config(arrays: BundleArrayPayload) -> BundleConfig:
    return BundleConfig(
        bundle_id="local-synthetic-output-bundle",
        provenance=BundleProvenance(
            producer="tests",
            created_utc="2026-08-31T00:00:00Z",
            output_configuration={"format": "local-registration-v1"},
        ),
        arrays=arrays,
    )


def test_writes_and_validates_a_fail_closed_local_bundle(tmp_path: Path) -> None:
    result, arrays = _result()
    outcome = write_local_registration_bundle(result, tmp_path, config=_config(arrays))

    assert outcome.status == "partial"
    assert outcome.route_qualified is False
    assert outcome.scene_verdict == "reject"
    assert (tmp_path / "correspondences.csv").is_file()
    assert (tmp_path / "metrics.json").is_file()
    assert (tmp_path / "source.npy").is_file()
    assert (tmp_path / "reference.npy").is_file()
    assert (tmp_path / "source-validity-mask.npy").is_file()
    assert (tmp_path / "reference-validity-mask.npy").is_file()
    assert (tmp_path / "coverage-mask.npy").is_file()
    assert (tmp_path / "overlap-mask.unavailable.json").is_file()
    assert (tmp_path / "manifest.json").is_file()
    assert not list(tmp_path.glob("*.tif"))
    assert not list(tmp_path.glob("*.gpkg"))
    assert validate_local_registration_bundle(tmp_path).valid

    metrics = json.loads((tmp_path / "metrics.json").read_text())
    assert metrics["route_qualified"] is False
    assert metrics["origin"] == "synthetic_test"
    assert metrics["scene_verdict"]["verdict"] == "reject"
    assert metrics["correspondence_count"] == len(result.correspondences)
    assert all(item["status"] == "unsupported" for item in metrics["optional_products"])
    assert np.array_equal(np.load(tmp_path / "source.npy", allow_pickle=False), arrays.source)
    assert np.load(tmp_path / "coverage-mask.npy", allow_pickle=False).dtype == bool

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["origin"] == "synthetic_test"
    assert manifest["route_qualified"] is False
    assert manifest["scene_verdict"]["verdict"] == "reject"
    assert manifest["pipeline_provenance"]["job_id"] == "output-bundle-test"
    assert manifest["pipeline_provenance"]["input_digest"] == "a" * 64


def test_validator_reports_tampered_and_missing_artifacts(tmp_path: Path) -> None:
    result, arrays = _result()
    write_local_registration_bundle(result, tmp_path, config=_config(arrays))
    (tmp_path / "correspondences.csv").write_text("tampered", encoding="utf-8")
    tampered = validate_local_registration_bundle(tmp_path)
    assert not tampered.valid
    assert any(failure.code == "checksum_mismatch" for failure in tampered.artifacts)

    (tmp_path / "metrics.json").unlink()
    missing = validate_local_registration_bundle(tmp_path)
    assert not missing.valid
    assert any(failure.code == "missing" for failure in missing.artifacts)


def test_validator_rejects_rehashed_malformed_npy_payload(tmp_path: Path) -> None:
    result, arrays = _result()
    write_local_registration_bundle(result, tmp_path, config=_config(arrays))

    bad_source = tmp_path / "source.npy"
    with bad_source.open("wb") as handle:
        np.save(handle, np.ones((1, 1), dtype=np.float32), allow_pickle=False)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    source_entry = next(
        item for item in manifest["artifacts"] if item["relative_path"] == "source.npy"
    )
    source_entry["sha256"] = hashlib.sha256(bad_source.read_bytes()).hexdigest()
    source_entry["size_bytes"] = bad_source.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validation = validate_local_registration_bundle(tmp_path)
    assert not validation.valid
    assert any(failure.code == "invalid_content" for failure in validation.artifacts)


def test_validator_requires_csv_even_when_its_manifest_entry_is_removed(tmp_path: Path) -> None:
    result, arrays = _result()
    write_local_registration_bundle(result, tmp_path, config=_config(arrays))
    (tmp_path / "correspondences.csv").unlink()
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"] = [
        item for item in manifest["artifacts"] if item["relative_path"] != "correspondences.csv"
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validation = validate_local_registration_bundle(tmp_path)
    assert not validation.valid
    assert any(
        failure.relative_path == "correspondences.csv" and failure.code == "missing"
        for failure in validation.artifacts
    )


def test_refuses_any_in_place_overwrite_and_finite_inconsistent_masks(tmp_path: Path) -> None:
    result, arrays = _result()
    write_local_registration_bundle(result, tmp_path, config=_config(arrays))
    with pytest.raises(BundleAlreadyExistsError):
        write_local_registration_bundle(result, tmp_path, config=_config(arrays))

    invalid_destination = tmp_path / "invalid"
    invalid_destination.mkdir()
    source = arrays.source.copy()
    source[0, 0] = np.nan
    invalid_payload = BundleArrayPayload(
        source=source,
        reference=arrays.reference,
        source_validity_mask=np.ones_like(source, dtype=bool),
        reference_validity_mask=arrays.reference_validity_mask,
    )
    with pytest.raises(ValueError, match="non-finite"):
        write_local_registration_bundle(
            result, invalid_destination, config=_config(invalid_payload)
        )
    assert not tuple(invalid_destination.iterdir())
