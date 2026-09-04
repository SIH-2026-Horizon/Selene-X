# Tests

Layers follow section 9 of the implementation plan. Each directory maps to a
pytest marker declared in the root `pyproject.toml`.

| Directory | Marker | Required coverage |
| --- | --- | --- |
| `unit/` | `unit` | Coordinate conversions, local Jacobians, PSF kernels, known shifts, covariance validity, robust residuals, metric formulas, and the parser fixtures for XXE, entity expansion, malformed PVL, decompression bombs, path traversal, raster driver restrictions, and hostile filenames |
| `property/` | `property` | Projection round trips, metric bounds, mask and eligibility invariants, deterministic selection, schema round trips |
| `integration/` | `integration` | A tiny complete registration through real local dependencies and output writers, and adapter contract tests against common fixtures |
| `science/` | `science` | Frozen controlled, real, and adversarial scenes with per-route and per-stratum results, plus ablations for the metadata prior, PSF matching, each auxiliary channel, the learned challenger, coverage, refinement, covariance, and adjustment |
| `security/` | `security` | Hostile inputs, upload limits, injection, secret handling, and authorization coverage |
| `e2e/` | `e2e` | Product validation, preflight, run, progress, review, export, output validation, and a failure case, through CLI, API, and UI |

Additional markers: `requires_data` for anything needing an uncommitted
benchmark product, and `requires_gpu` for accelerator-dependent tests.

## Numerical tolerance policy

- Every comparison declares units, frame, absolute or relative tolerance, and
  the justification for that tolerance.
- Exact equality is reserved for hashes, schemas, identifiers, and
  intentionally deterministic serialised data.
- Coordinate and derivative tests use a tolerance based on numerical
  conditioning.
- Image, render, and matcher tests use physically meaningful pixel or radiance
  tolerances.
- CPU/GPU parity is reported at the tolerance actually measured, never assumed.

No tests exist yet.
