"""Scene verdict engine and immutable review records (plan sections 8 and 10;
ADR-010; WP-09 tasks 9-11).

**Scope ruling (read before extending this module).** Most of WP-09 needs
``rasterio``/GDAL and real WP-03 geometry, neither of which exists in this
repository. This module is the part of WP-09 that does not: it is pure
decision logic over already-computed evidence (:class:`CorrespondenceRecord`
from :mod:`selene_core.match.correspondence`, :class:`CoverageMetrics` from
:mod:`selene_core.select.coverage`). It never reads a raster, never computes
geometry, and never decides whether an algorithm/parameter/reference version
has passed a real frozen-benchmark evaluation — that decision
(``route_qualified``) is always supplied as an external input, the same
pattern this branch's ``MatchPrior``/``EligibilityGrid``/``reverse_records``
used throughout for "the real version of this doesn't exist yet, so it's a
parameter."

Gate thresholds are explicitly provisional (plan: they "must not be frozen as
final challenge thresholds until D-001 and D-007 are resolved"), so this
engine takes gate definitions as **data** — a list of caller-supplied
:class:`GateSpec` values with named thresholds — and never hardcodes a
specific numeric threshold as if it were final.

The 8 verdict rules this module implements (transcribed from plan section
10; each rule is cited by number at its enforcement point below):

1. Evaluate applicability first; a metric is not applicable only for a
   documented scientific reason.
2. A missing applicable hard-gate metric is a rejection, not a pass.
3. A user scene without independent control may receive a scene verdict only
   through a currently qualified route and scene-observable gates; it
   cannot acquire a scene-specific independent-accuracy claim.
4. A result based only on internal fit residuals cannot pass a route
   independent-accuracy gate.
5. A synthetic result cannot pass a real-data route gate.
6. An absolute metre claim cannot pass without named control uncertainty.
7. A human review can qualify use but cannot rewrite measured values, the
   computed verdict, or a failed route gate.
8. Aggregate success rate includes rejected and failed inputs according to
   the declared benchmark population. **Out of scope here** — rule 8 is
   about cross-scene aggregate reporting; this module computes ONE scene's
   verdict.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Literal

from pydantic import model_validator

from selene_core.contracts import Contract
from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.select.coverage import CoverageMetrics

__all__ = [
    "GateKind",
    "GateResult",
    "GateSpec",
    "ReviewRecord",
    "SceneEvidence",
    "SceneVerdict",
    "compute_scene_verdict",
    "derive_scene_metrics",
    "effective_disposition",
    "evaluate_gate",
]


_COMPARISON_SYMBOLS: Final[Mapping[str, str]] = {"lt": "<", "le": "<=", "gt": ">", "ge": ">="}


class GateKind(StrEnum):
    """How a failing or inapplicable-but-required gate affects the verdict."""

    HARD = "hard"
    """A failing or missing-applicable metric blocks ``accept`` entirely
    (rule 2) — the scene is rejected."""

    SOFT = "soft"
    """A failing or missing-applicable metric forces ``review``, never a
    silent ``accept``, but does not by itself force ``reject``."""


@dataclass(frozen=True, slots=True)
class GateSpec:
    """One configurable quality gate. Gate *definitions* are caller-supplied
    data, never a hardcoded module-level policy — see this module's
    docstring on why thresholds stay provisional.

    ``route_qualification_only`` and ``requires_independent_control`` and
    ``requires_absolute_control_uncertainty`` each encode one of rules 3, 5,
    6 as an applicability precondition evaluated by :func:`evaluate_gate`
    before any threshold comparison happens (rule 1).
    """

    name: str
    kind: GateKind
    metric_name: str
    """Key into :attr:`SceneEvidence.metrics`."""
    comparison: Literal["lt", "le", "gt", "ge"]
    threshold: float
    route_qualification_only: bool = False
    """Rule 5: this gate is a real-data route claim. Applicability is
    ``False`` whenever ``SceneEvidence.is_synthetic`` — a synthetic scene can
    never satisfy it."""
    requires_independent_control: bool = False
    """Rules 3-4: this gate claims independent/withheld-point accuracy.
    Applicability is ``False`` whenever
    ``SceneEvidence.has_independent_control`` is ``False``.

    Rule 4 ("a result based only on internal fit residuals cannot pass a
    route independent-accuracy gate") is enforced by naming convention, not
    a runtime type distinction: any metric meant to satisfy a gate with this
    flag set must be computed ONLY from ``PointRole.WITHHELD_CHECK_POINT``
    records, never ``FITTING_INLIER``/``TRAINING`` — see
    :func:`derive_scene_metrics`'s ``"withheld_rmse_2d_px"``, which is
    constructed so that it structurally cannot draw from fit-role records."""
    requires_absolute_control_uncertainty: bool = False
    """Rule 6: this gate is an absolute-metre claim. Applicability is
    ``False`` whenever ``SceneEvidence.control_uncertainty_m is None``."""


@dataclass(frozen=True, slots=True)
class SceneEvidence:
    """Already-computed evidence for one scene, gathered from upstream
    stages. The gate engine never reads a :class:`CorrespondenceRecord` or
    :class:`CoverageMetrics` directly — only this dataclass's ``metrics``
    mapping — so it stays metric-source-agnostic; :func:`derive_scene_metrics`
    is the (optional) bridge from raw records to this mapping.
    """

    route_qualified: bool
    route_id: str
    is_synthetic: bool
    has_independent_control: bool
    control_uncertainty_m: float | None
    metrics: Mapping[str, float | None]
    """Named metric values. ``None`` means "this metric could not be
    computed" — per this project's universal null-with-reason rule, never a
    fabricated ``0.0``."""


class GateResult(Contract):
    """Per-gate observed value, threshold, applicability, pass state, and
    evidence source (plan section 6.6)."""

    name: str
    metric_name: str
    observed_value: float | None
    threshold: float
    comparison: str
    kind: GateKind
    applicable: bool
    applicability_reason: str | None = None
    """Non-``None`` exactly when ``applicable`` is ``False`` — validated
    below, not just documented."""
    passed: bool | None = None
    """``None`` when ``applicable`` is ``False``. Otherwise ``True``/
    ``False`` — a missing metric on an applicable gate is ``passed=False``
    (rule 2), never ``None`` masking a real gap. Validated below."""
    evidence_source: str

    @model_validator(mode="after")
    def _check_applicability_pairings(self) -> GateResult:
        if self.applicable and self.applicability_reason is not None:
            raise ValueError(
                "GateResult.applicability_reason must be None when applicable=True; a "
                "reason documents an inapplicability, and this gate is applicable"
            )
        if not self.applicable and self.applicability_reason is None:
            raise ValueError(
                "GateResult.applicability_reason must be set (non-None) when "
                "applicable=False; a metric is inapplicable only for a documented "
                "reason (rule 1)"
            )
        if not self.applicable and self.passed is not None:
            raise ValueError(
                "GateResult.passed must be None when applicable=False; an inapplicable "
                "gate has no pass/fail outcome to report"
            )
        if self.applicable and self.passed is None:
            raise ValueError(
                "GateResult.passed must be True or False when applicable=True; a "
                "missing applicable metric is passed=False (rule 2), never a None "
                "masking a real gap"
            )
        return self


def _compare(
    observed: float, comparison: Literal["lt", "le", "gt", "ge"], threshold: float
) -> bool:
    if comparison == "lt":
        return observed < threshold
    if comparison == "le":
        return observed <= threshold
    if comparison == "gt":
        return observed > threshold
    if comparison == "ge":
        return observed >= threshold
    raise ValueError(f"unknown comparison {comparison!r}")  # pragma: no cover — Literal-exhausted


def evaluate_gate(spec: GateSpec, evidence: SceneEvidence) -> GateResult:
    """Evaluate one :class:`GateSpec` against one scene's :class:`SceneEvidence`.

    Applicability is decided FIRST (rule 1), strictly before any metric value
    is consulted for pass/fail purposes — this ordering is what rule 3's test
    proves: a gate can be inapplicable even when ``evidence.metrics`` happens
    to hold a value for its ``metric_name``. The applicability checks run in
    this order (matching the plan's rule numbering, not because later checks
    depend on earlier ones):

    1. ``route_qualification_only`` and ``evidence.is_synthetic`` (rule 5).
    2. ``requires_independent_control`` and not
       ``evidence.has_independent_control`` (rule 3).
    3. ``requires_absolute_control_uncertainty`` and
       ``evidence.control_uncertainty_m is None`` (rule 6).

    Only if the gate is applicable does the metric value get looked up and
    compared. A missing value (``None``) on an applicable gate is
    ``passed=False`` for BOTH ``HARD`` and ``SOFT`` kinds (rule 2) — a
    ``SOFT`` gate that cannot be evaluated is not silently treated as
    passing; it simply does not, by itself, force ``reject`` (that is
    :func:`compute_scene_verdict`'s job, not this function's).
    """
    observed_value = evidence.metrics.get(spec.metric_name)

    if spec.route_qualification_only and evidence.is_synthetic:
        return GateResult(
            name=spec.name,
            metric_name=spec.metric_name,
            observed_value=observed_value,
            threshold=spec.threshold,
            comparison=spec.comparison,
            kind=spec.kind,
            applicable=False,
            applicability_reason=(
                "route-qualification-only gate; scene is synthetic and a synthetic "
                "result cannot pass a real-data route gate (rule 5)"
            ),
            passed=None,
            evidence_source="scene_observed",
        )

    if spec.requires_independent_control and not evidence.has_independent_control:
        return GateResult(
            name=spec.name,
            metric_name=spec.metric_name,
            observed_value=observed_value,
            threshold=spec.threshold,
            comparison=spec.comparison,
            kind=spec.kind,
            applicable=False,
            applicability_reason=(
                "gate requires independent/withheld-point control; this scene has none, "
                "so it cannot acquire a scene-specific independent-accuracy claim "
                "(rule 3)"
            ),
            passed=None,
            evidence_source="scene_observed",
        )

    if spec.requires_absolute_control_uncertainty and evidence.control_uncertainty_m is None:
        return GateResult(
            name=spec.name,
            metric_name=spec.metric_name,
            observed_value=observed_value,
            threshold=spec.threshold,
            comparison=spec.comparison,
            kind=spec.kind,
            applicable=False,
            applicability_reason=(
                "gate is an absolute-metre claim requiring named control uncertainty; "
                "none was provided (rule 6)"
            ),
            passed=None,
            evidence_source="scene_observed",
        )

    if observed_value is None:
        passed = False  # rule 2: a missing applicable metric is a rejection input, not a pass
    else:
        passed = _compare(observed_value, spec.comparison, spec.threshold)

    return GateResult(
        name=spec.name,
        metric_name=spec.metric_name,
        observed_value=observed_value,
        threshold=spec.threshold,
        comparison=spec.comparison,
        kind=spec.kind,
        applicable=True,
        applicability_reason=None,
        passed=passed,
        evidence_source="scene_observed",
    )


class SceneVerdict(Contract):
    """The immutable computed verdict for one scene."""

    verdict: Literal["accept", "review", "reject"]
    route_id: str
    gate_results: tuple[GateResult, ...]
    computed_utc: datetime
    reason: str
    """Names the specific gate(s) that drove the outcome, e.g. "route not
    qualified" or "hard gate 'eligible_occupancy' failed: 0.42 < 0.70" or
    "all applicable gates passed"."""


def compute_scene_verdict(
    gate_results: tuple[GateResult, ...],
    *,
    route_qualified: bool,
    route_id: str,
    clock: Callable[[], datetime] | None = None,
) -> SceneVerdict:
    """Combine pre-evaluated :class:`GateResult` values into one
    :class:`SceneVerdict`.

    ``clock`` defaults to ``lambda: datetime.now(tz=UTC)`` and is injectable
    for deterministic tests — the same convention as
    ``selene_core.pipeline.runner.StageRunner``'s ``clock`` parameter;
    ``datetime.now()`` is never called directly without this indirection.

    Decision order:

    1. ``not route_qualified`` -> ``"reject"``. Checked first and
       independently of every gate result: an unqualified route rejects the
       scene regardless of what the gates say (rule 3's "only through a
       currently qualified route").
    2. Among APPLICABLE gates only (inapplicable gates never drive the
       outcome — an inapplicable gate is not a failing gate): any
       ``kind=HARD`` gate with ``passed=False`` -> ``"reject"``. The reason
       names EVERY failing hard gate (not just the first), so a caller never
       has to re-run gate evaluation to see the full rejection picture.
    3. Else, any ``kind=SOFT`` gate with ``passed=False`` -> ``"review"``.
       The reason names every failing soft gate.
    4. Else (every applicable gate passed, including the vacuous case of
       zero gates) -> ``"accept"``.
    """
    now = (clock or (lambda: datetime.now(tz=UTC)))()

    if not route_qualified:
        return SceneVerdict(
            verdict="reject",
            route_id=route_id,
            gate_results=gate_results,
            computed_utc=now,
            reason=(
                f"route {route_id!r} is not qualified; a scene verdict may only be "
                "accepted or reviewed for use through a currently qualified route"
            ),
        )

    applicable_results = [g for g in gate_results if g.applicable]

    failing_hard = [g for g in applicable_results if g.kind == GateKind.HARD and g.passed is False]
    if failing_hard:
        return SceneVerdict(
            verdict="reject",
            route_id=route_id,
            gate_results=gate_results,
            computed_utc=now,
            reason="; ".join(_gate_failure_description("hard", g) for g in failing_hard),
        )

    failing_soft = [g for g in applicable_results if g.kind == GateKind.SOFT and g.passed is False]
    if failing_soft:
        return SceneVerdict(
            verdict="review",
            route_id=route_id,
            gate_results=gate_results,
            computed_utc=now,
            reason="; ".join(_gate_failure_description("soft", g) for g in failing_soft),
        )

    return SceneVerdict(
        verdict="accept",
        route_id=route_id,
        gate_results=gate_results,
        computed_utc=now,
        reason="all applicable gates passed",
    )


def _gate_failure_description(kind_label: str, gate: GateResult) -> str:
    symbol = _COMPARISON_SYMBOLS.get(gate.comparison, gate.comparison)
    return (
        f"{kind_label} gate {gate.name!r} failed: {gate.observed_value} {symbol} {gate.threshold}"
    )


class ReviewRecord(Contract):
    """One human review decision responding to a :class:`SceneVerdict`.

    Recorded for provenance, never used to gate anything by itself — see
    :func:`effective_disposition` for how (and how not) a review can
    influence use.
    """

    actor: str
    decision: Literal["accepted", "rejected"]
    reason_code: str
    note: str | None = None
    input_verdict: Literal["accept", "review", "reject"]
    """Which ``SceneVerdict.verdict`` this review is responding to — for
    provenance, not to gate anything itself."""
    reviewed_utc: datetime


def effective_disposition(
    verdict: SceneVerdict, reviews: tuple[ReviewRecord, ...]
) -> Literal["accepted", "rejected", "pending"]:
    """Rule 7, precisely: "a human review can qualify use but cannot rewrite
    measured values, the computed verdict, or a failed route gate."

    - ``verdict.verdict == "reject"`` -> always ``"rejected"``, REGARDLESS of
      any review — a review can never override a failed hard gate or an
      unqualified route.
    - ``verdict.verdict == "accept"`` -> always ``"accepted"``; no review is
      needed to use an already-accepted scene.
    - ``verdict.verdict == "review"`` -> looks at ``reviews`` for the most
      recent one whose ``input_verdict == "review"``, by ``reviewed_utc``.
      Ties in ``reviewed_utc`` are broken deterministically by preferring
      whichever tied record appears LATER in the ``reviews`` tuple (treated
      as reflecting submission/insertion order — the caller controls that
      order, e.g. by appending new reviews). If no such review exists,
      returns ``"pending"``.

    This function never mutates ``verdict`` or any ``ReviewRecord`` — both
    are ``Contract`` instances (frozen, ``validate_assignment=True``), and
    this function only reads their fields and returns a new string; it is a
    pure combination, matching "a review produces an effective disposition
    ... without altering computed metrics or the original review verdict."
    """
    if verdict.verdict == "reject":
        return "rejected"
    if verdict.verdict == "accept":
        return "accepted"

    most_recent: ReviewRecord | None = None
    most_recent_index = -1
    for index, review in enumerate(reviews):
        if review.input_verdict != "review":
            continue
        if most_recent is None or (
            review.reviewed_utc,
            index,
        ) > (most_recent.reviewed_utc, most_recent_index):
            most_recent = review
            most_recent_index = index

    if most_recent is None:
        return "pending"
    return most_recent.decision


def derive_scene_metrics(
    records: tuple[CorrespondenceRecord, ...], coverage: CoverageMetrics
) -> dict[str, float | None]:
    """Compute a small, named set of common metrics from already-verified/
    selected records, so callers don't have to hand-roll this every time.

    The gate engine itself (:func:`evaluate_gate`, :func:`compute_scene_verdict`)
    stays metric-source-agnostic — it never reads a :class:`CorrespondenceRecord`
    or :class:`CoverageMetrics` directly, only the ``dict`` this function
    returns, via :attr:`SceneEvidence.metrics`.

    Metrics computed:

    - ``"eligible_occupancy"``: ``coverage.eligible_cell_occupancy`` directly.
    - ``"largest_empty_run_fraction"``: ``coverage.largest_empty_run`` divided
      by the total cell count of ``coverage.per_cell_candidate_counts``
      (``.size``, i.e. the full grid, rows*cols). ``CoverageMetrics`` does not
      itself carry an eligible-only cell count (that lives on the
      ``EligibilityGrid`` used to produce it, which this function does not
      receive), so this denominator is the total grid cell count, not a
      guaranteed eligible-only count. When every cell in the grid is
      eligible this is exact; when some cells are ineligible, this fraction
      is a conservative (smaller-than-true) estimate, since the true
      eligible-only denominator would be <= the total grid cell count.
      ``None`` if the grid has zero cells.
    - ``"verified_inlier_fraction"``: fraction of ``records`` with
      ``is_inlier=True`` among all ``is_candidate=True`` records. ``None``
      (never ``0.0``) if there are zero candidates.
    - ``"max_estimator_disagreement_px"``: the maximum
      ``estimator_disagreement_px`` among records where it is not ``None``.
      ``None`` if no record has one computed.
    - ``"invalid_covariance_fraction"``: fraction of ``is_inlier=True``
      records whose ``covariance is None`` — a covariance that could not be
      estimated at all. ``None`` if there are zero inliers.
    - ``"uncalibrated_covariance_fraction"``: fraction of ``is_inlier=True``
      records whose ``covariance`` exists but ``covariance_calibrated`` is
      ``False`` — distinct from the metric above: this counts a covariance
      that exists but has not been validated against truth, not one that
      could not be produced at all. Conflating the two into a single number
      would hide which failure mode is present, so they are tracked
      separately. ``None`` if there are zero inliers.
    - ``"withheld_rmse_2d_px"``: computed ONLY from
      ``PointRole.WITHHELD_CHECK_POINT`` records (rule 4's naming-convention
      enforcement, made structural here: this function's withheld-only
      filter is the only path this metric's value can come from) — the
      root-mean-square of each such record's ``robust_model_residual_px``.
      A withheld record whose ``robust_model_residual_px`` is ``None`` is
      excluded from the RMSE (partial availability among withheld points
      does not block the metric; it just narrows the sample). ``None`` if
      there are zero withheld-check-point records with a usable residual —
      which is exactly rule 3's intent: no independent control means this
      metric is ``None``, hence inapplicable-safe for any
      ``requires_independent_control`` gate that references it.
    """
    total_grid_cells = int(coverage.per_cell_candidate_counts.size)
    largest_empty_run_fraction = (
        coverage.largest_empty_run / total_grid_cells if total_grid_cells > 0 else None
    )

    candidates = [r for r in records if r.is_candidate]
    verified_inlier_fraction = (
        sum(1 for r in candidates if r.is_inlier) / len(candidates) if candidates else None
    )

    disagreements = [
        r.estimator_disagreement_px for r in records if r.estimator_disagreement_px is not None
    ]
    max_estimator_disagreement_px = max(disagreements) if disagreements else None

    inliers = [r for r in records if r.is_inlier]
    invalid_covariance_fraction = (
        sum(1 for r in inliers if r.covariance is None) / len(inliers) if inliers else None
    )
    uncalibrated_covariance_fraction = (
        sum(1 for r in inliers if r.covariance is not None and not r.covariance_calibrated)
        / len(inliers)
        if inliers
        else None
    )

    withheld_residuals = [
        r.robust_model_residual_px
        for r in records
        if r.point_role == PointRole.WITHHELD_CHECK_POINT and r.robust_model_residual_px is not None
    ]
    withheld_rmse_2d_px = (
        math.sqrt(sum(value**2 for value in withheld_residuals) / len(withheld_residuals))
        if withheld_residuals
        else None
    )

    return {
        "eligible_occupancy": coverage.eligible_cell_occupancy,
        "largest_empty_run_fraction": largest_empty_run_fraction,
        "verified_inlier_fraction": verified_inlier_fraction,
        "max_estimator_disagreement_px": max_estimator_disagreement_px,
        "invalid_covariance_fraction": invalid_covariance_fraction,
        "uncalibrated_covariance_fraction": uncalibrated_covariance_fraction,
        "withheld_rmse_2d_px": withheld_rmse_2d_px,
    }
