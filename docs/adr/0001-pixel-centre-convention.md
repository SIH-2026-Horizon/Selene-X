# ADR-0001: Internal pixel-centre convention and named ISIS/GDAL conversions

- **Status:** accepted
- **Date:** 2026-08-27
- **Blocks:** WP-01 typed coordinates; WP-03 geometry; every raster stage
- **Related decisions:** R-010

## Context

ISIS, GDAL, CSM, and array indexing do not agree on where a pixel coordinate falls. An unstated convention produces a plausible half-pixel error that survives every internal round trip. Inline half-pixel corrections are forbidden; conversions must be named, tested, and documented.

## Decision

The internal convention is zero-based and centre-referenced: the centre of the
first pixel along an axis is `line = 0.0, sample = 0.0`
(`PixelConvention.SELENE_INTERNAL`, `INTERNAL_PIXEL_CONVENTION` in
`selene_core.types`). `SourcePixel` and `ReferencePixel` hold only this
convention; there is no other way to construct or read one.

Every other convention this codebase must interoperate with is named and its
first-pixel-centre offset is recorded in one table
(`_FIRST_PIXEL_CENTRE`): `ARRAY_INDEX` (NumPy indexing, 0.0), `CSM` (Community
Sensor Model, 0.5), `GDAL_CORNER` (GDAL geotransform pixel/line space,
measured from the outer corner, 0.5), and `ISIS` (one-based,
centre-referenced, 1.0). `convert_pixel_coordinate(value, source=, target=)` is
the single function that converts one axis between any two of these
conventions, by table lookup and subtraction — not by a formula restated at
each call site. `SourcePixel`/`ReferencePixel` expose this only through named
constructors (`from_isis`, `from_csm`, `from_gdal`, `from_array_index`,
`from_convention`) and named exporters (`to_isis`, `to_csm`, `to_gdal`,
`to_array_index`, `to_convention`); there is no other sanctioned path in or out
of the internal convention. Inline half-pixel arithmetic anywhere else is not
a stylistic preference but a violation of this decision.

## Consequences

Adding support for a new tool's pixel convention means adding one entry to
`_FIRST_PIXEL_CENTRE` and, if needed, one pair of named
constructor/exporter methods — not touching call sites elsewhere. Any code
outside `convert_pixel_coordinate` that adds or subtracts `0.5` or `1.0` to a
`line`/`sample`/pixel value is now a review rejection, because it is exactly
the kind of inline correction this convention exists to make impossible to
express by accident. `WP-03` still owes verification of the ISIS, CSM, and
GDAL offsets against the real tools on a real product before any geometry
claim may depend on them (`convert_pixel_coordinate`'s docstring records this
as a stated exit criterion, not an assumption already made).

## Verification

`tests/unit/test_types_pixels.py` — exercises `INTERNAL_PIXEL_CONVENTION`,
`convert_pixel_coordinate` across every convention pair, and the
`SourcePixel`/`ReferencePixel` named constructors and exporters.

## Alternatives considered

Not recorded; this ADR ratifies an implementation decision already embodied in merged code rather than a forward decision with a considered alternative set.
