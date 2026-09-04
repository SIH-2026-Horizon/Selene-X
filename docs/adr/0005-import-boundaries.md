# ADR-0005: Package import boundaries

- **Status:** accepted
- **Date:** 2026-08-27
- **Blocks:** WP-01 repository foundation; enforced in CI for every later work package
- **Related decisions:** R-014

## Context

The scientific core must run with no database, queue, or browser, and the API must not grow a second scientific implementation. Import direction is the only mechanism that keeps this true as the service surface expands.

## Decision

Six `import-linter` contracts in `.importlinter` govern the four workspace
packages (`selene_core`, `selene_client`, `selene_service`, `selene_worker`):

1. `core-is-independent` (forbidden): `selene_core` must not import
   `selene_client`, `selene_service`, or `selene_worker`.
2. `core-has-no-infrastructure` (forbidden): `selene_core` must not import
   HTTP, ORM, queue, cache, or object-store infrastructure — `fastapi`,
   `starlette`, `uvicorn`, `sqlalchemy`, `alembic`, `psycopg`, `asyncpg`,
   `redis`, `celery`, `kombu`, `boto3`, `botocore`, `httpx`, `requests`, or
   `aiohttp`.
3. `client-does-not-import-service` (forbidden): `selene_client` must not
   import `selene_service` or `selene_worker`.
4. `worker-does-not-import-service` (forbidden): `selene_worker` must not
   import `selene_service`.
5. `core-layers` (layers): within `selene_core`, `pipeline` sits above
   `products`, `metrics`, `adjust`, `refine`, `select`, `match`, `features`,
   `preprocess`, `reference`, `geometry`, `ingest`, and `types`, in that
   order — a later-listed layer may not import an earlier-listed one.
6. `service-and-worker-use-core-public-api` (forbidden): service and worker
   packages may import `selene_core` itself, the documented public facade, but
   may not import any `selene_core.*` implementation module. Public contracts
   are re-exported from `selene_core` and `selene_core.pipeline` for callers
   that need the local runner protocol.

CI's `python` job runs `uv run lint-imports` (the "Enforce import boundaries"
step) on every push and pull request, after linting and type-checking and
before the test steps, so a forbidden import fails the build before tests run.

## Consequences

A new scientific stage can depend on `selene_core.pipeline` and the layers
below it without ever importing service, transport, or persistence code,
because the layering contract makes that the only direction that type-checks
against the linter. The API and worker are free to depend on `selene_core`,
but `selene_core` can never be made to depend on them back, so a "just this
once" import from `selene_core` into `selene_service` to reach a shared helper
is now a CI failure, not a matter of review taste. Adding a new HTTP client,
ORM, or queue library to `selene_core` — even transitively through a helper
module — fails CI the moment `lint-imports` runs, forcing that logic to live
in `selene_client`/`selene_service`/`selene_worker` instead. Reordering
`selene_core`'s internal packages so that, say, `types` imported `geometry`
is likewise a CI failure under the `core-layers` contract.

## Verification

`.importlinter`'s six contracts, enforced by the "Enforce import boundaries"
CI step (`.github/workflows/ci.yml`, `uv run lint-imports`).

## Alternatives considered

Not recorded; this ADR ratifies an implementation decision already embodied in merged code rather than a forward decision with a considered alternative set.
