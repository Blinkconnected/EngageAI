# Authentication, RBAC & Multi-Tenancy

Phase 2 of the roadmap. Covers company (tenant) registration, login,
token lifecycle, and role-based authorization.

## Data model

```
companies                users                     roles
---------                -----                     -----
id (PK)                  id (PK)                   id (PK)
name                     company_id (FK, cascade)  company_id (FK, cascade)
slug (unique)            email (globally unique)   name
status                   hashed_password           description
created/updated/deleted  full_name                 is_system
                         is_active                 created/updated
                         is_company_owner
                         last_login_at             role_permissions
                         created/updated/deleted    ----------------
                                                     role_id (FK)
permissions              user_roles                 permission_code (FK)
----------               ----------
code (PK)                user_id (FK, cascade)
description              role_id (FK, cascade)
```

- `permissions` is a seeded, application-managed catalog
  (`domain.rbac.PERMISSIONS`) — end users never create permissions, only
  assign existing ones to roles via `role_permissions`.
- Every company gets three seeded roles at creation
  (`domain.rbac.SystemRole`: Owner/Admin/Agent), each with a fixed default
  permission set (`DEFAULT_ROLE_PERMISSIONS`). Owner always holds the full
  catalog. Roles are marked `is_system=True` and cannot be deleted.

## Key architectural decisions

1. **Email is globally unique, not unique-per-company.** `POST /auth/login`
   takes only email+password — no company selector. This keeps the login
   UX simple at the cost of one person needing distinct email addresses to
   belong to two companies. Documented as a v1 constraint, not an
   oversight; multi-company membership per identity is a plausible future
   feature if ever requested.

2. **Permissions are embedded in the access token at issuance**
   (`AuthService.issue_tokens`), not re-checked against the database on
   every request (see `core/auth_context.py`). `require_permission()` in
   `api/deps.py` checks the JWT's `permissions` claim — no DB round-trip
   per authorized request.
   *Tradeoff, explicitly accepted*: a permission or role change takes
   effect only once the access token expires (15 min default) or the
   client refreshes. Anything that must take effect immediately (e.g.
   deactivating a compromised account) should also call
   `RefreshTokenStore.revoke_all_for_user` so re-authentication fails
   before the access token naturally expires. This tradeoff should be
   revisited if a customer requirement demands sub-minute permission
   propagation — the fix would be a short-TTL permission cache checked
   per-request instead of embedding in the JWT.

3. **Refresh tokens are individually revocable via a Redis allowlist**
   (`infrastructure/cache/refresh_tokens.py`), keyed by the token's `jti`
   claim with a TTL matching its expiry. Plain JWTs can't be revoked
   before they expire; this closes that gap for logout and
   logout-everywhere without needing a database-backed session table.
   Refresh tokens rotate on every use (`AuthService.refresh`) — the
   presented token is deleted from the allowlist and a new one issued, so
   a leaked-and-reused refresh token is detectable (the legitimate client's
   next refresh will fail, signaling compromise) and single-use in the
   normal case.

4. **Login takes the same code path whether or not the email exists**
   (`AuthService.authenticate` verifies against a dummy bcrypt hash on a
   failed lookup before raising) — reduces (but does not eliminate; bcrypt
   cost is still a variable) user-enumeration-by-timing risk. The error
   response is identical ("Invalid email or password") for both "wrong
   password" and "no such user".

5. **Rate limiting is a simple Redis fixed-window counter**
   (`core/rate_limit.py`), applied to `/auth/register` and `/auth/login`
   keyed by client IP (`X-Forwarded-For` if present, else the connecting
   socket). Deliberately simple — not a sliding-window/token-bucket
   limiter. Sufficient as blunt brute-force protection; revisit if precise
   burst control becomes a requirement.

6. **Migrations run from every service that starts (`backend`,
   `celery-worker`, `celery-beat`) via `docker/backend/entrypoint.sh`, but
   are serialized with a Postgres advisory lock** (`core/migrate.py`).
   *This was a real bug caught during end-to-end verification, not a
   theoretical concern*: without the lock, three containers starting
   simultaneously each ran `alembic upgrade head` concurrently, and two of
   them issued the same `CREATE TABLE` statement at the same time —
   Postgres rejected the loser with a duplicate-object error and that
   container crashed. The advisory lock means whichever container gets it
   runs the migration; the others block until it's released, then find
   the schema already at head and no-op. This also protects a future
   multi-replica rollout of the same service, not just the current
   cross-service race.

## Password policy

Enforced in `api/schemas/auth.py` at the request-validation layer (not the
service layer, since it's an input-shape concern): minimum 10 characters,
at least one letter and one digit. No maximum complexity theater (no
mandatory special characters, which drives predictable substitutions more
than it improves entropy) — length is enforced as the primary control per
current NIST guidance.

## What's deliberately deferred

- **Account lockout after N failed attempts** — the fixed-window rate
  limiter on `/auth/login` provides some protection, but a persistent
  per-account lockout (independent of client IP, so it can't be bypassed
  by rotating source addresses) is a Phase 6 (security hardening) item.
- **Email verification / password reset flows** — not part of the
  Authentication/RBAC/Multi-Tenant *foundation*; these are typically built
  alongside notification infrastructure (Phase 4) since they need to
  actually send email.
- **Custom (non-system) roles per company** — the data model already
  supports it (`Role.is_system=False` for anything a company creates
  itself), but no API surface exists yet to create/edit custom roles.
  Lands with Core CRM (Phase 3) or later, once there's a real admin UI
  consuming it.
- ~~New permissions are not retroactively backfilled onto existing
  companies~~ — **fixed 2026-07-25** by the generic permission sync (see
  "Permission synchronization" below). This was real, demonstrated
  technical debt: every "seed a new permission" migration before Sprint 2
  Item 4 (Conversation Transfer)'s own (`8a08ed1c4d83`) inserted the new
  `Permission` catalog row but never the corresponding `role_permissions`
  rows for companies that already existed, so `domain/rbac.py`'s
  docstring claim that Owner holds every permission "unconditionally"
  was never actually true in practice for any permission added after a
  company's creation. `8a08ed1c4d83` fixed it for `conversations.transfer`
  alone, as a one-off, explicitly leaving every earlier permission
  migration unfixed. The generic sync fully closes that gap — one
  reconciling pass brings *every* company's *every* system role up to
  date with *every* current default permission, not just the newest one
  (verified live: a simulated pre-existing company missing everything
  from every historical permission migration went from 4/28/13 granted
  Owner/Admin/Agent permissions to the full 30/28/13 in one pass — see
  `docs/ROADMAP.md`'s entry for the full verification). See below for the
  mechanism and its one honestly-documented remaining limit, which is a
  different limitation from this one.
- **A Postgres-backed test run.** The test suite runs against SQLite
  in-memory for speed and hermeticity (`tests/conftest.py`). This is a
  real, demonstrated blind spot: a `DateTime` column declared without
  `timezone=True` on `User.last_login_at` passed all 50 SQLite-backed
  tests (SQLite has no native tz-aware/naive distinction) but crashed
  every login attempt against real Postgres with a tz-mismatch error,
  caught only by the manual end-to-end Docker verification pass for this
  phase. Consider adding a smaller, slower Postgres-backed test tier
  (even just the auth integration tests) in CI once GitHub Actions is
  wired up (Phase 6), specifically to catch this class of bug
  automatically instead of relying on manual verification each phase.

## Permission synchronization

The generic mechanism (added 2026-07-25, replacing the per-permission
backfill-migration pattern above) that keeps every company's RBAC grants
in sync with `domain/rbac.py`'s current `PERMISSIONS`/
`DEFAULT_ROLE_PERMISSIONS` — no matter how old the company or how long
ago the permission was added.

**Core function**: `infrastructure.database.permission_sync.
sync_permissions(session, *, company_id=None)` — takes a plain *sync*
SQLAlchemy `Session` (not `AsyncSession`), so the identical function runs
unmodified in three different contexts:

1. **Inside an Alembic migration** — `Session(bind=op.get_bind())`. See
   `alembic/versions/3000cabd1c86_generic_rbac_permission_sync.py`, the
   one-time migration that reconciled every company that existed at the
   time it was written.
2. **From async application code**, via `AsyncSession.run_sync()` —
   `application/services/permission_sync_service.py`'s
   `PermissionSyncService.sync()`, a thin bridge with no logic of its
   own. `AuthService._seed_default_roles` calls this scoped to the
   brand-new company it just created — seeding a new company's roles and
   backfilling an existing one are now the exact same code path (a new
   company is just the "everything is missing" case), which is what
   guarantees they can never drift apart again the way the old
   hand-rolled seeding loop and the old hand-written migrations did.
3. **A standalone script**, `core/sync_permissions.py`
   (`python -m blinkengage.core.sync_permissions`) — for an operator to
   run on demand, e.g. right after deploying code that added a permission
   without waiting for a migration or a restart.

**Runs automatically on every deploy, too**: `core/migrate.py` — already
responsible for serializing `alembic upgrade head` across
concurrently-starting containers via a Postgres advisory lock — now also
runs the sync immediately after, under the same lock. In practice this
means: add a permission to `domain/rbac.py`, deploy, and every company
already has it correctly granted the moment the containers finish
restarting. No migration is required at all for the common case (a
migration is still reasonable when the permission ships bundled with
other schema work, or when the change should be visible in migration
history) — this is the literal fulfillment of "automatically detects
newly introduced permissions."

**What it does, concretely, each run** (all three layers purely
additive — insert-only, never update or delete an existing row):

1. Seeds the `permissions` catalog table from `domain.rbac.PERMISSIONS`.
2. For every targeted company (`company_id=None` means every company),
   for every `SystemRole`, ensures a `Role` row exists — creating one if
   a `SystemRole` value was introduced after that company was created.
   (Today there are only three — Owner/Admin/Agent — but this means a
   future fourth system role needs no "create it for every existing
   company" migration either, just the enum/default-set change itself.)
3. For every such role, grants every permission code in
   `DEFAULT_ROLE_PERMISSIONS[role]` that isn't already granted.

Never touches non-system (`is_system=False`) roles — company-defined
custom roles are completely out of scope. Never removes a grant, so a
role's *extra* permissions beyond its defaults (however they got there)
always survive a sync untouched.

**One honestly-documented limit**: because this is a stateless diff
against the *current* default set, it cannot distinguish "this default
permission was never granted yet" from "this default permission was
deliberately revoked from this company's role" — both look identical (a
missing row) and both get (re-)granted. This is a non-issue *today*
because no API/UI exists anywhere in this codebase to revoke a default
permission from a system role in the first place (the custom-roles/
role-editor item above is still deferred) — but if that ever ships,
telling an explicit revocation apart from a not-yet-synced gap will need
an explicit marker (e.g. a revocation record), not a rework of this
mechanism. This is a *different* limitation from the one this mechanism
replaced: the old per-permission migrations could simply be forgotten;
this one is honest about a genuine, narrow ambiguity that doesn't yet
have a way to arise.

**Idempotent and safe to run concurrently**: every insert is preceded by
reading current state within the same transaction, so re-running it (or
running it from two containers starting at once, serialized by the
advisory lock in `core/migrate.py`/`core/sync_permissions.py`) produces
identical results — verified directly (see `docs/ROADMAP.md`'s
verification entry).

## Verification performed

- 50 unit/integration tests (SQLite-backed) covering: RBAC catalog
  consistency, slug generation, rate limiter behavior, refresh-token
  store behavior, the `require_permission` dependency, and the full
  register/login/me/refresh/logout HTTP flows including multi-tenant
  isolation between two companies.
- End-to-end verification against real Postgres/Redis/RabbitMQ via Docker
  Compose: registered a real account, logged in, fetched `/me`, refreshed
  (confirmed rotation + old-token rejection), and logged out (confirmed
  post-logout refresh rejection) — all against the live stack, not mocks.
- Confirmed the migration advisory-lock fix by resetting the Postgres
  volume and starting `backend`+`celery-worker`+`celery-beat`
  simultaneously: only one container's log shows `Running upgrade ...`;
  the other two show a clean no-op.

**Permission synchronization (2026-07-25)**: 10 new tests directly
against `sync_permissions()` (fresh-company seeding, idempotency,
backfilling one missing grant without touching others, preserving an
extra permission beyond a role's defaults, never touching a custom
non-system role, company-scoped vs. global reconciliation, seeding a
missing catalog row, recreating a missing system-role row) plus 2 more
proving the async `PermissionSyncService` bridge and the refactored
registration flow — 593 backend tests total (was 583). Live-verified
against a throwaway Postgres instance: applied the full migration chain
clean on an empty database; then, simulating a company that predates
every permission-seeding migration in this codebase's history (an Owner
role with only the very first migration's 4 permissions, plus a custom
non-system role with one unrelated grant), re-ran the new migration and
confirmed Owner went from 4/30 to the full 30/30, Admin and Agent came up
to their exact current default sets (28 and 13 respectively), and the
custom role's single grant was completely untouched. Re-ran the
standalone script against the same database afterward and confirmed zero
further changes (idempotent). Separately, against this sandbox's real
production Docker stack (12 real, pre-existing companies accumulated
across every prior milestone's live verification), confirmed after
applying the migration that zero system-role grants are missing anywhere
relative to the current `DEFAULT_ROLE_PERMISSIONS` — the historical gap
is fully closed, not just for `conversations.transfer`. Also confirmed
the standalone script and a brand-new company registration both still
work correctly against the live stack post-migration.
