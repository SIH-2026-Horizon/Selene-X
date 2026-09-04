# Geometry and reference readiness

WP-03 accepts a sensor-pose provider only when it carries explicit kernel
furnishing evidence. A missing optional SPICE dependency, missing terrain
intercept, unfurnished kernel, or unvalidated real-scene comparison produces an
unavailable/not-validated state; none is replaced with synthetic geometry.
`externally_validated` additionally requires immutable independent-reference
ID/hash, validation-process ID, and a positive covariance. Text labels alone
cannot qualify a route.

Footprints are sampled on the boundary and interior, unwrap east-positive lunar
longitude across the antimeridian, and use polar stereographic projections at
high latitude. They become externally validated only after ordered comparison
against independently supplied boundary/control points inside a stated metre
tolerance.

The base build uses spherical lunar projection formulas and fully serializes
central meridian, origin, standard parallel, radius, frame, and longitude
direction. Optional GIS libraries may consume that CRS, but do not change it.

Pyramids apply a supplied instrument PSF sigma where available; otherwise they
record a Gaussian fallback before each downsample/resample. A paired pyramid is
resampled at an exact common target GSD, and target levels never use a `ceil`
decimation that would be unexpectedly coarser than requested.

SLDEM2015 is a coarse terrain support product (declared approximately 60°S to
60°N), never a high-frequency texture reference. Polar terrain or LOLA must
declare coverage before selection. LROC NAC and SELENE TC remain image
references even if controlled; only a named control-network asset can enable an
absolute-control route.

Route preflight requires independent geometry validation, projected overlap,
compatible GSD/search bounds, a quantified warp prior when one is supplied,
and declared control with coverage and positive uncertainty by default. This is intentionally more
strict than exploratory matching; a caller may provide an explicit policy for a
limited research route, whose output still records all limitations.
