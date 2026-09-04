"""The canonical correspondence record (plan section 6.4, WP-01 task 5, WP-04).

Every matcher — classical or learned — emits :class:`CorrespondenceRecord`
instances, whether or not the point survives to become a control point. A
rejected candidate is recorded with its rejection reason, not discarded,
because a matching stage's behaviour is only auditable if the points it threw
away are as visible as the points it kept.

**Scope note (read before extending this module).** ``match/__init__.py``'s
docstring describes a matcher consuming "typed pyramid tiles" from WP-03
(geometry, pyramids, masks) — but WP-03 does not exist in this repository yet,
and neither does the raster stack it would need. This record's ``tile_id`` and
``pyramid_level`` fields are therefore always ``None`` in this build; they are
kept so the schema is forward-compatible with tiled pyramid-level matching
(plan WP-04 task 6) once WP-03 supplies it. Nothing here assumes tiling,
halos, or deterministic overlap deduplication.

The ``Matcher`` protocol that produces these records lives in
:mod:`selene_core.match.protocol`, in its own module because it is a
behavioural contract (an interface a matcher implementation satisfies) rather
than a serialised, schema-bound data contract like this one.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import Field, model_validator

from selene_core.contracts import Contract as _Contract
from selene_core.hashing import is_sha256
from selene_core.types import (
    Covariance2D,
    LocalWarpJacobian,
    MapCoordinate,
    ReferencePixel,
    SourcePixel,
)

__all__ = [
    "CorrespondenceRecord",
    "NmsStatus",
    "PointRole",
]


class PointRole(StrEnum):
    """The single role a correspondence has been assigned, if any.

    Deliberately one enum field rather than three independent booleans
    (``is_training``, ``is_fitting_inlier``, ``is_withheld``). The plan
    requires that training points, fitting inliers, and withheld check points
    be disjoint; three booleans can disagree with each other (a bug, not a
    scientific finding), while a single-valued enum makes disjointness a
    structural guarantee — a record can only ever have *one* ``point_role``.
    ``TRAINING``, ``FITTING_INLIER``, and ``WITHHELD_CHECK_POINT`` are
    therefore mutually exclusive by construction, which is what satisfies the
    plan's "disjoint and explicitly flagged" requirement.
    """

    CANDIDATE = "candidate"
    """Produced by a matcher, not yet classified into a downstream role."""

    TRAINING = "training"
    """Used to fit a model that is not the final robust estimate."""

    FITTING_INLIER = "fitting_inlier"
    """An inlier that participated in the final robust model fit."""

    WITHHELD_CHECK_POINT = "withheld_check_point"
    """Deliberately excluded from fitting so it can independently check the
    fitted model."""

    REJECTED = "rejected"
    """Excluded from every downstream role. See ``rejection_reason``."""


class NmsStatus(StrEnum):
    """Outcome of non-maximum suppression against nearby candidates."""

    SURVIVED = "survived"
    """Kept after suppression ran."""

    SUPPRESSED = "suppressed"
    """Removed in favour of a stronger nearby candidate."""

    NOT_EVALUATED = "not_evaluated"
    """Suppression has not run for this record, for example because the
    matcher does not perform it."""


class CorrespondenceRecord(_Contract):
    """One candidate or accepted match between a source and reference pixel.

    Field groups follow plan section 6.4: identity, position, evidence,
    geometry, refinement, uncertainty, quality, coverage, and provenance.
    Every field that cannot be computed by the producing matcher is ``None``,
    never a fabricated default.
    """

    # -- Identity ------------------------------------------------------
    match_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Caller-supplied identity, or an auto-generated UUID4 when the caller has "
        "no natural identity for this record. Either way, unique per record within a job.",
    )
    job_id: str
    algorithm: str
    algorithm_version: str
    tile_id: str | None = Field(
        default=None,
        description="Always None in this build: no tiling infrastructure exists yet (WP-03). "
        "Kept for forward compatibility with tiled pyramid-level matching (WP-04 task 6).",
    )
    pyramid_level: int | None = Field(
        default=None,
        description="Always None in this build: no pyramid infrastructure exists yet (WP-03). "
        "Kept for forward compatibility.",
    )
    selection_reason: str | None = None

    # -- Position --------------------------------------------------------
    source_pixel: SourcePixel
    reference_pixel: ReferencePixel
    ground_coordinate: MapCoordinate | None = Field(
        default=None,
        description="Optional ground coordinate and frame. MapCoordinate carries its own "
        "crs_wkt, so one field covers both the coordinate and the frame it is meaningful in.",
    )

    # -- Evidence ----------------------------------------------------------
    raw_score: float
    calibrated_confidence: float | None = None
    descriptor_channel_agreement: float | None = None
    forward_backward_error_px: float | None = None

    # -- Geometry ------------------------------------------------------
    prior_displacement_px: tuple[float, float] | None = Field(
        default=None,
        description="(dy, dx) — line/sample = row/column = y/x order, matching this project's "
        "established internal pixel convention (selene_core.types).",
    )
    residual_from_prior_px: tuple[float, float] | None = Field(
        default=None, description="(dy, dx), same order as prior_displacement_px."
    )
    robust_model_residual_px: float | None = None
    local_warp_jacobian: LocalWarpJacobian | None = None

    # -- Refinement ----------------------------------------------------
    coarse_location: SourcePixel | None = None
    refined_location: SourcePixel | None = None
    estimator_identities: tuple[str, ...] = ()
    estimator_disagreement_px: float | None = None

    # -- Uncertainty -----------------------------------------------------
    covariance: Covariance2D | None = None
    covariance_method: str | None = None
    covariance_calibrated: bool = Field(
        default=False,
        description="False unless the covariance has actually been validated against truth. "
        "An uncalibrated covariance claiming calibration would be a fabricated confidence claim.",
    )

    # -- Quality -------------------------------------------------------
    is_candidate: bool = False
    is_inlier: bool = False
    point_role: PointRole = PointRole.CANDIDATE
    rejection_reason: str | None = None
    nms_status: NmsStatus | None = None

    # -- Coverage --------------------------------------------------------
    eligible_cell_id: str | None = None
    grid_level: int | None = None
    selected_for_coverage: bool = False
    coverage_selection_rationale: str | None = None

    # -- Provenance ----------------------------------------------------
    input_digest: str
    reference_digest: str
    parameter_set_digest: str
    code_revision: str | None = None

    @model_validator(mode="after")
    def _check(self) -> CorrespondenceRecord:
        if self.is_inlier and not self.is_candidate:
            raise ValueError(
                "CorrespondenceRecord.is_inlier=True requires is_candidate=True; a point can "
                "only be an inlier if it was a candidate in the first place"
            )
        if (
            self.point_role
            in {PointRole.TRAINING, PointRole.FITTING_INLIER, PointRole.WITHHELD_CHECK_POINT}
            and not self.is_candidate
        ):
            raise ValueError(
                f"CorrespondenceRecord.point_role={self.point_role!r} requires "
                "is_candidate=True; a downstream role can only be assigned to a point that was "
                "at least a candidate"
            )
        if self.covariance_calibrated and self.covariance is None:
            raise ValueError(
                "CorrespondenceRecord.covariance_calibrated=True requires covariance to be "
                "set; there is nothing calibrated when no covariance was produced"
            )
        for field_name in ("input_digest", "reference_digest", "parameter_set_digest"):
            value = getattr(self, field_name)
            if not is_sha256(value):
                raise ValueError(
                    f"CorrespondenceRecord.{field_name} must be a SHA-256 hex digest, got {value!r}"
                )
        return self
