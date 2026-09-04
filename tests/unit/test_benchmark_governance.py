"""Focused contract tests for WP-00 public evidence artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from benchmarks.scripts.checkpoints import CheckpointValidationError, validate_checkpoint_record
from benchmarks.scripts.governance import (
    GovernanceValidationError,
    load_claim_ledger,
    load_product_route_matrix,
)
from benchmarks.scripts.runner import run_benchmark

from selene_core.pipeline.hashing import digest_json
from selene_core.pipeline.results import StageOutcome, StageResult

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_interim_route_matrix_covers_all_required_families_without_fake_products() -> None:
    matrix = load_product_route_matrix(
        _ROOT / "benchmarks/manifests/interim-public-product-route-matrix.v1.json"
    )

    assert matrix["interim"] is True
    assert matrix["limitation_status"] == "external_product_evidence_pending"
    assert {route["payload_family"] for route in matrix["routes"]} == {
        "OHRC",
        "TMC-2",
        "IIRS",
        "LROC_NAC",
        "SELENE_TC",
        "SLDEM",
        "LOLA",
        "REGIONAL_NAC_DTM",
    }
    assert all(route["product_id"]["value"] is None for route in matrix["routes"])
    assert all("credentials" in route for route in matrix["routes"])


def test_known_route_fact_requires_evidence_citation(tmp_path: Path) -> None:
    matrix_path = _ROOT / "benchmarks/manifests/interim-public-product-route-matrix.v1.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["routes"][0]["product_id"] = {"value": "invented-product", "citations": []}
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(matrix), encoding="utf-8")

    with pytest.raises(GovernanceValidationError, match="non-empty"):
        load_product_route_matrix(path)


def test_initial_claim_ledger_authorizes_no_public_quantitative_claims() -> None:
    ledger = load_claim_ledger(_ROOT / "benchmarks/claim-ledger.v1.json")

    assert ledger["status"] == "no_public_quantitative_claims"
    assert ledger["claims"] == []


def test_claim_ledger_rejects_duplicate_claim_ids(tmp_path: Path) -> None:
    ledger = {
        "schema_version": "1.0.0",
        "ledger_id": "fixture",
        "status": "active",
        "claims": [
            {
                "claim_id": "same-id",
                "statement": "Synthetic numeric claim.",
                "value": 1.0,
                "unit": "px",
                "run_report_id": "brr-sha256-" + "a" * 64,
                "checkpoint_id": "icp-sha256-" + "c" * 64,
                "metric_reference": {
                    "scene_product_id": "synthetic",
                    "metric_key": "x",
                    "value": 1.0,
                    "unit": "px",
                },
                "scope": "synthetic fixture",
                "limitations": "Not mission evidence.",
            },
            {
                "claim_id": "same-id",
                "statement": "Another synthetic numeric claim.",
                "value": 2.0,
                "unit": "px",
                "run_report_id": "brr-sha256-" + "b" * 64,
                "checkpoint_id": "icp-sha256-" + "d" * 64,
                "metric_reference": {
                    "scene_product_id": "synthetic",
                    "metric_key": "x",
                    "value": 2.0,
                    "unit": "px",
                },
                "scope": "synthetic fixture",
                "limitations": "Not mission evidence.",
            },
        ],
    }
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(ledger), encoding="utf-8")

    with pytest.raises(GovernanceValidationError, match="duplicate claim_id"):
        load_claim_ledger(path)


def test_active_claim_resolves_report_and_independent_checkpoint(tmp_path: Path) -> None:
    product = {
        "product_id": "held-out-001",
        "mission": "synthetic",
        "payload_family": "OTHER",
        "role": "source",
        "split_role": "held_out_test",
        "terrain_group": "held-out-terrain",
        "source_url": "https://synthetic.invalid",
        "license": "synthetic",
        "credentials_required": [],
        "files": [
            {
                "relative_path": "held-out-001/data.bin",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "media_type": "application/octet-stream",
                "role": "data",
            }
        ],
    }
    development_product = json.loads(json.dumps(product))
    development_product["product_id"] = "development-001"
    development_product["split_role"] = "train_development"
    development_product["terrain_group"] = "development-terrain"
    development_product["files"][0]["relative_path"] = "development-001/data.bin"
    manifest = {
        "schema_version": "1.0.0",
        "manifest_id": "held-out",
        "interim": True,
        "created_utc": "2026-01-01T00:00:00Z",
        "products": [product, development_product],
    }
    frozen_route = {
        "route_id": "synthetic-frozen-route",
        "route_version": "1",
        "parameter_snapshot": {"threshold": 0.5},
    }
    frozen_route_sha256 = digest_json(frozen_route)
    fit_provenance = {
        "schema_version": "1.0.0",
        "source_manifest_id": manifest["manifest_id"],
        "source_manifest_sha256": digest_json(manifest),
        "frozen_route_snapshot_sha256": frozen_route_sha256,
        "inputs": [{"product_id": "development-001", "split_role": "train_development"}],
    }
    fit_provenance["fit_id"] = "pfp-sha256-" + digest_json(fit_provenance)
    checkpoint = {
        "schema_version": "1.0.0",
        "benchmark_run_report_id": "brr-sha256-" + "0" * 64,
        "scene_product_id": "held-out-001",
        "split_role": "held_out_test",
        "process": {"independent": True, "blinded": True, "protocol_version": "v1"},
        "reviewers": [
            {"reviewer_id": "r1", "decision": "accept"},
            {"reviewer_id": "r2", "decision": "accept"},
        ],
        "covariance": {"value": None, "reason": "No control solution."},
        "control_uncertainty_m": None,
        "control_uncertainty_reason": "No control solution.",
        "disagreement": {"present": False, "description": "Both accept.", "resolution": None},
        "status": "accepted",
        "status_reason": "Synthetic checkpoint accepted only for ledger-linkage testing.",
    }
    checkpoint_identity = {
        key: value for key, value in checkpoint.items() if key != "benchmark_run_report_id"
    }
    checkpoint["checkpoint_id"] = "icp-sha256-" + digest_json(checkpoint_identity)

    def metric_route(product: dict[str, Any]) -> StageResult:
        return StageResult(
            stage_name=f"benchmark_scene:{product['product_id']}",
            stage_version="1",
            outcome=StageOutcome.SUCCEEDED,
            metrics={"synthetic.rmse": {"value": 1.0, "unit": "px"}},
        )

    report = run_benchmark(
        manifest,
        held_out_checkpoints=(
            {
                key: checkpoint[key]
                for key in ("checkpoint_id", "scene_product_id", "status", "status_reason")
            },
        ),
        frozen_route=frozen_route,
        parameter_fit_provenance=fit_provenance,
        route=metric_route,
    )
    checkpoint["benchmark_run_report_id"] = report.run_report_id
    reports = tmp_path / "reports"
    checkpoints = tmp_path / "checkpoints"
    report.write(reports / "report.json")
    checkpoints.mkdir()
    (checkpoints / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    ledger = {
        "schema_version": "1.0.0",
        "ledger_id": "active",
        "status": "active",
        "claims": [
            {
                "claim_id": "claim-1",
                "statement": "Synthetic only.",
                "value": 1.0,
                "unit": "px",
                "run_report_id": report.run_report_id,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "metric_reference": {
                    "scene_product_id": "held-out-001",
                    "metric_key": "synthetic.rmse",
                    "value": 1.0,
                    "unit": "px",
                },
                "scope": "synthetic",
                "limitations": "Not mission evidence.",
            }
        ],
    }
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    assert (
        load_claim_ledger(
            ledger_path,
            report_directory=reports,
            checkpoint_directory=checkpoints,
            manifest_directory=manifests,
        )
        == ledger
    )

    development_metric_ledger = json.loads(json.dumps(ledger))
    development_metric_ledger["claims"][0]["metric_reference"]["scene_product_id"] = (
        "development-001"
    )
    development_metric_ledger_path = tmp_path / "development-metric-ledger.json"
    development_metric_ledger_path.write_text(
        json.dumps(development_metric_ledger), encoding="utf-8"
    )

    with pytest.raises(
        GovernanceValidationError, match="must target the accepted checkpoint scene"
    ):
        load_claim_ledger(
            development_metric_ledger_path,
            report_directory=reports,
            checkpoint_directory=checkpoints,
            manifest_directory=manifests,
        )

    contradictory = json.loads(json.dumps(checkpoint))
    contradictory["reviewers"][1]["decision"] = "exclude"
    contradictory["checkpoint_id"] = "icp-sha256-" + digest_json(
        {
            key: value
            for key, value in contradictory.items()
            if key not in {"checkpoint_id", "benchmark_run_report_id"}
        }
    )
    contradictory_report = report.to_document()
    contradictory_report["held_out_checkpoints"][0]["checkpoint_id"] = contradictory[
        "checkpoint_id"
    ]
    contradictory_report["run_report_id"] = "brr-sha256-" + digest_json(
        {key: value for key, value in contradictory_report.items() if key != "run_report_id"}
    )
    contradictory["benchmark_run_report_id"] = contradictory_report["run_report_id"]

    with pytest.raises(CheckpointValidationError, match=r"disagreement\.present"):
        validate_checkpoint_record(contradictory, contradictory_report)

    overlapping_actor_report = json.loads(json.dumps(report.to_document()))
    overlapping_actor_report["run_context"]["tuning_actor_ids"] = ["r1"]
    overlapping_actor_report["run_report_id"] = "brr-sha256-" + digest_json(
        {key: value for key, value in overlapping_actor_report.items() if key != "run_report_id"}
    )
    overlapping_actor_checkpoint = json.loads(json.dumps(checkpoint))
    overlapping_actor_checkpoint["benchmark_run_report_id"] = overlapping_actor_report[
        "run_report_id"
    ]

    with pytest.raises(CheckpointValidationError, match="overlap route tuning actors"):
        validate_checkpoint_record(overlapping_actor_checkpoint, overlapping_actor_report)

    excluded = json.loads(json.dumps(checkpoint))
    excluded["reviewers"] = [
        {"reviewer_id": "r1", "decision": "exclude"},
        {"reviewer_id": "r2", "decision": "exclude"},
    ]
    excluded["status"] = "excluded"
    excluded["status_reason"] = "Excluded for claim-authorization test."
    excluded["disagreement"] = {
        "present": False,
        "description": "Both exclude.",
        "resolution": None,
    }
    excluded["checkpoint_id"] = "icp-sha256-" + digest_json(
        {
            key: value
            for key, value in excluded.items()
            if key not in {"checkpoint_id", "benchmark_run_report_id"}
        }
    )
    excluded_report = json.loads(json.dumps(report.to_document()))
    excluded_report["held_out_checkpoints"] = [
        {
            key: excluded[key]
            for key in ("checkpoint_id", "scene_product_id", "status", "status_reason")
        }
    ]
    excluded_report["summary"]["held_out_checkpoint_population"] = {
        "total": 1,
        "accepted": 0,
        "excluded": 1,
        "unresolved": 0,
    }
    excluded_report["run_report_id"] = "brr-sha256-" + digest_json(
        {key: value for key, value in excluded_report.items() if key != "run_report_id"}
    )
    excluded["benchmark_run_report_id"] = excluded_report["run_report_id"]
    excluded_reports = tmp_path / "excluded-reports"
    excluded_checkpoints = tmp_path / "excluded-checkpoints"
    excluded_reports.mkdir()
    excluded_checkpoints.mkdir()
    (excluded_reports / "report.json").write_text(json.dumps(excluded_report), encoding="utf-8")
    (excluded_checkpoints / "checkpoint.json").write_text(json.dumps(excluded), encoding="utf-8")
    excluded_ledger = json.loads(json.dumps(ledger))
    excluded_ledger["claims"][0]["run_report_id"] = excluded_report["run_report_id"]
    excluded_ledger["claims"][0]["checkpoint_id"] = excluded["checkpoint_id"]
    excluded_ledger_path = tmp_path / "excluded-ledger.json"
    excluded_ledger_path.write_text(json.dumps(excluded_ledger), encoding="utf-8")

    with pytest.raises(GovernanceValidationError, match="cannot be authorized"):
        load_claim_ledger(
            excluded_ledger_path,
            report_directory=excluded_reports,
            checkpoint_directory=excluded_checkpoints,
            manifest_directory=manifests,
        )

    detached_report = report.to_document()
    detached_report["manifest_sha256"] = "f" * 64
    detached_report["run_report_id"] = "brr-sha256-" + digest_json(
        {key: value for key, value in detached_report.items() if key != "run_report_id"}
    )
    detached_checkpoint = json.loads(json.dumps(checkpoint))
    detached_checkpoint["benchmark_run_report_id"] = detached_report["run_report_id"]
    detached_reports = tmp_path / "detached-reports"
    detached_checkpoints = tmp_path / "detached-checkpoints"
    detached_reports.mkdir()
    detached_checkpoints.mkdir()
    (detached_reports / "report.json").write_text(json.dumps(detached_report), encoding="utf-8")
    (detached_checkpoints / "checkpoint.json").write_text(
        json.dumps(detached_checkpoint), encoding="utf-8"
    )
    detached_ledger = json.loads(json.dumps(ledger))
    detached_ledger["claims"][0]["run_report_id"] = detached_report["run_report_id"]
    detached_ledger_path = tmp_path / "detached-ledger.json"
    detached_ledger_path.write_text(json.dumps(detached_ledger), encoding="utf-8")

    with pytest.raises(GovernanceValidationError, match="manifest_sha256"):
        load_claim_ledger(
            detached_ledger_path,
            report_directory=detached_reports,
            checkpoint_directory=detached_checkpoints,
            manifest_directory=manifests,
        )
