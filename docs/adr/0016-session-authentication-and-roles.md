# ADR-0016: Session-based operator authentication and role model

- **Status:** proposed
- **Date:** not yet decided
- **Blocks:** WP-10 CLI, REST API, and review UI (login, session-gated routes, role-gated review/admin actions)
- **Related decisions:** ADR-0015 (loopback-only versus authenticated network service boundary — this ADR does not resolve ADR-0015; see Context)

## Context

The service today recognises exactly two identities: an unauthenticated
loopback caller (`AuthenticationMode.UNAUTHENTICATED`) and a caller holding a
service-scoped API key (`AuthenticationMode.EXTERNAL`'s sibling path through
`authenticate_api_key`). Neither models a human operator. There is no
password-hashing dependency in the service (only SHA-256, used exclusively
for API-key digests, which is unsuitable for passwords), no session concept,
and no role concept anywhere in the codebase.

The implementation plan lists "Keycloak-backed institutional identity and the
full role matrix" under deferred, out-of-scope productionisation work
(section 3.2), with its own entry criteria (section 3.4 gate table):
"multi-user workflow is requested; policy actions and resource scopes are
frozen; security review is available." The first criterion is now satisfied
— multi-user workflow (distinct operator accounts, a fixed per-account role,
role-gated review actions) has been explicitly requested. The third has not:
no security review of this design has taken place. This ADR is written and
implemented anyway, on the record that a security review remains outstanding
for the mechanism it introduces, because the deferred item explicitly named
was a *Keycloak-backed institutional identity and full role matrix* — a
distinct, heavier thing than the minimal three-role, single-service session
scheme this ADR proposes. That heavier item stays deferred.

ADR-0015 (loopback-only versus authenticated network service boundary)
separately covers whether the service may ever bind beyond loopback, and is
still unresolved ("Status: proposed", no decision recorded). This ADR does
not touch `validate_network_boundary()` or loosen that boundary. Session
authentication ships for the existing loopback-bound deployment; whether a
non-loopback bind is ever permitted remains entirely ADR-0015's question, to
be decided later with its own evidence.

The service already has exactly one generic identity anchor —
`Subject` (`persistence/models.py`), which every existing durable record
(`Product.owner_subject_id`, and analogous columns elsewhere) references for
ownership and provenance. Introducing a second, parallel identity concept for
human operators would fork that anchor and require touching every table that
currently references `subjects.id`.

## Decision

Add a third authentication mode, `AuthenticationMode.SESSION`, alongside the
existing `UNAUTHENTICATED` and `EXTERNAL` modes. When active:

- Each operator account is a `user_accounts` row 1:1-linked to its own new
  `Subject` row (`subject_type='user'`) via a unique `subject_id` foreign
  key. No other table changes: everything that already attributes state to a
  `subject_id` continues to work unchanged for human-authenticated actions.
- `user_accounts` holds `username` (unique), `password_hash` (Argon2, via a
  new `argon2-cffi` dependency — the codebase's existing SHA-256 usage is
  explicitly for API-key digests only and is not reused for passwords),
  `role` (`analyst` | `reviewer` | `admin`), `display_name`, `is_active`,
  `created_by_user_id` (nullable self-FK, audit trail for who provisioned
  the account), `last_login_at`.
- `user_sessions` holds the opaque session id (the cookie value itself),
  `user_account_id`, `created_at`, `expires_at`, `revoked_at` (nullable).
  Sessions are server-side and revocable; the cookie carries no claims of
  its own.
- The session cookie is `httpOnly`, `SameSite=Strict`, scoped to the
  same-origin deployment this console already assumes (`docs/runbooks/local-platform.md`).
  No bearer-token or `Authorization`-header path is added for browser
  sessions; the existing API-key header path is untouched for
  service-to-service callers.
- `api/dependencies.py::get_subject_identity` gains a first branch: if a
  session cookie is present, resolve it against `user_sessions` (not
  expired, not revoked) and return a `SubjectIdentity` carrying the
  account's role; otherwise fall through unchanged to the existing
  API-key/loopback logic. `SubjectIdentity` gains two new fields,
  `role: str | None = None` and `user_account_id: UUID | None = None`, both
  defaulted so every existing call site keeps compiling.
- The first Admin account is provisioned the same way the service already
  provisions its one existing credential
  (`api/local_auth.py::bootstrap_local_api_key`, called from the app's
  `lifespan` hook): an idempotent upsert driven by
  `SELENE_SERVICE_BOOTSTRAP_ADMIN_USERNAME` /
  `SELENE_SERVICE_BOOTSTRAP_ADMIN_PASSWORD`, a no-op when neither is set.
  Every subsequent account is created by an Admin through the API
  (`POST /api/v1/auth/users`), never by self-service signup.
- Role is fixed per account and set only by an Admin acting on a *different*
  account. No endpoint lets a session change its own role. The web console
  shows the caller's role as a read-only badge, never a selector.

## Consequences

Operators get real, individually attributable logins and a role that
actually gates server-side behaviour (review-decision endpoints reject a
non-Reviewer/Admin session with 403, not just hide the button client-side).
Every existing persisted record's ownership model is untouched, because
human identity rides the same `Subject` anchor everything else already uses.
Password storage, session revocation, and role assignment now exist as real
attack surface that did not exist before; this ADR's Verification section is
the enforcement floor, not a substitute for the outstanding security review
noted in Context. Non-loopback deployment is still not authorised by this
decision — that is ADR-0015's call, separately.

Explicitly not delivered by this ADR: password reset over email (no email
infrastructure exists; an Admin resets a password directly), OAuth/SSO/any
external identity provider (matches the plan's explicit Keycloak deferral),
multi-device session-management UI (the `user_sessions` table supports it
later; no UI ships now), and rate-limiting beyond a simple fixed-window
lockout after repeated failed logins on one account.

The packaged local platform uses `authentication_mode=session`. Its Nginx
proxy forwards browser cookies but injects no shared API key, and the service
does not fall back to API-key authentication in SESSION mode. This preserves
the role-gating guarantee for every browser request.

## Verification

- Unit tests (`tests/unit/`) for `password_auth.hash_password` /
  `verify_password` round-tripping and rejecting tampered hashes; for
  `get_subject_identity`'s new session branch, using the existing
  `app.dependency_overrides[get_db_session]` in-memory-double pattern; for
  role-gating on the review-decision endpoint (403 for Analyst, 200 for
  Reviewer/Admin).
- Integration test (`tests/integration/`, real Postgres, existing
  `SELENE_SERVICE_TEST_DATABASE_URL`-gated pattern) exercising
  login → session cookie → authenticated request → logout → cookie
  rejected.
- A schema-level check that `user_accounts.password_hash` is never queried
  or logged in plaintext-adjacent form (mirrors the existing comment on
  `ApiKey.key_digest`: "Never add a plaintext-token column here").
- Frontend: `sessionStore` unit test asserting it only ever reflects
  `/api/v1/auth/session` server state and exposes no client-side role
  setter; a route-guard test asserting an unauthenticated request to any
  non-`/login` route redirects to `/login`.

## Alternatives considered

- **Stateless JWT in the cookie instead of a server-side session table.**
  Rejected for this scale: revocation would require a denylist anyway
  (re-adding the statefulness this was meant to avoid), and the plan's own
  deferred-work list explicitly excludes the distributed/stateless
  concerns (Celery/Redis, distributed workers) that would make statelessness
  worth its complexity here.
- **A parallel `users` table with no link to `Subject`.** Rejected: every
  existing ownership/provenance column already points at `subjects.id`;
  forking identity would mean either duplicating that FK everywhere or
  leaving human-authored records unattributed in the existing provenance
  model.
- **Reusing `AuthenticationMode.EXTERNAL` for session auth.** Rejected:
  `EXTERNAL`'s own docstring states it "deliberately names no identity
  provider… does not implement, validate, or advertise" any real
  authentication. Session auth is a real, implemented mechanism and needs
  its own mode so `EXTERNAL` keeps meaning "an upstream gateway handles
  this, we don't."
- **A role-selector dropdown for the logged-in user (as sketched in an
  early UI mockup).** Rejected outright: it would let any account grant
  itself Admin. The mockup's dropdown becomes a read-only role badge; role
  changes only happen on an Admin's Users screen, applied to accounts other
  than the Admin's own session.
