# Blink Engage — System Documentation

**What the platform does, feature by feature, and how each one actually
works.**

This is the functional companion to
[`architecture/platform-handbook.md`](architecture/platform-handbook.md).
The handbook explains the *architecture* — bounded contexts, invariants,
diagrams — for engineers holding the whole system in their head. This
document explains the *product*: every capability that exists, what it
does for a customer, and the mechanism behind it.

Read this if you are onboarding, writing a proposal, supporting a
customer, or deciding whether a feature already exists before building
it.

**Scope: what is in the code today**, traced against the source rather
than a roadmap. Where something is designed but not built, it is in
[§14 Not built](#14-what-is-not-built) rather than described as if it
worked.

| | |
|---|---|
| Version | `1.1.0` (stable), plus unreleased work in the tree |
| HTTP + WebSocket routes | **332** |
| Database tables | **99** across 86 migrations |
| Domain event types | **99** |
| Background consumers | **12** |
| Scheduled jobs | **19** |
| Automated tests | **3,472** backend, 470 frontend |

---

## Contents

1. [What Blink Engage is](#1-what-blink-engage-is)
2. [Accounts, access and tenancy](#2-accounts-access-and-tenancy)
3. [The organisation: departments, teams, agents](#3-the-organisation)
4. [Customers](#4-customers)
5. [Channels — the seven ways a customer reaches you](#5-channels)
6. [Conversations](#6-conversations)
7. [Routing, queues and assignment](#7-routing-queues-and-assignment)
8. [SLA: the four clocks](#8-sla-the-four-clocks)
9. [Automation: policies and workflows](#9-automation)
10. [AI](#10-ai)
11. [Knowledge, FAQs, quick replies and notes](#11-knowledge-faqs-quick-replies-and-notes)
12. [The intelligence layer: memory and learning](#12-the-intelligence-layer)
13. [Reporting, billing and administration](#13-reporting-billing-and-administration)
14. [What is not built](#14-what-is-not-built)
15. [How a message becomes a reply](#15-how-a-message-becomes-a-reply)

---

## 1. What Blink Engage is

An **enterprise AI-powered omnichannel customer engagement platform**.
Concretely: one inbox for seven channels, an operations layer that can
explain every decision it made, and an intelligence layer that earns
trust before it acts.

Three properties distinguish it from the category, and they show up in
almost every feature below.

**Everything explains itself.** Routing, assignment, SLA, ownership,
policy and AI each write down *why* they did what they did. "Why is this
conversation here and why has nobody answered it?" is answered by a
stored timeline, not by reasoning backwards from the current state.

**Nothing fails silently.** The platform's recurring bug class is *"a
thing that quietly stopped happening"*, so the codebase carries an unusual
density of structural guards: the container refuses to boot if a critical
collaborator is missing, static tests fail the build if code writes where
it should not, and every background sweep records that it ran.

**The AI layer is deliberately constrained.** AI waits before it answers,
gives conversations back when it is unsure, quotes only approved
material, and — in the intelligence layer — measures itself before
proposing anything.

---

## 2. Accounts, access and tenancy

### Signing up

`POST /auth/register` creates, in one transaction: the **company**
(tenant), its **Owner** user, and the seeded Owner/Admin/Agent roles.
There is no separate provisioning step.

### Signing in

| Feature | How it works |
|---|---|
| **Login** | Email + password → a short-lived access token (15 min) and a long-lived refresh token (30 days) |
| **Session revocation** | Refresh tokens are individually revocable and rotate on every refresh, tracked in Redis. Killing one session does not kill the others |
| **Password rules** | 10 characters, letter + digit — one validator, applied identically at registration, agent creation, admin reset and self-service change |
| **Password reset** | Owner/Admin can reset any agent's password; every agent can change their own. **Both revoke every refresh token for that user** |
| **Email verification** | A tokened link; unverified accounts are restricted rather than blocked outright |
| **Rate limiting** | Register, login, refresh, logout and the public survey endpoint are rate-limited per IP |

### Permissions

Role-based, with a seeded catalog of permissions like `conversations.read`,
`channels.manage`, `memory.erase`. Roles are per company and editable —
except **Owner**, which holds every permission and cannot be edited or
deleted.

**Permissions travel inside the access token**, so checking one costs no
database query. The accepted trade: a permission change takes effect
within the 15-minute token window.

Two things are re-read from the database on *every* request, because both
are decisions an operator expects to be instant:

- **whether the account is a platform administrator**
- **whether the company is suspended**

### Tenant isolation

Row-level within one database, enforced at five independent layers:

1. The access token carries `company_id`. A platform token carries none
   and is rejected from tenant endpoints outright.
2. `company_id` is a **required argument** on every repository read — a
   cross-tenant query is hard to write, not merely wrong to write.
3. Vector search takes `company_id` as a required argument, so a
   cross-company semantic search is **inexpressible**. This matters more
   than it sounds: a similarity index ranks *before* filters apply, so a
   "search then filter" implementation would return whatever fraction of
   its results happened to be the right tenant's.
4. Search results are re-filtered by company when hydrated.
5. A suspended or deleted company is refused on every request.

Measured, not assumed: a harness with 10,000 vectors across 20 tenants
returned **zero** cross-tenant rows across 40 queries.

---

## 3. The organisation

| Feature | What it does |
|---|---|
| **Departments** | The top-level split — Sales, Support, Billing. Agents belong to one |
| **Teams** | Groups within (or across) departments |
| **Agents** | An operational profile on top of a user: title, status, department, team, skills |
| **Agent status** | `ONLINE` / `AWAY` / `OFFLINE`. Connecting the app flips OFFLINE→ONLINE but **never overrides an explicit AWAY**; disconnecting always sets OFFLINE |
| **Skills** | A company-scoped catalog. Queues can require them, which narrows who a conversation can be assigned to |
| **Business hours & holidays** | Per company. SLA clocks and AI behaviour read them |

**A detail worth knowing:** deleting a department is a *soft* delete, so
the database's own "set null on delete" never fires. The platform clears
`department_id` on affected agents explicitly — otherwise agents would
keep pointing at a department that had become invisible everywhere else.

---

## 4. Customers

| Feature | What it does |
|---|---|
| **Profiles** | Name, email, phone, timezone, language, tier, VIP flag, custom fields |
| **Tags** | A company-scoped catalog, created on first use, shared with knowledge articles and FAQs |
| **Channel identities** | One customer, many channel handles — a WhatsApp number, a Telegram id, an email address |
| **Search** | By name, email or phone |
| **Timeline** | Every conversation, composed from the customer's history |
| **Internal ratings** | Agents' own private assessment of a customer, separate from CSAT |
| **ERP records** | Invoices, orders, quotations, tickets, payments pulled from ERPNext |

### How identity resolution works

When a message arrives, the platform has to decide *who* sent it.

- **Email** resolves on the customer's email address directly — an
  unambiguous field that already existed.
- **Everything else** resolves through one channel-agnostic mapping
  table. WhatsApp, Telegram, Messenger, Instagram and SMS all use the
  same path, with **no per-channel resolution code**.
- **Web chat** resolves before the first message: the visitor session
  already created the customer.

An unrecognised sender creates a new customer. An anonymous web-chat
visitor is normal, not an error.

---

## 5. Channels

Seven, all landing in the same conversation model.

| Channel | Inbound | Outbound | Notes |
|---|---|---|---|
| **WhatsApp Business** | Meta Cloud API webhook | Send API | Real read receipts. No edit/delete — the platform has none |
| **Telegram** | Bot API webhook | Bot API | Real edit, delete **and** typing indicators |
| **Facebook Messenger** | Meta webhook | Send API | Real typing. No edit/delete |
| **Instagram** | Same Meta platform | Send API | Same as Messenger |
| **Email** | IMAP polling **or** provider webhook | SMTP | Threads resolved from mail headers |
| **SMS** | Gateway webhook | Gateway API | Twilio today; the gateway is itself a plugin |
| **Web Chat** | WebSocket | WebSocket | No external vendor at all |

### How the plugin architecture works

Every channel implements the same 11-method contract: send, receive,
edit, delete, mark-as-read, typing, upload, download, webhook, verify
signature, health check.

**Unsupported capabilities are honest no-ops with documented reasons, not
fake implementations.** SMS has no edit, delete, read receipt or typing at
the carrier level; email has no provider-side equivalent for any of the
four. The platform says so rather than pretending.

Channels are looked up by a string stored in the database, so adding one
means writing a class and registering it — no changes to the conversation
engine. SMS goes one level deeper: it is a plugin whose *gateways*
(Twilio, and others later) are themselves plugins.

### Connecting a channel

- A **guided wizard** per channel, rendered from a manifest rather than
  hand-built per channel
- **Credential-shape validation** before saving
- **"Test connection"** both before saving and against a saved channel
- A **health sweep** every 5 minutes, logging only transitions
- A **connection log** timeline per channel
- **Reconnect** — rotate credentials on an existing channel without
  losing its history

### Two safety properties

**Credentials never leak into error text.** A provider's own health-check
failure can echo the access token back (it sits in the request URL).
Every place provider error text becomes a stored or returned string
passes through a redaction boundary first.

**A generated secret is shown exactly once.** The auto-generated webhook
secret is returned only from the create call — the one moment a
server-generated secret may leave the server — and never echoed
afterwards.

---

## 6. Conversations

### The lifecycle

```
NEW → WAITING → IN_PROGRESS ⇄ WAITING_CUSTOMER / WAITING_AGENT
                   ↓
              RESOLVED → CUSTOMER_FEEDBACK → CLOSED
                   ↑                            │
                   └────────── reopen ──────────┘
```

Status, queue and owner are **three independent facts**. A conversation
can be `WAITING` in a queue owned by nobody, `IN_PROGRESS` owned by AI, or
`RESOLVED` and still owned by the agent who resolved it.

### What a conversation carries

| | |
|---|---|
| **Messages** | Inbound and outbound, with separate delivery and read status |
| **Attachments** | Type- and size-validated, stored in object storage. Images, documents, audio and video render inline |
| **Internal notes** | A separate thing from messages — a note was never sent through a channel and has none of a message's delivery concerns |
| **Transfers** | To an agent or a department, with a structured reason and an optional note |
| **Ownership timeline** | Append-only: who had it, when, and why it moved |
| **SLA clocks** | Four, running independently |
| **Decision log** | Every routing, policy, assignment and SLA decision |

### Reopening

A customer writing back to a finished conversation **reopens it into the
queue** — never straight to whoever used to have it. Whether the previous
owner gets it again is the ownership rules' decision; deciding it at
reopen time would re-couple status to owner.

### The Conversation Inspector

`GET /conversations/{id}/inspector` — the "black box". One call answers
six questions: which service it resolved to and why, which queue and why,
what every policy decided, who owned it and when, what the clocks did,
and what AI decided. **Not a paid extra** — explaining what the platform
did is not a feature you sell.

### The Inbox

Views rather than filters: *Needs attention*, *Mine*, *Unassigned*,
*Breached*. Ordered by **SLA health first** — priority does not override
a clock about to run out. Ownership is shown, never inferred.

---

## 7. Routing, queues and assignment

### The path a new conversation takes

```
Customer → Service → Logical queue → Runtime queue → Agent
```

### Service resolution

Four strategies, in order, each recording what it looked at:

1. **Customer selection** — the customer picked a service. First, and it
   has to be: a classifier overriding that would be the platform telling
   somebody they are wrong about their own problem.
2. **Business rules** — the company's conditions on channel and keywords.
3. **Fixed service** — one service, or a nominated default.
4. **Fallback** — so a conversation always lands somewhere.

The resolved service is **frozen by version** onto the conversation. An
administrator halving an SLA target at noon does not move the deadline of
every conversation opened that morning.

### Queues

- **Logical queues** are what a company configures: name, assignment
  strategy, SLA policy, AI opt-in, required skills
- **Runtime queues** are the lanes inside one (VIP vs standard)
- **Assignment strategies**: round-robin, or least-load measured
  *company-wide* — the point of load balancing is total workload, not a
  per-queue count

### The Queue First Principle

A conversation in a queue is **owned by the queue**, not "unassigned". A
conversation nobody has picked up is still somebody's problem — findable,
escalatable, and counted.

### Why decisions are recorded

Both engines *decide and describe*; neither writes. The assignment engine
returns the chosen agent **and every rejected candidate with the reason
they were passed over**. "Why isn't this with Ada?" is answerable only if
Ada was recorded at the moment she was skipped.

Likewise, "no routing rules at all" and "rules that all missed" are
recorded as two different reasons — same symptom, different fixes.

---

## 8. SLA: the four clocks

| Clock | Answers | Settles when |
|---|---|---|
| **Queue** | How long until somebody took it? | Ownership is accepted — **not** when a reply is sent |
| **First response** | How long until the customer heard back? | The first outbound message |
| **Next response** | How long between subsequent replies? | Each outbound message |
| **Resolution** | How long until it was over? | Resolution |

Three start together when a conversation enters a queue — the customer is
simultaneously waiting for someone to take it, for a first reply, and for
the whole thing to end.

**Targets are copied onto the clock when it starts**, not read through a
join on every check. That is what makes "an administrator's edit does not
move a running deadline" true without a lookup per sweep.

Other properties:

- **Business-hours aware**, including per-company holidays
- **Health bands** — healthy / at risk / breaching / breached — drive
  Inbox ordering
- **Warning and breach** are separate events; breach can trigger AI,
  workflows and notifications
- **Running out of time is not an event** — nothing happens, which is
  exactly the problem — so a sweep every 60 seconds notices

### One resolver, and why

SLA targets once had two owners: the queue's attached policy (written by
the UI) and the service version (read by the engine). Result: **zero SLA
clocks across the entire installation**, a permanently empty Breached
queue, and nothing reporting a problem.

Now one resolver answers both SLA targets *and* AI policy down the same
chain — **service → queue → company → platform default** — and each answer
carries the tier that produced it.

---

## 9. Automation

### The Policy Engine

**Every business rule lives here, and only here.** Modules do not evaluate
rules; they ask.

Eleven policies, including: may AI answer this? may this be routed? may it
skip the queue? may an agent take it? may the platform remember anything?
may it learn from what it remembered?

An evaluation never returns a boolean. It returns a decision with an
**effect**, a **reason** from a closed set, and a **source** — the field
an administrator actually needs. "Denied" sends them hunting; *"denied,
from the Customer Context"* tells them which screen to open.

Three properties worth knowing:

- **Denial order is narrowest-first.** When several rules would deny, the
  reported one is the one that stays true after the broader ones are
  fixed. A customer's opt-out is reported before "the company has AI off",
  because it survives an administrator turning AI back on.
- **AI engagement fails closed.** The AI switch is a compliance promise,
  so a caller that fails to supply the company's capabilities is
  *refused*, not granted permission by omission.
- **Allowances are recorded, not just refusals.** "Why was this
  permitted?" is the question asked after something reached a customer
  that should not have.

### The Workflow Engine

Event-triggered automations: when *X* happens, if *conditions*, do
*actions*.

- **Triggers** — any of the platform's 99 event types
- **Conditions** — nested all/any trees, deliberately not a full
  expression language, so a visual builder stays possible
- **Actions** — add a tag, assign to a queue or agent, set status, send a
  reply, create a notification, publish an event

Every run is recorded — matched, failed *or skipped* — and one workflow
failing never affects another.

### Notifications

- A durable per-user inbox, plus live delivery over WebSocket
- Email and push dispatch, each on its own sweep
- Per-user preferences and registered devices
- Platform email settings are separate from a company's own email
  channel, so a notification reaches an agent even at a company with no
  customer-facing email configured

---

## 10. AI

### The ten capabilities

Reply suggestions · conversation summary · translation · language
detection · sentiment analysis · auto-tagging · knowledge search · **FAQ
search** · grammar improvement · professional rewrite · next best action.

### Providers

OpenAI, Claude, Ollama, Gemini, Azure OpenAI, Mistral, Groq, DeepSeek —
selected per deployment, overridable per company. **One `complete()`
method**, not one per feature, so prompt engineering lives in one place.

An unconfigured platform returns a clear "AI is not configured" error,
never a silent empty result.

### AI Autopilot: a queue worker, not a first responder

The most important AI decision in the platform.

When AI is permitted to answer, it **does not answer immediately**. The
conversation sits in its queue, visible, for the service's pickup delay
(30 seconds by default), so a human gets first refusal. Only if nobody
takes it does AI pick it up.

**AI is an owner, not an absence.** When it engages, it takes ownership —
so "nobody has it" is never false, and the moment it hands back has
something to be a transition *from*.

Three ways AI can activate:

| Trigger | When |
|---|---|
| **New message** | A customer writes on an AI-enabled queue |
| **SLA** | A response target is slipping — *because* nobody replied, so no new message is coming |
| **Agent request** | A human presses "Ask AI to reply" |

### Handing back

Below its confidence threshold, AI clears its own flag, returns ownership
to the queue, and raises a handoff notification. An agent can also take a
conversation back from AI at any time.

### Safety properties

- **Auto-tagging can only pick from the company's real tag catalog** — a
  hallucinated tag is structurally impossible
- **Next Best Action is advisory only** — surfaced to the agent, never
  executed
- **Every AI reply is marked as AI-generated**, and drafts an agent
  edited are marked as AI-assisted. Billing and the learning layer both
  read those marks
- **Per-user rate limiting** on every AI endpoint, because AI calls cost
  real money and several agents share one office IP

---

## 11. Knowledge, FAQs, quick replies and notes

### Knowledge base

Categories (nestable) and articles, tagged from the shared catalog,
published or draft.

**Search is hybrid.** Two retrievers run and their results are fused:

- **Lexical** — trigram similarity, which is language-agnostic and
  therefore works for Arabic, English and the mixture customers actually
  write. This is the half that finds an order number, a plan name or a
  SKU exactly.
- **Semantic** — vector similarity, which finds an article that answers
  the question in different words. *"Can I get my money back"* finds
  *"Refund policy"*.

They are combined by rank rather than score, because the two scores are
not comparable and normalising them is a tuning exercise that never
converges. A document found by **both** outranks one found brilliantly by
either.

**Why this matters here specifically:** pure vector search is weakest at
exactly what support retrieves most. *"Plan B"* and *"Plan D"* embed
almost identically, and quoting the wrong one is a wrong answer delivered
confidently.

**Degradation is explicit.** With no embedding provider configured,
search runs lexical-only and *says so*. A worse search, never a broken
feature.

**Indexing** happens on a 60-second sweep, not on the write path — because
embedding calls a metered external API, and doing it inline would put a
vendor's latency on the request an author is waiting for. Re-indexing is
incremental by content hash: correcting a typo in a forty-chunk manual
costs one embedding call, not forty.

### FAQs

A published question and its answer — **its own entity**, not a flag on an
article, and the difference is worth understanding:

| | Article | FAQ |
|---|---|---|
| Found by matching | Prose in a body | **A question** |
| Embedding | Chunked into many vectors | **One vector** |
| Order | None | **Curated** |
| Audience | Agents, internally | **The customer** |
| Created as | Published | **Unpublished** |

That last row is the clearest expression of the split: an unfinished
*article* is seen by agents, who can tell a draft from a policy; an
unfinished *FAQ* is seen by customers, who cannot.

**What FAQs give you:**

- Hybrid search of their own, matching the question *and* the answer — so
  a customer typing a product name that only appears in the answer still
  finds it
- A curated order, with partial reordering that will not reshuffle
  entries a filtered screen never loaded
- Optional locale (`ar` / `en`), where "no locale" means "applies whatever
  the customer speaks" and appears in every language's list
- Publication that is a real gate: **unpublishing removes the answer from
  the search index**, so the AI cannot quote something that has been
  taken down

**And how AI uses them.** `POST /ai/knowledge-search` now grounds on both,
and the ordering is the point:

> **APPROVED ANSWERS** (prefer these; reuse their wording where it fits)
> — then —
> **REFERENCE MATERIAL** (background; summarise only what is needed)

An FAQ is a complete answer somebody published for exactly this question;
an article passage is raw material. Handing the model both without saying
which is which invites it to paraphrase a curated answer into an
uncurated one — which is how a company that carefully worded its refund
policy finds the platform explaining refunds in its own words instead.

Full detail: [`architecture/faq.md`](architecture/faq.md).

### Quick replies

Company-wide canned responses with a unique shortcut. Simple by design —
these are text expansions, not knowledge.

### Internal notes

Private to the company, attached to a conversation, never sent anywhere.
A genuinely separate table from messages, because a note has none of a
message's delivery, read-status or reopen concerns.

---

## 12. The intelligence layer

Three domains with different owners, different guarantees and different
lifecycles. The separation is structural, not careful — and it exists to
prevent one specific failure:

> Without it, *"the AI learned our refund window is 14 days"* and *"our
> refund policy states 14 days"* are the same sentence in the same store.
> Six months later retrieval ranks the learned one higher because it was
> seen more recently, and the platform quotes a refund window nobody
> approved. Nothing fails, no test goes red, and the company finds out
> from a customer.

| | Knowledge | Memory | Learning |
|---|---|---|---|
| Answers | What is true? | What happened? | What tends to work? |
| Written by | Humans, through publication | The Memory Manager, from evidence | Nothing — it only observes |
| Erasable | No (retired, never deleted) | **Yes, and it must be** | Yes |

### Memory — what the platform observed

Three durable tiers (organisational, customer, experience) plus a
short-lived working memory per live conversation.

**Every fact must arrive with evidence.** A fact without it cannot be
explained, re-derived, or correctly weakened when an erasure removes what
supported it — so the platform refuses to store one. Evidence is a
**pointer, never a copy**: no transcripts are duplicated into a second
store.

**Confidence is computed, never claimed.** It rises with how much support
a fact has, **how broadly** that support spreads across different
customers and agents, how the conversations turned out, and how recently
it was seen — and falls with contradictions and age. Forty repetitions by
one agent to one customer is one person's habit observed forty times; six
agents converging independently is a practice, and the formula can tell
them apart.

**Repetition is not corroboration.** A fact supported only by what a
customer said cannot pass "candidate" however often it is repeated. That
is the defence against somebody talking the platform into a false belief
— defeated by a counter, not by detection.

**Facts age on two independent axes**: how much it is believed, and how
alive the row is. A trusted fact that goes quiet and comes back returns
with the standing it earned, rather than starting again.

**Forgetting is not erasure.** Forgetting is scheduled and reversible;
erasure is on demand, complete, and irreversible. Erasing a customer
removes every fact about them and every trace of their contribution,
recomputes the company-wide patterns their conversations supported, and
returns **counts** — because "we ran erasure" is not evidence, and this
is the response somebody forwards to a regulator.

Memory is on by default and switchable off **independently of AI** — a
hospital may want AI answering from approved articles while retaining
nothing about what patients said.

### Learning — what tends to work

**Phase 1 observes and does nothing else.** No clustering, no
suggestions, no model calls. That is not an unfinished feature; it is the
phase that makes the expensive phases *measurable before they are
switched on*.

One completed conversation becomes one traceable row: what it was about,
which language, any order numbers or amounts, how it ended, how long it
took, whether the customer rated it. **Nothing is copied** — each summary
points back at the messages it came from.

Two refusals are worth stating plainly:

- **It does not learn from its own replies.** A conversation AI handled
  end to end is recorded as *not learnable*. The share of observed content
  the platform itself wrote is reported as a number on an operator
  screen, because that figure quietly rising is the one way a system like
  this goes wrong invisibly.
- **It does not treat an automatic closure as success.** A conversation
  closed by a rule is closed — but only a *person* deciding it is
  finished counts as evidence that anything worked.

Nothing settles immediately: an observation waits until its outcome can
no longer change (a rating arriving, a reopen) and settles by itself after
three days if nothing does.

Switching learning off stops it **before a single message is read**, and
the refusal itself is recorded — so a company can show that the platform
saw a conversation and chose not to learn from it.

---

## 13. Reporting, billing and administration

### Reports

Executive dashboard · live dashboard · agent performance · conversations ·
queues · SLA · CSAT · AI usage (including per agent). PDF and Excel export
on all of them.

Reports read **pre-summed daily rollups** rather than scanning
conversations and messages. The live dashboard is the deliberate
exception — a daily rollup cannot represent "right now".

**CSAT** is a token-gated survey link sent when a conversation resolves,
reusing the existing token machinery rather than building a customer login
for one rating.

### Billing

A full commercial engine, not a bolt-on:

- **Metering** — one immutable event per customer-facing message
- **Pricing** — profiles, rates, volume tiers, effective dating, an audit
  log. Metering and pricing are separate systems; a metering row cannot
  know a price
- **Invoicing** — document numbers, a state machine, immutability, credit
  notes
- **Payments** — multiple providers including Jordanian schemes,
  reconciliation, refunds, reversals
- **Collections** — a dunning sequence and suspension
- **A double-entry ledger** where nothing is ever amended; corrections are
  new entries
- **A free monthly allowance**, applied at read time

Currency is a property of the currency — JOD carries three decimal
places — and nothing converts between currencies.

### Platform administration

A cross-tenant operator console: company lifecycle, feature entitlements,
per-company users, pricing, invoicing, payments, ledger, revenue,
installation settings, scheduler health.

**Read-only operators** are a real state, not a convention. (A bug once
let them change everything except pricing; that is closed and tested.)

### ERPNext integration

Per-company connection. Customers sync outward on creation, idempotently
and silently no-op for companies without a connection. Documents flow
inward through a doctype-agnostic webhook into one generic cache — because
invoices, orders, quotations, tickets, payments and contacts are
heterogeneous, read-only shapes only ever displayed.

### Audit

Every event on the bus becomes an audit row. "What gets audited" is
"everything", which is simpler and safer than a list somebody could forget
to extend — with one carve-out: message bodies and transfer notes are
**redacted**, because the audit log has longer retention and a different
permission than the conversations they came from.

### Observability

Prometheus + Grafana (five dashboards, six alert rules), Loki for logs,
exporters for Postgres, Redis, RabbitMQ and Celery. A dependency-aware
readiness probe. A scheduler monitor, so a background job that silently
stopped running is visible. Automated backups with a **verified restore
drill**.

---

## 14. What is not built

Named honestly rather than implied by omission.

### Intelligence layer

| | |
|---|---|
| **Answer verification** | Nothing yet refuses a generated reply whose restricted claim cites no approved source. "Official knowledge wins" is enforced on the memory side, advisory on the answer side |
| **Knowledge versioning** | An article is a moving target; a citation is not reproducible. FAQs share the gap and should gain versions in the same change |
| **Retrieval traces** | Gap detection cannot yet see "a search that returned nothing" |
| **Learning phases 2–4** | Clustering, trends and anomalies are in the tree unreleased; candidates, suggestions and human review are not built |
| **Memory distillation** | Working memory expires with the conversation; nothing turns it into durable facts |
| **Company Behavior** | Named practices and procedures — reserved deliberately, because it would compile into five existing configuration surfaces and must become their single writer in the same change |
| **Voice constraints** | Mandatory disclaimers enforced at generation are designed, not built |

### Product surface

- **No frontend for**: workflows, queues, routing rules, knowledge
  authoring, FAQs, quick replies, standalone notes, audit log viewer
- **FAQ**: no voting, no public help-centre endpoint, no linked
  translations
- **Outbound MMS**: an explicit boundary — the SMS gateway needs a
  publicly fetchable media URL that private object storage does not
  provide. Inbound MMS works fully
- **Attachment virus scanning**: a documented extension point, not a fake
  scanner
- **Channel connection**: no webhook auto-registration and no OAuth —
  credentials are pasted

### Deployment

TLS, a secrets manager, off-host backups, object-storage backup, a real
alert destination and a real deploy target are all open, tracked in
`deployment/go-live-checklist.md`. **A stable version number does not
close them.**

---

## 15. How a message becomes a reply

The whole platform in one path. A customer messages a company on WhatsApp
at 09:14.

**09:14:02 — Arrival.** Meta posts to the webhook. The signature is
verified (wrong signature → 401, nothing else runs). The provider
normalises the payload into a channel-agnostic message and publishes
"message received". **Nothing is persisted yet** — the webhook returns in
milliseconds, which is what stops Meta retrying.

**09:14:04 — Ingestion.** The event reaches the conversation engine.
The customer is resolved through the channel-identity table (created if
new). No open conversation exists on this thread, so one is created.
Attachments are validated. The message is stored. An "agent is typing"-
style live update goes out so any open inbox updates immediately.

**Routing.** Four resolution strategies run in order; "Support" matches on
a business rule. The service **version** is frozen onto the conversation
— it will run under those rules for its whole life, even if somebody
edits the service at 09:30.

**Policy.** *May this be routed?* Allowed — and the allowance is
recorded, not just refusals.

**Queue.** The service names a queue, so the service wins. The
conversation becomes `WAITING`, and **the queue owns it** — not "nobody".

**Clocks.** Three start at once, with targets copied onto them.

**AI.** *May AI answer this?* The policy checks, narrowest first: has the
customer opted out of automated messages? is the company's AI switch off?
is a provider configured? has the service disabled AI? does an agent
already own it? is it finished? All pass. But the service's pickup delay
is 30 seconds — so AI is *permitted and deliberately waits*. The
conversation sits visibly in the queue where a human can take it.

Meanwhile the assignment engine looks for an agent: candidates narrowed
by required skills, then least-load. Nobody is online. The decision is
recorded **with every rejected candidate and why**.

**09:14:34 — AI picks it up.** Nobody took it. Ownership transfers to AI.
The queue clock is answered *on acceptance*, not on reply.

**Grounding.** The customer asked *"can I get my money back"*.

- **FAQ search** runs first — hybrid, over questions and answers. It finds
  a published FAQ: *"How long do refunds take?"*
- **Article search** runs — the lexical half finds nothing (the article is
  titled "Refund policy" and shares no words with the question); the
  semantic half finds it anyway. The matching **passage** is returned, not
  the whole 4,000-word manual.

**Memory.** Working memory supplies what this thread has already
established, so the customer is not asked for an order number they gave
at turn three. Durable facts about this customer are read — but their
account balance is **not** remembered, it is queried from ERPNext, because
a remembered balance is wrong by the time it is retrieved.

**Learning.** Nothing happens yet. Learning observes *finished* work, and
it never blocks anything.

**Generation.** The model receives the conversation history, the FAQ
labelled as an **approved answer**, the article passage labelled as
**reference material**, and the memory context. It replies, with a
confidence score. Above the threshold, it sends. Below it, it hands the
conversation back to the queue and raises a notification — and the
inspector shows exactly why.

**09:14:36 — Reply delivered.** The message goes out through the same
provider factory every channel uses, is stored, is marked
**AI-generated**, settles the first-response clock, and is metered as one
billable event. Twenty-two seconds elapsed — thirty of which the platform
deliberately spent waiting for a human who did not come.

**Later — the aftermath.** An agent takes over, finishes the conversation
and resolves it. A CSAT link goes out. The resolution clock settles. The
rollups increment. And the learning layer assembles one observation: the
AI turn is stripped out **before** feature extraction, the outcome is
copied from the single shared definition of "resolved", and the row waits
— not final until the rating lands or three days pass.

Then it stops. No cluster, no candidate, no memory fact, no model call.
Just a traceable row, and a number on an operator's screen that says how
much of what the platform observed the platform itself wrote.

**That number is the gate on everything that comes next.**

---

## See also

- [Platform Handbook](architecture/platform-handbook.md) — the architecture, in depth
- [FAQ](architecture/faq.md) · [Memory Platform](architecture/memory-platform.md) · [Learning Platform](architecture/learning-platform.md)
- [Company Intelligence Engine](architecture/company-intelligence-engine.md) — semantic retrieval
- [Policy Engine](architecture/policy-engine.md) · [SLA Engine](architecture/sla-engine.md) · [Billing](architecture/billing.md)
- [API guide](api/README.md) · live OpenAPI at `/docs`
- [CHANGELOG](../CHANGELOG.md) — the release history in plain language
