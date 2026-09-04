"""Validation helpers for WP-00's public evidence artifacts.

The route matrix intentionally inventories only what is known locally.  It
therefore uses explicit ``null`` values with reasons until a verified official
product record is available.  The claim ledger is separate because a public
number is a stronger assertion: it must point to a content-addressed benchmark
run report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema

from benchmarks.scripts.checkpoints import validate_checkpoint_record
from benchmarks.scripts.fit_provenance import FitProvenanceError, validate_fit_provenance
from benchmarks.scripts.manifest import load_manifest
from benchmarks.scripts.runner import validate_report_document
from selene_core.pipeline.hashing import digest_json

__all__ = [
    "CLAIM_LEDGER_SCHEMA_PATH",
    "ROUTE_MATRIX_SCHEMA_PATH",
    "GovernanceValidationError",
    "load_claim_ledger",
    "load_product_route_matrix",
]

_SCHEMAS_DIR: Final = Path(__file__).resolve().parents[2] / "schemas"
CLAIM_LEDGER_SCHEMA_PATH: Final = _SCHEMAS_DIR / "claim-ledger.schema.json"
ROUTE_MATRIX_SCHEMA_PATH: Final = _SCHEMAS_DIR / "product-route-matrix.schema.json"


class GovernanceValidationError(ValueError):
    """Raised for a malformed or internally inconsistent governance artifact."""


def _load_validated(path: Path, schema_path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(document, schema, format_checker=jsonschema.FormatChecker())
    except jsonschema.exceptions.ValidationError as error:
        raise GovernanceValidationError(
            f"{path} failed schema validation at {error.json_path}: {error.message}"
        ) from error
    return document


def load_product_route_matrix(path: Path) -> dict[str, Any]:
    """Load an interim route matrix and ensure every route family occurs once."""
    document = _load_validated(path, ROUTE_MATRIX_SCHEMA_PATH)
    families = [route["payload_family"] for route in document["routes"]]
    if len(families) != len(set(families)):
        raise GovernanceValidationError(f"{path} contains duplicate payload_family route entries")
    return document


def load_claim_ledger(
    path: Path,
    *,
    report_directory: Path | None = None,
    checkpoint_directory: Path | None = None,
    manifest_directory: Path | None = None,
) -> dict[str, Any]:
    """Load a ledger; active claims must resolve to valid immutable evidence.

    Empty ledgers need no evidence directory.  An active ledger must receive
    both directories explicitly so a caller cannot accidentally validate a
    claim against an ambient or mutable working directory.
    """
    document = _load_validated(path, CLAIM_LEDGER_SCHEMA_PATH)
    claim_ids = [claim["claim_id"] for claim in document["claims"]]
    if len(claim_ids) != len(set(claim_ids)):
        raise GovernanceValidationError(f"{path} contains duplicate claim_id entries")
    if not document["claims"]:
        return document
    if report_directory is None or checkpoint_directory is None or manifest_directory is None:
        raise GovernanceValidationError(
            "active claim ledger requires report_directory, checkpoint_directory, and "
            "manifest_directory"
        )
    reports = _load_reports(report_directory)
    checkpoints = _load_checkpoints(checkpoint_directory, reports)
    manifests = _load_manifests(manifest_directory)
    for claim in document["claims"]:
        report = reports.get(claim["run_report_id"])
        checkpoint = checkpoints.get(claim["checkpoint_id"])
        if report is None:
            raise GovernanceValidationError(
                f"claim {claim['claim_id']!r} references a missing immutable run report"
            )
        if checkpoint is None:
            raise GovernanceValidationError(
                f"claim {claim['claim_id']!r} references a missing independent checkpoint"
            )
        if checkpoint["benchmark_run_report_id"] != claim["run_report_id"]:
            raise GovernanceValidationError(
                f"claim {claim['claim_id']!r} checkpoint does not link to its run report"
            )
        if checkpoint["status"] != "accepted":
            status = checkpoint["status"]
            raise GovernanceValidationError(
                f"claim {claim['claim_id']!r} cannot be authorized by a {status} checkpoint"
            )
        if claim["metric_reference"]["scene_product_id"] != checkpoint["scene_product_id"]:
            raise GovernanceValidationError(
                f"claim {claim['claim_id']!r} metric reference must target the "
                "accepted checkpoint scene"
            )
        _validate_claim_metric_reference(claim, report)
        fit_provenance = report["run_context"]["parameter_fit_provenance"]
        manifest = manifests.get(report["manifest_id"])
        if fit_provenance is None:
            raise GovernanceValidationError(
                f"claim {claim['claim_id']!r} report has no parameter-fit provenance"
            )
        if manifest is None:
            raise GovernanceValidationError(
                f"claim {claim['claim_id']!r} source manifest is missing"
            )
        _validate_report_manifest_binding(report, manifest)
        try:
            validate_fit_provenance(
                fit_provenance, manifest, report["run_context"]["frozen_route"]["snapshot_sha256"]
            )
        except FitProvenanceError as error:
            raise GovernanceValidationError(f"invalid parameter-fit provenance: {error}") from error
    return document


def _load_reports(directory: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        try:
            validate_report_document(document)
        except (jsonschema.exceptions.ValidationError, ValueError) as error:
            raise GovernanceValidationError(f"invalid report {path}: {error}") from error
        report_id: str = document["run_report_id"]
        if report_id in reports:
            raise GovernanceValidationError(f"duplicate immutable report ID {report_id!r}")
        reports[report_id] = document
    return reports


def _load_checkpoints(
    directory: Path, reports: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    checkpoints: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        report_id = record.get("benchmark_run_report_id")
        report = reports.get(report_id) if isinstance(report_id, str) else None
        if report is None:
            raise GovernanceValidationError(
                f"checkpoint {path} references a missing immutable report"
            )
        try:
            validate_checkpoint_record(record, report)
        except (jsonschema.exceptions.ValidationError, ValueError) as error:
            raise GovernanceValidationError(f"invalid checkpoint {path}: {error}") from error
        checkpoint_id: str = record["checkpoint_id"]
        if checkpoint_id in checkpoints:
            raise GovernanceValidationError(f"duplicate checkpoint ID {checkpoint_id!r}")
        checkpoints[checkpoint_id] = record
    return checkpoints


def _load_manifests(directory: Path) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            manifest = load_manifest(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise GovernanceValidationError(f"invalid source manifest {path}: {error}") from error
        manifest_id: str = manifest["manifest_id"]
        if manifest_id in manifests:
            raise GovernanceValidationError(f"duplicate source manifest ID {manifest_id!r}")
        manifests[manifest_id] = manifest
    return manifests


def _validate_report_manifest_binding(report: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Prove report population and manifest digest still describe the same corpus."""
    if report["manifest_sha256"] != digest_json(manifest):
        raise GovernanceValidationError(
            "report manifest_sha256 does not match the loaded source manifest"
        )
    expected_scenes = [
        (product["product_id"], product["split_role"])
        for product in manifest["products"]
        if product["role"] == "source"
    ]
    actual_scenes = [
        (scene["product_id"], scene["split_role"]) for scene in report["scene_results"]
    ]
    if actual_scenes != expected_scenes:
        raise GovernanceValidationError(
            "report source-scene IDs or split roles do not match the loaded source manifest"
        )


def _validate_claim_metric_reference(claim: dict[str, Any], report: dict[str, Any]) -> None:
    """Bind a published number to one typed metric in the cited immutable report."""
    reference = claim["metric_reference"]
    if reference["value"] != claim["value"] or reference["unit"] != claim["unit"]:
        raise GovernanceValidationError("claim value/unit must equal its metric reference")
    scene = next(
        (
            item
            for item in report["scene_results"]
            if item["product_id"] == reference["scene_product_id"]
        ),
        None,
    )
    if scene is None:
        raise GovernanceValidationError("claim metric reference scene is absent from the report")
    metric = scene["result"]["metrics"].get(reference["metric_key"])
    if not isinstance(metric, dict):
        raise GovernanceValidationError("claim metric reference is absent or not a typed metric")
    if metric.get("value") != reference["value"] or metric.get("unit") != reference["unit"]:
        raise GovernanceValidationError(
            "claim metric reference disagrees with immutable report evidence"
        )
