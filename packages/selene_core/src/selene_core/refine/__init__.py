"""Sub-pixel refinement and per-match uncertainty (WP-08).

Responsibilities:

* Mask-aware local patch extraction in the source and reference working
  representations.
* Inverse-compositional ECC refinement and band-limited Fourier upsampled phase
  correlation as two independent estimators, with recorded convergence, peak
  ambiguity, patch texture, and estimator disagreement.
* Anisotropic covariance from the local Hessian where valid, calibrated
  empirically with controlled shifts, bootstrap or perturbation tests, and
  reliability diagrams.

Non-positive covariance is rejected. An otherwise valid match with uncalibrated
covariance is retained only with ``covariance_status = uncalibrated``, is
excluded from uncertainty-dependent acceptance gates, and forces the scene to
``review`` where policy requires. Directionally weak but valid covariance is
down-weighted, never collapsed to a single scalar.
"""

__all__: list[str] = []
