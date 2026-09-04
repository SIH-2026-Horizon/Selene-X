"""Fail-closed sensor-pose providers and optional SPICE kernel furnishing.

This module does not contain a mission-specific camera model.  It provides the
boundary that an OHRC/TMC-2/IIRS adapter must implement and records whether a
provider was actually furnished and independently checked.  An unavailable
``spiceypy`` installation is a normal, explicit result rather than a fallback
to fabricated geometry.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from selene_core.geometry.contracts import GeometryValidation, GroundPoint
from selene_core.hashing import digest_file
from selene_core.ingest.spice_inventory import KernelRecord
from selene_core.types import BodyFixedCoordinate, SourcePixel

__all__ = [
    "KernelFurnishingEvidence",
    "PoseAvailability",
    "PoseSamplingReport",
    "SensorPose",
    "SensorPoseProvider",
    "SpicePoseProvider",
    "furnish_spice_kernels",
    "sample_provider_geometry",
]


class PoseAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_VALIDATED = "not_validated"


@dataclass(frozen=True, slots=True)
class KernelFurnishingEvidence:
    """The outcome of furnishing already checksum-validated kernel records."""

    availability: PoseAvailability
    validation: GeometryValidation
    furnished_kernel_names: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class SensorPose:
    """Body-fixed sensor position at a sampled image line/pixel."""

    position: BodyFixedCoordinate
    acquisition_et_s: float
    attitude_source: str
    covariance_position_m2: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.acquisition_et_s) or not self.attitude_source.strip():
            raise ValueError("pose time must be finite and attitude_source must be non-empty")
        if self.covariance_position_m2 is not None and (
            not math.isfinite(self.covariance_position_m2) or self.covariance_position_m2 < 0
        ):
            raise ValueError("covariance_position_m2 must be non-negative when supplied")


class SensorPoseProvider(Protocol):
    """Operational camera/terrain boundary for geometry sampling."""

    @property
    def evidence(self) -> KernelFurnishingEvidence:
        """Availability and validation provenance for this provider."""

    def pose_at(self, pixel: SourcePixel) -> SensorPose | None:
        """Return the pose sampled at ``pixel``, or ``None`` if unavailable."""

    def ground_at(self, pixel: SourcePixel) -> GroundPoint | None:
        """Return the camera-model terrain intercept for ``pixel``, or ``None``."""


@dataclass(frozen=True, slots=True)
class PoseSamplingReport:
    """Per-line/pixel provider sampling evidence for route qualification."""

    evidence: KernelFurnishingEvidence
    attempted_samples: int
    pose_samples: int
    ground_samples: int
    validation: GeometryValidation
    message: str


def sample_provider_geometry(
    provider: SensorPoseProvider, *, image_shape: tuple[int, int], samples_per_line: int = 3
) -> PoseSamplingReport:
    """Evaluate pose and terrain intercepts throughout an image, without interpolation."""
    rows, columns = image_shape
    if rows < 1 or columns < 1 or samples_per_line < 1:
        raise ValueError("image dimensions and samples_per_line must be positive")
    attempted = rows * samples_per_line
    pose_samples = 0
    ground_samples = 0
    for line in range(rows):
        for index in range(samples_per_line):
            sample = (
                0.0 if samples_per_line == 1 else index * (columns - 1) / (samples_per_line - 1)
            )
            pixel = SourcePixel(float(line), sample)
            pose_samples += provider.pose_at(pixel) is not None
            ground_samples += provider.ground_at(pixel) is not None
    evidence = provider.evidence
    if evidence.availability is PoseAvailability.UNAVAILABLE:
        validation = GeometryValidation.UNAVAILABLE
        message = evidence.message
    elif pose_samples != attempted or ground_samples != attempted:
        validation = GeometryValidation.UNAVAILABLE
        message = "provider did not supply pose and ground intersections for all samples"
    else:
        validation = evidence.validation
        message = evidence.message
    return PoseSamplingReport(
        evidence, attempted, pose_samples, ground_samples, validation, message
    )


def furnish_spice_kernels(records: Sequence[KernelRecord]) -> KernelFurnishingEvidence:
    """Furnish inventory-validated local kernels when optional SpiceyPy exists.

    ``validate_kernel_inventory`` must be called first; this function accepts
    only its records, never filenames from untrusted labels.  Furnishing alone
    remains ``NOT_VALIDATED`` until a real scene comparison is recorded.
    """
    if not records:
        return KernelFurnishingEvidence(
            PoseAvailability.UNAVAILABLE,
            GeometryValidation.UNAVAILABLE,
            (),
            "no checksum-validated SPICE kernel records were provided",
        )
    try:
        import spiceypy
    except ImportError:
        return KernelFurnishingEvidence(
            PoseAvailability.UNAVAILABLE,
            GeometryValidation.UNAVAILABLE,
            (),
            "optional spiceypy dependency is not installed",
        )
    furnished: list[str] = []
    try:
        for record in records:
            if not record.path.is_file() or digest_file(record.path) != record.sha256:
                raise ValueError(f"kernel bytes changed since inventory validation: {record.name}")
            spiceypy.furnsh(str(record.path))
            furnished.append(record.name)
    except Exception as exc:  # SpiceyPy exposes toolkit-specific exception classes.
        for name in reversed(furnished):
            record = next(item for item in records if item.name == name)
            try:
                spiceypy.unload(str(record.path))
            except Exception as rollback_error:
                # Continue rolling back the remaining items; never report a partial pool.
                _ = rollback_error
        return KernelFurnishingEvidence(
            PoseAvailability.UNAVAILABLE,
            GeometryValidation.UNAVAILABLE,
            (),
            f"SPICE kernel furnishing failed: {type(exc).__name__}",
        )
    return KernelFurnishingEvidence(
        PoseAvailability.NOT_VALIDATED,
        GeometryValidation.INVENTORY_ONLY,
        tuple(furnished),
        "kernels furnished; mission camera/terrain and independent scene validation "
        "remain required",
    )


@dataclass(frozen=True, slots=True)
class SpicePoseProvider:
    """Explicit unavailable placeholder until a mission camera adapter is supplied.

    A real adapter should wrap this evidence and implement ``pose_at`` and
    ``ground_at`` using its sensor model.  Returning ``None`` prevents callers
    from treating furnished kernels as a geometry solution by themselves.
    """

    evidence: KernelFurnishingEvidence

    def pose_at(self, pixel: SourcePixel) -> SensorPose | None:
        del pixel
        return None

    def ground_at(self, pixel: SourcePixel) -> GroundPoint | None:
        del pixel
        return None
