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
