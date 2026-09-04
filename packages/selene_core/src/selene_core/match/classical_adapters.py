"""Optional SIFT and RIFT-class adapters with explicit provenance boundaries.

Neither OpenCV nor a particular RIFT implementation is a required dependency
of ``selene-core``.  These adapters consequently never silently substitute a
different algorithm: callers can inspect availability and either choose a
declared fallback or record the unavailable route as such.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.ncc import NccMatcher
from selene_core.match.protocol import MatchParameters, MatchPrior
from selene_core.types import ReferencePixel, SourcePixel

__all__ = [
    "AlgorithmProvenance",
    "MatcherUnavailableError",
    "RiftBackend",
    "RiftMatcher",
    "SiftMatcher",
]


@dataclass(frozen=True, slots=True)
class AlgorithmProvenance:
    """Immutable algorithm identity required for scientific comparison."""

    algorithm: str
    version: str
    license_expression: str
    dependency: str | None
    available: bool
    availability_reason: str | None = None


class MatcherUnavailableError(RuntimeError):
    """Raised when an explicitly requested optional classical backend is absent."""


class RiftBackend(Protocol):
    """Narrow plugin ABI for a user-supplied RIFT-class implementation."""

    provenance: AlgorithmProvenance

    def match(
        self,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        *,
        source_mask: npt.NDArray[np.bool_] | None,
        reference_mask: npt.NDArray[np.bool_] | None,
        prior: MatchPrior,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
    ) -> tuple[CorrespondenceRecord, ...]: ...


def _image_for_opencv(
    image: npt.NDArray[np.float64], mask: npt.NDArray[np.bool_] | None
) -> npt.NDArray[np.uint8]:
    if image.ndim != 2 or image.size == 0 or not np.all(np.isfinite(image)):
        raise ValueError("SIFT input image must be a non-empty finite 2-D array")
    valid = np.ones(image.shape, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    if valid.shape != image.shape:
        raise ValueError("SIFT mask must have the same shape as its image")
    if not np.any(valid):
        raise ValueError("SIFT mask has no usable pixels")
    # Normalise from valid pixels only.  Invalid samples are zero after this
    # normalisation and are also withheld by OpenCV's detection mask.
    low, high = np.percentile(image[valid], (1.0, 99.0))
    if high <= low:
        high = low + 1.0
    scaled = np.zeros(image.shape, dtype=np.float64)
    scaled[valid] = np.clip((image[valid] - low) * 255.0 / (high - low), 0.0, 255.0)
    return scaled.astype(np.uint8)


class SiftMatcher:
    """OpenCV SIFT adapter, optional by design and mask-aware at detection."""

    @property
    def provenance(self) -> AlgorithmProvenance:
        available = importlib.util.find_spec("cv2") is not None
        return AlgorithmProvenance(
            algorithm="sift",
            version="opencv-sift",
            # OpenCV's license applies to the adapter dependency; feature
            # patent status is not asserted here and is a deployment review.
            license_expression="Apache-2.0",
            dependency="opencv-python",
            available=available,
            availability_reason=(
                None if available else "optional dependency opencv-python is not installed"
            ),
        )

    def match(
        self,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        *,
        source_mask: npt.NDArray[np.bool_] | None,
        reference_mask: npt.NDArray[np.bool_] | None,
        prior: MatchPrior,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
    ) -> tuple[CorrespondenceRecord, ...]:
        provenance = self.provenance
        if not provenance.available:
            raise MatcherUnavailableError(provenance.availability_reason or "SIFT unavailable")
        import cv2  # type: ignore[import-not-found]

        source_image = _image_for_opencv(source, source_mask)
        reference_image = _image_for_opencv(reference, reference_mask)
        source_cv_mask = (
            None if source_mask is None else np.asarray(source_mask, dtype=np.uint8) * 255
        )
        reference_cv_mask = (
            None if reference_mask is None else np.asarray(reference_mask, dtype=np.uint8) * 255
        )
        detector = cv2.SIFT_create(nfeatures=int(parameters.values.get("max_features", 0)))
        source_keypoints, source_descriptors = detector.detectAndCompute(
            source_image, source_cv_mask
        )
        reference_keypoints, reference_descriptors = detector.detectAndCompute(
            reference_image, reference_cv_mask
        )
        if source_descriptors is None or reference_descriptors is None:
            return ()
        ratio = float(parameters.values.get("ratio_test", 0.75))
        if not 0.0 < ratio < 1.0:
            raise ValueError("SIFT ratio_test must lie strictly between zero and one")
        pairs = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False).knnMatch(
            source_descriptors, reference_descriptors, k=2
        )
        records: list[CorrespondenceRecord] = []
        for index, pair in enumerate(pairs):
            if not pair:
                continue
            match = pair[0]
            source_point = source_keypoints[match.queryIdx].pt
            reference_point = reference_keypoints[match.trainIdx].pt
            source_pixel = SourcePixel(line=float(source_point[1]), sample=float(source_point[0]))
            reference_pixel = ReferencePixel(
                line=float(reference_point[1]), sample=float(reference_point[0])
            )
            displacement = (
                reference_pixel.line - source_pixel.line,
                reference_pixel.sample - source_pixel.sample,
            )
            accepted = len(pair) >= 2 and match.distance < ratio * pair[1].distance
            records.append(
                CorrespondenceRecord(
                    match_id=f"sift-{index:08d}",
                    job_id=job_id,
                    algorithm=provenance.algorithm,
                    algorithm_version=provenance.version,
                    selection_reason=(
                        "Lowe ratio-test SIFT descriptor pair"
                        if accepted
                        else "SIFT descriptor pair rejected by Lowe ratio test"
                    ),
                    source_pixel=source_pixel,
                    reference_pixel=reference_pixel,
                    raw_score=1.0 / (1.0 + float(match.distance)),
                    prior_displacement_px=prior.displacement_px,
                    residual_from_prior_px=prior.residual_at(source_pixel, displacement),
                    local_warp_jacobian=prior.local_warp_jacobian,
                    is_candidate=accepted,
                    point_role=PointRole.CANDIDATE if accepted else PointRole.REJECTED,
                    rejection_reason=(
                        None
                        if accepted
                        else "SIFT descriptor pair did not pass the configured Lowe ratio test"
                    ),
                    input_digest=input_digest,
                    reference_digest=reference_digest,
                    parameter_set_digest=parameters.parameter_set_digest,
                )
            )
        return tuple(records)


class RiftMatcher:
    """Operational RIFT-class structural baseline, optionally replaced by a plugin.

    The built-in path matches gradient magnitude (rather than radiance) with
    the same mask-aware NCC search.  It is intentionally labelled
    ``rift_class_gradient_ncc``: this is a reproducible structural baseline,
    not an assertion that it is an implementation of any external RIFT code.
    """

    def __init__(self, backend: RiftBackend | None = None) -> None:
        self._backend = backend

    @property
    def provenance(self) -> AlgorithmProvenance:
        if self._backend is None:
            return AlgorithmProvenance(
                algorithm="rift_class_gradient_ncc",
                version="builtin-1",
                license_expression="Apache-2.0",
                dependency=None,
                available=True,
            )
        return self._backend.provenance

    def match(
        self,
        source: npt.NDArray[np.float64],
        reference: npt.NDArray[np.float64],
        *,
        source_mask: npt.NDArray[np.bool_] | None,
        reference_mask: npt.NDArray[np.bool_] | None,
        prior: MatchPrior,
        parameters: MatchParameters,
        job_id: str,
        input_digest: str,
        reference_digest: str,
    ) -> tuple[CorrespondenceRecord, ...]:
        if self._backend is not None:
            return self._backend.match(
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
        if source.ndim != 2 or reference.ndim != 2:
            raise ValueError("RIFT-class gradient baseline requires 2-D images")
        source_gradient = np.hypot(*np.gradient(source))
        reference_gradient = np.hypot(*np.gradient(reference))
        records = NccMatcher().match(
            source_gradient,
            reference_gradient,
            source_mask=source_mask,
            reference_mask=reference_mask,
            prior=prior,
            parameters=parameters,
            job_id=job_id,
            input_digest=input_digest,
            reference_digest=reference_digest,
        )
        provenance = self.provenance
        return tuple(
            record.model_copy(
                update={
                    "algorithm": provenance.algorithm,
                    "algorithm_version": provenance.version,
                    "selection_reason": "gradient-magnitude structural "
                    + (record.selection_reason or "candidate"),
                }
            )
            for record in records
        )
