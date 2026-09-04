# ADR-0014: Service state authority, minimum persistence model, and transaction boundaries

- **Status:** accepted
- **Date:** 2026-08-30
- **Blocks:** WP-10 persistence and job control
- **Related decisions:** ADR-0005, ADR-0010, ADR-0013, ADR-0015

## Context

Persistent job state needs exactly one authority. Ephemeral progress and queued
work must not become competing state stores. A state transition and its event,
artefact, metric, or review record must commit together. The scientific CLI
remains infrastructure-independent, but a multi-user REST service requires
durable coordination, audit, and ownership records.

## Decision

PostgreSQL with PostGIS is the **sole durable state authority** for the
service profile. PostgreSQL holds the minimum model in implementation plan
section 5.4: subjects and hashed API-key metadata; products; runs and stages;
validated published artefact metadata; versioned metrics; immutable reviews
and run events; and idempotency records.

The database owns service identity, ownership, frozen run definition,
execution state, computed scientific verdict, effective disposition, audit
history, and the consistency boundaries between them. It does not hold image
or product bytes. A filesystem or S3-compatible object store owns those bytes,
but only after a producer validates, checksums, schema-checks, and atomically
publishes them. PostgreSQL records the resulting URI/key, checksum, schema and
CRS metadata, and validation evidence; a partial object is never an artefact.

Each state change and its corresponding run event is one transaction. The
same rule applies to a state change paired with an artefact, metric, or review
record. Repository helpers neither commit independently nor hide a sequence of
commits: callers supply a transaction or deliberately enter the explicit
atomic unit-of-work seam.

Run lifecycle transitions use an optimistic `state_version` predicate. A
successful conditional update advances both that version and a per-run event
counter, then records the corresponding event with that allocated sequence.
The unique `(run_id, sequence)` constraint gives durable event order even when
timestamps collide. A stale caller receives a transition conflict and records
no event. Callers cannot override event identity, sequence, or state facts in
their metadata document.

The initial persistence revision remains immutable once applied. Later
hardening is a forward migration: it backfills historical event order by
`recorded_at` then UUID, updates each run counter, and restores the immutable
event trigger after that migration-authorised update.

`run_events` and `reviews` are append-only. The initial migration creates
PostgreSQL triggers that reject both `UPDATE` and `DELETE`, including raw SQL;
review can change effective disposition through new history, never by mutating
a computed verdict or prior review. API-key rows store a one-way digest and
scopes only, never a plaintext token.

PostGIS is enabled idempotently by the initial Alembic revision. Product
footprints use PostGIS `geometry`, while accompanying CRS metadata captures
the declared lunar CRS. The schema deliberately does not assign an Earth SRID
or use PostGIS `geography` as a shortcut.

Workers and queues are not state authorities. They may later transport a run
identifier or report an attempted action, but durable state is read from and
written to PostgreSQL through the transaction rules above.

## Consequences

- Service recovery reads a single authoritative state store rather than
  reconciling a queue, cache, and API database after failures.
- PostgreSQL/PostGIS is now an explicit service dependency; the standalone CLI
  remains free of it.
- The service runtime role is intentionally narrower than the migration role.
  It needs ordinary data privileges; a migration role must be able to execute
  DDL and create the installed PostGIS extension when necessary.
- Schema changes are Alembic revisions, never application startup
  `create_all`. Revisions are applied only with an explicit database URL.
- Every persisted SHA-256 field has command-boundary validation where a command
  owns it and a PostgreSQL lowercase-hex check constraint as the final guard.

## Verification

- Unit/static tests inspect the initial revision for `CREATE EXTENSION IF NOT
  EXISTS postgis` and immutable history triggers, and confirm there is no
  plaintext API-key field.
- An opt-in `integration` test uses `SELENE_SERVICE_TEST_DATABASE_URL` to
  apply the real Alembic revisions to a PostgreSQL/PostGIS test database and
  runs `alembic check` for ORM/schema drift; verifies transaction rollback,
  ordered event allocation, optimistic conflicts, reserved event payload
  rejection, SHA-256 checks, and immutable history triggers.
- The opt-in test skips with a reason when that variable is absent. SQLite is
  not accepted as migration assurance because it cannot validate PostGIS or
  PostgreSQL trigger semantics.
- Code review rejects queue/cache/object-store code that claims durable service
  state authority and checks new paired writes use one transaction.

## Alternatives considered

### Queue or cache as job authority

Redis, RabbitMQ, or a worker-local store could expose fast progress state, but
they are not transactional with product, audit, review, or idempotency writes.
They also lose or replay messages under ordinary failure modes. They are
therefore rejected as durable authority; no distributed worker stack is added
by this decision.

### Store product bytes and state together in object storage

Object storage is appropriate for large immutable imagery and derived files,
but it does not offer relational ownership, idempotency constraints, spatial
indexing, or the transactional multi-row audit guarantees required here.
Storing raster bytes in PostgreSQL is also rejected: it makes the state store
an inefficient large-object service and does not improve the scientific
publication protocol.
