"""Verifiable development/validation-only parameter fitting evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema

from selene_core.pipeline.hashing import digest_json

__all__ = ["FitProvenanceError", "validate_fit_provenance"]

_SCHEMA_PATH: Final = (
    Path(__file__).resolve().parents[2] / "schemas" / "parameter-fit-provenance.schema.json"
)
_FIT_SPLITS: Final = frozenset({"train_development", "validation"})


class FitProvenanceError(ValueError):
    """Fitting evidence is absent, tampered, or leaks held-out data."""


def validate_fit_provenance(
    provenance: dict[str, Any], manifest: dict[str, Any], frozen_route_snapshot_sha256: str
) -> None:
    """Verify a fit's ID, source manifest binding, route binding, and split isolation."""
    schema: dict[str, Any] = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(provenance, schema)
    except jsonschema.exceptions.ValidationError as error:
        raise FitProvenanceError(str(error)) from error
    identity = {key: value for key, value in provenance.items() if key != "fit_id"}
    if provenance["fit_id"] != f"pfp-sha256-{digest_json(identity)}":
        raise FitProvenanceError("fit_id does not match fit provenance content")
    if provenance["source_manifest_id"] != manifest["manifest_id"] or provenance[
        "source_manifest_sha256"
    ] != digest_json(manifest):
        raise FitProvenanceError("fit provenance is bound to a different source manifest")
    if provenance["frozen_route_snapshot_sha256"] != frozen_route_snapshot_sha256:
        raise FitProvenanceError("fit provenance is bound to a different frozen route snapshot")
    manifest_roles = {
        product["product_id"]: product["split_role"] for product in manifest["products"]
    }
    fit_ids = [item["product_id"] for item in provenance["inputs"]]
    if len(fit_ids) != len(set(fit_ids)):
        raise FitProvenanceError("fit provenance repeats a product input")
    for item in provenance["inputs"]:
        actual_role = manifest_roles.get(item["product_id"])
        if actual_role != item["split_role"]:
            raise FitProvenanceError("fit input role does not match the frozen source manifest")
        if actual_role not in _FIT_SPLITS:
            raise FitProvenanceError("parameter fitting may use development/validation scenes only")
