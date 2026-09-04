"""Mask- and prior-aware coarse phase-correlation matching (WP-04 task 2).

This baseline estimates one whole-image, integer-pixel translation.  It does
not perform sub-pixel peak fitting: refinement belongs to WP-08.  The source
and reference arrays must have the same shape because WP-03's pyramid and
tile-resampling infrastructure does not exist yet.

The returned correspondence is anchored at the geometric centre of the
source array, ``((height - 1) / 2, (width - 1) / 2)``.  Its reference position
is that centre plus the recovered ``(dy, dx)`` displacement.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from selene_core.match.correspondence import CorrespondenceRecord, PointRole
from selene_core.match.protocol import MatchParameters, MatchPrior
from selene_core.types import ReferencePixel, SourcePixel

__all__ = ["PhaseCorrelationMatcher"]

_ALGORITHM = "phase_correlation"
_ALGORITHM_VERSION = "1.0"


def _validate_image(name: str, image: npt.NDArray[np.float64]) -> None:
    if image.ndim != 2:
        raise ValueError(f"{name} must be a 2D array, got shape {image.shape!r}")
    if image.size == 0:
        raise ValueError(f"{name} must not be empty")
    if not np.all(np.isfinite(image)):
        raise ValueError(f"{name} must contain only finite values")


def _validate_mask(
    name: str,
    mask: npt.NDArray[np.bool_] | None,
    expected_shape: tuple[int, int],
) -> None:
    if mask is not None and mask.shape != expected_shape:
        raise ValueError(
            f"{name} shape {mask.shape!r} does not match image shape {expected_shape!r}"
        )


def _centre_masked(
    image: npt.NDArray[np.float64], mask: npt.NDArray[np.bool_] | None
) -> npt.NDArray[np.float64]:
    valid = np.ones(image.shape, dtype=np.bool_) if mask is None else mask
    if not np.any(valid):
        raise ValueError("a phase-correlation mask must contain at least one valid pixel")

    # Filling invalid pixels with zero *after* subtracting the valid-pixel
    # mean avoids turning a non-zero nodata fill into a dominant FFT edge.
    centred = np.zeros(image.shape, dtype=np.float64)
    valid_values = image[valid]
    centred[valid] = valid_values - float(np.mean(valid_values))
    return centred


def _signed_fft_offsets(length: int) -> npt.NDArray[np.int64]:
    indices = np.arange(length, dtype=np.int64)
    return np.where(indices <= length // 2, indices, indices - length)


class PhaseCorrelationMatcher:
    """Recover one coarse integer translation using normalized FFT phase."""

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
        """Return the array-centre correspondence for the recovered shift."""
        _validate_image("source", source)
        _validate_image("reference", reference)
        if source.shape != reference.shape:
            raise ValueError(
                "phase correlation requires source and reference to have identical shapes, "
                f"got {source.shape!r} and {reference.shape!r}"
            )
        _validate_mask("source_mask", source_mask, source.shape)
        _validate_mask("reference_mask", reference_mask, reference.shape)

        source_work = _centre_masked(source, source_mask)
        reference_work = _centre_masked(reference, reference_mask)

        # reference * conj(source) gives the displacement that maps a source
        # coordinate into the reference frame (the record's sign convention).
        cross_power = np.fft.fft2(reference_work) * np.conj(np.fft.fft2(source_work))
        magnitude = np.abs(cross_power)
        normalized = np.divide(
            cross_power,
            magnitude,
            out=np.zeros_like(cross_power),
            where=magnitude > np.finfo(np.float64).eps,
        )
        surface = np.abs(np.fft.ifft2(normalized))

        height, width = source.shape
        dy_grid = _signed_fft_offsets(height).reshape(height, 1)
        dx_grid = _signed_fft_offsets(width).reshape(1, width)
        centre_line = (height - 1) / 2.0
        centre_sample = (width - 1) / 2.0
        centre_source_pixel = SourcePixel(line=centre_line, sample=centre_sample)
        eligible = np.ones(source.shape, dtype=np.bool_)
        if prior.search_radius_px is not None and (
            prior.displacement_px is not None or prior.local_warp_jacobian is not None
        ):
            prior_dy, prior_dx = prior.displacement_at(centre_source_pixel)
            radius_squared = prior.search_radius_px**2
            eligible = (dy_grid - prior_dy) ** 2 + (dx_grid - prior_dx) ** 2 <= radius_squared
            if not np.any(eligible):
                raise ValueError(
                    "phase-correlation prior search region contains no integer displacement"
                )

        search_surface = np.where(eligible, surface, -np.inf)
        peak_index = np.unravel_index(int(np.argmax(search_surface)), search_surface.shape)
        peak_y, peak_x = int(peak_index[0]), int(peak_index[1])
        dy_px = int(dy_grid[peak_y, 0])
        dx_px = int(dx_grid[0, peak_x])

        peak = float(surface[peak_y, peak_x])
        background = surface[eligible].copy()
        background[int(np.argmax(background))] = 0.0
        # Peak-to-mean-background is stable for the impulse-like phase
        # surface and exposes a weak/flat solution as a score near one.
        background_mean = float(np.mean(background))
        raw_score = peak / max(background_mean, np.finfo(np.float64).eps)

        displacement = (float(dy_px), float(dx_px))
        source_pixel = centre_source_pixel
        residual = prior.residual_at(source_pixel, displacement)

        return (
            CorrespondenceRecord(
                job_id=job_id,
                algorithm=_ALGORITHM,
                algorithm_version=_ALGORITHM_VERSION,
                selection_reason="whole-frame coarse phase-correlation peak",
                source_pixel=source_pixel,
                reference_pixel=ReferencePixel(
                    line=centre_line + displacement[0],
                    sample=centre_sample + displacement[1],
                ),
                raw_score=raw_score,
                prior_displacement_px=prior.displacement_px,
                residual_from_prior_px=residual,
                local_warp_jacobian=prior.local_warp_jacobian,
                is_candidate=True,
                point_role=PointRole.CANDIDATE,
                input_digest=input_digest,
                reference_digest=reference_digest,
                parameter_set_digest=parameters.parameter_set_digest,
            ),
        )
