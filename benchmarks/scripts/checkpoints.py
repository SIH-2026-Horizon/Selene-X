"""Independent held-out checkpoint validation and immutable report linkage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema

from benchmarks.scripts.runner import validate_report_document
from selene_core.pipeline.hashing import digest_json

__all__ = ["CheckpointValidationError", "load_checkpoint_record", "validate_checkpoint_record"]

_SCHEMA_PATH: Final = (
    Path(__file__).resolve().parents[2] / "schemas" / "independent-checkpoint.schema.json"
)


class CheckpointValidationError(ValueError):
    """A checkpoint cannot support held-out evidence."""


def validate_checkpoint_record(record: dict[str, Any], report: dict[str, Any]) -> None:
    """Validate policy fields and bind a checkpoint to an immutable report."""
    schema: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(record, schema)
        validate_report_document(report)
    except (jsonschema.exceptions.ValidationError, ValueError) as error:
        raise CheckpointValidationError(str(error)) from error

    identity = {key: value for key, value in record.items() if key != "checkpoint_id"}
    identity.pop("benchmark_run_report_id")
    expected_id = f"icp-sha256-{digest_json(identity)}"
    if record["checkpoint_id"] != expected_id:
        raise CheckpointValidationError("checkpoint_id does not match checkpoint content")
    if record["benchmark_run_report_id"] != report["run_report_id"]:
        raise CheckpointValidationError("checkpoint does not link to the supplied immutable report")
    reviewer_ids = [reviewer["reviewer_id"] for reviewer in record["reviewers"]]
    if len(set(reviewer_ids)) != 2:
        raise CheckpointValidationError("checkpoint reviewers must be two distinct people")
    tuning_actor_ids = set(report["run_context"]["tuning_actor_ids"])
    reviewer_tuning_overlap = set(reviewer_ids) & tuning_actor_ids
    if reviewer_tuning_overlap:
        raise CheckpointValidationError(
            "checkpoint reviewers overlap route tuning actors: "
            + ", ".join(sorted(reviewer_tuning_overlap))
        )
    if record["scene_product_id"] in set(report["run_context"]["tuning_scene_product_ids"]):
        raise CheckpointValidationError("held-out checkpoint scene was used for route tuning")

    reviewer_decisions = {reviewer["decision"] for reviewer in record["reviewers"]}
    decisions_disagree = len(reviewer_decisions) > 1
    disagreement = record["disagreement"]
    if disagreement["present"] != decisions_disagree:
        raise CheckpointValidationError("disagreement.present must match reviewer decisions")
    resolution = disagreement["resolution"]
    status_for_decision = {"accept": "accepted", "exclude": "excluded", "unresolved": "unresolved"}
    if decisions_disagree:
        if not isinstance(resolution, dict):
            raise CheckpointValidationError("reviewer disagreement requires a non-empty resolution")
        if (
            resolution["resolver_id"] in reviewer_ids
            or resolution["resolver_id"] in tuning_actor_ids
        ):
            raise CheckpointValidationError(
                "disagreement resolution requires an independent resolver"
            )
        if record["status"] != status_for_decision[resolution["decision"]]:
            raise CheckpointValidationError("checkpoint status must match disagreement resolution")
    else:
        if resolution is not None:
            raise CheckpointValidationError(
                "a unanimous checkpoint must not carry a disagreement resolution"
            )
        decision = next(iter(reviewer_decisions))
        if record["status"] != status_for_decision[decision]:
            raise CheckpointValidationError(
                "checkpoint status must match unanimous reviewer decision"
            )
    report_split_roles = {
        scene["product_id"]: scene["split_role"] for scene in report["scene_results"]
    }
    if report_split_roles.get(record["scene_product_id"]) != "held_out_test":
        raise CheckpointValidationError("checkpoint scene is not a held-out benchmark report scene")
    report_checkpoints = {
        checkpoint["checkpoint_id"]: checkpoint for checkpoint in report["held_out_checkpoints"]
    }
    report_checkpoint = report_checkpoints.get(record["checkpoint_id"])
    if report_checkpoint is None:
        raise CheckpointValidationError("checkpoint is absent from held-out report population")
    if (
        report_checkpoint["scene_product_id"] != record["scene_product_id"]
        or report_checkpoint["status"] != record["status"]
        or report_checkpoint["status_reason"] != record["status_reason"]
    ):
        raise CheckpointValidationError("checkpoint disagrees with its report population record")


def load_checkpoint_record(path: Path, report_path: Path) -> dict[str, Any]:
    """Read and validate one checkpoint against its immutable report document."""
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    validate_checkpoint_record(record, report)
    return record
