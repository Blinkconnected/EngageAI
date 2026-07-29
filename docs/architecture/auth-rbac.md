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

1. **Email is globally unique among *non-deleted* users, not
   unique-per-company.** `POST /auth/login` takes only email+password —
   no company selector. This keeps the login UX simple at the cost of one
   person needing distinct email addresses to belong to two companies.
   Documented as a v1 constraint, not an oversight; multi-company
   membership per identity is a plausible future feature if ever
   requested.

   The "non-deleted" qualifier is load-bearing (added 2026-07-28,
   migration `040a7da326b5`): `ix_users_email` is a **partial** unique
   index, `WHERE deleted_at IS NULL`, matching `agents.user_id`'s
   long-standing `uq_agents_user_id` pattern. It was previously a plain
   global unique index, which meant a soft-deleted user's email stayed
   reserved forever. Combined with `AgentService.delete()` only
   soft-deleting the `Agent` profile and never its backing `User`, that
   made re-adding an agent with a previously-used email fail with
   "already exists" permanently — the bug this fixed.

   Correspondingly, `UserRepository.get_by_id`/`get_by_email` now filter
   `deleted_at IS NULL` (matching `CustomerRepository.get_by_email`'s
   existing convention, and previously the only repository in the
   codebase whose lookups did *not*). Because those two methods back
   `authenticate()`, `refresh()`, and `get_current_user()`, this also
   closes a real gap: a deleted agent's still-valid access token,
   refresh token, and password all previously kept working, since
   `is_active` is a separate flag deletion never touched.
   `AgentService.delete()` additionally revokes the user's refresh
   tokens outright, so revocation does not wait on access-token expiry.

   *Existing data needed a backfill, not just a code fix*: the service
   change only governs *future* deletions, so every agent deleted before
   this release had already left a live `User` row permanently holding
   its email. Migration `6b6f167ff303` soft-deletes exactly those —
   users with a soft-deleted agent profile, **no** active agent profile,
   and `is_company_owner = false` — backdating `deleted_at` to the
   agent's own deletion time so the audit trail reflects when the
   account really stopped being usable. It is deliberately irreversible
   (`downgrade()` is a documented no-op): the pre-migration state *is*
   the bug, nothing records which rows were touched, and restoring them
   would re-block the very addresses the upgrade freed.

   *Deliberately soft, never hard, delete*: `agents.user_id` declares
   `ondelete="CASCADE"`, and `audit_logs`/`internal_notes`/
   `conversation_transfers`/`customers.rated_by_user_id` all reference
   `users.id` with `SET NULL` specifically to preserve attribution
   history. A hard `DELETE` would cascade away the agent row and blank
   out that history; soft-delete keeps every record intact while freeing
   the email.

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

## Custom roles

Added 2026-07-27 (Milestone 3 of the Product & UX Review's roadmap — "Access
control has a hard ceiling"). Every company can now define its own roles
alongside the seeded Owner/Admin/Agent set, and edit what Admin/Agent
grant by default. No schema change was needed for the roles themselves —
`Role`/`RolePermission`/`UserRole` already supported this from Phase 2 —
and no change was needed to authorization/login either, since
`AuthService` already resolves a user's effective permissions live from
`user_role.role.role_permissions` at token-issuance time rather than from
a hardcoded mapping. This milestone is entirely the CRUD/guardrails layer
on top of a data model that was already ready for it, plus one real fix
to an existing mechanism it exposed (see "Permission synchronization"
below).

**API** (`api/v1/endpoints/roles.py`, all gated by `roles.manage` — the
only permission covering both reading and writing this resource, like
`erp.manage`): `GET/POST /roles`, `GET/PATCH/DELETE /roles/{id}`,
`GET /roles/{id}/members`, `GET /permissions` (the static catalog, for
building a permission checklist UI). Agent-role (re)assignment is a
separate, on-demand endpoint pair — `GET/PUT /agents/{id}/role` — rather
than a field on `AgentResponse`, to avoid touching that schema's 5
existing call sites in `api/v1/endpoints/agents.py` for data most callers
of `AgentResponse` don't need.

**Guardrails** (`application/services/role_service.py`), each backed by
a dedicated `DomainError` subclass in `domain/exceptions/__init__.py`:

- A system role (`is_system=True`) can never be deleted, nor renamed —
  its *name* is a hardcoded lookup key elsewhere (`AuthService` seeds a
  new company's Owner by looking up `name="Owner"`;
  `AgentService.create()` seeds every new agent by looking up
  `name="Agent"`), so renaming one out from under those lookups would
  silently break agent/owner creation for that company. Description and
  (Admin/Agent only — see next point) permissions remain editable.
- The Owner role's permission set can never be edited — it must always
  hold the full catalog, so a company can never end up with nobody able
  to manage its own RBAC configuration.
- A role — system or custom — can't be deleted while it still has
  members. `UserRole.role_id` cascade-deletes on `Role` deletion, so
  allowing this would silently strip every member of all permissions
  with no warning.
- Reassigning the founding company owner (`User.is_company_owner=True`)
  away from the Owner role is blocked, for the same reason Owner's
  permissions can't be edited: it's the one invariant guaranteeing a
  company always has at least one user who can manage its own roles.

**Frontend**: a new "Roles & Permissions" page (`features/roles/`, nav +
route both gated on `roles.manage`) — a table of every role with a
permission-checklist create/edit dialog (grouped by resource prefix,
e.g. "Conversations", "Queues"), a members viewer, and delete with the
same guardrails reflected in the UI (disabled with an explanatory tooltip
rather than a server-error round-trip). A "Change role" action was added
to the Agents page (`features/agents/AgentRoleDialog.tsx`), independently
gated on `roles.manage` (distinct from `agents.manage`, since editing an
agent's title/department and reassigning their role are different
permissions with different defaults — only Owner gets `roles.manage` out
of the box).

## What's deliberately deferred

- **Account lockout after N failed attempts** — the fixed-window rate
  limiter on `/auth/login` provides some protection, but a persistent
  per-account lockout (independent of client IP, so it can't be bypassed
  by rotating source addresses) is a Phase 6 (security hardening) item.
- **Email verification / password reset flows** — not part of the
  Authentication/RBAC/Multi-Tenant *foundation*; these are typically built
  alongside notification infrastructure (Phase 4) since they need to
  actually send email.
- ~~Custom (non-system) roles per company~~ — **shipped 2026-07-27**, see
  "Custom roles" below.
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

~~**One honestly-documented limit**: because this is a stateless diff
against the *current* default set, it cannot distinguish "this default
permission was never granted yet" from "this default permission was
deliberately revoked from this company's role" — both look identical (a
missing row) and both get (re-)granted.~~ — **closed 2026-07-27** by
custom roles (below) shipping with exactly the explicit marker this
paragraph anticipated needing: `Role.permissions_customized`, set the
moment `RoleService.update()` changes an Admin/Agent system role's
`permission_codes`. `sync_permissions()` now skips step 3 entirely for
any role with that flag set, so a deliberate revocation and a
not-yet-synced gap are no longer ambiguous — only the former sets the
flag. See `test_sync_does_not_regrant_a_deliberately_removed_permission_from_a_customized_role`
and `test_editing_admin_permissions_survives_a_later_permission_sync`
for the regression coverage this closed.

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

**Custom roles (2026-07-27)**: 20 new backend tests — 18 covering the
full `roles.py`/agent-role API surface (system-role immutability rules,
member-count-blocks-delete, permission-code validation, multi-tenant
scoping, the founding-owner-can't-be-reassigned guard) plus 2 regression
tests proving a deliberately-edited Admin/Agent permission set survives a
later `sync_permissions()` run — 796 backend tests total (was 777).
Frontend: a new Roles & Permissions page and an Agents-page "Change
role" dialog, 9 new tests (axe-checked) — 201 frontend tests total (was
192). Live-verified against the real Docker stack: rebuilt and
recreated `backend`, confirmed the new `94fee869e809` migration applied
cleanly against real Postgres; via curl, created a custom role, invited
an agent, assigned them the custom role, confirmed deleting a role with
a member is blocked (400) and its members list is correct, confirmed
renaming Admin is blocked (400), then removed a permission from Admin's
grants and — critically — ran the real standalone `sync_permissions`
script directly inside the container afterward, confirming zero grants
were re-added and Admin's edited permission set survived exactly as
left. Also confirmed visually via Playwright screenshots: the Roles
page's table and permission-checklist edit dialog, and the Agents page's
"Change role" dialog correctly pre-selecting the agent's actual current
role.


## Email verification

A newly registered company starts **unverified**. Its people can sign in
and read; they cannot act.

That middle position is deliberate. Refusing sign-in outright locks a
customer out with nothing on screen to act on when the email is delayed
or bounces, and the only thing verification actually needs to prevent is
an unverified account *doing* something — sending messages, connecting
channels, inviting people. Somebody who has just signed up should be
able to look around.

### Where the gate lives

Inside `require_permission`, not on individual endpoints. A list of
routes to protect is a list somebody forgets to add to, and the failure
mode is a feature that silently works before the customer has proved
they own the address. `UNVERIFIED_BLOCKED_ACTIONS` in
`domain/verification.py` names the permissions refused — all of them
`.manage`-class actions, plus `ai.use`, which has a real external cost.

The check reads the company per request rather than trusting a token
claim. A claim would mean somebody who has just verified still cannot
act until they sign out and back in, which is exactly the moment they
are least willing to.

It raises `EmailNotVerifiedError` → **403**, deliberately distinct from
a missing permission: the person *has* the permission, and telling them
otherwise sends them to an administrator who cannot help — they usually
*are* the administrator. The message names the actual fix.

### Tokens

Stored as a **SHA-256 hash**, never raw. A verification link is a bearer
credential, so a database backup or a support screenshot containing raw
tokens would be a way to verify somebody else's account; the raw value
exists only in the email that was sent. Not a password hash and
deliberately not bcrypt — this is a high-entropy random value, so there
is nothing for a slow hash to defend against, and a slow hash on the
lookup path would mean scanning every row.

Links last 48 hours. Consuming one is a guarded UPDATE, so two clicks
arriving together cannot both consume it, and the row is kept rather
than deleted — a customer clicking twice is told **"already verified"**,
not "invalid link", which reads as though something went wrong.

Resending is throttled to once every two minutes. It is a legitimate,
common action — the first email lands in spam — but unthrottled it is a
way to use this installation to mail an address somebody else owns. It
requires a session for the same reason: an unauthenticated resend taking
an email address will mail anybody.

### Failure of the email does not fail the signup

The verification email is sent from the endpoint, *after* the account is
created, and a delivery failure is logged rather than raised. A
rolled-back registration would leave the customer with nothing and an
email address that now appears taken.

### In the test suite

`conftest.py` clears `UNVERIFIED_BLOCKED_ACTIONS` for every test except
those marked `@pytest.mark.enforce_verification`. Almost every test
creates its own company and is about something else entirely; without
this, every write in the suite would fail on the gate and say nothing
about the feature under test. Clearing the domain set rather than
stubbing the dependency keeps the production path identical — the same
lookup runs, it simply finds nothing.

## Features are not permissions

A permission asks "may this **user** do it?"; a feature entitlement asks
"has this **company** bought it?" — see
[`billing.md`](billing.md). They are stacked, never substituted: a user
can hold every permission in this catalog and still be refused, with
**402 Payment Required**, because their company's plan does not include
the capability. Answering 403 there would send an administrator to edit
roles that were never the problem.

`billing.manage` is Owner-only by default, the one permission in the
catalog that commits the company to a recurring charge. `billing.read`
also goes to Admin.
