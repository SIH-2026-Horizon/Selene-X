"""Tests for benchmark split-role and terrain-group leakage detector.

Every fixture manifest in this module is validated against the benchmark
manifest JSON schema before use, so drifting fixtures are caught as schema
violations, not silently assumed valid.
"""

from __future__ import annotations

from datetime import UTC, datetime

import jsonschema
import pytest
from benchmarks.scripts import leakage_check, manifest

pytestmark = pytest.mark.unit


def _make_product(
    product_id: str,
    split_role: str,
    terrain_group: str | None = None,
) -> dict[str, object]:
    """Helper to create a minimal valid product entry for testing."""
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
        "split_role": split_role,
        "terrain_group": terrain_group,
        "stress_bins": {},
        "control_uncertainty_m": None,
        "control_uncertainty_reason": "synthetic fixture, not applicable",
        "warnings": [],
    }


def _make_manifest(products: list[dict[str, object]]) -> dict[str, object]:
    """Create a minimal valid manifest containing the given products."""
    return {
        "schema_version": "1.0.0",
        "manifest_id": "sync-f-manifest",
        "interim": True,
        "created_utc": datetime.now(UTC).isoformat(),
        "products": products,
    }


def _validate_manifest_schema(manifest_dict: dict[str, object]) -> None:
    """Validate a fixture manifest against the benchmark manifest schema.

    Raises jsonschema.ValidationError if the manifest does not conform to
    the schema, so drifting fixtures are caught immediately.
    """
    schema = manifest.load_schema()
    jsonschema.validate(manifest_dict, schema)


class TestNoLeakage:
    """Leakage checker returns empty tuple when there is no leakage."""

    def test_all_distinct_terrain_groups(self) -> None:
        """Different products with distinct terrain groups do not leak."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "validation", "sync-tg-b"),
                _make_product("sync-f-003", "held_out_test", "sync-tg-c"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert violations == ()

    def test_same_terrain_group_same_split(self) -> None:
        """Two products sharing a terrain group in the same split do not leak."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "train_development", "sync-tg-a"),
                _make_product("sync-f-003", "validation", "sync-tg-b"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert violations == ()

    def test_all_null_terrain_groups(self) -> None:
        """Products with null terrain_group do not leak, regardless of split role."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "train_development", None),
                _make_product("sync-f-002", "train_development", None),
                _make_product("sync-f-003", "validation", None),
                _make_product("sync-f-004", "held_out_test", None),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert violations == ()


class TestSingleLeakage:
    """Leakage checker detects and reports a single terrain group leak."""

    def test_two_protected_splits(self) -> None:
        """A terrain group appearing in two different protected splits is flagged."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "held_out_test", "sync-tg-a"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 1
        violation = violations[0]
        assert violation.terrain_group == "sync-tg-a"
        assert violation.split_roles == {"train_development", "held_out_test"}
        assert violation.product_ids == {"sync-f-001", "sync-f-002"}

    def test_three_protected_splits(self) -> None:
        """A terrain group spanning all three protected splits is one violation."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "validation", "sync-tg-a"),
                _make_product("sync-f-003", "held_out_test", "sync-tg-a"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 1
        violation = violations[0]
        assert violation.terrain_group == "sync-tg-a"
        assert violation.split_roles == {"train_development", "validation", "held_out_test"}
        assert violation.product_ids == {
            "sync-f-001",
            "sync-f-002",
            "sync-f-003",
        }

    def test_multiple_products_per_split(self) -> None:
        """Leakage with multiple products per split is reported correctly."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "train_development", "sync-tg-a"),
                _make_product("sync-f-003", "validation", "sync-tg-a"),
                _make_product("sync-f-004", "validation", "sync-tg-a"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 1
        violation = violations[0]
        assert violation.terrain_group == "sync-tg-a"
        assert violation.split_roles == {"train_development", "validation"}
        assert violation.product_ids == {
            "sync-f-001",
            "sync-f-002",
            "sync-f-003",
            "sync-f-004",
        }


class TestNotApplicableHandling:
    """Leakage checker handles split_role: not_applicable correctly.

    Products with split_role: not_applicable (e.g., terrain references or
    control benchmarks) are not considered protected splits. They group with
    terrain_group but do not trigger leakage by themselves. Rationale:
    not_applicable products are outside the formal train/validation/held-out
    pipeline and represent reference or control data that is intended to be
    independent of the data splits. Allowing them to coexist in a terrain_group
    with protected-split products does not constitute leakage, since the
    not_applicable product is not part of the protected boundary system.
    """

    def test_not_applicable_alone_no_leak(self) -> None:
        """A terrain group with only not_applicable products does not leak."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "not_applicable", "sync-tg-a"),
                _make_product("sync-f-002", "not_applicable", "sync-tg-a"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert violations == ()

    def test_not_applicable_with_one_protected_split_no_leak(self) -> None:
        """not_applicable products can coexist with one protected split without leaking.

        A terrain group with split_role: not_applicable and split_role:
        train_development does not leak because only one protected split is
        present. The not_applicable product is reference/control data, not a
        training or evaluation product.
        """
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "not_applicable", "sync-tg-a"),
                _make_product("sync-f-002", "train_development", "sync-tg-a"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert violations == ()

    def test_not_applicable_with_multiple_protected_splits_leaks(self) -> None:
        """not_applicable is excluded from violation but other splits still leak.

        A terrain group with split_role: not_applicable, train_development,
        and validation still leaks because train_development and validation
        are distinct protected splits. The not_applicable product does not
        prevent the violation; it just is not counted in the violation's
        split_roles.
        """
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "not_applicable", "sync-tg-a"),
                _make_product("sync-f-002", "train_development", "sync-tg-a"),
                _make_product("sync-f-003", "validation", "sync-tg-a"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 1
        violation = violations[0]
        assert violation.terrain_group == "sync-tg-a"
        # only protected splits are in split_roles
        assert violation.split_roles == {"train_development", "validation"}
        # only products with protected split_role are in product_ids
        assert violation.product_ids == {"sync-f-002", "sync-f-003"}


class TestMultipleLeaks:
    """Leakage checker detects multiple independent terrain group leaks."""

    def test_two_independent_leaking_terrain_groups(self) -> None:
        """Two independent terrain groups leaking separately are both reported."""
        manifest_dict = _make_manifest(
            [
                # Leaking group A
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "validation", "sync-tg-a"),
                # Leaking group B
                _make_product("sync-f-003", "train_development", "sync-tg-b"),
                _make_product("sync-f-004", "held_out_test", "sync-tg-b"),
                # Non-leaking group C
                _make_product("sync-f-005", "validation", "sync-tg-c"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 2
        # Violations are in manifest order (group A first, then group B)
        assert violations[0].terrain_group == "sync-tg-a"
        assert violations[1].terrain_group == "sync-tg-b"
        # Each violation is independent
        assert violations[0].product_ids == {"sync-f-001", "sync-f-002"}
        assert violations[1].product_ids == {"sync-f-003", "sync-f-004"}
        # No cross-contamination
        assert len(violations[0].split_roles) == 2
        assert len(violations[1].split_roles) == 2

    def test_three_independent_leaking_terrain_groups(self) -> None:
        """Three independent terrain groups leaking are all reported."""
        manifest_dict = _make_manifest(
            [
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "validation", "sync-tg-a"),
                _make_product("sync-f-003", "train_development", "sync-tg-b"),
                _make_product("sync-f-004", "held_out_test", "sync-tg-b"),
                _make_product("sync-f-005", "validation", "sync-tg-c"),
                _make_product("sync-f-006", "held_out_test", "sync-tg-c"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 3
        terrain_groups = {v.terrain_group for v in violations}
        assert terrain_groups == {
            "sync-tg-a",
            "sync-tg-b",
            "sync-tg-c",
        }


class TestMixedScenarios:
    """Leakage checker handles complex mixed scenarios correctly."""

    def test_mixed_leaking_and_nonleaking_groups(self) -> None:
        """Manifest with both leaking and non-leaking terrain groups."""
        manifest_dict = _make_manifest(
            [
                # Leaking
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "validation", "sync-tg-a"),
                # Non-leaking: same group, same split
                _make_product("sync-f-003", "train_development", "sync-tg-b"),
                _make_product("sync-f-004", "train_development", "sync-tg-b"),
                # Non-leaking: null group
                _make_product("sync-f-005", "train_development", None),
                _make_product("sync-f-006", "validation", None),
                # Non-leaking: distinct groups
                _make_product("sync-f-007", "validation", "sync-tg-c"),
                _make_product("sync-f-008", "held_out_test", "sync-tg-d"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 1
        assert violations[0].terrain_group == "sync-tg-a"
        assert violations[0].product_ids == {"sync-f-001", "sync-f-002"}

    def test_complex_scenario_with_not_applicable(self) -> None:
        """Complex scenario mixing protected splits and not_applicable."""
        manifest_dict = _make_manifest(
            [
                # Group A: leaking between train and validation
                _make_product("sync-f-001", "train_development", "sync-tg-a"),
                _make_product("sync-f-002", "validation", "sync-tg-a"),
                # Group B: not_applicable alone, non-leaking
                _make_product("sync-f-003", "not_applicable", "sync-tg-b"),
                # Group C: not_applicable with one protected split, non-leaking
                _make_product("sync-f-004", "not_applicable", "sync-tg-c"),
                _make_product("sync-f-005", "held_out_test", "sync-tg-c"),
                # Group D: three products, two protected splits, leaking
                _make_product("sync-f-006", "train_development", "sync-tg-d"),
                _make_product("sync-f-007", "held_out_test", "sync-tg-d"),
                _make_product("sync-f-008", "held_out_test", "sync-tg-d"),
            ]
        )
        _validate_manifest_schema(manifest_dict)

        violations = leakage_check.check_split_leakage(manifest_dict)

        assert len(violations) == 2
        # Group A leaks
        assert violations[0].terrain_group == "sync-tg-a"
        assert violations[0].product_ids == {"sync-f-001", "sync-f-002"}
        # Group D leaks
        assert violations[1].terrain_group == "sync-tg-d"
        assert violations[1].product_ids == {"sync-f-006", "sync-f-007", "sync-f-008"}


class TestManifestValidation:
    """Fixture manifests are validated against the JSON schema."""

    def test_fixture_manifests_are_schema_valid(self) -> None:
        """All fixture manifests used in tests conform to the benchmark schema.

        This test serves as a canary: if a fixture drifts from the schema, it
        will fail here rather than silently in other tests.
        """
        schema = manifest.load_schema()

        # Sample manifests from various test scenarios
        manifests_to_check = [
            _make_manifest(
                [
                    _make_product("sync-f-001", "train_development", "sync-tg-a"),
                ]
            ),
            _make_manifest(
                [
                    _make_product("sync-f-001", "train_development", None),
                    _make_product("sync-f-002", "not_applicable", "sync-tg-a"),
                ]
            ),
            _make_manifest(
                [
                    _make_product("sync-f-001", "train_development", "sync-tg-a"),
                    _make_product("sync-f-002", "validation", "sync-tg-a"),
                    _make_product("sync-f-003", "held_out_test", "sync-tg-a"),
                ]
            ),
        ]

        for test_manifest in manifests_to_check:
            # Should not raise
            jsonschema.validate(test_manifest, schema)
