"""Calibration checks, PSF/MTF handling, pyramids, and masks (WP-03).

Responsibilities:

* Common-resolution pyramids built from local GSD, blurring before
  downsampling so that aliasing cannot be introduced.
* Measured MTF/PSF matching once D-005 is resolved, and a documented fallback
  with a labelled uncertainty until then.
* Residual local scale and affine range estimation for the matcher, treating
  metadata as a bound rather than an exact value.
* Overlap, nodata, terrain-coverage, and preliminary illumination eligibility
  masks.
* The shared tiling contract: every raster stage declares core window, halo,
  valid window, merge rule, and memory and scratch budgets.
"""

__all__: list[str] = []
