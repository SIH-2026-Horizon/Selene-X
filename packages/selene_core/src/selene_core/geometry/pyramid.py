"""Common-resolution image pyramids with explicit anti-aliasing provenance."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

__all__ = [
    "EligibilityMasks",
    "PairedPyramidLevel",
    "PyramidLevel",
    "build_common_resolution_pyramid",
    "build_paired_common_resolution_pyramid",
    "combine_eligibility_masks",
    "conservative_downsample_mask",
    "derive_eligibility_masks",
    "gaussian_blur",
]

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


def gaussian_blur(image: npt.ArrayLike, sigma_px: float) -> FloatArray:
    """Blur an image separably before decimation; NumPy fallback when no PSF exists."""
    source = np.asarray(image, dtype=np.float64)
    if source.ndim != 2 or not math.isfinite(sigma_px) or sigma_px < 0:
        raise ValueError("image must be 2-D and sigma_px must be finite and non-negative")
    if sigma_px == 0:
        return source.copy()
    radius = max(1, math.ceil(3.0 * sigma_px))
    axis = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(axis * axis) / (2 * sigma_px * sigma_px))
    kernel /= kernel.sum()
    padded_x = np.pad(source, ((0, 0), (radius, radius)), mode="edge")
    horizontal = np.apply_along_axis(
        lambda values: np.convolve(values, kernel, mode="valid"), 1, padded_x
    )
    padded_y = np.pad(horizontal, ((radius, radius), (0, 0)), mode="edge")
    return np.apply_along_axis(
        lambda values: np.convolve(values, kernel, mode="valid"), 0, padded_y
    )


@dataclass(frozen=True, slots=True)
class PyramidLevel:
    image: FloatArray
    pixel_size_m: float
    decimation: int
    antialias_method: str
    psf_source: str
    psf_sigma_uncertainty_px: float | None = None
    grid_origin_x_m: float = 0.0
    grid_origin_y_m: float = 0.0
    eligibility_mask: BoolArray | None = None

    def __post_init__(self) -> None:
        if self.image.ndim != 2 or self.image.size == 0:
            raise ValueError("pyramid image must be a non-empty 2-D array")
        if not math.isfinite(self.pixel_size_m) or self.pixel_size_m <= 0 or self.decimation < 1:
            raise ValueError("pyramid pixel size must be positive and decimation at least one")
        if self.psf_sigma_uncertainty_px is not None and (
            not math.isfinite(self.psf_sigma_uncertainty_px) or self.psf_sigma_uncertainty_px < 0
        ):
            raise ValueError("PSF sigma uncertainty must be non-negative when supplied")
        if not math.isfinite(self.grid_origin_x_m) or not math.isfinite(self.grid_origin_y_m):
            raise ValueError("pyramid grid origin must be finite")
        image = np.array(self.image, dtype=np.float64, copy=True)
        image.setflags(write=False)
        object.__setattr__(self, "image", image)
        if self.eligibility_mask is not None:
            mask = np.array(self.eligibility_mask, dtype=bool, copy=True)
            if mask.shape != image.shape:
                raise ValueError("pyramid eligibility mask must match image shape")
            mask.setflags(write=False)
            object.__setattr__(self, "eligibility_mask", mask)

    @property
    def extent_m(self) -> tuple[float, float]:
        """Grid edge-to-edge width/height; origin denotes the first pixel centre."""
        return (self.image.shape[1] * self.pixel_size_m, self.image.shape[0] * self.pixel_size_m)

    @property
    def affine(self) -> tuple[float, float, float, float, float, float]:
        """Centre-aware north-up affine with the outer corner shifted half a pixel."""
        return (
            self.pixel_size_m,
            0.0,
            self.grid_origin_x_m - self.pixel_size_m / 2,
            0.0,
            -self.pixel_size_m,
            self.grid_origin_y_m + self.pixel_size_m / 2,
        )


def conservative_downsample_mask(mask: npt.ArrayLike, factor: int) -> BoolArray:
    """A target pixel is eligible only when every contributing input is eligible."""
    source = np.asarray(mask, dtype=bool)
    if source.ndim != 2 or factor < 1:
        raise ValueError("mask must be 2-D and factor positive")
    rows = math.ceil(source.shape[0] / factor)
    columns = math.ceil(source.shape[1] / factor)
    result = np.empty((rows, columns), dtype=bool)
    for row in range(rows):
        for column in range(columns):
            result[row, column] = bool(
                np.all(
                    source[
                        row * factor : (row + 1) * factor,
                        column * factor : (column + 1) * factor,
                    ]
                )
            )
    result.setflags(write=False)
    return result


def build_common_resolution_pyramid(
    image: npt.ArrayLike,
    *,
    native_gsd_m: float,
    target_gsd_m: float,
    psf_sigma_px: float | None = None,
    psf_sigma_uncertainty_px: float | None = None,
    eligibility_mask: npt.ArrayLike | None = None,
) -> PyramidLevel:
    """Return one target-resolution level, always blurring before decimation.

    Without instrument PSF metadata, uses a Gaussian approximation whose sigma
    is half the additional downsampling width.  The output records that fallback
    so it cannot be misrepresented as calibrated sensor PSF processing.
    """
    if native_gsd_m <= 0 or target_gsd_m <= 0:
        raise ValueError("GSD values must be positive")
    ratio = target_gsd_m / native_gsd_m
    if ratio < 1:
        raise ValueError("target GSD is finer than native data; use an explicit upsampling product")
    # Floor ensures the selected level is never coarser than requested merely
    # because the native ratio was non-integral.  Exact resampling is handled
    # by paired common-resolution output below.
    decimation = max(1, math.floor(ratio))
    if decimation == 1:
        return PyramidLevel(
            np.asarray(image, dtype=np.float64).copy(),
            native_gsd_m,
            1,
            "none",
            "none",
            None,
            eligibility_mask=np.asarray(eligibility_mask, dtype=bool)
            if eligibility_mask is not None
            else None,
        )
    sigma = (
        psf_sigma_px if psf_sigma_px is not None else 0.5 * math.sqrt(decimation * decimation - 1)
    )
    if sigma <= 0 or not math.isfinite(sigma):
        raise ValueError("psf_sigma_px must be finite and positive when supplied")
    blurred = gaussian_blur(image, sigma)
    return PyramidLevel(
        blurred[::decimation, ::decimation].copy(),
        native_gsd_m * decimation,
        decimation,
        "gaussian_blur_before_decimation",
        "instrument_psf" if psf_sigma_px is not None else "gaussian_fallback",
        psf_sigma_uncertainty_px if psf_sigma_px is not None else None,
        eligibility_mask=conservative_downsample_mask(eligibility_mask, decimation)
        if eligibility_mask is not None
        else None,
    )


@dataclass(frozen=True, slots=True)
class PairedPyramidLevel:
    """Source/reference images resampled to exactly one common target GSD."""

    target_gsd_m: float
    source: PyramidLevel
    reference: PyramidLevel


def _resize_bilinear(
    image: FloatArray,
    rows: int,
    columns: int,
    *,
    source_pixel_size_m: float,
    target_pixel_size_m: float,
) -> FloatArray:
    if rows < 1 or columns < 1:
        raise ValueError("resampled image dimensions must be positive")
    target_origin_m = (target_pixel_size_m - source_pixel_size_m) / 2
    row_coordinates = (
        target_origin_m + np.arange(rows, dtype=np.float64) * target_pixel_size_m
    ) / source_pixel_size_m
    column_coordinates = (
        target_origin_m + np.arange(columns, dtype=np.float64) * target_pixel_size_m
    ) / source_pixel_size_m
    intermediate = np.array(
        [np.interp(column_coordinates, np.arange(image.shape[1]), row) for row in image],
        dtype=np.float64,
    )
    return np.array(
        [
            np.interp(row_coordinates, np.arange(image.shape[0]), intermediate[:, column])
            for column in range(columns)
        ],
        dtype=np.float64,
    ).T


def _conservative_resample_mask(
    mask: npt.ArrayLike, *, ratio: float, rows: int, columns: int
) -> BoolArray:
    """Map a mask to an edge-aligned target grid without inventing eligibility."""
    source = np.asarray(mask, dtype=bool)
    result = np.empty((rows, columns), dtype=bool)
    for row in range(rows):
        start_row = math.floor(row * ratio)
        stop_row = math.ceil((row + 1) * ratio)
        for column in range(columns):
            start_column = math.floor(column * ratio)
            stop_column = math.ceil((column + 1) * ratio)
            result[row, column] = bool(
                np.all(source[start_row:stop_row, start_column:stop_column])
            )
    result.setflags(write=False)
    return result


def _resample_common(
    image: npt.ArrayLike,
    *,
    native_gsd_m: float,
    target_gsd_m: float,
    psf_sigma_px: float | None,
    psf_sigma_uncertainty_px: float | None,
    eligibility_mask: npt.ArrayLike | None = None,
) -> PyramidLevel:
    source = np.asarray(image, dtype=np.float64)
    if source.ndim != 2:
        raise ValueError("paired pyramid images must be 2-D")
    if eligibility_mask is not None and np.asarray(eligibility_mask).shape != source.shape:
        raise ValueError("paired eligibility mask must match its image shape")
    ratio = target_gsd_m / native_gsd_m
    if ratio < 1:
        raise ValueError("common target GSD must not be finer than either native image")
    if ratio > 1:
        sigma = psf_sigma_px if psf_sigma_px is not None else 0.5 * math.sqrt(ratio * ratio - 1)
        filtered = gaussian_blur(source, sigma)
        method = "gaussian_blur_before_resample"
        provenance = "instrument_psf" if psf_sigma_px is not None else "gaussian_fallback"
    else:
        filtered, method, provenance = source, "none", "none"
    exact_rows = source.shape[0] / ratio
    exact_columns = source.shape[1] / ratio
    if (
        abs(exact_rows - round(exact_rows)) > 1e-9
        or abs(exact_columns - round(exact_columns)) > 1e-9
    ):
        raise ValueError("target GSD cannot represent the source grid extent at pixel centres")
    rows = max(1, round(exact_rows))
    columns = max(1, round(exact_columns))
    return PyramidLevel(
        _resize_bilinear(
            filtered,
            rows,
            columns,
            source_pixel_size_m=native_gsd_m,
            target_pixel_size_m=target_gsd_m,
        ),
        target_gsd_m,
        1,
        method,
        provenance,
        psf_sigma_uncertainty_px if psf_sigma_px is not None else None,
        grid_origin_x_m=(target_gsd_m - native_gsd_m) / 2,
        grid_origin_y_m=(target_gsd_m - native_gsd_m) / 2,
        eligibility_mask=(
            _conservative_resample_mask(
                eligibility_mask, ratio=ratio, rows=rows, columns=columns
            )
            if eligibility_mask is not None
            else None
        ),
    )


def build_paired_common_resolution_pyramid(
    source_image: npt.ArrayLike,
    reference_image: npt.ArrayLike,
    *,
    source_native_gsd_m: float,
    reference_native_gsd_m: float,
    levels: int = 1,
    source_psf_sigma_px: float | None = None,
    reference_psf_sigma_px: float | None = None,
    source_psf_sigma_uncertainty_px: float | None = None,
    reference_psf_sigma_uncertainty_px: float | None = None,
    source_eligibility_mask: npt.ArrayLike | None = None,
    reference_eligibility_mask: npt.ArrayLike | None = None,
) -> tuple[PairedPyramidLevel, ...]:
    """Build paired levels at exact common GSDs, with blur-before-resample provenance."""
    if levels < 1:
        raise ValueError("levels must be at least one")
    if source_native_gsd_m <= 0 or reference_native_gsd_m <= 0:
        raise ValueError("native GSD values must be positive")
    base_target = max(source_native_gsd_m, reference_native_gsd_m)
    output: list[PairedPyramidLevel] = []
    for level in range(levels):
        target = base_target * (2**level)
        output.append(
            PairedPyramidLevel(
                target,
                _resample_common(
                    source_image,
                    native_gsd_m=source_native_gsd_m,
                    target_gsd_m=target,
                    psf_sigma_px=source_psf_sigma_px,
                    psf_sigma_uncertainty_px=source_psf_sigma_uncertainty_px,
                    eligibility_mask=source_eligibility_mask,
                ),
                _resample_common(
                    reference_image,
                    native_gsd_m=reference_native_gsd_m,
                    target_gsd_m=target,
                    psf_sigma_px=reference_psf_sigma_px,
                    psf_sigma_uncertainty_px=reference_psf_sigma_uncertainty_px,
                    eligibility_mask=reference_eligibility_mask,
                ),
            )
        )
    return tuple(output)


@dataclass(frozen=True, slots=True)
class EligibilityMasks:
    """Per-pixel physical eligibility; all masks must share a shape."""

    valid_source: BoolArray
    valid_reference: BoolArray
    overlap: BoolArray
    terrain_supported: BoolArray
    illumination_supported: BoolArray
    eligible: BoolArray

    def __post_init__(self) -> None:
        arrays = (
            self.valid_source,
            self.valid_reference,
            self.overlap,
            self.terrain_supported,
            self.illumination_supported,
            self.eligible,
        )
        if arrays[0].ndim != 2 or any(array.shape != arrays[0].shape for array in arrays):
            raise ValueError("eligibility masks must be same-shaped 2-D arrays")
        for name, array in zip(
            (
                "valid_source",
                "valid_reference",
                "overlap",
                "terrain_supported",
                "illumination_supported",
                "eligible",
            ),
            arrays,
            strict=True,
        ):
            frozen = np.array(array, dtype=bool, copy=True)
            frozen.setflags(write=False)
            object.__setattr__(self, name, frozen)


def combine_eligibility_masks(
    *,
    valid_source: npt.ArrayLike,
    valid_reference: npt.ArrayLike,
    overlap: npt.ArrayLike,
    terrain_supported: npt.ArrayLike,
    illumination_supported: npt.ArrayLike,
) -> EligibilityMasks:
    arrays = tuple(
        np.asarray(value, dtype=bool)
        for value in (
            valid_source,
            valid_reference,
            overlap,
            terrain_supported,
            illumination_supported,
        )
    )
    if not arrays or arrays[0].ndim != 2 or any(array.shape != arrays[0].shape for array in arrays):
        raise ValueError("all eligibility masks must be same-shaped 2-D arrays")
    return EligibilityMasks(
        valid_source=arrays[0],
        valid_reference=arrays[1],
        overlap=arrays[2],
        terrain_supported=arrays[3],
        illumination_supported=arrays[4],
        eligible=np.logical_and.reduce(arrays),
    )


def derive_eligibility_masks(
    *,
    source_valid: npt.ArrayLike,
    reference_valid: npt.ArrayLike,
    projected_overlap: npt.ArrayLike,
    terrain_available: npt.ArrayLike,
    illumination_acceptable: npt.ArrayLike,
) -> EligibilityMasks:
    """Derive eligibility from named physical input masks rather than a pre-made grid."""
    return combine_eligibility_masks(
        valid_source=source_valid,
        valid_reference=reference_valid,
        overlap=projected_overlap,
        terrain_supported=terrain_available,
        illumination_supported=illumination_acceptable,
    )
