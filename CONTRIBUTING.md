# Contributing to SELENE-XR

Read [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) before changing
anything. It is the governing document. Where the design sources disagree,
`docs/context/SELENE-XR-Technical-Verification.md` takes precedence.

## Current status

The repository includes implemented pipeline foundations, contracts, fixtures,
and baselines, plus a standalone `web/` console prototype. The Vite/React/
TypeScript/Tailwind console uses local mock data and a mock job stream; it is
not connected to an implemented backend or scientific production route and
does not prove mission-data results, performance, or scientific validation.
Nothing described in the plan may be represented as satisfying a work package
until its exit criteria are met and the evidence is committed or linked from a
versioned benchmark manifest.

## Environment

The web workspace requires Node.js `^22.22.2 || ^24.15.0 || >=26.0.0` to
support its lockfile-pinned runtime and test dependencies. It pins pnpm
`10.34.5` in `web/package.json`; Corepack reads that pin, so pnpm does not need
to be installed globally. Some Node distributions omit Corepack. If
`corepack --version` is unavailable, bootstrap it once before continuing:

```bash
npm install --global corepack@0.34.5
corepack enable
```

```bash
uv sync --all-packages --all-groups   # Python workspace
(
  cd web
  corepack pnpm install --frozen-lockfile
)
```

## Local checks

Current CI runs the Python checks below but does not yet run the `web/`
workspace. Run both sets locally before submitting a change:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run lint-imports
uv run pytest -m "unit or property"
uv run pytest -m e2e
(
  cd web
  corepack pnpm lint
  corepack pnpm test
  corepack pnpm build
)
```

## Rules that a review must enforce

**Architecture**

- `selene_core` imports no HTTP, ORM, queue, cache, object-store, or UI code.
  `.importlinter` enforces this; do not add an exemption to make a change fit.
- The API calls the same core functions as the CLI. A second scientific
  implementation inside a router is a rejection.
- Original input bytes and geometry are immutable. Corrected outputs are named
  derived variants.
- Every raster stage is tiled and declares its memory, scratch, validity, and
  merge behaviour. No stage loads a full OHRC frame.
- Stage and final outputs are written to a temporary location, flushed,
  checksummed, schema-validated, and atomically published.

**Correctness**

- Coordinates use the typed contracts in `selene_core.types`. Inline half-pixel
  corrections are forbidden; conversions are named, tested, and documented.
- Angles carry `_deg` or `_rad`; distances carry `_m`, `_px`, or `_m2`. Times
  are UTC at interfaces and ephemeris time internally.
- A metric that cannot be computed is `null` with a reason. Never zero, never
  omitted.
- A missing applicable hard-gate metric is a rejection, not a pass.

**Evidence**

- An ADR listed in section 5.3 of the plan is accepted before the code it
  governs is merged.
- Every quantitative claim in the README, an issue, or the presentation links
  to a benchmark run ID and an immutable report through the claim ledger.
- A synthetic result is never presented as real mission-data accuracy.
- Held-out check points stay out of fitting and tuning. Tuning happens on the
  development split.
- An unsupported or experimental route is marked as such in machine-readable
  status and in user documentation.

**Data and security**

- Mission products, credentials, SPICE kernels, model weights, and generated
  rasters never enter Git. Commit manifests, checksums, acquisition
  instructions, small permitted fixtures, and expected results.
- Label and raster parsing runs with DTD loading, entity expansion, and
  external entity resolution disabled, under size and recursion limits.
- Native tools are invoked with argument arrays through a shell-disabled
  subprocess API with an allow-listed environment and resource limits.
- Logs carry run, product, route, stage, algorithm, and trace identifiers.
  They never carry imagery, tokens, credentials, or signed URLs.

## Tests

Layers, markers, and the numerical tolerance policy are described in
[`tests/README.md`](tests/README.md). Every numerical comparison declares
units, frame, tolerance, and the justification for that tolerance.

## Commits and branches

Work on a branch and open a pull request. A pull request states which work
package it advances and which exit criteria it does or does not satisfy.
