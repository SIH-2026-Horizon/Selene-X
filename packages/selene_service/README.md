# selene_service

The SELENE-XR REST service owns persisted product/run provenance state in
PostgreSQL/PostGIS. It provides typed environment configuration, an application
factory, loopback network-boundary validation, and JSON system endpoints:

- `GET /healthz` reports process liveness without contacting a dependency.
- `GET /readyz` reports PostgreSQL readiness and returns the standard `503`
  error envelope without database details when that dependency is unavailable.
- `GET /api/v1/version` reports the service name, package version, and
  environment. It never returns configuration values or secrets.
- `GET /api/v1/openapi.json` exposes the versioned API contract (the interactive
  documentation UI is intentionally disabled).

The persisted v1 API includes catalog registration/browsing (`/products`), run
creation/browsing (`/runs`), run stages/events/metrics/artifacts, cancellation,
immutable reviews, and `/registration-graphs` (also available as the legacy
`/knowledge-graph` path). Collection routes use opaque cursor pagination.
`POST /runs` stores a canonical parameter manifest and digest, requires
source/reference product records, and supports `Idempotency-Key`.
`GET /products` and `GET /runs` also accept an optional `query` parameter for
case-insensitive literal matching over their own persisted identifier fields;
the response remains a bounded cursor page and never scans additional pages on
behalf of a client.

Semantic knowledge is a separate, unseeded durable graph under `/knowledge`:
`/entities`, `/edges`, `/query`, entity neighbors, and crater-compatible detail
and observation paths read/write only PostgreSQL rows. Entity types and relation
labels are deliberately extensible and support the web vocabulary (for example
`CRATER`, `OBSERVATION`, `PAYLOAD`, `REFERENCE_PRODUCT`, `TERRAIN`,
`MORPHOLOGY_FEATURE`, `REGISTRATION_JOB`, `DATA_PRODUCT`, `OBSERVED_IN`,
`DERIVED_FROM`, and `REGISTERED_WITH`). `/knowledge/query` performs only
case-insensitive literal label/external-ID matching plus exact type/relation
filters; it does not compute or fabricate similarity.

The API never manufactures metrics, stage records, artifacts, images, tie
points, crater data, or graph relationships: those routes return only records a
trusted runner has durably written. A newly registered run is therefore
truthfully `created` with empty runner-result collections. Image bytes remain in
external object storage; products reject server filesystem paths. Importing the
package and creating settings never opens a connection; the application
lifespan creates and disposes the runtime engine/session factory.

## Local development

From the workspace root, install the development environment and run the
focused service tests:

```bash
uv sync --group dev
uv run pytest tests/unit/test_service_app.py
```

To run the controlled local development launcher (which defaults to
`127.0.0.1:8000`), use:

```bash
uv run python -m selene_service
```

Configuration uses `SELENE_SERVICE_*` environment variables. The primary
settings are `BIND_HOST`, `PORT`, `ENVIRONMENT`, `PACKAGE_VERSION`,
`AUTHENTICATION_MODE`, `AUTH_ISSUER_URL`, `AUTH_AUDIENCE`, and `DATABASE_URL`.
For example, use `SELENE_SERVICE_BIND_HOST=::1 SELENE_SERVICE_PORT=8123 uv run
python -m selene_service` for a local IPv6 bind. The controlled launcher owns
the effective socket host and port: it validates `BIND_HOST` before calling
Uvicorn and offers no separate host or port override that could bypass that
check.

## Database migrations

ADR-0014 makes PostgreSQL/PostGIS the service profile's single durable-state
authority. Run Alembic only against a dedicated PostgreSQL database with the
PostGIS extension package installed; the migration environment intentionally
requires an explicit URL and will not fall back to the local development
default.

```bash
export SELENE_SERVICE_DATABASE_URL='postgresql+psycopg://selene_migrator:password@127.0.0.1:5432/selene_test'
uv run alembic -c packages/selene_service/alembic.ini upgrade head
uv run alembic -c packages/selene_service/alembic.ini current
uv run alembic -c packages/selene_service/alembic.ini check
```

The migration role needs ordinary DDL privileges and permission to run
`CREATE EXTENSION IF NOT EXISTS postgis` when PostGIS has not already been
enabled. The runtime role should instead have only `CONNECT`, schema `USAGE`,
and the needed DML privileges on the migrated tables and sequences; it should
not be an extension or schema owner.

For real-database verification, point this test-only variable at an isolated
PostgreSQL/PostGIS database. It applies the actual revisions and proves that
raw SQL cannot update or delete `run_events` and `reviews`:

```bash
SELENE_SERVICE_TEST_DATABASE_URL='postgresql+psycopg://selene_migrator:password@127.0.0.1:5432/selene_test' \
  uv run pytest tests/integration/test_postgres_persistence.py -m integration
```

The test also checks actual ORM/migration drift, transactional run/event
pairing and rollback, ordered optimistic transitions, and database hash
constraints. It skips cleanly when the variable is unset. SQLite is not a
substitute for this verification. Image bytes remain in a filesystem or
S3-compatible store; PostgreSQL stores validated, already-published metadata
only.

## Network boundary

`authentication_mode=unauthenticated` is the safe development default and is
accepted only for `localhost`, an IPv4 loopback address (`127.0.0.0/8`), or
IPv6 loopback (`::1`). Wildcard, LAN, public, and unrecognised host names fail
application construction. Setting `authentication_mode=external` permits a
non-loopback bind as an explicit operator declaration for a future external
authentication boundary. When the optional `SELENE_SERVICE_LOCAL_API_KEY` is
set, the service bootstraps its SHA-256 digest against one configured local
subject and verifies a scoped `X-SELENE-API-Key` for every mutation. The raw
key is never persisted or returned. This narrow mechanism is for the private
local Compose proxy only; it is not OIDC or Keycloak. Do not expose it
publicly until real identity and authorization controls exist.

A third mode, `authentication_mode=session` (ADR-0016), implements real
multi-user operator authentication: individually attributable `user_accounts`
rows with Argon2-hashed passwords, a fixed per-account role
(`analyst`/`reviewer`/`admin`), and revocable server-side sessions carried by
an `httpOnly` cookie. It is implemented and covered by this package's test
suite and is wired into the packaged local Compose profile. Its Nginx proxy
forwards the session cookie and injects no shared API credential; set the
bootstrap Admin credentials described in the local platform runbook before
starting that profile.

The [local platform runbook](../../../docs/runbooks/local-platform.md) describes
the narrowly scoped Docker Compose deployment: the containerized service uses
SESSION mode on Docker's internal `0.0.0.0` interface and has no host port.
Its same-origin web proxy is the only API ingress and forwards browser session
cookies unchanged. It remains local development, not OIDC/Keycloak
authentication; do not expose an API mapping for LAN/public access.
