# Blink Engage — Implementation Roadmap

This roadmap is the permanent execution plan for building Blink Engage, an
enterprise omnichannel customer engagement platform, to the standard defined
in [`CLAUDE.md`](../CLAUDE.md).

Scope of comparable reference: Zendesk / Intercom / Freshdesk feature parity.
This is a multi-milestone, long-running build. Each milestone below must be
built, tested, fixed, documented and committed before the next one starts, per
the WORKFLOW rules in `CLAUDE.md`. No milestone is considered complete while
tests are red.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` complete

---

## Phase 0 — Foundations

- [x] **M0. Server & tooling preparation**
  Docker Engine + Compose plugin, Node.js 22 LTS, Python 3.13, PostgreSQL /
  Redis client tools installed on the host. Docker daemon verified running.
- [x] **M1. Repository bootstrap**
  Git repo, directory structure (`docs/`, `frontend/`, `backend/`, `docker/`,
  `scripts/`, `tests/`, `monitoring/`, `backups/`, `.github/`), `.gitignore`,
  `README.md`, `CLAUDE.md`, this roadmap, editorconfig.
- [x] **M2. Docker Compose infrastructure**
  PostgreSQL, Redis, RabbitMQ, MinIO (+ bucket auto-create), backend,
  frontend (dev), NGINX reverse proxy (unified origin, dynamic upstream
  resolution), Prometheus, Grafana (provisioned datasources + a live
  dashboard), Loki + Promtail, Celery worker/beat. `docker-compose.yml`
  (dev) + `docker-compose.prod.yml` overlay (lean runtime images, no bind
  mounts, resource limits, SPA baked into NGINX). All 15 services verified
  healthy end-to-end, including a real Celery task round-tripping through
  RabbitMQ + Redis, and both dev/prod images build successfully. See
  `docs/architecture/infrastructure.md`, `docs/deployment/`.
- [x] **M3. Backend application skeleton**
  FastAPI app factory, layered Clean Architecture package layout
  (`domain/`, `application/`, `infrastructure/`, `api/`), settings via
  Pydantic Settings, structured logging, dependency-injection container,
  `/health` and `/health/ready` endpoints, OpenAPI metadata, Celery app +
  a verified baseline task, Prometheus instrumentation at `/metrics`,
  pytest + coverage config, ruff/black/mypy strict — all green. See
  `docs/architecture/backend.md`.
- [x] **M4. Database layer**
  SQLAlchemy 2 async engine/session management, Alembic migration
  environment (async-aware `env.py`), base repository pattern + unit of
  work, shared entity mixins (UUID PK, timestamps, soft-delete), first
  real migration (`pgcrypto`/`citext` extensions) verified against a live
  Postgres container. First domain tables land with M6/M7.
- [x] **M5. Frontend application skeleton**
  Vite + React 19 + TypeScript, Material UI theme (light/dark/RTL) branded
  to Blink ("Baloo 2" + "Nunito Sans", brand green `#8CC63F` on warm black
  `#171412`), Redux Toolkit store (`auth`, `ui` slices), React Query client,
  React Router with a `ProtectedRoute`, Axios API client with JWT
  access/refresh-token interceptor, ESLint (flat config)/Prettier/Vitest +
  Testing Library — all green. See `docs/architecture/frontend.md`.

## Phase 1 — Identity & Core Directory

- [x] **M6. Auth, RBAC & multi-tenant foundation**
  Company (tenant) model + `POST /auth/register` (creates a company, its
  Owner user, and seeded Owner/Admin/Agent roles in one transaction),
  `User` login identity, JWT access + individually-revocable refresh
  tokens (rotation on refresh, Redis-backed allowlist), bcrypt password
  hashing with a strength policy, `login`/`refresh`/`logout`/`me`
  endpoints, `Role`/`Permission`/`RolePermission`/`UserRole` schema with a
  seeded permission catalog (`domain/rbac.py`), the `require_permission`
  authorization dependency (permissions embedded in the access token —
  no per-request DB round-trip), and Redis fixed-window rate limiting on
  `/auth/register`+`/auth/login`. 50 tests passing (SQLite-backed) plus a
  full manual end-to-end pass against real Postgres/Redis/RabbitMQ, which
  caught and fixed three real bugs (a session-commit bug that silently
  rolled back every write, a missing eager-load causing an async
  lazy-load crash, and a concurrency race between services' migration
  steps — see `docs/architecture/auth-rbac.md` for details). See also
  `docs/database/schema.md`.
- [x] **M7. Departments, Teams, Agents**
  Department/team hierarchy (teams optionally scoped to a department),
  agent profiles (operational layer on top of the `User` identity —
  title, status, department/team membership) created together with their
  underlying `User` + seeded "Agent" role via `POST /agents`, team
  membership management (`POST`/`DELETE .../members`), full CRUD +
  pagination + RBAC-protected admin APIs, 80 tests passing. (Company/
  tenant foundation itself landed in M6, above.)
- [x] **M8. Customers**
  Customer profile model, tagging (company-scoped tag catalog,
  created-on-first-use), schema-less custom fields (JSON), search
  (name/email/phone), full CRUD + pagination + tenant isolation verified.
  Multi-channel identity resolution and merge/dedupe explicitly deferred
  to Phase 4 (nothing to resolve/merge until channels exist to create
  per-channel contact records). See `docs/architecture/core-crm.md` for
  three real bugs found and fixed during this milestone (a soft-delete +
  unique-constraint conflict, and two ORM-relationship-staleness bugs),
  and `docs/database/schema.md` for the full schema.
- [x] **M9. Audit logging foundation**
  Append-only `audit_logs` table (no update/soft-delete mixins — a row is
  written once and never changes), an `AuditEvent`/`AuditPublisher`
  contract (`domain/audit.py`) hooked directly into every mutating method
  of `DepartmentService`, `TeamService` (incl. membership add/remove),
  `AgentService`, `CustomerService`, and `AuthService` (registration,
  login, logout) — each publish call runs on the same DB session as the
  triggering change, so an audit entry and its business change commit or
  roll back together atomically. `GET /audit-logs` read API (the
  `audit_logs.read` permission was already seeded back in M6) with
  filtering by entity type/action/actor/entity id/date range plus the
  standard pagination. 86 tests passing (6 new). See
  `docs/architecture/audit-logging.md` for the design decisions
  (particularly why this is synchronous/in-transaction rather than queued)
  and `docs/database/schema.md` for the table.

## Phase 2 — Conversations Core

- [x] **M10. Domain event bus foundation**
  Transactional outbox (`event_outbox` table + `OutboxEventPublisher`,
  same-transaction as the triggering change — no dual-write gap), a
  Celery-beat relay draining the outbox to a durable RabbitMQ topic
  exchange (`SELECT ... FOR UPDATE SKIP LOCKED` claiming, safe under
  concurrent relay instances), and a shared `aio_pika`-based consumer
  runtime that any future module binds its own durable queue to — adding a
  consumer requires zero changes to a publisher or any other consumer.
  M9's audit hook is migrated onto this bus (the five mutating services
  now publish a generic `DomainEvent` instead of calling `AuditPublisher`
  directly; a new `audit-log` consumer service, bound to every routing
  key, writes the `AuditLog` rows instead — `docker-compose.yml`'s
  `audit-log-consumer` service). A `RealtimePublisher` (Redis pub/sub)
  adds the ephemeral, non-durable tier for typing indicators/presence.
  9 new tests plus the 6 existing M9 audit tests adapted to the new
  async write path. See `docs/architecture/event-bus.md`.
- [x] **M11. Channels — plugin architecture**
  Channel-agnostic DTOs and an 11-method `ChannelProvider` ABC
  (`send_message`/`receive_message`/`edit_message`/`delete_message`/
  `mark_as_read`/`typing_indicator`/`upload_attachment`/
  `download_attachment`/`webhook`/`verify_signature`/`health_check`), a
  registry + factory (channel type → provider class, looked up by string,
  never hardcoded), a per-company `ChannelConfig` model with
  application-layer-encrypted credentials (`channels.read`/
  `channels.manage` permissions), and a generic
  `POST /webhooks/{channel_config_id}` ingress that verifies, parses, and
  publishes `message.received` onto the M10 event bus — with zero
  Conversation/Message persistence yet (that's M13) and zero real
  providers (that's M12 and Phase 3). Proven end-to-end (12 new tests) with
  a `FakeChannelProvider` test double only, per the explicit requirement
  that provider implementations wait until the architecture itself is
  signed off. 107 tests total passing across the whole suite; `ruff
  check`/`mypy` clean. See `docs/architecture/channels.md` (which also
  specifies the `messages`/`message_attachments` schema for M13 to
  implement).
- [x] **M12. Web Chat channel (reference implementation)**
  The first real `ChannelProvider` (`web_chat`), proving M11's architecture
  against a genuine channel with no external API. A WebSocket gateway
  (`WS /api/v1/web-chat/ws/{channel_config_id}`) speaking a small JSON
  frame protocol (the "chat widget contract"), Redis-backed opaque
  session tokens (`ChatSessionStore` — a visitor session is a different
  trust domain than an agent's JWT login, so it isn't one), a
  `POST .../sessions` endpoint that creates a `Customer` on first visit,
  and Redis pub/sub fanout (`RealtimePublisher.subscribe`, new this
  milestone) so a reply published from any app server reaches whichever
  process holds the visitor's socket — no distributed connection registry
  needed. Also lands the shared MinIO-backed `AttachmentStore` M13 will
  reuse. 16 new tests (123 total); `ruff check`/`mypy` clean. See
  `docs/architecture/web-chat.md`.
- [x] **M13. Conversations, Messages, Attachments**
  The "conversation engine" finally exists, concretely: a
  `conversation-ingest-consumer` service subscribed to `message.received`
  on the M10 bus (never calling a `ChannelProvider` — that already
  happened upstream), building `Conversation`/`Message` rows per the
  schema `channels.md` specified. Conversation lifecycle
  (open/pending/resolved/closed) with validated status transitions,
  message model (text/media/system, delivery/read receipts via separate
  `status`/`delivery_status`/`read_status` columns), and attachments —
  upload/download through the M12 `AttachmentStore`, with type/size
  validation (`attachment_allowed_content_types`/`_max_size_bytes`) and
  virus scanning deliberately left as a documented, unimplemented
  extension point rather than a fake scanner. Outbound replies close the
  loop through the same `ChannelProviderFactory` every other channel
  entry point uses — end-to-end proven with `web_chat`: an agent's reply
  is persisted and observed arriving back over the visitor's realtime
  session channel. 23 new tests (146 total); `ruff check`/`mypy` clean.
  See `docs/architecture/conversations.md`.
- [x] **M14. Queues, Assignment Engine, Routing Engine**
  Closes out Phase 2. Queue model (per-queue assignment strategy + SLA
  targets), a company-scoped agent skill catalog, and a narrow
  `RoutingRule` evaluator (priority-ordered `channel_type`/`body_contains`
  matching — deliberately *not* the general Workflow Engine, that's M19).
  Round-robin and least-load assignment strategies, narrowed first by
  per-queue required skills. Both routing and assignment run synchronously
  inside the M13 conversation-ingest consumer, only for a brand-new
  conversation — zero changes needed to the webhook route or WebSocket
  gateway. SLA breach detection is a single periodic Celery-beat sweep
  (not a per-conversation timer) publishing `conversation.sla_breached`
  exactly once per breach type; the escalation *action* itself
  (reassign, notify) is explicitly left to Workflow Engine (M19)/
  Notifications (M21) to consume, not faked here. 25 new tests (171
  total); `ruff check`/`mypy` clean. See
  `docs/architecture/queues-routing.md`.

## Phase 3 — Omnichannel Expansion

- [x] **M15. Email channel** (SMTP/IMAP + provider webhook variants)
  First channel built after the plugin architecture had a second, harder
  data point to prove itself against: provider-agnostic infrastructure
  (SMTP/IMAP are protocols, not one vendor) with genuine inbound identity
  to resolve. Outbound via `aiosmtplib` (async-native, no thread-pool
  wrapping). Inbound has two entry points sharing one MIME parser
  (stdlib `email`, not a bespoke per-ESP format): the existing generic
  webhook route (M11, zero new route), and a new Celery-beat IMAP poll
  task (`infrastructure/tasks/email_imap_poll_task.py`, every 60s) that
  fetches `UNSEEN` messages and marks them `\Seen` — IMAP's own flag *is*
  the idempotency tracker, no separate cursor table. Thread resolution
  via `References`/`In-Reply-To` heuristics. Email is the first channel
  where multi-channel identity resolution (deferred since M8) is actually
  implemented: the conversation-ingest consumer gets-or-creates a
  `Customer` by address via M8's existing `CustomerRepository.get_by_email`
  — real matching, not deferred, because an email address is already an
  unambiguous `Customer` field (WhatsApp/Messenger identity resolution
  remains deferred to M16/M17). `edit_message`/`delete_message`/
  `mark_as_read`/`typing_indicator` are documented no-ops — email has no
  provider-side equivalent. Zero schema changes (`channel_type` stays a
  plain string; M13's `messages`/`message_attachments` already had every
  column needed). 27 new tests (198 total); `ruff check`/`mypy` clean.
  See `docs/architecture/email-channel.md`.
- [x] **M16. WhatsApp Business + Telegram channels**
  Two providers built together because they exercise the plugin
  architecture from opposite directions. WhatsApp needed the provider GET
  handshake (Meta's `hub.challenge`) M11 had explicitly flagged and
  deferred — solved with a new `GET /webhooks/{channel_config_id}` route
  reusing the exact same `verify_signature`/`webhook` hooks every
  provider already has (via `WebhookAck.body`, already designed for
  exactly this), no 12th `ChannelProvider` method needed. Telegram needed
  real customer identity resolution with no natural `Customer` column to
  land on (unlike email's `Customer.email`) — solved by finally building
  the generic `customer_channel_identities` mapping table `Customer`'s
  own docstring predicted since M8, rather than adding another
  special-cased branch to the ingest consumer; every channel from here on
  (Messenger/Instagram/SMS included) resolves through this one
  channel-agnostic path with zero new resolution code. WhatsApp:
  Meta Cloud (Graph) API, real `mark_as_read`, no-op edit/delete/typing
  (platform has no equivalent). Telegram: Bot API, composite
  `chat_id:message_id` ids so real `edit_message`/`delete_message`/
  `typing_indicator` fit the existing single-id ABC signature with no
  interface change. One new migration (`customer_channel_identities`,
  verified against real Postgres — upgrade/downgrade/re-upgrade — not
  only SQLite). 52 new tests (250 total); `ruff check`/`mypy` clean. See
  `docs/architecture/whatsapp-telegram.md`.
- [x] **M17. Facebook Messenger + Instagram channels**
  Two more providers built together — Messenger and Instagram are the
  same underlying Meta "Messenger Platform" (one webhook envelope, one
  Send API), so this is the second concrete case that justified
  extracting shared code rather than a third near-duplicate: an
  unregistered `MetaMessagingProvider` base (send/receive/attachments/
  typing/health-check) with `MessengerProvider`/`InstagramProvider` as
  five-line registered subclasses differing only in which credential key
  names the Graph API node id. WhatsApp's GET-handshake/signature logic
  (M16) was also lifted into shared `_meta_webhook.py` functions and
  WhatsApp refactored onto it (behavior-preserving — its 21 tests re-run
  unchanged) now that a third provider needs the identical logic.
  `mark_as_read` is a no-op (the real `mark_seen` action needs a
  recipient id this ABC method's signature doesn't provide); real
  `typing_indicator` via `sender_action`; no-op `edit_message`/
  `delete_message` (no platform capability); no reply-context field (an
  honest Send API limitation, not built around). No sender display name
  in either platform's webhook — deferred as a documented future
  enrichment, not a gap, since the M16 generic identity-resolution path
  already tolerates a missing name. Zero schema changes. 28 new tests
  (278 total); `ruff check`/`mypy` clean. See
  `docs/architecture/messenger-instagram.md`.
- [x] **M18. SMS channel** (provider-agnostic gateway abstraction)
  Closes out Phase 3. Unlike every other channel so far, SMS has no
  shared vendor protocol (Twilio/Vonage/MessageBird/Plivo all differ) —
  so this is a second, inner plugin layer: `SmsProvider` (registered as
  `"sms"` in `ChannelRegistry`) delegates to whichever `SmsGateway` its
  config names (`SmsGatewayRegistry`, mirroring `ChannelProvider`/
  `ChannelRegistry` one level down). `TwilioGateway` is the first concrete
  gateway — form-urlencoded webhooks (not JSON), and Twilio's own
  HMAC-SHA1/base64-over-the-full-URL signature scheme, which is why
  `WebhookRequest` gained a new `url` field (additive, default `""`, no
  other provider affected) and why a new `settings.public_base_url`
  exists — this stack's backend port is reachable directly alongside
  nginx, so trusting client-supplied forwarded headers for a
  signature-relevant URL would be spoofable; the public scheme+host is a
  fixed setting instead. Outbound MMS is an explicit, documented scope
  boundary (Twilio needs a publicly fetchable media URL our private MinIO
  bucket doesn't have — `send_message` raises rather than silently
  dropping attachments); inbound MMS works fully. `edit_message`/
  `delete_message`/`mark_as_read`/`typing_indicator` are honest no-ops —
  SMS has none of those capabilities at the carrier level. Zero schema
  changes. 21 new tests (299 total); `ruff check`/`mypy` clean. See
  `docs/architecture/sms.md`.

## Phase 4 — Engagement Intelligence

- [x] **M19. Workflow Engine**
  The first module that consumes from the M10 event bus purely as a
  subscriber, no channel concerns at all — and building its trigger
  surface exposed that "assignment changed"/"customer created" (named in
  the original event-bus mandate) were never actually published in every
  path, and the pre-persistence `message.received` had no
  `conversation_id` to trigger on. Fixed with two new events
  (`conversation.created`, `message.persisted`) and two new publish sites
  for `conversation.assignment_changed`/`customer.created` — all
  additive, no existing consumer changed. Condition DSL
  (`domain/workflow_condition.py`): `{"all"/"any": [...]}` trees,
  deliberately not a full expression grammar — visual-builder-friendly by
  construction. Actions are a third application of this codebase's
  "registry keyed by a database-stored string" idiom
  (`WorkflowActionRegistry`, after `ChannelRegistry`/`SmsGatewayRegistry`):
  `add_tag`, `assign_to_queue`, `assign_to_agent`,
  `set_conversation_status`, `send_reply` (reusing
  `ConversationService`'s existing validated logic, not re-derived), and
  `publish_event` (the extensibility escape hatch for future modules).
  `WorkflowEngine` records one `WorkflowRun` per (workflow, event) pair
  unconditionally — matched, failed, or skipped — and publishes
  `workflow.executed`, closing the last event the original mandate named.
  One workflow's failure never affects sibling workflows or the consumer
  loop. Two new tables (`workflow_definitions`, `workflow_runs`); new
  `workflows.read`/`workflows.manage` permissions. 33 new tests (332
  total); `ruff check`/`mypy` clean. See
  `docs/architecture/workflow-engine.md`.
- [x] **M20. Knowledge Base, Quick Replies, Internal Notes**
  Three agent-productivity features, none needing a new architectural
  pattern — straightforward applications of conventions M7/M8/M14 already
  established. Knowledge Base: self-referential `KnowledgeCategory`
  (`SET NULL` on parent delete, detach not cascade) + `KnowledgeArticle`,
  reusing the existing company-scoped `Tag` catalog (M8) via a new join
  rather than a parallel tagging system; search is basic `ILIKE`
  substring matching — semantic/AI-powered search is explicitly an AI
  Engine (M22) concern, not built speculatively. Building this surfaced a
  real async-SQLAlchemy lesson: a just-flushed, never-loaded relationship
  collection can't be lazy-loaded via plain attribute access
  (`MissingGreenlet`) — fixed by assigning tags at construction time
  (transient-object collections are "loaded" from the start), matching
  what `CustomerService.create()`'s own code comment had already
  documented. Quick Replies: company-wide canned responses with a unique
  `shortcut`, explicit-check-before-insert (409, not a raw `IntegrityError`
  500) mirroring `QueueService`'s pattern. Internal Notes: a genuinely
  separate table from `Message` (M13) rather than a third
  `MessageDirection` — a note was never sent through a channel provider
  and has none of a message's delivery/read-status/reopen-logic concerns;
  nested under `/conversations/{id}/notes` reusing the existing
  `conversations.read`/`manage` permissions rather than adding a new one.
  Five new tables; new `knowledge_base.*`/`quick_replies.*` permissions.
  23 new tests (355 total); `ruff check`/`mypy` clean. See
  `docs/architecture/knowledge-quick-replies-notes.md`.
- [x] **M21. Notifications & real-time layer**
  Two halves. First: closed a dormant gap left open since M11/M12 —
  every `ChannelProvider` has implemented `typing_indicator()` since it
  was added, but nothing ever called it. The new agent WebSocket gateway
  (`/ws/agent`, authenticated with the same JWT every REST call uses)
  forwards an agent's typing state to `ConversationService.
  send_typing_indicator` (new), which finally invokes it — completing
  the customer-visible "agent is typing" signal the architecture always
  supported. The same gateway also handles presence (connect flips
  `Agent.status` `OFFLINE`->`ONLINE`, never overriding an explicit
  `AWAY`; disconnect always sets `OFFLINE`) and forwards live
  `Notification` creations. Second: a durable per-user `Notification`
  inbox, created either by a new built-in consumer bound to a fixed set
  of routing keys (`conversation.assignment_changed`/
  `conversation.sla_breached` — unlike the Workflow Engine's `#`, since
  these are first-party notifications every company gets) or by a new
  `create_notification` workflow action (M19's `publish_event` escape
  hatch made concrete). Email dispatch is a Celery-beat sweep over
  `email_dispatched_at IS NULL` — deliberately not a fire-and-forget task
  enqueue, since no precedent for that pattern exists elsewhere in this
  codebase and the outbox/IMAP-poll-style periodic sweep already is the
  established one. New platform-level `settings.smtp_*`, distinct from a
  company's own `EmailProvider` channel credentials, since a notification
  must reach an agent even for a company with no customer-facing email
  channel configured. One new table (`notifications`); no new RBAC
  permission (a personal inbox is gated by authentication alone). 20 new
  tests (375 total); `ruff check`/`mypy` clean. See
  `docs/architecture/notifications.md`.
- [x] **M22. AI Engine**
  One minimal `AiProvider` contract (`complete()` + `health_check()`),
  not one method per feature — every LLM backend shares the same
  fundamental capability, so prompt engineering for all ten AI features
  lives once in `AiService`, shared across the three built-in providers
  (OpenAI, Claude, Ollama), registered via the same
  registry-keyed-by-string idiom `ChannelRegistry`/`SmsGatewayRegistry`/
  `WorkflowActionRegistry` already established. Platform-level
  configuration (`settings.ai_provider`, defaulting to `"disabled"`), not
  per-company — an AI Engine is one shared capability per deployment,
  unlike a company's own WhatsApp number. A disabled/unconfigured
  platform surfaces a new `AiNotConfiguredError` -> 503 consistently
  across every endpoint, never a silent empty result. One new `ai.use`
  permission (not ten) gates all ten endpoints — AI calls have a real
  external per-call cost that justifies an on/off switch, unlike Internal
  Notes' permission-reuse. `suggest_tags` only ever picks from the
  company's real tag catalog (never a hallucinated tag name); Knowledge
  Search and FAQ Search are implemented as one capability
  (`answer_from_knowledge_base`), since this codebase's Knowledge Base
  never modeled a distinct FAQ entity; Next Best Action is advisory-only,
  surfaced to the agent, never auto-executed. Every capability publishes
  an `ai.completed` domain event instead of a dedicated usage-tracking
  table, for M23's AI Reports to consume later. No new tables — a
  permission-seed-only migration. 49 new tests (375 -> 424); `ruff
  check`/`mypy` clean. See `docs/architecture/ai-engine.md`.

## Phase 5 — Reporting & Ecosystem

- [x] **M23. Reports & Analytics**
  Five incremental rollup tables (`conversation`/`agent`/`queue`/`ai`/
  `csat_daily_stats`), fed by a new `reporting-consumer` bound to a fixed
  set of M10 event-bus routing keys — reports aggregate a handful of
  pre-summed rows per date range instead of scanning
  `conversations`/`messages` directly, the concrete payoff of the
  original event-bus mandate at this milestone's target scale. The one
  exception is the Live Dashboard, which queries current
  `agents`/`conversations`/`queues` state directly — a daily rollup can't
  represent "right now," and these tables are small enough that a direct
  query costs nothing. `conversation.updated` gained a `previous_status`
  field so the consumer can detect a genuine transition into
  closed/resolved rather than recounting an already-closed conversation
  on every unrelated update. Customer Satisfaction reuses the existing
  JWT machinery for a new conversation-scoped `TokenType.CSAT` survey
  link (`POST /conversations/{id}/csat-survey-link`,
  `conversations.manage`) and a public, token-gated response endpoint
  (`POST /csat/{id}/respond`, no auth) — no new customer-auth system
  built for one rating per conversation. Every report reuses the
  existing `reports.read` permission (no new permission needed). PDF/
  Excel export (`reportlab`/`openpyxl`, two new runtime dependencies) is
  one generic table-renderer pair shared by every report, not one
  renderer per report type. 34 new tests (424 -> 458); `ruff check`/
  `mypy` clean; migration verified against real Postgres. Also closed a
  pre-existing gap where `workflow-engine-consumer`/`notification-
  consumer` were missing from the production docker-compose overlay
  since M19/M21. See `docs/architecture/reports-analytics.md`.
- [x] **M24. ERPNext Integration**
  One named integration, not a plugin architecture — `ErpClient` is a
  `Protocol` (like `DomainEventPublisher`), not a registry-backed `ABC`
  (like `ChannelProvider`/`AiProvider`), since there's exactly one
  concrete implementation and nothing to register a second entry
  against. `ErpConfig` mirrors `ChannelConfig` exactly (per-company,
  encrypted credentials). Outbound: a new `erp-sync-consumer` binds
  `customer.created` and silently no-ops for the vast majority of
  companies with no ERPNext connection configured, syncing idempotently
  (via a unique `ErpCustomerLink`) for the rest; ERPNext-side failures
  are logged, never re-raised, so a customer's sync failing can't block
  the customer's own creation. Inbound: a doctype-agnostic webhook route
  (`POST /webhooks/erpnext/{id}/{doctype}`, secret verified via a custom
  header — ERPNext has no standardized signature scheme) lands every
  document type in one generic `erp_synced_records` cache table rather
  than six near-duplicate tables, since invoices/orders/quotations/
  tickets/payments/contacts are heterogeneous, read-only, per-company-
  customized shapes only ever displayed. Manual pull
  (`POST /customers/{id}/erp-pull/{doctype}`) shares that same cache for
  backfill/retry. One new `erp.manage` permission (Admin-only) for
  configuring the connection and manual sync/pull; viewing synced
  records reuses `customers.read`. 34 new tests (458 -> 492); `ruff
  check`/`mypy` clean; both migrations verified against real Postgres.
  See `docs/architecture/erp-integration.md`.
- [x] **M25. Administration console**
  Backend only, matching every milestone since M15 — a full frontend
  console is a dedicated future phase, not a sub-task of one backend
  milestone (confirmed explicitly rather than assumed). `Company` gained
  a `settings` JSON blob (like `Customer.custom_fields`) plus
  `GET/PATCH /company`: viewing needs only authentication (shared,
  company-wide info every member already sees), editing needs
  `company.manage` — a permission that has sat in the catalog unused
  since M2, now wired to an actual endpoint and finally added to the
  `Admin` role's default permission set. `GET /admin/plugins` reports
  what's registered across all four registry-keyed-by-string plugin
  systems (channels, SMS gateways, AI providers, workflow actions) plus
  the active AI provider — surfaced a real gap where
  `WorkflowActionRegistry` was only ever populated in the
  workflow-engine-consumer process, never the API process, now fixed
  with a scoped import in the one endpoint that needs it.
  `GET /audit-logs` gained `export=pdf|xlsx`, reusing M23's generic
  table renderers rather than new rendering code. 10 new tests
  (492 -> 502); `ruff check`/`mypy` clean; migration verified against
  real Postgres. See `docs/architecture/administration.md`.

## Phase 6 — Hardening & Launch

- [x] **M26. Security hardening**
  An audit first (see `docs/security/hardening.md`), then fixes for the
  real gaps it found — not a rebuild of what was already solid.
  Confirmed already-solid and left alone: no raw-SQL injection surface
  anywhere (SQLAlchemy parameterized queries exclusively), no XSS
  surface (pure JSON API, no HTML rendering), no CSRF surface
  (bearer-JWT-only, zero cookies), bcrypt password hashing, JWT decode
  with an explicit algorithm allowlist. Gaps closed: rate limiting
  extended to `/auth/refresh`/`/auth/logout` and the public CSAT-respond
  endpoint, plus a new **per-user** (not per-IP) limiter on every
  `/ai/*` endpoint since AI calls carry real external cost and several
  agents can share one office IP; a new `SecurityHeadersMiddleware`
  (X-Frame-Options, X-Content-Type-Options, Referrer-Policy,
  Permissions-Policy always, CSP + HSTS in production only, since
  `/docs`/`/redoc` — real HTML — only exist outside production); a
  startup-time guard rejecting a CORS wildcard origin combined with
  `allow_credentials=True`. A `pip-audit` dependency scan found 27
  vulnerabilities across 8 packages — patched `python-jose` (JWT-bomb +
  algorithm-confusion CVEs, security-critical), `orjson`,
  `python-multipart`, and `aiosmtplib` (the one genuinely exploitable
  finding: unsanitized CRLF in customer-supplied email addresses
  reaching raw SMTP commands) via same-API patch bumps, verified
  against the full test suite; removed the unused `black` dependency
  entirely (superseded by `ruff format` since early in this build,
  never actually invoked) rather than patching a CVE in dead weight.
  Deferred with explicit, documented justification rather than
  silently ignored: a `starlette`/`fastapi` major-version bump (~24
  minor releases behind — its own dedicated upgrade project, not a
  hardening-pass line item), a `pytest` major bump (dev-only, low
  real-world severity), and the `ecdsa` Minerva timing CVE (no fix
  exists upstream; confirmed not exploitable since this platform only
  ever signs JWTs with HS256, never ECDSA algorithms). Wrote
  `docs/security/owasp-asvs-checklist.md` and
  `docs/security/pentest-checklist.md`. 11 new tests (502 -> 513);
  `ruff check`/`mypy` clean; no schema changes. See
  `docs/security/hardening.md`.
- [x] **M27. Observability & DevOps**
  Found and fixed a real, systemic bug while verifying the new Celery
  metrics pipeline against the live stack: all four Celery-beat tasks
  (outbox relay, SLA sweep, IMAP poll, notification email dispatch)
  cache their async engine at module level across `asyncio.run()`-per-
  invocation calls, and a pooled asyncpg connection bound to one
  invocation's (now-closed) event loop crashed the next invocation's
  `pool_pre_ping` — 50+ occurrences in 3 minutes before the fix
  (`engine.dispose()` in a `finally` block on all four), zero after,
  verified against the real running stack. Added `celery-exporter`
  (closing the last exporter gap alongside existing
  postgres/redis/rabbitmq exporters) plus the two Celery config flags
  it needs to receive any events at all; four new Grafana dashboards
  (Postgres, Redis, RabbitMQ & Celery, Logs) alongside the existing
  Backend API one, every metric name verified against real Prometheus
  query results before going into a panel. Six Grafana unified-alerting
  rules (5xx rate, p95 latency, Postgres/Redis down, queue backlog,
  Celery failures), provisioned and confirmed loaded via Grafana's own
  API — contact point is a deliberately obvious placeholder webhook,
  since the real Slack/PagerDuty/email destination is a business
  decision this codebase can't make for itself. Promtail now extracts
  only `level` (5 values) as an indexed Loki label, not `logger` (~90
  values), per Loki's own cardinality guidance. `/health/ready` now
  checks Redis and RabbitMQ alongside Postgres, returning 503 with a
  per-dependency breakdown — the backend's Docker healthcheck now
  points at it instead of plain liveness. Closed a real gap where
  `nginx.prod.conf`'s `/metrics` was publicly exposed with no
  restriction; scoped to private IP ranges. nginx's existing dynamic-
  DNS re-resolution against `backend:8000` already gives coarse-grained
  load distribution across `docker compose up --scale backend=N`
  replicas (documented honestly as DNS-rotation, not per-request
  balancing — a real orchestrator is the next step at higher scale).
  Automated backups (`scripts/backup_postgres.sh`) plus a genuine
  restore drill (`scripts/verify_backup_restore.sh`, restoring into a
  scratch database and sanity-checking it) — both run against the real
  stack as part of this milestone's own verification, not just written
  and assumed to work. `.github/workflows/ci.yml` built from an empty
  `.github/workflows/` directory: lint/test/build/scan jobs for both
  backend and frontend, plus a documented placeholder deploy job gated
  on version tags (no fabricated deploy target). `ruff check`/`mypy`
  clean; 513 tests still passing (one updated in place for the richer
  readiness response, no new test files — this milestone's changes are
  almost entirely infra-layer, verified against the real stack rather
  than through new pytest coverage). See
  `docs/architecture/observability.md`.
- [x] **M28. Performance & load testing**
  A real load test (`scripts/load_test.py`, no new dependency — a ~160-
  line async `httpx` script, not Locust/k6) against the live stack
  surfaced a genuine finding: at concurrency=20, p50 latency balloons
  from 30-45ms (concurrency=3) to 190-370ms, with throughput barely
  rising — the signature of a saturated single dev-mode uvicorn worker,
  not slow application code. Confirmed by comparing against a
  standalone build of the production `--workers 4` target: ~44% higher
  throughput at the same concurrency. Honest caveat documented: this
  sandbox has only 2 CPU cores shared across 18+ containers, so absolute
  numbers aren't production-representative — the qualitative finding
  (worker-count matters; 0% error rate under load) is. `EXPLAIN ANALYZE`
  against the two highest-traffic list queries
  (`ConversationRepository`/`CustomerRepository.list_for_company`) found
  both doing an index scan on `company_id` alone followed by a separate
  in-memory sort before `LIMIT` — invisible at today's row counts, real
  cost at scale. Fixed with two partial, pre-sorted composite indexes
  (migration `f2a3b4c5d6e7`), confirmed via `EXPLAIN ANALYZE` before/
  after that the separate `Sort` node disappears entirely. Caching
  strategy reviewed and validated rather than expanded: RBAC permissions
  are already effectively cached via the JWT's `permissions` claim (zero
  DB round trips per permission check), and the load test didn't surface
  a caching-shaped bottleneck — adding one anyway would be exactly the
  premature optimization this codebase's principles argue against.
  `messages` table partitioning written up as a documented, ready-to-
  execute playbook rather than applied now — partitioning a near-empty
  table is pure risk for zero benefit, and a migration that does nothing
  against near-empty data can't be verified the way every other
  migration in this codebase has been. See
  `docs/architecture/performance.md`.
- [x] **M29. Documentation & production readiness review**
  `docs/api/README.md` — a curated usage guide (auth flow, pagination,
  error shape, rate limits, public-endpoint trust models, a full
  resource index) rather than a hand-duplicated copy of every schema,
  which would drift the moment an endpoint changed; the live
  auto-generated OpenAPI docs (`/docs`, `/redoc`,
  `/api/v1/openapi.json`) remain the authoritative source for exact
  request/response shapes. `docs/database/schema.md` verified
  consistent: 22 migrations on disk, 22 rows in the migration-history
  table, matching `alembic heads`. `docs/deployment/` gained three new
  documents: `runbooks.md` (restart/rebuild/rotate-secrets/scale/
  investigate-a-stuck-queue procedures), `disaster-recovery.md`
  (RTO/RPO targets honestly scoped to this single-host deployment,
  per-dependency failure scenarios and recovery steps, and two real
  gaps surfaced by writing it: backups aren't shipped off-host yet, and
  MinIO/attachment storage has no backup at all), and
  `go-live-checklist.md` — a launch checklist reflecting this build's
  *actual* state rather than a generic template, explicitly calling out
  every open item this session's own milestones left as documented,
  accepted risk (TLS, secrets manager, off-host backups, MinIO backup,
  a real alert destination, a real CI/CD deploy target, and — the
  single largest one — that no frontend UI exists for the vast majority
  of features built across M15-M29, since that entire arc was
  explicitly scoped backend-only per direct confirmation rather than
  assumption). No code changes this milestone; `ruff check`/`ruff
  format --check`/`mypy src` and the full test suite re-verified green
  as this build's final state.

---

**Backend complete.** M0 through M29 are done. Phase 7 below opens the
next arc: the enterprise frontend, using the backend exactly as built —
no new backend endpoints except where a milestone explicitly calls one
out as a small, narrowly-scoped gap the frontend genuinely needs (not a
redesign).

---

## Phase 7 — Enterprise Frontend

Builds the React + TypeScript + MUI SPA against the already-complete
backend. Ordered to deliver one complete, working, end-to-end workflow —
Login → Dashboard → Create Company → Create User → Connect WhatsApp →
Inbox → Conversation View → Reply → Customer Timeline → ERPNext Customer
View → Reports — before polishing secondary pages (Departments, Teams,
Queues, Routing Rules, Workflows, Knowledge Base, Quick Replies). See
`docs/architecture/frontend.md` for the full architecture.

- [x] **M30. Frontend core infrastructure**
  Fixed a real bug in the original scaffold: `features/auth/api.ts`
  assumed `POST /auth/login`'s response included a `user` object — it
  doesn't (tokens only, confirmed against the live backend). `GET
  /auth/me` is now the one source of truth for user/roles/permissions,
  fetched via React Query (`features/session/`) and gated through
  `ProtectedRoute`'s loading state so authenticated navigation never
  flashes the wrong items. Added `features/auth/RegisterPage.tsx` (the
  golden path's "Create Company" step — `POST /auth/register`, which
  creates the company, Owner user, and default roles in one call and
  auto-authenticates), an RBAC-aware sidebar (`features/layout/`,
  `RequirePermission`, a 403 page), and the shared primitives every
  later page builds on: `DataTable` (MUI X Data Grid, new dependency,
  server-side pagination against this API's `Page<T>` shape),
  `FormDialog`, `ConfirmDialog`, `EmptyState`/`ErrorState`/`LoadingState`,
  and pagination/error-extraction helpers. Replaced the scaffold's
  `DashboardPage` (hardcoded zeros) with a real one backed by `GET
  /reports/live-dashboard`.

  Added MSW + `vitest-axe` to the test stack (`vitest-axe`'s own
  `extend-expect` entry point ships an empty build in the installed
  0.1.0 — worked around by calling `expect.extend` directly against
  `vitest-axe/matchers` and bridging its types onto `@vitest/expect`'s
  `Matchers` interface, since Vitest 4 moved matcher augmentation off
  the older global `Vi` namespace that package's types still target).
  19 tests passing (component/integration tests against MSW-mocked
  responses, an accessibility assertion on the login page, and unit
  tests for the rewritten `authSlice` and the new error-extraction
  helper). `tsc -b`, `eslint`, `prettier --check`, and a production
  build (`npm run build` and the real `docker/nginx/Dockerfile` image)
  all clean.

  Verified against the live dev stack, not just MSW mocks: registered a
  real company via `POST /auth/register` through nginx, confirmed
  `/auth/login`, `/auth/me`, and `/reports/live-dashboard` responses
  match the hand-authored TypeScript types byte-for-byte. That pass also
  caught a real documentation bug from M29 — `docs/api/README.md`
  claimed `GET /health`/`GET /health/ready` were unversioned like
  `/metrics`; they're actually mounted under `/api/v1` like every other
  endpoint (only `/metrics` is genuinely registered outside it) — fixed
  alongside this milestone since the same verification pass surfaced it.
- [ ] **M31. Golden path — Company settings, Agents**
  Company settings page (`GET`/`PATCH /company`), Agents (Users)
  list/create/edit — the first "Create User" step of the golden path.
- [ ] **M32. Golden path — Channels (Connect WhatsApp)**
  Channel config list/create/edit with per-`channel_type` dynamic
  credential fields (WhatsApp first-class: `phone_number_id`,
  `access_token`, `verify_token`; generic JSON editor fallback for other
  types), webhook URL + verify-token display for pasting into Meta's App
  Dashboard.
- [ ] **M33. Golden path — Inbox, Conversation View, Reply**
  Conversation list (status filter, pagination), conversation detail
  (message thread, send reply, attachment upload, internal notes,
  assign agent/queue), the notification bell + `/ws/agent` realtime
  wiring (typing indicators, live notification push backed by
  `GET /notifications` polling as the durable source of truth).
- [ ] **M34. Golden path — Customer Timeline, ERPNext Customer View**
  Customer profile page and a composed timeline (conversations + notes +
  audit trail — there's no single backend timeline endpoint, confirmed by
  design). Adds one narrowly-scoped backend addition: an optional
  `customer_id` filter on `GET /conversations` (a query param + repository
  filter, no schema change — the existing single-column `customer_id`
  index already covers it) since composing a customer's conversation
  history without one means scanning the whole company's list
  client-side. ERPNext tab: `/erp-configs` setup admin page plus the
  customer's synced records/manual-pull view, rendered generically since
  the backend is doctype-agnostic (`data: dict[str, Any]` per record).
- [ ] **M35. Golden path — Reports**
  Reports hub covering all eight report endpoints (executive, live, agent,
  conversations, performance, queues, SLA, CSAT, AI), date-range picker,
  PDF/Excel export buttons wired to the existing `export=pdf|xlsx` query
  param, charts per the dataviz design system.
- [ ] **M36. Docker deployment verification + golden-path smoke test**
  Verifies `npm run build` against the real production
  `docker/nginx/Dockerfile` target and runs the full golden-path workflow
  against the live `docker compose` stack end-to-end, fixing anything the
  smoke test surfaces.
- [ ] **M37. Polish — accessibility, responsive, secondary pages**
  Full `vitest-axe` sweep, responsive/mobile breakpoint pass, RTL
  verification, and the remaining CLAUDE.md-listed features not on the
  golden path (Departments, Teams, Queues, Routing Rules, Workflows,
  Knowledge Base, Quick Replies, Internal Notes as a standalone view,
  Notifications inbox page, Audit Logs viewer).

---

## Working agreement

1. One milestone in progress at a time; mark `[~]` here when started.
2. Every milestone ships with unit + integration tests passing before commit.
3. Every milestone gets a dedicated commit (or small set of commits) with a
   message describing what was delivered.
4. Architecture decisions that deviate from this roadmap are recorded in
   `docs/architecture/`.
5. This file is updated as part of each milestone's commit.
