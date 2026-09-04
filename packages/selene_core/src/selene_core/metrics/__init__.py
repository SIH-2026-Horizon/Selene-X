"""Accuracy, coverage, diagnostics, gates, and verdicts (WP-09).

Responsibilities:

* The two report kinds sharing one schema (plan section 6.6): a
  route-qualification report, which is the authority for held-out accuracy
  claims on the frozen benchmark, and a scene report, which qualifies one user
  product from observable scene evidence and cites the route-qualification
  version.
* Source-frame ``RMSE_x``, ``RMSE_y``, ``RMSE_2D``, median endpoint error, P90,
  and CE90 on withheld check points (ADR-003).
* Optional absolute horizontal error in metres, reported only with a named
  independent control source and its uncertainty.
* Candidate, inlier, estimator-failure, coverage, illumination, terrain,
  overlap, and reference-quality strata, plus runtime and resource diagnostics.
* Per-gate observed value, threshold, applicability, pass state, and evidence
  source.
* The immutable computed verdict ``accept``, ``review``, or ``reject`` and the
  fail-closed rules of plan section 10 (ADR-010).

A metric that cannot be computed is ``null`` with a reason. It is never
replaced with zero and never omitted. A missing applicable hard-gate metric is
a rejection, not a pass.
"""

__all__: list[str] = []
