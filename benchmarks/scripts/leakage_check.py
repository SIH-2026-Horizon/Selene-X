"""Benchmark split-role and terrain-group leakage detector (WP-00 tasks 4/5).

A benchmark's train/validation/held-out-test splits are protected boundaries:
spatially related crops, repeated acquisitions, and products from the same
local terrain group must stay in one split to prevent geographic leakage
(plan WP-00 task 4). This module operates on an already-loaded, already
schema-valid manifest dict (output of ``manifest.load_manifest``) and checks
whether any terrain group has leaked across these protected splits.

A terrain group with ``split_role: not_applicable`` (e.g. control references,
terrain references, or products outside the formal train/validation/held-out
pipeline) does not count as a protected split for this check. Only
``train_development``, ``validation``, and ``held_out_test`` are considered
protected boundaries against leakage. Products with ``terrain_group: null``
are skipped — the absence of a terrain group is not evidence of leakage, it
is simply a data point we cannot check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "SplitIntegrityError",
    "SplitLeakageViolation",
    "check_split_leakage",
    "validate_split_integrity",
]

# The set of split roles that are protected boundaries for leakage checking.
# Products with these split_role values must not share a terrain_group with
# products in a different protected split.
_PROTECTED_SPLITS = frozenset(["train_development", "validation", "held_out_test"])


class SplitIntegrityError(ValueError):
    """Raised when a source split cannot be proven geographically isolated."""


@dataclass(frozen=True, slots=True)
class SplitLeakageViolation:
    """A terrain group leaked across protected splits.

    Records which terrain group violated the constraint, the set of protected
    split roles it appeared under, and the product IDs involved so a human
    can investigate and resolve the issue.
    """

    terrain_group: str
    """The terrain group name that leaked."""

    split_roles: frozenset[str]
    """The distinct protected split roles this terrain group appeared under.

    If this set has size >= 2, the leakage is clear: products from one split
    share a terrain group with products from another. The violation is emitted
    once per terrain group, regardless of whether the split_roles set is
    {train_development, validation}, {train_development, held_out_test}, or
    all three.
    """

    product_ids: frozenset[str]
    """The product IDs sharing this terrain group across protected splits.

    Includes only products whose split_role is in the protected set; products
    with split_role: not_applicable are excluded from the violation report
    (their presence does not trigger a violation on its own, though they are
    part of the same terrain group).
    """


def check_split_leakage(manifest: dict[str, Any]) -> tuple[SplitLeakageViolation, ...]:
    """Check whether any terrain group leaked across protected splits.

    Args:
        manifest: A manifest dict already validated by ``manifest.load_manifest``
            (this function trusts its shape: it does not re-run schema
            validation).

    Returns:
        A tuple of violations, one per terrain group that appeared under more
        than one distinct protected split role. Returns an empty tuple if
        there is no leakage.

        Violations are emitted in the order terrain groups are first
        encountered (manifest order), so results are deterministic.

    Raises:
        No exceptions — this is a reporting function, not a validating gate.
        Callers decide whether to act on the returned violations.
    """
    # Group products by terrain_group, tracking split_roles and product_ids
    # per group. Only process terrain groups that are not null.
    leakage_map: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    # Track order of first appearance for deterministic results.
    group_order: list[str] = []

    for product in manifest["products"]:
        terrain_group: str | None = product.get("terrain_group")

        # Skip products with no terrain group — absence of information is not
        # evidence of leakage.
        if terrain_group is None:
            continue

        split_role: str = product["split_role"]
        product_id: str = product["product_id"]

        if terrain_group not in leakage_map:
            group_order.append(terrain_group)
            leakage_map[terrain_group] = (frozenset(), frozenset())

        current_splits, current_products = leakage_map[terrain_group]

        # Only track split_roles and product_ids if this product is in a
        # protected split. Products with split_role: not_applicable are
        # grouped by terrain_group but not counted for leakage purposes.
        if split_role in _PROTECTED_SPLITS:
            current_splits = current_splits | {split_role}
            current_products = current_products | {product_id}

        leakage_map[terrain_group] = (current_splits, current_products)

    # Emit a violation for each terrain group that spans 2+ protected splits.
    violations: list[SplitLeakageViolation] = []
    for terrain_group in group_order:
        splits, products = leakage_map[terrain_group]
        # Only flag if we have 2+ distinct protected splits. If a terrain group
        # only appears in one protected split (or only in not_applicable), no
        # violation.
        if len(splits) >= 2:
            violations.append(
                SplitLeakageViolation(
                    terrain_group=terrain_group,
                    split_roles=splits,
                    product_ids=products,
                )
            )

    return tuple(violations)


def validate_split_integrity(manifest: dict[str, Any]) -> None:
    """Enforce spatial grouping and separation for every protected source scene.

    This is intentionally stricter than :func:`check_split_leakage`, which is
    also useful as a diagnostic on incomplete incoming metadata.  A frozen
    benchmark manifest, however, cannot claim split isolation without a
    terrain group for every source scene in a protected split.
    """
    product_ids = [product["product_id"] for product in manifest["products"]]
    if len(product_ids) != len(set(product_ids)):
        raise SplitIntegrityError("product_id values must be unique within a benchmark manifest")

    ungrouped = [
        product["product_id"]
        for product in manifest["products"]
        if product["role"] == "source"
        and product["split_role"] in _PROTECTED_SPLITS
        and not product.get("terrain_group")
    ]
    if ungrouped:
        rendered_ids = ", ".join(ungrouped)
        raise SplitIntegrityError(
            "protected source products require a non-empty terrain_group: " + rendered_ids
        )

    violations = check_split_leakage(manifest)
    if violations:
        rendered_groups = ", ".join(violation.terrain_group for violation in violations)
        raise SplitIntegrityError(
            "terrain groups span protected benchmark splits: " + rendered_groups
        )
