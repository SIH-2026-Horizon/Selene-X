"""Candidate verification, eligibility, and coverage-aware selection (WP-07).

Responsibilities:

* Score normalisation within each algorithm, forward/backward consistency,
  mutual-nearest checks, prior uncertainty gates, and duplicate removal.
* A robust local geometric or sensor-aware outlier model. A homography is a
  diagnostic baseline only and is never the final terrain-aware model.
* An eligibility definition of valid source and reference data inside physical
  overlap and supported terrain and illumination, recording why each excluded
  cell is ineligible (ADR-008).
* Quality filtering and spatial non-maximum suppression before any coverage
  scoring.
* A deterministic 8 by 8 eligible grid selector first; an adaptive quadtree
  selector only after the fixed grid is tested and only if it improves the
  coverage-versus-accuracy trade-off.
* Coverage metrics: eligible-cell occupancy, convex-hull to valid-overlap
  ratio, largest empty region or run, and per-cell count distribution.

Measured, interpolated, and derived points stay distinct. Derived points never
count as verified inliers or occupied measured cells. Clark-Evans, if reported
at all, is labelled as a complete-spatial-randomness diagnostic and is never
presented as proof of regular spacing.
"""

__all__: list[str] = []
