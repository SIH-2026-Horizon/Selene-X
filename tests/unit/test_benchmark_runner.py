"""Tests for the benchmark runner (WP-00 task 9).

Every fixture manifest in this module is validated against the benchmark
manifest JSON schema before use. Every scene result is validated against the
stage-result schema. This ensures the runner produces schema-valid output
even when routes fail or raise exceptions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from benchmarks.scripts import manifest, runner
from benchmarks.scripts.fit_provenance import FitProvenanceError

from selene_core.pipeline.failures import FailureCode
from selene_core.pipeline.hashing import digest_json
from selene_core.pipeline.results import StageFailure, StageOutcome, StageResult

pytestmark = pytest.mark.unit


def _make_source_product(
    product_id: str,
) -> dict[str, Any]:
    """Create a minimal valid source product for testing."""
    return {
        "product_id": product_id,
        "mission": "synthetic",
        "payload_family": "OTHER",
        "role": "source",
        "product_level": None,
        "source_url": "https://synthetic.invalid/product",
        "license": "synthetic",
        "access_conditions": None,
        "credentials_required": [],
        "files": [
            {
                "relative_path": f"{product_id}/data.tif",
                "sha256": "00" * 32,
                "size_bytes": 1000,
                "media_type": "image/tiff",
                "role": "data",
            }
        ],
        "reference_version": None,
        "split_role": "train_development",
        "terrain_group": None,
        "stress_bins": {},
        "control_uncertainty_m": None,
        "control_uncertainty_reason": "synthetic fixture, not applicable",
        "warnings": [],
    }


def _make_terrain_product(
    product_id: str,
) -> dict[str, Any]:
    """Create a minimal valid terrain reference product for testing."""
    return {
        "product_id": product_id,
        "mission": "synthetic",
        "payload_family": "OTHER",
        "role": "terrain",
        "product_level": None,
        "source_url": "https://synthetic.invalid/terrain",
        "license": "synthetic",
        "access_conditions": None,
        "credentials_required": [],
        "files": [
            {
                "relative_path": f"{product_id}/terrain.tif",
                "sha256": "11" * 32,
                "size_bytes": 5000,
                "media_type": "image/tiff",
                "role": "data",
            }
        ],
        "reference_version": None,
        "split_role": "not_applicable",
        "terrain_group": None,
        "stress_bins": {},
        "control_uncertainty_m": None,
        "control_uncertainty_reason": "not applicable",
        "warnings": [],
    }


def _make_image_reference_product(
    product_id: str,
) -> dict[str, Any]:
    """Create a minimal valid image reference product for testing."""
    return {
        "product_id": product_id,
        "mission": "synthetic",
        "payload_family": "OTHER",
        "role": "image_reference",
        "product_level": None,
        "source_url": "https://synthetic.invalid/reference",
        "license": "synthetic",
        "access_conditions": None,
        "credentials_required": [],
        "files": [
            {
                "relative_path": f"{product_id}/reference.tif",
                "sha256": "22" * 32,
                "size_bytes": 4000,
                "media_type": "image/tiff",
                "role": "data",
            }
        ],
        "reference_version": "v1.0.0",
        "split_role": "not_applicable",
        "terrain_group": None,
        "stress_bins": {},
        "control_uncertainty_m": None,
        "control_uncertainty_reason": "not applicable",
        "warnings": [],
    }


def _make_manifest(products: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a minimal valid manifest containing the given products."""
    return {
        "schema_version": "1.0.0",
        "manifest_id": "sync-benchmark-manifest",
        "interim": True,
        "created_utc": datetime.now(UTC).isoformat(),
        "products": products,
    }


def _validate_manifest_schema(manifest_dict: dict[str, Any]) -> None:
    """Validate a fixture manifest against the benchmark manifest schema.

    Raises jsonschema.ValidationError if the manifest does not conform to
    the schema, catching drifting fixtures immediately.
    """
    schema = manifest.load_schema()
    jsonschema.validate(manifest_dict, schema)


def _validate_stage_result_schema(result: StageResult) -> None:
    """Validate a stage result against the stage-result schema.

    Raises jsonschema.ValidationError if the result does not conform to
    the schema, proving we produce schema-valid output.
    """
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "stage-result.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    result_dict = result.model_dump(mode="json")
    jsonschema.validate(result_dict, schema)


class TestDefaultRoute:
    """Tests for default_route behavior."""

    def test_default_route_returns_rejected(self) -> None:
        """default_route returns REJECTED with VALIDATION_ROUTE_NOT_QUALIFIED."""
        product = _make_source_product("sync-test-001")
        result = runner.default_route(product)

        assert result.outcome == StageOutcome.REJECTED
        assert result.failure is not None
        assert result.failure.code == FailureCode.VALIDATION_ROUTE_NOT_QUALIFIED
        assert result.stage_name == "benchmark_scene:sync-test-001"
        assert result.stage_version == "1"

    def test_default_route_schema_valid(self) -> None:
        """default_route result validates against stage-result schema."""
        product = _make_source_product("sync-test-002")
        result = runner.default_route(product)

        _validate_stage_result_schema(result)


class TestRunBenchmark:
    """Tests for run_benchmark function."""

    def test_run_benchmark_no_route_all_rejected(self) -> None:
        """Without a custom route, all source products are REJECTED."""
        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-001"),
                _make_source_product("sync-002"),
                _make_source_product("sync-003"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict)

        assert report.manifest_id == "sync-benchmark-manifest"
        assert report.total_scenes == 3
        assert report.rejected == 3
        assert report.succeeded == 0
        assert report.failed == 0
        assert report.cancelled == 0
        assert len(report.scene_results) == 3
        assert all(sr.result.outcome == StageOutcome.REJECTED for sr in report.scene_results)
        report.validate()

    def test_report_document_is_content_addressed_and_write_is_immutable(
        self, tmp_path: Path
    ) -> None:
        manifest_dict = _make_manifest([_make_source_product("sync-immutable")])
        report = runner.run_benchmark(manifest_dict)

        document = report.to_document()
        assert document["run_report_id"] == report.run_report_id
        assert document["summary"]["rejected"] == 1

        path = tmp_path / "report.json"
        report.write(path)
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written == document
        with pytest.raises(FileExistsError, match="immutable benchmark report"):
            report.write(path)

    def test_report_manifest_digest_is_captured_before_route_mutation(self) -> None:
        manifest_dict = _make_manifest([_make_source_product("sync-provenance")])
        expected_digest = digest_json(manifest_dict)

        def mutating_route(product: dict[str, Any]) -> StageResult:
            product["warnings"].append("route attempted mutation")
            return StageResult(
                stage_name=f"benchmark_scene:{product['product_id']}",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
            )

        report = runner.run_benchmark(manifest_dict, route=mutating_route)

        assert report.manifest_sha256 == expected_digest

    def test_report_validator_rejects_a_tampered_content_addressed_report(self) -> None:
        report = runner.run_benchmark(_make_manifest([_make_source_product("sync-tamper")]))
        document = report.to_document()
        document["summary"]["failed"] = 1

        with pytest.raises(ValueError, match="summary does not match"):
            runner.validate_report_document(document)

    def test_held_out_excluded_checkpoint_stays_in_population_denominator(self) -> None:
        product = _make_source_product("sync-held-out")
        product["split_role"] = "held_out_test"
        checkpoint = {
            "checkpoint_id": "icp-sha256-" + "a" * 64,
            "scene_product_id": "sync-held-out",
            "status": "excluded",
            "status_reason": "Deliberately excluded fixture.",
        }
        report = runner.run_benchmark(_make_manifest([product]), held_out_checkpoints=(checkpoint,))

        population = report.to_document()["summary"]["held_out_checkpoint_population"]
        assert population == {"total": 1, "accepted": 0, "excluded": 1, "unresolved": 0}
        assert report.total_scenes == 1

    def test_held_out_scene_cannot_be_declared_as_tuning_data(self) -> None:
        product = _make_source_product("sync-held-out-tuning")
        product["split_role"] = "held_out_test"
        checkpoint = {
            "checkpoint_id": "icp-sha256-" + "b" * 64,
            "scene_product_id": "sync-held-out-tuning",
            "status": "unresolved",
            "status_reason": "Fixture protocol not completed.",
        }

        with pytest.raises(ValueError, match="held-out scenes are present"):
            runner.run_benchmark(
                _make_manifest([product]),
                held_out_checkpoints=(checkpoint,),
                tuning_scene_product_ids=("sync-held-out-tuning",),
            )

    def test_report_validator_rejects_tampered_frozen_route_snapshot(self) -> None:
        report = runner.run_benchmark(_make_manifest([_make_source_product("sync-route")]))
        document = report.to_document()
        document["run_context"]["frozen_route"]["parameter_snapshot"] = {"threshold": 0.5}

        with pytest.raises(ValueError, match="frozen route snapshot hash"):
            runner.validate_report_document(document)

    def test_non_default_route_requires_verifiable_fit_provenance(self) -> None:
        frozen_route = {
            "route_id": "fitted-route",
            "route_version": "1",
            "parameter_snapshot": {"threshold": 0.5},
        }

        with pytest.raises(ValueError, match="requires parameter_fit_provenance"):
            runner.run_benchmark(
                _make_manifest([_make_source_product("sync-fit-required")]),
                frozen_route=frozen_route,
            )

    def test_fit_provenance_rejects_held_out_fit_input(self) -> None:
        product = _make_source_product("sync-fit-held-out")
        product["split_role"] = "held_out_test"
        manifest_dict = _make_manifest([product])
        frozen_route = {
            "route_id": "fitted-route",
            "route_version": "1",
            "parameter_snapshot": {"threshold": 0.5},
        }
        provenance = {
            "schema_version": "1.0.0",
            "source_manifest_id": manifest_dict["manifest_id"],
            "source_manifest_sha256": digest_json(manifest_dict),
            "frozen_route_snapshot_sha256": digest_json(frozen_route),
            "inputs": [{"product_id": "sync-fit-held-out", "split_role": "held_out_test"}],
        }
        provenance["fit_id"] = "pfp-sha256-" + digest_json(provenance)
        checkpoint = {
            "checkpoint_id": "icp-sha256-" + "a" * 64,
            "scene_product_id": "sync-fit-held-out",
            "status": "unresolved",
            "status_reason": "Fixture only.",
        }

        with pytest.raises(FitProvenanceError, match="development/validation"):
            runner.run_benchmark(
                manifest_dict,
                frozen_route=frozen_route,
                parameter_fit_provenance=provenance,
                held_out_checkpoints=(checkpoint,),
            )

    def test_route_mutation_cannot_change_frozen_split_population(self) -> None:
        product = _make_source_product("sync-route-mutation")
        product["split_role"] = "held_out_test"
        checkpoint = {
            "checkpoint_id": "icp-sha256-" + "c" * 64,
            "scene_product_id": "sync-route-mutation",
            "status": "unresolved",
            "status_reason": "Fixture only.",
        }

        def mutating_route(route_product: dict[str, Any]) -> StageResult:
            route_product["split_role"] = "train_development"
            return StageResult(
                stage_name=f"benchmark_scene:{route_product['product_id']}",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
            )

        report = runner.run_benchmark(
            _make_manifest([product]), route=mutating_route, held_out_checkpoints=(checkpoint,)
        )

        assert report.to_document()["scene_results"][0]["split_role"] == "held_out_test"

    def test_report_freezes_caller_owned_evidence_records(self) -> None:
        checkpoints = [{"checkpoint_id": "icp-sha256-" + "d" * 64, "status": "excluded"}]
        context = {"nested": {"value": 1}}
        report = runner.BenchmarkRunReport(
            manifest_id="immutable-fixture",
            manifest_sha256_value="e" * 64,
            scene_results=(),
            held_out_checkpoints=tuple(checkpoints),
            run_context=context,
        )
        before = report.to_document()
        checkpoints[0]["status"] = "accepted"
        context["nested"]["value"] = 2

        assert report.to_document() == before

    def test_readdressed_report_cannot_omit_a_held_out_checkpoint(self) -> None:
        product = _make_source_product("sync-omitted-checkpoint")
        product["split_role"] = "held_out_test"
        checkpoint = {
            "checkpoint_id": "icp-sha256-" + "e" * 64,
            "scene_product_id": "sync-omitted-checkpoint",
            "status": "unresolved",
            "status_reason": "Fixture only.",
        }
        report = runner.run_benchmark(_make_manifest([product]), held_out_checkpoints=(checkpoint,))
        document = report.to_document()
        document["held_out_checkpoints"] = []
        document["summary"]["held_out_checkpoint_population"] = {
            "total": 0,
            "accepted": 0,
            "excluded": 0,
            "unresolved": 0,
        }
        document["run_report_id"] = "brr-sha256-" + digest_json(
            {key: value for key, value in document.items() if key != "run_report_id"}
        )

        with pytest.raises(ValueError, match="exactly one checkpoint"):
            runner.validate_report_document(document)

    def test_run_benchmark_non_source_products_ignored(self) -> None:
        """Non-source products (terrain, reference) are not run."""
        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-001"),
                _make_source_product("sync-002"),
                _make_terrain_product("sync-terrain-ref"),
                _make_image_reference_product("sync-image-ref"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict)

        # Only source products should be in scene_results
        assert report.total_scenes == 2
        assert len(report.scene_results) == 2
        product_ids = {sr.product_id for sr in report.scene_results}
        assert product_ids == {"sync-001", "sync-002"}
        assert "sync-terrain-ref" not in product_ids
        assert "sync-image-ref" not in product_ids

    def test_run_benchmark_custom_route_mixed_outcomes(self) -> None:
        """Custom route with mixed outcomes processes all scenes."""

        def custom_route(product: dict[str, Any]) -> StageResult:
            if product["product_id"] == "sync-001":
                # Return a successful result
                return StageResult(
                    stage_name=f"benchmark_scene:{product['product_id']}",
                    stage_version="1",
                    outcome=StageOutcome.SUCCEEDED,
                )
            else:
                # Return a rejection with a different code
                return StageResult(
                    stage_name=f"benchmark_scene:{product['product_id']}",
                    stage_version="1",
                    outcome=StageOutcome.REJECTED,
                    failure=StageFailure(
                        code=FailureCode.GEOMETRY_NO_OVERLAP,
                        message="Source and reference do not overlap.",
                        context={"product_id": product["product_id"]},
                    ),
                )

        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-001"),
                _make_source_product("sync-002"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict, route=custom_route)

        # Both scenes should be present
        assert report.total_scenes == 2
        assert len(report.scene_results) == 2
        assert report.succeeded == 1
        assert report.rejected == 1
        assert report.failed == 0

        # Verify the actual outcomes
        results_by_id = {sr.product_id: sr.result for sr in report.scene_results}
        assert results_by_id["sync-001"].outcome == StageOutcome.SUCCEEDED
        assert results_by_id["sync-002"].outcome == StageOutcome.REJECTED

    def test_run_benchmark_route_exception_caught(self) -> None:
        """Route exceptions are caught and converted to FAILED results."""

        def failing_route(product: dict[str, Any]) -> StageResult:
            if product["product_id"] == "sync-002":
                raise ValueError("Synthetic test error in route")
            return StageResult(
                stage_name=f"benchmark_scene:{product['product_id']}",
                stage_version="1",
                outcome=StageOutcome.SUCCEEDED,
            )

        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-001"),
                _make_source_product("sync-002"),
                _make_source_product("sync-003"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict, route=failing_route)

        # All three scenes should still be present
        assert report.total_scenes == 3
        assert len(report.scene_results) == 3

        # Check outcomes
        results_by_id = {sr.product_id: sr.result for sr in report.scene_results}
        assert results_by_id["sync-001"].outcome == StageOutcome.SUCCEEDED
        assert results_by_id["sync-002"].outcome == StageOutcome.FAILED
        assert results_by_id["sync-003"].outcome == StageOutcome.SUCCEEDED

        # Verify the failed result captures the exception
        failed_result = results_by_id["sync-002"]
        assert failed_result.failure is not None
        assert failed_result.failure.code == FailureCode.INTERNAL_UNEXPECTED_ERROR
        assert "ValueError" in failed_result.failure.message
        assert "Synthetic test error in route" in failed_result.failure.message

        # Verify counts
        assert report.succeeded == 2
        assert report.failed == 1
        assert report.rejected == 0
        assert report.cancelled == 0

    def test_run_benchmark_empty_source_products(self) -> None:
        """A manifest with no source products returns empty report."""
        manifest_dict = _make_manifest(
            [
                _make_terrain_product("sync-terrain-ref"),
                _make_image_reference_product("sync-image-ref"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict)

        assert report.total_scenes == 0
        assert len(report.scene_results) == 0
        assert report.succeeded == 0
        assert report.failed == 0
        assert report.rejected == 0
        assert report.cancelled == 0

    def test_run_benchmark_stage_result_schema_validation(self) -> None:
        """Every scene result validates against stage-result schema."""

        def custom_route(product: dict[str, Any]) -> StageResult:
            if product["product_id"] == "sync-001":
                return StageResult(
                    stage_name=f"benchmark_scene:{product['product_id']}",
                    stage_version="1",
                    outcome=StageOutcome.SUCCEEDED,
                )
            else:
                return StageResult(
                    stage_name=f"benchmark_scene:{product['product_id']}",
                    stage_version="1",
                    outcome=StageOutcome.REJECTED,
                    failure=StageFailure(
                        code=FailureCode.GEOMETRY_NO_OVERLAP,
                        message="No overlap.",
                        context={"product_id": product["product_id"]},
                    ),
                )

        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-001"),
                _make_source_product("sync-002"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict, route=custom_route)

        # Validate each scene result against the schema
        for scene_result in report.scene_results:
            _validate_stage_result_schema(scene_result.result)

    def test_run_benchmark_default_route_schema_validation(self) -> None:
        """Default route results validate against stage-result schema."""
        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-001"),
                _make_source_product("sync-002"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict)  # No route, uses default

        # Validate each scene result against the schema
        for scene_result in report.scene_results:
            _validate_stage_result_schema(scene_result.result)

    def test_run_benchmark_manifest_id_preserved(self) -> None:
        """Manifest ID is correctly included in the report."""
        manifest_dict = _make_manifest([_make_source_product("sync-001")])
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict)

        assert report.manifest_id == "sync-benchmark-manifest"

    def test_run_benchmark_scene_results_ordered(self) -> None:
        """Scene results are in the same order as manifest products."""
        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-prod-a"),
                _make_source_product("sync-prod-b"),
                _make_source_product("sync-prod-c"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict)

        product_ids = [sr.product_id for sr in report.scene_results]
        assert product_ids == ["sync-prod-a", "sync-prod-b", "sync-prod-c"]

    def test_run_benchmark_counts_never_negative(self) -> None:
        """All counts are non-negative and sum correctly."""

        def custom_route(product: dict[str, Any]) -> StageResult:
            # Mix of different outcomes
            pid = product["product_id"]
            if pid == "sync-001":
                return StageResult(
                    stage_name=f"benchmark_scene:{pid}",
                    stage_version="1",
                    outcome=StageOutcome.SUCCEEDED,
                )
            elif pid == "sync-002":
                return StageResult(
                    stage_name=f"benchmark_scene:{pid}",
                    stage_version="1",
                    outcome=StageOutcome.REJECTED,
                    failure=StageFailure(
                        code=FailureCode.GEOMETRY_NO_OVERLAP,
                        message="No overlap.",
                        context={"product_id": pid},
                    ),
                )
            elif pid == "sync-003":
                return StageResult(
                    stage_name=f"benchmark_scene:{pid}",
                    stage_version="1",
                    outcome=StageOutcome.CANCELLED,
                    failure=StageFailure(
                        code=FailureCode.INTERNAL_CANCELLED,
                        message="Cancelled cooperatively.",
                        context={"product_id": pid},
                    ),
                )
            else:
                raise RuntimeError("Unexpected product")

        manifest_dict = _make_manifest(
            [
                _make_source_product("sync-001"),
                _make_source_product("sync-002"),
                _make_source_product("sync-003"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        report = runner.run_benchmark(manifest_dict, route=custom_route)

        # All counts should be non-negative
        assert report.total_scenes >= 0
        assert report.succeeded >= 0
        assert report.rejected >= 0
        assert report.failed >= 0
        assert report.cancelled >= 0

        # Counts should sum correctly
        total_counted = report.succeeded + report.rejected + report.failed + report.cancelled
        assert total_counted == report.total_scenes
