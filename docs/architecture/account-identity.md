# Identity — architecture review

*Proposed. Nothing here is built. Written against the code as it stands.*

**Identity is a first-class domain, not part of Authentication.** The two
answer different questions and have different lifetimes:

| Domain | Question |
|---|---|
| **Authentication** | *Can this person sign in right now?* |
| **Identity** | *Who is this person, and how much do we trust that?* |
| **Authorization** | *What is this person allowed to do?* |

An authentication answer is true for the length of a session. An identity
answer is true for the length of an employment. Collapsing them is why
`email_verified_at` currently sits on a table owned by login and gates nothing
— it was filed where the login flow happened to touch it.

## The finding that reframes everything

**Verification today is a company onboarding gate wearing a user's clothes.**

`VerificationService.verify()` sets **`Company.verified_at`**. `is_verified()`
takes a `company_id`. `deps.py` blocks 19 permissions when the *company* is
unverified. `User.email_verified_at` exists on the model and gates nothing.

The practical consequence: **the first person to click the link unlocks the
company for everyone.** A second, third or fiftieth user can hold an address
nobody has ever proved they own, and the platform neither knows nor cares.

That is a reasonable design for *"is this a real business"*. It is not a
design for *"does this person control this mailbox"* — and the second is what
a security model needs, because the mailbox is the reset path for the account.

So the first architectural decision is to separate two things that are
currently one:

| Concern | Question | Scope | Gates |
|---|---|---|---|
| **Company verification** | Is this a real business? | Company | Onboarding: the 19 blocked actions today |
| **Account verification** | Does this person control this mailbox? | User | Acting as *that person* |

Both keep the name "verification" to users. Internally they must never share
a field again.

---

## 0. The boundary

### Who owns what

| Concern | Domain | Today |
|---|---|---|
| Login, password check, sessions, refresh tokens, logout | **Authentication** | `auth_service.py` ✅ correct |
| MFA *(future)* | **Authentication** | Does not exist |
| Roles, permissions, access control | **Authorization** | `domain/rbac.py` ✅ correct |
| Profile: name, language, timezone, avatar | **Identity** | ❌ Nowhere — no profile write path exists |
| Email lifecycle | **Identity** | ❌ Split: the token lives in `verification_service`, the column on the login table |
| Verification lifecycle | **Identity** | ❌ `verification_service` verifies *companies* |
| Identity Health | **Identity** | ❌ Does not exist |
| Restrictions | **Identity** | ❌ Does not exist |
| Protected account rules | **Identity** | ⚠️ A fragment: `_require_another_active_owner` in `platform_user_service` |
| Identity audit history | **Identity** | ⚠️ Generic `audit_logs`, no identity shape |

### What moves, and what deliberately does not

**Moves out of Authentication into Identity:**

- `User.email_verified_at` and everything that reads it
- `verification_service.py` — split in two, see below
- `domain/verification.py`'s blocked-action set
- The `_require_another_active_owner` fragment, which is a protected-account
  rule wearing a platform-admin helper's clothes

**Stays in Authentication:**

- `authenticate`, `issue_tokens`, `refresh`, `logout`, `change_password`
- The `hashed_password` column. A password is a *credential*, not an identity
  attribute — Identity may ask Authentication "when was it last changed" for
  Identity Health, and never reads or writes the hash.

**Stays in Authorization:** everything in `rbac.py`. Identity asks
Authorization *"who else holds this permission"* to answer protected-account
questions, and never inspects roles itself.

### The one genuinely shared thing

`register_company` today creates a company, a user, roles and (as of this
week) a queue and a routing rule. It spans four domains and belongs to none.

It is **company onboarding**, not authentication, and it should say so. This
review does not move it — that is a separate change with its own risk — but it
should stop living in `auth_service.py`, and Identity should not inherit it.

### Package structure

```
domain/identity/            application/services/identity/
  __init__.py                 profile_service.py        profile writes
  profile.py                  email_change_service.py   the lifecycle in §2c
  email_change.py             verification_service.py   *account* verification
  verification.py             restriction_service.py    apply / lift
  health.py                   health_service.py         the derived view
  restrictions.py             protection_service.py     protected-account rules
  protection.py               history_service.py        readable history
  history.py

domain/verification.py    →  becomes *company* verification only, renamed
                             company_verification.py so the two are never
                             confused again
```

Framework-free in `domain/identity/`, as everywhere else: the states, the
rules, the wording. Services orchestrate; the domain decides.

### API surface

Identity gets its own prefix rather than more verbs under `/auth`. The URL is
the first documentation anybody reads, and `/auth/me/email` says the change is
an authentication concern when it is not.

```
GET    /identity/me                     profile + health + state
PATCH  /identity/me                     name, language, timezone, avatar
POST   /identity/me/email               request a change
DELETE /identity/me/email               cancel a pending change
POST   /identity/me/email/resend
GET    /identity/me/history             this person's own history

GET    /platform/identities/{user_id}
PATCH  /platform/identities/{user_id}/email
POST   /platform/identities/{user_id}/verification/force
POST   /platform/identities/{user_id}/verification/extend
POST   /platform/identities/{user_id}/restriction        apply / lift
GET    /platform/identities/{user_id}/history

POST   /auth/verify-email               stays: it is an unauthenticated
                                        token exchange, and moving it would
                                        break links already in inboxes
```

`GET /auth/me` stays and keeps returning what a session needs. It gains
nothing identity-shaped: a client that wants identity asks Identity.

---

## 0a. Dependency review

Traced against real imports, not the diagram.

### What is already clean

- **`domain/rbac.py` imports nothing.** Authorization is a pure leaf. It
  cannot participate in a cycle, which is the best possible starting point.
- **The `Company` model does not import `User`.** Company does not reach into
  identity.
- **The `User` model imports only its base.** Its relationships are
  `TYPE_CHECKING` only.

### Cycle risk 1 — Authentication ↔ Identity, through login

Identity Health needs **password age**, which is Authentication's. If
Authentication *also* asks Identity "is this account restricted?" at login,
the two point at each other.

**Broken by a decision already made:** restricted and unverified accounts
**can sign in** (§3). Authentication never asks Identity anything. The edge
that would close the cycle does not exist.

Password age flows the other way and only one way — see *Shared table* below.

### Cycle risk 2 — Authorization ↔ Identity, through the permission gate

This is the one that would have bitten during implementation.

Restrictions have to gate actions. The obvious home is `require_permission`,
which is Authorization — and Identity already needs Authorization to answer
protected-account questions (*"does anybody else still hold this
permission?"*). That is a cycle:

```
   Authorization ──"is this user restricted?"──► Identity
        ▲                                            │
        └────"who else holds this permission?"───────┘
```

**Resolution: neither domain enforces the other. The API layer composes them.**

This is not a new pattern — it is exactly how company verification works
today. `deps.py` asks `domain/verification.py` whether a permission is blocked
and combines that with the RBAC check. `rbac.py` has never imported
verification, and must never import Identity either.

```
  api/deps.py  ── require_permission(code)
        ├── Authorization: does this role grant `code`?
        ├── Company:       is the company verified?
        └── Identity:      is this account restricted from `code`?
        (composes three independent answers; none of them knows the others)
```

Identity exposes a pure predicate — `is_restricted_from(state, code)` — in
`domain/identity/restrictions.py`, framework-free and importing nothing. The
same shape as `is_blocked_before_verification`, for the same reason.

### Cycle risk 3 — Identity ↔ Company, through verification

`verification_service` currently **writes `Company.verified_at`**. Under the
new rule that is Identity manipulating Company's internal state.

**Broken by the split this document opens with.** Company verification stays
with Company; Identity owns account verification and never touches a Company
row. The service divides along the same line the concepts do.

### The coupling package structure cannot fix: one `users` table, three owners

| Columns | Owner |
|---|---|
| `hashed_password`, `last_login_at` | **Authentication** |
| `email`, `pending_email`, `full_name`, `language`, `timezone`, `avatar_url`, verification and restriction state | **Identity** |
| `is_company_owner`, role links | **Authorization** |
| `company_id` | **Company** |

Three domains, one table. No package layout changes that.

**Recommendation: accept it, and write the ownership down.** Splitting
`identities` out of `users` buys boundary purity at the cost of a join on the
hottest path in the product — every authenticated request — and the coupling
is at the storage layer, not in the logic. The rule that matters is
enforceable without a migration: *a domain reads and writes only its own
columns, and asks a service or reads an event for anything else.*

**Password age is the live example.** Identity Health needs it; the column
belongs to Authentication. Identity does not read `hashed_password` or a
timestamp beside it — Authentication publishes `PasswordChanged`, and Identity
projects it like any other event. One direction, no import.

### The one remaining tangle, named rather than fixed

`register_company` creates a company, a user, roles, a queue and a routing
rule. It spans all four domains and lives in `auth_service.py` — the file with
the *least* claim to it.

It is **company onboarding**. It should move, and moving it is unrelated to
Identity: it is load-bearing for the entire test suite. Identity must not
inherit it, and Phase 1 must not touch it.

### Verdict

**No circular dependency will exist after the split.** Two would have
appeared if the boundary had been drawn naively — the permission gate and the
login check — and both are avoided by decisions already in this document
rather than by new machinery.

---

## 1. Identity architecture

### Recommended shape

| Field | Purpose | Verified? | Notes |
|---|---|---|---|
| `email` | **Login identity** | Yes | Unique per platform. The credential. |
| `pending_email` | An email change awaiting proof | — | Login stays on `email` until proven |
| `recovery_email` | Account recovery only | Yes, separately | Optional. Never a login. |
| `full_name` | Display | — | Exists |
| `avatar_url` | Display | — | New |
| `language` | This person's UI language | — | New — today language is company-wide only |
| `timezone` | This person's times | — | New — today timezone is company-wide only |

### Where I disagree with the brief

**Drop "contact email" as a user field.** Three addresses is three things to
keep verified and three ways for a person to be confused about which one
matters. The real use — *"where do invoices and account notices go"* — is a
property of the **company**, not of a user, and putting it on the user means
it silently changes when that employee leaves. Recommend a company-level
billing contact instead.

**Recovery email earns its place**, but only if it is verified separately and
can never be used to sign in. An unverified recovery address is worse than
none: it is a second attack surface that looks like a safety net.

### Language and timezone are per-user, and this is a real change

Both exist only on `Company.settings` today. An agent in Amman and a
supervisor in London currently share one timezone, which means one of them
reads every SLA figure wrong. Per-user preference with company default as the
fallback.

---

## 2. Account lifecycle

```
   register ──►┌──────────────┐                    ┌─────────────┐
               │   PENDING    │─── verifies ──────►│  VERIFIED   │◄──┐
               └──────┬───────┘                    └──────┬──────┘   │
                      │ 24h · 3d · 7d reminders           │          │
                      │                      changes email│          │
                      ▼                                   ▼          │
               ┌──────────────┐                 ┌─────────────────┐  │
               │  RESTRICTED  │── verifies ────►│ CHANGE PENDING  │  │
               └──────┬───────┘                 │  login = old    │──┘
                      │                         └────────┬────────┘
   an administrator,  │                    reminders,    │
   policy, or an      │                    then          ▼
   extended period    │                          ┌──────────────┐
                      ▼                          │  RESTRICTED  │
               ┌──────────────┐                  └──────────────┘
               │  SUSPENDED   │── verifies ──► VERIFIED
               └──────────────┘

   PROTECTED accounts never leave RESTRICTED automatically — see §2a.
```

### The decision that matters most: a change does not take effect until proven

**Login stays on the old address while a change is pending.**

Under the obvious alternative — change immediately, 24 hours to verify — a
single typo means the person cannot receive the verification, cannot be
reached, and is suspended a day later. Support then has a locked-out customer
whose address nobody knows.

Under the proposed model a typo costs nothing: the mail bounces, login still
works, the change quietly expires, and the platform says so.

### Nobody is suspended on a clock alone

**Approved lifecycle.** Verification does not end in suspension. It ends in
*restriction*, and suspension is a separate decision somebody makes.

```
  email changed / account created
            │
            ▼
  ┌──────────────────────┐
  │ PENDING VERIFICATION │
  └──────────┬───────────┘
             │  reminder at 24h
             │  reminder at 3 days
             │  reminder at 7 days
             ▼
  ┌──────────────────────┐
  │     RESTRICTED       │  ← still signs in, still reads, cannot act
  └──────────┬───────────┘
             │  extended period, or company policy, or an administrator
             ▼
  ┌──────────────────────┐
  │      SUSPENDED       │
  └──────────────────────┘
```

Three reminders across a week before anything changes, and the change is
survivable when it comes. An account that has been restricted has been told
three times and can still see exactly why and fix it.

The earlier draft proposed 24 hours to suspension for a changed email. That
was wrong for the same reason it was wrong for new accounts: it turns one
mistyped address, or one week of annual leave, into a locked-out employee and
a support ticket.

### Restrictions are configurable

What "restricted" *means* is company policy, not a platform constant. The
platform ships a default; a company that needs stricter or looser sets its
own. Configurable per company:

| Setting | Default |
|---|---|
| Reminder schedule | 24h · 3 days · 7 days |
| Restrict after | 7 days |
| Restricted capabilities | cannot send to customers, cannot change billing, cannot manage users |
| Suspend after restriction | **Never** — administrator action only |
| Grace on email change for a *proven* account | Restrict at 7 days, same as new |

The one thing that is **not** configurable is protected accounts — see below.

### Suspension is reversible by verifying

Verifying a suspended account reactivates it, without a support ticket. A
suspension that can only be lifted by an administrator turns a mistyped
address into a queue of tickets that all have the same answer.

---

## 2a. Protected accounts

**The platform must never automatically suspend an account whose loss would
leave a company unable to run itself.**

Protected, and exempt from every automatic transition:

| Account | Why |
|---|---|
| The last **Company Owner** | Nobody left who can manage roles, transfer ownership or invite a replacement |
| The last **Billing Administrator** | Nobody left who can pay an invoice — and an unpaid invoice suspends the *company* |
| Any account whose suspension **orphans the company** | Generalises both: no active user retains the permission |

The rule is deliberately about *permissions remaining*, not about titles. An
owner and a billing administrator can be one person; a company can have three
owners of whom two are already restricted. What matters is whether the
capability survives the action, and that is a question about the set of
remaining active accounts.

### What happens instead

A protected account never silently escalates. It **stays restricted**, and the
platform raises the problem to people who can act on it:

1. The account itself keeps its restriction banner and its reminders.
2. Other administrators of the company are told that an account they depend on
   is unverified and cannot be restricted further.
3. Platform administrators see it in Identity Health, with the three ways out:
   **another administrator**, **ownership transfer**, or **platform
   intervention**.

Automation stops at the point where it would break the customer. It does not
stop quietly — a protected account that nobody is told about is the same
outage arriving later.

### This is a guarantee, not a default

Company policy can make restriction stricter. It cannot switch protection off.
A company that could configure its way into orphaning itself would eventually
do so, and the support cost lands on the platform either way.

---

## 2b. Identity Health

**One place that answers "is this account safe".** Today the answer is spread
across a boolean, a nullable timestamp, and nothing at all.

| Signal | Today | Notes |
|---|---|---|
| Email verification | `User.email_verified_at` — set but ungating | Per account, once §1 lands |
| Company verification | `Company.verified_at` | Separate concern, shown beside it |
| MFA status | **Does not exist** | See below |
| Password age | `hashed_password` only — no `password_changed_at` | New column |
| Recovery email | **Does not exist** | New, verified separately |
| Last login | `User.last_login_at` ✅ | Exists |
| Suspicious login activity | **Does not exist** | See below |
| Account restrictions | **Does not exist** | Comes with §2 |

Identity Health is a **derived view over these signals**, not a stored score.
A stored score drifts from the facts it summarises, and this codebase has been
bitten by exactly that twice — the SLA bands and the Inbox view predicates,
both caught only by tests that ran two paths over the same rows.

### The honest part

**Two of these signals do not exist at all.** MFA is not implemented — there
is no enrolment, no secret storage, no challenge. "Suspicious login activity"
needs a login-attempt history with IP and user agent, which is also not
recorded.

### Identity Health must never fabricate a signal

Every signal renders in exactly one of four states, and the last two are not
decoration — they are the whole reason this rule exists:

| State | Meaning | Shown as |
|---|---|---|
| **Healthy** | The platform checked, and it is fine | Green |
| **Attention** | The platform checked, and it is not | Amber / red |
| **Not configured** | The capability exists; this company has not set it up | Neutral, with the setting to fix it |
| **Not available** | The capability **does not exist in the platform** | Neutral, stated plainly |

**Never green, never red, for a signal we cannot measure.** Green on an MFA
row the platform cannot evaluate tells a security officer their people are
protected. Red tells them to go and fix something that cannot be fixed. Both
are the screen inventing a fact, and this screen exists to be trusted.

Today that means **MFA** and **suspicious login activity** ship as *not
available*, with one sentence saying so. The Conversation Story already sets
this precedent — it reports runtime queues as *not in use* rather than
rendering a blank that reads as a failure, and lists what the platform does
not version so an engineer stops looking.

A test should assert it: **no signal may render Healthy or Attention unless
its underlying capability is implemented.** That is the guard which stops a
future contributor wiring MFA to a constant `false` and turning the row green.

MFA and login-attempt history are each their own milestone. Neither belongs
inside this one, and Identity Health must not imply otherwise while they are
missing.

---

## 2c. The email change is its own record

An email change is not a field edit. It is an **immutable lifecycle with its
own row**, for the same reason routing decisions and ledger entries are: the
question asked afterwards is *"who changed this address, when, and did anybody
prove it"* — and a mutated column cannot answer that at all.

```
  CURRENT ──► PENDING ──► VERIFICATION_SENT ──► VERIFIED ──► ACTIVATED
                 │                 │
                 │                 ├──► CANCELLED   (the user or an admin withdrew it)
                 └─────────────────┴──► EXPIRED     (nobody acted in time)
```

`email_change_requests`, append-only, one row per attempt:

| Column | |
|---|---|
| `user_id`, `company_id` | Who |
| `from_email`, `to_email` | The change itself, copied by value |
| `state` | The lifecycle above |
| `requested_at` · `sent_at` · `verified_at` · `activated_at` · `closed_at` | When each step happened |
| `requested_by_user_id` | The user themselves, or an administrator |
| `reason` | Required when an administrator does it |
| `ip_address`, `user_agent` | Where from, when available |

**`VERIFIED` and `ACTIVATED` are deliberately separate.** Verified means the
person proved the mailbox. Activated means the login credential actually moved.
They are usually the same second and are not the same fact — a change verified
while the account is suspended should not silently move the credential, and an
administrator reading the history needs to see which of the two happened.

Append-only, enforced by a database trigger, matching `routing_decisions` and
the ledger tables. An identity history that can be edited is not a history.

---

## 3. Security — what is blocked, and why

**Unverified users may sign in.** Blocking login makes a typo an unrecoverable
lockout with no self-service path, and gives the person no way to see *why* or
to fix it. They sign in; they are told exactly what is wrong and given the
button that fixes it.

| Action | Unverified (new) | Change pending | Suspended |
|---|---|---|---|
| Sign in | ✅ | ✅ (old address) | ✅ — to see why, and fix it | ✅ |
| Read conversations, reports | ✅ | ✅ | ✅ | ❌ |
| **Send a message to a customer** | ✅ | ✅ | ❌ | ❌ |
| Change billing / payment methods | ✅ | ❌ | ❌ | ❌ |
| Create or invite users | ✅ | ❌ | ❌ | ❌ |
| Change own email again | ✅ | ✅ | ✅ | ✅ |

*(Columns: pending · change pending · restricted · suspended.)*

**Pending is not restricted.** During the reminder week the account works
normally — it has been told, not punished. The restrictions land at the end of
that week, which is the point of having a week.

**Sending to customers is the line.** Everything else is recoverable
internally; a message leaving the platform under the company's brand from an
account nobody has proved ownership of is not.

**Change-pending keeps sending.** The account was proven; the person is
mid-change. Punishing them for updating their address is how people learn not
to update their address.

---

## 4. Platform administration

Six of the seven required capabilities do not exist.

| Capability | Today |
|---|---|
| Change a user's email | ❌ **No endpoint at all** |
| Force verification | ❌ |
| Resend verification | ✅ exists |
| Extend the deadline | ❌ |
| Remove suspension | ⚠️ Partial — `is_active` only, unrelated to verification |
| See verification history | ❌ |
| Audit every action | ⚠️ Partial — see §7 |

**An admin changing somebody's email must not silently verify it.** The
correct default is: change it, mark it unverified, start the clock, send the
mail. *Force verification* stays a separate, deliberate, audited action — the
answer to "our domain moved and I have confirmed this person by phone", not a
side effect of a correction.

---

## 5. Company administration

Owners may change their own profile freely — name, language, timezone, avatar
— with **only email requiring proof**, because only email is a credential.

Company administrators editing *other* users should reuse the existing
permission (`users.manage`) rather than inventing an identity permission. One
exception: **changing another user's email is an account takeover primitive.**
It should require the same deliberate path as the platform version and be
audited identically.

---

## 6. User experience — never suspended unexpectedly

The brief's requirement is the design constraint, and it decides the
reminder schedule rather than being decorated by it.

Persistent banner from the moment a change is pending, on every screen, not
only the profile page:

> **Confirm your new email address.** We sent a link to `new@example.com`.
> Your account will be suspended in **19 hours** if it is not confirmed.
> **Resend** · **Change the address** · **Contact your administrator**

Reminders at **send**, **+8h**, **+20h** — the last one four hours out, while
the working day can still absorb it. Nobody is suspended having seen only one
message.

On suspension the person can still sign in and sees only: what happened, the
resend button, and how to reach an administrator.

---

## 5a. Identity is event-driven

**History is the truth. Current state is a projection of it.**

The same contract `routing_decisions` and `conversation_ownership` already
keep, and for the same reason: a column tells you what is true now and cannot
tell you how it got that way, who did it, or whether anybody approved.

`identity_events`, append-only, enforced by a database trigger:

| Event | Carries |
|---|---|
| `user.created` | how the account came to exist — registered, invited, imported |
| `email_change.requested` | from → to, actor, reason, IP |
| `email_change.verification_sent` | address, attempt number |
| `email_change.reminder_sent` | which reminder — 24h, 3 days, 7 days |
| `email_change.verified` | the mailbox was proven |
| `email_change.activated` | the credential actually moved |
| `email_change.cancelled` · `.expired` | how it ended |
| `restriction.applied` · `.removed` | reason, actor, until, resolution |
| `account.protected` | which rule, and what would have happened |
| `admin.override` | what was overridden, by whom, why |
| `profile.language_changed` · `.timezone_changed` · `.avatar_changed` | from → to |
| `recovery_contact.added` · `.removed` | *(future)* |
| `health.changed` | which signal, from which state to which |

**Values are copied, never referenced.** "English → Arabic" must still read
correctly when a language is removed from the product, the same rule the
decision log follows for queue and agent names.

Three readers, one stream — which is the point of doing it this way:

- **Audit** — the history in §6a is a rendering of these events, not a
  second record kept in parallel.
- **Notifications** — the reminder mails are consumers, so a reminder that
  was sent is provable rather than assumed.
- **Automation** — the restriction sweep, and whatever comes after it, read
  the same stream.

`account.protected` earns its place by being an event about something that
**did not happen**: the sweep would have restricted an account and did not,
because it was the last owner. Without a row, "nothing happened" and "the
sweep never ran" are indistinguishable — the same reason `LEFT_UNROUTED` is
recorded rather than left as an absence.

**`health.changed` is derived, and the change is still an event.** Identity
Health is a projection (§2b) and must not be stored; the *transition* is a
fact worth keeping, because "when did MFA coverage drop" is a question with no
answer otherwise.

---

## 5b. Every restriction explains itself

A restricted person must never have to guess, or ask.

```
Status        Restricted

Reason        Pending email verification

Applied by    Automatically, by company policy
Applied at    3 Aug 2026, 09:00 UTC
Until         —  (until resolved)

Resolution    Verify your pending email address:
              new@example.com   [ Resend ]  [ Change it ]

              Still stuck? Contact your administrator.
```

The shape, returned by the API and rendered by the UI from the same fields:

| Field | |
|---|---|
| `state` | The code — `restricted`, `suspended`, `pending` |
| `reason` | A code plus its sentence, never prose alone |
| `applied_by` | `policy`, `administrator` (named), or `platform` |
| `applied_at` | |
| `until` | Present only when it genuinely expires. `null` means *until you resolve it*, which is a different thing from "we do not know" |
| `resolution` | What **this person** can do, with the action attached |
| `contact` | Who to ask when the resolution is not theirs to perform |

**The resolution is specific to the reason, and to who is reading.** "Verify
your email" is useful to the person whose email it is. To a colleague looking
at somebody else's restricted account it is noise, and the useful line is
*"they need to verify their email; you can extend their deadline."*

**`resolution` is never empty.** A restriction with no stated way out is a
dead end, and every dead end becomes a support ticket with the same answer. If
the only way out is a platform administrator, the field says exactly that.

This is the same principle the Policy Engine follows — *a denial names the
screen to open* — applied to the person on the receiving end.

---

## 6a. Identity history, in a person's words

Every identity change produces a **readable line**, not a diff of columns. The
audience is a person asking *what happened to my account* — or a support
engineer asking it on their behalf — and neither of them reads JSON.

```
Changed preferred language          English → Arabic
  You · 12 Mar, 09:14

Changed timezone                    UTC → Asia/Amman
  You · 12 Mar, 09:14

Requested email change              old@example.com → new@example.com
  You · 14 Mar, 16:02

Verification sent                   to new@example.com
  System · 14 Mar, 16:02

Verified pending email
  You · 14 Mar, 16:09 · from 82.x.x.x

Activated new email                 old@example.com → new@example.com
  System · 14 Mar, 16:09

Restriction applied                 unverified for 7 days
  System · 21 Mar, 00:04

Restriction removed
  Sara Haddad (administrator) · 21 Mar, 09:30 · "confirmed by phone"
```

Every entry answers four questions, and the fourth is the one systems usually
drop:

| | Source |
|---|---|
| **What changed** | The rendered sentence, with old → new by value |
| **Who** | The actor: the person, an administrator by name, or *System* |
| **Why** | Required for administrator actions, absent for self-service |
| **When** | Plus IP where available |

**Rendered from structured fields, never stored as prose** — the same contract
the routing decision log keeps. The codes are what a console filters on; the
sentence is what a person reads; and a sentence stored instead of its fields
cannot be re-rendered in Arabic.

**The same history, two audiences.** A user sees their own; a platform
administrator sees any. One renderer, one shape, so the support engineer on
the phone is looking at exactly what the customer is looking at.

---

## 7. Audit

`audit_logs` exists — `company_id`, `actor_user_id`, `action`, `entity_type`,
`entity_id`, `details` (JSON), `created_at`. It carries most of what is
needed. Three gaps:

1. **No IP column.** The client address is available (`rate_limit.py` reads
   `request.client.host`) and is not recorded.
2. **No `reason`.** The platform user actions already require a reason and
   put it in `details`; identity changes should make it first-class.
3. **Not immutable.** `routing_decisions`, `service_versions` and the ledger
   tables carry append-only database triggers. `audit_logs` does not — the
   security log is the one table with *no* enforcement, which is exactly
   backwards.

**Old and new values belong in `details`** as a consistent shape rather than a
new table. An email change is `{"field": "email", "from": "...", "to": "..."}`
— the same shape every identity change uses, so one reader renders all of them.

---

## 8. Required changes

### Database

| Change | Table | Note |
|---|---|---|
| `pending_email`, `pending_email_at`, `verification_deadline` | `users` | The change-pending state |
| `recovery_email`, `recovery_email_verified_at` | `users` | Optional |
| `language`, `timezone`, `avatar_url` | `users` | Per-user preference |
| `identity_state` | `users` | Derived or stored — see Risks |
| `ip_address`, `reason` | `audit_logs` | |
| Append-only trigger | `audit_logs` | Matching the ledger's |
| `purpose` on tokens | `email_verification_tokens` | Distinguish signup / change / recovery |

**No backfill needed.** Every existing user is `VERIFIED` if
`email_verified_at` is set and `UNVERIFIED` otherwise, and nobody is
retroactively suspended — see Migration.

### API

- `PATCH /auth/me` — name, language, timezone, avatar *(none of this exists)*
- `POST /auth/me/email` — request a change; returns the deadline
- `DELETE /auth/me/email-change` — cancel a pending change
- `POST /auth/me/email/resend`
- `GET /auth/me/identity` — state, deadline, pending address, history
- `PATCH /platform/companies/{id}/users/{uid}/email`
- `POST …/users/{uid}/verification/force`
- `POST …/users/{uid}/verification/extend`
- `GET …/users/{uid}/identity-history`

### UI

- Profile: real fields, not just a password form *(it has only a password form today)*
- The global verification banner with a live countdown
- Platform Company Users: an email action, force-verify, extend, and history
- A suspended-account screen that explains and offers the fix

### Background

One sweep, in the pattern the SLA and AI sweeps already use: find deadlines
that have passed, suspend, record, notify. Registered with the scheduler
monitor — *a suspension sweep that stops running looks exactly like nobody
missing a deadline.*

---

## Migration strategy

1. **Add columns; change no behaviour.** Deploy, backfill `identity_state`
   from `email_verified_at`.
2. **Ship the read paths** — banner, profile, identity endpoint — so people
   can see and fix their state *before* anything enforces it.
3. **Enable enforcement for email changes only.** Existing unverified accounts
   are untouched: they never agreed to a deadline that did not exist when they
   signed up. Suspending them on deploy day would be the platform breaking its
   own "never unexpectedly" rule at the moment it announces it.
4. **Then** decide, separately and with data on how many are affected, what
   to do about long-unverified existing accounts.

---

## Risks

**Suspending real users through our own bug.** The highest risk in the whole
design. The sweep must be idempotent, must record every suspension as a
decision with its reason, and should have a kill switch. A dry-run mode that
logs what it *would* suspend, run for a week first, is cheap insurance.

**`identity_state` stored vs derived.** Stored is fast and can drift from the
columns it summarises; derived cannot drift and costs a computation per read.
Given this codebase has been bitten by exactly that class of drift twice — the
SLA bands, and the view predicates — I lean **derived**, with the same
dual-path test that caught both.

**Email delivery is now a security dependency.** A provider outage becomes a
wave of suspensions. The sweep should refuse to suspend anybody whose
verification mail is not *confirmed sent*, and pause entirely if the send
failure rate crosses a threshold.

**Two "verifications" in one product.** Company and account verification will
both be called verification by users. They need different words in the UI —
"Confirm your business" and "Confirm your email" — or every support
conversation starts with disambiguation.

**Scope.** This is materially larger than "add a deadline column": three
lifecycle states, a sweep, nine endpoints, four UI surfaces and an audit
hardening. Two to three focused milestones, not a fix.

---

## Recommendation

**Approve the separation of company and account verification.** It is the
change that makes the rest coherent, and the current shared field is a genuine
security weakness — one verified mailbox currently vouches for every account
in a company.

**Approve the change-pending model.** Keeping login on the proven address
until the new one is proven is what makes "never suspended unexpectedly"
achievable rather than aspirational.

**Push back on two points in the brief:** drop contact email from the user
(it belongs to the company), and do not apply the 24-hour rule to new
accounts — 7 days and restriction rather than suspension.

**Sequence it as three milestones**, because the value arrives in that order
and each is independently shippable:

**Phase 1 — Identity.** The domain package and its boundary; per-user profile,
language, timezone, avatar; the identity history and its readable renderer;
`audit_logs` hardened with IP, reason and an append-only trigger. Account
verification separated from company verification, recorded but **enforcing
nothing**. Identity Health showing only signals that exist, with MFA and login
activity as *not available*.

No behaviour changes for anybody. Immediately useful, and it makes Phase 2
mostly wiring.

**Phase 2 — Verification lifecycle.** The email change record and its seven
states; pending changes with login on the proven address; the reminder
schedule; the banner and countdown; the restriction sweep in **dry-run**,
logging what it would do and doing none of it.

**Phase 3 — Enforcement.** Restrictions actually applied; protected-account
rules enforced; the platform administration surface — change email, force,
extend, lift, history.

I would not ship 2 without 1, and I would not ship 3 until 2 has run in
dry-run against real data for a week. The highest risk in the design is
restricting real users through our own bug, and a week of dry-run output is
the cheapest possible insurance against it.

### Two things this review deliberately leaves alone

**`register_company` still spans four domains.** It is company onboarding, not
authentication, and it should move — but it is load-bearing for every test in
the suite and its risk is unrelated to Identity. Separate change, separate
milestone.

**MFA and login-attempt history stay unbuilt.** They are Authentication's, not
Identity's, and Identity Health is designed to report their absence honestly
rather than wait for them.
