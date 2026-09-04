# Service migrations

Versioned PostgreSQL/PostGIS migrations for the entities in section 5.4 of the
implementation plan. The initial revision creates the durable service-state
model and PostgreSQL-enforced append-only triggers for `run_events` and
`reviews`; it does not create a scientific pipeline or an object store.

Run only with an explicitly supplied **dedicated** PostgreSQL/PostGIS URL:

```bash
export SELENE_SERVICE_DATABASE_URL='postgresql+psycopg://selene_migrator:password@127.0.0.1:5432/selene_test'
uv run alembic -c packages/selene_service/alembic.ini upgrade head
uv run alembic -c packages/selene_service/alembic.ini current
uv run alembic -c packages/selene_service/alembic.ini check
```

`env.py` intentionally rejects an absent `SELENE_SERVICE_DATABASE_URL`; there
is no implicit local target. The migration role needs DDL permissions and the
ability to enable the installed PostGIS extension. A runtime role should have
only the DML and schema usage permissions it needs after migration.

To use the real-database verification test, supply a separate explicit test
URL. The test skips when absent and must never be replaced by SQLite:

```bash
SELENE_SERVICE_TEST_DATABASE_URL='postgresql+psycopg://selene_migrator:password@127.0.0.1:5432/selene_test' \
  uv run pytest tests/integration/test_postgres_persistence.py -m integration
```

`alembic check` is the metadata-drift policy: on the real PostgreSQL/PostGIS
target, it compares the declarative mapping with the upgraded schema using
type and server-default comparison. Run it before adding a migration; do not
try to replace it with a SQLite metadata check.

The initial `20260830_001` revision is immutable once applied. The forward
`20260830_002` revision upgrades it with optimistic run versions, ordered
events, and digest checks. During its one-time historical sequence backfill it
temporarily disables only the `run_events` immutability trigger, orders tied
timestamps by event UUID, and re-enables the trigger in the same transaction.
