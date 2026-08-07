# Tenant Onboarding Wizard — Specification

**Status:** specification. Not implemented.
**Scope:** enhancing the wizard that already exists, not building a new one.
**Goal:** a new tenant cannot finish onboarding in a state where a
customer message would go unanswered.

---

## 1. What already exists

Two things are already in place, and the specification is much smaller
because of them.

### 1.1 Registration seeds a working routing chain

A newly registered company is **not** an empty shell. `auth_service`
creates, inside the registration transaction:

- default roles, and the owner assigned to one,
- a default **Queue**,
- a **catch-all RoutingRule** at the lowest possible priority,
- a default **Service**, giving `Company → Service → Queue → rule`.

So the worst failure — a message arriving and reaching no queue, sitting
where no agent is looking — **is already solved**. Any rule an
administrator writes later outranks the catch-all, so this is a floor
rather than a competitor.

### 1.2 A four-step wizard exists

`frontend/src/features/onboarding/OnboardingWizardPage.tsx`, route
`/onboarding`:

| # | Step | Component |
|---|---|---|
| 1 | Company information | `CompanyInfoStep` |
| 2 | Team setup | `TeamSetupStep` |
| 3 | Channels | `ChannelsStep` |
| 4 | ERP integration | `ErpIntegrationStep` |

Position is persisted to `sessionStorage`, so a reload resumes where the
administrator was. Each panel saves independently, so data is never lost
between steps.

**The sequence is right.** Company identity, then people, then how
customers reach you, then integrations, is the correct order.

## 2. What is wrong with it

The wizard is a **navigation shell around existing settings panels**, not
a guided setup. Specifically:

### 2.1 Nothing is required

`Next` is never disabled. `Finish` performs no validation. A "Skip setup"
button sits on every step and does the same thing as finishing.

An administrator can open `/onboarding`, click through four times, and
land on a dashboard for a company that has **no channel connected** — so
no customer can reach them at all — with the platform reporting setup as
complete.

```tsx
function finish() {
  finishMutation.mutate({ settings: { onboarding: { completed: true } } }, ...)
}
```

`completed: true` is asserted, never checked.

### 2.2 The one genuinely blocking gap is invisible

Of everything the wizard covers, exactly one item makes the difference
between a platform that works and one that cannot: **at least one
connected channel**. Without it there is no inbound path. The wizard
treats it as the third of four equal steps.

### 2.3 It says nothing about what it did for you

Registration created a queue, a catch-all rule and a service. The wizard
never mentions them. An administrator does not learn that routing already
works, so they either duplicate it or assume it is missing.

### 2.4 No business hours or SLA step

SLA clocks and AI eligibility both depend on business hours. A company
that never sets them gets platform defaults, silently — and then reports
that "SLA times look wrong" because the platform counted overnight hours
as working time.

### 2.5 No completion summary

There is no point at which the administrator sees "here is what is
configured, here is what is missing, here is what will happen when a
customer messages you."

---

## 3. Specification

### 3.1 Principle

> **The wizard's job is to make the tenant reachable, not to collect
> every setting.**

Everything that is not required for a customer message to arrive and be
answered is *optional* and clearly marked so. Everything that is required
blocks completion. There is no third category.

### 3.2 Step model

Each step declares its own completion state, and the wizard derives
whether finishing is allowed:

```ts
type StepStatus = 'complete' | 'incomplete' | 'skipped'

interface WizardStep {
  key: string
  required: boolean          // blocks Finish when incomplete
  status(): StepStatus       // derived from server state, never from local flags
  summary(): string          // one line for the completion screen
}
```

**`status()` must be derived from server state**, not from a local
"visited" flag. A step is complete because the thing it configures
exists, not because somebody looked at it. This is the single most
important rule in the spec: the current wizard's defect is that it
records intent rather than fact.

### 3.3 Steps

| # | Step | Required | Complete when |
|---|---|---|---|
| 0 | **What is already set up** | — | informational; no input |
| 1 | Company information | ✅ | name and timezone set |
| 2 | Business hours | ✅ | at least one working day defined |
| 3 | Channels | ✅ | **≥ 1 channel connected and verified** |
| 4 | Team | ⬜ | ≥ 1 agent invited *(optional — see below)* |
| 5 | Routing & SLA | ⬜ | reviewed |
| 6 | AI | ⬜ | reviewed |
| 7 | Go-live check | — | all required steps complete |

**Step 0 — What is already set up.** New. A read-only panel:

> Your workspace already has a **General** queue, a **General** service,
> and a catch-all routing rule, so no message can arrive with nowhere to
> go. You can refine this later under Routing.

This costs one screen and removes the most common early support question.

**Step 2 — Business hours** is promoted to required because SLA and AI
eligibility silently depend on it, and a wrong default is harder to
notice than a missing value.

**Step 4 — Team is optional, deliberately.** A single-owner company where
the owner answers conversations is a legitimate configuration, and
blocking on "invite somebody" would be a wizard inventing a requirement
the platform does not have.

**Step 7 — Go-live check.** New. See §3.5.

### 3.4 Channel verification

Channel connection is the only genuinely blocking step, so it gets the
strongest treatment: **connect, then prove it.**

```
[ Connect WhatsApp ]  →  credentials  →  [ Test connection ]
                                              │
                            ┌─────────────────┴─────────────────┐
                       ✅ verified                        ❌ failed
                    step complete                  step stays incomplete
                                                   error shown verbatim
```

`channel_config.test_connection_ephemeral` already exists as an event, so
the test path is built. The change is that the wizard **requires a
successful test**, not merely saved credentials.

Saved-but-unverified credentials are the failure this prevents: the most
common onboarding mistake is a typo'd token that looks saved and silently
receives nothing.

### 3.5 The go-live check

The final step replaces "Finish" with a readiness summary:

```
  Ready to go live
  ─────────────────────────────────────────────
  ✅  Company          Acme Ltd · Asia/Amman
  ✅  Business hours   Sun–Thu, 09:00–17:00
  ✅  Channels         WhatsApp (verified 2 min ago)
  ✅  Routing          General queue · catch-all rule active
  ⬜  Team             No agents invited — you will handle
                       conversations yourself
  ⬜  SLA              Using platform defaults
  ⬜  AI               Disabled

  When a customer messages your WhatsApp number, the
  conversation will land in the General queue and notify you.

  [ Go live ]
```

The sentence beginning **"When a customer messages…"** is the point of
the whole screen. It states the outcome in the administrator's terms and
is generated from actual configuration, so if it reads wrong, something
is wrong.

`Go live` is enabled only when every required step is complete. When it
is not:

> **Connect a channel before going live.** Without one, customers have no
> way to reach you. [Go to Channels]

### 3.6 Skip

"Skip setup" is removed from required steps and kept on optional ones as
"Skip for now", which marks the step `skipped` — visibly distinct from
`complete` on the summary.

An administrator who genuinely wants to leave without finishing uses
browser navigation; the wizard does not need a button that undoes its own
purpose. Onboarding remains resumable from the existing banner.

### 3.7 Resumability

Already correct and unchanged: position in `sessionStorage`, data saved
per panel. One addition — because `status()` is derived from server
state, a step completed in Settings *outside* the wizard shows as
complete when the administrator returns. The wizard reports reality
rather than its own history.

---

## 4. API

No new endpoints are required. Every step reads and writes through
existing APIs:

| Step | Endpoint |
|---|---|
| Company | `GET/PATCH /api/v1/company` |
| Business hours | `GET/PUT /api/v1/company/business-hours` |
| Channels | `GET /api/v1/channels`, `POST /api/v1/channels/{id}/test` |
| Team | `GET /api/v1/agents`, `POST /api/v1/agents` |
| Routing | `GET /api/v1/queues`, `GET /api/v1/routing-rules` |
| SLA | `GET /api/v1/sla-policies` |
| AI | `GET /api/v1/company` (AI config) |
| Completion | `PATCH /api/v1/company` → `settings.onboarding.completed` |

**One optional addition** worth considering: a single
`GET /api/v1/company/onboarding-status` returning each step's derived
status in one round trip. Seven parallel requests to render one screen is
workable but wasteful, and putting the derivation server-side means the
same answer is available to support tooling and to the wizard. It is
optional because the client can derive all of it today.

## 5. What this does not change

- **No new tables.** Completion already lives in `company.settings`.
- **No routing changes.** The seeded catch-all stays exactly as it is.
- **No permission changes.** The wizard is owner/admin only, as now.
- **No change to registration.** Seeding already happens and is correct.

## 6. Acceptance criteria

1. A company with no connected channel **cannot** reach "Go live".
2. Saved-but-unverified channel credentials do **not** complete step 3.
3. Configuring business hours in Settings marks step 2 complete without
   opening the wizard.
4. The completion screen's "When a customer messages…" sentence reflects
   the actual queue and notification target.
5. Reloading mid-wizard resumes on the same step with no data loss.
6. An owner-only company can complete onboarding without inviting anyone.
7. The wizard states that a queue, service and catch-all rule already
   exist.

## 7. Effort

| Item | Estimate |
|---|---|
| `status()` derivation per step | 1 day |
| Step 0 (what already exists) | 2 hours |
| Business hours step | half a day |
| Channel verification gate | half a day |
| Go-live summary screen | 1 day |
| Remove/rework skip semantics | 2 hours |
| Tests | 1 day |
| **Total** | **~4 days** |

The optional `onboarding-status` endpoint adds roughly half a day.

---

## See also

- [Administrator Guide](../guides/administrator-guide.md) — what each setting does
- [User Guide](../guides/user-guide.md)
- [FAQ](../guides/faq.md)
- `docs/architecture/company-onboarding.md` — the existing mechanism
- [V1.0 Baseline](../releases/v1.0-baseline.md)
