"""Limited robust source-frame adjustment (WP-08).

This package is an in-memory numerical core for caller-supplied observation
linearisations.  It robustly fits a small, explicit source-frame correction
using calibrated full 2-D covariance, rejects unobservable models by default,
and reports fitting diagnostics separately from withheld check-point metrics.

It does not provide pushbroom geometry, an ISIS/CSM integration, physical
sensor-model export, terrain rendering, platform jitter, graph adjustment, or
absolute accuracy claims.  A physical sensor-model exporter remains required.
"""

from selene_core.adjust.linearized import (
    AdjustmentInputError,
    AdjustmentOptions,
    AdjustmentParameter,
    AdjustmentParameterization,
    AdjustmentResult,
    ObservationLinearization,
    ParameterizationAttempt,
    ParameterReduction,
    ReductionPolicy,
    ResidualDiagnostic,
    ResidualMetrics,
    ScanLineResidualCorrelation,
    fit_adjustment,
    translation_only_parameterization,
)

__all__ = [
    "AdjustmentInputError",
    "AdjustmentOptions",
    "AdjustmentParameter",
    "AdjustmentParameterization",
    "AdjustmentResult",
    "ObservationLinearization",
    "ParameterReduction",
    "ParameterizationAttempt",
    "ReductionPolicy",
    "ResidualDiagnostic",
    "ResidualMetrics",
    "ScanLineResidualCorrelation",
    "fit_adjustment",
    "translation_only_parameterization",
]
