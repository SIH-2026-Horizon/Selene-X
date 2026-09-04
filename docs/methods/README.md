# Methods notes

Derivations, conventions, and measurement protocols that are too detailed for
an ADR and too durable for a commit message. Examples of what belongs here:

- the pixel-centre convention worked through each ISIS, GDAL, and CSM boundary
- the local warp Jacobian derivation used for cross-frame residual conversion
- the PSF/MTF matching procedure and its fallback while D-005 is unresolved
- the covariance calibration procedure and its reliability diagrams
- the independent check-point protocol, including reviewer process, point
  covariance, control uncertainty, disagreement handling, and exclusions
- the coverage metric definitions over eligible overlap

Current notes:

- [Geometry and reference readiness](geometry-reference.md) — provider evidence,
  footprint validation, lunar projections, terrain/control authority, pyramids,
  and route qualification.
