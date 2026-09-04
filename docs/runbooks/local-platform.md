# Local platform

This runbook starts the **local single-user development** platform profile: a
PostgreSQL/PostGIS database, an independent MinIO instance, an Alembic migration
job, the persisted-state service, and a packaged static web console at
`http://127.0.0.1:8080`. The web origin reverse-proxies the service API and
operational checks, so normal browser requests need no CORS configuration.
It is not a production deployment. It does not implement
scientific processing, object-storage integration, retention or archival,
distributed work, OIDC, Keycloak, observability, failover, or client upload.
It provisions a local Admin account for the built-in session and role model;
it is not an external identity-provider integration. The platform never seeds products, runs, metrics,
artifacts, or semantic-knowledge records: empty views are the expected initial
state. MinIO remains unused by the service and web application.

## Prerequisites and local configuration

Install Docker Engine with the Docker Compose v2 plugin, plus `uv` if you will
run the repository validation script. Docker itself need not be running for the
configuration render, but it must be running before containers can start.

Create the ignored local environment file with restrictive permissions. Do not
edit or commit the checked-in example.

```bash
umask 077
cp -n infra/compose/.env.platform.example infra/compose/.env.platform
chmod 600 infra/compose/.env.platform
${EDITOR:-vi} infra/compose/.env.platform
git check-ignore -v infra/compose/.env.platform
```

Replace the password placeholders and bootstrap Admin credentials. PostgreSQL
and MinIO passwords are interpolated into the service's URL, so use distinct,
noncommitted, URL-safe local passwords made of
`A-Z`, `a-z`, `0-9`, `.`, `_`, `~`, and `-`. Keep them in a password manager or
enter them directly in the ignored file; do not paste them into shell commands,
issue reports, or logs. Keep the database and MinIO user names and database
name present as well—Compose requires every listed value and has no credential
defaults. Use a distinct bootstrap Admin password of at least eight characters.
On the first service startup it is stored only as an Argon2id password hash in
PostgreSQL; it is never embedded in the Vite build or passed through Nginx.

`VITE_SELENE_ARTIFACT_HOSTS` is optional and blank by default. Add only
comma-separated HTTPS storage **host names** that the local operator has
explicitly approved for browser rendering. It is a public build setting, not a
credential or API URL. Leave it blank when no published artifact host should be
loaded; the client then refuses every external artifact URI.

The default named volumes preserve the standard local database and MinIO state.
If an incompatible prior local volume must be retained, replace the
`SELENE_PLATFORM_POSTGIS_VOLUME_NAME` and
`SELENE_PLATFORM_MINIO_VOLUME_NAME` values in the ignored environment file
with new, unique local names before starting. This creates a separate platform
state; it does not delete or modify the existing volume.

## Validate, build, start, and verify

The CI-safe validator renders the profile with the non-secret example file and
performs static checks. It does not start containers, build images, connect to
the daemon, or mutate Docker volumes.

```bash
uv run python scripts/validate_platform_compose.py
```

It fails with an explicit nonzero status when Docker Compose v2 is unavailable;
that is not a passing or skipped validation. To validate your own ignored file,
render it without starting anything:

```bash
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform config --quiet
```

Build the complete packaged stack after both renders pass:

```bash
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform build
```

The service image contains only the locked runtime dependencies and source
needed by Alembic. The web image builds the lockfile-pinned Vite artifact and
contains only static browser assets plus its server configuration. Their build
contexts exclude local data, models, secrets, and active `.env` files; no image
bytes, trained artifacts, or credentials are copied into either image.

The base, PostGIS, and MinIO images use explicit but mutable tags rather than
verified content digests. Digest pinning is intentionally deferred until
provenance and multi-architecture digests can be verified; this local profile
does not guess or invent a digest pin.

Start the complete profile in dependency order. `--wait` returns only after the
migration dependency chain permits the service and web health checks to become
ready; if it fails, inspect the commands immediately below rather than
recreating volumes.

```bash
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform up -d --build --wait
```

Compose first waits for PostGIS to become healthy, runs Alembic once, starts the
service only after the migration exits successfully, then starts `web` only
after service liveness is healthy. MinIO starts independently because the
service has no object-storage integration. Inspect the one-shot migration and
steady-state health without exposing configuration:

```bash
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform ps
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform logs migrate
curl --fail --silent --show-error http://127.0.0.1:8080/healthz
curl --fail --silent --show-error http://127.0.0.1:8080/readyz
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/version
```

The migration log should show an Alembic upgrade to `head` and a successful
exit. The first endpoint is dependency-free process liveness; `/readyz` issues
a minimal PostgreSQL query and returns the standard `503` error envelope if the
database is unavailable. Open the console at
`http://127.0.0.1:8080`; all three checks above intentionally use that same web
origin. It is a static Nginx container, not a Vite development server.

## Register actual product metadata

Run ingestion and scientific validation outside this platform, then register
only the resulting, real metadata. The API persists metadata and a manifest
hash; it does not accept or read server-local filesystem paths and it does not
upload image bytes. Do not send `file://` values or metadata keys such as
`path`, `file_path`, `local_path`, or `server_path`.

Sign in to the console with the bootstrap Admin account before registering
metadata. The same-origin Nginx proxy forwards the browser's httpOnly session
cookie, but a shell `curl` invocation does not share that browser session.
Browser JavaScript and curl callers must not send `X-SELENE-API-Key` or a
subject header. The Admin can create separate Analyst and Reviewer accounts
from Administration → Operator accounts.

To make the authenticated curl examples below, log in to a restrictive
temporary cookie jar. This Bash snippet prompts without echoing the password,
does not place it in shell history, and removes the jar on normal exit or an
interrupt. Do not paste credentials into commands or save them in a file.

```bash
umask 077
SELENE_SESSION_JAR="$(mktemp)"
cleanup_selene_session() {
  unset SELENE_LOGIN_PASSWORD
  [ -n "${SELENE_SESSION_JAR:-}" ] && unlink "$SELENE_SESSION_JAR"
}
trap cleanup_selene_session EXIT HUP INT TERM

read -r -p 'Local Admin username: ' SELENE_LOGIN_USERNAME
read -r -s -p 'Local Admin password: ' SELENE_LOGIN_PASSWORD
printf '\n'
# `printf` is a shell builtin; jq receives both values only on standard input,
# not through command-line arguments.
printf '%s\n%s\n' "$SELENE_LOGIN_USERNAME" "$SELENE_LOGIN_PASSWORD" | \
  jq -Rn '[inputs] | {username: .[0], password: .[1]}' | \
  curl --fail --silent --show-error \
    -c "$SELENE_SESSION_JAR" \
    -H 'Content-Type: application/json' \
    --data @- \
    http://127.0.0.1:8080/api/v1/auth/login
unset SELENE_LOGIN_PASSWORD
```

Replace every `REPLACE_…` string below with metadata derived from a real,
already validated product before running it. The JSON intentionally contains no
sample mission data, paths, credentials, or usable hash.

```bash
curl --fail --silent --show-error \
  -b "$SELENE_SESSION_JAR" \
  -X POST http://127.0.0.1:8080/api/v1/products \
  -H 'Content-Type: application/json' \
  --data-raw '{
    "product_identity": "REPLACE_WITH_REAL_PRODUCT_IDENTIFIER",
    "payload_type": "REPLACE_WITH_REAL_PAYLOAD_TYPE",
    "payload_metadata": {
      "published_object_uri": "https://REPLACE_WITH_APPROVED_STORAGE_HOST/REPLACE_WITH_REAL_OBJECT_KEY",
      "mission_metadata": "REPLACE_WITH_VALIDATED_METADATA"
    },
    "validation_state": "REPLACE_WITH_ACTUAL_VALIDATION_STATE",
    "validation_details": {
      "validator": "REPLACE_WITH_REAL_VALIDATION_PROCEDURE",
      "validation_record": "REPLACE_WITH_REAL_RECORD_IDENTIFIER"
    },
    "manifest_sha256": "REPLACE_WITH_64_LOWERCASE_HEXADECIMAL_CHARACTERS"
  }'
```

Inspect the record through the same origin or in the Catalog view at
`http://127.0.0.1:8080/catalog`:

```bash
curl --fail --silent --show-error \
  -b "$SELENE_SESSION_JAR" \
  'http://127.0.0.1:8080/api/v1/products?limit=10'
```

The console exposes only stored metadata and does not invent a footprint,
imagery, validation outcome, or graph relationship when a field is absent.
Semantic entities and edges can likewise be persisted through the documented
`/api/v1/knowledge` contract once real metadata is available; an empty knowledge
graph is truthful until then.

When the authenticated CLI work is complete, revoke the temporary session and
let the trap remove its cookie jar:

```bash
curl --fail --silent --show-error \
  -b "$SELENE_SESSION_JAR" -c "$SELENE_SESSION_JAR" \
  -X POST http://127.0.0.1:8080/api/v1/auth/logout
```

## Vite development versus packaged stack

For UI development, run the service separately and start Vite from `web/`.
Vite proxies its default `/api` path to the loopback service, preserving the
same `/api/v1` client base without enabling CORS:

```bash
cd web
corepack pnpm install --frozen-lockfile
VITE_SELENE_API_PROXY_TARGET=http://127.0.0.1:8000 corepack pnpm dev
```

The packaged Compose stack instead builds the lockfile-pinned Vite artifact and
serves it at `127.0.0.1:8080`. It fixes the browser API base to `/api/v1` and
proxies it internally to `service`; do not set an external API base for that
stack. See the [web README](../../web/README.md) for frontend checks.

## Optional local MinIO administration

After MinIO is healthy, an operator may create its private bucket explicitly.
This does **not** integrate MinIO with the service or web application and should
not be treated as an ingestion or artifact-publication step. The command
contains no credential and relies on the in-image `local` alias already used by
MinIO's healthcheck. If you change `MINIO_BUCKET`, replace the final bucket name
below with that non-secret value.

```bash
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform \
  exec minio mc mb --ignore-existing local/selene-private
```

Open the MinIO console at `http://127.0.0.1:9001` only when needed and sign in
with the ignored local MinIO credentials. Leave anonymous access disabled and
do not add a public policy. There is intentionally no bucket-init helper:
keeping the explicit command out of a Compose service prevents a
credential-bearing command from entering Compose logs. There is also no service
storage endpoint or client-controlled object-key/upload path.

To stop containers while preserving local database and MinIO state:

```bash
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform down
```

To permanently delete both named volumes and all local platform state, use the
following destructive command only when that loss is intended:

```bash
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform down --volumes
```

## Rotate local credentials

For PostgreSQL, changing `POSTGRES_PASSWORD` in the ignored env file alone does
not update an initialized volume. First open an interactive `psql` session in
the PostGIS container using the configured database user and database name,
then run `\password` so the password is prompted rather than recorded in shell
history. Update the same value in `.env.platform` before restarting the profile.

For MinIO, stop the profile, update `MINIO_ROOT_PASSWORD` in the ignored file,
then start it again and verify console access. Treat this as a local development
credential rotation; there is no production secrets manager, identity service,
or audit lifecycle here. Rotate the bootstrap Admin's password after signing in
through Profile & security; changing the bootstrap value later does not
overwrite an existing account.

## Security boundary and intentional limits

The service listens on `0.0.0.0` **only inside the Docker network** so the web
container can reach it; it has no host port. The Compose file uses
`authentication_mode=session` for that private listener. The database, MinIO
API, MinIO console, and web port are the only published ports, and each is
explicitly bound to `127.0.0.1` on the host.

Do not change a port mapping to `0.0.0.0`, a LAN address, or a public interface.
Do not use this profile as a production multi-user deployment. SESSION mode
does not authorise non-local exposure; production identity and authorization
controls still require a dedicated review.

The web container has a read-only filesystem, runs as an unprivileged Nginx
user, keeps only a bounded tmpfs, and sends restrictive browser security
headers. Its artifact allowlist is compiled from explicit host names into both
the app and Content Security Policy. Do not add wildcard artifact origins,
unsafe proxy locations, or CORS headers to work around a deployment issue.
