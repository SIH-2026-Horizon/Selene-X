# selene_core

The SELENE-XR scientific core. Ingestion, geometry, reference preparation,
preprocessing, feature channels, matching, verification and selection,
sub-pixel refinement, sensor adjustment, metrics, product writing, and the
local stage runner.

**Status:** skeleton only. No stage is implemented.

## Rules

- No dependency on HTTP, ORM, queues, Redis, object-store SDKs, or UI code
  (ADR-005, enforced by `.importlinter` in CI).
- The CLI and the REST service both call these functions. Neither holds a
  second scientific implementation.
- The package must run in a clean local environment with no database, queue, or
  browser.
- Original input bytes and geometry are immutable; corrected geometry and
  registered rasters are named derived variants.
- Every raster stage is tiled and declares memory, scratch, validity, and merge
  behaviour through the shared `TileSpec`.

## Local models

Install the learned extra and point `SXR_MODEL_ROOT` at a mounted registry:

```bash
python -m pip install -e '.[learned]'
export SXR_MODEL_ROOT=../../model
```

`selene_core.load_local_model("selene_matcher", device="cuda")` verifies the
active artifact SHA-256 and instantiates the matching architecture. Bias,
IIRS-bandweight, and render-residual artifacts use the same API.
