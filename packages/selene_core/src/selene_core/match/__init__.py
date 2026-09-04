"""Matcher contracts and classical matching implementation (WP-04).

Responsibilities:

* A compact ``Matcher`` array interface plus typed pyramid-tile orchestration,
  masks, priors, parameter snapshots, and canonical correspondence records.
* Classical baselines: coarse phase correlation within metadata-bounded search
  regions, local normalised cross-correlation with peak sharpness and ambiguity
  measures, SIFT, and a RIFT-class multimodal baseline.
* Tiled matching with halos, deterministic overlap deduplication, and tile
  provenance.
* Mask-aware normalisation so that nodata, mutually unusable shadow, borders,
  and terrain gaps never become features.
* Optional SIFT and explicitly plugin-backed RIFT-class adapters with declared
  dependency/license provenance. Learned matching belongs to WP-06.

Every candidate is recorded, including rejected candidates and their reasons.
"""

from selene_core.match.classical_adapters import (
    AlgorithmProvenance,
    MatcherUnavailableError,
    RiftMatcher,
    SiftMatcher,
)
from selene_core.match.learned import (
    ConfidenceCalibration,
    GroupedDenseFlowMatcher,
    LearnedMatcherConfigurationError,
    LearnedMatcherError,
    LearnedMatcherInferenceError,
    LearnedMatcherInputError,
    LearnedMatcherLoadError,
)
from selene_core.match.ncc import NccMatcher
from selene_core.match.phase_correlation import PhaseCorrelationMatcher
from selene_core.match.protocol import Matcher, MatchParameters, MatchPrior
from selene_core.match.runner import (
    ClassicalMatchReport,
    VerificationParameters,
    run_classical_match,
)
from selene_core.match.tiling import (
    MatchTile,
    TiledMatchResult,
    deduplicate_tile_records,
    match_pyramid_tiles,
)

__all__ = [
    "AlgorithmProvenance",
    "ClassicalMatchReport",
    "ConfidenceCalibration",
    "GroupedDenseFlowMatcher",
    "LearnedMatcherConfigurationError",
    "LearnedMatcherError",
    "LearnedMatcherInferenceError",
    "LearnedMatcherInputError",
    "LearnedMatcherLoadError",
    "MatchParameters",
    "MatchPrior",
    "MatchTile",
    "Matcher",
    "MatcherUnavailableError",
    "NccMatcher",
    "PhaseCorrelationMatcher",
    "RiftMatcher",
    "SiftMatcher",
    "TiledMatchResult",
    "VerificationParameters",
    "deduplicate_tile_records",
    "match_pyramid_tiles",
    "run_classical_match",
]
