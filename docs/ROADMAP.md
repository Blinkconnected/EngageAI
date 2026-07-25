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
- [x] **M31. Golden path — Company settings, Agents**
  Company settings page (`features/company/`) — name editing via
  `PATCH /company`, read-only slug/status display. Agents page
  (`features/agents/`) — the golden path's "Create User" step: a
  `DataTable`-backed list, create dialog (email/full name/initial
  password/title/department), edit dialog (title/department/status),
  and delete with confirmation, all against the real `agents.read`/
  `agents.manage`-gated endpoints. Added a minimal read-only
  `features/departments/` (list-only, page_size=100 for the department
  picker) rather than building full department management now — a
  dedicated Departments CRUD page is deferred to the M37 secondary-pages
  polish milestone, since organizations rarely have more than a handful
  and a full-list fetch is proportionate today. Both new nav entries are
  permission-gated (`agents.read`, `company.manage`) and match the routes'
  own `RequirePermission` guards, so there's never a visible link to a
  page the current user would be redirected away from.

  Along the way, fixed a newer `eslint-plugin-react-hooks` rule
  (`set-state-in-effect`, not present in the version active during M30's
  initial setup review) flagging the common "seed local form state from
  a query result via `useEffect`" pattern in both the agent-edit dialog
  and the company settings form — refactored to the key-based remount
  pattern (edit dialog) and a child component seeded directly from props
  (company form) instead, per React's own guidance, rather than
  suppressing the rule.

  8 new tests (list/create/edit/delete/accessibility for Agents, view/
  accessibility/save for Company settings — 19 → 27 total), all against
  new MSW handlers including a stateful in-memory agents mock (reset
  per-test). Verified against the live dev stack: registered a test
  agent and renamed a test company through the real API, confirming
  every response shape matches the hand-authored types exactly.
- [x] **M32. Golden path — Channels (Connect WhatsApp)**
  `features/channels/`: a `DataTable`-backed list, a connect dialog with
  a guided WhatsApp form (`phone_number_id`, `access_token`,
  `verify_token` — field names verified against the real
  `WhatsAppProvider` source, not just the API schema) and a generic
  JSON credentials editor fallback for the other five registered channel
  types (`telegram`, `messenger`, `instagram`, `email`, `sms`,
  `web_chat`), and an edit dialog with a collapsible "update
  credentials" section (credentials/`webhook_secret` are write-only and
  never echoed back, so editing never pre-fills them — confirmed against
  `ChannelConfigResponse`, which deliberately excludes both fields).

  Since the API never returns a pre-built webhook URL, the frontend
  constructs it itself: `${window.location.origin}/api/v1/webhooks/
  {id}` — correct because the browser's own origin is already the
  publicly-reachable one nginx proxies `/api/` through, unlike the
  backend's own `PUBLIC_BASE_URL` setting (which exists only because the
  backend has no "browser origin" to infer from). Verified end-to-end
  against the live stack: created a real WhatsApp channel config through
  the API, then called `GET /api/v1/webhooks/{id}?hub.mode=subscribe
  &hub.verify_token=...&hub.challenge=12345` with the exact
  `window.location.origin`-based URL format the UI displays and
  confirmed Meta's handshake echoes the challenge back — the URL the
  admin is told to paste into Meta's dashboard actually works.

  5 new tests (list/create-with-instructions/edit/delete/accessibility
  — 27 → 32 total). Also bumped Vitest's default 5000ms per-test timeout
  to 15000ms (`vite.config.ts`) after intermittent timeouts surfaced
  running MUI X Data Grid + dialog interaction tests concurrently across
  files on this sandbox's constrained (2-core, per M28) hardware —
  confirmed as CPU contention, not a real bug, by re-running the
  isolated file successfully before the fix and the full suite twice
  stably after it.
- [x] **M33. Golden path — Inbox, Conversation View, Reply**
  `features/conversations/`: an Inbox (status tabs, `DataTable`,
  customer/channel/agent names resolved via small lookup hooks) and a
  Conversation View (message thread with bubble styling and a
  100-message "load older" cap — documented, not silent — a reply box
  with attachment upload and throttled typing-indicator sends, an
  internal notes tab, and a sidebar with status/assign-agent/assign-queue
  controls). `features/notifications/` (bell + unread badge + mark-read)
  and `features/realtime/` (one `/api/v1/ws/agent` WebSocket per session,
  mounted in `AppLayout` — not per-conversation, since connecting/
  disconnecting flips agent presence) round out realtime per the
  architecture doc's own two-tier design.

  Fixed one small, narrowly-scoped backend gap required for this
  milestone: `PATCH /conversations/{id}` accepted `queue_id` in its
  schema and the service already applied it, but the endpoint never
  forwarded `payload.queue_id` through — queue reassignment silently
  no-opped. One-line fix plus a regression test (514 → 515 backend
  tests).

  **Found and fixed a severe, previously-undiscovered production bug**
  while doing this milestone's live verification (see
  `docs/architecture/event-bus.md`'s new incident section for the full
  writeup): `GUID.process_result_value` used `isinstance(value,
  uuid.UUID)`, which is `True` for asyncpg's own UUID subclass — so it
  passed through unconverted, working everywhere *except* the outbox
  relay's direct `orjson.dumps()` call, which only accepts the exact
  `uuid.UUID` type. Every outbox row with a non-null UUID field had been
  silently failing to publish since the `GUID` type was introduced (M2);
  compounding this, `claim_batch`'s uncapped FIFO reclaiming meant the
  same permanently-failing oldest rows (confirmed live: one row had
  reached 14,586 attempts, roughly 20 hours) starved every healthy event
  created since from ever being claimed at all — the entire event-bus-
  dependent surface (audit logging, reporting, conversation ingestion,
  notifications, workflow triggers, ERP sync) had been silently broken.
  No existing test caught it because every consumer test exercises
  handlers directly against fabricated event dicts, never the relay's
  real `orjson.dumps()` path against real asyncpg-typed columns.

  Fixed both the root cause (exact-type check instead of `isinstance`)
  and the severity multiplier (a `max_attempts` dead-letter guard on
  `claim_batch`, so one poisoned event can only ever cost a bounded
  number of wasted ticks, never bring down the whole relay again).
  Verified live: before the fix, 0 of ~1,400 outbox rows had
  `dispatched_at` set; after restarting the affected containers, 1,317
  drained within seconds and exactly the 100 rows already past the new
  cap were correctly excluded. The golden-path conversation created
  during this investigation (via the real web-chat WebSocket) flowed
  through end-to-end — list, messages, reply, status change, and an
  internal note all worked exactly as the frontend expects. Six new
  regression tests added (514 → 520 backend tests): five isolated
  `GUID` type-conversion tests (`tests/unit/test_guid_type.py`) and one
  simulated-poison-event dead-letter test.

  10 new frontend tests (32 → 42), plus the six new backend regression
  tests above. Verified the WebSocket path live too: nginx's `/api/`
  location had no `Upgrade`/`Connection` proxy headers, so *both*
  realtime WebSocket routes (`/api/v1/ws/agent` and the pre-existing
  `/api/v1/web-chat/ws/{id}`) were unreachable through nginx even though
  the backend itself was fine — fixed by adding those headers to the one
  `/api/` location (harmless for ordinary requests) and pointing
  `VITE_WS_BASE_URL` at the real `/api/v1/ws` prefix instead of a
  `/ws` prefix that was never actually registered on the backend.
- [x] **M34. Golden path — Customer Timeline, ERPNext Customer View**
  `features/customers/`: a browsable Customer directory (search, `Customers`
  nav entry) and a Customer profile page — header (name, email/phone,
  tags, notes, edit dialog), a Timeline tab composed client-side from the
  customer's conversations (there's no single backend timeline endpoint,
  confirmed by design), and an ERPNext tab. `features/erp/`: an admin
  connect/disconnect page (`/erp-configs`) and a per-customer panel
  showing synced records rendered generically (`ErpRecordCard` renders
  whatever key/value pairs the raw ERPNext document actually has, since
  the backend is doctype-agnostic by design — no fixed schema per
  doctype), plus sync-now and pull-by-doctype actions. The conversation
  sidebar's customer name (M33) now links to this page.

  Added the one narrowly-scoped backend gap this needed: an optional
  `customer_id` filter on `GET /conversations` (query param + repository
  filter, no schema change — the existing single-column `customer_id`
  index already covers it), since composing a customer's conversation
  history without one meant scanning the whole company's list
  client-side. One new backend regression test (520 → 521).

  Found and fixed one test-fixture bug of its own during this milestone:
  the MSW `customers.ts` mock never had a `PATCH` handler (it was only
  ever a `GET`-only stub from M30, before customer editing existed), so
  the new "edit customer" test's mutation had nowhere to succeed — caught
  because it failed *consistently* across two independent runs, including
  one under severe memory pressure, which is what separated it from that
  run's other seven failures (all resource-contention flakiness that
  vanished on a clean, isolated re-run — this sandbox's 3.7GB/2GB-swap
  ceiling can't sustain the full frontend and backend suites running
  concurrently; re-running them serially is the fix, not a code change).

  10 new frontend tests (42 → 52). Verified live against the real
  backend: the new `customer_id` filter correctly scopes conversations
  (confirmed both the matching and non-matching case), a real customer
  edit persisted, and `POST/GET /erp-configs` round-tripped exactly as
  the frontend expects.
- [x] **M35. Golden path — Reports**
  `features/reports/ReportsPage.tsx`: a single tabbed hub (`/reports/:tab?`,
  `reports.read`, new `Reports` nav entry) over all eight report endpoints
  — Executive, Conversations, Agent Performance, Queues, SLA, CSAT, AI
  Usage, plus an agent-only "My Performance" tab (hidden unless the
  current user's roles include `Agent`; the backend 404s `agent-dashboard`
  for anyone without an Agent profile, handled as an `EmptyState` rather
  than an error). One shared `DateRangeFilter` (plain `<input type=date>`
  fields plus 7d/30d/90d presets — no `@mui/x-date-pickers`/`dayjs` added
  just for two date fields) drives every tab, defaulting to the last 30
  days. Added **`@mui/x-charts`** (Community, same major version as
  `@mui/x-data-grid`) for Bar/Line/Pie charts rather than a third-party
  charting library, to stay inside the existing MUI theming system. Report
  result sets are small, fully-loaded arrays (not the paginated `Page<T>`
  shape `DataTable` wraps), so table panels use a new `ReportDataGrid` —
  client-side sort/paginate, no server round-trip. Export
  (`?export=pdf|xlsx`) downloads via `apiClient` with `responseType: 'blob'`
  (so it still carries the Authorization header) into a temporary
  object-URL `<a download>`.

  Found and fixed two real accessibility bugs via `vitest-axe`, not just
  compiled-and-shipped: `StatCard`'s numeric value used `variant="h4"`
  (rendering an actual `<h4>`) directly under the page's `<h1>`, and every
  panel's card-section `Typography variant="subtitle1"` renders as `<h6>`
  by MUI's default variant mapping — both skipped heading levels
  (axe's `heading-order` rule). Fixed by giving `StatCard` `component="p"`
  (a stat value isn't a heading) and promoting the section titles to
  `component="h2"` (the correct next level under `<h1>`), rather than
  weakening or deleting the check.

  Also re-hit the container `node_modules`-named-volume gotcha from M32
  (`docker compose exec frontend npm install` + `docker compose restart
  frontend` needed after adding the new dependency — now called out in
  `docs/deployment/local-development.md`'s Troubleshooting section so it
  isn't rediscovered a third time).

  5 new frontend tests (52 → 57). Verified live against the real backend
  (not just MSW): `executive-dashboard` and `conversations` return correct
  company-scoped data for the seeded demo conversations; `export=pdf`
  returns a genuine `%PDF-1.4` binary with the right `Content-Disposition`
  filename, `export=xlsx` a genuine `PK\x03\x04` (zip) binary; the Owner
  gets `404` from `agent-dashboard` (no Agent profile) while the seeded
  Agent gets `200` with their own stats — confirming the "My Performance"
  tab's visibility gate (`roles.includes('Agent')`) matches the backend's
  actual 404 condition rather than guessing at it.
- [x] **M36. Docker deployment verification + golden-path smoke test**
  Treated as a full production-release validation, not just a Docker
  sanity check — the entire `docker-compose.yml` + `docker-compose.prod.yml`
  overlay was brought up for real (runtime-target images, compiled SPA,
  `ENVIRONMENT=production`/`DEBUG=false`, no bind mounts, no dev servers),
  and every golden-path step was exercised against it end to end. Four
  real, previously-undiscovered production bugs were found and fixed —
  this milestone existed specifically to catch exactly this class of
  issue, and it did:

  1. **Migration chain couldn't actually run from empty.** An isolated
     throwaway-Postgres fresh-migration test (no risk to real data) hit a
     `UniqueViolationError` on `permissions.code`: the very first
     migration (`f2df1379a476`) seeds permissions by importing the *live*
     `domain.rbac.PERMISSIONS` list — which today already includes every
     permission six later "seed X permissions" migrations
     (`5463a5076e76`, `7c6ca45d6fac`, `a7b8c9d0e1f2`, `c3d4e5f6a7b8`,
     `d0e1f2a3b4c5`, `e5f6a7b8c9d0`) also hardcode. Every environment so
     far was built incrementally over the life of the project, so this
     never triggered — only a true from-scratch deploy on today's code
     hits it. Fixed by switching those six migrations' inserts to
     `INSERT ... ON CONFLICT (code) DO NOTHING`; re-verified clean (29
     permissions, 0 duplicates) on a fresh DB, and confirmed a no-op
     against the already-migrated demo database. Full backend suite
     re-run green after the fix: 522 passed.
  2. **`npm run build` (the real production build command) failed —
     `npx tsc --noEmit` had been silently checking zero files.** This
     repo's frontend `tsconfig.json` is solution-style (`files: []` +
     `references`), so bare `tsc --noEmit` (used to "verify" M35's
     typecheck) resolves no input files and exits 0 having checked
     nothing — confirmed via `--listFiles`. The real command
     (`tsc -b`, what `npm run build` and the CI-run `npm run typecheck`
     both actually use) caught 4 genuine type errors in the M35 Reports
     panels: `@mui/x-charts`'s `dataset` prop needs
     `{[key: string]: T}`, which named interfaces
     (`CsatDailyRow`/`AgentPerformanceRow`/`QueueStatsRow`) don't
     structurally satisfy, unlike a fresh object literal. Fixed by
     mapping into fresh literals (`rows.map(row => ({...row}))`) at the
     four call sites. **Process lesson, not a CI gap**: CI's own
     `npm run typecheck` was already correct; the miss was mine, running
     an ad-hoc `tsc --noEmit` instead of the project's real script —
     always use the project's own defined commands, never an
     approximation, especially for project-reference ("solution-style")
     TypeScript configs.
  3. **Every Celery/consumer container reported permanently
     "unhealthy."** `docker/backend/Dockerfile`'s `runtime` stage bakes
     in a `HEALTHCHECK` that curls the web server on `:8000` — correct
     for `backend`, wrong for `celery-worker`/`celery-beat` and all 6
     RabbitMQ event-bus consumers, which build from the same image/target
     but run a Celery or standalone-consumer process, never a web server.
     A false "unhealthy" on 7 containers, permanently, on every
     production deployment — the kind of thing that trains operators to
     ignore health status. Fixed in `docker-compose.prod.yml`: a real
     `celery inspect ping` healthcheck for `celery-worker` (confirmed
     genuinely healthy), and `healthcheck: disable: true` for
     `celery-beat` and the 6 consumers (none have an HTTP or CLI-pingable
     surface; `restart: always` plus the existing `celery-exporter`
     Prometheus metrics are what actually cover their liveness).
  4. **nginx's own healthcheck always failed.** The production nginx
     image's `/etc/hosts` maps `localhost` to `::1` only (no IPv4 entry),
     while `nginx.prod.conf` only has `listen 80;` (IPv4) — so
     `wget http://localhost/` inside the container always hit
     connection-refused on `[::1]:80`, even though nginx correctly served
     every real request on `0.0.0.0:80` throughout. Confirmed via
     `getent hosts localhost` and a manual `wget http://127.0.0.1/`
     succeeding where `http://localhost/` failed. Fixed by pointing
     `docker/nginx/Dockerfile`'s `HEALTHCHECK` at `127.0.0.1` explicitly.

  **Full golden path smoke-tested against the real production stack**
  (login/register through audit log — no dev server involved anywhere):
  Create Company (`POST /auth/register`, a brand-new company, not the
  seeded demo) → Login → `GET /auth/me` → Dashboard (live) → Create User
  (agent) → Create Customer → Connect WhatsApp (guided credentials form) →
  connect a Web Chat channel → simulate a real customer message over its
  WebSocket → confirm the conversation is created **asynchronously**
  (outbox → 5s Celery-beat relay tick → RabbitMQ → conversation-ingest-
  consumer — not a synchronous DB write in the WS handler; the smoke
  test's first attempt asserted this instantly and correctly failed,
  fixed by polling) → agent reply → Customer Timeline
  (`GET /conversations?customer_id=`) → connect an ERPNext config →
  per-customer ERP records endpoint (empty, correctly, no real ERPNext
  instance) → Executive Dashboard report (same async-relay latency as
  conversation ingestion, one more hop through `reporting-consumer`) →
  PDF export (genuine `%PDF-1.4` binary) → Excel export (genuine `PK`
  zip binary) → Audit Log (`GET /audit-logs`, 12 real entries spanning
  `company.registered` through `message.sent`, proving the outbox/relay/
  consumer pipeline works end to end under `ENVIRONMENT=production`, not
  just in dev).

  **Persistence validated across a real restart**: uploaded a real
  attachment (`POST /conversations/{id}/attachments`), restarted
  `backend`/`postgres`/`minio`/`rabbitmq`/`redis`/`nginx` together, then
  confirmed — after backend re-passed its healthcheck — that login,
  agents, customers, channels, the conversation, both messages, the ERP
  config, the full audit log history, *and* the uploaded attachment's
  actual bytes (a genuine MinIO object-storage durability check, not just
  a Postgres metadata row) all survived unchanged.

  **Production hardening confirmed, not assumed**: compiled SPA with no
  Vite client/dev artifacts; `/docs`/`/redoc` return 404 (correctly
  disabled via `settings.is_production`); `Content-Security-Policy`/
  `Strict-Transport-Security` headers present (production-only, per
  `core/security_headers.py`); backend running as `uvicorn ... --workers 4`
  with no `--reload`, no bind mounts, non-root `blinkengage` user
  (confirmed via `docker top`/`docker inspect`, since the lean runtime
  image has no `ps`).

  **Two gaps flagged, not silently fixed, since fixing them here would be
  scope creep or a business/ops decision, not a code bug**:
  - **This sandbox's live `.env` still has 7 literal `change-me-...`
    placeholder secrets** (`POSTGRES_PASSWORD`, `DATABASE_URL`,
    `RABBITMQ_DEFAULT_PASS`, `RABBITMQ_URL`, `MINIO_ROOT_PASSWORD`,
    `S3_SECRET_KEY`, `GF_SECURITY_ADMIN_PASSWORD`) — confirmed via direct
    inspection. Functionally harmless for this sandbox (nothing here
    depends on their *values* being unguessable) but a real, concrete
    launch blocker for any actual internet-facing deployment. Rotating
    `POSTGRES_PASSWORD` on an already-initialized cluster needs an
    in-database `ALTER USER` alongside the `.env` edit, not just a file
    change — a coordinated rotation, correctly out of scope for this
    verification pass to perform live against the demo data. Added to
    `docs/deployment/go-live-checklist.md`.
  - **This environment is already reachable from the public internet**:
    nginx's access log, during this milestone, showed real external IPs
    (Microsoft/Bing crawler ranges) requesting old dev-mode paths
    (`/src/...`, `/node_modules/.vite/deps/...`) with 200 responses (the
    SPA's `try_files ... /index.html` fallback, not an actual leak of
    those files) — meaning this sandbox's port 80 has live, unsolicited
    internet traffic hitting it right now, over plain HTTP, no TLS. TLS
    absence was already a known `go-live-checklist.md` gap; this is live
    confirmation it's not theoretical. Outside this codebase's control
    (network/firewall/hosting-layer, not application code) — flagged
    prominently rather than acted on unilaterally.

  Left behind in the shared dev/demo database: four inert, fully
  isolated throwaway companies (`M36 Prod Validation Co`..`Co 4`) created
  while smoke-testing "Create Company" against a fresh tenant each retry
  — company-scoped RBAC means they're invisible to and non-interfering
  with the `Blink Demo` company; harmless to leave, droppable via
  `docker compose down -v` + reseed if a pristine environment is wanted.

  After verification, `.env` and the running stack were switched back to
  `ENVIRONMENT=development` (the environment `docs/deployment/
  demo-guide.md` documents and the user has been validating against) —
  confirmed the original `Blink Demo` company/login and Swagger UI both
  still work exactly as before. Frontend suite re-run green after the
  chart-type fixes: 57 passed.
- [ ] **M37. Polish — accessibility, responsive, secondary pages**
  Full `vitest-axe` sweep, responsive/mobile breakpoint pass, RTL
  verification, and the remaining CLAUDE.md-listed features not on the
  golden path (Departments, Teams, Queues, Routing Rules, Workflows,
  Knowledge Base, Quick Replies, Internal Notes as a standalone view,
  Notifications inbox page, Audit Logs viewer).

**Standing gate opened 2026-07-24, immediately after M36**: the user
requested a complete Channel Integration Design Specification before any
further channel-connection-flow implementation or polish — delivered at
`docs/architecture/channel-integration-spec.md`, documenting the actual
current state of all 7 channels (connection method, required fields,
auth flow, webhook registration, token refresh, verification, error
handling, reconnection, wizard UX, security, multi-tenancy — grounded in
source with file:line references, not assumed) plus a scoped, tiered
proposal for closing the gaps found (no send-failure visibility, no
"Test connection" UI despite every provider already having a working
`health_check()`, guided forms for only 1 of 7 channels, no server-side
credential validation, no webhook auto-registration, no token-refresh/
expiry awareness, no OAuth). Gate closed 2026-07-25: Section 3a approved
and implemented as Phase 1 below.

- [x] **Phase 1: Channel Experience (2026-07-25)**
  Implements Section 3a of the approved spec for the 4 priority channels
  (WhatsApp Cloud API, Web Chat, Telegram, Email): guided per-channel
  setup wizard, server-side credential-shape validation before save,
  "Test Connection" (both pre-save/ephemeral and against an already-saved
  channel), periodic health-monitoring sweep (Celery beat, 5-minute
  cadence, transition-only logging), structured send-failure diagnostics
  surfaced in the conversation UI, a reconnect flow (rotate credentials
  on an existing channel), and a connection-log timeline per channel.
  Backend: migration adding `channel_configs.last_health_status/
  last_health_checked_at/last_health_detail` and the new
  `channel_connection_logs` table; `ChannelConnectionLogRepository`;
  `ChannelProviderFactory.build_ephemeral()` for pre-save testing;
  3 new `channel-configs` routes (`POST .../test-connection`,
  `POST .../{id}/test-connection`, `GET .../{id}/connection-logs`);
  `channel_health_check_task` Celery task. Frontend: a shared guided-
  wizard architecture (`ChannelCreateDialog`/`ChannelEditDialog` +
  per-channel field components), `TestConnectionButton`,
  `ChannelHealthBadge`, `ConnectionLogsDialog`, and inline error
  diagnostics on failed sends in `MessageThread`/`ReplyBox`.

  An Ultracode adversarial review (4 independent dimensions — backend
  correctness, security, frontend correctness, spec consistency — each
  finding separately re-verified against the actual code) found 14
  confirmed issues before this shipped, including two critical ones now
  fixed: `send_reply`'s failure handler only caught `httpx.HTTPError`/
  `ValueError`, so real SMTP/Redis/malformed-URL failures still surfaced
  as unhandled 500s instead of the graceful diagnostic Phase 1 exists to
  provide; and a live credential-leak path where a provider's own
  `health_check()` embeds a credential in its error text (confirmed for
  Telegram, WhatsApp and Messenger/Instagram, whose bot token/access
  token sits in the request URL an `httpx.HTTPStatusError` echoes back
  verbatim) — that text was persisted into 3 newly-broadly-readable
  surfaces (`ChannelConnectionLog.message`, `ChannelConfig.
  last_health_detail`, a `Message.message_metadata`) any `channels.read`/
  `conversations.read` principal could see. Fixed via a single shared
  `redact_credentials()`/`safe_health_check()` boundary
  (`infrastructure/channels/error_sanitizer.py`) applied everywhere
  provider error text becomes a stored or returned string. Also fixed: a
  functional regression where the auto-generated `webhook_secret` (and,
  for WhatsApp, `verify_token`) was never surfaced back to the operator
  after creation — meaning Telegram/Email channels literally could not
  receive webhooks if the operator followed the setup wizard's own
  "leave blank to auto-generate" guidance — via a `ChannelConfigCreateResponse`
  schema returned only from `POST /channel-configs`, the one moment a
  server-generated secret is allowed to leave the server at all.

  Live Docker verification (production build, full stack) surfaced one
  further bug the review and both test suites had missed: the periodic
  health-monitoring sweep and the IMAP-poll task both run in the
  standalone `celery-worker`/`celery-beat` processes, which never
  imported `infrastructure.channels.providers` — the module whose import-
  time `@ChannelRegistry.register(...)` decorators are what make any
  channel type resolvable at all. Every channel type therefore raised
  "Unknown channel type" in those processes from the day Phase 1's sweep
  task was written, silently. Fixed structurally, not with another ad hoc
  import: `infrastructure/channels/factory.py` — the one class whose job
  is "look up a registered provider" — now imports the providers package
  itself at module level, so registration no longer depends on which
  entrypoint happens to remember to trigger it.

  Two lower-severity gaps found in review were deliberately deferred
  (documented in `channel-integration-spec.md`'s "Phase 1 implementation
  notes" section, not silently dropped): full SSRF host/IP restriction on
  operator-supplied credential hosts, and the existing `400`-flat-string
  vs `422`-field-level convention for credential validation errors —
  both judged broader-than-Phase-1-scope, proportionate follow-ups rather
  than blocking issues.

  Backend: 557 passed (`pytest -q`), `ruff check`/`mypy src` clean.
  Frontend: 65 passed (`vitest run`), `tsc -b --noEmit`/`eslint .` clean.
  Verified against the production Docker Compose stack (`docker-compose.yml`
  + `docker-compose.prod.yml`, built images only): created and tested
  WhatsApp/Telegram/Email channels end-to-end via the live API, confirmed
  `webhook_secret`/`verify_token` are returned once on create and never
  again on GET, manually triggered `check_channel_health` on the rebuilt
  `celery-worker` and confirmed all 18 active channels resolved correctly
  with the leaked-token scenario now redacted in both `ChannelConfig.
  last_health_detail` and the connection-log timeline.

---

## Sprint 2 — Pilot Feedback & UX Improvements

Started 2026-07-25. Explicit scope: polish the existing product for real
customer use — no new major features. Ten items in priority order, each
its own commit.

- [x] **Item 1: Password Management (2026-07-25)**
  Owner/Admin can reset any agent's password directly
  (`POST /agents/{id}/password`, gated by the existing `agents.manage`
  permission — no new "Owner-only" concept invented); every agent can
  change their own password from a new **My Profile** page
  (`POST /auth/me/password`, always requires the current password).
  Both flows revoke every one of the affected user's refresh tokens via
  the existing `RefreshTokenStore.revoke_all_for_user` (self-service also
  revokes the session making the request — the client logs out and
  redirects to `/login` with a flash message). Both publish a
  `DomainEvent` (`agent.password_reset` / `user.password_changed`), so
  both land in the audit log for free via the existing outbox → audit-log
  consumer pipeline, per the milestone's requirement — no new
  audit-writing code needed.

  Backend: `AuthService.change_password`, `AgentService.reset_password`,
  reused the existing `validate_password_strength` schema validator (same
  10-char/letter/digit rule as registration and agent creation — no new
  policy invented). Frontend: `ProfilePage` (routed at `/profile`, linked
  from the account menu), `AgentResetPasswordDialog` wired into the
  Agents grid's row actions, and a flash-message banner on `LoginPage`
  for the post-change redirect.

  10 new backend tests (self-service success/wrong-current-password/
  weak-password/unauthenticated, admin reset success/cross-agent-403/
  weak-password, refresh-token revocation for both flows, audit-log
  entries for both event types) plus 5 new frontend tests (profile
  display, accessibility, change-password success/redirect, mismatch
  validation, agent-grid reset-password flow). No migration needed — both
  flows write to `users.hashed_password`, which already existed.

  Backend: 567 passed, ruff/mypy clean. Frontend: 70 passed, tsc/eslint
  clean. Verified live against the production Docker stack: created a
  test agent, logged in with its initial password, had the Owner reset
  it, confirmed the old password now 401s and the new one works, then
  self-service-changed it again as the agent and confirmed the same,
  and confirmed both `agent.password_reset` and `user.password_changed`
  rows appear in `GET /audit-logs` with the correct actor.

- [x] **Item 2: Departments (2026-07-25)**
  A complete Departments management page — the backend CRUD API, RBAC
  permissions (`departments.read`/`departments.manage`) and audit events
  already existed from an earlier milestone (only the frontend page was
  ever missing, deliberately deferred at the time). New: `DepartmentsPage`
  (routed at `/departments`, linked from the sidebar) with full
  create/edit/(soft-)delete, an Active/Inactive toggle, and a
  per-department agent-count chip that opens a read-only membership list.
  Assignment itself stays on the existing Agent form's "Department"
  picker (the one place that already writes `Agent.department_id`)
  rather than building a second, divergent mutation path for the same
  relationship — the Departments page's job is visibility and lifecycle
  management, not duplicating assignment UI.

  Live verification surfaced a real backend bug: `Agent.department_id`'s
  FK declares `ondelete="SET NULL"`, but department deletion is a *soft*
  delete (`UPDATE ... SET deleted_at`, never a real `DELETE`), so that
  trigger never actually fired — agents kept pointing at a department
  that had just become invisible everywhere else, silently. Worse, the
  new delete-confirmation dialog's own copy claimed "N agent(s) will be
  unassigned," which was false until this was fixed. Fixed with a new
  `AgentRepository.clear_department()` (bulk `UPDATE`) called from
  `DepartmentService.delete()` before the soft-delete, wired through a
  new `agents: AgentRepository` dependency on `DepartmentService` (same
  pattern `TeamService` already uses) — no migration needed, this is a
  service-layer fix, not a schema change.

  "Prepare departments for routing, queues and reporting" is satisfied by
  what already exists — `Agent.department_id` and the full CRUD API are
  already there for those future features to build on — no speculative
  schema or integration work was added ahead of an actual routing/queues/
  reporting milestone actually needing it.

  Frontend: `departments/api.ts` expanded from a single read-all hook to
  full CRUD mutations; `DepartmentCreateDialog`, `DepartmentEditDialog`,
  `DepartmentAgentsDialog`. 5 new frontend tests (list, accessibility,
  create, edit, delete) plus a 6th covering the agent-membership view.
  Also fixed a test-fixture gap surfaced while writing these: the shared
  MSW mock user was missing `departments.read`/`departments.manage`
  entirely (present for every other resource), which would have silently
  hidden every permission-gated control on this and any future
  Departments-page test. Backend: 1 new integration test proving delete
  actually clears `department_id` on assigned agents.

  Backend: 568 passed (was 567). Frontend: 76 passed (was 70), tsc/eslint
  clean. Verified live against the production Docker stack: created a
  department, assigned an agent to it via the Agent form, confirmed the
  department page's agent count and membership list reflected it, edited
  and deactivated the department, then deleted it and confirmed (after
  the fix above) the agent's `department_id` was actually cleared.

- [x] **Item 3: Chat Attachments (2026-07-25)**
  Attachments now render inside the conversation thread: images as a
  clickable inline preview, documents as a file-type icon + filename +
  formatted size + download button (`AttachmentList.tsx`). Both are
  click-to-download via a blob-fetch helper (`fetchAttachmentBlobUrl`/
  `downloadAttachment` in `conversations/api.ts`), matching the existing
  Reports PDF/Excel export's pattern for hitting an auth-protected binary
  endpoint from the frontend.

  This exposed two real, independent, pre-existing bugs -- not something
  the new UI introduced, both present since attachments/messaging first
  shipped:

  1. **`MessageResponse` never carried attachment data at all.**
     `GET .../messages` and `POST .../messages` returned messages with no
     way to know which had attachments -- the data was always correctly
     linked and stored (`MessageAttachment.message_id`), just never
     surfaced. Fixed with a new `MessageAttachmentRepository.
     list_for_messages()` (batch query, not N+1) and `ConversationService.
     list_attachments_for_messages()`, wired into both endpoints via a new
     `attachments: list[AttachmentResponse]` field on `MessageResponse`.
     Kept as an explicit endpoint-layer join rather than an ORM
     relationship, matching `message.py`'s own documented reasoning for
     staying join-free at this table's scale.

  2. **The frontend's attachment upload was completely broken** --
     confirmed live against the real backend, not assumed: `uploadAttachment`
     explicitly set `Content-Type: multipart/form-data` with no `boundary`
     parameter. Per the XHR/Fetch spec (verified directly in axios's
     installed source -- `xhr.js` calls `setRequestHeader` for every header
     already present, and browsers only auto-generate the boundary when
     Content-Type is *not* explicitly set), this reaches the browser
     exactly as an explicit, boundary-less header. Reproduced the precise
     byte pattern against the live production backend: it rejects the
     request outright with `400 Missing boundary in multipart` -- this
     was not a filename-corruption edge case, file upload from the
     browser could not have worked at all. Fixed by clearing the header
     per-request (`Content-Type: undefined`) rather than setting it to
     `multipart/form-data` (still boundary-less) or leaving the instance's
     `application/json` default in place (axios's own `transformRequest`
     would then JSON-stringify the FormData instead of sending it, per
     `defaults/index.js`) -- letting axios/XHR generate the correct
     `multipart/form-data; boundary=...` header itself, the only one of
     the three options that actually works.

  No real browser is available in this sandbox to click through by hand,
  so this fix was verified to the strongest standard available: direct
  inspection of the exact installed axios version's request pipeline
  (not assumed from memory or docs), plus reproducing both the broken and
  fixed byte patterns as raw multipart requests against the live
  production backend -- the broken pattern 400s, the fixed one uploads,
  links to a message, downloads back byte-for-byte, and surfaces correctly
  through both `list_messages` and the immediate `send_message` response,
  including for a pre-existing historical message from seeded demo data
  (`conversation-report.pdf`), proving the fix isn't limited to
  newly-sent messages.

  Backend: 2 new/extended integration tests (attachments on `send_message`
  response and on `list_messages`, including a text-only message getting
  an empty list, not a missing field) -- 568 passed unchanged (the
  attachment fix is additive, no prior test touched this). Frontend: a
  dedicated `AttachmentList.test.tsx` (image/document rendering, size
  formatting, download wiring) with the network layer mocked -- jsdom's
  `Blob` doesn't implement `.stream()`, which breaks MSW's Response
  construction for any blob-typed response in this environment, an
  unrelated tooling gap confirmed independent of this app's code via a
  minimal reproduction (`new Request(..., {body}).formData()` alone loses
  fidelity here) -- so the actual network fetch-and-render path is covered
  by the live-backend verification above instead. 81 frontend tests total
  (was 76), tsc/eslint clean.

- [x] **Item 4: Conversation Transfer (2026-07-25)**
  Agents/Owners/Admins can transfer a conversation to another agent or to
  a department, with an optional note, full history, an audit-log entry,
  a real-time notification to the receiving agent, and immediate
  inbox-visibility changes for both the old and new owner. New
  `POST /conversations/{id}/transfer` and `GET /conversations/{id}/transfers`
  endpoints, gated by a new `conversations.transfer` permission (granted
  to Owner/Admin by default — see the RBAC decision below).

  **RBAC**: rather than inventing a fourth `SystemRole` ("Supervisor")
  with no existing role-editor anywhere in this codebase to make it
  meaningfully configurable, "Owners/Admins/Supervisors (configurable)" is
  satisfied the same way every other granular permission already is: a
  single new permission code (`conversations.transfer`) in the existing
  catalog/`RolePermission` mechanism, granted to Owner and Admin by
  default. This surfaced a real, **pre-existing, systemic gap**: every
  prior "seed a new permission" migration in this codebase's history only
  ever inserted into the `permissions` catalog table and never backfilled
  `role_permissions` for companies that already existed at the time —
  meaning `domain/rbac.py`'s own docstring claim that "Owner is granted
  every permission... unconditionally" has not actually been true for any
  permission added after a company's creation. Fixed for this one
  permission (the new seed migration backfills every existing company's
  Owner/Admin roles, verified against a real pre-existing company on a
  throwaway Postgres instance before shipping); **not** retroactively
  fixed for every past permission, which remains a known, accepted,
  out-of-scope gap for a future dedicated migration to address.

  **"Pending" for an offline recipient** (requirement: "if the new agent
  is offline, mark the transfer as pending and notify when they return")
  is implemented as an informational `recipient_was_online: bool` on each
  history row, computed from `AgentStatus` at transfer time — not a new
  "accept/reject" workflow, which would be a real behavioral change this
  codebase's assignment model has never had. The conversation is
  reassigned immediately regardless (requirements #8/#9 say "immediately",
  which a pending-acceptance gate would contradict); "notify when they
  return" is satisfied for free by the existing durable
  `Notification` row + badge/poll mechanism — no new infrastructure.

  **New `Conversation.department_id`**, distinct from `Queue.department_id`
  (an organizational label only, per `docs/architecture/queues-routing.md`)
  — this one is the conversation's actual current routing target, needed
  because the spec treats "transfer to a department" as equally first-class
  as "transfer to an agent." A department transfer clears
  `assigned_agent_id`; an agent transfer clears `department_id`.

  Backend: `ConversationTransfer` model (append-only, no soft-delete),
  `ConversationTransferRepository`, `ConversationService.transfer()`/
  `list_transfers()`, one `conversation.transferred` `DomainEvent` per
  transfer — audit-log and notification-fanout consumers both already
  subscribe to the existing outbox, so requirements #6/#7 needed zero new
  publishing infrastructure, only a new routing-key binding on the
  existing notification consumer (fans out to every agent in a department
  transfer, not just one). The generic `PATCH /conversations/{id}` no
  longer accepts `assigned_agent_id` — reassignment is transfer-only now,
  so history is never silently bypassed.

  Frontend: `TransferDialog` (search-as-you-type agent/department picker
  via MUI `Autocomplete`, optional note, an explicit confirm step),
  `TransferHistoryPanel` (new "Transfers" tab on the conversation view),
  and a real `assigned_agent_id` filter — the Inbox had no per-agent view
  at all before this (it was company-wide), so a "My conversations only"
  toggle was added to give requirements #8/#9 ("remove/add from the
  agent's inbox immediately") an actual UI surface to apply to. A
  correctness edge case found and fixed while building that toggle: a
  pure Owner with no `Agent` record now sees a distinct "No agent profile"
  empty state, instead of either a 422 (a bogus filter value) or silently
  falling back to showing every conversation.

  15 new backend tests (agent-target and department-target transfer
  including cross-clearing, note + full history — using set-membership
  assertions for a same-second pair, plus a dedicated ordering test with
  explicit DB-manipulated timestamps to sidestep SQLite's second-resolution
  clock —, 403 for a plain Agent, audit-log creation, 422 for a mismatched
  target, 404 for a nonexistent agent/department, SLA-timer and message-
  history preservation, `recipient_was_online` correctness for both an
  offline and a since-brought-online agent, inbox `assigned_agent_id`
  filtering, and confirmation the generic PATCH no longer reassigns an
  agent) plus 2 new notification-consumer tests (agent-target fanout,
  department-target fanout to every member with a control agent outside
  the department proving no false-positive). 583 backend tests total (was
  568), ruff/mypy clean. 5 new frontend tests (transfer flow end-to-end,
  permission-gated button visibility, the "My conversations only" filter,
  and the "no agent profile" empty state) — 83 frontend tests total (was
  81), tsc/eslint clean.

  Verified live against the production Docker stack: migration applied
  cleanly against real Postgres, and the permission backfill was
  confirmed correct against this sandbox's 10 pre-existing companies
  (Owner+Admin gained `conversations.transfer`, Agent did not). End-to-end
  with two real logged-in sessions: an Owner and an Agent (via a live
  WebSocket connection on `/ws/agent`, the same gateway the frontend
  uses) — transferring the conversation to that agent delivered a
  `conversation.transferred` notification frame over the agent's live
  socket within the same request, with `recipient_was_online: true`
  correctly recorded; a follow-up department transfer correctly cleared
  the agent assignment, recorded `from_agent_id`, and (with no agent yet
  in that department) correctly recorded `recipient_was_online: false`.
  Also confirmed live: both transfers appear in `GET /audit-logs` with
  full detail, a plain Agent gets 403 attempting a transfer, a
  nonexistent agent/department target 404s, a mismatched
  target-type/target-id pair 422s, the generic `PATCH` endpoint silently
  ignores an `assigned_agent_id` payload instead of reassigning, and the
  inbox's `assigned_agent_id` filter correctly reflects the post-transfer
  state.

- [x] **RBAC technical debt cleanup: generic permission synchronization
  (2026-07-25)** — requested explicitly, before Item 5, to eliminate the
  permission-backfill gap Item 4 discovered and only partially fixed
  (see Item 4's own entry above and `docs/architecture/auth-rbac.md`).
  Not itself a numbered sprint item.

  Replaced the old pattern of hand-writing a bespoke backfill in every
  "seed a new permission" migration with one reusable, generic mechanism:
  `infrastructure.database.permission_sync.sync_permissions()` diffs
  every company's granted RBAC permissions against `domain/rbac.py`'s
  *current* `DEFAULT_ROLE_PERMISSIONS`, additively — insert-only, never
  updates or deletes a row, so a role's extra grants beyond its defaults
  and every non-system (custom) role are always left completely
  untouched. Runs from three call sites sharing this one implementation:
  a migration (`3000cabd1c86`, this task's one-time reconciliation of
  every company that existed when it ran), the async application layer
  (`PermissionSyncService`, which `AuthService._seed_default_roles` now
  also uses — seeding a brand-new company's roles and backfilling an
  existing one are the same code path now, so they can never drift
  apart again), and a new standalone script
  (`python -m blinkengage.core.sync_permissions`) for on-demand ops use.
  `core/migrate.py` now also runs it automatically after every
  `alembic upgrade head`, on every container startup — meaning a future
  permission added to `domain/rbac.py` needs **no migration at all** to
  reach every existing company; the next deploy's restart does it.

  Per the explicit requirement to keep Owner/Admin/Agent as the only
  system roles for now (a "Supervisor" role was raised but deliberately
  not added — see Item 4's entry — and this task didn't revisit that),
  the mechanism is still built generically over whatever `SystemRole`
  values exist: it can create a missing system-role row for a company
  (not just missing permission grants on an existing one), so a future
  fourth role needs no "create it for every existing company" migration
  either.

  10 new tests directly against `sync_permissions()` (fresh-company
  seeding, idempotency, targeted backfill, extra-permission preservation,
  custom-role isolation, company-scoped vs. global reconciliation,
  catalog-row seeding, missing-role recreation) plus 2 more proving the
  async bridge and the refactored registration flow — 593 backend tests
  total (was 583), ruff/mypy clean.

  Verified live against a throwaway Postgres instance: the full migration
  chain applies clean on an empty database; then, simulating a company
  that predates every permission-seeding migration in this codebase's
  history (an Owner role with only the first migration's 4 permissions,
  plus a custom non-system role with one unrelated grant), re-running the
  new migration brought Owner from 4/30 to the full 30/30, Admin and
  Agent up to their exact current defaults (28 and 13), and left the
  custom role's grant completely untouched; re-running the standalone
  script afterward made zero further changes (idempotent). Also verified
  against this sandbox's real production Docker stack — 12 real,
  pre-existing companies accumulated across every prior milestone's
  testing — confirming zero missing system-role grants anywhere after
  the migration: the historical gap is now fully closed for every
  permission, not just `conversations.transfer`. A brand-new company
  registration and the standalone script were both re-confirmed working
  against the live stack afterward.

- [x] **Item 5: Inbox Notifications — built as a generic platform
  notification framework, not a conversation-specific feature
  (2026-07-25)** — explicit requirement: build a reusable notification
  service usable by conversations, transfers, SLA alerts, AI events,
  system events, and future modules; store in the database; deliver in
  real time over WebSockets; support future push/email without a core
  redesign; a Notification Center in the header with unread badge, mark
  (all) read, history, browser notifications, optional sound, and
  per-type preferences; real-time delivery with no duplicates,
  persistence across logout/login, correct unread counts across tabs,
  multi-tenant isolation, and RBAC-aware delivery.

  Much of the underlying infrastructure already existed from Item 4
  (Conversation Transfer): `NotificationService`/`Notification`
  model/REST API/`RealtimeProvider`/`NotificationBell` were all real,
  tested, and in production — this item generalized and extended that,
  rather than building from scratch. See
  `docs/architecture/notifications.md` for the full design (this entry
  summarizes what changed and the verification chain).

  **Generalized**: `NotificationRuleRegistry` replaces
  `notification_consumer.py`'s hardcoded if/elif chain and hand-maintained
  routing-key list — a future module adds its own trigger by registering
  one `NotificationRule` class, zero changes to the consumer, mirroring
  the exact "generic registry over a hand-maintained list" fix this
  session already applied once for RBAC permission sync. New built-in
  trigger: `message.persisted` → "New message received", for the
  conversation's assigned agent.

  **New**: per-user delivery preferences (email/browser/sound,
  opt-out-by-default) with a settings UI; a duplicate-prevention
  mechanism (`source_event_id` + a unique constraint) for RabbitMQ's
  at-least-once redelivery; a cross-tab/cross-device realtime signal on
  mark-read so every open session converges immediately, not just its
  own 30s poll; a full Notification Center page (history + preferences)
  alongside the existing header dropdown; browser desktop notifications
  and a synthesized (Web Audio API, no bundled asset) notification
  sound — capabilities this app never had before.

  **Adversarial review before shipping** (27 sub-agent calls, 5
  dimensions, each finding independently re-verified by 2 more agents)
  found 11 real issues, all fixed except one deliberately-accepted low-
  severity, no-impact redundant index: a critical unhandled-`IntegrityError`
  race in the dedup path (the exact crash-loop anti-pattern
  `audit_log_consumer.py` had already been fixed for once, reintroduced
  in a new place — fixed via a `SAVEPOINT`-based insert-or-recover), a
  cross-tenant conversation-scoping gap in the new notification rules, a
  frontend bug where a saved "disable this notification's sound/popup"
  preference was silently ignored in any browser tab that hadn't visited
  the preferences panel, and several real test-coverage gaps.

  **Live Docker verification then found a second, unrelated critical bug**
  the review couldn't have caught (the test suite never runs Alembic
  migrations at all): building the new migration's `UNIQUE` constraint
  via `CREATE INDEX CONCURRENTLY` to avoid locking the live
  `notifications` table — correct in isolation — deadlocked outright the
  moment this codebase's own multi-container startup lock
  (`core/migrate.py`) was involved, since a *blocking*
  `pg_advisory_lock` holds a waiting container's transaction open for
  its whole wait, and `CONCURRENTLY` must wait for every other open
  transaction in the database to finish before it can complete. Fixed
  by polling `pg_try_advisory_lock` instead (genuinely idle between
  attempts), plus making the migration resumable from the partial state
  a mid-migration container kill can now leave behind. Full detail in
  `docs/architecture/notifications.md`.

  Backend: 616 passed (was 593), ruff/mypy clean. Frontend: 110 passed
  (was 83), tsc/eslint clean, production build succeeds. Live-verified
  against the real production Docker stack with two real logged-in
  sessions (an Owner and an Agent connected over `/ws/agent`): the full
  real async pipeline for a new message (outbox → relay → ingest
  consumer → notification consumer, not a direct function call)
  delivering a live notification within seconds; the cross-tab
  read-state signal; preference persistence; the dedup fix, replayed
  through two genuinely separate transactions with zero duplicates and
  zero consumer crashes; and — discovered and fixed during this same
  pass — the migration deadlock, with the full 9-container concurrent
  startup re-verified clean afterward and the migration re-verified to
  converge correctly both from empty and from the exact partial-failure
  state the deadlock had left behind.

---

## Working agreement

1. One milestone in progress at a time; mark `[~]` here when started.
2. Every milestone ships with unit + integration tests passing before commit.
3. Every milestone gets a dedicated commit (or small set of commits) with a
   message describing what was delivered.
4. Architecture decisions that deviate from this roadmap are recorded in
   `docs/architecture/`.
5. This file is updated as part of each milestone's commit.
