"""Benchmark runner producing schema-valid per-scene reports (WP-00 task 9).

Given a benchmark manifest and an optional route function, this module iterates
every source product, runs it through the route, and produces a schema-valid
report on every scene—including failures. No scene is dropped from the report
when a route fails, and no exception escaping a route halts processing of
remaining scenes.

The report produced uses the existing, ratified StageResult contract from
``selene_core.pipeline.results`` and validates each scene's result against
``schemas/stage-result.schema.json``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import jsonschema

from benchmarks.scripts.fit_provenance import validate_fit_provenance
from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.hashing import canonical_json, digest_json
from selene_core.pipeline.results import StageFailure, StageOutcome, StageResult

__all__ = [
    "BENCHMARK_RUN_REPORT_SCHEMA_PATH",
    "BenchmarkRunReport",
    "RouteFn",
    "SceneResult",
    "default_route",
    "run_benchmark",
    "validate_report_document",
]

BENCHMARK_RUN_REPORT_SCHEMA_PATH: Final = (
    Path(__file__).resolve().parents[2] / "schemas" / "benchmark-run-report.schema.json"
)
_STAGE_RESULT_SCHEMA_PATH: Final = (
    Path(__file__).resolve().parents[2] / "schemas" / "stage-result.schema.json"
)

RouteFn = Callable[[dict[str, Any]], StageResult]
"""A route is a function taking a product dict and returning a StageResult.

A "route" represents a qualified image registration pathway for later WP-04+
work. It takes one product dict (one entry from a manifest's ``products`` list)
and returns a ``StageResult`` describing what happened.
"""


def default_route(product: dict[str, Any]) -> StageResult:
    """Return a REJECTED result with VALIDATION_ROUTE_NOT_QUALIFIED.

    This is the fallback when the caller supplies no route. It is not a
    placeholder hack but an honest, correctly-coded statement that no qualified
    route exists yet for the given scene, using the taxonomy's own code for
    exactly this situation.

    Args:
        product: A product dict (one entry from a manifest's ``products`` list).

    Returns:
        A ``StageResult`` with outcome=REJECTED and
        failure=FailureCode.VALIDATION_ROUTE_NOT_QUALIFIED.
    """
    product_id: str = product["product_id"]
    return StageResult(
        stage_name=f"benchmark_scene:{product_id}",
        stage_version="1",
        outcome=StageOutcome.REJECTED,
        failure=StageFailure(
            code=FailureCode.VALIDATION_ROUTE_NOT_QUALIFIED,
            message="No qualified route version covers this benchmark scene.",
            context={"product_id": product_id},
        ),
    )


@dataclass(frozen=True, slots=True)
class SceneResult:
    """Pairing of a product ID with its stage result.

    Immutable and hashable, suitable for inclusion in a frozen dataclass.
    """

    product_id: str
    """The product's unique identifier."""

    split_role: str
    """Frozen benchmark role, retained so held-out population is auditable."""

    result: StageResult
    """The stage result for this scene."""


@dataclass(frozen=True, slots=True)
class BenchmarkRunReport:
    """The complete report of a benchmark run.

    Includes the manifest identity, all scene results, and computed aggregate
    counts. Counts are computed as properties from scene_results to prevent
    drift between the data and the reported aggregate.
    """

    manifest_id: str
    """The identifier of the manifest that was run."""

    scene_results: tuple[SceneResult, ...]
    """Every scene result, one per source product in manifest order."""

    manifest_sha256_value: str
    """Digest captured before any route runs; later caller mutation cannot alter provenance."""

    held_out_checkpoints: tuple[dict[str, Any], ...] = ()
    """All held-out checkpoint statuses, including excluded and unresolved scenes."""

    run_context: dict[str, Any] = field(
        default_factory=lambda: _build_run_context(
            frozen_route=None,
            parameter_fit_provenance=None,
            tuning_actor_ids=(),
            tuning_scene_product_ids=(),
        )
    )
    """Frozen route snapshot and actor records used to prove held-out separation."""

    def __post_init__(self) -> None:
        """Freeze nested caller-owned evidence records at the public boundary."""
        object.__setattr__(self, "held_out_checkpoints", _freeze(self.held_out_checkpoints))
        object.__setattr__(self, "run_context", _freeze(self.run_context))

    @property
    def total_scenes(self) -> int:
        """Total source products processed, including failures and rejections."""
        return len(self.scene_results)

    @property
    def succeeded(self) -> int:
        """Count of scenes with outcome.is_success == True."""
        return sum(1 for sr in self.scene_results if sr.result.outcome.is_success)

    @property
    def rejected(self) -> int:
        """Count of scenes with outcome == REJECTED."""
        return sum(1 for sr in self.scene_results if sr.result.outcome == StageOutcome.REJECTED)

    @property
    def failed(self) -> int:
        """Count of scenes with outcome == FAILED."""
        return sum(1 for sr in self.scene_results if sr.result.outcome == StageOutcome.FAILED)

    @property
    def cancelled(self) -> int:
        """Count of scenes with outcome == CANCELLED."""
        return sum(1 for sr in self.scene_results if sr.result.outcome == StageOutcome.CANCELLED)

    @property
    def manifest_sha256(self) -> str:
        """Canonical digest of the exact manifest object the route received."""
        return self.manifest_sha256_value

    @property
    def run_report_id(self) -> str:
        """Content-addressed immutable identity for this report's payload."""
        return f"brr-sha256-{digest_json(self._document_without_id())}"

    def _document_without_id(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "manifest_id": self.manifest_id,
            "manifest_sha256": self.manifest_sha256,
            "run_context": _thaw(self.run_context),
            "scene_results": [
                {
                    "product_id": scene.product_id,
                    "split_role": scene.split_role,
                    "result": scene.result.model_dump(mode="json"),
                }
                for scene in self.scene_results
            ],
            "held_out_checkpoints": _thaw(self.held_out_checkpoints),
            "summary": {
                "total_scenes": self.total_scenes,
                "succeeded": self.succeeded,
                "rejected": self.rejected,
                "failed": self.failed,
                "cancelled": self.cancelled,
                "held_out_checkpoint_population": {
                    "total": len(self.held_out_checkpoints),
                    "accepted": sum(
                        checkpoint["status"] == "accepted"
                        for checkpoint in self.held_out_checkpoints
                    ),
                    "excluded": sum(
                        checkpoint["status"] == "excluded"
                        for checkpoint in self.held_out_checkpoints
                    ),
                    "unresolved": sum(
                        checkpoint["status"] == "unresolved"
                        for checkpoint in self.held_out_checkpoints
                    ),
                },
            },
        }

    def to_document(self) -> dict[str, Any]:
        """Return the schema-valid, JSON-serializable immutable report document."""
        document = self._document_without_id()
        document["run_report_id"] = self.run_report_id
        return document

    def validate(self) -> None:
        """Validate the outer report and each embedded immutable stage result."""
        validate_report_document(self.to_document())

    def write(self, path: Path) -> None:
        """Atomically publish a report once, refusing to overwrite evidence.

        The filename is deliberately not trusted as identity; callers should
        use :attr:`run_report_id`.  Existing files are never replaced, even
        with identical bytes, because overwrite would make publication races
        and audit trails ambiguous.
        """
        self.validate()
        payload = canonical_json(self.to_document()).encode("utf-8") + b"\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"refusing to overwrite immutable benchmark report: {path}")
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # link rather than replace: a concurrent publisher cannot be
            # overwritten.  A hard link is atomic within the output directory.
            os.link(temporary, path)
        except FileExistsError:
            message = f"refusing to overwrite immutable benchmark report: {path}"
            raise FileExistsError(message) from None
        finally:
            temporary.unlink(missing_ok=True)


def validate_report_document(document: dict[str, Any]) -> None:
    """Validate report shape, stage records, counts, and its content-derived ID."""
    report_schema: dict[str, Any] = json.loads(
        BENCHMARK_RUN_REPORT_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    stage_schema: dict[str, Any] = json.loads(_STAGE_RESULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, report_schema)
    for scene in document["scene_results"]:
        jsonschema.validate(scene["result"], stage_schema)
    scene_split_roles = {
        scene["product_id"]: scene["split_role"] for scene in document["scene_results"]
    }
    if len(scene_split_roles) != len(document["scene_results"]):
        raise ValueError("benchmark report contains duplicate scene product IDs")
    frozen_route = document["run_context"]["frozen_route"]
    snapshot = {
        "route_id": frozen_route["route_id"],
        "route_version": frozen_route["route_version"],
        "parameter_snapshot": frozen_route["parameter_snapshot"],
    }
    if frozen_route["snapshot_sha256"] != digest_json(snapshot):
        raise ValueError("benchmark report frozen route snapshot hash is invalid")
    held_out_ids = {
        scene_id
        for scene_id, split_role in scene_split_roles.items()
        if split_role == "held_out_test"
    }
    forbidden_tuning_use = held_out_ids & set(document["run_context"]["tuning_scene_product_ids"])
    if forbidden_tuning_use:
        raise ValueError("benchmark report records held-out scenes as tuning data")
    checkpoint_ids = [
        checkpoint["checkpoint_id"] for checkpoint in document["held_out_checkpoints"]
    ]
    if len(checkpoint_ids) != len(set(checkpoint_ids)):
        raise ValueError("benchmark report contains duplicate held-out checkpoint IDs")
    for checkpoint in document["held_out_checkpoints"]:
        if scene_split_roles.get(checkpoint["scene_product_id"]) != "held_out_test":
            raise ValueError("held-out checkpoint must refer to a held-out report scene")
    checkpoint_scene_ids = [
        checkpoint["scene_product_id"] for checkpoint in document["held_out_checkpoints"]
    ]
    if set(checkpoint_scene_ids) != held_out_ids or len(checkpoint_scene_ids) != len(
        set(checkpoint_scene_ids)
    ):
        raise ValueError("every held-out report scene requires exactly one checkpoint")
    outcomes = [scene["result"]["outcome"] for scene in document["scene_results"]]
    expected_summary = {
        "total_scenes": len(outcomes),
        "succeeded": sum(
            outcome in {"succeeded", "succeeded_with_warnings"} for outcome in outcomes
        ),
        "rejected": outcomes.count("rejected"),
        "failed": outcomes.count("failed"),
        "cancelled": outcomes.count("cancelled"),
        "held_out_checkpoint_population": {
            "total": len(document["held_out_checkpoints"]),
            "accepted": sum(
                checkpoint["status"] == "accepted"
                for checkpoint in document["held_out_checkpoints"]
            ),
            "excluded": sum(
                checkpoint["status"] == "excluded"
                for checkpoint in document["held_out_checkpoints"]
            ),
            "unresolved": sum(
                checkpoint["status"] == "unresolved"
                for checkpoint in document["held_out_checkpoints"]
            ),
        },
    }
    if document["summary"] != expected_summary:
        raise ValueError("benchmark report summary does not match its scene results")
    document_without_id = {key: value for key, value in document.items() if key != "run_report_id"}
    expected_id = f"brr-sha256-{digest_json(document_without_id)}"
    if document["run_report_id"] != expected_id:
        raise ValueError("benchmark report run_report_id does not match its canonical content")


def run_benchmark(
    manifest: dict[str, Any],
    *,
    route: RouteFn | None = None,
    held_out_checkpoints: tuple[dict[str, Any], ...] = (),
    frozen_route: dict[str, Any] | None = None,
    parameter_fit_provenance: dict[str, Any] | None = None,
    tuning_actor_ids: tuple[str, ...] = (),
    tuning_scene_product_ids: tuple[str, ...] = (),
) -> BenchmarkRunReport:
    """Run a benchmark manifest through a route, producing a schema-valid report.

    Iterates every product in the manifest whose role is "source" (reference,
    terrain, and control products are not "run"). For each source product, calls
    the supplied route (or default_route if none is supplied). If the route
    raises an exception, catches it and converts it into a FAILED StageResult
    with failure code INTERNAL_UNEXPECTED_ERROR, ensuring no exception halts
    processing of remaining scenes.

    Args:
        manifest: A manifest dict already validated by ``manifest.load_manifest``
            (this function trusts its shape and does not re-run schema
            validation).
        route: Optional custom route function. If not supplied, default_route is
            used, which always returns REJECTED with VALIDATION_ROUTE_NOT_QUALIFIED.

    Returns:
        A BenchmarkRunReport containing every source product's result and
        aggregate counts.
    """
    if route is None:
        route = default_route

    # Freeze the provenance identity before calling arbitrary route code.  A
    # route receives a product dict for ergonomics but must not be able to
    # retroactively change the manifest identity recorded in evidence.
    manifest_snapshot = deepcopy(manifest)
    manifest_sha256 = digest_json(manifest_snapshot)
    run_context = _build_run_context(
        frozen_route=frozen_route,
        parameter_fit_provenance=parameter_fit_provenance,
        tuning_actor_ids=tuning_actor_ids,
        tuning_scene_product_ids=tuning_scene_product_ids,
    )
    if frozen_route is not None and parameter_fit_provenance is None:
        raise ValueError("a non-default frozen route requires parameter_fit_provenance")
    if parameter_fit_provenance is not None:
        validate_fit_provenance(
            parameter_fit_provenance,
            manifest_snapshot,
            run_context["frozen_route"]["snapshot_sha256"],
        )
    scene_results: list[SceneResult] = []

    for product in manifest_snapshot["products"]:
        # Only process source products; skip reference, terrain, control, etc.
        if product.get("role") != "source":
            continue

        product_id: str = product["product_id"]

        try:
            result = route(deepcopy(product))
            if not isinstance(result, StageResult):
                raise TypeError("route must return a StageResult")
        except Exception as error:
            # Convert any exception into a FAILED result with
            # INTERNAL_UNEXPECTED_ERROR, preserving the original exception
            # message. This ensures no scene's route crashing aborts the run.
            result = StageResult(
                stage_name=f"benchmark_scene:{product_id}",
                stage_version="1",
                outcome=StageOutcome.FAILED,
                failure=StageFailure(
                    code=FailureCode.INTERNAL_UNEXPECTED_ERROR,
                    message=f"{type(error).__name__}: {error}",
                    context={"product_id": product_id},
                ),
            )

        scene_results.append(
            SceneResult(product_id=product_id, split_role=product["split_role"], result=result)
        )

    manifest_id: str = manifest_snapshot["manifest_id"]
    held_out_source_ids = {
        product["product_id"]
        for product in manifest_snapshot["products"]
        if product["role"] == "source" and product["split_role"] == "held_out_test"
    }
    checkpoint_scene_ids = [checkpoint["scene_product_id"] for checkpoint in held_out_checkpoints]
    if set(checkpoint_scene_ids) != held_out_source_ids or len(checkpoint_scene_ids) != len(
        set(checkpoint_scene_ids)
    ):
        raise ValueError(
            "every held-out source scene requires exactly one checkpoint, including excluded "
            "and unresolved scenes"
        )
    held_out_tuning_use = held_out_source_ids & set(tuning_scene_product_ids)
    if held_out_tuning_use:
        raise ValueError(
            "held-out scenes are present in tuning_scene_product_ids: "
            + ", ".join(sorted(held_out_tuning_use))
        )
    report = BenchmarkRunReport(
        manifest_id=manifest_id,
        scene_results=tuple(scene_results),
        manifest_sha256_value=manifest_sha256,
        held_out_checkpoints=held_out_checkpoints,
        run_context=run_context,
    )
    report.validate()
    return report


def _build_run_context(
    *,
    frozen_route: dict[str, Any] | None,
    parameter_fit_provenance: dict[str, Any] | None,
    tuning_actor_ids: tuple[str, ...],
    tuning_scene_product_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Create content-verifiable frozen route provenance for a benchmark run."""
    snapshot = (
        deepcopy(frozen_route)
        if frozen_route is not None
        else {
            "route_id": "unqualified-default-route",
            "route_version": "1",
            "parameter_snapshot": {},
        }
    )
    expected_keys = {"route_id", "route_version", "parameter_snapshot"}
    if set(snapshot) != expected_keys:
        raise ValueError(
            "frozen_route must contain exactly route_id, route_version, parameter_snapshot"
        )
    if not isinstance(snapshot["route_id"], str) or not snapshot["route_id"]:
        raise ValueError("frozen_route.route_id must be a non-empty string")
    if not isinstance(snapshot["route_version"], str) or not snapshot["route_version"]:
        raise ValueError("frozen_route.route_version must be a non-empty string")
    if not isinstance(snapshot["parameter_snapshot"], dict):
        raise ValueError("frozen_route.parameter_snapshot must be an object")
    if len(tuning_actor_ids) != len(set(tuning_actor_ids)):
        raise ValueError("tuning_actor_ids must be unique")
    if len(tuning_scene_product_ids) != len(set(tuning_scene_product_ids)):
        raise ValueError("tuning_scene_product_ids must be unique")
    frozen_route_document = dict(snapshot)
    frozen_route_document["snapshot_sha256"] = digest_json(snapshot)
    return {
        "frozen_route": frozen_route_document,
        "parameter_fit_provenance": deepcopy(parameter_fit_provenance),
        "tuning_actor_ids": list(tuning_actor_ids),
        "tuning_scene_product_ids": list(tuning_scene_product_ids),
    }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
