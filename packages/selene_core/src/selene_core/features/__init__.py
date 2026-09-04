"""Radiometric, structural, and IIRS feature channels (WP-05).

Responsibilities:

* Local radiometric normalisation with explicit masks and no extrapolation into
  invalid areas.
* Gradient magnitude and orientation, phase congruency or an equivalent phase
  feature, and local self-similarity channels.
* Conservative dark and shadow estimation that preserves penumbra as
  uncertainty rather than binary truth.
* An optional source-lit hillshade or portable Hapke-inspired terrain channel
  behind a feature flag, with DTM resolution and uncertainty recorded in the
  channel confidence mask.
* IIRS reflective versus thermally influenced band separation from label
  wavelengths, bad-band and low-SNR rejection with recorded reasons, and
  structural composites from the selected bands (ADR-012).

Every channel is individually toggleable so that identical runs form an
ablation. Disabling all auxiliary channels must reproduce the WP-04 baseline.
No channel may claim to remove the illumination difference or to recreate
texture finer than its terrain and albedo inputs support.
"""

from selene_core.features.local_radiometry import (
    FeatureChannel,
    LocalRadiometricNormalizationParameters,
    normalize_local_radiometry,
)
from selene_core.features.shadow_estimation import (
    ShadowEstimate,
    ShadowEstimationParameters,
    estimate_source_shadows,
)
from selene_core.features.structural import (
    StructuralFeatureBundle,
    StructuralFeatureParameters,
    extract_gradient_magnitude,
    extract_gradient_orientation,
    extract_local_self_similarity,
    extract_phase_equivalent,
    extract_structural_features,
)

__all__ = [
    "FeatureChannel",
    "LocalRadiometricNormalizationParameters",
    "ShadowEstimate",
    "ShadowEstimationParameters",
    "StructuralFeatureBundle",
    "StructuralFeatureParameters",
    "estimate_source_shadows",
    "extract_gradient_magnitude",
    "extract_gradient_orientation",
    "extract_local_self_similarity",
    "extract_phase_equivalent",
    "extract_structural_features",
    "normalize_local_radiometry",
]
