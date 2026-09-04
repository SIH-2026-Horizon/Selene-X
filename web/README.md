# SELENE-XR web console

The SELENE-XR scientific console is a Vite, React, TypeScript, and Tailwind
application. It is intentionally isolated in `web/` so the repository's Python
packages and workflows remain independent.

## Prerequisites

Use Node.js `^22.22.2 || ^24.15.0 || >=26.0.0` to support the lockfile-pinned
runtime and test dependencies. The workspace pins `pnpm@10.34.5` in
`packageManager`; Corepack honors that pin, so pnpm does not need to be
installed globally.

Some Node distributions omit Corepack. If `corepack --version` is unavailable,
bootstrap and enable it once before running the commands below:

```sh
npm install --global corepack@0.34.5
corepack enable
```

## Local development

From this directory, use Corepack to install the lockfile-pinned dependencies
and start Vite:

```sh
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

The web client reads persisted records from the versioned service API. During
development, its default `/api/v1` base is proxied by Vite to the local service:

```sh
VITE_SELENE_API_PROXY_TARGET=http://127.0.0.1:8000 corepack pnpm dev
```

For a deployment that supplies CORS itself, `VITE_SELENE_API_BASE_URL` can
point at that versioned API directly. When unset, the client uses `/api/v1`,
which is suitable for the local proxy or a production reverse proxy. The client
never substitutes local sample records when the API is unavailable or the
database is empty.

Artifact imagery is intentionally withheld until the deployment sets
`VITE_SELENE_ARTIFACT_HOSTS` to the comma-separated HTTPS object-storage hosts
it trusts. This prevents persisted metadata from making the browser request
arbitrary origins.

For the packaged, same-origin local stack (PostGIS migrations, service, and
static web console at `127.0.0.1:8080`), follow the
[local platform runbook](../docs/runbooks/local-platform.md). It uses no
frontend demo records; an empty database is expected until an operator
registers actual metadata.

Run the checks before submitting a change:

```sh
corepack pnpm lint
corepack pnpm test
corepack pnpm build
```

The app retains the `@` source alias and code-split routes from the supplied
prototype. Its product, run, semantic-knowledge, and registration-provenance
views read only persisted API responses.

## Motion and accessibility

`src/styles/motion.css` provides lightweight CSS-only entrance, stagger,
running-status, and live-progress cues. These are presentational: controls and
data are never hidden or delayed. When the operating system requests reduced
motion, the console disables decorative animations and transitions entirely.
