# Session-auth integration evidence

## 2026-08-31 local verification

This record documents a real local integration pass completed against the
packaged platform profile. The stack was started with an isolated,
loopback-only Docker Compose environment and disposable named PostGIS and
MinIO volumes. All credentials were generated for that run and are not
recorded here.

The migration job completed at revision `20260830_005`. The same-origin web
origin returned `200` for both `/healthz` and `/readyz` after the proxy
restart-regression fix.

### Session and role observations

1. A bootstrap Admin logged in through `POST /api/v1/auth/login`; the returned
   session and `GET /api/v1/auth/session` both reported `admin`.
2. The Admin created a disposable Analyst account through
   `POST /api/v1/auth/users`, logged out (`204`), and the Analyst logged in.
   The new session reported `analyst`.
3. A review submission by that Analyst returned `403`, confirming the
   Reviewer/Admin authorization boundary.
4. The Admin logged in again and promoted the Analyst with
   `PATCH /api/v1/auth/users/{id}`. A fresh login for that account then
   reported `reviewer`.
5. The same review request then returned `404` for an intentionally
   nonexistent run ID, rather than `403`; authorization had passed and the
   request reached normal run lookup.

No successful runner-produced run was available in the empty local database.
For the browser-only role-control check, the Admin created two disposable
products and a run through the supported API, then an isolated-database fixture
marked that run `succeeded` with a fixture verdict. This was only to make the
existing review UI eligible; it does not represent a runner-produced scientific
result and was discarded with the isolated container state. The role-dependent
control behavior is additionally covered by the ReviewRoute component tests.

### Browser verification

The rerun used Playwright `1.54.2` with local headless Google Chrome `152`.
It made the following real assertions against the packaged session-mode web
origin:

1. Visiting `/` without a cookie navigated to `/login`.
2. Form login as the bootstrap Admin navigated to `/`, displayed the visible
   `ADMIN` badge, and displayed the expected single-letter initial avatar for
   that disposable Admin display name.
3. The Admin used the Operator accounts page to create the disposable Analyst.
   On the eligible fixture run, that Analyst's review page showed the
   Reviewer/Admin requirement message and both Accept and Reject were disabled.
4. The Admin changed the Analyst role to Reviewer through the Operator accounts
   UI (the UI's `PATCH` path). After refresh, the Analyst session displayed
   `REVIEWER`, the requirement message was absent, and both review buttons were
   enabled after the required form fields were filled.

### Unauthenticated compatibility

A second loopback-bound service instance with
`authentication_mode=unauthenticated` returned `404` from
`/api/v1/auth/session`. A headless browser loaded the Vite console through its
same-origin proxy, remained at `/` (no login redirect), and found neither the
role badge nor the sign-in control. Component checks cover the same behavior.

### Commands and results

The following checks completed successfully:

```sh
uv run python scripts/validate_platform_compose.py
docker compose --env-file infra/compose/.env.platform \
  -f infra/compose/compose.platform.yaml --profile platform up -d --build --wait
uv run pytest tests/unit/test_platform_infrastructure.py -q
cd web && ./node_modules/.bin/vitest run \
  src/components/shell/TopBar.test.tsx \
  src/components/shell/AppShell.test.tsx \
  src/routes/review/ReviewRoute.test.tsx
cd web && npm run build
```

Results: Compose validation passed; the focused platform suite passed 7 tests;
the focused web suite passed 13 tests; and the production web build completed.
The browser assertions were driven with the locally installed Playwright and
Chrome against the live packaged stack and the loopback unauthenticated Vite
proxy; they passed as described above.
The isolated containers were stopped with `docker compose ... down`; no
volumes or user data were removed.
