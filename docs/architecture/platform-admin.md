# Platform (Super) Administration

The operator tier: managing the installation itself — which companies
exist, their lifecycle state, and (from the next milestone) their
subscriptions. Everything here acts *across* tenants, which is the one
place in this codebase that deliberately steps outside the isolation
model `auth-rbac.md` describes.

## The isolation promise, and how it survives

Every other request in the system asserts a tenant: one JWT carries one
`company_id`, and all ~100 repository methods filter on it. A platform
administrator inverts that — they *target* a company rather than
asserting one.

The scope is therefore deliberately narrow: **company lifecycle and
billing; never tenant content.** A platform operator cannot read any
company's conversations, messages or customers. This is a product
promise, not just an access-control default, so it is enforced
structurally rather than by discipline:

| Mechanism | Effect |
|---|---|
| `PlatformContext` is a *separate type* from `AuthContext` | A platform token cannot be passed to a tenant endpoint — the type checker enforces it, not a convention |
| A platform token carries **no `company_id` claim** | `get_current_auth` rejects it outright (403); there is no tenant to substitute |
| All unscoped queries live in `PlatformRepository` | One file to audit, rather than spot-checking a filtering convention across every repository |
| `PlatformRepository` returns counts and company metadata only | No method returns a tenant row; one that did would be the bug |
| Platform authority is a **column**, not an RBAC role | `roles.company_id` is NOT NULL so a cross-tenant role cannot exist — and keeping it out of the tenant catalog means no tenant role can ever be *edited* into platform access |

`CompanyOverviewResponse` deliberately omits `settings` (which holds the
tenant's own AI/branding configuration) and `ai_config` (which holds
their provider credentials).

## The platform principal

A platform administrator is a `User` with `company_id IS NULL` and
`is_platform_admin = true` (migration `f45d6fb60d19`, which also made
`users.company_id` nullable — it was NOT NULL, so a company-less identity
was previously impossible).

They are created by CLI, never by an API:

```
docker compose exec backend python -m blinkengage.cli.create_platform_admin \
    ops@example.com "Ops Name"
```

Deliberately shell-only. A platform admin can suspend every company on
the installation, so minting one requires the same trust level as the
database itself; there is intentionally no "invite a platform admin"
flow that would put the most privileged account in the product behind an
email link. Re-running for an existing platform admin resets their
password, which doubles as the lockout-recovery path. It refuses to
promote an existing *tenant* user, since that would be an invisible
privilege escalation on somebody else's account.

Authority is **re-read from the database on every request**
(`get_platform_auth`), not trusted from the token — unlike ordinary
tenant permissions, which accept a 15-minute staleness window. Revoking
platform access has to be immediate.

## Company lifecycle

`CompanyStatus` (`trial` / `active` / `suspended`) existed since the
first migration but was completely inert: nothing read it and no API
could set it, so every company was permanently `trial`. It is now real.

`PATCH /platform/companies/{id}/status` sets it. Suspension is enforced
at three points:

1. **`AuthService.authenticate`** — sign-in refused.
2. **`AuthService.refresh`** — token refresh refused.
3. **`deps.get_active_auth`** — every permission-gated route, i.e.
   effectively the whole tenant API.

The third is the load-bearing one. An access token stays
cryptographically valid for its full 15-minute life, so without a
per-request check a just-suspended company would keep working until its
token expired. That costs one indexed primary-key read per request,
accepted because suspension is an account-state decision an operator
expects to take effect *now*.

`CompanyNotActiveError` subclasses `AuthenticationError` so it keeps the
401 mapping, but carries a distinct message. "Your workspace is
suspended" and "wrong password" are materially different things to tell
someone — conflating them sends people to reset a password that was
never the problem.

**A suspended company keeps receiving customer messages.** Webhook and
web-chat ingress are untouched, so nothing is lost while a billing
dispute is resolved and the tenant is not silently dropping their own
customers. Only *their* access is blocked.

**Platform admins are exempt** — suspending a tenant must never lock out
the operator who needs to un-suspend it.

## A bug this closed

Nothing on any auth path read `Company.deleted_at`, so a soft-deleted
company's users could keep signing in indefinitely. The same
`_assert_company_active` check now covers it.

## Status-code mapping

`domain_error_handler` looked its status up by `type(exc)` exactly, so a
*subclass* of a mapped exception fell through to a generic 400 — the more
precise the exception, the more wrong the status became. It now walks the
MRO, so `CompanyNotActiveError` correctly inherits `AuthenticationError`'s
401.

## API surface

All under `/api/v1/platform`, all gated by `get_platform_auth`:

| Endpoint | Purpose |
|---|---|
| `GET /companies` | Paginated list with user/agent/conversation counts; `search`, `status_filter` |
| `GET /companies/{id}` | One company's overview |
| `PATCH /companies/{id}/status` | Suspend / reactivate / return to trial, with an optional `reason` |

Every status change publishes `platform.company_status_changed`, which
the audit-log consumer records automatically — a platform operator
changing a customer's account state must be reconstructable later.

## The console

`/platform` — outside `ProtectedRoute` and `AppLayout` on purpose. The
tenant shell's navigation is the product itself (Inbox, Customers,
Reports…), none of which a platform operator can open; rendering it
would offer a dozen links that all 403.

**Sign-in routes automatically.** A platform admin signs in at the same
`/login` as everyone else. `ProtectedRoute` then sees `/auth/me` return
403, asks `GET /platform/me`, and redirects to the console. Before this
existed, a successful platform sign-in rendered the tenant shell against
a failed profile query and produced a **blank page** — indistinguishable
from a broken session. `/platform/me` exists precisely so the frontend
can tell those two apart; `/auth/me` cannot answer it, since it describes
a user *within a company*.

`PlatformRoute` guards the console in the other direction: a tenant user
who follows a `/platform` link is sent back to their own workspace rather
than shown an error, because they simply followed a link that isn't
theirs.

The companies grid shows name, identifier, status, and user/agent/
conversation **counts**, with search, a status filter, and a
suspend/reactivate action behind a confirmation that states both
consequences: people are locked out immediately, and their customers'
messages keep arriving. A frontend test asserts the page issues **no
requests to tenant endpoints** — pinned on requests rather than rendered
copy, since the page legitimately uses words like "Conversations" as a
column header.

## Deliberately not built

- **Impersonation.** Considered and rejected for this milestone: reading
  a tenant's conversations would break the promise above and create a
  GDPR/confidentiality exposure that would have to be disclosed to
  customers. If support ever needs it, it should be a separate,
  consent-gated, heavily-audited feature — not an extension of this one.
- **Platform admins managing tenant users/roles.** Same reasoning.
- **A second platform tier** (e.g. read-only analyst). Platform authority
  is currently all-or-nothing; add tiers when there is a real second
  persona, not speculatively.
