# Platform (Super) Administration

The operator tier: managing the installation itself — which companies
exist, their lifecycle state, their subscriptions, and which product
features each one may use. Billing and entitlements have their own
document, [`billing.md`](billing.md); this one covers the principal and
the company lifecycle they act on. Everything here acts *across* tenants, which is the one
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

Suspension also happens **automatically** when a subscription lapses;
`billing.md` covers how that interacts with everything below, including
why a payment lifts a billing suspension but never an operator's.

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
| `GET/POST /plans`, `PATCH /plans/{id}/status` | The billing catalog — see [`billing.md`](billing.md) |
| `GET /companies/{id}/subscription` | One company's billing state |
| `GET /features`, `GET/PUT /companies/{id}/features` | Feature entitlements — see [`billing.md`](billing.md) |

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

## Installation settings

`platform_settings` — one row per settings group, keyed by a string, the
value encrypted as a whole with `EncryptedJSON`. Encrypting the row
rather than one column means a field added later is protected by
default instead of by whoever remembers.

Today the only group is `smtp`: the outbound mail relay the product
sends notifications, invites and verification emails from. Deliberately
**not** the same thing as a company's customer-facing email *channel*
credentials, which belong to the tenant and live on `channel_configs`.

### Stored settings override the environment; they never replace it

SMTP has always been configured by environment variable, and existing
installations depend on that. So an installation that has never opened
the console keeps working exactly as before, and one that has keeps
working if the row is deleted. A setting that only works after somebody
fills in a form is one that takes the next fresh deployment down.

`DELETE /platform/settings/mail` drops the override and falls back —
the way back for an operator who has misconfigured the relay from the
console, and a safer instruction than "guess what the environment
variables were".

### The password is write-only

It is accepted on the way in and never sent back. An operator who can
read a credential off a screen has a way to exfiltrate it, and there is
no legitimate reason to need it again once set.

That creates one ambiguity, which the API resolves explicitly:

| What the client sends | What it means |
| --- | --- |
| `password` omitted | Keep the stored password |
| `password: ""` | Clear it |
| `password: "…"` | Replace it |

A naive round-trip of the form would otherwise erase the password every
time somebody edited the host. The read path returns `password_set`
instead, because a blank field means two different things — "no
authentication" and "authenticated, but hidden" — and an operator cannot
tell which without trying to send.

### Encryption is a choice, not a mode

`MailSecurity` is one field with three values rather than a pair of
booleans. `use_tls` and `start_tls` as separate flags admit a
combination that means nothing (both true) and one that silently sends
credentials in clear (both false) — and the second is indistinguishable
from a deliberate choice when it is rendered as two checkboxes. The
values are passed explicitly to `aiosmtplib` rather than left to its
autodetection, which would otherwise fall back to an unencrypted session
against a relay that does not offer STARTTLS.

### Testing sends a real message

`POST /platform/settings/mail/test` sends, rather than merely
connecting. A relay that accepts a TCP connection and authenticates can
still reject the envelope sender, and "connected successfully" followed
by silent non-delivery is worse than no test at all.

It answers **200 with `delivered: false`** on failure, carrying the
relay's own words. The refusal is the *answer* to the request, not an
error in serving it — and "535 authentication failed" tells an operator
to fix the password, while a generic failure sends them looking at DNS.

Rate-limited like the channel and ERP connection tests, even though the
caller is a platform administrator: trusting the operator is not the
point, and a stolen platform token should not turn the installation into
a port scanner.

### Sender-address validation is permissive

A format check, not `EmailStr`. Pydantic's validator rejects special-use
domains, and this installation's own shipped default is
`notifications@blinkengage.local` — so an operator on a fresh install who
changed only the host would have been refused because of a field they
never touched. Internal relays legitimately send from `.local` and
`.internal`, and the authority on whether an envelope sender is
acceptable is the relay, which says so in the test-send result.

## Read-only operators

`users.platform_read_only` narrows a platform operator to reading.

Platform authority is otherwise **all-or-nothing**, deliberately, so that
no tenant role can be edited into it. This does not weaken that: it only
ever *narrows* what an operator can do, and a strictly less powerful
principal cannot be an escalation path. Widening would be the dangerous
direction; narrowing is not.

It exists because auditing what a customer is charged is a normal job
that does not require the authority to change it, and the alternative is
sharing an account that can rewrite prices.

Reads stay open, including `POST /pricing/resolve` — a POST, but a read:
it writes nothing, and seeing what the resolver will decide is the main
reason to grant read access at all. Writes are refused by
`require_platform_write`, at the API rather than only in the console: a
disabled button is a courtesy, not a permission.

`GET /platform/me` reports `read_only` so the console can disable its
controls and say why, instead of letting somebody fill in a form that will
be refused.

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
