# Administrator Guide

**How to configure Blink Engage, setting by setting.**

For the person responsible for a workspace: what each setting does, what
it affects, and what happens if it is wrong. The last part matters most —
most support questions are a setting doing exactly what it was told.

- Using the product day to day: [User Guide](./user-guide.md)
- Deploying and operating the platform: [Production Deployment Guide](../deployment/production-deployment-guide.md)
- Quick answers: [FAQ](./faq.md)

---

## Contents

1. [Setting up a new workspace](#1-setting-up-a-new-workspace)
2. [Company settings](#2-company-settings)
3. [Business hours](#3-business-hours)
4. [Users, agents and roles](#4-users-agents-and-roles)
5. [Departments and teams](#5-departments-and-teams)
6. [Channels](#6-channels)
7. [Services](#7-services)
8. [Queues and routing](#8-queues-and-routing)
9. [SLA policies](#9-sla-policies)
10. [AI configuration](#10-ai-configuration)
11. [Knowledge, FAQs and quick replies](#11-knowledge-faqs-and-quick-replies)
12. [Workflows](#12-workflows)
13. [Notifications](#13-notifications)
14. [ERP integration](#14-erp-integration)
15. [Feature flags](#15-feature-flags)
16. [Billing](#16-billing)
17. [Audit logs](#17-audit-logs)
18. [Configuration resolution](#18-configuration-resolution)

---

## 1. Setting up a new workspace

### What you get automatically

Registration is not an empty shell. Your workspace already has:

- **default roles**, with you as owner,
- a **General queue**,
- a **catch-all routing rule** at the lowest priority,
- a **General service** linking them.

So a customer message cannot arrive with nowhere to go, even before you
configure anything. Every rule you write later outranks the catch-all.

### What you must do

**One thing is genuinely blocking: connect a channel.** Without one there
is no way for a customer to reach you.

Recommended order:

| Order | Task | Why here |
|---|---|---|
| 1 | Company name, timezone | Everything time-based depends on the timezone |
| 2 | **Business hours** | SLA and AI eligibility both use it; wrong defaults are hard to spot |
| 3 | **Connect a channel** | The only blocking step |
| 4 | Invite agents | Optional — a single-owner workspace is valid |
| 5 | Review routing | The catch-all works; refine when you need to |
| 6 | SLA policy | Defaults apply until you set one |
| 7 | AI | Off until configured |

The `/onboarding` wizard walks steps 1–4. It does not currently prevent
you from finishing with no channel connected — see the
[wizard specification](../product/tenant-onboarding-wizard.md).

## 2. Company settings

**Settings → Company**

| Setting | Effect | If wrong |
|---|---|---|
| Name | Shown to customers in templates and surveys | Customers see the wrong company |
| **Timezone** | Base for business hours, SLA, reports, schedules | Every time in the platform is skewed |
| Logo | Branding on surveys and emails | Cosmetic |
| Default language | Fallback when a customer's language is unknown | Wrong-language auto-replies |
| Locale | Date and number formatting | Cosmetic |

> **Set the timezone before anything else.** It is the base for every
> time calculation, and changing it later does not retroactively correct
> reports already generated.

## 3. Business hours

**Settings → Company → Business hours**

Working days, opening and closing times, and holidays.

**What depends on this:**

- **SLA clocks pause outside business hours.** A message at 22:00 does
  not burn overnight against a four-hour response target.
- **AI eligibility** can be scoped to business hours.
- **Notification timing** respects it.

**If you never set it**, platform defaults apply and every hour counts as
a working hour. This is the single most common cause of "our SLA numbers
look wrong" — the targets are being measured against a 24×7 week nobody
works.

Holidays are managed separately and apply on top of the weekly pattern.

## 4. Users, agents and roles

### Users vs agents

A **user** signs in. An **agent** is a user who handles conversations,
with capacity and skills. Every agent is a user; not every user is an
agent.

### Inviting

**Agents → Invite.** They receive a verification email and set their own
password. You never set a password on someone's behalf — you can trigger
a reset.

> Creating an agent through the API creates an **agent**. The role field
> is not honoured there; assign roles explicitly afterwards.

### Roles and permissions

**Roles** grants permissions per action — read, create, update, delete,
per resource. Default roles cover owner, administrator, supervisor and
agent.

Principles worth keeping:

- **Grant the narrowest role that works.** Widening later is easy;
  discovering someone had delete rights for a year is not.
- **Permissions are enforced server-side.** Hiding a menu item does not
  protect anything; the role does.
- **Role changes are audited**, including who made them.

### Deactivating

Deactivate rather than delete. Deactivation preserves conversation
history and audit trail; the person can no longer sign in and is removed
from assignment.

## 5. Departments and teams

**Departments** are organisational units — Support, Sales, Billing. They
group agents and can be routing targets.

**Teams** are working groups within or across departments, used for
assignment and reporting.

Neither is required. A small workspace can run with no departments at
all. Create them when you have a reason — an empty organisational
hierarchy is overhead that has to be maintained.

## 6. Channels

**Channels** is how customers reach you. Supported: WhatsApp, Facebook
Messenger, Instagram, Telegram, Email, SMS, Web Chat, plus a plugin
architecture for others.

### Connecting

Each channel needs credentials from its provider. The connection form
lists exactly what is required.

**Always use Test connection before saving.** Saved-but-unverified
credentials are the most common onboarding mistake: a typo'd token looks
saved, reports no error, and silently receives nothing. The test tells
you within seconds.

### Credentials are encrypted at rest

Channel credentials are encrypted with `CREDENTIALS_ENCRYPTION_KEY`.
Rotating that key requires re-encrypting existing rows — see the
[key rotation runbook](../deployment/runbooks.md#rotate-the-credentials-encryption-key).
A plain key swap makes every stored credential permanently unreadable.

### Health

**Status** shows whether each channel is currently reachable, checked
every five minutes. A channel that has gone unhealthy is usually an
expired token.

## 7. Services

A **Service** is what your company offers — "Technical Support",
"Billing Enquiries". It is the anchor for policy.

**Why services matter:** SLA targets and AI policy resolve *from the
service*, not from platform fallbacks. A workspace that is service-first
gets its own configuration rather than inheriting defaults it never
chose.

Your workspace starts with a **General** service. Add more when different
kinds of work need different policies — not before.

## 8. Queues and routing

### Queues

A **queue** is where conversations wait for an agent. Create one per team
or work type that needs its own waiting line and its own metrics.

### Routing rules

**Rules are evaluated by priority, highest first.** The first match wins.
Conditions can test channel, keywords, language, customer attributes and
business hours.

The seeded **catch-all sits at the lowest possible priority** with empty
conditions, so it catches whatever nothing else claimed. Every rule you
add outranks it automatically.

**Do not delete the catch-all.** Without it, a conversation matching no
rule is recorded as `LEFT_UNROUTED` and sits where no agent is looking.
The Inbox flags this as critical, but the conversation is still waiting.

### Assignment

Once in a queue, the assignment engine picks an agent by availability,
current load, capacity and skills. Ownership expires if untouched, so a
conversation is not stranded on someone who went home.

## 9. SLA policies

**SLA** defines targets for the four clocks: first response, next
response, resolution, idle.

| Setting | Meaning |
|---|---|
| Target | The time allowed |
| Warning threshold | When to warn before breaching |
| Business hours | Whether the clock pauses outside working hours |
| Scope | Which service or queue it applies to |

**Almost always leave business hours enabled.** A four-hour first-response
target measured around the clock means an 18:00 message breaches before
anyone is back.

SLA warnings and breaches are visible in the Inbox, drive notifications,
and stop AI autopilot — a conversation in SLA trouble is handed to a
person.

## 10. AI configuration

**Settings → AI.** Requires the `ai` feature.

### Provider

OpenAI, Claude or Ollama. Ollama runs locally, which matters for
customers who cannot send conversation content to a third party.

### Policy

| Setting | Effect |
|---|---|
| **Enabled** | Master switch |
| **Autopilot** | Whether AI may reply without an agent |
| **Confidence threshold** | Below this, AI hands off instead of answering |
| **Pickup delay** | How long to wait for a human before AI steps in |
| **Resume delay** | How long after an agent goes quiet before AI resumes |
| **Business hours only** | Restrict AI to working hours |

**The confidence threshold is the dial that matters.** Too high and the AI
hands off everything, adding latency for no benefit. Too low and it
answers questions it should not. Start conservative and lower it while
watching the AI report.

### What AI cannot do

It cannot see other companies' data, cannot act outside the conversation,
and stops automatically on SLA trouble. Suggestions to agents are never
auto-sent.

## 11. Knowledge, FAQs and quick replies

> **No management screen exists in this release.** The capability is real
> — knowledge powers AI answers and appears in search — but it is
> maintained through the API. Ask your provider to load or change
> content. The same applies to §12 Workflows.

| | Visibility | Publishing |
|---|---|---|
| **Knowledge article** | Internal by default | Immediate |
| **FAQ** | Written for customers | **Starts unpublished** |
| **Quick reply** | Internal | Immediate |

FAQs start unpublished deliberately: unlike an article, an FAQ is written
to be shown to customers. Unpublishing also removes it from search, so
nothing can quote something you have taken down.

**Keep knowledge current.** The AI answers from it. An out-of-date article
produces a confidently wrong answer, which is worse than no answer.

## 12. Workflows

> **No workflow builder exists in the interface.** Workflows are
> configured through the API by your provider.

The workflow engine triggers actions on events — assign, notify, tag,
transfer, call a webhook.

**A workflow can trigger on any event type.** All 99 are available; see
the [Event Catalogue](../architecture/event-catalogue.md).

Build them narrowly. A workflow triggering on a broad event and acting
unconditionally will act far more often than intended.

## 13. Notifications

Configure which events notify whom, and by which channel — in-app, email,
push.

**Email** requires SMTP configuration.
**Push** requires `FCM_SERVICE_ACCOUNT_JSON`. If unset, the platform
sends nothing and does not mark notifications as pushed — so configuring
it later starts delivering immediately.

Be sparing. A notification that fires on everything is muted within a
week, and then the one that mattered is muted too.

## 14. ERP integration

**ERPNext**, if the `erp` feature is enabled. Synchronises customers,
invoices, sales orders, quotations, support tickets, payments and
contacts.

Connection requires an ERPNext URL and API credentials, encrypted at rest
like channel credentials.

## 15. Feature flags

Six commercial flags, controlled by your plan rather than by you:

| Flag | Controls |
|---|---|
| `ai` | AI Engine |
| `erp` | ERP Integration |
| `workflows` | Workflow Engine |
| `knowledge_base` | Knowledge Base |
| `sla` | SLA Management |
| `reports_export` | PDF and Excel export |

A disabled feature is **hidden entirely**, not shown-and-blocked.

> **Flags and permissions are different questions.** A permission asks
> whether *you* may do something; a flag asks whether your *company* has
> it. A 403 can mean either, and the message distinguishes them.

## 16. Billing

**Billing** shows usage, invoices, payments and credit notes. Usage is
metered from conversation and message events as they happen.

Invoices generate hourly for closed periods. A `usage.late_record_rejected`
event means usage arrived after its period closed — worth investigating if
frequent, as it points at a lagging consumer.

## 17. Audit logs

Every domain event is audited: who, what, when, and the correlation id
tying it to the originating request.

**Audit logs are append-only and exempt from all retention.** They are not
pruned, ever — an audit trail is meant to outlive the records it
describes.

Use them for "who changed this and when", and for anything that needs to
be defensible after the fact.

## 18. Configuration resolution

Configuration resolves through exactly one chain:

```
Service  →  Queue  →  Company  →  Platform default
```

The most specific value wins. If a service defines an SLA target, it is
used; otherwise the queue's; otherwise the company's; otherwise the
platform default.

**There is exactly one chain**, enforced by a test that fails the build.
Nine competing fallbacks once disagreed with each other, and which answer
you got depended on which code path you happened to hit.

A daily sweep checks for **configuration drift** — settings that are set
but not obeyed — and reports it.

---

## Common mistakes

| Symptom | Usual cause |
|---|---|
| SLA numbers look wrong | Business hours never configured |
| Customers cannot reach us | No channel connected, or credentials never tested |
| Conversations go nowhere | Catch-all routing rule deleted |
| AI never answers | Feature off, provider unconfigured, or threshold too high |
| AI answers badly | Knowledge base out of date |
| Nobody gets notified | SMTP or FCM not configured |
| Agent cannot see a screen | Role lacks the permission, or plan lacks the feature |
| Times are all shifted | Company timezone wrong |
| PayPal still in sandbox | `PAYPAL_ENVIRONMENT` does nothing — use `PAYPAL_SANDBOX` ([TD-1](../releases/v1.0-technical-debt.md#td-1)) |

## See also

- [**Blink Engage User Guide**](./blink-engage-user-guide.md) — the full product manual
- [User Guide](./user-guide.md)
- [FAQ](./faq.md)
- [Onboarding wizard specification](../product/tenant-onboarding-wizard.md)
- [Production Deployment Guide](../deployment/production-deployment-guide.md)
- [SYSTEM.md](../SYSTEM.md)

## Redacting a message

`messages.redact` — Administrators and the Owner.

Removing what one message said, keeping that it was said. A message sent
over WhatsApp or email cannot be unsent, so deleting our copy would
destroy our half of a record the customer still holds.

**It is irreversible and there is no recovery path.** Nothing in the
product will show the content again, for anybody. Restoring it means
restoring a backup taken before the redaction.

Redaction removes the text, the provider's stored copy of it, any
attachments from object storage, and every citation of the message in
Memory and Learning. It leaves the message in the thread and writes an
append-only record of who did it, when, and why.

Agents do not hold this permission and should not be granted it lightly:
a redaction cannot be undone by whoever notices the mistake a minute
later.

**It is not conversation deletion.** `conversations.delete` — which
removes a whole conversation with no reason recorded, and which also
gates bulk destruction through agent removal — remains Owner-only.
Granting `messages.redact` does not affect it.

Review what has been redacted at `GET /api/v1/message-redactions`. That
log names customers and quotes the reasons given, so it is gated on the
same permission as performing a redaction.

See `docs/architecture/message-redaction.md`.
