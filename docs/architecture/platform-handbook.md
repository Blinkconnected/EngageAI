# Blink Engage — Platform Engineering Handbook

**The state of the system after Stage 1 (Knowledge / semantic retrieval),
Stage 2 (Memory Platform), and Stage 3 Phase 1 (Learning Platform —
Observe).**

This document is written for someone joining the team who needs to hold
the whole platform in their head. It is a walkthrough, not a reference
card. Where a design decision has a reason, the reason is here, because
the reason is the thing that stops the decision being undone by accident
six months from now.

Everything asserted here was traced against the code, not against intent.
Where the code and an older document disagree, the code wins and the
disagreement is named.

**Current release: `1.1.0` (stable), 2026-08-05.** Writing this document
found one previously-unrecorded defect — an event binding with no
publisher — which was fixed and guarded in that release; see
[the 1.1.0 release report](../releases/1.1.0.md).

**Verified counts, as of the 1.1.0 release**

| | |
|---|---|
| Database tables | **93** |
| Alembic migrations | **83**, single head `e5b2c83f19d7` |
| HTTP routes | **313** + 2 WebSocket routes |
| Domain event types published | **94** |
| RabbitMQ consumer processes | **12** |
| Celery beat schedules | **16** |
| Application service modules | **84** |
| Repositories | **58** |
| Backend tests | **3,237** collected |
| Frontend tests | **470** in 53 files |
| Docker Compose services | **31** (+ 8 named volumes) |

> **Scope note.** This document describes the platform through **Stage 3
> phase 1**, which is what `1.1.0` released. **FAQs** landed after it —
> a real question-and-answer entity closing the gap where the AI Engine
> answered "FAQ Search" by pointing at article search; see
> [faq.md](./faq.md). **Learning phase 2** —
> clustering, trend detection and anomaly detection — landed in the
> working tree after this was written and is recorded under
> `## [Unreleased]` in the changelog, not in 1.1.0. It adds four tables,
> one migration, five endpoints and its own consumers and sweeps, none of
> which are described here. Its design is in
> [learning-platform-phase-2.md](./learning-platform-phase-2.md). The
> counts above are deliberately those of the released platform, not of
> whatever the working tree currently holds — a handbook whose numbers
> track an uncommitted branch is a handbook nobody can trust against a
> deployed build.

---|---|
| Database tables | **93** |
| Alembic migrations | **83**, single head `e5b2c83f19d7` |
| HTTP routes | **313** + 2 WebSocket routes |
| Domain event types published | **94** |
| RabbitMQ consumer processes | **12** |
| Celery beat schedules | **16** |
| Application service modules | **84** |
| Repositories | **58** |
| Backend tests | **3,237** collected |
| Frontend test files | **53** |
| Docker Compose services | **31** (+ 8 named volumes) |

---

## Table of contents

**Part 0 — How to read this**

**Part I — The business**
1. The business vision
2. Why the platform exists

**Part II — The map**
3. Every bounded context
4. Every service (process topology)
5. Every database and store
6. Every queue
7. Every background worker
8. Every event
9. Every public API
10. Every ownership boundary
11. Every repository
12. Every domain model
13. Every lifecycle

**Part III — The engines, one at a time**
(each with: why it exists · what problem it solves · what it owns · what
it never owns · who depends on it · events emitted · events consumed ·
tables · APIs · tests)

**Part IV — Cross-cutting**
21. Every policy
22. Every architectural invariant
23. Every important design decision
24. Every scalability mechanism
25. Every security mechanism
26. Every tenant-isolation mechanism
27. Every replay / idempotency mechanism
28. Every observability component

**Part V — Honest state**
29. Every current limitation
30. Every planned future phase

**Part VI — Diagrams and lifecycles**
A. Complete architecture diagram
B. Complete event flow diagram
C. Complete request lifecycle
D. Complete conversation lifecycle
E. Complete Memory lifecycle
F. Complete Knowledge lifecycle
G. Complete Learning lifecycle
H. Dependency graph
I. Ownership matrix
J. End-to-end walkthrough: message → routing → policy → knowledge →
   memory → learning → AI → reply

---

# Part 0 — How to read this

Three ideas explain more of this codebase than anything else. If you
internalise only three things, internalise these.

### 1. Every business fact has exactly one owner

Not "should have". *Has* — and where two owners were found, it was
recorded as a defect with a name (`A1`, `A3`) and fixed. The audit lives
at [`domain-ownership.md`](./domain-ownership.md).

The reason is not tidiness. Two owners of one fact produces a specific,
recognisable failure: the UI writes one, the engine reads the other, and
nothing errors. `A3` is the canonical example — SLA targets had two
owners, and the consequence was **zero SLA clocks across the entire
installation**, a permanently empty Breached queue, and no error anywhere.
A customer would have to report it.

### 2. Nothing may fail silently

The platform's recurring bug shape is *"a thing that quietly stopped
happening"*. Four separate production defects had that shape before
`core/wiring.py` existed. So the codebase carries an unusual density of
structural guards:

- `core/wiring.py` — the container **refuses to boot** if a critical
  service is built without a collaborator whose absence would be silent.
- AST guards — `test_ownership_is_the_only_writer.py`,
  `test_memory_manager_is_the_only_writer.py`,
  `test_learning_writes_only_its_own_tables.py`. These parse the source
  tree and fail on writes nobody has written *yet*.
- `RecordingPolicyEngine` — a policy cannot be asked quietly. Evaluating
  records; there is no flag to forget.
- `routing_decisions` — every branch that could have gone another way
  writes down which way it went and why.

### 3. Decide, and write down why

`RoutingDecision` rows, `PolicyDecision` objects, `ConversationSlaClock`
transitions, `memory_evidence` pointers, `learning_observation_refs` —
the platform's answer to *"why did it do that?"* is always a stored row,
never a reconstruction. The Conversation Inspector (the "Black Box") reads
them in order and explains a conversation end to end.

---

# Part I — The business

## 1. The business vision

Blink Engage is an **enterprise AI-powered omnichannel customer
engagement platform**, built to the standard of Zendesk / Intercom /
Freshdesk, targeting SMBs, enterprises, government, healthcare and
financial institutions — with a home market in Jordan (the billing engine
prices in JOD with 3 decimal places, and the language stack treats
Arabic/English code-switching as normal traffic, not an edge case).

The product promise has three layers, and they are deliberately stacked in
this order:

1. **One inbox for every channel.** WhatsApp, Telegram, Facebook
   Messenger, Instagram, Email, SMS and Web Chat land in one conversation
   model, one queue system, one SLA, one report. A channel is a plugin;
   the platform's core knows nothing about any specific vendor.
2. **Operations you can explain.** Routing, assignment, SLA, ownership,
   policy and AI engagement each write down *why*. A supervisor asking
   "why is this conversation here, and why has nobody answered it?" gets a
   timeline, not a theory.
3. **A company intelligence layer that earns trust before it acts.**
   Knowledge (what is true), Memory (what happened), Learning (what tends
   to work) — built as three separate bounded contexts with different
   write paths, different guarantees and different erasure obligations,
   *before* anything is allowed to generate from them.

The commercial model is metered: **one billable event per
customer-facing message**, with volume tiers, a free monthly allowance,
per-company pricing profiles, invoicing, payments, dunning and a
double-entry financial ledger. Billing is not a bolt-on — it is a
first-class bounded context with an immutable ledger and its own audit
trail.

## 2. Why the platform exists

### The operational problem

A company with seven channels has seven inboxes, seven notions of "who is
handling this", and no shared clock. Nobody can answer "how long has this
customer been waiting?" because the question spans systems that do not
share a definition of waiting.

Blink Engage exists to make that one system: one conversation, one owner,
one set of clocks, one policy layer, one audit trail.

### The intelligence problem, and why it is harder than it looks

Every platform in this category is adding AI. The failure mode is
specific and it kills systems of this shape:

> Without separation, *"the AI learned that our refund window is 14 days"*
> and *"our refund policy states 14 days"* are the same sentence in the
> same store, distinguishable only by a column somebody remembered to
> check. Six months in, retrieval ranks the learned one higher because it
> was observed more recently, and the platform quotes a refund window
> nobody approved. Nothing fails, no test goes red, and the company finds
> out from a customer holding the platform to a promise it invented.

So the intelligence layer is built as three domains with a **structural**
separation — different tables, different authority, different retrievers,
different erasure obligations — rather than a careful one. That is the
whole reason Stages 1, 2 and 3 exist as separate stages, in that order,
and why Stage 3 Phase 1 deliberately *observes and does nothing else*.

### The compliance problem

The target segments (government, healthcare, financial institutions) turn
"we asked both stores and neither reported an error" into an unacceptable
answer to a regulator. That single constraint shaped:

- Memory's **one erasure boundary** (which is why Experience is a Memory
  *tier*, not a fourth peer domain — see §3).
- Erasure as a **fan-out with acknowledgement**: a participant that cannot
  confirm makes the erasure *incomplete*, not silently partial.
- `Policy.MEMORY_RECORDING` and `Policy.KNOWLEDGE_LEARNING` as separate
  switches from `AI_ENGAGEMENT` — a hospital may want AI answering from
  approved articles while retaining nothing about what patients said.
- The audit consumer's `_REDACTED_PAYLOAD_FIELDS`: message bodies are
  never copied verbatim into `audit_logs`, which has longer retention and
  a different permission than `conversations`.

---

# Part II — The map

## 3. Every bounded context

A bounded context here is defined operationally: **a write path and an
erasure boundary**. Who may create a row, and who must be able to prove
it is gone.

| # | Context | Owns | Built? |
|---|---|---|---|
| 1 | **Authentication** | Passwords, sessions, JWT access/refresh tokens | ✅ |
| 2 | **Authorization** | Roles, permissions, access decisions (`domain/rbac.py`) | ✅ |
| 3 | **Identity** | Profile, email lifecycle, verification | ⚠️ partial — reviewed, Phase 1 designed |
| 4 | **Company** | Tenant, departments, teams, membership, business config, business hours | ✅ |
| 5 | **Customers (CRM)** | Customer profiles, tags, custom fields, channel identities, internal ratings | ✅ |
| 6 | **Channels / Connectors** | Channel configs, provider plugins, connector manifests, health, connection logs | ✅ |
| 7 | **Conversations** | Conversation + message + attachment lifecycle, internal notes, transfers | ✅ |
| 8 | **Ownership** | Who is responsible for a conversation, as an append-only timeline | ✅ |
| 9 | **Routing / Service Directory** | Service resolution, versioned service context, queue selection, decision log | ✅ |
| 10 | **Queues & Assignment** | Logical + runtime queues, skills, assignment strategies | ✅ |
| 11 | **SLA** | Four clocks, targets, business hours, breach, health | ✅ |
| 12 | **Policy Engine** | Every business rule. `PolicyDecision` — allowed or not, and why | ✅ |
| 13 | **Workflow Engine** | Event-triggered condition/action automations | ✅ |
| 14 | **Notifications & Realtime** | Durable per-user inbox, preferences, devices, WebSocket gateways | ✅ |
| 15 | **AI Engine / Autopilot** | Classification, suggestions, autopilot reply-or-handoff, confidence | ✅ |
| 16 | **Knowledge** | What the company officially states; articles, categories, chunks, **FAQs**, semantic index | ✅ **Stage 1** (retrieval) + **FAQ entity**; versioning designed, not built |
| 17 | **Memory** | What the platform observed; facts, evidence, confidence, erasure | ✅ **Stage 2** |
| 18 | **Learning** | What tends to work — *observation only* | ✅ **Stage 3 Phase 1** |
| 19 | **Intelligence** | Reasoning over Knowledge + Memory. **Owns no data** | ⛔ designed, not built |
| 20 | **Company Behavior** | How the organization chooses to operate | 🔒 **reserved, deliberately unbuilt** |
| 21 | **Reporting & Analytics** | Rollups, dashboards, exports | ✅ |
| 22 | **Billing** | Usage, pricing, invoices, payments, collections, ledger | ✅ |
| 23 | **Platform Administration** | Cross-tenant operator surface, installation settings | ✅ |
| 24 | **ERP Integration** | ERPNext link + doctype-agnostic record cache | ✅ |
| 25 | **Audit** | Append-only record of everything on the bus | ✅ |
| 26 | **Search** | Cross-entity global search | ✅ |
| 27 | **Inspector** | The Conversation Black Box — reads every decision log | ✅ |

### The six product questions, and their three owners

The product vocabulary is six questions. That vocabulary is correct and
should be kept, because it is how a person explains this platform to
another person. But a *domain* is a write path and an erasure boundary,
and on that test there are three owners today:

| Question | Answered by | Status |
|---|---|---|
| What is true? | **Knowledge** | Stage 1 shipped (retrieval) |
| What happened? | **Memory** | Stage 2 built |
| What tends to work? | **Experience** | Built as a **Memory tier** |
| How do we sound? | **Company DNA** | Splits across Knowledge and Memory — designed |
| How do we choose to operate? | **Company Behavior** | Reserved, unbuilt |
| What should we do now? | **Intelligence** | Designed, unbuilt |

**Why Experience is a tier, not a fourth domain.** It is identical to
Memory on every axis — written by the Manager from evidence, confidence
computed, two-axis lifecycle, contradicted by Knowledge on sight. The
decisive argument is erasure: a customer erasure request must remove that
customer's contribution from Customer Memory, Organizational Memory *and*
Experience in one transaction. As a peer domain, that becomes a
distributed transaction across two owners, and the guarantee degrades from
"it is gone" to "we asked both and neither reported an error." **One
erasure boundary means one owner.**

**Why Company Behavior is reserved rather than sketched.** It genuinely
passes the fourth-context test (written by humans deliberately, nothing
personal to erase, an executable structure, a compliance question
groundedness cannot answer). It is unbuilt because its hard part is not a
schema — it is a *migration of five existing configuration surfaces*
(Policy, Workflow, Routing, SLA, Assignment), each already directly
configurable. Introduced as a parallel authoring layer it does not create
one `A3`; it creates five. The condition on ever building it is recorded
now: **Behavior must become the single writer of the configuration it
owns, and the direct authoring path must be withdrawn in the same
change.** The names *practice*, *procedure* and *step* are reserved.

---

## 4. Every service (process topology)

Everything runs as Docker Compose services. `docker-compose.yml` is the
dev definition; `docker-compose.prod.yml` is a lean-runtime overlay (no
bind mounts, compiled SPA, resource limits, `--workers 4`).

### Infrastructure

| Service | Role | Notes |
|---|---|---|
| `postgres` | Primary datastore | **`pgvector/pgvector:pg17`**, not stock `postgres:17-alpine` — same major version so the existing volume is read as-is. `shared_preload_libraries=pg_stat_statements`, `track=all`, `max=5000` |
| `redis` | Cache, rate limits, refresh-token allowlist, chat sessions, realtime pub/sub, **Conversation Memory** | Two roles that matter: the ephemeral event tier, and Stage 2's working-memory store |
| `rabbitmq` | Durable topic exchange `blinkengage.events` + Celery broker | |
| `minio` (+ `minio-init`) | S3-compatible attachment storage | Bucket auto-created |
| `nginx` | Unified origin reverse proxy, SPA host | Dynamic DNS re-resolution against `backend:8000` (coarse load distribution under `--scale backend=N`) |
| `greenmail` | Local SMTP/IMAP for development | Dev only |

### Application

| Service | Role |
|---|---|
| `backend` | FastAPI app — the entire HTTP + WebSocket surface |
| `frontend` | Vite dev server (dev) / baked into nginx (prod) |
| `celery-worker` | Executes all scheduled tasks |
| `celery-beat` | Schedules them |

### Event-bus consumers (12 independent processes)

Each is its own process, its own durable RabbitMQ queue, its own binding.
**Adding consumer #13 is a new module plus one compose service — zero
changes to the outbox, the relay, or any existing consumer.**

| Consumer | Binds | Does |
|---|---|---|
| `audit-log-consumer` | `#` (everything) | Writes one `audit_logs` row per event, with free-text redaction |
| `conversation-ingest-consumer` | `message.received` | Builds `Conversation`/`Message`; resolves service, policy, queue, SLA clocks, ownership, assignment |
| `workflow-engine-consumer` | `#` | Evaluates every company's workflows against every event |
| `notification-consumer` | Rule-declared keys | Creates `Notification` rows from a rule registry |
| `reporting-consumer` | 8 keys | Increments five daily rollup tables |
| `csat-dispatch-consumer` | `conversation.resolved` | Sends the CSAT survey link |
| `ai-autopilot-consumer` | `message.persisted` | The "new message" trigger for Autopilot |
| `autopilot-sla-consumer` | `conversation.sla_warning`, `.sla_breached` | The "SLA" trigger for Autopilot |
| `usage-metering-consumer` | `message.persisted`, `message.sent` | One immutable `billable_events` row per customer-facing message |
| `erp-sync-consumer` | `customer.created` | Idempotent ERPNext customer sync; no-ops for companies without ERP |
| `learning-observation-consumer` | `conversation.resolved`, `.closed` | **Stage 3** — assembles one observation per finished conversation |
| `learning-signals-consumer` | `csat.submitted`, `conversation.reopened`, `.transferred`, `.sla_breached` | **Stage 3** — attaches late outcome signals |

**Why two Learning consumers rather than one.** The work genuinely
differs: the first reads every message in a conversation once; the second
attaches a late rating to a row that already exists. Sharing a queue would
put a heavyweight assembly and a trivial update behind the same prefetch.

### Observability

`postgres-exporter`, `redis-exporter`, `celery-exporter`, `prometheus`,
`grafana`, `loki`, `promtail`.

**Health-check honesty.** `celery-beat` and all six original consumers
had `healthcheck: disable: true` set deliberately in the prod overlay —
they build from the same image as `backend`, whose baked-in `HEALTHCHECK`
curls a web server they do not run. Seven permanently-"unhealthy"
containers on every production deployment is the kind of thing that trains
operators to ignore health status. `celery-worker` gets a real
`celery inspect ping`; the consumers are covered by `restart: always`
plus `celery-exporter` metrics.

---

## 5. Every database and store

**One PostgreSQL database, 93 tables, 83 migrations, one head.** There is
no per-context database — the contexts are enforced by ownership rules and
AST guards, not by network boundaries, and the erasure guarantee is
*easier* to keep in one transaction than across four databases. That is a
deliberate trade and it is the same argument that made Experience a Memory
tier.

### Table inventory by owning context

| Context | Tables |
|---|---|
| Authentication / Authorization | `users`, `roles`, `permissions`, `role_permissions`, `user_roles`, `email_verification_tokens` |
| Company | `companies`, `departments`, `teams`, `team_memberships`, `agents`, `agent_skills`, `agent_skill_assignments`, `holidays` |
| Customers | `customers`, `customer_tags`, `tags`, `customer_channel_identities`, `customer_internal_ratings`, `customer_context_versions` |
| Channels | `channel_configs`, `channel_connection_logs` |
| Conversations | `conversations`, `messages`, `message_attachments`, `internal_notes`, `conversation_transfers` |
| Ownership | `conversation_ownership` (**append-only**) |
| Routing / Services | `services`, `service_versions` (**append-only**), `conversation_context_bindings` (**append-only**), `runtime_queues`, `routing_rules`, `routing_decisions` |
| Queues | `queues`, `queue_required_skills` |
| SLA | `sla_policies`, `conversation_sla_clocks` |
| Workflow | `workflow_definitions`, `workflow_runs` |
| Notifications | `notifications`, `notification_preferences`, `device_tokens` |
| **Knowledge (Stage 1)** | `knowledge_categories`, `knowledge_articles`, `knowledge_article_tags`, **`knowledge_chunks`**, **`embeddings`**, **`faqs`**, **`faq_tags`** |
| **Memory (Stage 2)** | **`memory_facts`**, **`memory_evidence`**, **`memory_confidence_samples`**, **`memory_contradictions`** |
| **Learning (Stage 3 P1)** | **`learning_observations`**, **`learning_observation_features`**, **`learning_observation_refs`**, **`learning_runs`** |
| Reporting | `conversation_daily_stats`, `agent_daily_stats`, `queue_daily_stats`, `ai_daily_stats`, `csat_daily_stats`, `agent_ai_daily_stats`, `csat_responses` |
| Billing | `billable_events`, `usage_records`, `usage_period_lines`, `billing_periods`, `billing_daily_summary`, `pricing_profiles`, `pricing_rates`, `pricing_rate_tiers`, `pricing_audit_log`, `company_pricing_profile_assignments`, `invoices`, `invoice_lines`, `credit_notes`, `credit_note_lines`, `document_number_sequences`, `payments`, `payment_intents`, `payment_allocations`, `payment_refunds`, `dunning_notices`, `ledger_entries`, `financial_audit_events` |
| ERP | `erp_configs`, `erp_customer_links`, `erp_synced_records` |
| Platform | `platform_settings`, `scheduler_runs` |
| Cross-cutting | `audit_logs` (**append-only**), `event_outbox` (**append-only**), `quick_replies` |

### The append-only tables, and why each one is

| Table | Guarantee | Enforcement |
|---|---|---|
| `audit_logs` | A row is written once and never changes | No `Timestamp`/`SoftDelete` mixins |
| `event_outbox` | Same | Same |
| `conversation_ownership` | The handover *is* the row, not evidence about it | `OwnershipService.transfer` is the only writer, AST-guarded |
| `service_versions` | A conversation must always be able to say what rules it ran under | **PostgreSQL trigger refusing UPDATE/DELETE** |
| `customer_context_versions` | Same | Same trigger |
| `conversation_context_bindings` | Same | Same trigger |
| `ledger_entries` | Financial immutability | Nothing is ever amended; corrections are new entries |
| `billable_events` | The meter cannot be rewritten | DB-level immutability |

### Tables with **no soft delete**, deliberately

`memory_facts`, `memory_evidence`, `memory_confidence_samples` — unlike
every other entity in this schema. These are subject to erasure requests,
and **a store promising both immutability and deletion is promising one of
them falsely.**

### Non-PostgreSQL stores

| Store | Holds | Retention |
|---|---|---|
| **Redis** | Refresh-token allowlist, rate-limit windows, chat session tokens, realtime pub/sub channels, **Conversation Memory (working memory)** | TTL |
| **MinIO / S3** | Message attachments, company logos | Durable, **not currently backed up** — a named gap |
| **Prometheus** | Metrics | Local volume |
| **Loki** | Logs, `level` as the only indexed label | Local volume |

**Why Conversation Memory lives in Redis and not Postgres.** It has no
confidence, no evidence, no lifecycle, no steward and no human state —
every field of the memory-fact contract is meaningless for state that dies
when the conversation closes. Modelling it as a fact would mean either
eight permanently-null columns or loosening the contract for the tiers
that need it, and the contract is the reason the platform is trustworthy.
**The TTL is the design, not a detail**: working memory that outlived its
conversation would be a growing store of customer content with no
retention story. A TTL means the default outcome is deletion and
remembering requires a deliberate act.

---

## 6. Every queue

The word "queue" means two different things here, and conflating them is
the first mistake a new engineer makes.

### 6a. Product queues — where conversations wait for people

| Concept | Table | Meaning |
|---|---|---|
| **Logical queue** | `queues` | What a company configures: name, assignment strategy, SLA policy, autopilot opt-in, required skills |
| **Runtime queue** | `runtime_queues` | The lanes *inside* a logical queue (e.g. VIP vs standard) |
| **Required skills** | `queue_required_skills` | Narrows candidates before a strategy runs |

Assignment strategies: **Round Robin** (fewest ever assigned —
approximates least-recently-assigned without a rotation cursor) and
**Least Load** (fewest currently open, *company-wide*, not per-queue —
the point of load balancing is total workload).

**The Queue First Principle.** A conversation entering a queue becomes
`WAITING` and is **owned by the queue** — not "unassigned". A conversation
nobody has picked up is still somebody's problem, findable and
escalatable. `QUEUE_BYPASS` is denied by default for exactly this reason:
bypassing means never queueing at all, and folding it into
`VIP_QUEUE_ENTRY` is how a platform quietly acquires conversations that
exist nowhere.

### 6b. Message queues — RabbitMQ

One durable **topic exchange**, `blinkengage.events`. Routing key = event
type. Twelve durable queues bound to it, one per consumer, each consumed
with **manual ack** — a message is acked only once its handler returns
successfully, so a crashed handler leaves it for redelivery.

| Queue name | Binding keys |
|---|---|
| `audit-log` | `#` |
| `workflow-engine` | `#` |
| `conversation-ingest` | `message.received` |
| `ai-autopilot` | `message.persisted` |
| `autopilot-sla` | `conversation.sla_warning`, `conversation.sla_breached` |
| `reporting` | `conversation.created`, `conversation.updated`, `conversation.assignment_changed`, `conversation.sla_breached`, `message.sent`, `ai.completed`, `conversation.autopilot_replied`, `csat.submitted` |
| `notifications` | Computed from `NotificationRuleRegistry.registered_event_types()` |
| `csat-dispatch` | `conversation.resolved` |
| `usage-metering` | `message.persisted`, `message.sent` |
| `erp-sync` | `customer.created` |
| `learning-observations` | `conversation.resolved`, `conversation.closed` |
| `learning-signals` | `csat.submitted`, `conversation.reopened`, `conversation.transferred`, `conversation.sla_breached` |

**The acyclicity invariant (I-4).** *No Learning consumer binds a
`memory.*`, `learning.*` or `intelligence.*` routing key*, and a test
parses their `ROUTING_KEYS` to assert it. A consumer bound to Memory's
events would close the loop: memory writes an event, Learning observes it,
Learning's output eventually strengthens that same memory, and confidence
rises with no new human evidence anywhere in the cycle.

### 6c. Celery queues

Celery is used only for *scheduled* work (RPC-style, one dispatch → one
execution). Fan-out is RabbitMQ's job, not Celery's. This split is
deliberate: Celery's task model cannot express topic-exchange fan-out
without abuse.

---

## 7. Every background worker

Sixteen Celery beat schedules. Each is idempotent, each self-heals on a
missed run, and each disposes its engine pool in a `finally` block (see
§28 for the incident that made that mandatory).

| Task | Cadence | What it does | Why that cadence |
|---|---|---|---|
| `blinkengage.events.relay_outbox` | **5s** | Drains `event_outbox` → RabbitMQ | Cheap when empty: one indexed, limited `SELECT` against a partial index |
| `blinkengage.ai.pickup_waiting_conversations` | **10s** | Hands AI conversations nobody picked up | The pickup delay defaults to 30s; a coarser sweep would turn that into up to 90s — a different promise than the administrator typed |
| `blinkengage.notifications.dispatch_pending_pushes` | **10s** | Push notifications | A push's entire value is being current |
| `blinkengage.notifications.dispatch_pending_emails` | **30s** | Notification emails | An email half a minute late is still an email |
| `blinkengage.queues.check_sla_breaches` | **60s** | SLA breach detection sweep | A single periodic sweep, **not** a per-conversation timer |
| `blinkengage.sla.breach_overdue_clocks` | **60s** | Marks clocks out of time | Running out is the one thing that is not an event: *nothing happens*, which is exactly the problem |
| `blinkengage.channels.poll_email_imap` | **60s** | Fetches `UNSEEN` IMAP mail, marks `\Seen` | IMAP's own flag **is** the idempotency tracker — no cursor table |
| `blinkengage.knowledge.reindex_pending` | **60s** | **Stage 1** — embeds `PENDING` articles | Calls a metered external API; an article isn't edited on a timescale where 30s of staleness is felt |
| `blinkengage.conversations.release_expired_ownership` | **300s** | Releases lapsed sticky ownership | A window measured in hours doesn't need a tighter sweep |
| `blinkengage.channels.check_channel_health` | **300s** | Calls each active channel's `health_check()` | Hits real third-party APIs for every channel of every company |
| `blinkengage.learning.settle_observations` | **900s** (from setting) | **Stage 3** — promotes `pending` → `ready` | Reads `learning_settle_interval_seconds` rather than a literal, because the sweep truncates its run window to the same number |
| `blinkengage.memory.age_memory` | **3600s** | **Stage 2** — recompute confidence, move lifecycle, purge and prune | Far more often than confidence meaningfully moves (half-lives are months) but keeps each run's backlog small |
| `blinkengage.billing.close_due_periods` | 3600s | Closes billing periods whose month ended | A monthly cron that misses its window leaves every company unclosed until somebody notices |
| `blinkengage.billing.generate_pending_invoices` | 3600s | Bills every closed period without an invoice | Closing and invoicing are separate acts; only the first used to be scheduled |
| `blinkengage.billing.refresh_daily_summaries` | 3600s | Rebuilds daily aggregates, finalises past days | |
| `blinkengage.billing.collections_sweep` | 3600s | Reconciles gateway payments, runs dunning | A delayed final notice means somebody is suspended with less warning than policy promises |
| `blinkengage.services.check_configuration_drift` | **86400s** | Reports queue SLA config a Service now overrides | What it finds is an administrator's edit silently having no effect — a mistake measured in days, and it has no write path at all |

**Design rule shared by all of them:** *the write path does the cheap
half in the same transaction as the change; a bounded sweep does the
expensive half.* That is the outbox/relay division of labour, and it is
reused verbatim for knowledge indexing (`PENDING` column + sweep) — which
buys retries and backpressure for free, and prevents one slow vendor from
backing up a queue carrying every other tenant's events.

---

## 8. Every event

**94 distinct durable event types**, all published through the
transactional outbox.

### The contract

```python
@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_type: str            # "<aggregate_type>.<verb>"
    company_id: UUID | None    # nullable — some events are platform-level
    aggregate_type: str
    aggregate_id: UUID | None
    actor_user_id: UUID | None
    payload: dict[str, Any]
    occurred_at: datetime
```

### Catalog

**Conversation lifecycle** — `conversation.created`, `.updated`,
`.queued`, `.picked`, `.released`, `.transferred`, `.deleted`,
`.assignment_changed`, `.autopilot_replied`, `.autopilot_stopped`,
`.autopilot_handoff_needed`, `.sla_warning`, `.sla_breached`,
`.resolved`, `.closed`

Before 1.1.0, `.resolved` and `.closed` were assembled as
`f"conversation.{status.value}"` and `conversation.reopened` was bound by
`learning-signals-consumer` and published by nothing. Both are fixed: the
terminal events are explicit literals in `_TERMINAL_EVENT`, and both
reopen paths publish `conversation.reopened`. **Every event type is now a
literal in the source**, and a static guard fails the build for any
binding without a publisher — see [1.1.0](../releases/1.1.0.md).

**Messages** — `message.received` (pre-persistence, from the webhook /
WS gateway), `message.persisted` (post-persistence, carries our resolved
ids), `message.sent` (outbound)

**Customers** — `customer.created`, `.updated`, `.deleted`,
`customer_internal_rating.created`/`.updated`/`.deleted`

**Directory** — `agent.created`/`.updated`/`.deleted`/`.status_changed`/
`.password_reset`, `department.*`, `team.*`, `team_membership.added`/
`.removed`, `role.*`, `queue.*`, `routing_rule.*`, `sla_policy.*`,
`holiday.*`

**Auth/company** — `company.registered`, `.updated`, `.ai_config_updated`,
`.logo_updated`, `.logo_removed`, `user.login`, `.logout`,
`.password_changed`, `.role_changed`

**Channels** — `channel_config.created`/`.updated`/`.deleted`/
`.test_connection_ephemeral`

**Knowledge** — `knowledge_article.created`/`.updated`/`.deleted`,
`knowledge_category.created`/`.updated`/`.deleted`

**AI** — `ai.completed` (every capability publishes one; **there is
deliberately no AI usage-tracking table** — reporting consumes the event)

**Workflow** — `workflow.created`/`.updated`/`.deleted`/`.executed`

**CSAT** — `csat.submitted`

**ERP** — `erp_config.*`, `erp.customer_synced`

**Billing / usage** — `usage.period_closed`, `usage.late_record_rejected`,
`billing.payment_recorded`, `billing.credit_note_issued`

**Platform** — `platform.company_status_changed`, `.company_features_changed`,
`.company_owner_transferred`, `.user_role_changed`, `.user_status_changed`,
`.user_verification_resent`

**Memory (Stage 2)** — `memory.fact_recorded`, `.fact_reinforced`,
`.fact_state_changed`, `.fact_lifecycle_changed`, `.fact_confirmed`,
`.fact_suppressed`, `.fact_corrected`, `.fact_contradicted`,
`.fact_archived`, `.subject_erased`

**Quick replies / notes** — `quick_reply.*`, `internal_note.*`

### Two rules on event payloads

1. **Memory payloads carry ids, counts and structure — never the
   statement.** The audit log has longer retention and a different
   permission than the conversations a memory derives from, so a statement
   in the payload would be a second, longer-lived copy of customer
   content. `memory.subject_erased` carries **only counts**: an erasure
   event naming what was erased would defeat the erasure.
2. **`_REDACTED_PAYLOAD_FIELDS`** in the audit consumer replaces
   `message.received`/`.persisted`/`.sent`'s `body` and
   `conversation.transferred`'s `note` with `"[redacted]"` before the
   `audit_logs` row is written. Structural fields are untouched.

### The ephemeral tier

Typing indicators, presence and live message ticks do **not** use the
outbox. They go through `RealtimePublisher` (Redis pub/sub) on channels
like `company:{company_id}:conversation:{conversation_id}:typing`.
Durability is exactly the property these signals don't need, and paying
for it would add latency to something inherently latency-sensitive.

---

## 9. Every public API

**313 HTTP routes + 2 WebSocket routes**, all under `/api/v1` (only
`/metrics` is registered outside it). Interactive docs at `/docs` and
`/redoc` — **disabled in production** via `settings.is_production`.

### Route families

| Prefix | Permission gate | Feature gate |
|---|---|---|
| `/auth` | public / bearer | — |
| `/company` | authenticated (read) / `company.manage` (write) | — |
| `/departments`, `/teams`, `/agents` | `departments.*`, `teams.*`, `agents.*` | — |
| `/customers` | `customers.read` / `.manage` | — |
| `/channel-configs`, `/channel-connect` | `channels.read` / `.manage` | — |
| `/webhooks/{channel_config_id}` | **signature-verified, no auth** | — |
| `/web-chat` | opaque Redis session token | — |
| `/conversations` | `conversations.read` / `.manage` / `.pick` / `.release` / `.transfer` / `.delete` | — |
| `/queues`, `/routing-rules`, `/services` | `queues.read` / `.manage` | — |
| `/sla-policies`, `/holidays` | `sla_policies.*` | `require_feature("sla")` |
| `/workflows` | `workflows.*` | `require_feature("workflows")` |
| `/knowledge`, `/faqs` | `knowledge_base.*` | `require_feature("knowledge_base")` |
| **`/memory`** | `memory.read` / `.manage` / `.erase` | **no feature gate** |
| **`/intelligence`** | `intelligence.read` / `.manage` | **no feature gate** |
| `/ai` | `ai.use` + per-user rate limit | `require_feature("ai")` |
| `/reports` | `reports.read` | `require_export_feature` |
| `/notifications` | authentication alone | — |
| `/audit-logs` | `audit_logs.read` | — |
| `/erp-configs` | `erp.manage` | `require_feature("erp")` |
| `/billing` | `billing.read` | **no feature gate** |
| `/platform/*` | `PlatformContext` (re-read from DB every request) | — |
| `/csat/{id}/respond` | **public, JWT-token-gated** | — |
| `/search` | per-entity permissions | — |
| `/health`, `/health/ready`, `/version`, `/releases` | public | — |

**Why Memory and Learning have no feature gate.** Memory is platform
infrastructure that the Customer Timeline, CRM and Reporting read as
ordinary product surface — gating it would 402 an agent looking at a
customer's history. Learning's read surface is an operator view, not a
purchasable add-on.

**Why feature gates are applied at router registration**, not per
endpoint: one place to read, and a new endpoint added to a gated router
inherits the gate instead of quietly shipping ungated.

### Stage-specific APIs

**Knowledge (Stage 1)**
- `GET /knowledge/search` — hybrid retrieval, returns per-hit `sources`
  and a `degraded` flag
- `GET /faqs/search` — the same hybrid retrieval over the **FAQ** entity,
  which embeds as one vector rather than a chunk set. See
  [faq.md](./faq.md)
- `GET /knowledge/index-status` — chunks total/embedded, articles
  pending/failed
- `POST /ai/knowledge-search` — grounds an AI answer on retrieved
  **chunks**, not whole article bodies

**Memory (Stage 2)** — 12 routes
- `GET /memory/facts`, `GET /memory/facts/{id}` (`memory.read`)
- `POST /memory/facts` (`memory.manage`)
- `POST /memory/facts/{id}/confirm` | `/suppress` | `/correct` (`memory.manage`)
- `GET /memory/subjects/{subject_type}/{subject_id}/facts` (`memory.read`)
- `DELETE /memory/subjects/{subject_type}/{subject_id}` (**`memory.erase`, Owner only**)
- `GET /memory/status` (`memory.read`) — includes recompute backlog
- `GET|PUT|DELETE /memory/conversations/{id}` — working memory, gated on
  `conversations.read`/`conversations.manage`

**Learning (Stage 3 P1)** — 4 routes, **read-only**
- `GET /intelligence/observations/{conversation_id}` — the traceability
  call: what Learning extracted, and from what, with content refs
- `GET /intelligence/observations` — paged, filterable by `state`
- `GET /intelligence/runs` — execution history
- `GET /intelligence/health` — five operator counters + the **feedback
  ratio**

There is no endpoint to approve, promote or dismiss a candidate **because
there are no candidates.** Phase 1 proposes nothing.

---

## 10. Every ownership boundary

The rule is one owner per business fact. Here is the full matrix, traced
against code.

| Business fact | Owner | Consumers | Exposed as | Clean? |
|---|---|---|---|---|
| Password, sessions, tokens | Authentication | — | `AuthService` | ✅ |
| Password *policy* | Company (config) → Authentication (enforcement) | Authentication | `company_settings.min_password_length` | ✅ config and rule correctly separate |
| Roles, permissions, access decisions | Authorization | API gate | `domain/rbac.py` — a pure leaf that imports nothing | ✅ |
| Company, teams, departments, business config | Company | Everything | Repositories + `Company.settings` | ✅ |
| Business hours | Company | SLA (pause), AI | `domain/business_hours.py` | ✅ |
| Profile, email lifecycle, verification | Identity | API gate, Company admin | — | ⚠️ not built; today split across auth and verification |
| Company verification | Company | API gate | `Company.verified_at` | ⚠️ **D3** — currently written by Identity's service |
| Service resolution, queue selection, assignment | Routing | Conversation, Inbox, Inspector | `routing_decisions` + `queue_id` | ✅ |
| Which service a conversation runs in | Routing → binding | SLA, AI, Inbox | `ConversationContextBinding`, **frozen by value** | ✅ |
| Conversation lifecycle status | Conversation | Inbox, SLA, reporting | `Conversation.status` | ✅ |
| **Who is responsible for a conversation** | **Ownership** | Inbox, Inspector, metrics | `conversation_ownership`, append-only | ✅ **A1 resolved** — `assigned_agent_id` is now a projection |
| Operational state | Conversation (derived) | Inbox | `operational_state()` | ⚠️ **D2** — expressed twice (Python + SQL), accepted with a drift test |
| Time, deadlines, breaches | SLA | Inbox, Inspector, reporting | Clocks + decisions | ✅ |
| SLA health | SLA | Inbox ordering, Inspector | `Clock.health` | ⚠️ **D1** — expressed twice, accepted with a drift test |
| SLA targets | Service version, then queue policy, then company, then platform | SLA | `ConfigurationResolver` | ✅ **A3 resolved** — one resolver |
| Usage, pricing, invoices, payments, ledger | Billing | Dashboard, invoices, platform | `_effective_rates` | ✅ |
| Classification, suggestions, autopilot, confidence | AI | Conversation, Inbox | `AutopilotService` | ✅ |
| Whether AI may engage | **Policy Engine** | Ingest, pickup sweep | `Policy.AI_ENGAGEMENT` | ✅ single evaluator |
| Customer identity | Company | Conversation, Inbox, ERP | `customers` | ✅ |
| **What the company officially states** | Knowledge | AI, agents, customers | Articles + chunks | ⚠️ **versioning designed, not built** |
| **What the platform has observed** | **Memory** | AI, Workflow, CRM, Reporting, Timeline, Analytics | `memory_facts` + evidence | ✅ `MemoryManager` is the only writer, AST-guarded |
| **What Learning saw** | **Learning** | Operators (read-only) | 4 `learning_*` tables | ✅ AST-guarded |
| What the answer should be | Intelligence | Conversation, agents | A response with citations | ⛔ not built |
| What becomes official | **Humans** | — | Suggestion review, append-only | ⛔ not built |
| How the organization operates | **Company Behavior** | Policy, Workflow, Routing, SLA | — | 🔒 reserved |

### The vocabulary that keeps the boundaries from eroding

| Verb | Owner | Produces |
|---|---|---|
| **Reasons / proposes** | Intelligence | An answer, a recommendation, a suggestion |
| **Decides** | Policy Engine | A `PolicyDecision` — allowed or not, and why |
| **Approves** | Humans | A published knowledge version |
| **Remembers** | Memory Manager | A confidence-scored fact with evidence |

Intelligence may propose an action it is not permitted to take, and that
is a normal, healthy state — the proposal is recorded, the refusal is
recorded, and a supervisor can see both. **An Intelligence layer that
could only propose what it was allowed to do would be one that had
absorbed the policy rules.**

### The chain of authority

> **Systems of Record supply facts, Memory supplies observations,
> Intelligence proposes, Policy decides, Humans approve.**
> No module holds two of those.

### The fourth input: Systems of Record

A system of record is **queried, never remembered.** ERP stock levels,
invoice balances, order status, calendar availability.

| Claim | Knowledge | Memory | System of Record |
|---|---|---|---|
| "Our refund window is 14 days" | ✅ | — | — |
| "This customer's card declined twice" | — | ✅ | — |
| "This customer owes 42.50 JOD" | — | ❌ **never** | ✅ |
| "Card declines spike at month-end" | — | ✅ | — |

A remembered stock level is wrong by the time it is retrieved, and a
confidently-cited wrong balance is worse than no answer.

---

## 11. Every repository

58 repository modules, all in `infrastructure/repositories/`, all following one
pattern: **construct with an `AsyncSession`, take `company_id` as a
required keyword argument on every read**.

| Group | Repositories |
|---|---|
| Identity/access | `user`, `role`, `platform` |
| Company | `company`, `department`, `team`, `agent`, `agent_skill`, `holiday` |
| Customers | `customer`, `customer_channel_identity`, `customer_internal_rating`, `tag` |
| Channels | `channel_config`, `channel_connection_log` |
| Conversations | `conversation`, `message`, `message_attachment`, `internal_note`, `conversation_transfer` |
| Ownership | `ownership` |
| Routing | `routing_rule`, `routing_decision`, `service_directory` (services + versions + bindings + customer contexts) |
| Queues | `queue` |
| SLA | `sla_policy`, `sla_health_rank` |
| Workflow | `workflow`, `workflow_run` |
| Notifications | `notification`, `notification_preference`, `device_token` |
| **Knowledge** | `knowledge`, **`knowledge_index`** (chunks + embeddings + index state), **`lexical_search`** |
| **Memory** | **`memory`** (facts + evidence + samples + contradictions) |
| **Learning** | **`learning`** |
| Reporting | `reporting`, `daily_stats`, `csat` |
| Billing | `billable_event`, `usage`, `pricing`, `invoicing`, `payments`, `collections`, `ledger`, `financial_audit`, `billing_summary` |
| ERP | `erp_config`, `erp_customer_link`, `erp_synced_record` |
| Cross-cutting | `audit_log`, `event_outbox`, `search`, `quick_reply`, `scheduler_run`, `platform_settings` |

**Why repositories and not an ORM free-for-all.** Two reasons that have
each already paid for themselves: the `company_id` keyword makes a
cross-tenant query hard to *write*, not merely wrong to write; and the
AST guards (`test_memory_manager_is_the_only_writer.py`,
`test_ownership_is_the_only_writer.py`) can enumerate write methods on a
repository, which they could not do against inline `session.add()` calls.

---

## 12. Every domain model

`domain/` in this codebase means **the framework-free layer** — no
SQLAlchemy, no FastAPI, no clock, no repository — not "a business domain".
That distinction is load-bearing: a rule that could look something up
would be a rule whose answer depended on *when* you asked it.

### The pure rule modules (no I/O, exhaustively testable)

| Module | Holds |
|---|---|
| `rbac.py` | Permission catalog, system roles, default role permissions. **Imports nothing** |
| `policies.py` | `Policy`, `PolicyEffect`, `PolicySource`, `PolicyReason`, `PolicyDecision`, `PolicyEngine` |
| `execution_context.py` | `ExecutionContext`, `ConversationFacts`, `CompanyCapabilities` |
| `service_context.py` | `ServiceContext`, `SlaTargets`, `ContextBindingReason` |
| `customer_context.py` | `CustomerContext`, the routing-relevance fingerprint |
| `ownership.py` | `OwnerKind`, `Responsibility`, `OwnershipReason`, `ReleasePolicy`, `Owner`, `OwnershipChange`, `assigned_agent` |
| `lifecycle.py` | `ConversationStatus` + the `ACTIVE`/`AWAITING_OTHERS`/`FINISHED` sets |
| `sla.py` | `Clock`, `SlaTimer`, `SlaState`, `SlaHealth`, `PauseReason`, `overall()` |
| `business_hours.py` | Business-hour arithmetic |
| `conversation_outcome.py` | **The single definition** of resolved / reopened / escalated / first-contact / handling time / `resolved_by` / `settled` |
| `routing_decisions.py` | `RoutingDecision`, `QueueRouting`, `AgentAssignment`, `MatchedRule`, `RejectedCandidate` |
| `service_resolution.py` | The resolution pipeline contract and `StageResult` |
| `workflow_condition.py` | The `{"all"/"any": [...]}` condition DSL |
| `chunking.py` | **Stage 1** — chunking rules, `embeddable_text` |
| `retrieval.py` | **Stage 1** — Reciprocal Rank Fusion |
| `vector_index.py` | **Stage 1** — the `VectorIndex` port and `VectorMatch` |
| `embedding_provider.py` | **Stage 1** — the `EmbeddingProvider` ABC |
| `memory.py` | **Stage 2** — the fact contract, tiers, subjects, fact-type vocabularies, `validate_fact_shape` |
| `memory_confidence.py` | **Stage 2** — the confidence formula, half-lives, hysteresis thresholds, direction |
| `memory_lifecycle.py` | **Stage 2** — the liveness axis, retention, `display_label` |
| `memory_identity.py` | **Stage 2** — dedupe keys (NFKC, case folding, Arabic orthographic folding) |
| `memory_ports.py` | **Stage 2** — `ErasureParticipant`, `SupportsFactRecompute`, `SupportsOwnerDeletion` |
| `conversation_memory.py` | **Stage 2** — working memory value objects |
| `learning_observation.py` | **Stage 3** — the observation envelope, `Provenance`, `decide_state`, `PIPELINE_VERSION` |
| `learning_features.py` | **Stage 3** — deterministic tier 0/1 extraction |
| `money.py`, `pricing*.py`, `ledger.py`, `invoicing.py`, `tiers.py` | Billing's pure arithmetic |
| `severity.py`, `projection.py`, `operational_state.py`, `inbox_views.py` | Inbox and Inspector rules |

### The five stored context tables

Migration `8c3d9a4e7b21`:

| Table | Holds | Mutable? |
|---|---|---|
| `services` | Identity — code, name, active, `current_version_id` pointer | Yes |
| `service_versions` | One frozen configuration | **Append-only (trigger)** |
| `customer_context_versions` | One frozen set of routing-relevant attributes | **Append-only (trigger)** |
| `runtime_queues` | The lanes inside a logical queue | Yes |
| `conversation_context_bindings` | Which versions a conversation runs inside, and why | **Append-only (trigger)** |

`services.current_version_id` is a **pointer**, not an `is_current` flag on
the version, because "the current one" is a single fact and two rows both
claiming it is a state no query can resolve.

---

## 13. Every lifecycle

### Conversation status (`domain/lifecycle.py`)

```
NEW → WAITING → IN_PROGRESS ⇄ WAITING_CUSTOMER / WAITING_AGENT
                     ↓
                 RESOLVED → CUSTOMER_FEEDBACK → CLOSED
                     ↑                              │
                     └──────── reopen ──────────────┘
```

Status, queue and owner are **three independent facts**. That split was a
deliberate change: a conversation being `WAITING` and being *in a queue*
are the same fact stated twice, but *who owns it* is a separate question
with its own timeline.

### Ownership

`OwnerKind`: `NOBODY` · `HUMAN_AGENT` · `AI_QUEUE_WORKER` · `TEAM` ·
`QUEUE` · `SUPERVISOR`.

Transitions are append-only rows in `conversation_ownership` with a
structured `OwnershipReason` — `NEW_CONVERSATION`, `PICKED_BY_AGENT`,
`ASSIGNED_BY_STRATEGY`, `AI_ENGAGEMENT`, `MANUAL_TRANSFER`, `ESCALATION`,
`SUPERVISOR_OVERRIDE`, `STICKY_CONTINUATION`, `CUSTOMER_REPLIED`,
`RELEASED_BY_OWNER`, `AI_RELEASED`, `OWNERSHIP_EXPIRED`,
`CONVERSATION_RESOLVED`, `CONVERSATION_CLOSED`, `OWNER_UNAVAILABLE` —
never free text.

`ReleasePolicy`: `STICKY` (a hold with a window) · `IMMEDIATE` ·
`ON_RESOLVE` · `ON_CLOSE`.

### SLA clocks

Four clocks, started and settled independently: `QUEUE`,
`FIRST_RESPONSE`, `NEXT_RESPONSE`, `RESOLUTION`. Targets are **copied onto
the clock at start** from the resolved configuration, never read through a
join on every sweep — so an administrator halving a target at noon does
not move the deadline of everything already running.

### Knowledge article

Today: `draft ⇄ published` + soft delete. **Versioning is designed and not
built** — `knowledge_article_versions` does not exist, and
`knowledge_chunks.article_id` points at the mutable article. Recorded as
finding **B9**.

### Memory fact — **two axes, not one chain**

```
confidence_state   OBSERVED → CANDIDATE → CONFIRMED → TRUSTED
                       ▲          ▲           ▲          │
                       └──────────┴───────────┴──────────┘
                              demotion, with hysteresis

lifecycle_state    ACTIVE → DORMANT → ARCHIVED → PURGED
                      ▲        │
                      └────────┘
                      re-observation revives

orthogonal         contradiction_count · human_state
```

### Learning observation

```
                   ┌─→ excluded (policy_denied | no_human_content | too_short)
assembled ─────────┤
                   └─→ pending ──(settle)──→ ready
```

---

*(continued in Part III)*

---

# Part III — The engines, one at a time

Each engine below follows the same ten-point template: **why it exists ·
what problem it solves · what it owns · what it never owns · who depends
on it · events emitted · events consumed · tables · APIs · tests.**

---

## 14. Event Bus (foundational)

**Why it exists.** Every module after Phase 2 needs to react to what other
modules do — AI, workflows, notifications, ERP, reporting, audit,
learning. Direct calls would mean each publisher knows each consumer, and
adding a consumer would mean touching a publisher. The requirement was
explicit: *adding a consumer must require zero changes to whatever
publishes the event, or to any other consumer.*

**What problem it solves.** The dual-write gap. "Commit to Postgres, then
publish to RabbitMQ" loses the event if the process dies between the two;
"publish, then commit" fabricates an event for a change that never
happened.

**What it owns.** `event_outbox`, the relay, the shared consumer runtime
(`run_consumer`), the `blinkengage.events` topic exchange, and the
ephemeral Redis pub/sub tier.

**What it never owns.** Any business meaning. The relay does not know what
a `message.received` is; the consumer runtime does not know what any
consumer does with an event.

**Who depends on it.** All 12 consumers, and every mutating service in the
platform.

**Mechanics.**

1. `OutboxEventPublisher.publish()` adds one `EventOutbox` row **on the
   same `AsyncSession` the business change is using**. No broker round
   trip on the request path. The event and the change commit or roll back
   together, atomically, by construction.
2. `relay_outbox` (Celery beat, 5s) claims a batch with
   `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL — so overlapping
   relay invocations claim disjoint batches — and publishes each as a
   persistent message to the topic exchange with `routing_key = event_type`.
   SQLite (tests only) branches to a non-locking claim.
3. Publish failures leave `dispatched_at` null and increment `attempts`.
   At-least-once delivery.
4. A **dead-letter guard**: `claim_batch` takes a required `max_attempts`
   (`events_relay_max_attempts`, default 10) and excludes rows at or past
   it from future claims. Not a silent drop — the rows stay in the table
   for an operator to find.

**Tables.** `event_outbox` (append-only, partial index on
`WHERE dispatched_at IS NULL`).

**APIs.** None. It is infrastructure.

**Tests.** `tests/integration/test_event_bus.py`,
`tests/unit/test_guid_type.py` (5 tests).

### The incident that shaped it

Worth reading in full because it is the platform's canonical example of a
silent failure. `GUID.process_result_value` used `isinstance(value,
uuid.UUID)` — which is `True` for asyncpg's own UUID *subclass*, so the
raw asyncpg object passed through unconverted. It behaved identically
everywhere except `orjson.dumps()`, which only accepts the exact type. The
relay is the only code that calls `orjson.dumps()` on a loaded UUID
directly. So **every outbox row with a non-null UUID field had been
silently failing to publish since the `GUID` type was introduced.**

Compounding it: `claim_batch` had no `attempts` cap, so the *same* oldest
~100 permanently-failing rows were reclaimed every 5 seconds forever,
starving every healthy event behind them. One row reached **14,586
attempts** (~20 hours). The entire event-bus-dependent surface — audit,
reporting, conversation ingestion, notifications, workflows, ERP sync —
was down, and nothing reported it.

No test caught it because every consumer test called handlers directly
against fabricated event dicts, never the relay's real serialization path
against real asyncpg-typed columns.

**The lesson encoded in the codebase:** a test that exercises a handler is
not a test that exercises the pipeline.

---

## 15. Channels & Connectors

**Why it exists.** Seven channels with nothing in common at the protocol
level (Meta Graph, Telegram Bot API, SMTP/IMAP, Twilio's form-encoded
HMAC-SHA1-over-the-full-URL scheme, a WebSocket). Hardcoding any of them
into the conversation engine would make the eighth channel a refactor.

**What problem it solves.** One conversation model over N transports.

**What it owns.** `ChannelConfig` (per-company, application-layer-encrypted
credentials), the `ChannelProvider` ABC and its registry, connector
manifests, channel health state, `channel_connection_logs`, and the
generic webhook ingress.

**What it never owns.** Conversations, messages or customers. A provider
normalises an inbound payload into a channel-agnostic DTO and publishes
`message.received`. **It never persists anything.**

**The plugin contract.** An 11-method `ChannelProvider` ABC:
`send_message` · `receive_message` · `edit_message` · `delete_message` ·
`mark_as_read` · `typing_indicator` · `upload_attachment` ·
`download_attachment` · `webhook` · `verify_signature` · `health_check`.

Unsupported capabilities are **honest no-ops with documented reasons**,
not fake implementations. SMS has no edit, delete, read receipt or typing
at the carrier level; email has no provider-side equivalent for any of the
four; Messenger/Instagram have no edit or delete.

**Two inner plugin layers.** `SmsProvider` (registered as `"sms"` in
`ChannelRegistry`) delegates to whichever `SmsGateway` its config names
(`SmsGatewayRegistry`) — because Twilio, Vonage, MessageBird and Plivo
share no protocol at all. Registry-keyed-by-a-database-string is this
codebase's most-reused idiom: `ChannelRegistry`, `SmsGatewayRegistry`,
`AiProviderRegistry`, `EmbeddingProviderRegistry`,
`WorkflowActionRegistry`, `NotificationRuleRegistry`.

**Identity resolution.** `customer_channel_identities` is the single
channel-agnostic mapping table. Email resolves on `Customer.email`
directly (an unambiguous field); every other channel resolves through this
one table with zero per-channel resolution code.

**Health and diagnostics.** `check_channel_health` (beat, 300s) calls each
active channel's `health_check()`, records transitions only (not every
tick), and writes a `channel_connection_logs` timeline.

**Credential redaction — a real vulnerability that was caught in review.**
A provider's own `health_check()` error text embeds the credential:
Telegram's bot token and Meta's access token sit in the request URL, which
an `httpx.HTTPStatusError` echoes back verbatim. That text was being
persisted into three newly-broadly-readable surfaces
(`ChannelConnectionLog.message`, `ChannelConfig.last_health_detail`, and a
`Message.message_metadata`) that any `channels.read` or
`conversations.read` principal could see. Closed with a single shared
boundary: `redact_credentials()` / `safe_health_check()` in
`infrastructure/channels/error_sanitizer.py`, applied everywhere provider
error text becomes a stored or returned string.

**Secret-return discipline.** An auto-generated `webhook_secret` (and, for
WhatsApp, `verify_token`) is returned **only** from
`POST /channel-configs`, via a distinct `ChannelConfigCreateResponse`
schema — the one moment a server-generated secret is allowed to leave the
server at all. It is never echoed on `GET`. (Before this, following the
wizard's own "leave blank to auto-generate" guidance meant a
Telegram/Email channel literally could not receive webhooks.)

**Events emitted.** `channel_config.created`/`.updated`/`.deleted`/
`.test_connection_ephemeral`, and `message.received` from the ingress.

**Events consumed.** None.

**Tables.** `channel_configs`, `channel_connection_logs`,
`customer_channel_identities`.

**APIs.** `/channel-configs` (8), `/channel-connect` (8 — catalog +
wizard sessions), `GET|POST /webhooks/{channel_config_id}`,
`WS /web-chat/ws/{channel_config_id}`.

**Tests.** `test_channels.py`, `test_whatsapp_telegram_webhooks.py`,
`test_messenger_instagram_webhooks.py`, `test_sms_webhook.py`,
`test_web_chat.py`, `test_channel_health_check_task.py`,
`test_channel_provider_secret.py`, `test_channel_connection_log_repository.py`,
plus unit suites per provider and `test_channel_error_sanitizer.py`.

**A structural bug worth remembering.** The health sweep and IMAP poll run
in `celery-worker`/`celery-beat`, which never imported
`infrastructure.channels.providers` — the module whose import-time
`@ChannelRegistry.register(...)` decorators make any channel type
resolvable. Every channel type raised "Unknown channel type" in those
processes, silently, from the day the sweep was written. Fixed
**structurally**, not with another ad-hoc import:
`infrastructure/channels/factory.py` — the one class whose job is "look up
a registered provider" — now imports the providers package at module
level, so registration no longer depends on which entrypoint remembers to
trigger it.

---

## 16. Conversations

**Why it exists.** It is the product.

**What it owns.** `Conversation`, `Message`, `MessageAttachment`,
`InternalNote`, `ConversationTransfer`; the status state machine; outbound
send; attachment upload/download.

**What it never owns.** Who is responsible (Ownership), which queue
(Routing), the deadlines (SLA), whether AI may reply (Policy).

**Key decisions.**

- **Internal notes are a separate table, not a third `MessageDirection`.**
  A note was never sent through a channel provider and has none of a
  message's delivery-status, read-status or reopen-logic concerns.
- **Delivery and read receipts are separate columns** (`status`,
  `delivery_status`, `read_status`), not one enum, because they move
  independently.
- **Attachment virus scanning is a documented, unimplemented extension
  point** rather than a fake scanner.
- **`assigned_agent_id` is a maintained projection**, written only by
  `OwnershipService.transfer`. Documented as transitional architecture.
- **Reopen goes back to the queue, never straight to the previous owner.**
  Whether the previous owner gets it again is the ownership rules'
  decision; deciding it here would re-couple status to owner.

**Events emitted.** `conversation.created`, `.updated` (carries
`previous_status`, so reporting can detect a genuine transition rather
than recounting an already-closed conversation), `.queued`, `.picked`,
`.released`, `.transferred`, `.deleted`, `.resolved`, `.closed`,
`.reopened`, `.assignment_changed`, `message.persisted`, `message.sent`,
`internal_note.*`.

**Events consumed.** `message.received` (via the ingest consumer).

**APIs.** `/conversations` — 21 routes plus messages, attachments, notes,
transfers, CSAT link, pick/release/autopilot.

**Tests.** `test_conversations_api.py`, `test_conversation_messaging.py`,
`test_conversation_ingest_consumer.py`, `test_internal_notes_api.py`,
`test_inbox_media.py`, `test_range_requests.py`.

---

## 17. Ownership

**Why it exists.** Because the platform had **two answers** to "who has
this conversation" — `Conversation.assigned_agent_id` (a mutable column)
and `conversation_ownership` (an append-only timeline) — written by
overlapping-but-not-identical sets of callers, with nothing comparing
them. Recorded as finding **A1**.

**The concrete defect.** The `assign_to_agent` workflow action called
`ConversationService.update(assigned_agent_id=...)`, which set the column,
cleared `autopilot_active` and wrote no ownership row — so the Inbox showed
the *queue* as owner while an agent was assigned. Three further problems
surfaced during the fix, none in the original finding:

- `take_over_from_autopilot` — a human taking a conversation back from AI
  — wrote no ownership row either. **That is the transition every "AI must
  not speak after a human steps in" rule reads.**
- `release()` on a conversation with no queue wrote nothing, leaving the
  timeline naming an agent who had just let go.
- Three production wiring sites built `ConversationService` with
  `ownership=None`. Two were the exact paths the defect was about, so a
  corrected `update()` would still have done nothing there.

**How it stands now.** `OwnershipService.transfer` is the only place a
transition happens; it writes the history row and *then projects it* onto
`assigned_agent_id`. The projection rule is `domain/ownership.assigned_agent`,
and it is total over `OwnerKind`. `ownership` is a **required**
collaborator, its failures are no longer swallowed, and
`tests/unit/test_ownership_is_the_only_writer.py` fails when any new code
path writes the column outside a two-entry allow-list — verified by
planting a real writer in a real module.

**What it owns.** `conversation_ownership`, and the projection.

**What it never owns.** Conversation status, queue membership, SLA.

**Sticky ownership.** A `STICKY` release policy holds a conversation for
its previous owner for a window. `release-expired-ownership` (beat, 300s)
writes the next row when the window lapses — an append-only timeline
cannot release itself.

**APIs.** `GET /conversations/{id}/ownership`.

**Tests.** `test_ownership.py` (36 unit),
`test_ownership_is_the_only_writer.py`, `test_ownership_timeline.py`,
`test_ownership_metrics.py`.

---

## 18. Routing, Service Directory & Execution Context

**Why it exists.** Every module needs the same three things about a
conversation: how the business behaves, how this customer is treated, and
what is true right now. Before `ExecutionContext`, each module fetched
them separately — which meant each could fetch something *different*, and
two modules disagreeing about a customer's tier is a bug that only appears
under timing nobody reproduces.

```
ExecutionContext
├── ServiceContext        immutable, versioned    how the business behaves
├── CustomerContext       immutable, versioned    how this customer is treated
├── ConversationFacts     snapshot                what is true right now
└── CompanyCapabilities   company-wide switches   what the company permits
```

**The rule.** *A module that receives an `ExecutionContext` **cannot look
anything up again**, because it holds no ids to look up with — only
resolved contexts.* That is structural, not conventional. If a module
needs something the context does not carry, the answer is to add it here,
deliberately, where every module sees the same value.

**Two immutable contexts, one mutable snapshot.** `execution.service.sla`
is a decision made when the conversation began; it cannot move under a
reader. `execution.conversation.status` is what was true a moment ago and
makes no claim to be stable. Both are correct; conflating them is how a
system starts deciding on stale state without anybody knowing which half
was stale.

**Customer context versioning, and the hazard it avoids.** A service
changes when an administrator edits it — rarely, deliberately. A customer
record changes *constantly* (a CRM sync writes a field back, `last_seen_at`
is touched on every visit). Minting a version on every change would produce
one version per conversation and effectively no versioning at all. So a
version is minted from a **fingerprint of the routing-relevant attributes
only**: `tier · is_vip · language · timezone · country_code · contract_id ·
pricing_profile_id · segment · contact_preference · preferred_agent_id`.

Equal fingerprint → reuse the version, write nothing. **Renaming a
customer does not fork their history; promoting them to VIP does.** The
fingerprint is SHA-256 over canonically ordered JSON — deliberately not
Python's `hash()`, which is salted per process and would silently fork
every customer's history on restart. A test asserts every field declared
routing-relevant actually moves the digest.

**Resolution pipeline** (`resolution_strategies.py`), in order:

1. **Customer selection** — the customer picked a service. First, and it
   has to be: a classifier overriding that would be the platform telling
   somebody they are wrong about their own problem. Also the cheapest
   stage (one comparison, no query).
2. **Business rules** — the company's own conditions on channel and
   keywords.
3. **Fixed service** — one service, or a nominated default.
4. **Fallback** — so a conversation always lands somewhere.

AI classification is **deliberately absent**: it belongs with the AI queue
worker, and a stage that guessed without a model would be a guess wearing
a classifier's name. Every stage answers with a `StageResult` carrying
evidence — what it looked at and what it found — which is why a stage that
resolves nothing is still worth running.

**Queue selection.** *The service owns queue selection where it names a
queue.* Customer → Service → Logical Queue → Runtime Queue → Agent. Routing
rules remain the fallback, not a legacy path — they are how a conversation
reaches a queue when no service claimed it.

**"No rules at all" and "rules that all missed" are two different
reasons**, on purpose: a new company that never configured routing and an
established one whose forty rules do not cover a new channel have the same
symptom and different fixes.

**Matched rules are captured as values** (`MatchedRule`), not as a
reference to the row — rules are edited and deleted routinely, and a
decision that re-read its rule would silently rewrite its own history
every time somebody tuned their routing.

**Which edits mint a version** is drawn field by field in
`VERSIONED_FIELDS`, because it is the decision an administrator has to be
able to predict:

| Edit | Mints? | Why |
|---|---|---|
| SLA target, AI policy, queue binding | **Yes** | A running conversation reads them |
| Name | **Yes** | Carried by value; without minting, conversations starting after a rename would report the old name |
| Code, description, active, display order | No | No conversation reads them |

**Foreign keys, each different for a reason.**
`service_versions.logical_queue_id` → `SET NULL` (deleting a queue must
not delete the history of every service that fed it).
`conversation_context_bindings.service_version_id` → **`RESTRICT`**, the
only one (deleting a version a conversation is bound to would leave it
unable to say what rules it ran under — the single thing this design
exists to guarantee). `customer_context_versions.contract_id` → **no
foreign key at all** (Billing owns those objects; a live reference would
be a second place billing configuration could be read from).

**Tables.** `services`, `service_versions`, `customer_context_versions`,
`runtime_queues`, `conversation_context_bindings`, `routing_rules`,
`routing_decisions`.

**APIs.** `/services` (6), `/routing-rules` (5) — both gated on
`queues.read`/`queues.manage`, deliberately **not** a new permission pair,
because a new permission would be denied to every company that has
customised its roles and would silently lock their administrators out of a
feature they can see in the navigation.

**Tests.** `test_service_resolution.py`, `test_service_context.py`,
`test_execution_context.py`, `test_routing_engine.py`,
`test_routing_decisions.py`, `test_routing_explainability.py`,
`test_service_directory_storage.py`, `test_service_resolution_ingest.py`,
`test_resolution_strategies.py`, `test_services_api.py`.

---

## 19. Queues & Assignment

**Why it exists.** A conversation must reach a person, fairly, respecting
skills.

**What it owns.** `queues`, `queue_required_skills`, `agent_skills`,
`agent_skill_assignments`, and the assignment strategies.

**What it never owns.** The routing decision (that is Routing), the
ownership row (that is Ownership).

**Both engines decide and describe; neither writes.**
`RoutingEngine.select_queue` returns a `QueueRouting` — the queue *and*
the reasoning. `AssignmentEngine.select_agent` returns an
`AgentAssignment` — the chosen agent, which strategy ran, how many people
were considered, and **why each of the others was passed over**. *"Why
isn't this with Ada?"* is answerable only if Ada was recorded at the moment
she was skipped; a bare `UUID | None` threw that away. The consumer
persists it, which keeps both engines unit-testable with a fake repository
and no database.

**Tests.** `test_assignment_and_routing.py`, `test_queues_api.py`,
`test_agent_skills_api.py`, `test_runtime_queues.py`.

---

## 20. SLA Engine

**Why it exists.** Time is the product's only objective measure, and
running out of time is *the one thing that is not an event*: nothing
happens, which is exactly the problem, so something has to notice.

**What it owns.** `conversation_sla_clocks`, `sla_policies`, `holidays`,
the four timers, health bands, breach detection.

**What it never owns.** *When* to start or settle a clock. That belongs to
the events the platform already has — entering a queue, an owner
accepting, a message going out, a status changing — and keeping the
decision at the call site is what stops this module growing a second
opinion about the lifecycle.

**Every method does two things and always both:** moves the clock, and
writes the transition into the conversation's decision log. A clock that
changed without a row would be a deadline nobody could explain.

**Three clocks start with the queue** — the customer is now waiting for
somebody to take it, for a first reply, and for the whole thing to be over
— all true at once, which is why they are separate clocks.

**The queue clock is answered on *acceptance*, not on reply.** "How long
has this customer been waiting for ownership?" is answered the moment
somebody owns it.

**A3, and how it was resolved.** SLA targets had two owners — the queue's
attached `SlaPolicy` (written by the SLA Builder and the Queue editor) and
`service.sla` (frozen onto the service version). The engine read the
second; the UI mostly wrote the first. Every company without a service
directory therefore started **no clocks at all** —
`conversation_sla_clocks` held zero rows across the entire installation,
with a permanently empty Breached queue and nothing reporting a problem.

Resolved by **one resolver**, `ConfigurationResolver.for_conversation`,
which resolves SLA targets *and* AI policy together down the same chain —
**service → queue → company → platform default** — so they cannot disagree
about what the company configured, and each answer carries the tier that
produced it.

**Tests.** `test_sla.py`, `test_sla_engine.py`, `test_sla_builder.py`,
`test_sla_policies_api.py`, `test_sla_target_resolution.py`,
`test_sla_targets_reach_the_engine.py`, `test_inbox_sla_order.py`
(the drift test that runs every health band through both the Python and
SQL implementations on the same rows — and which found a real defect,
SQLite's `julianday` returning `2400.0000001` where PostgreSQL returns
`2400`, putting a clock one band too healthy).

---

## 21. Policy Engine

**Why it exists.** *Every business rule in Blink Engage lives here, and
only here.* A rule like "AI may not answer a customer who asked for no
automated messages" is true everywhere or it is not true at all. Left to
each module, it gets written in the AI service, forgotten in the
automation service, and written slightly differently in a third place —
and the platform then behaves differently depending on which door a
conversation came through.

**Modules do not evaluate business rules. They ask.**

**What it owns.** `Policy`, `PolicyDecision`, the pure rules, and
`RecordingPolicyEngine`.

**What it never owns.** Facts. `ExecutionContext` carries facts; the
Policy Engine makes decisions. `ai_may_engage` was a property on the
context and was **removed** when this engine landed — a business rule
answerable on the context is one the AI module reads, the automation
module forgets, and a third reimplements differently, and a bare boolean
can never explain itself in the Inspector. **A test asserts it cannot come
back.**

**A decision is never a boolean.**

| Field | Meaning |
|---|---|
| `policy` | Which question was asked |
| `effect` | `allow` / `deny` |
| `reason` | Why, from a closed enum |
| `source` | **Where the answer came from** |
| `detail` | Anything beyond the reason code |

`source` is the field an administrator actually needs. "Denied" sends them
hunting; *"Denied, from the Customer Context"* tells them which screen to
open. Reasons are a closed enum, not free text, so the Inspector can group
and filter them — and **every reason has stored wording, enforced by a
test**, because a reason with no sentence renders as a raw enum name.

**Decisions are frozen.** They get written to the decision log, and a
caller able to edit one would be a caller able to rewrite history.

**Denial order: narrowest first.** When more than one rule would deny, the
reported reason is the one that stays true after the broader ones are
fixed. For `AI_ENGAGEMENT`:

1. The customer asked for no automated messages
2. The company's AI switch is off
3. No AI provider is configured
4. The service has AI switched off
5. An agent already owns the conversation
6. The conversation is finished

A customer's refusal survives an administrator re-enabling AI
company-wide, so it is reported first. And *"switched on but never set
up"* is a different answer from *"switched off"* — different problem,
different screen.

**`AI_ENGAGEMENT` fails closed. Every other policy defaults to allowing.**
`ai_enabled` is a compliance kill switch — a promise the company has made
— so `CompanyCapabilities` defaults every field to the *unavailable*
answer, and an execution carrying no capabilities at all is refused with
`CAPABILITIES_UNKNOWN` rather than treated as permission. Refusing costs a
reply; the other direction costs the promise, and nothing would fail, no
test would go red, and customers would receive AI replies from a company
that had switched AI off. **`CAPABILITIES_UNKNOWN` in the log means a
caller needs fixing, not that a customer was legitimately refused.**

Only AI fails closed — failing every policy closed would mean the engine
could not be adopted one module at a time.

**`MEMORY_RECORDING` and `KNOWLEDGE_LEARNING` also fail closed**, for the
same reason: a caller that did not populate capabilities is not thereby
granted permission to retain, or to mine, what somebody said.

**Asking is not deciding.** Two methods:

| | Records? | For |
|---|---|---|
| `evaluate(policy, execution)` | **Always** | Gating behaviour |
| `preview(execution)` | Never | The Routing Inspector |

If Inspector reads wrote decisions, opening it would append nine rows
about the act of looking, and a conversation's history would change every
time somebody read it. `preview` is synchronous and takes no repository,
so reaching for it instead of `evaluate` is a *visible choice* rather than
an easy mistake — the method that cannot record is also the one whose
answer nothing may act on.

**Allowances are recorded as well as refusals.** A log holding only
refusals answers "why was this blocked?" and not "why was this
permitted?" — and the second is the question asked after something reached
a customer that should not have.

**Recording is never fatal.** The decision is the product; the record is
evidence about it. An evaluation that could not be written must not stop a
customer being answered.

**What is stored as columns vs JSON.** `policy`, `policy_reason`,
`policy_source` and `policy_text` are **columns**, unlike
`resolution_stages` which is JSON — because these are what somebody
*filters* by, and a filter over a JSON key is a filter nobody writes.
`policy_text` is frozen at the moment of decision, so a row cannot
re-render itself and restate an old decision in today's words.

**Tests.** `test_policies.py` (35 unit),
`test_policy_explainability.py`.

---

## 22. Workflow Engine

**Why it exists.** Companies need automations the platform did not
anticipate.

**What it owns.** `workflow_definitions`, `workflow_runs`, the condition
DSL, the action registry.

**What it never owns.** Any action's underlying logic — `send_reply`
reuses `ConversationService`'s existing validated path rather than
re-deriving it.

**The condition DSL** is `{"all"/"any": [...]}` trees — deliberately *not*
a full expression grammar, so a visual builder is possible by
construction.

**Actions** (`WorkflowActionRegistry`): `add_tag`, `assign_to_queue`,
`assign_to_agent`, `set_conversation_status`, `send_reply`,
`create_notification`, `publish_event` (the extensibility escape hatch).

**One `WorkflowRun` per (workflow, event) pair, unconditionally** —
matched, failed, or skipped. One workflow's failure never affects sibling
workflows or the consumer loop.

**Binds `#`.** Every event, every company.

**Events emitted.** `workflow.executed`, `workflow.created`/`.updated`/
`.deleted`.

**Tests.** `test_workflow_engine.py`, `test_workflow_engine_consumer.py`,
`test_workflows_api.py`, `test_workflow_condition.py`.

---

## 23. Notifications & Realtime

**Two halves.**

**Half one — realtime.** `WS /api/v1/ws/agent`, authenticated with the
same JWT every REST call uses. Forwards agent typing state into
`ConversationService.send_typing_indicator`, which finally invokes the
`typing_indicator()` every `ChannelProvider` had implemented since it was
added and *nothing had ever called*. Also handles presence (connect flips
`Agent.status` `OFFLINE → ONLINE`, **never overriding an explicit
`AWAY`**; disconnect always sets `OFFLINE`) and forwards live
notifications.

**Half two — the durable inbox.** `notifications`, created either by
built-in rules in `NotificationRuleRegistry` or by the
`create_notification` workflow action. The consumer's `ROUTING_KEYS` are
*computed from the registry*, so adding a rule needs no consumer change.

**Dispatch is a beat sweep over `email_dispatched_at IS NULL` /
`push_dispatched_at IS NULL`**, deliberately not a fire-and-forget task
enqueue — the outbox/IMAP-poll-style periodic sweep is the established
pattern in this codebase and a second one would be an unexplained
divergence.

**Platform SMTP is distinct from a company's `EmailProvider` channel
credentials**, because a notification must reach an agent even for a
company with no customer-facing email channel configured.

**No new RBAC permission** — a personal inbox is gated by authentication
alone.

**Tables.** `notifications`, `notification_preferences`, `device_tokens`.

**Tests.** `test_notifications_api.py`, `test_notification_consumer.py`,
`test_notification_email_dispatch_task.py`,
`test_notification_push_dispatch_task.py`,
`test_notification_preferences_api.py`, `test_agent_realtime_gateway.py`,
`test_notification_rule_registry.py`.

---

## 24. AI Engine & Autopilot

**Why it exists.** Ten AI capabilities, three-plus backends, one cost
model.

**What it owns.** The `AiProvider` contract, prompt engineering, the
autopilot decision, confidence thresholds, per-agent AI provenance.

**What it never owns.** Whether it *may* engage (Policy Engine), what is
true (Knowledge), what happened (Memory), who has the conversation
(Ownership).

**One `complete()` method, not one method per feature.** Every LLM backend
shares the same fundamental capability, so prompt engineering for all ten
features lives once in `AiService`. Providers: OpenAI, Claude, Ollama,
plus Gemini, Azure OpenAI, Mistral, Groq, DeepSeek.

**Configuration is platform-level with a per-company override.** An AI
Engine is one shared capability per deployment, unlike a company's own
WhatsApp number.

**Fails as 503, never a silent empty result.** A disabled or unconfigured
platform surfaces `AiNotConfiguredError` → 503 consistently.

**One permission, not ten.** `ai.use` gates all ten endpoints — AI calls
have a real external per-call cost that justifies an on/off switch.

**Per-user rate limiting** (not per-IP) on every `/ai/*` endpoint, because
several agents share one office IP.

### AI is a queue worker, not a first responder

The single most important AI decision in the platform. When Autopilot is
permitted, the conversation is **not** answered immediately. It sits in
its queue, visible, for the service's `pickup_delay_seconds` (default 30),
so a human gets first refusal. Only if nobody takes it does
`ai-pickup-waiting-conversations` (beat, 10s) hand it to AI.

The delay is resolved down the same chain as everything else — service,
then platform default — rather than read from the service with a
hard-coded `0` behind it. **That literal was the entire reason "AI is a
queue worker" was untrue for every company without a service directory: a
fallback nobody had chosen, in a branch nobody could see.**

### Three activation modes, one decision

Autopilot originally lived entirely inside the `message.persisted`
consumer, so the *only* thing that could make it act was a new inbound
message — precisely the wrong shape for two of the three modes:

- **New message** — the consumer.
- **SLA** — fires *because* nobody replied, so no new inbound message is
  coming. Waiting for one would mean never replying at all.
- **Agent request** — a human clicking a button.

So the decision moved into `AutopilotService`, parameterised by
`AutopilotTrigger`, and the consumer became one of three callers. A fourth
trigger, `PICKUP`, handles the delay expiry.

**Idempotency.** `Conversation.autopilot_last_handled_message_id` guards
against at-least-once redelivery causing a duplicate auto-reply or a
duplicate handoff notification.

**AI is an owner, not an absence.** When AI engages it takes ownership
(`AI_OWNER`, reason `AI_ENGAGEMENT`). "Nobody has it" would be false, and
the moment AI hands back would have nothing to be a transition *from*.

**Hand-off.** Below the confidence threshold, or on an explicit
low-confidence signal from the model, Autopilot clears the flag, releases
ownership, and publishes `conversation.autopilot_handoff_needed`.

**Hallucination-proof auto-tagging.** `suggest_tags` only ever picks from
the company's real tag catalog — never a hallucinated tag name.

**Next Best Action is advisory-only**, surfaced to the agent, never
auto-executed.

**Usage tracking via the event bus, not a table.** Every capability
publishes `ai.completed`; the reporting consumer aggregates it.

**Events emitted.** `ai.completed`, `conversation.autopilot_replied`,
`.autopilot_stopped`, `.autopilot_handoff_needed`.

**Events consumed.** `message.persisted` (new-message trigger),
`conversation.sla_warning`/`.sla_breached` (SLA trigger).

**Tests.** `test_ai_service.py`, `test_ai_providers.py`,
`test_ai_factory.py`, `test_ai_api.py`, `test_ai_autopilot_consumer.py`,
`test_ai_lifecycle.py`, `test_ai_queue_worker.py`,
`test_autopilot_activation_modes.py`.

---

## 25. Knowledge — **Stage 1, as shipped**

**Why it exists.** `ILIKE '%query%'` meant a customer asking *"can I get
my money back"* found nothing in an article titled *"Refund policy"* — and
the AI, reading from that same search, correctly and uselessly replied
that it could find no relevant articles.

**What problem it solves.** Retrieval that finds the answer rather than
the words.

**What it owns.** `knowledge_categories`, `knowledge_articles`,
`knowledge_article_tags`, `knowledge_chunks`, `embeddings`, the article
index state, and hybrid retrieval.

**What it never owns.** Anything learned. Knowledge is written by humans
through approval; Memory is written by the Memory Manager from evidence.
Knowledge may *invalidate* Memory automatically; Memory may only ever
*propose* to Knowledge.

### What exists

| Piece | Where |
|---|---|
| `EmbeddingProvider` ABC | `domain/embedding_provider.py` |
| `VectorIndex` port + `VectorMatch` | `domain/vector_index.py` |
| Chunking rules (pure) | `domain/chunking.py` |
| Reciprocal Rank Fusion (pure) | `domain/retrieval.py` |
| OpenAI / Ollama / hashing providers | `infrastructure/embeddings/providers/` |
| Registry + platform/per-company factory | `infrastructure/embeddings/` |
| `vector(n)` column, dialect-branched | `infrastructure/database/vector.py` |
| pgvector HNSW adapter, exact adapter, factory | `infrastructure/vector/` |
| `knowledge_chunks`, `embeddings`, index state | migration `b1c7e94d3a52` |
| Indexing pipeline | `application/services/embedding_service.py` |
| Hybrid retrieval | `application/services/knowledge_retrieval_service.py` |
| Trigram / substring lexical half | `infrastructure/repositories/lexical_search_repository.py` |
| Re-index sweep (beat, 60s) | `infrastructure/tasks/knowledge_index_sweep_task.py` |
| `GET /knowledge/search`, `/index-status` | `api/v1/endpoints/knowledge.py` |
| pgvector verification harness | `scripts/verify_pgvector.py` |

### Hybrid retrieval, and why fusion by rank

Two retrievers whose scores are **not comparable**: trigram similarity in
`[0,1]` and cosine similarity in `[-1,1]`, measuring different things with
different distributions. Combining them by weighted addition requires
normalising two moving distributions against each other — a tuning
exercise that never converges and silently re-tunes itself whenever the
corpus changes.

**Reciprocal Rank Fusion consumes ranks only, so it has nothing to
normalise:**

```
score(d) = Σ_r  1 / (k + rank_r(d))        k = 60
```

`k` damps the top rank so a single retriever cannot dominate. A document
found by *both* retrievers outranks one found brilliantly by either —
which is the property that makes hybrid better than its halves.

**Why this matters for this product specifically:** pure vector search is
weakest at exactly what customer support retrieves most — an order number,
a plan name, a policy clause, a price. **"Plan B" and "Plan D" embed
almost identically, and quoting the wrong one is a wrong answer delivered
confidently.**

Ties break deterministically by first-seen order, so the same inputs
always produce the same output — a retrieval that reshuffled equal-scoring
results between calls would make every trace unreproducible and every
regression test flaky.

**Fusion happens at the article level**, not the chunk level, because that
is the unit a person searches for and cites — four chunks of one long
manual crowding out four different articles is the classic chunk-level
ranking failure.

### Degradation is graceful and explicit

With no embedding provider configured, retrieval runs lexical-only and
**says so** in `RetrievalOutcome.sources` / `degraded` / `reason`. A
provider outage is caught and degrades rather than propagating: an OpenAI
incident must not make the knowledge base unsearchable for every tenant,
including the ones who only ever type exact product names.

### Indexing: incremental by content hash

A naive re-index deletes an article's chunks and re-embeds all of them on
every save — correcting a typo in paragraph one of a forty-chunk manual
costs forty embedding calls. Since embedding is the metered,
rate-limited, externally-billed step, **that is the difference between a
feature a company can afford to leave on and one they turn off.**

So a re-index compares newly chunked text against what is stored, chunk by
chunk, and pays only for what changed. The hash is computed over the
*embeddable* string (heading path + body — exactly what the provider
receives), because hashing anything else would make unchanged chunks look
changed. `article_content_hash` deliberately excludes tags, category and
the publication flag: retagging changes nothing a vector encodes.

**The write path marks `PENDING`; the sweep does the embedding.** The
design implied an event consumer. A consumer awaiting an embedding call
would let one slow vendor back up the queue carrying every other knowledge
event, and a provider outage would become redelivery storms rather than a
number on a dashboard. Same division of labour as the outbox and its
relay, and it buys retries and backpressure for free.

**Per-company providers mean per-company batches.** Articles are grouped
by company so each group is indexed with that company's own provider and
model — indexing a mixture under whichever provider happened to be built
first would write vectors under the wrong model name and make them
silently unretrievable.

### Tenant isolation in vector search is structural

`company_id` is a **required keyword argument** on `VectorIndex.search`,
so there is no way to express a cross-company search. This matters more
for vector search than for ordinary queries: **an ANN index ranks before
predicates apply**, so a "search then filter" implementation would return
whatever fraction of its top-k happened to belong to the right tenant —
frequently zero for a small tenant on a large installation. *That failure
looks like poor relevance, not like a leak, so it survives review.*

`model` is likewise always filtered on: a partially completed model
migration otherwise returns a mixture of two models' vectors ranked
against each other, which is not a degraded result but a meaningless one.

### What the verification actually measured

`scripts/verify_pgvector.py` against the compose PostgreSQL: 10,000
embeddings across 20 tenants, the tenant under test holding 5%.

| Measure | Result |
|---|---|
| Cross-tenant rows in ANN results | **0** |
| Queries returning nothing for the small tenant | **0 / 40** |
| recall@10 vs the exact index | **1.000** |
| top-1 agreement | **40 / 40** |
| ANN latency p50 / p95 / max | **9.2 / 9.9 / 11.2 ms** |

An earlier version of that harness reported recall of **0.70 and was wrong
about its own subject**: it ran all forty queries inside one long-lived
transaction, and `PgVectorIndex` tunes each scan with `SET LOCAL`, which
is transaction-scoped — so it measured something the application never
does. Corrected to one session per query, the same index measures 1.000.
Worth recording because *an approximate index degrades silently*, and a
number that looks bad for the wrong reason is one step better than a
number that looks good for the wrong reason. Both are found the same way:
by making the harness resemble production.

### Where the design was wrong, and the build changed it

- **Chunks belong to articles, not versions.** Versions arrive later, so
  Stage 1 points at the article — honest rather than premature. The FK
  moves when versions land.
- **No `RetrievalOrchestrator`, no `IntelligenceContext`, no planner, no
  verifier.** Stage 1 ships the retrieval *mechanism*; the reasoning
  pipeline that consumes it does not exist.
- **The claim query deliberately does not filter soft-deleted articles.**
  Found by a test: a deleted article is exactly the one whose vectors must
  come *out* of the index. Filtering it out of the queue left it
  searchable and quotable forever while invisible in every list its
  company could see.
- **No `pgvector` Python dependency.** The storage format is a documented
  text form PostgreSQL casts natively; a `UserDefinedType` expresses the
  column in three lines.
- **`postgres:17-alpine` → `pgvector/pgvector:pg17`.** Same major version,
  so the existing volume is read as-is. The migration creates `vector` and
  `pg_trgm` and **fails loudly without them**, rather than degrading to an
  unindexable text column that would appear to work while scanning the
  whole corpus per query.

**Events emitted.** `knowledge_article.created`/`.updated`/`.deleted`,
`knowledge_category.*`.

**Events consumed.** None — indexing is a sweep, not a subscription.

**APIs.** `/knowledge` (12 routes) incl. `GET /knowledge/search`,
`GET /knowledge/index-status`; `POST /ai/knowledge-search`.

**Tests.** `test_semantic_retrieval.py` (16),
`test_knowledge_index_sweep.py` (13), `test_chunking.py` (11),
`test_retrieval_fusion.py` (7), `test_embedding_providers.py` (16),
`test_embedding_ownership.py` (8), `test_knowledge_api.py`.

**Known limitations.** The lexical halves differ by dialect (PostgreSQL
`word_similarity` trigram vs SQLite substring); no frontend for
`GET /knowledge/search` yet; backfill is the sweep, so a large corpus
takes minutes to become searchable after enabling a provider; one
embedding width per installation — `EMBEDDING_DIMENSIONS` is a schema
commitment.

---

## 26. Memory — **Stage 2, built and stabilised**

**Why it exists.** Knowledge answers *"what is true?"*. Nothing answered
*"what happened?"* — and until something did, every consumer that needed
it (AI, Workflow, CRM, Reporting, the Customer Timeline, Analytics) was
going to invent its own answer.

**What problem it solves.** Keeping an observation so that it can be
**explained, aged and erased**.

**What it owns.** `memory_facts`, `memory_evidence`,
`memory_confidence_samples`, `memory_contradictions`, and the Redis
working-memory store.

**What it never owns.** What is worth remembering. *That is a judgement,
and judgement belongs to the callers.* There is no extraction, no
clustering, no distillation — those need a model deciding what matters,
which is an Intelligence concern and a later stage. What exists today are
the callers that need no model: an agent writing a note, a CRM sync, a
workflow action, an import.

**Why that ordering is deliberate.** Building the store first means the
learning pipeline arrives into a context where evidence is mandatory,
confidence is computed, erasure works and the write path is already one
door — rather than into an empty schema where each of those becomes
something to remember to do.

### The four tiers

| Tier | Scope | Subject | Store | Erasable |
|---|---|---|---|---|
| **Organizational** | The business | Company | `memory_facts` | Aggregate only |
| **Customer** | One customer | Customer | `memory_facts` | **Yes, on request** |
| **Experience** | What has worked | Company or Agent | `memory_facts` | Aggregate only |
| **Conversation** | One live thread | — | Redis, TTL | With the conversation |

**One table for three tiers**, because they share the entire contract and
differ only in fact-type vocabulary and subject. Three tables would mean
three repositories and three copies of decay and lifecycle code — but the
decisive argument is erasure: a customer request must delete their facts
**and** weaken the aggregate facts their conversations supported, in one
transaction. Against one table that is one delete and one recompute;
across three it is a dance where a missed table is a compliance failure
that looks like nothing.

### The fact contract

Enforced by `domain/memory.validate_fact_shape`, called by the Manager
before anything reaches the session.

| Field | Why it exists |
|---|---|
| `subject_type` / `subject_id` | What the fact is *about*. **The erasure key** |
| `evidence` | Why it is believed. At least one, always |
| `created_from` | agent / customer-stated / inference / system-of-record / import |
| `confidence` | Computed from evidence, never claimed |
| `confidence_state` | observed → candidate → confirmed → trusted |
| `confidence_direction` | rising / stable / falling / contested / unknown |
| `lifecycle_state` | active → dormant → archived → purged |
| `steward_user_id` / `steward_role` | Where a contradiction gets routed |
| `human_state` | unreviewed / confirmed / suppressed / corrected |
| `last_observed_at` | New evidence arrived |
| `last_confirmed_at` | **Corroborated** — a stricter thing |
| `attributes_schema_version` | The payload evolves without a migration |

**Evidence is mandatory, and it is a pointer.** No excerpt, no transcript.
A conversation excerpt here would put customer content into a second store
with different retention and a different permission — and it would turn
erasure from a row deletion into a text-editing problem. `customer_id` and
`agent_id` are **denormalised onto the evidence row** for two load-bearing
reasons: the distinct-customer and distinct-agent counters are what stop
one person's habit becoming company policy, and **erasure joins on
`customer_id`** — resolving it lazily would make erasure depend on a row a
conversation purge may already have removed.

**`last_observed_at` is not `last_confirmed_at`.** If repetition counted
as confirmation, a customer repeating a wrong belief forty times would
confirm it. A fact supported only by customer-authored content **cannot
pass `CANDIDATE`** whatever the arithmetic says — `has_corroboration`
gates the ceiling. *The prompt-injection path where somebody repeats "the
refund policy is 100% cash" forty times is defeated by a counter, not by
detection.*

And the claim must be **backed**: `AGENT_STATEMENT` evidence must carry an
`agent_id`, `SYSTEM_RECORD` must carry a `source_id`. Before that check, a
caller could claim corroboration by setting a string, and a buggy
extractor labelling customer-derived observations `AGENT_STATEMENT` would
have defeated the ceiling silently — *the worst kind of security failure,
because nothing looks wrong.*

### Confidence

```
raw  = bias
     + w₁·log₁₊(support)
     + w₂·log₁₊(distinct_customers)
     + w₃·log₁₊(distinct_agents)
     + w₄·outcome_quality
     − w₅·log₁₊(contradictions)

conf = sigmoid(raw) · 0.5^(age / half_life(fact_type))
```

Weights: `W_SUPPORT=0.55`, `W_DISTINCT_CUSTOMERS=0.95`,
`W_DISTINCT_AGENTS=0.85`, `W_OUTCOME=1.10`, `W_CONTRADICTION=1.40`,
`BIAS=-2.30`. **A test asserts each weight actually moves the output** — a
declared input the function ignores is a rule that silently never takes
effect.

- **Breadth is weighted separately from volume.** Forty repetitions by one
  agent to one customer is one person's habit observed forty times; six
  agents converging independently is a practice. A formula that cannot
  tell them apart will confidently promote the first into company policy.
- **Logarithmic in the counts**, because the tenth observation genuinely
  tells you less than the second.
- **Per-type half-lives.** `terminology` 1460d · `preferred_language` 365d
  · `seasonal_pattern` 400d (a pattern *about* a yearly cycle must not
  expire before its season comes round again) · `promise_made` **30d** (a
  promise has a due date) · Experience types 90–120d (a market moves).
  Default 120d.
- **`outcome_quality` is neutral when absent, not bad.** Most
  conversations have no CSAT, and treating unmeasured as poor would mean
  only the surveyed minority could ever be believed.
- **Hysteresis.** Promote at 0.30 / 0.55 / 0.80; demote at 0.22 / 0.47 /
  0.72. A fact hovering at a boundary must not flap on every recompute —
  each flap is a state change something downstream reacts to.
- **Decay is finished at read time.** `decayed_confidence()` treats the
  stored column as a *cache* that was correct at
  `confidence_computed_at`. A stale cache now produces a slightly
  conservative number rather than a wrong one.

**Direction is measured from the evidence stream with decay removed**, in
`memory_confidence_samples`, **never** by differencing the confidence
column. Confidence already includes recency decay, so a naive difference
reports `FALLING` for every fact that is merely quiet — which is most
facts, most of the time — and the column would become a slower, noisier
restatement of `DORMANT`. `CONTESTED` (supporting *and* contradicting
evidence both growing) is the distinct and more actionable finding: two
departments quoting different lead times produce exactly this, and it is
usually the first time anybody notices.

### Two axes, not one chain

A fact reaches `TRUSTED` over six months — 200 conversations, 14 agents.
The topic goes quiet for a quarter and decays to stale. Then it is
observed again. **On one chain, where does it go?** Back to candidate
discards 200 conversations of evidence, so the fact is *less* believed on
strictly *more* evidence. Jumping straight to trusted makes "stale" a
label that meant nothing. There is no right answer because the question is
malformed.

Two axes resolve it cleanly: `DORMANT → ACTIVE`, confidence untouched,
because the evidence never went anywhere. **Displayed: `Stale → Trusted`.**
Exactly what a human would expect, and unreachable on one axis.

`display_label()` derives the single word a human reads — `suppressed`,
`contradicted`, `forgotten`, `archived`, `stale`, or the confidence state
— so the product vocabulary stays one-dimensional while the schema can
express what a chain cannot.

**Lifecycle ordering is the design.** A human's suppression outranks the
schedule (decaying a muted fact would remove it for a reason unrelated to
why it was muted, and reviving it on re-observation would un-mute it
behind their back). An explicit expiry outranks the default schedule.
Losing all evidence archives immediately — **not purge**, because the row
is the record that the platform once believed this. `ARCHIVED` does not
revive automatically: its evidence has been pruned, so a revived row would
carry counters it can no longer justify.

### Forgetting is not erasure

| | Forgetting | Erasure |
|---|---|---|
| Cause | Decay, retention | A legal request |
| Trigger | Scheduled | On demand, must complete |
| Scope | One fact | Every fact, evidence row and vector for a subject |
| Evidence | Pruned on archive | **Deleted** |
| Reversible | Until purge | **Never, by design** |
| Answer to an auditor | "It decayed" | "It is gone" |

`MemoryDecayService` never erases; `MemoryErasureService` never decays.

**The half of erasure that is easy to miss.** Deleting the facts *about* a
customer is obvious. The subtle half is the aggregate facts their
conversations **contributed to**. "Card declines spike at month-end" is a
fact about the business and it survives — but its support must be
recomputed once their evidence is gone, or it keeps claiming a confidence
it can no longer justify. So erasure does the third thing:

1. Find the aggregate facts they contributed to **first**, while their
   evidence still exists to identify them.
2. Delete the facts about them, and their vectors.
3. Delete their evidence everywhere else.
4. Recompute what is left. **A fact that loses its last support is
   archived, not deleted** — an erasure request did not ask for the
   company's own history to be rewritten.

Aggregate facts survive only because they are non-attributable *by
construction*: a fact supported by a single customer is not aggregate, and
the distinct-customer weighting is what keeps that line real rather than
asserted.

**Erasure is a fan-out with acknowledgement.** `ErasureParticipant` is a
protocol; each context erases its own store. A participant that raises is
recorded as **incomplete** rather than swallowed. `ErasureReport` returns
**counts**, not an acknowledgement, because "we ran erasure" is not
evidence and this is the response somebody forwards to a regulator.

Registered participants today: Memory itself, **Conversation Memory**, and
**Learning**.

### The Memory Manager is the only writer

Every guarantee rests on this. With two doors, confidence gets set by hand
somewhere, evidence gets skipped on the path somebody was in a hurry on,
lifecycle transitions happen outside the state machine, and the audit
trail acquires holes nobody can enumerate.

Enforced three ways:

1. **An AST guard** — `tests/unit/test_memory_manager_is_the_only_writer.py`
   fails if any module outside the Manager calls a memory write method,
   and a second check fails if a module merely *constructs* a memory
   repository outside a known list. Static rather than behavioural,
   deliberately: *a behavioural test covers the paths somebody thought to
   write; this covers the paths nobody has written yet.*
2. **The contract is checked at the door**, by the pure validator.
3. **One transaction boundary.** A fact, its evidence, its recomputed
   confidence and its lifecycle transition commit together or not at all.

Three modules are on the allow-list, each with its reason recorded in the
guard: the Manager; erasure (which must complete even where no Manager is
wired, and reaches recompute through a narrow port); and the decay sweep
(which purges rows the state machine already marked — every *recompute* in
it goes through the Manager).

**Counters are recomputed from evidence, never incremented.** An increment
is wrong the moment anything deletes evidence — which erasure does,
constantly.

**Re-observation is idempotent** on `(fact, source_type, source_id)`.

### Identity and dedupe

`uq_memory_facts_identity` on `(company, tier, subject_type, subject_id,
fact_type, fact_key)`. Without it a second observation creates a sibling
row, support splits, and a fact seen a hundred times crosses no threshold.

**The key is never the statement text** — a caller may reword its output
between runs, and keying on prose would fork a fact's history every time
the wording changed. `domain/memory_identity.py` normalises: Unicode NFKC,
case folding, Arabic diacritic removal and orthographic folding
(أ/إ/آ → ا, ة → ه), and **hashing rather than truncation** past 180
characters, because truncation makes two long distinct keys collide on
their shared prefix.

**For Experience, the stratum is part of the identity.** The same claim
about two segments is two facts; merging them would reintroduce the
confounding that stratification exists to remove.

### Policy and permissions

`Policy.MEMORY_RECORDING` gates whether the platform may remember anything
for a company. **It fails closed.** It is deliberately **independent of
`AI_ENGAGEMENT`**: Memory is consumed by Reporting, CRM, the Customer
Timeline and Analytics as well as by AI, so gating it on the AI switch
would mean turning AI off silently emptied the Customer Timeline — a
consequence nobody flipping that switch is asking for.

A customer who has asked for no automated messages is **not** refused
here. That preference is about being contacted by a machine, not about the
company keeping notes on its own relationship with them, and conflating
the two would let a contact preference quietly delete a business record.

| Permission | Gates | Default roles |
|---|---|---|
| `memory.read` | Reading memory | Owner, Admin, Agent |
| `memory.manage` | Record, confirm, correct, suppress | Owner, Admin |
| `memory.erase` | Irreversible erasure of a subject | **Owner only** |

Three rather than one, split by blast radius. `memory.enabled` defaults
**on**, unlike the AI switches — AI defaults off because it generates
content a company may not want sent; memory defaults on because it is how
the Customer Timeline and Reporting already describe a relationship.

**Events emitted.** The ten `memory.*` events. Payloads carry ids, counts
and structure — never the statement.

**Events consumed.** None. Memory has no consumer process; it is written
through the Manager by its callers.

**APIs.** `/memory` — 12 routes.

**Tests.** `test_memory_domain.py` (36 unit),
`test_memory_manager_is_the_only_writer.py` (6, incl. planted writers it
must catch), `test_memory_platform.py` (18),
`test_memory_stabilization.py` (21), `test_memory_api.py` (16). Migration
applied, downgraded and re-applied on real PostgreSQL.

### What stabilisation changed

The architecture freeze review demonstrated that the platform's
foundational property — *confidence cannot inflate without new evidence* —
was **false**. Four defects shared one shape: **a number that was tracked
instead of derived.**

| Finding | Was | Is |
|---|---|---|
| **B1** | `record()` refreshed `last_observed_at` before knowing whether evidence was new, so a replay reset recency and inflated confidence **4.7×** on nothing | Recency and revival gated on `evidence_added`. A replay changes nothing |
| **B2** | `contradiction_count += 1` — a redelivered contradiction demoted a true fact | `memory_contradictions` rows, unique per source; the count is derived |
| **B3** | `contradicting_delta` hard-coded to zero, so `FALLING` and `CONTESTED` were **unreachable code** | Real deltas, measured across a window |
| **B4** | The delta was `total − previous_delta` — a total minus a delta, drifting upward | Samples carry running totals; deltas derived from two of them |
| **E3** | Corroboration was a string a caller could claim | `AGENT_STATEMENT` needs an agent, `SYSTEM_RECORD` needs a source |
| **B6** | 500 facts/hour — **2.3 years for one pass at 10M facts**, with retrieval ranking on a years-stale column | Batch derived from corpus size; decay finished at read time |
| **B7** | Global claim ordering starved small tenants — the relay incident repeating | Tenant-fair rotation plus a recompute circuit breaker |
| **B5** | Erasure could not include other contexts; `working_memory_cleared` was a hardcoded `False` | Participant fan-out with acknowledgement |

**The invariant, now stated and tested:**

> **Every input to confidence is a `COUNT` over rows protected by a
> uniqueness constraint, and no code path may advance a time-based input
> without inserting one of those rows.**

Before the fix, a replay probe measured **+0.1006**. After it, **+0.0000**.

**One definition of an outcome.** `domain/conversation_outcome.py` is now
the single derivation of resolved / reopened / escalated / first-contact /
handling time, because Reporting and Learning were about to have two —
**the shape of the A3 defect that produced zero SLA clocks platform-wide.**
It carries two things the first design lacked: `resolved_by` (so a rule
firing is not read as evidence that something worked — a feedback loop the
AI-provenance mitigation does not touch, because a workflow is not AI) and
`settled` (so nothing learns from a conversation whose CSAT has not
landed).

---

## 27. Learning — **Stage 3, Phase 1 (Observe)**

**One sentence:** *a finished conversation becomes a traceable,
idempotent row carrying structural and lexical features, and nothing
else.*

Clustering, pattern detection, trends, gaps, contradiction detection,
knowledge candidates, memory candidates, suggestions, human review and
**every model call** are phases 2–4 and are **absent from the codebase,
not stubbed in it.**

### Why a phase that proposes nothing exists at all

A pipeline that observes and proposes nothing looks like an incomplete
feature. It is the opposite: it is the phase that makes the expensive
phases **measurable before they are switched on.** Three things become
facts rather than estimates once it ships:

1. **What extraction actually costs** over the real corpus, before
   anything metered is enabled. Tiers 0 and 1 are free, so the whole
   history can be run through them.
2. **What the feedback ratio really is** — the share of observed content
   the platform itself wrote. *That number decides whether phase 2 is safe
   at all, and no amount of design produces it.*
3. **Whether the pipeline can be re-run.** Phase 1 is where
   `pipeline_version` gets its meaning, and a rollback story invented
   after clusters exist is a rollback story invented too late.

### What an observation is

One unit of finished work, as Learning saw it. Not a message, not a
conversation row, and **deliberately not a channel.**

| Column group | Holds |
|---|---|
| Source | `source_kind`, `source_id`, `channel`, `observed_at` |
| Subject | `customer_id` (nullable — anonymous web chat is normal) |
| Provenance | `human_authored_count`, `ai_generated_count`, `ai_assisted_count`, `human_authored_fraction` |
| Outcome | `resolved`, `resolved_by`, `outcome_attributable`, `reopened`, `escalated`, `first_contact_resolution`, `handling_seconds`, `csat_score`, `outcome_quality`, `settled`, `settle_due_at` |
| State | `state`, `exclusion_reason`, `pipeline_version` |

**The extensibility seam, stated as a rule:**

> **The first `if source.channel == ...` inside Learning is the change
> that breaks it. Channel belongs to the adapter, never to the pipeline.**

`channel` is recorded for reporting and adapter debugging, and handed to
the Policy Engine — which *is* allowed to care. Nothing else in Learning
reads it. A voice call becomes a transcript with segments, an email thread
becomes turns, an ERP ticket becomes a source kind, and all of them
produce the same envelope.

**Content refs are pointers, never copies.** `learning_observation_refs`
holds `(ref_kind, ref_id, ordinal)` and **has nowhere to put a message
body — by construction, not by discipline.** Every observation carries at
least one ref or it is refused; a row asserting that something happened
with nothing to check it against is the same defect Memory refuses when a
fact arrives with no evidence. **Excluded observations are exempt**, and
that exemption is the point of recording them.

### Three states, and why exclusion is written down

| State | Meaning |
|---|---|
| `pending` | Assembled; its outcome may still change |
| `ready` | Settled and eligible for everything downstream |
| `excluded` | Policy refused, or there was nothing learnable |

`decide_state` evaluates in a **fixed order, and the order is the
design**:

1. **Policy first.** A company that forbids learning gets an excluded row
   and nothing else is evaluated — no features read, no content examined.
2. **Human content next.** An entirely machine-written exchange is the
   platform's own output.
3. **Substance.** "ok", "thanks" — real, and worth nothing.
4. Only then does settlement decide `ready` versus `pending`.

A company that forbade learning must get `policy_denied` and not
`no_human_content`, even when both are true. Not cosmetic: *"we were not
allowed to look"* is a materially different answer to a regulator than
*"we looked and found nothing."*

Writing an excluded row rather than nothing is what makes **"the platform
saw this and chose not to learn from it"** an auditable fact instead of an
absence somebody has to take on trust.

### Features: tiers 0 and 1 only

| Tier | What | Cost | Phase |
|---|---|---|---|
| 0 — structural | outcome, timings, counts | free | **1** |
| 1 — lexical | language, entities, topic tokens | negligible | **1** |
| 2 — embedding | placement against clusters | cheap | 2 |
| 3 — small model | intent, judgement | metered | 3 |
| 4 — strong model | per *candidate*, never per observation | expensive | 4 |

Phase 1 stops at tier 1. Tier 2 exists to place an observation against
*existing clusters* — there are none — and the charter permits Learning to
write only `CLUSTER_CENTROID` vectors into the shared index, so an
observation embedding **has nowhere it is allowed to live yet.**

Everything in `domain/learning_features.py` is **deterministic**: same
text, same features, every run. That is what makes `pipeline_version` a
rollback boundary rather than a label on a moving target.

**Two rules exist because production text broke the earlier ones (phase
1.5).** URLs are stripped before topic extraction — they are already kept
as entities, and their path segments are identifiers. And a token mixing
letters and digits is rejected as an identifier fragment: a CSAT link put
UUID and JWT pieces (`9d1d`, `gl9pwqnk`) into the topic list of every
conversation that received one, consuming six of twenty topic slots and
displacing real signal. The rule is deliberately **not a hex test** —
`cafe`, `dead` and `decade` are hexadecimal and also words.

Language detection is script-based and honest about it — `ar`, `en`,
`mixed`, or nothing. **`mixed` is a first-class answer rather than a
tie-break**, because Arabic/English code-switching in one message is
normal traffic here, not an edge case.

### The anti-feedback-loop defence

Autopilot answers conversations using knowledge and memory that Learning
produced. Observing those as evidence is circular by construction:
confidence rises on no new information, and **every counter looks healthy
while it happens.**

| Mechanism | Where | Effect |
|---|---|---|
| Provenance counts | `Provenance` on the envelope | An all-AI exchange is `is_evidence_bearing == False` → excluded |
| **Extraction filter (I-5)** | `LearningObservationService.assemble` | Machine-written turns removed **before** extraction, not filtered from the results after |
| Template exclusion | `is_system_generated` on message metadata | A platform template is neither human nor AI, and is not evidence |
| Feedback ratio | `GET /intelligence/health` | The share of observed content the platform wrote, on the operator's screen |

**The filter's placement matters more than it looks.** Filtering
afterwards would still let a conversation Autopilot answered contribute
the platform's own vocabulary to the topics it later clusters on — the
same loop wearing a different hat, and invisible because the row would
still show a healthy human fraction.

**The template rule was added in 1.5 after production data showed the loop
being closed by something the AI filter was never going to catch.** The
CSAT invitation carried no provenance marker, so its wording —
"feedback", "moment", "share" — was being read as human-authored content.
Nobody wrote it *to this customer*; it counts as neither human nor AI,
because adding it to either number would make that number lie.

`is_ai_assisted` content is **admitted**: a human read the draft and
pressed send, so it is real content. What it may never do is
*corroborate*, which is enforced by the Memory contract when phase 2
proposes facts — not by dropping it here.

### Outcomes are copied, never recomputed (I-6)

`domain/conversation_outcome.derive` is the single definition, shared with
SLA and reporting. Learning copies its result into columns and re-derives
nothing. **Two definitions of "resolved" is the A3 defect.**

`outcome_attributable` is separate from `resolved` and does most of the
work. A conversation Autopilot closed is genuinely resolved; **what it is
not is evidence that whatever preceded it worked.** Only
`ResolvedBy.HUMAN` is attributable — a workflow or timeout close is a rule
firing, not a person judging a conversation finished, and *a pipeline that
conflated the two would learn most enthusiastically from its own
behaviour.* Phase 1 cannot separate a workflow close from a human one on
the available data, so an unassigned close answers `unknown` rather than
guessing `human`. `unknown` is not attributable.

### Settlement

An outcome is not final when a conversation ends. CSAT arrives minutes to
days later; a reopen invalidates the resolution outright. Two paths close
the window:

- **`learning-signals-consumer`** shortens it whenever the thing it was
  waiting for actually arrives. A rated conversation settles immediately;
  waiting further would delay learning for no gain.

  > **`conversation.reopened` had no publisher until 1.1.0.** The
  > consumer bound it and its own docstring called it *"the one that
  > matters most — it invalidates a resolution outright"*, but nothing in
  > the platform produced that routing key: `ConversationService` emitted
  > `f"conversation.{status.value}"` only for the two terminal statuses,
  > and the ingest consumer's reopen path set `status = WAITING` and
  > published nothing. The handler was tested — against a **fabricated
  > event dict**, which is the same blind spot that let the outbox/relay
  > incident survive. Both paths now publish it, and
  > `test_bound_routing_keys_have_publishers.py` fails the build for any
  > binding with no publisher. See
  > [the 1.1.0 release report](../releases/1.1.0.md).
- **`settle-learning-observations`** (beat, 15 min) promotes the ones
  where nothing ever arrives — which is most of them — after
  `LEARNING_SETTLE_HOURS` (default 72).

72 hours is deliberately far shorter than the 14-day CSAT token life.
**Waiting for the last possible response would make every observation two
weeks stale, which is the same as not learning.**

**Attaching a signal never un-excludes an observation.** A company that
forbade learning does not start learning because a survey came back.

**The sweep re-derives nothing.** Settlement is a fact about time: the
window elapsed, so the outcome recorded at assembly is now final.

### Idempotency and replay

`UNIQUE (source_id, pipeline_version)` is the whole idempotency story.
At-least-once delivery makes redelivery routine, a consumer restart
replays, and a deliberate re-run is a supported operation. **Two rows for
one conversation would double every count derived from them, and the
counts are the input to clustering, so the error would compound rather
than show up as a number somebody could sanity-check.**

Evidence pointers and the features row are equally idempotent: a
re-assembly updates features in place and adds no duplicate refs.
`AssemblyResult` reports `created` and `features_written` so a caller
replaying a batch can see that its replay changed nothing.

**Including `pipeline_version` in the key is what makes a bad extraction
recoverable**: version 2 writes *alongside* version 1 instead of over it,
and the two can be compared before either is trusted. That is exactly what
phase 1.5 did — `PIPELINE_VERSION` is now **2**, and everything observed
before the fix was **re-observed rather than overwritten**.

`learning_runs` carries `UNIQUE (company_id, run_type, pipeline_version,
window_start)`, so two workers cannot both claim one window.

### Ownership, and the guards that keep it

Four tables, all carrying `company_id`, all **derived and rebuildable**
from source events — which is the property that makes `pipeline_version`
rollback real.

Learning **reads** conversations, messages, CSAT responses and channel
configs. It **writes nothing outside its own four tables (I-2)**, enforced
by an AST guard (`tests/unit/test_learning_writes_only_its_own_tables.py`)
rather than by review. That guard is also what makes replay safe:
re-running a pipeline that also touched `conversations` would replay side
effects onto live rows.

**The evidence graph stays acyclic (I-4).** Neither consumer binds a
`memory.*`, `learning.*` or `intelligence.*` routing key, asserted by a
test that parses their `ROUTING_KEYS`. **Phase 1 also writes no memory at
all**, guarded by the same file. An observation is evidence, not a fact —
and a confidence that can be written from two places is a confidence
nobody can explain.

### Policy and permissions

`Policy.KNOWLEDGE_LEARNING` is the kill switch, evaluated through
`RecordingPolicyEngine` so *"why did Learning ignore this company?"* is
answerable from the decision log rather than from worker output nobody
keeps. It **fails closed.**

It is nested under the `memory` settings section rather than given one of
its own: Learning is a *use* of retained observation, so a company that
switched memory off has already answered this, and `is_memory_enabled` is
checked first — this flag only ever narrows. **But it can be refused on its
own**, which is the point: a company may accept the platform keeping notes
on its relationships while refusing to have those notes mined for
patterns. Collapsing the two would force an all-or-nothing choice on
exactly the regulated tenants who need the distinction most.

| Permission | Role | May |
|---|---|---|
| `intelligence.read` | Owner, Admin | Read observations, runs, health |
| `intelligence.manage` | Owner | Reserved for phase 2 |

**Not on Agent.** An observation is a customer conversation seen sideways
— provenance counts, outcome attribution, extracted entities — which is an
operator's view of the platform's own behaviour, not part of an agent's
working day.

### Erasure

Learning registers as an `ErasureParticipant`, closing **B5**. Only
`customer` subjects have anything here: an agent appears in an
observation's participants but is not its subject, and **erasing an agent
must not delete the company's record that work happened.**

Children are deleted **explicitly**, not left to `ON DELETE CASCADE`.
PostgreSQL honours the cascade; SQLite enforces foreign keys only with a
pragma, and a bulk `DELETE` bypasses the ORM's own cascade either way.
**An erasure report must not depend on a database setting to be true.**

### Health, and the two counters that are not columns

The five counters are `pending`, `settled`, `failed`, `replayed`,
`erased`.

- **`failed`** is a fact about a *run*, not an observation. An observation
  that failed to settle is still a correct pending observation, and a
  `FAILED` state would make a transient database blip look like corrupted
  data.
- **`erased`** is counted from the audit trail, because after an erasure
  there is nothing left in Learning's tables to count. *The audit log
  outlives the rows it describes, which is what a deletion record is for.*
- **`replayed`** counts superseded generations. It stays at zero through
  ordinary redelivery, which is what makes it worth watching.

`feedback_ratio` is on the same payload as health deliberately: it is the
number most likely to be quietly wrong, and an operator should not have to
know it lives somewhere else.

### Configuration

| Setting | Default | Meaning |
|---|---|---|
| `LEARNING_SETTLE_HOURS` | 72 | How long an outcome may still change |
| `LEARNING_SETTLE_BATCH_SIZE` | 500 | Observations promoted per sweep |
| `LEARNING_SETTLE_INTERVAL_SECONDS` | 900 | Sweep cadence **and** the width of the window a run claims — one setting because the two must agree |
| `memory.learning_enabled` (per company) | `true` | The kill switch |

**Nothing here costs money in phase 1.**

### Runtime shape

| Process | Binds / schedule | Does |
|---|---|---|
| `learning-observation-consumer` | `conversation.resolved`, `.closed` | Assembles one observation per finished conversation |
| `learning-signals-consumer` | `csat.submitted`, `conversation.reopened`, `.transferred`, `.sla_breached` | Attaches late outcome signals |
| `settle-learning-observations` | beat, 900s | Promotes observations whose window closed |

Neither binds `message.persisted` — an observation is about a *finished
unit*, and assembling one per message would produce a row per turn that
the settle window then has to reconcile.

**Learning never blocks anything.** Both consumers are separate processes
that read other contexts and write only Learning's tables. If they are
down, every other context continues unaffected. `_MAX_TURNS = 500` bounds
how much of one conversation is read.

**Events emitted.** None. Phase 1 emits no domain events — it is a pure
sink.

**Events consumed.** Six routing keys across two consumers.

**APIs.** `/intelligence` — 4 read-only routes.

**Tests.** `test_learning_domain.py` (28 unit),
`test_learning_writes_only_its_own_tables.py` (6 AST guards, **including a
test that watches the guard fire, because a guard nobody has watched fail
is a guard nobody knows works**), `test_learning_platform.py` (35
integration). Plus one live run against the deployed stack over real
conversations — **which is what found the two extraction defects the
5,000-sample benchmark scored 1.000 on.**

### Deviations from the charter, recorded not absorbed

1. **Tiers 0–1, not 0–2.** Tier 2 lands with clustering, because an
   observation embedding has nowhere it is permitted to live.
2. **A fourth table, `learning_observation_refs`.** The charter names two
   tables but its traceability requirement needs a third.

Both are narrowings; neither adds capability. Deferred within phase 1
deliberately: the operator-triggered **windowed replay** endpoint. Replay
*safety* is built — that is what `pipeline_version` and the unique key are
— but the trigger belongs with phase 2, when there is something to replay
*into*.

---

## 28. Reporting, Billing, Platform Admin, ERP, Audit, Search, Inspector

### Reporting & Analytics

Five incremental rollup tables fed by `reporting-consumer` bound to eight
routing keys. Reports aggregate a handful of pre-summed rows per date
range instead of scanning `conversations`/`messages` directly — **the
concrete payoff of the event bus at this scale.**

The one exception is the **Live Dashboard**, which queries current
`agents`/`conversations`/`queues` state directly: a daily rollup cannot
represent "right now," and these tables are small enough that a direct
query costs nothing.

`conversation.updated` carries `previous_status` so the consumer detects a
genuine transition rather than recounting an already-closed conversation
on every unrelated update.

**CSAT reuses the existing JWT machinery** for a conversation-scoped
`TokenType.CSAT` survey link and a public token-gated response endpoint —
no new customer-auth system built for one rating per conversation.

PDF/Excel export is **one generic table-renderer pair** shared by every
report, not one renderer per report type.

### Billing

A full bounded context: metering (one immutable `billable_events` row per
customer-facing message), pricing (profiles, rates, volume tiers,
effective dating, an audit log), usage periods, invoicing (document
numbers, state machine, immutability, credit notes), payments (four
flows, intents vs payments, reconciliation, reversal, refunds),
collections (dunning, suspension), and a **double-entry financial
ledger** where nothing is ever amended.

Two rules worth internalising:

- **Metering and pricing are separate systems.** A metering row cannot
  know a price. The meter does not construct the pricing engine.
- **Round once, at the end.** Currency decimal places are a property of
  the currency (JOD has 3), and nothing converts between currencies.

### Platform Administration

A cross-tenant operator surface with its own principal (`PlatformContext`).
**The platform-admin flag is re-read from the database on every request**
rather than trusted from the token, because platform authority is the most
privileged thing in the system and revoking it must take effect
immediately — not after the access token's 15-minute window.

A platform token **carries no `company_id`**, and `get_current_auth`
rejects it outright rather than relying on ~100 tenant endpoints to
notice.

**Read-only operators** exist as a distinct state. A bug this closed:
read-only platform operators could change everything except pricing.

### ERP Integration

**One named integration, not a plugin architecture.** `ErpClient` is a
`Protocol` (like `DomainEventPublisher`), not a registry-backed ABC (like
`ChannelProvider`), because there is exactly one implementation and
nothing to register a second entry against.

Outbound: `erp-sync-consumer` binds `customer.created` and **silently
no-ops for the vast majority of companies with no ERPNext connection**,
syncing idempotently via a unique `ErpCustomerLink` for the rest.
ERPNext-side failures are logged, never re-raised, so a customer's sync
failing cannot block the customer's own creation.

Inbound: a doctype-agnostic webhook lands every document type in one
generic `erp_synced_records` cache table rather than six near-duplicate
tables, since invoices/orders/quotations/tickets/payments/contacts are
heterogeneous, read-only, per-company-customised shapes only ever
displayed.

### Audit

`audit-log-consumer` binds `#`. **"What gets audited" is "everything"**,
which is both simpler and safer for compliance than an opt-in list a
future developer could forget to extend — with the `_REDACTED_PAYLOAD_FIELDS`
carve-out for four free-text fields (§8).

### Search

`GET /search` — cross-entity global search, each entity gated on its own
permission.

### The Conversation Inspector (the Black Box)

`GET /conversations/{id}/inspector` — **not feature-gated**, because
explaining what the platform did to a conversation is not a paid extra.

It reads, in order: the service resolution stages and their evidence, the
routing decision and matched rule, every recorded policy evaluation, the
queue decision, the assignment decision and every rejected candidate with
its reason, the ownership timeline, the four SLA clocks and their
transitions, and the AI decisions. Six questions, one screen, no
reproduction of the conditions.

`evaluate_all(execution)` answers every policy in one call, via `preview`
— which records nothing (§21).

---

# Part IV — Cross-cutting

## 29. Every policy

Eleven policies. All pure: handed an `ExecutionContext`, return a
`PolicyDecision`. No repository, no clock, no I/O.

| Policy | Question | Enforced today | Fails closed? |
|---|---|---|---|
| `AI_ENGAGEMENT` | May AI answer this conversation? | **Yes** | **Yes** |
| `ROUTING` | May this conversation be routed? | Yes | No |
| `VIP_QUEUE_ENTRY` | May it enter the VIP lane? | Yes | No |
| `QUEUE_BYPASS` | May it skip the queue entirely? | Yes (**denied** unless a service opts in) | No |
| `AGENT_PICKUP` | May an agent take it? | Yes | No |
| `OWNERSHIP_CONTINUATION` | May a previous agent keep it? | Partly | No |
| `MEMORY_RECORDING` | May the platform remember anything for this company? | **Yes** | **Yes** |
| `KNOWLEDGE_LEARNING` | May the platform mine retained observation? | **Yes** | **Yes** |
| `SLA_PAUSE` | May the SLA clock stop? | Not yet | — |
| `AUTOMATION_EXECUTION` | May an automation run? | Not yet | — |
| `AUTO_CLOSE` | May it be closed without a human? | Not yet | — |

**The three unenforced policies exist deliberately.** Rather than omit
them — which would leave each future module free to invent its own answer
— they answer `NOT_YET_ENFORCED` from `PLATFORM_DEFAULT`. A reader of the
Inspector sees *"allowed because this policy is not yet enforced"*, which
is the truth, instead of a fabricated rationale that reads like a real
decision.

`OWNERSHIP_CONTINUATION` shows the middle case: the 24-hour window belongs
to a later milestone, but that a *finished* conversation has no owner to
continue is knowable today, so that much is enforced now.

**Facts versus decisions, worked through one example.**
`ExecutionContext.is_priority` says what is *true of the customer*. The
two policies built on that one fact deliberately **disagree**:

- `VIP_QUEUE_ENTRY` — **allowed**. A VIP goes to the front of a lane.
- `QUEUE_BYPASS` — **denied** unless a service explicitly opts in.
  Bypassing means never queueing at all, which contradicts the Queue First
  Principle. *Folding these into one rule is how a platform quietly
  acquires conversations that exist nowhere.*

**Replacing a rule.** `PolicyEngine(rules={...})` overrides individual
rules without editing the engine. This is the seam that keeps the module
from becoming something people work around: an installation with genuinely
different policy overrides a rule; it does not fork the engine or
reimplement the check locally.

**Outstanding migrations into the engine.** The AI Autopilot gate is
migrated (four of its five conditions are now `CompanyCapabilities`). The
queue's own opt-in stays inline as the outer gate — it predates services,
and a company that has not adopted the service directory has no service AI
policy to replace it with. That is a gap in *explainability*, never in
enforcement, and it closes as services become universal. `api/deps.py`
still gates the agent-facing AI endpoints on its own company-switch check.
**Each migration deletes the local copy rather than leaving both.**

---

## 30. Every architectural invariant

These are the statements that, if violated, mean the platform is no longer
the thing this document describes. Most are mechanically enforced.

| # | Invariant | Enforced by |
|---|---|---|
| 1 | Every business fact has exactly one owner | `domain-ownership.md` audit + the guards below |
| 2 | `OwnershipService.transfer` is the only writer of `assigned_agent_id` | **AST guard** `test_ownership_is_the_only_writer.py`, two-entry allow-list |
| 3 | `MemoryManager` is the only writer of memory tables | **AST guard** `test_memory_manager_is_the_only_writer.py`, three-entry allow-list with reasons |
| 4 | Learning writes only its own four tables (**I-2**) | **AST guard** `test_learning_writes_only_its_own_tables.py` |
| 4b | Every routing key a consumer binds has a publisher | **Static guard** `test_bound_routing_keys_have_publishers.py`, verified by watching it fail |
| 5 | The evidence graph is acyclic (**I-4**) | Test parses consumer `ROUTING_KEYS`; no `memory.*`/`learning.*`/`intelligence.*` binding |
| 6 | Phase 1 Learning writes no memory at all | Same AST guard |
| 7 | Every memory fact has at least one piece of evidence | `validate_fact_shape`, called by the Manager before the session |
| 8 | Every confidence input is a `COUNT` over uniqueness-constrained rows; no code path advances a time-based input without inserting one | `test_memory_stabilization.py` — measured +0.0000 on replay |
| 9 | A fact uncorroborated by an agent, a system of record or an outcome cannot exceed `CANDIDATE` | `next_confidence_state` ceiling |
| 10 | Corroboration must be **backed** — `AGENT_STATEMENT` names an agent, `SYSTEM_RECORD` names the record | `validate_fact_shape` |
| 11 | Every observation carries at least one content ref, or is refused (excluded rows exempt) | `learning_observation.validate` |
| 12 | Evidence and content refs are **pointers, never copies** | Schema — there is nowhere to put a body |
| 13 | An erasure that any participant cannot confirm is **incomplete**, never silently partial | `ErasureReport` + participant fan-out |
| 14 | Erasure and forgetting are separate operations with separate audit records | Two services; `MemoryDecayService` never erases |
| 15 | The event and the business change it describes commit or roll back together | Transactional outbox on the same session |
| 16 | A policy cannot be asked quietly | `RecordingPolicyEngine.evaluate` always records; `preview` cannot |
| 17 | `ExecutionContext` holders cannot look anything up again | They hold no ids, only resolved contexts |
| 18 | `service_versions`, `customer_context_versions`, `conversation_context_bindings` are append-only | **PostgreSQL triggers refusing UPDATE/DELETE**, plus repositories exposing no mutating method |
| 19 | `ai_may_engage` cannot return to `ExecutionContext` | A test asserts it |
| 20 | The platform refuses to boot half-wired | `core/wiring.py`, plus a test that every optional collaborator on a listed service is named |
| 21 | Every `PolicyReason` has stored wording | A test asserts it |
| 22 | Every declared confidence weight actually moves the output | A test asserts it |
| 23 | Every field declared routing-relevant actually moves the customer-context fingerprint | A test asserts it |
| 24 | No cross-company vector search is expressible | `company_id` is a required kwarg on the only search method |
| 25 | An assembled observation is unique per `(source_id, pipeline_version)` | DB constraint |
| 26 | A learning run window is claimed once | `UNIQUE (company_id, run_type, pipeline_version, window_start)` |
| 27 | Re-observation is idempotent on `(fact, source_type, source_id)` | DB constraint |
| 28 | Counters are recomputed from evidence, never incremented | Manager code + the stabilisation tests |
| 29 | Knowledge may invalidate Memory automatically; Memory may only propose to Knowledge | `MemoryManager.contradict` exists; there is no automatic Memory→Knowledge path |
| 30 | Intelligence owns no data | It does not exist yet; the read-only-port design is specified for when it does |

### The five sanctioned crossings between Knowledge, Memory and Intelligence

Anything else is a boundary violation.

| Crossing | Mechanism | Direction |
|---|---|---|
| Memory → Knowledge | **Knowledge Suggestion**, human-approved | Never automatic |
| Knowledge → Memory | **Contradiction**, demotes or retires a fact | Automatic, one-way |
| Knowledge + Memory → Intelligence | Read-only retrieval into `IntelligenceContext` | Read only |
| Knowledge → Intelligence (voice) | **Voice Constraints**, enforced at the verifier | Applied, never cited |
| Memory → Intelligence (voice) | **Voice Profile**, a generation directive | Shapes phrasing, never facts |

**The first two are asymmetric, and the asymmetry is the point.**
Official truth corrects observation on sight; observation asks permission.
That single asymmetry is what "official knowledge wins" means when it is a
mechanism rather than a sentence.

**Half of it is built.** `MemoryManager.contradict` demotes on sight. The
answer-side guarantee — a generated reply refused unless its restricted
claims cite an authoritative source — waits on a verifier Stage 1 did not
build (**B8**). **Authority is advisory on that path until it exists**, and
three documents were amended to say so plainly rather than continue
claiming a guarantee that did not hold.

---

## 31. Every important design decision

A running list, each with its reason, because the reason is what prevents
the decision being undone.

**Architecture**

1. **Clean Architecture with `domain/` meaning "framework-free"**, not "a
   business domain". A rule that could look something up would be a rule
   whose answer depended on when you asked it.
2. **Repository pattern with `company_id` as a required kwarg** — makes a
   cross-tenant query hard to write, and makes write methods enumerable by
   an AST guard.
3. **One database, not one per context.** Contexts are enforced by
   ownership rules and static guards. The erasure guarantee is *easier* to
   keep in one transaction than across four databases.
4. **Registry keyed by a database-stored string** as the universal plugin
   idiom — channels, SMS gateways, AI providers, embedding providers,
   workflow actions, notification rules.
5. **`Protocol` when the caller holds the object; `ABC` + registry when it
   has to find it by name.** `ErpClient` and `DomainEventPublisher` are
   Protocols; `ChannelProvider` and `AiProvider` are registered ABCs.

**Events**

6. **Transactional outbox, not direct publish.** No dual-write gap.
7. **RabbitMQ topic exchange for fan-out; Celery only for scheduled
   work.** Celery's task model cannot express fan-out without abuse.
8. **Two tiers, not one bus wearing two hats.** Durability is exactly the
   property a typing indicator does not need.
9. **The write path does the cheap half in-transaction; a bounded sweep
   does the expensive half.** Applied to the outbox relay, knowledge
   indexing, notification dispatch and memory ageing. Buys retries and
   backpressure for free.
10. **`message.received` (pre-persistence) and `message.persisted`
    (post-persistence) are two different events**, because a consumer that
    needs our resolved ids cannot use the first.

**Data**

11. **Pointer, never copy** — memory evidence and learning content refs.
    Two reasons: a copy is a second store of customer content with its own
    retention, and it turns erasure from a row deletion into a
    text-editing problem.
12. **Append-only where the row *is* the fact**, with database triggers
    where the guarantee must survive a `psql` session.
13. **No soft delete on the memory tables** — a store promising both
    immutability and deletion is promising one of them falsely.
14. **Pointer, not flag, for "the current version".** Two rows both
    claiming `is_current` is a state no query can resolve.
15. **Names and configuration are copied by value onto decisions and
    clocks**, so a rename does not rewrite history.
16. **Version numbers allocated read-then-write, guarded by a unique
    constraint.** A counter table would serialise every edit on the
    installation to avoid a collision that happens when two people edit
    one service in the same second.

**Intelligence**

17. **Three domains, structurally separated**, before anything generates
    from them.
18. **Stage order: retrieval → memory → learning.** The Memory Manager's
    exclusive write ownership is an invariant, and an invariant is cheap to
    start with and expensive to retrofit. *A fact written by a learning
    consumer before the Manager exists is a fact written outside the
    lifecycle, with no evidence rows and a confidence somebody set by hand
    — and backfilling that is archaeology, not a migration.*
19. **Erasure ships in the same stage as the first fact**, because a
    memory store that cannot yet prove deletion is one that should not yet
    hold personal data.
20. **Confidence is computed, never model-claimed.** A model's
    self-assessment is uncorrelated with whether a claim is true *of this
    company* — the one thing the model cannot know.
21. **Two axes, not one chain**, for the memory lifecycle.
22. **Hybrid retrieval fused by rank, not by score.** Nothing to
    normalise.
23. **Experience is a Memory tier, not a fourth domain.** One erasure
    boundary means one owner.
24. **Negative experience is a re-ranking penalty and a verifier check,
    never a prompt instruction.** *"Do not say X" in a prompt is a reliable
    way to make a model say X.*
25. **Learning phase 1 observes and does nothing else**, so the expensive
    phases become measurable before they are switched on.
26. **Company Behavior is reserved, not sketched**, because its hard part
    is migrating five configuration surfaces.

**Operations**

27. **AI is a queue worker, not a first responder.** The pickup delay is
    the mechanism.
28. **A conversation in a queue is *owned by the queue*, not
    unassigned.**
29. **Reopen returns to the queue, never to the previous owner
    directly.**
30. **One resolver per fact** — SLA targets, AI policy and the confidence
    threshold all resolve down the same service → queue → company →
    platform chain, through `ConfigurationResolver`.
31. **Unsupported channel capabilities are honest no-ops with documented
    reasons**, never fake implementations.
32. **`preview` cannot record; `evaluate` cannot not.**

---

## 32. Every scalability mechanism

| Mechanism | Where | What it buys |
|---|---|---|
| **`SELECT ... FOR UPDATE SKIP LOCKED`** | Outbox relay claim | Horizontally safe relays — add `celery-worker` replicas, throughput scales, no coordination |
| **Partial indexes on "pending" predicates** | `event_outbox WHERE dispatched_at IS NULL`, notification dispatch, AI pickup, knowledge index | A sweep with an empty backlog costs one indexed query regardless of table size |
| **Independent consumer processes, one queue each** | 12 consumers | Scale a hot consumer independently of a cold one; RabbitMQ's competing-consumers semantics load-balance within a type |
| **Manual ack** | `run_consumer` | A crashed handler leaves the message for redelivery instead of losing it |
| **Dead-letter guard** | `claim_batch(max_attempts)` | One poison event costs at most `max_attempts` wasted ticks, never an unbounded starvation |
| **Bounded batches everywhere** | `events_relay_batch_size`, `embedding_index_batch_size`, `memory_decay_batch_size`, `learning_settle_batch_size`, `_MAX_TURNS=500`, `MAX_CONTENT_REFS=200` | No sweep can be surprised by corpus size |
| **Tenant-fair rotation** | Memory decay sweep (`memory_sweep_companies_per_run`) | **B7** — a global claim order let one large tenant consume the sweep entirely and every other company's memory stopped ageing |
| **Batch sizing derived from corpus size** | Memory decay (`memory_target_pass_hours`) | **B6** — a fixed 500/hour meant 2.3 years for one pass at 10M facts |
| **Recompute circuit breaker** | `memory_recompute_max_attempts` | A permanently failing row cannot consume the sweep |
| **Decay finished at read time** | `decayed_confidence()` | The sweep keeps the cache warm; a stale cache is conservative, not wrong |
| **Incremental indexing by content hash** | `EmbeddingService` | A typo fix costs one embedding call, not forty |
| **pgvector HNSW with company pre-filtering** | `PgVectorIndex` | recall@10 = 1.000, p95 9.9ms at 10k vectors / 20 tenants |
| **Five daily rollup tables** | `reporting-consumer` | Reports read pre-summed rows instead of scanning `conversations`/`messages` |
| **JWT-embedded permissions** | `AuthContext` | Zero DB round-trips per permission check |
| **Two partial, pre-sorted composite indexes** | `ConversationRepository`/`CustomerRepository.list_for_company` | `EXPLAIN ANALYZE` confirmed the separate `Sort` node disappears entirely |
| **`--workers 4` uvicorn in production** | prod overlay | ~44% higher throughput at the same concurrency vs a single dev worker |
| **nginx dynamic DNS re-resolution** | Both configs | Coarse load distribution across `--scale backend=N`. **Honestly documented as DNS rotation, not per-request balancing** — a real orchestrator is the next step |
| **Chunk-level retrieval collapsed to articles** | `KnowledgeRetrievalService` | Bounded result sets; avoids one long manual crowding out four articles |

**A measured limitation, documented rather than hidden.** At
concurrency=20, p50 latency rose from 30–45 ms (concurrency=3) to
190–370 ms with throughput barely rising — the signature of a saturated
single dev-mode uvicorn worker, not slow application code. The sandbox has
2 CPU cores shared across 18+ containers, so absolute numbers are not
production-representative; the qualitative finding (worker count matters;
0% error rate under load) is.

**`messages` table partitioning** is written up as a ready-to-execute
playbook rather than applied. Partitioning a near-empty table is pure risk
for zero benefit, and a migration that does nothing against near-empty
data cannot be verified the way every other migration here has been.

---

## 33. Every security mechanism

### Authentication

- **JWT access tokens**, 15 min, HS256, decoded with an **explicit
  algorithm allowlist**.
- **Individually-revocable refresh tokens**, 30 days, rotated on refresh,
  **Redis-backed allowlist** — so a single session can be killed.
- **bcrypt** password hashing with a strength policy (10 chars, letter +
  digit), applied identically at registration, agent creation, admin reset
  and self-service change — one validator, no second policy invented.
- **Password changes revoke every refresh token** for the affected user;
  self-service also revokes the session making the request.
- **Email verification tokens** as a distinct `TokenType`.
- **CSAT survey links** as a distinct conversation-scoped `TokenType`,
  14-day life — deliberately longer than a session token because it is
  messaged to a customer rather than kept alive by an active session.

### Authorization

- **RBAC** with a seeded permission catalog (`domain/rbac.py`, a pure leaf
  that imports nothing), `Role`/`Permission`/`RolePermission`/`UserRole`.
- **Permissions embedded in the access token** — no per-request DB round
  trip. The accepted tradeoff: a permission change takes effect within the
  15-minute access-token window.
- **Two exceptions that are re-read from the database every request**,
  because both are account-state decisions an operator expects to take
  effect immediately: the **platform-admin flag**, and **company
  suspension** (`_assert_company_active`, on every permission-gated
  route).
- **Owner is granted every permission and cannot be deleted or have its
  permissions edited.**
- **Permission splitting by blast radius** — `memory.read` / `.manage` /
  `.erase`, the last Owner-only.

### Transport & headers

- **`SecurityHeadersMiddleware`** — `X-Frame-Options`,
  `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`
  always; **CSP + HSTS in production only**, since `/docs`/`/redoc` (real
  HTML) only exist outside production.
- **A startup-time guard rejecting a CORS wildcard origin combined with
  `allow_credentials=True`.**
- **`/docs`, `/redoc` return 404 in production.**
- **`/metrics` restricted to private IP ranges in `nginx.prod.conf`** — it
  was previously publicly exposed with no restriction, leaking
  per-endpoint request-rate and latency data.

### Secrets

- **Application-layer encryption for channel and ERP credentials**, with
  `credentials_encryption_key` **deliberately separate from
  `jwt_secret_key`** so rotating one never invalidates the other.
- **Credentials are write-only** — never echoed on `GET`. A
  server-generated `webhook_secret` is returned exactly once, from the
  create response.
- **`redact_credentials()` / `safe_health_check()`** at every boundary
  where provider error text becomes a stored or returned string.
- **The platform SMTP password is write-only.**

### Input & injection

- **No raw-SQL injection surface** — SQLAlchemy parameterised queries
  exclusively.
- **No XSS surface** — pure JSON API, no HTML rendering.
- **No CSRF surface** — bearer-JWT only, zero cookies.
- **Attachment allowlist** by content type and size, applied at *both* the
  upload endpoint and the ingest consumer.
- **Signature verification on every inbound webhook**, per provider
  (Meta's HMAC-SHA256, Twilio's HMAC-SHA1-over-the-full-URL, ERPNext's
  custom header secret).
- **`public_base_url` is a fixed setting, not derived from
  `X-Forwarded-*`.** The backend port is reachable directly alongside
  nginx, so trusting client-supplied forwarded headers for a
  signature-relevant URL would be spoofable.

### Rate limiting

- Redis fixed-window on `/auth/register`, `/auth/login`, `/auth/refresh`,
  `/auth/logout` and the public CSAT-respond endpoint.
- **Per-user (not per-IP) on every `/ai/*` endpoint**, because AI calls
  carry real external cost and several agents can share one office IP.

### Prompt-injection and poisoning defence (Stage 2/3)

- A fact supported only by customer-authored content **cannot pass
  `CANDIDATE`**, whatever the arithmetic says. *Defeated by a counter, not
  by detection.*
- Corroboration claims must be **backed** by an agent id or a source id.
- `promise_made` requires human confirmation — "we'll refund you by
  Thursday" is a commitment with financial and legal consequences, and a
  component extracting it from a hedged sentence would create an
  obligation nobody made.
- Learning **excludes machine-written turns before extraction**, and
  reports the feedback ratio to the operator.

### Dependency posture

A `pip-audit` scan found 27 vulnerabilities across 8 packages. Patched:
`python-jose` (JWT-bomb + algorithm-confusion, security-critical),
`orjson`, `python-multipart`, and `aiosmtplib` — *the one genuinely
exploitable finding: unsanitised CRLF in customer-supplied email addresses
reaching raw SMTP commands.* Removed the unused `black` dependency
entirely rather than patching a CVE in dead weight.

Deferred **with explicit justification, not silently**: a
`starlette`/`fastapi` major bump (its own project), a `pytest` major bump
(dev-only), and the `ecdsa` Minerva timing CVE (**no fix exists upstream;
confirmed not exploitable — this platform only ever signs JWTs with
HS256**).

Written up in `docs/security/hardening.md`,
`docs/security/owasp-asvs-checklist.md`,
`docs/security/pentest-checklist.md`.

---

## 34. Every tenant-isolation mechanism

Multi-tenancy here is **row-level within one schema**, and it is enforced
at five independent layers.

| Layer | Mechanism |
|---|---|
| **1. Token** | The access token carries `company_id`. A **platform** token carries none, and `get_current_auth` rejects it from every tenant endpoint — once, rather than relying on ~100 endpoints to notice |
| **2. Repository signature** | `company_id` is a required keyword argument on every read. A cross-tenant query is hard to *write*, not merely wrong to write |
| **3. Vector search** | `company_id` is a required kwarg on `VectorIndex.search` — **there is no way to express a cross-company search**. Critical because an ANN index ranks *before* predicates apply |
| **4. Second predicate on hydration** | `KnowledgeRetrievalService` re-filters by company when loading articles found by retrieval — deliberately the second place company scoping is enforced |
| **5. Company state check** | `_assert_company_active` on every permission-gated route: a suspended or deleted company is refused immediately, not after the token expires |

**Additional tenant-scoped behaviours:**

- Every table carries `company_id`, including all four Learning tables and
  all four Memory tables.
- **Cross-tenant references in an observation are refused, not filtered**
  (`TenantMismatchError`, **I-1**) — because a cross-tenant reference
  reaching the envelope means an adapter is wrong, and silently dropping
  it would hide that.
- **Erasure is company-scoped**: erasing a customer in one company does
  not touch another company holding the same customer id. There is a test
  for exactly this.
- **Per-company embedding providers mean per-company indexing batches** —
  indexing a mixture under whichever provider was built first would write
  vectors under the wrong model name and make them silently
  unretrievable.
- **Nothing learns across tenants.** Non-negotiable, stated in the engine
  design and true by construction: there is no cross-company read path
  anywhere in Knowledge, Memory or Learning.
- **Tenant-fair sweep rotation** — the memory ageing sweep serves each
  company in turn rather than draining a global queue.
- **Feature entitlements are per company** and applied at router
  registration.
- **Platform admins see cross-tenant *metadata*, not tenant content** —
  the platform-users router declares the read-only gate and the
  tenant-content boundary once per file instead of once per route.

**Measured, not assumed:** the pgvector harness found **0 cross-tenant
rows** in ANN results across 40 queries with the tenant under test holding
5% of a 10,000-vector index, and **0/40 queries returning nothing** for
that small tenant.

---

## 35. Every replay / idempotency mechanism

At-least-once delivery makes replay the **normal case**, not an edge case.
Every consumer is idempotent, and each by a different mechanism suited to
what it writes.

| Path | Mechanism | Why that one |
|---|---|---|
| Outbox relay | `dispatched_at` + `SKIP LOCKED` claim + `attempts` cap | Overlapping relays claim disjoint batches; a poison row is bounded |
| Conversation ingest | `messages.external_message_id` lookup before insert | The channel's own id is the natural key |
| IMAP poll | **IMAP's `\Seen` flag is the tracker** | No separate cursor table to drift |
| AI Autopilot | `Conversation.autopilot_last_handled_message_id` | Guards both a duplicate reply and a duplicate handoff notification |
| ERP sync | Unique `ErpCustomerLink` | Sync is naturally once-per-customer |
| Usage metering | One immutable `billable_events` row per message, DB-enforced | The meter must not be able to double-charge |
| Billing period close / invoice run | Idempotent by state — a closed period is not re-closed | Hourly sweeps mean the operation runs constantly |
| **Memory re-observation** | `UNIQUE (fact_id, source_type, source_id)` on `memory_evidence` | **A replay that inflated the counters would inflate exactly the numbers confidence is computed from** |
| **Memory contradictions** | Same shape, same constraint on `memory_contradictions` | **B2** — a redelivered contradiction was demoting a true fact |
| **Memory counters** | Recomputed from evidence, never incremented | An increment is wrong the moment erasure deletes evidence |
| **Memory recency** | `last_observed_at` advanced only inside `if evidence_added` | **B1** — a replay was inflating confidence 4.7× on nothing |
| **Learning observation** | `UNIQUE (source_id, pipeline_version)` | Two rows for one conversation would double every count clustering depends on |
| **Learning refs & features** | Updated in place; no duplicate refs | A re-assembly must change nothing |
| **Learning runs** | `UNIQUE (company_id, run_type, pipeline_version, window_start)` | Two workers cannot both claim one window — exactly the redeploy-overlaps-a-sweep case |
| Knowledge indexing | Content hash per chunk | A re-index pays only for what changed |
| Notification dispatch | `email_dispatched_at` / `push_dispatched_at` null-checks | The sweep is the retry |
| Migrations | `INSERT ... ON CONFLICT (code) DO NOTHING` on permission seeds | Six later migrations hardcode permissions the first one already seeds from the live catalog |

### Versioned replay

`pipeline_version` is the deliberate replay boundary for Learning. Because
it is part of the unique key, **version 2 writes alongside version 1
rather than over it**, and the two generations can be compared before
either is trusted. That is not theoretical — phase 1.5 bumped
`PIPELINE_VERSION` to **2** and re-observed the corpus rather than
overwriting it, so the old and new readings sit side by side.

`replayed` on `GET /intelligence/health` counts superseded generations.
**It stays at zero through ordinary redelivery, which is what makes it
worth watching.**

The operator-triggered *windowed replay endpoint* is deliberately deferred
to phase 2: replay **safety** is built; the **trigger** belongs with the
phase that has something to replay into. In phase 1 a replay is a version
bump and a re-consume — a deploy-time act.

---

## 36. Every observability component

### Metrics

| Component | Scrapes |
|---|---|
| `prometheus` | Everything below |
| Backend `/metrics` | FastAPI instrumentation — request rate, latency histograms, status codes |
| `postgres-exporter` | `pg_up`, connections, transactions, locks |
| `redis-exporter` | `redis_connected_clients`, memory, ops |
| RabbitMQ built-in plugin | `rabbitmq_queue_messages_ready`, consumers, publish rates |
| `celery-exporter` | `celery_task_succeeded_total`, `celery_task_failed_total`, `celery_task_runtime_bucket` |

`celery-exporter` needs two Celery config flags
(`worker_send_task_events`, `task_send_sent_event`) — **without them
Celery never publishes task lifecycle events at all and the exporter's
`/metrics` stays permanently empty.**

### Dashboards

Five Grafana dashboards: Backend API, PostgreSQL, Redis, RabbitMQ &
Celery, Logs. **Every metric name was verified against real Prometheus
query results before going into a panel.**

### Alerting

Six Grafana unified-alerting rules, provisioned and confirmed loaded via
Grafana's own API after a real restart (not "the YAML looks right"): high
5xx rate (>5%), high p95 latency (>2s), Postgres down, Redis down,
RabbitMQ queue backlog (>1000 ready for 10+ min), Celery task failure
rate.

**The contact point is a deliberately obvious placeholder webhook.** Which
Slack channel, PagerDuty key or email address should receive these is a
business decision this codebase cannot make for itself. Rules and routing
are fully wired; plugging in a real destination is a one-line change.

### Logs

`core/logging.py` emits JSON in production/staging, plain colored text in
development. Promtail extracts **only `level`** as an indexed Loki label
(5 values) — deliberately **not** `logger` (~90 values), per Loki's own
cardinality guidance. Everything else stays queryable via LogQL's `| json`
without being indexed.

### Health

- `GET /health` — liveness. "The process is up," nothing more.
- `GET /health/ready` — checks **Postgres, Redis and RabbitMQ**, returning
  503 with a per-dependency breakdown, each bounded by a 3-second timeout
  so a hung dependency cannot hang the health check itself. The `backend`
  container's Docker healthcheck points here.
- `GET /platform/health/scheduler` — **the scheduler monitor**. Every
  sweep records a `scheduler_runs` row, so a job that silently stopped
  running is visible. (This exists because a billing sweep once failed
  quietly.)
- `GET /memory/status` — memory recompute backlog.
- `GET /intelligence/health` — the five Learning counters plus the
  feedback ratio.
- `GET /knowledge/index-status` — chunks embedded, articles pending,
  articles failed.

### Request latency

nginx's `timed` log format records **two** timings:

- `rt=$request_time` — wall clock, first client byte to last byte written.
  What the user actually waited.
- `urt=$upstream_response_time` — the backend alone.

Logging both is the point: a large `rt` beside a small `urt` means the
client link is the cost; the two rising together means the backend is
genuinely slow. **One number cannot separate those cases**, and picking
only `$request_time` would have made every mobile-network user look like a
backend problem.

`pg_stat_statements` is loaded with `track=all` and `max=5000`. It cannot
be enabled at runtime, so it lives in the compose command rather than a
migration.

### Explainability as observability

The platform's most distinctive observability surface is not metrics —
it is the decision logs: `routing_decisions` (including
`POLICY_EVALUATED` rows), `conversation_ownership`,
`conversation_sla_clocks` transitions, `workflow_runs`,
`channel_connection_logs`, `memory_evidence`,
`memory_confidence_samples`, `learning_observation_refs`,
`learning_runs`, `pricing_audit_log`, `financial_audit_events`, and
`audit_logs`.

### Backups

`scripts/backup_postgres.sh` (`pg_dump`, gzip, timestamped, retention
pruning), `scripts/restore_postgres.sh` (typed confirmation of the target
database unless `--force`), and `scripts/verify_backup_restore.sh` — **a
genuine restore drill** that restores the most recent backup into a
throwaway scratch database, sanity-checks it, then drops it. All three
were run against the real stack.

### CI

`.github/workflows/ci.yml` — backend lint (ruff + mypy), backend test,
frontend lint (eslint/prettier/`tsc -b`), frontend test, Docker build for
backend and nginx+SPA images, Trivy image scan (advisory), and a
**documented placeholder deploy job** gated on version tags that
intentionally does not deploy anywhere.

### The incident that shaped the task layer

All Celery beat tasks cache their `AsyncEngine` at module level, but each
invocation calls `asyncio.run()`, which creates a **brand-new event
loop**. An asyncpg connection is bound to the loop that opened it, so
`pool_pre_ping` trying to reuse a connection pooled during a previous
(now-closed) loop **crashed** — pre_ping recovers from "the connection
died", not "the connection belongs to a different event loop entirely."
50+ occurrences in three minutes.

Fixed identically in every task: `engine.dispose()` in a `finally` block.
That closes pooled connections but not the lightweight `AsyncEngine`
object, so the next invocation still takes the "already cached" branch —
it just opens fresh connections against the current loop. Zero occurrences
across a 130-second window afterwards.

**The consumers were never affected** — each calls `asyncio.run(main())`
exactly once for the entire process lifetime. `test_task_engine_disposal.py`
now asserts every task does this.

---

# Part V — Honest state

## 37. Every current limitation

Grouped by severity of consequence, not by area.

### Intelligence layer

| # | Limitation | Consequence | Recorded as |
|---|---|---|---|
| 1 | **`AnswerVerifier` does not exist.** Stage 1 shipped retrieval only, not steps 0–7 of the reasoning pipeline | *"Official knowledge wins"* is enforced on the Memory side (contradiction demotes) but **advisory on the answer side** — nothing refuses a reply whose restricted claim cites no authoritative source | **B8** |
| 2 | **Knowledge versioning is designed, not built.** `knowledge_article_versions` does not exist; `knowledge_chunks.article_id` points at the mutable article | A citation is not reproducible — "what did this say in March?" cannot be answered. Deferred *until Learning cites knowledge*; it is a table, a pointer and an FK move | **B9** |
| 3 | **`retrieval_traces` does not exist** | Stage 3's gap detection loses its retrieval half ("retrievals that returned nothing") and keeps only "an agent answered without citing". Traces and the verifier are the same instrument, so B8 and B10 land together | **B10** |
| 4 | Learning phase 1 **proposes nothing** — no clustering, no candidates, no suggestions, no model calls | The intelligence layer currently produces observation only | By design |
| ~~5~~ | ~~**`conversation.reopened` is bound and published by nothing.**~~ **Fixed in 1.1.0** — both reopen paths publish it, the signals consumer reads `reopened_at`/`ended_at` off the payload, `attach_outcome` returns a no-longer-settled observation to `pending`, and a static guard now fails the build for any binding without a publisher | Was: a conversation reopened after settling kept an observation claiming first-contact resolution, with every counter looking healthy | **Found while writing this handbook; fixed in [1.1.0](../releases/1.1.0.md)** |
| 6 | Learning cannot separate a workflow close from a human close on available data | An unassigned close answers `unknown`, which is not attributable — so some genuinely human resolutions are excluded from outcome attribution | Documented |
| 7 | Tier 2 (embedding) features are absent from observations | Observations cannot be placed against clusters until phase 2 | Charter deviation 1 |
| 8 | No operator-triggered windowed replay endpoint | A replay is a version bump plus a re-consume — a deploy-time act | Deferred to phase 2 |
| 9 | Conversation Memory has **no distillation step** — nothing turns working memory into evidence-backed facts | Working memory expires with the conversation and contributes nothing | By design (Stage 2 builds the store, not the judgement) |
| 10 | Memory has **no semantic recall** — `OWNER_MEMORY_FACT` is declared for the polymorphic `embeddings` table but nothing embeds a fact | Facts are found by filter, not by similarity | Ready when needed; no schema change required |
| 11 | Memory has **no `pipeline_version` equivalent** for a model migration | Knowledge has a re-indexing path; memory does not | Named in the freeze review |
| 12 | `Company Behavior` does not exist | "Did we follow our own procedure?" is unanswerable | Reserved, deliberately |
| 13 | Voice Constraints and Voice Profile are designed, not built | Generated replies have no enforced compliance wording and no per-(channel, segment, situation, language) register | Ships with the generator |

### Knowledge / retrieval

| # | Limitation |
|---|---|
| 13 | **The lexical halves differ by dialect** — PostgreSQL `word_similarity` trigram vs SQLite substring. Fusion, ranking and tenant isolation are tested on SQLite; trigram scoring itself is verified against real PostgreSQL only |
| 14 | **No frontend for `GET /knowledge/search`.** The admin article table still uses `GET /articles?search=` |
| 15 | **Backfill is the sweep.** A large corpus takes several minutes to become searchable after enabling a provider |
| 16 | **One embedding width per installation.** `EMBEDDING_DIMENSIONS` is a schema commitment; changing it needs a migration and a full re-index |
| 17 | Semantic retrieval is **off by default** (`embedding_provider="disabled"`) |

### Operations & infrastructure

| # | Limitation |
|---|---|
| 18 | **No TLS.** Confirmed live: nginx access logs showed real external IPs hitting port 80 over plain HTTP. Outside application code — a network/hosting-layer decision — but flagged, not theoretical |
| 19 | **Seven `change-me-...` placeholder secrets** in the live `.env` (`POSTGRES_PASSWORD`, `DATABASE_URL`, `RABBITMQ_DEFAULT_PASS`, `RABBITMQ_URL`, `MINIO_ROOT_PASSWORD`, `S3_SECRET_KEY`, `GF_SECURITY_ADMIN_PASSWORD`). Rotating `POSTGRES_PASSWORD` on an initialised cluster needs an in-database `ALTER USER` alongside the file edit |
| 20 | **No secrets manager** — environment variables only |
| 21 | **Backups are not shipped off-host** |
| 22 | **MinIO / attachment storage has no backup at all** |
| 23 | **The alert contact point is a placeholder webhook** |
| 24 | **The CI deploy job is a documented placeholder** — no real target |
| 25 | nginx gives **DNS-rotation load distribution, not per-request balancing** |
| 26 | `messages` partitioning is a playbook, not applied |
| 27 | **No `pg_stat_statements`-driven query alerting** — the extension is loaded, nothing alerts on it |
| 28 | **Outbox pruning is an operational task, not built.** The partial index keeps the hot path cheap regardless of table size, but dispatched rows accumulate |

### Product surface

| # | Limitation |
|---|---|
| 29 | **Identity Phase 1 is designed, not built.** Profile/email lifecycle/verification are still split across auth and verification services; `VerificationService.verify()` writes `Company.verified_at` (**D3**) |
| 30 | Frontend coverage is the golden path plus Sprint 2 items; several backend features have no UI (Workflows, Queues, Routing Rules, Knowledge Base authoring, Quick Replies, standalone Notes, Audit Log viewer are partial or absent) |
| 31 | **Outbound MMS is an explicit scope boundary** — Twilio needs a publicly fetchable media URL a private MinIO bucket does not have. `send_message` raises rather than silently dropping attachments; inbound MMS works fully |
| 32 | **No sender display name from Messenger/Instagram** webhooks — a documented future enrichment |
| 33 | **Attachment virus scanning is an unimplemented extension point** |
| 34 | **No webhook auto-registration and no OAuth** for channel connection — credentials are pasted |
| 35 | **No SSRF host/IP restriction** on operator-supplied credential hosts — deferred as broader than the phase that found it |
| 36 | Credential validation errors use a `400` flat string where the rest of the API uses `422` field-level — a known convention inconsistency |
| 37 | `D1`/`D2` — SLA health and operational state are each **expressed twice** (Python + SQL). Accepted duplications, kept only because a drift test runs every case through both paths. Both have already caught real bugs |

### Testing

| # | Limitation |
|---|---|
| 38 | The suite runs on **SQLite + fakeredis**. Real-broker and real-PostgreSQL behaviour is verified manually against docker-compose — the standard this codebase has held since M10, and the gap that let the `GUID`/relay incident survive |
| 39 | No real browser in the sandbox, so some frontend paths are verified by byte-level request reproduction against the live backend rather than by clicking |

### A binding with no publisher — found while writing this handbook, fixed in 1.1.0

Kept in full rather than deleted, because it is the platform's own
canonical failure shape and the reason a new guard exists.

`learning_signals_consumer.py` binds four keys, and its own comment names
this one as the most important:

> *"`conversation.reopened` is the one that matters most: it invalidates a
> resolution outright, and an observation that kept claiming
> first-contact resolution after a reopen would be teaching the platform
> that a failure was a success."*

**Nothing published it.** Two paths reopen a conversation, and neither
emitted that event:

1. **A new inbound message on a resolved/closed conversation.** The ingest
   consumer flipped `status` to `WAITING` and cleared `closed_at`
   **inline**, without going through `ConversationService.update`, so no
   status event was published at all.
2. **An agent changing the status back.** `ConversationService.update`
   published `conversation.{status.value}` **only for terminal statuses** —
   by design, per its own comment. A transition *out* of a terminal status
   emitted `conversation.updated` and nothing more specific.

**Consequence.** An observation assembled at resolution kept its
provisional `resolved / first_contact_resolution` outcome through a
reopen, then settled as `ready` 72 hours later — because the sweep
promotes on elapsed time and deliberately re-derives nothing. Learning's
corpus recorded some failures as successes. In phase 1 that costs nothing
but accuracy in a read-only table; **in phase 2 those rows become
clustering input, and the error would be invisible because every counter
would still look healthy** — the exact class of failure the anti-feedback
machinery exists to prevent.

**Why no test caught it.** `test_learning_platform.py` exercised the
handler against a **fabricated event dict** containing
`"event_type": "conversation.reopened"`. The handler was correct; the
handler had never been reachable. This is the identical gap that let the
`GUID`/relay incident run for months: *a test that exercises a handler is
not a test that exercises the pipeline.*

**A second bug sat behind the first.** Even with the event published, the
consumer never set `reopened_at` on its `OutcomeInputs`, so
`conversation_outcome.derive` would have answered `reopened=False` for the
one event whose entire purpose is to say a resolution did not hold.
Publishing alone would have produced an event that still changed nothing.

### How it was fixed

| Change | Where |
|---|---|
| Publish `conversation.reopened` on leaving a `FINISHED` status | `ConversationService.update()` |
| Publish it on the customer-message reopen path, reading `closed_at` **before** clearing it | `conversation_ingest_consumer` |
| Read `reopened_at`/`ended_at` off the payload; a malformed timestamp answers `None` rather than raising | `learning_signals_consumer` |
| Return a no-longer-settled observation to `pending`, and clear `settle_due_at` when the conversation is not resolved | `LearningObservationService.attach_outcome()` |
| Replace `f"conversation.{status.value}"` with an explicit `_TERMINAL_EVENT` mapping | `ConversationService` |

`ended_at` is carried **by value** on the payload because the ingest path
clears the only column it lives in — by the time any consumer reads the
event, when the conversation had ended is a fact only the publisher still
holds.

The `attach_outcome` change closes a defect the reopen signal exposed
rather than caused: without it, a reopen produced a row that was
simultaneously `ready` and unsettled — a state the settle sweep (which
claims on `state == pending`) could never correct — and a settle deadline
computed from the resolution the conversation had just lost, which would
have had the sweep promote it straight back.

### The guard, so it cannot recur

`tests/unit/test_bound_routing_keys_have_publishers.py`. Every
non-wildcard routing key in any consumer's `ROUTING_KEYS` must appear as a
string literal in some **other** module under `src/`. Static, like the
three existing AST guards, and for the same reason: *a behavioural test
covers the paths somebody thought to write; this covers the bindings
nobody has written yet.*

Three properties, each deliberate:

- **Bindings are read by importing the consumer, not by parsing it** —
  `notification_consumer` computes its keys from a registry at import
  time, so a source-level read would see a function call rather than the
  keys a running consumer binds.
- **Docstrings are excluded from the publisher search.** A routing key
  *named in prose* is exactly what `conversation.reopened` had; counting
  it would have made the guard pass on the bug it exists to catch.
- **The guard's own coverage is asserted**, so it cannot pass by having
  nothing to check — which reads exactly like coverage.

Making every event type a literal in the source was a precondition for
this, and is worth having on its own: an event name assembled at runtime
is invisible to a reader, to a grep, and to a static guard.

**Verified by watching it fail** with the two publishers temporarily
renamed, and pass once restored. A guard nobody has watched fail is a
guard nobody knows works.

---

## 38. Every planned future phase

### The Company Intelligence Engine build order

| Stage | Contents | Status |
|---|---|---|
| **1 — Retrieval** | Embeddings, chunking, vector index, hybrid retrieval, index sweep | ✅ **shipped** |
| **2 — Memory foundation** | `MemoryManager`, the pure confidence/lifecycle/identity modules, evidence, erasure, Conversation Memory | ✅ **shipped and stabilised** |
| **3 — Learning** | Phase 1 Observe ✅ · Phase 2 Cluster & detect · Phase 3 Candidates · Phase 4 Suggestions | 🔄 **Phase 1 shipped** |
| **Reasoning pipeline** | Steps 0–7 including `AnswerVerifier`, `RetrievalOrchestrator`, `IntelligenceContext`, gap detection, `retrieval_traces` | ⛔ not built — **B8/B10 land here** |
| **Experience** | Both corpora (succeeded *and* failed), clustering, stratified effects, negative-experience penalty | ⛔ tier exists; causal machinery not built |
| **Suggestions** | Generation, dedupe, state machine, review UI | ⛔ |
| **Graph** | Edge projection and inference, graph retrieval | ⛔ |
| **Analytics** | Every intelligence metric | ⛔ |

**Two ordering decisions carry weight and should not be reversed:**

- **Verification before learning.** *Learning without verification produces
  a store nobody can trust and no instrument for noticing; verification
  without learning is still a strictly better product than today. If the
  sequence has to be cut short, cut it after verification.*
- **Memory before learning.** The exclusive-write invariant is cheap to
  start with and expensive to retrofit.

### Learning phases 2–4 (specified, not built)

| Phase | Adds | Cost tier |
|---|---|---|
| **2 — Cluster & detect** | Intent clustering, similarity to existing clusters, trends, gap scan, contradiction detection. Tier 2 features join the envelope. `intelligence.manage` gains meaning (dismiss a candidate, replay a window) | Tier 2 — cheap |
| **3 — Candidates** | Knowledge candidates and memory candidates, with per-candidate judgement | Tier 3 — metered |
| **4 — Suggestions & review** | Suggestion generation, dedupe, state machine, human review queue. **This is where candidates become facts, through `MemoryManager`** | Tier 4 — per candidate, never per observation |

**The gate on phase 2 is a number phase 1 exists to produce:** the
feedback ratio. If too much of what the platform observes is content the
platform itself wrote, phase 2 is not safe to switch on.

### Knowledge, next steps

1. `knowledge_article_versions` + move `knowledge_chunks.article_id` to
   the version (**B9**) — a precondition on Learning's contradiction
   detector.
2. `retrieval_traces` (**B10**) — lands with the verifier.
3. `KnowledgeClass.VOICE_CONSTRAINT`, restricted, requiring
   `knowledge.approve_restricted`.
4. Retraction and **emergency withdrawal** — one authorised human, no
   queue, effective on the next retrieval. It exists because *a published
   price that is wrong is being quoted right now, and a process requiring
   a second reviewer before it can stop is a process that will be bypassed
   by an engineer with database access — which is worse in every way,
   including the audit trail.*
5. A frontend for `GET /knowledge/search`.

### Memory, next steps

1. Semantic recall over facts (`OWNER_MEMORY_FACT` is already declared —
   no schema change).
2. Distillation: working memory → evidence-backed facts, gated on
   `KNOWLEDGE_LEARNING`.
3. `ExperienceService` — stratified, baseline-relative effects, writing
   **through** the Manager (it holds no write path of its own, because the
   whole point of declining Experience as a peer domain was that erasure
   has one owner).
4. Per-fact-type confidence thresholds, calibrated against real data.
5. A `pipeline_version` equivalent for memory model migration.

### Reserved, deliberately unscheduled

**Company Behavior.** Named practices, SOPs as executable procedures, and
the mapping from a practice to the configuration that enforces it. The
condition on building it is recorded: **it must become the single writer
of the configuration it owns, and the direct authoring path must be
withdrawn in the same change.** Its hard part is a migration of five
existing configuration surfaces, and that cost belongs in the estimate on
the day somebody proposes it.

The capability that only exists once both Experience and Behavior exist is
worth naming, because it is the argument for eventually building it:

> **Experience ⨯ Behavior = practice drift.** Behavior states the
> practice. Experience observes what agents actually do. The difference is
> *"the organization is not operating the way it says it does"* — a
> finding no module in this platform can produce today, and one no amount
> of reporting on either half alone will surface. It is also the honest,
> non-punitive framing of agent-attributed learning: **the finding is
> about the practice, not the person.**

### Product roadmap outside intelligence

- **Identity Phase 1** — split account verification from company
  verification, closing `D3`; account lifecycle, protected accounts,
  Identity Health, restrictions that explain themselves.
- **M37 polish** — full `vitest-axe` sweep, responsive/mobile pass, RTL
  verification, and the remaining CLAUDE.md features without UI.
- **Channel spec tiers 2+** — webhook auto-registration, token-refresh
  awareness, OAuth, full SSRF restriction.
- **Real experiments.** Where a company runs enough volume, randomising
  between two candidate responses and measuring is the only thing that
  turns Experience's associations into causal claims. Deliberately not
  designed yet.

### Open questions, named rather than answered

- **Conversation Memory across conversations.** A customer opening a
  second chat about the same order — one working context or two? Leaning
  two, with Customer Memory carrying the continuity, because merging live
  working state across conversations creates a shared mutable object two
  agents can read simultaneously.
- **Confidence thresholds per fact type.** `terminology` should reach
  `TRUSTED` on far less evidence than `promise_made`.
- **Whether Organizational Memory can outlive erasure of every supporting
  customer.** Leaning toward retaining the fact and marking its evidence
  irrecoverable — **but this is a question for counsel, not
  architecture.**

---

# Part VI — Diagrams and lifecycles

## A. Complete architecture diagram

```
                                   ┌──────────────────────────────────────┐
   CUSTOMERS                       │            AGENTS / ADMINS           │
   WhatsApp · Telegram             │      React 19 + TS + MUI SPA         │
   Messenger · Instagram           │   (Vite · Redux Toolkit · RQuery)    │
   Email · SMS · Web Chat          └───────────────────┬──────────────────┘
        │                                              │
        │ webhooks / WS                                │ HTTPS + WS
        ▼                                              ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │                              NGINX  (unified origin)                    │
  │  /api/ → backend:8000 (dynamic DNS re-resolve) · / → SPA · /metrics 🔒  │
  └───────────────────────────────┬────────────────────────────────────────┘
                                  │
  ┌───────────────────────────────▼────────────────────────────────────────┐
  │                      FastAPI  (uvicorn --workers 4)                     │
  │                                                                         │
  │  api/v1/  313 routes + 2 WS   ·  deps.py = the only DI touchpoint      │
  │  ┌───────────────────────────────────────────────────────────────────┐ │
  │  │ APPLICATION   84 service modules                                    │ │
  │  │  Auth · Company · Customer · Channel · Conversation · Ownership    │ │
  │  │  Routing · Assignment · SLA · Workflow · Notification · AI         │ │
  │  │  Knowledge+Retrieval · MemoryManager · LearningObservation         │ │
  │  │  Reporting · Billing · Platform · ERP · Inspector · Search         │ │
  │  ├───────────────────────────────────────────────────────────────────┤ │
  │  │ DOMAIN  (framework-free · no I/O · no clock)                       │ │
  │  │  rbac · policies · execution_context · service_context             │ │
  │  │  customer_context · ownership · lifecycle · sla · business_hours   │ │
  │  │  conversation_outcome · routing_decisions · workflow_condition     │ │
  │  │  chunking · retrieval(RRF) · vector_index · embedding_provider     │ │
  │  │  memory · memory_confidence · memory_lifecycle · memory_identity   │ │
  │  │  memory_ports · conversation_memory                                │ │
  │  │  learning_observation · learning_features                          │ │
  │  │  money · pricing · ledger · invoicing · tiers                      │ │
  │  ├───────────────────────────────────────────────────────────────────┤ │
  │  │ INFRASTRUCTURE  58 repositories · 46 ORM models                    │ │
  │  │  channels/{providers,gateways} · ai/providers · embeddings         │ │
  │  │  vector/{pgvector,exact} · events/{outbox,relay,consumers}         │ │
  │  │  storage(MinIO) · email · erp · push · reporting · tasks           │ │
  │  └───────────────────────────────────────────────────────────────────┘ │
  └───┬──────────────┬──────────────┬───────────────┬────────────────┬─────┘
      │              │              │               │                │
      ▼              ▼              ▼               ▼                ▼
 ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌────────────┐
 │POSTGRES │   │  REDIS   │   │ RABBITMQ │   │   MINIO   │   │ PROMETHEUS │
 │pgvector │   │          │   │          │   │           │   │  GRAFANA   │
 │  pg17   │   │ sessions │   │ topic ex │   │attachments│   │  LOKI      │
 │93 tables│   │ rate lim │   │ 12 queues│   │  logos    │   │  PROMTAIL  │
 │+ HNSW   │   │ pub/sub  │   │ + celery │   │           │   │            │
 │+ trgm   │   │ WORKING  │   │          │   │           │   │            │
 │         │   │ MEMORY   │   │          │   │           │   │            │
 └────▲────┘   └──────────┘   └────▲─────┘   └───────────┘   └────────────┘
      │                            │
      │  outbox relay (5s)         │  topic exchange  blinkengage.events
      └────────────────────────────┤
                                   │
  ┌────────────────────────────────▼───────────────────────────────────────┐
  │  12 INDEPENDENT CONSUMER PROCESSES  (durable queue each, manual ack)    │
  │                                                                         │
  │  audit-log(#)          workflow-engine(#)      conversation-ingest      │
  │  reporting(8 keys)     notifications(rules)    csat-dispatch            │
  │  ai-autopilot          autopilot-sla           usage-metering           │
  │  erp-sync              learning-observation    learning-signals         │
  └─────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  CELERY  worker + beat   ·  16 schedules                                │
  │  relay(5s) ai-pickup(10s) push(10s) email(30s) sla-sweep(60s)           │
  │  sla-breach(60s) imap(60s) knowledge-index(60s) ownership(300s)         │
  │  channel-health(300s) learning-settle(900s) memory-age(3600s)           │
  │  billing×4(3600s)                                                       │
  └─────────────────────────────────────────────────────────────────────────┘
```

## B. Complete event flow diagram

```
  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
  │  WEBHOOK   │   │ WS GATEWAY │   │  REST API  │   │ CELERY TASK│
  │ (7 channel │   │ (web chat, │   │ (agent     │   │ (sweeps)   │
  │  providers)│   │  agent)    │   │  actions)  │   │            │
  └──────┬─────┘   └──────┬─────┘   └──────┬─────┘   └──────┬─────┘
         │                │                │                │
         └────────────────┴────────┬───────┴────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  OutboxEventPublisher       │
                    │  .publish(DomainEvent)      │
                    │                             │
                    │  ONE ROW on the SAME        │
                    │  AsyncSession as the change │
                    └──────────────┬──────────────┘
                                   │  COMMIT  ← atomic: change + event
                                   ▼
                    ┌─────────────────────────────┐
                    │  event_outbox               │
                    │  partial idx WHERE          │
                    │    dispatched_at IS NULL    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  relay_outbox  (beat, 5s)   │
                    │  SELECT..FOR UPDATE         │
                    │        SKIP LOCKED          │
                    │  attempts < max_attempts    │  ← dead-letter guard
                    └──────────────┬──────────────┘
                                   │ orjson → persistent message
                    ┌──────────────▼──────────────┐
                    │  RabbitMQ TOPIC EXCHANGE    │
                    │     blinkengage.events      │
                    │     routing_key = type      │
                    └──┬───┬───┬───┬───┬───┬──────┘
      ┌────────────────┘   │   │   │   │   └──────────────┐
      │        ┌───────────┘   │   │   └────────┐         │
      ▼        ▼               ▼   ▼            ▼         ▼
 ┌─────────┐┌──────────┐┌───────────┐┌──────────┐┌────────────┐
 │audit-log││ workflow ││conversation││reporting ││notification│
 │   (#)   ││   (#)    ││  -ingest   ││ (8 keys) ││  (rules)   │
 │         ││          ││message.    ││          ││            │
 │→audit_  ││→workflow_││ received   ││→5 daily  ││→notificat- │
 │  logs   ││  runs    ││→Conversat- ││  rollups ││  ions      │
 │(redacted││          ││  ion/Msg   ││          ││            │
 │ bodies) ││          ││→routes     ││          ││            │
 └─────────┘└──────────┘└───────────┘└──────────┘└────────────┘
      ▼        ▼               ▼           ▼            ▼
 ┌─────────┐┌──────────┐┌───────────┐┌──────────┐┌────────────┐
 │  csat-  ││    ai-   ││ autopilot ││  usage-  ││  erp-sync  │
 │ dispatch││ autopilot││   -sla    ││ metering ││            │
 │conv.    ││message.  ││sla_warning││message.  ││customer.   │
 │resolved ││persisted ││sla_breach ││persisted ││ created    │
 │         ││          ││           ││message.  ││            │
 │→survey  ││→reply or ││→AI takes  ││ sent     ││→ERPNext    │
 │  link   ││  handoff ││  over     ││→billable ││  (no-op if │
 │         ││          ││           ││  _events ││   unconfig)│
 └─────────┘└──────────┘└───────────┘└──────────┘└────────────┘
      ▼                        ▼
 ┌──────────────────┐   ┌──────────────────┐
 │learning-         │   │ learning-signals │
 │  observation     │   │ csat.submitted   │
 │conversation.     │   │ conv.reopened    │
 │  resolved/closed │   │ conv.transferred │
 │                  │   │ conv.sla_breached│
 │→learning_        │   │                  │
 │  observations    │   │→attach late      │
 │  +features+refs  │   │  outcome, settle │
 └──────────────────┘   └──────────────────┘
     ▲  NEVER binds memory.* / learning.* / intelligence.*   (I-4)
     └────────────────────────────────────────────────────────────

  EPHEMERAL TIER (no outbox, no durability, fine to drop)
  ─────────────────────────────────────────────────────────
  RealtimePublisher → Redis PUB/SUB
     company:{cid}:conversation:{conv}:typing
     company:{cid}                             ← live message ticks
     └→ subscribed by  WS /ws/agent  and  WS /web-chat/ws/{id}
```

## C. Complete request lifecycle

An authenticated `PATCH /api/v1/conversations/{id}`, end to end.

```
 1  Browser
      Authorization: Bearer <access JWT>
      │
 2  NGINX
      timed log format: rt= + urt=
      proxy_pass http://$backend  (re-resolved every 10s)
      Upgrade/Connection headers present (so WS works on the same location)
      │
 3  CorrelationMiddleware
      X-Request-ID in or generated → bound to every log line in this request
      │
 4  SecurityHeadersMiddleware
      X-Frame-Options · X-Content-Type-Options · Referrer-Policy
      · Permissions-Policy   (+ CSP + HSTS in production only)
      │
 5  Prometheus instrumentation  (start timer)
      │
 6  Route match → dependency graph resolves
      │
      ├─ get_settings_dep       (lru_cached Settings)
      ├─ get_db_session         (AsyncSession, request-scoped)
      ├─ get_redis
      ├─ require_permission("conversations.manage")
      │     └─ get_active_auth
      │           └─ get_current_auth
      │                 · decode_token(expected_type=ACCESS,
      │                                algorithm allowlist)
      │                 · company_id claim present?  else 403
      │                    ("this is a platform admin account")
      │                 · AuthContext(user_id, company_id, permissions)
      │           └─ _assert_company_active
      │                 · Company deleted? → 401
      │                 · Company SUSPENDED? → 403
      │                 (re-read every request, not trusted from the token)
      │     └─ permission ∈ auth.permissions?  else 403
      │        (permissions come from the JWT — zero DB round-trips)
      │
      ├─ require_feature(...)   on gated routers only
      └─ build_conversation_service(session, ...)
            └─ core/wiring.py already asserted at BOOT that this factory
               produces a service with sla, ownership, events, realtime,
               attachments and the channel factory all present
      │
 7  Endpoint handler
      · Pydantic request schema validated (422 on shape errors)
      · service.update(company_id=auth.company_id, ...)
      │
 8  Application service
      · Repository read, ALWAYS company_id=...
      · Domain rules applied (pure, no I/O)
      · Ownership change?  → OwnershipService.transfer
      │     · append conversation_ownership row
      │     · project onto Conversation.assigned_agent_id
      · SLA-relevant?     → SlaEngine  (moves clock + writes decision row)
      · Policy-gated?     → RecordingPolicyEngine.evaluate
      │     · PolicyDecision (effect, reason, source, text)
      │     · POLICY_EVALUATED row into routing_decisions
      · events.publish(DomainEvent)  → one event_outbox row,
                                       SAME SESSION
      │
 9  session_scope commits
      Business change + ownership row + SLA transition + policy decision
      + outbox event  — all in ONE transaction. Any failure rolls back all.
      │
10  Response serialised through a Pydantic response schema
      · Write-only fields (credentials, secrets) structurally excluded
      │
11  Prometheus records status + duration; nginx logs rt/urt
      │
12  ── asynchronously, 0–5 s later ──
      relay → RabbitMQ → 12 consumers fan out
      (audit row, reporting rollup, workflow evaluation, notification,
       metering, learning observation if the conversation finished, …)
```

**Domain errors map deliberately.** `MemoryError_` subclasses are
`DomainError`, translated at the API boundary to a **400 telling the
caller what is wrong** — an unknown fact type, a subject/tier mismatch,
missing evidence are caller mistakes. A 500 would say the platform broke,
which it did not.

## D. Complete conversation lifecycle

```
  ① INBOUND ARRIVES
     webhook POST /webhooks/{cfg}   or   WS /web-chat/ws/{cfg}
         │
         ├─ provider.verify_signature(request)      ← per-vendor scheme
         ├─ provider.webhook(request) → InboundMessage DTO
         └─ publish  message.received               ← NOTHING PERSISTED YET
                                                       (no Conversation,
                                                        no Message)
                              │
                       outbox → relay → exchange
                              │
  ② conversation-ingest-consumer
         │
         ├─ resolve customer
         │     email → Customer.email
         │     everything else → customer_channel_identities
         │     new? → publish customer.created  (→ erp-sync-consumer)
         │
         ├─ get_by_thread(channel_config_id, external_thread_id)
         │     found?    → continue it
         │     not found → CREATE  +  publish conversation.created
         │
         ├─ external_message_id already ingested? → RETURN (idempotent)
         │
         ├─ validate attachments (content type + size), reject the rest
         ├─ INSERT Message (direction=INBOUND)
         ├─ status ∈ REOPEN_SET?  → status = WAITING, closed_at = NULL
         │     (back to the QUEUE — never straight to the previous owner)
         │
         ├─ publish  message.persisted
         │     → ai-autopilot-consumer, usage-metering-consumer,
         │       notification rules, reporting
         ├─ realtime.publish(company channel, "message_received")   ← Redis
         │
         └─ IF the conversation was just created → ③

  ③ ROUTE AND ASSIGN     (only ever for a brand-new conversation)
         │
         ├─ SERVICE RESOLUTION  (4 stages, each recording evidence)
         │     customer-selection → business-rules → fixed → fallback
         │     → bind conversation_context_bindings (append-only)
         │       + record a SERVICE decision
         │
         ├─ POLICY: ROUTING     (recorded)          denied → STOP
         │
         ├─ QUEUE SELECTION
         │     service names a queue?  → SERVICE_OWNS_QUEUE
         │     else RoutingEngine      → first matching rule by priority
         │     no queue?  → record the decision and STOP   (never silent)
         │
         ├─ conversation.queue_id · queue_entered_at · status = WAITING
         ├─ publish  conversation.queued
         │
         ├─ ConfigurationResolver.for_conversation
         │     ONE read → SLA targets AND AI policy,
         │     service → queue → company → platform, each tagged with tier
         │
         ├─ START THREE CLOCKS  (queue · first-response · resolution)
         │     targets COPIED onto the clock, not read through a join
         │
         ├─ OWNERSHIP → the QUEUE owns it   (reason NEW_CONVERSATION)
         │     "owned by the queue", never "unassigned"
         │
         ├─ queue missing / inactive? → record queue_unavailable, STOP
         │
         ├─ IF queue.autopilot_enabled:
         │     POLICY: AI_ENGAGEMENT  (recorded, fails closed)
         │       narrowest reason first:
         │         customer opted out → company off → no provider →
         │         service off → agent owns it → conversation finished
         │     allowed AND pickup_delay > 0?
         │         → ai_pickup_eligible_at = now + delay
         │         → record AI_DEFERRED,  engaged = False
         │         ("AI is a queue worker, not a first responder")
         │     allowed AND delay == 0?
         │         → autopilot_active, status = IN_PROGRESS
         │         → accept the queue clock
         │         → OWNERSHIP → AI_OWNER  (AI is an owner, not an absence)
         │         → record AUTOPILOT, RETURN
         │
         └─ ASSIGNMENT ENGINE
               narrow by queue required skills
               strategy: RoundRobin | LeastLoad
               record the decision INCLUDING every rejected candidate
                 and why    ("why isn't this with Ada?")
               selected?
                 → status = IN_PROGRESS, picked_up_at, first_picked_up_at
                 → OWNERSHIP → agent  (reason ASSIGNED_BY_STRATEGY)
                 → publish conversation.assignment_changed

  ④ WAITING IN THE QUEUE
         agent picks it  → OWNERSHIP → agent (PICKED_BY_AGENT)
                         → queue clock ANSWERED on acceptance
         nobody picks it → ai-pickup sweep (10 s) fires at
                           ai_pickup_eligible_at → AutopilotTrigger.PICKUP
         SLA warning/breach → autopilot-sla-consumer
                            → AutopilotTrigger.SLA
         agent asks AI     → AutopilotTrigger.AGENT_REQUEST

  ⑤ THE EXCHANGE
         agent reply  → ConversationService.send_reply
                        → ChannelProviderFactory → provider.send_message
                        → Message(OUTBOUND) → publish message.sent
                        → first-response clock SETTLED
                        → send failure? structured diagnostic on the
                          message, surfaced in the UI — never a bare 500
         typing       → Redis pub/sub only
         AI reply     → AutopilotService: build history (≤50 msgs),
                        AiService.suggest_autopilot_reply,
                        confidence ≥ threshold? send : hand off
                        → publish conversation.autopilot_replied
                          (or .autopilot_handoff_needed)
                        → messages stamped is_ai_generated /
                          is_ai_assisted    ← Learning and Billing read
                            these
         human takes over from AI
                      → OWNERSHIP row (this is the transition every
                        "AI must not speak after a human steps in" rule
                        reads)

  ⑥ ENDING
         RESOLVED → publish conversation.resolved
                    → csat-dispatch-consumer sends the survey link
                    → learning-observation-consumer ASSEMBLES  (⑦)
                    → resolution clock SETTLED
         CLOSED   → publish conversation.closed  → also assembles
         REOPENED → publish conversation.reopened      (since 1.1.0)
                    Both paths: a new inbound message on a resolved/
                    closed conversation (ingest consumer), and an agent
                    moving it out of a FINISHED status
                    (ConversationService.update).
                    Payload carries ended_at + reopened_at, because the
                    ingest path CLEARS closed_at — the publisher is the
                    last thing that still holds them.
                    → learning-signals-consumer invalidates the outcome

  ⑦ AFTER THE FACT  (nothing here can block anything above)
         learning observation assembled → pending
         csat.submitted → settles it immediately
         nothing arrives → settle sweep promotes it after 72 h
         reporting rollups incremented
         usage metered → billable_events
         audit rows written (bodies redacted)
```

## E. Complete Memory lifecycle

```
  RECORD                              (the ONLY door: MemoryManager)
  ────────────────────────────────────────────────────────────────────
  caller (agent note · CRM sync · workflow action · import)
     │
     ├─ Policy.MEMORY_RECORDING    ← FAILS CLOSED
     │     denied → nothing is written, and the refusal is recorded
     │
     ├─ validate_fact_shape()      ← pure, before the session
     │     · fact_type ∈ tier vocabulary?     else UnknownFactTypeError
     │     · subject_type allowed for tier?   else SubjectTierMismatch
     │     · at least one EvidenceRef?        else EvidenceRequiredError
     │     · AGENT_STATEMENT has agent_id?    else UnsupportedCorroboration
     │     · SYSTEM_RECORD has source_id?     else UnsupportedCorroboration
     │
     ├─ fact_key = memory_identity.fact_key(statement)
     │     NFKC · casefold · Arabic diacritics · أ/إ/آ→ا · ة→ه
     │     · hash past 180 chars (truncation would collide prefixes)
     │     NEVER the raw statement text
     │
     ├─ UPSERT on uq_memory_facts_identity
     │     (company, tier, subject_type, subject_id, fact_type, fact_key)
     │
     ├─ INSERT evidence  UNIQUE(fact_id, source_type, source_id)
     │     evidence_added = did the insert actually happen?
     │
     ├─ IF evidence_added:                       ← THE INVARIANT
     │     last_observed_at = now
     │     lifecycle = revive_on_observation(lifecycle)   DORMANT→ACTIVE
     │   ELSE: nothing moves. A replay changes NOTHING.
     │
     ├─ RECOMPUTE (never increment)
     │     support        = COUNT(memory_evidence)
     │     distinct_cust  = COUNT(DISTINCT customer_id)
     │     distinct_agent = COUNT(DISTINCT agent_id)
     │     contradictions = COUNT(memory_contradictions)
     │     confidence     = sigmoid(w·log₁₊(...)) · 0.5^(age/half_life)
     │
     ├─ next_confidence_state(current, confidence, has_corroboration)
     │     promote 0.30 / 0.55 / 0.80    demote 0.22 / 0.47 / 0.72
     │     NO corroboration → CEILING AT **CANDIDATE**, always
     │
     ├─ INSERT memory_confidence_samples (running totals)
     ├─ compute_direction over a 6-sample window, decay removed
     │     RISING · STABLE · FALLING · CONTESTED · UNKNOWN
     │
     ├─ publish memory.fact_recorded | .fact_reinforced
     │          (+ .fact_state_changed if a threshold was crossed)
     │          payloads carry IDs AND COUNTS — never the statement
     │
     └─ ONE TRANSACTION: fact + evidence + confidence + lifecycle + event


  AGE                                  (age_memory — hourly)
  ────────────────────────────────────────────────────────────────────
   tenant-fair rotation, N companies per run, batch sized from corpus
     │
     ├─ recompute confidence     (a FUNCTION re-evaluated,
     │                            NOT a number decremented)
     ├─ next_lifecycle_state, in this order:
     │     1. human SUPPRESSED     → frozen. Outranks the schedule.
     │     2. no evidence left     → ARCHIVED (not purged — the row IS
     │                                the record that we believed this)
     │     3. expires_at reached   → ARCHIVED
     │     4. age ≥ purge (1095d)  → PURGED
     │        age ≥ archive (545d) → ARCHIVED
     │        age ≥ dormant (180d) → DORMANT
     │        else                 → ACTIVE
     │        (per-company retention where set)
     ├─ DELETE rows the machine marked PURGED
     ├─ PRUNE confidence history past its window
     └─ circuit breaker: a row failing max_attempts is skipped, not
        retried forever

   READ:  decayed_confidence(stored, computed_at, now)
          the sweep keeps the cache warm; the reader finishes the decay,
          so a stale cache is CONSERVATIVE, never wrong.


  HUMAN INTERVENTION            (memory.manage)
  ────────────────────────────────────────────────────────────────────
   confirm  → human_state = CONFIRMED, last_confirmed_at = now
   suppress → human_state = SUPPRESSED → not retrievable, and NOT
              purged (a suppressed fact that vanished would simply be
              re-learned next week)
   correct  → human_state = CORRECTED
   each publishes its own event.


  CONTRADICTION                 (Knowledge → Memory, automatic, one-way)
  ────────────────────────────────────────────────────────────────────
   MemoryManager.contradict(fact, source)
     → INSERT memory_contradictions  UNIQUE per source   ← B2 fix
     → recompute (count is DERIVED)  → demotion possible
     → publish memory.fact_contradicted


  ERASE                          (memory.erase — OWNER ONLY)
  ────────────────────────────────────────────────────────────────────
   DELETE /memory/subjects/{type}/{id}
     │
     1. FIND aggregate facts this subject contributed to
        ← FIRST, while their evidence still exists to identify them
     2. DELETE facts ABOUT the subject   + their vectors
        (SupportsOwnerDeletion port → embeddings)
     3. DELETE their evidence EVERYWHERE else
     4. RECOMPUTE what is left
          lost ALL support → **ARCHIVED, not deleted**
     5. FAN OUT to every ErasureParticipant
          · conversation memory (Redis)   · learning (4 tables)
          a participant that raises → the report says INCOMPLETE
     6. publish memory.subject_erased      ← COUNTS ONLY
          (an erasure event naming what was erased would defeat it)
     7. return ErasureReport(counts)  ← the document forwarded to a
                                        regulator


  WORKING MEMORY               (Conversation tier — Redis, TTL)
  ────────────────────────────────────────────────────────────────────
   entities · open questions · commitments · stated preferences ·
   turn summaries        bounded: 50 / 20 / 20 / 20
   no confidence · no evidence · no lifecycle · no steward · no human
   state
   dies with the conversation. Distillation into durable facts is
   DESIGNED AND NOT BUILT — it needs a model deciding what matters.
```

## F. Complete Knowledge lifecycle

```
  AUTHOR
    POST/PATCH /knowledge/articles
      · title, body, category, tags (reusing the company Tag catalog)
      · is_published
      │
      ├─ SAME TRANSACTION: KnowledgeIndexState.status = PENDING
      │     the write path does the CHEAP half only
      └─ publish knowledge_article.created | .updated
            → audit-log-consumer  (no indexing consumer — deliberately)

  INDEX                     (reindex_pending — beat, 60 s)
    claim a bounded batch of PENDING articles
      (deliberately DOES NOT filter soft-deleted articles —
       a deleted article is exactly the one whose vectors must come OUT)
      │
      ├─ GROUP BY company        ← per-company provider and model
      │
      ├─ chunk_article(title, body)
      │     heading-aware · max chars · overlap
      │     embeddable_text = heading path + body
      │
      ├─ content_hash per chunk (over the EMBEDDABLE string)
      │     unchanged chunk → SKIP, no embedding call
      │     changed/new     → embed
      │     (a typo fix in a 40-chunk manual costs 1 call, not 40)
      │
      ├─ provider.embed(batch)   OpenAI | Ollama | hashing
      │     dimension mismatch → EmbeddingDimensionMismatchError
      │
      ├─ UPSERT knowledge_chunks + embeddings
      │     embeddings is POLYMORPHIC: (owner_type, owner_id)
      │     OWNER_KNOWLEDGE_CHUNK today
      │     OWNER_MEMORY_FACT declared, unused
      │     CLUSTER_CENTROID reserved for Learning phase 2
      │
      └─ status = INDEXED   |   FAILED (attempts++, circuit breaker)

  RETRIEVE                  (GET /knowledge/search, POST /ai/knowledge-search)
    query
      │
      ├─ len < 2 chars → return empty, reason="query_too_short"
      │
      ├─ LEXICAL HALF   (always)
      │     PostgreSQL: word_similarity trigram (pg_trgm)
      │     SQLite:     substring ILIKE
      │     → ranked article_ids, pool 50
      │
      ├─ SEMANTIC HALF  (only if a provider is configured)
      │     embed(query) — provider error is CAUGHT, degraded=True
      │     PgVectorIndex.search(company_id=…, model=…, owner_type=…)
      │        company_id is a REQUIRED kwarg — a cross-tenant search
      │        is INEXPRESSIBLE. An ANN index ranks BEFORE predicates.
      │        model always filtered — a half-migrated corpus returns
      │        FEWER results, never a meaningless mixture
      │     → chunks → collapse to articles, keep the best chunk each
      │
      ├─ RECIPROCAL RANK FUSION   score = Σ 1/(60 + rank)
      │     ranks only — nothing to normalise
      │     found by BOTH > found brilliantly by EITHER
      │     ties broken by first-seen → deterministic, reproducible
      │
      ├─ HYDRATE articles  ← company predicate applied a SECOND time
      │
      └─ RetrievalOutcome(hits, sources, degraded, reason)
            each hit carries: article · score · sources · ranks
                            · excerpt (the matching CHUNK) · chunk_id

  GROUND AN ANSWER
    grounding_passages(company, query, limit=5)
      published_only=True   — an answer must never be grounded in a draft
      NO category filter    — restricting the corpus by a UI filter the
                              customer never chose would silently narrow
                              what the AI is allowed to know

  ── NOT BUILT ─────────────────────────────────────────────────────────
  versions (B9) · retraction · emergency withdrawal · VOICE_CONSTRAINT
  · AnswerVerifier (B8) · retrieval_traces (B10) · Suggestions
```

## G. Complete Learning lifecycle

```
  TRIGGER
    conversation.resolved  |  conversation.closed
        │
  ASSEMBLE      (learning-observation-consumer)
        │
        ├─ ① POLICY FIRST — Policy.KNOWLEDGE_LEARNING, fails closed
        │      denied → write an EXCLUDED row, reason=policy_denied,
        │               and READ NO CONTENT AT ALL
        │      ("we were not allowed to look" ≠ "we looked and found
        │        nothing" — a materially different answer to a regulator)
        │
        ├─ ② LOAD the conversation, ≤ _MAX_TURNS (500)
        │      cross-tenant reference → TenantMismatchError, REFUSED
        │      (not filtered — a filter would hide a broken adapter)
        │
        ├─ ③ PROVENANCE, per turn, from message metadata
        │      human_authored · ai_generated · ai_assisted
        │      is_system_generated → COUNTED AS NEITHER
        │        (a CSAT invitation was nobody's message to this customer;
        │         adding it to either number would make that number lie)
        │
        ├─ ④ FILTER BEFORE EXTRACTION  (I-5)
        │      remove ai_generated and is_system_generated turns
        │      filtering AFTERWARDS would still let the platform's own
        │      vocabulary become the topics it later clusters on
        │      is_ai_assisted is ADMITTED (a human pressed send) but may
        │      never corroborate — enforced by Memory, not here
        │
        ├─ ⑤ EXTRACT tier 0 + tier 1 — DETERMINISTIC, no model
        │      tier 0: inbound/outbound turns, human_char_count
        │      tier 1: language (ar|en|mixed|None — mixed is first-class)
        │              entities (orders, amounts, URLs)
        │              topics ≤20  — URLs stripped first;
        │                            letter+digit tokens rejected as
        │                            identifier fragments (NOT a hex
        │                            test — cafe/dead/decade are words)
        │
        ├─ ⑥ OUTCOME — copied from conversation_outcome.derive (I-6)
        │      resolved · resolved_by · reopened · escalated
        │      · first_contact · handling_seconds · csat · settled
        │      outcome_attributable = (resolved_by == HUMAN)
        │        a workflow/timeout close is a RULE FIRING, not evidence
        │        unknown → NOT attributable (never guessed as human)
        │
        ├─ ⑦ decide_state(settled, provenance, features, policy_allows)
        │      policy → human content → substance → settlement
        │      EXCLUDED(policy_denied | no_human_content | too_short)
        │      or PENDING / READY
        │
        ├─ ⑧ validate(observation)
        │      ≥1 content ref (excluded rows EXEMPT — that exemption is
        │      the whole point of recording them)
        │      ≤ MAX_CONTENT_REFS (200)
        │      excluded must say WHY
        │
        └─ ⑨ WRITE, idempotent on UNIQUE(source_id, pipeline_version)
               learning_observations      (the envelope)
               learning_observation_features (tier 0/1, updated in place)
               learning_observation_refs  (POINTERS — nowhere to put a
                                           body, by construction)
               AssemblyResult(created, features_written)
                 → a replay reports created=False and changes nothing

  SETTLE            two paths, and neither re-derives anything
    ├─ learning-signals-consumer
    │    csat.submitted → attach score, settle IMMEDIATELY
    │    conversation.reopened → invalidate the resolution
    │        resolved=False · reopened=True · first_contact=False
    │        state → PENDING · settle_due_at → None
    │        (had no publisher at all before 1.1.0)
    │    conversation.transferred / .sla_breached → escalation signal
    │    A SIGNAL NEVER UN-EXCLUDES AN OBSERVATION
    │
    └─ settle-learning-observations  (beat, 900 s)
         PENDING and settle_due_at ≤ now  → READY
         batch 500; the run window == the interval (one setting)
         records a learning_runs row EVERY run
           (it used to record hourly on a 15-minute schedule, so three
            runs in four left no trace — including their failures)

  OBSERVE           GET /intelligence/*
    observations/{conversation_id} → the whole audit story in one call:
        what was extracted, from WHICH refs, why it was excluded
    health → pending · settled · failed · replayed · erased
             + FEEDBACK RATIO  ← the number that decides whether phase 2
                                 is safe to switch on

  ERASE             LearningErasureParticipant
    customer subjects only (an agent is a participant, not a subject —
    erasing an agent must not delete the record that work happened)
    children deleted EXPLICITLY, never left to ON DELETE CASCADE
    (an erasure report must not depend on a database setting to be true)

  ── AND THEN NOTHING ELSE ─────────────────────────────────────────────
  no clustering · no detection · no trends · no gaps · no candidates
  · no suggestions · no review · NO MODEL CALLS · NO MEMORY WRITES
  Learning writes ONLY its four tables (I-2, AST-guarded) and binds NO
  memory.*/learning.*/intelligence.* routing key (I-4, test-asserted).
```

## H. Dependency graph

Arrows point **toward the dependency**. Nothing points back up a layer.

```
                          ┌─────────────────┐
                          │   domain/rbac   │  imports NOTHING
                          └─────────────────┘

  ┌──────────────────── domain/  (framework-free, no I/O, no clock) ─────┐
  │                                                                      │
  │  memory ← memory_confidence · memory_lifecycle · memory_identity     │
  │  memory_ports (Protocols only — Memory does not import Stage 1)      │
  │  learning_observation ← learning_features                            │
  │  conversation_outcome   ← the SINGLE definition, shared by           │
  │                            SLA · Reporting · Learning                │
  │  policies ← execution_context ← service_context · customer_context   │
  │  ownership · lifecycle · sla · business_hours · routing_decisions    │
  │  chunking · retrieval · vector_index · embedding_provider            │
  │                                                                      │
  └──────────────────────────────▲───────────────────────────────────────┘
                                 │
  ┌──────────────────── application/services/ ───────────────────────────┐
  │                                                                      │
  │  ConversationService ──► OwnershipService ──► domain/ownership       │
  │        │      │     └──► SlaEngine/SlaLifecycle                      │
  │        │      └────────► ChannelProviderFactory ──► providers        │
  │        └───────────────► AttachmentStore (MinIO)                     │
  │                                                                      │
  │  AutopilotService ──► ConversationService                            │
  │                  ──► AiService ──► AiProvider (registry)             │
  │                  ──► ServiceContextResolver                          │
  │                                                                      │
  │  RoutingEngine ─┐                                                    │
  │  AssignmentEngine├─► repositories (READ) — neither WRITES            │
  │  ConfigurationResolver ─► ONE resolver for SLA + AI policy           │
  │                                                                      │
  │  KnowledgeRetrievalService ──► EmbeddingService ──► providers        │
  │                            ──► VectorIndex (port)                    │
  │                            ──► LexicalSearchRepository               │
  │                            ──► domain/retrieval (RRF)                │
  │                                                                      │
  │  MemoryManager ──► domain/memory* (pure)                             │
  │       ▲       ──► memory repositories   ← THE ONLY WRITER            │
  │       │                                                              │
  │       ├── MemoryErasureService  (narrow SupportsFactRecompute port)  │
  │       └── memory_decay_sweep_task                                    │
  │                                                                      │
  │  LearningObservationService ──► domain/learning_* (pure)             │
  │                             ──► conversation_outcome (COPIES)        │
  │                             ──► LearningObservationRepository ONLY   │
  │                             ──► READS conversations/messages/CSAT    │
  │                             ──✗ NEVER memory, NEVER writes elsewhere │
  │                                                                      │
  └──────────────────────────────▲───────────────────────────────────────┘
                                 │
  ┌──────────────────── infrastructure/ ─────────────────────────────────┐
  │  repositories · ORM models · channels · ai · embeddings · vector     │
  │  events(outbox, relay, 12 consumers) · storage · email · erp · tasks │
  └──────────────────────────────▲───────────────────────────────────────┘
                                 │
  ┌──────────────────── api/ ────────────────────────────────────────────┐
  │  v1/router.py → 48 endpoint modules                                  │
  │  deps.py — THE ONLY place API code touches the container             │
  │  schemas/ — Pydantic request/response, write-only fields excluded    │
  └──────────────────────────────────────────────────────────────────────┘

  CROSS-CONTEXT EDGES, and the direction each is allowed to run:

     Knowledge ──contradiction──► Memory        AUTOMATIC, one-way
     Memory ──suggestion──► Knowledge           NEVER automatic (unbuilt)
     Knowledge + Memory ──read-only──► Intelligence      (unbuilt)
     Learning ──reads──► Conversations/Messages/CSAT/ChannelConfigs
     Learning ──✗──► Memory            FORBIDDEN (I-4), test-asserted
     Memory ──✗──► Learning            no such edge exists
     Everything ──► Policy Engine      ASK, never re-implement
     Everything ──► ExecutionContext   resolved facts, no ids to re-look-up
```

## I. Ownership matrix

| Business fact | **Owner** | Consumers | Exposed as | Erasable |
|---|---|---|---|---|
| Password, sessions, tokens | Authentication | — | `AuthService`, Redis allowlist | With the user |
| Roles, permissions | Authorization | API gate | `domain/rbac.py` | No |
| Person (name, email, verification) | Identity ⚠️ | API gate, Company admin | `users` | With the user |
| Membership in a company | Company | Everything | `users.company_id` | No |
| Company, departments, teams, business config | Company | Everything | Repositories + `Company.settings` | No |
| Business hours, holidays | Company | SLA, AI | `domain/business_hours.py` | No |
| Customer identity | Company (CRM) | Conversation, Inbox, ERP, Memory | `customers` | **Yes** |
| Channel credentials | Channels | Providers | `channel_configs` (encrypted) | No |
| Conversation status | Conversation | Inbox, SLA, Reporting | `Conversation.status` | Soft delete |
| Message content | Conversation | Everything | `messages` | Soft delete |
| **Who is responsible** | **Ownership** | Inbox, Inspector, metrics | `conversation_ownership` (append-only) | No |
| Which service it runs in | Routing → binding | SLA, AI, Inbox | `ConversationContextBinding` (by value) | No |
| Which queue | Routing | Assignment, Inbox | `Conversation.queue_id` + `routing_decisions` | No |
| Which agent | Assignment → **Ownership** | Inbox | `assigned_agent_id` (**projection**) | No |
| Deadlines, breaches, health | SLA | Inbox ordering, Inspector, Reporting | `conversation_sla_clocks` | No |
| **SLA targets** | Service version → queue → company → platform | SLA | `ConfigurationResolver` (**one resolver**) | No |
| **May this happen?** | **Policy Engine** | Every module | `PolicyDecision` + `POLICY_EVALUATED` rows | No |
| AI confidence threshold | Service version → company | AI | One resolver | No |
| Classification, suggestions, autopilot | AI | Conversation, Inbox | `AutopilotService` | No |
| **What the company officially states** | **Knowledge** | AI, agents, customers | `knowledge_articles` + `knowledge_chunks` | **No — retired, never deleted** |
| Semantic index | Knowledge | Retrieval | `embeddings` (polymorphic) | With the owner |
| **What the platform observed** | **Memory** | AI, Workflow, CRM, Reporting, Timeline, Analytics | `memory_facts` + `memory_evidence` | **Yes, and it must be** |
| Why we believe it | Memory | Review, audit, erasure | `memory_evidence` | **Yes** |
| How sure, and which way it is moving | Memory | Ranking, alerts | Computed `confidence`, `confidence_direction` | Derived |
| What is true right now in this conversation | Memory (working) | AI | Redis, TTL | With the conversation |
| **What Learning saw** | **Learning** | Operators | 4 `learning_*` tables | **Yes** (customer subjects) |
| What tends to work | Memory (Experience tier) | AI, analytics | `memory_facts` tier=experience | Aggregate only |
| Live stock, invoices, balances | **Systems of Record** | AI, agents | Queried, **never stored** | N/A |
| What the answer should be | Intelligence ⛔ | Conversation, agents | A response with citations | Owns nothing |
| What becomes official | **Humans** ⛔ | — | Suggestion reviews | — |
| How the organization operates | **Company Behavior** 🔒 | Policy, Workflow, Routing, SLA | — | Reserved |
| Usage, price, invoice, payment, ledger | Billing | Dashboard, platform | `billable_events` … `ledger_entries` | No (financial record) |
| Cross-tenant operations | Platform Admin | — | `/platform/*` | No |
| Everything that happened | Audit | Compliance | `audit_logs` (bodies redacted) | No |

## J. End-to-end walkthrough

**A customer messages a company on WhatsApp at 09:14. Follow it all the
way through.**

---

### Step 1 — Customer sends message

**09:14:02.** Meta POSTs to
`https://app.example.com/api/v1/webhooks/{channel_config_id}`.

nginx proxies it. The route loads the `ChannelConfig` (no auth — the
signature *is* the authentication) and builds the provider through
`ChannelProviderFactory`, which imports the providers package at module
level so registration cannot depend on which entrypoint remembered to
trigger it.

`WhatsAppProvider.verify_signature(request)` checks Meta's
`X-Hub-Signature-256` HMAC over the raw body, using the **App Secret**
stored encrypted on the config. Wrong signature → **401**, and nothing
else runs.

`provider.webhook(request)` parses Meta's envelope into a
channel-agnostic `InboundMessage`: external customer id, external thread
id, external message id, body, attachments, optional reply-to.

The route publishes:

```
message.received
  company_id      = <tenant>
  aggregate_type  = "message"
  payload         = { channel_config_id, channel_type: "whatsapp",
                      external_thread_id, external_message_id,
                      external_customer_id, external_customer_name,
                      body, attachments[] }
```

**Nothing has been persisted.** No `Conversation`, no `Message`, no
`Customer`. The webhook returns 200 in single-digit milliseconds, which is
what keeps Meta from retrying.

One `event_outbox` row was written on the request's session and committed
with it. **09:14:04** — the relay's next tick claims it with
`SKIP LOCKED` and publishes it to `blinkengage.events` with routing key
`message.received`.

Two queues are bound to that key: `conversation-ingest` and `audit-log`.

---

### Step 2 — Routing

`conversation-ingest-consumer` receives the message with manual ack.

**Customer resolution.** WhatsApp has no natural `Customer` column, so
resolution goes through `customer_channel_identities` — the same
channel-agnostic path Telegram, Messenger, Instagram and SMS use. No
match: a `Customer` is created and `customer.created` is published (which
`erp-sync-consumer` will pick up and, for a company with no ERPNext
config, silently no-op).

**Thread resolution.** `get_by_thread(channel_config_id,
external_thread_id)` finds nothing. A `Conversation` is created;
`conversation.created` is published.

**Idempotency.** `external_message_id` is not already in `messages`, so
this is not a redelivery.

**Attachments** are validated against the content-type allowlist and size
cap — the *same* validator the upload endpoint uses. Anything rejected is
logged and dropped from the message rather than failing the whole ingest.

The `Message` row is inserted (`direction=INBOUND`), `last_message_at` is
stamped, `message.persisted` is published, and a **Redis** realtime tick
goes out on the company channel so any open Inbox updates immediately
rather than waiting for a poll.

Because the conversation is **brand new**, `_route_and_assign` runs. It
never runs again for this conversation — a later message does not re-route
it.

**Service resolution** runs four stages in order, each recording evidence:

1. *Customer selection* — did the customer pick a service from a
   directory? No (WhatsApp has no such surface). One comparison, no query.
2. *Business rules* — the company's conditions on channel and keywords.
   Matches "Support".
3. *Fixed service* — not reached.
4. *Fallback* — not reached.

A `ConversationContextBinding` is written (append-only) pointing at
`service_versions` row 7 — **the version, not the service**. This
conversation will run under version 7's rules for its entire life, even if
an administrator edits the service at 09:30. `ContextBindingReason =
BOUND_AT_START`.

A `SERVICE` `RoutingDecision` is written carrying every stage's evidence.

---

### Step 3 — Policy

```python
routable = await policies.evaluate(Policy.ROUTING, execution)
```

`RecordingPolicyEngine` wraps the pure engine. The decision is
`allow / PERMITTED / PLATFORM_DEFAULT`, and a `POLICY_EVALUATED` row goes
into `routing_decisions` — **an allowance is recorded, not only a
refusal**, because "why was this permitted?" is the question asked after
something reached a customer that should not have.

**Queue selection.** Service version 7 names a logical queue, so the
service wins: `SERVICE_OWNS_QUEUE`. (Had it not, `RoutingEngine` would
evaluate routing rules by ascending priority, capturing the matched rule
**as values** so a later edit cannot rewrite this decision.)

`conversation.queue_id` is set, `queue_entered_at` stamped, status becomes
`WAITING`, and `conversation.queued` is published.

`ConfigurationResolver.for_conversation` resolves **SLA targets and AI
policy in one read**, down one chain — service → queue → company →
platform — each answer tagged with the tier that produced it. This is the
fix for `A3`; before it, a company without a service directory started no
clocks at all.

**Three clocks start**: `QUEUE`, `FIRST_RESPONSE`, `RESOLUTION` — targets
**copied onto the clock**, not read through a join. The customer is
simultaneously waiting for somebody to take it, for a first reply, and for
the whole thing to be over.

**Ownership**: `OwnershipService.transfer` writes an append-only row
naming the **queue** as owner, reason `NEW_CONVERSATION`, then projects
onto `assigned_agent_id` (which stays null for a queue owner). The
conversation is *owned*, not unassigned.

A `QUEUE` decision is recorded, carrying the queue's **name** as a value.

**AI engagement.** The queue has `autopilot_enabled`, so:

```python
engaged = await policies.evaluate(Policy.AI_ENGAGEMENT, execution)
```

Narrowest-first order: customer opted out? → company AI off? → no
provider? → service AI off? → agent already owns it? → conversation
finished? All pass. `CompanyCapabilities` were populated — had the caller
forgotten, the answer would be `deny / CAPABILITIES_UNKNOWN`, because
`AI_ENGAGEMENT` **fails closed**.

Allowed — and the service's `pickup_delay_seconds` is 30. So
`ai_pickup_eligible_at = 09:14:34`, an `AI_DEFERRED` decision is recorded,
and `engaged` is set back to `False`.

**AI is a queue worker, not a first responder.** The conversation sits in
its queue, visible, where a human gets first refusal.

The assignment engine runs: candidates narrowed by required skills, then
`LeastLoad`. Nobody is online. The decision is recorded **with every
rejected candidate and why** — which is what makes "why isn't this with
Ada?" answerable later.

---

### Step 4 — Knowledge retrieval

**09:14:34.** `ai-pickup-waiting-conversations` (10s sweep) finds the
conversation past its eligibility time and still unclaimed. It invokes
`AutopilotService` with `AutopilotTrigger.PICKUP`.

Ownership transfers to `AI_OWNER` (reason `AI_ENGAGEMENT`). Status becomes
`IN_PROGRESS`. **The queue clock is answered on acceptance**, not on
reply — "how long has this customer been waiting for ownership?" is
answered the moment somebody owns it.

`AutopilotService` builds history (≤50 messages) and calls
`AiService.suggest_autopilot_reply`, which grounds the answer:

```
grounding_passages(company_id, query=<customer text>, limit=5)
```

- **Lexical half** — PostgreSQL `word_similarity` trigram over
  `pg_trgm`, candidate pool 50. Finds nothing: the customer wrote *"can I
  get my money back"* and the article is titled *"Refund policy"*.
- **Semantic half** — the query is embedded, then
  `PgVectorIndex.search(company_id=…, model=…, owner_type=OWNER_KNOWLEDGE_CHUNK)`.
  `company_id` is a required kwarg, so a cross-tenant search is
  inexpressible — which matters because an ANN index ranks *before*
  predicates apply. Returns chunk hits; they collapse to articles keeping
  the best-ranked chunk each.
- **Fusion** — `score = Σ 1/(60 + rank)`. Ranks only, so nothing has to be
  normalised between a `[0,1]` trigram score and a `[-1,1]` cosine. Ties
  break deterministically.
- **Hydration** re-applies the company predicate — the second place tenant
  scoping is enforced, on purpose.

`published_only=True` (an answer must never be grounded in a draft) and
**no category filter** (restricting the corpus by a UI filter the customer
never chose would silently narrow what the AI is allowed to know).

The result carries the matching **chunk excerpt**, not the whole article —
so a question answered on page four of a long manual does not arrive
buried in four pages of unrelated text.

Had no embedding provider been configured, the outcome would return
`degraded=True, reason="embeddings_not_configured"` and lexical-only
results. **A worse search, never a broken feature** — the knowledge base
worked before embeddings existed.

---

### Step 5 — Memory

Two tiers are read on this path.

**Conversation Memory (working, Redis).** The entities, open questions,
commitments and stated preferences accumulated so far in this thread.
Bounded (50 entities / 20 open questions / 20 commitments / 20
preferences), TTL'd, no confidence, no evidence. It exists so a customer
who gave an order number at turn 3 is not asked for it again at turn 20 —
**the single most recognisable way software reveals it is not really
following the conversation.**

**Customer and Organizational Memory (durable).** Read through
`is_retrievable(lifecycle, human_state)` — one function, so the AI Engine,
the Customer Timeline, Reporting and Analytics all agree about whether a
suppressed fact is visible. Confidence is read through
`decayed_confidence()`, which finishes the decay the hourly sweep may not
have caught up on, so a stale cache produces a conservative number rather
than a wrong one.

**What Memory does *not* do on this path:**

- It does not supply the customer's balance. That is a **System of
  Record** — ERPNext owns it, and a remembered balance is wrong by the
  time it is retrieved.
- It does not write anything. Stage 2 records what callers *ask* it to
  record; there is no automatic extraction, because deciding what is worth
  remembering is a judgement and judgement belongs to callers.
- It does not let anything an unco­rroborated customer statement supports
  rise above `CANDIDATE`, no matter how often it has been repeated.

---

### Step 6 — Learning observation

**Nothing happens here yet, and that is the design.**

Learning binds only `conversation.resolved` and `conversation.closed`. It
does **not** bind `message.persisted`: an observation is about a
*finished* unit of work, and assembling one per message would produce a
row per turn that the settle window then has to reconcile.

**Learning never blocks anything.** Both consumers are separate processes
reading other contexts and writing only Learning's four tables. If they
were down right now, this reply would still be sent.

Learning will observe this conversation at Step 8's aftermath.

---

### Step 7 — AI

`AiService.suggest_autopilot_reply` composes the prompt from:

- the conversation history (≤50 messages),
- the retrieved grounding **chunks**,
- the working-memory context,
- the retrievable durable facts.

One `complete()` call to the configured provider — OpenAI, Claude, Ollama,
Gemini, Azure OpenAI, Mistral, Groq or DeepSeek. There is one method, not
one per feature, because every backend shares the same fundamental
capability and prompt engineering therefore lives once.

The response carries a `CONFIDENCE:` line. `ai-engine.md` is honest that
this is **still ultimately the model's own opinion** — which is defensible
for one reply a threshold gates, and is exactly *why* it is not acceptable
for a memory fact that will be quoted to thousands of customers. That is
the whole reason `domain/memory_confidence.py` computes instead of asking.

The threshold resolves down the same chain as everything else:
`effective_autopilot_confidence_threshold` — service version, then
company.

**Below the threshold, or an explicit low-confidence signal:**
`autopilot_active` is cleared, ownership returns to the queue,
`conversation.autopilot_handoff_needed` is published →
`notification-consumer` creates a durable `Notification` → the agent
WebSocket delivers it live → the push/email sweeps pick it up. The
conversation is back in front of a human, and the Inspector shows exactly
why.

**Above the threshold:** continue to Step 8.

`ai.completed` is published — every capability publishes one, which is why
there is deliberately **no AI usage-tracking table**; `reporting-consumer`
aggregates the event.

---

### Step 8 — Reply

`ConversationService.send_reply`:

1. `ChannelProviderFactory` builds the WhatsApp provider from the
   encrypted config.
2. `provider.send_message(...)` calls Meta's Cloud API.
   - On failure, a **structured diagnostic** is stored on the message and
     surfaced inline in the conversation UI — never a bare 500. The
     failure handler catches broadly (an earlier version caught only
     `httpx.HTTPError`/`ValueError`, so real SMTP, Redis and malformed-URL
     failures still surfaced as unhandled 500s — defeating the entire
     point of the diagnostic).
   - Any provider error text passes through `redact_credentials()` before
     it is stored, because Meta's and Telegram's error responses echo the
     access token back in the URL.
3. A `Message` row is inserted, `direction=OUTBOUND`, stamped
   `is_ai_generated=True` — **the marker Learning and Billing both read.**
4. `message.sent` is published.
5. The **first-response clock is settled**, and the transition is written
   into the decision log. (This is the path that once did nothing because
   `SlaLifecycle` was built with `None` — every AI reply settled no clock,
   so a conversation answered in seconds was reported as a missed first
   response until it breached. `core/wiring.py` now refuses to boot rather
   than let that recur.)
6. `usage-metering-consumer` writes one immutable `billable_events` row —
   one charge per customer-facing message, with the channel as a
   *dimension*, never as a price.
7. A Redis realtime tick updates any open Inbox.

**The customer receives the reply at 09:14:36.** Twenty-two seconds
elapsed since the message arrived, thirty of which the platform
deliberately spent waiting for a human who did not come.

---

### The aftermath — and where Learning finally acts

**Later that morning**, an agent takes over, finishes the exchange, and
marks the conversation `RESOLVED`.

- `conversation.resolved` is published.
- `csat-dispatch-consumer` sends the survey link (a conversation-scoped
  `TokenType.CSAT` JWT, 14-day life, reusing the existing JWT machinery
  rather than building a customer-auth system for one rating).
- The **resolution clock settles**.
- Ownership records `CONVERSATION_RESOLVED`.
- `reporting-consumer` increments the daily rollups —
  `conversation.updated` carries `previous_status`, so it detects a
  genuine transition rather than recounting an already-closed
  conversation.
- **`learning-observation-consumer` assembles.**

The assembly, in order:

1. **`Policy.KNOWLEDGE_LEARNING` first.** Allowed. Had it been denied, an
   `excluded / policy_denied` row would be written and **no content read
   at all**.
2. Load the conversation, bounded at 500 turns. Any cross-tenant reference
   would be **refused**, not filtered.
3. Count provenance per turn. The AI reply from Step 8 counts as
   `ai_generated`. The CSAT invitation counts as **neither** — it is
   `is_system_generated`, and adding it to either number would make that
   number lie.
4. **Filter before extraction (I-5).** The AI turn and the CSAT template
   are removed *before* the extractor sees them. Filtering afterwards
   would still let the platform's own vocabulary become the topics it
   later clusters on — the same loop wearing a different hat, invisible
   because the row would still show a healthy human fraction.
5. Extract tiers 0 and 1, deterministically. Language `mixed` (the
   customer switched between Arabic and English mid-thread — normal
   traffic here, not an edge case). Topics with URLs stripped and
   letter+digit identifier fragments rejected. Entities: an order number
   and an amount.
6. **Copy** the outcome from `conversation_outcome.derive` — never
   recompute it. `resolved=True`, `resolved_by=HUMAN`, therefore
   `outcome_attributable=True`. Had a workflow auto-closed it, `resolved`
   would still be `True` but `outcome_attributable` would be **False** —
   because a rule firing is not evidence that anything worked.
7. `decide_state` → `PENDING`, because the CSAT has not landed and
   `settle_due_at = now + 72h`.
8. Validate: at least one content ref, at most 200.
9. Write, idempotent on `UNIQUE(source_id, pipeline_version)`. The refs
   are **pointers** — the table has nowhere to put a message body.

**Two hours later** the customer submits CSAT 5. `csat.submitted` fires;
`learning-signals-consumer` attaches the score and settles the observation
**immediately** — waiting further would delay learning for no gain. Had
the customer instead reopened the conversation, the same consumer would
have invalidated the resolution outright.

**And then Learning stops.** No cluster is updated, no pattern is
detected, no candidate is generated, no memory fact is written, no model
is called. The observation sits in `learning_observations` as
`state=ready`, traceable to the exact messages it came from, waiting for
phase 2.

An operator can open `GET /intelligence/observations/{conversation_id}`
and see precisely what the platform extracted and from what. And they can
open `GET /intelligence/health` and read the **feedback ratio** — the
share of observed content the platform itself wrote.

**That number is the gate on phase 2.** It is the reason this phase
exists, and it is the one thing no amount of design could have produced.

---

## See also

- [System Documentation](../SYSTEM.md) — every feature, and how it works
- [Company Intelligence Engine](./company-intelligence-engine.md) — Stage 1
- [FAQ](./faq.md) — the question-and-answer entity, and why it is not an article flag
- [Memory Platform](./memory-platform.md) — Stage 2
- [Learning Platform](./learning-platform.md) — Stage 3 Phase 1
- [Learning Platform Charter](./learning-platform-charter.md) — the contract
- [Knowledge, Memory and Intelligence](./knowledge-memory-intelligence.md) — the domain boundaries
- [Intelligence Platform](./intelligence-platform.md) — the Stage 3 design
- [Architecture Freeze Review](./architecture-freeze-review.md) · [Review 2](./architecture-freeze-review-2.md)
- [Domain ownership audit](./domain-ownership.md)
- [Policy Engine](./policy-engine.md) · [Execution Context](./execution-context.md)
- [Domain Event Bus](./event-bus.md) · [Observability](./observability.md)
- [Learning Platform Production Readiness](./learning-platform-production-readiness.md)
