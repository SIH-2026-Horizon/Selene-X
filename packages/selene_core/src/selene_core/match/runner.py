"""Classical matcher execution reports, deliberately diagnostic-only.

This is a run ledger for an actual supplied image pair, not a benchmark report.
It records what the matchers and verification filters did, but contains no
accuracy claim, no named mission result, and no route qualification verdict.
Those require WP-00/11 frozen data and independent checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord
from selene_core.match.protocol import Matcher, MatchParameters, MatchPrior
from selene_core.match.verification import verify_match_candidates

__all__ = ["ClassicalMatchReport", "VerificationParameters", "run_classical_match"]


@dataclass(frozen=True, slots=True)
class VerificationParameters:
    """Explicit tuning parameters for reversible candidate verification."""

    fit_residual_threshold_px: float = 2.0
    fit_min_inliers: int = 3
    fit_max_iterations: int = 128
    forward_backward_max_error_px: float = 1.0
    forward_backward_anchor_tolerance_px: float | None = None


@dataclass(frozen=True, slots=True)
class ClassicalMatchReport:
    """Counts and candidates from one execution; never a real-data verdict."""

    algorithm: str
    raw_candidates: tuple[CorrespondenceRecord, ...]
    reverse_candidates: tuple[CorrespondenceRecord, ...] | None
    verified_candidates: tuple[CorrespondenceRecord, ...]
    evidence_status: str = "diagnostic_only_not_a_benchmark_claim"

    @property
    def candidate_count(self) -> int:
        return len(self.raw_candidates)

    @property
    def inlier_count(self) -> int:
        return sum(record.is_inlier for record in self.verified_candidates)

    @property
    def rejected_count(self) -> int:
        return sum(record.rejection_reason is not None for record in self.verified_candidates)


def run_classical_match(
    matcher: Matcher,
    source: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    *,
    source_mask: npt.NDArray[np.bool_] | None,
    reference_mask: npt.NDArray[np.bool_] | None,
    prior: MatchPrior,
    parameters: MatchParameters,
    verification: VerificationParameters,
    job_id: str,
    input_digest: str,
    reference_digest: str,
    run_reverse: bool = True,
    reverse_prior: MatchPrior | None = None,
) -> ClassicalMatchReport:
    """Run forward/reverse matching then forward-backward and robust filtering.

    Reverse matching is opt-in because it doubles cost.  If disabled, the
    verification result correctly leaves forward/backward error unavailable
    rather than claiming it is zero.
    """
    forward = matcher.match(
        source,
        reference,
        source_mask=source_mask,
        reference_mask=reference_mask,
        prior=prior,
        parameters=parameters,
        job_id=job_id,
        input_digest=input_digest,
        reference_digest=reference_digest,
    )
    reverse = None
    if run_reverse:
        reverse = matcher.match(
            reference,
            source,
            source_mask=reference_mask,
            reference_mask=source_mask,
            prior=reverse_prior or MatchPrior(),
            parameters=parameters,
            job_id=job_id,
            input_digest=reference_digest,
            reference_digest=input_digest,
        )
    # Deduplication and NMS are deliberately selection-stage policies.  The
    # matching-stage report preserves raw evidence and applies only reciprocal
    # checking plus its own robust geometric consistency filter.
    verified = verify_match_candidates(
        forward,
        reverse_records=reverse,
        residual_threshold_px=verification.fit_residual_threshold_px,
        min_inliers=verification.fit_min_inliers,
        max_iterations=verification.fit_max_iterations,
        forward_backward_max_error_px=verification.forward_backward_max_error_px,
        forward_backward_anchor_tolerance_px=verification.forward_backward_anchor_tolerance_px,
    )
    algorithm = forward[0].algorithm if forward else type(matcher).__name__
    return ClassicalMatchReport(
        algorithm=algorithm,
        raw_candidates=forward,
        reverse_candidates=reverse,
        verified_candidates=verified,
    )
