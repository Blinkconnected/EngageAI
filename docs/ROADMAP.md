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
- [ ] **M13. Conversations, Messages, Attachments**
  Conversation lifecycle (open/pending/resolved/closed), message model
  (text/media/system) per the schema specified in `channels.md`,
  attachment storage via MinIO (S3-compatible), virus/type validation,
  delivery/read receipts. The conversation engine consumes
  `message.received` from the M10 bus rather than calling any provider
  directly.
- [ ] **M14. Queues, Assignment Engine, Routing Engine**
  Queue model, skill/load-based assignment strategies, routing rules engine,
  SLA timers, escalation.

## Phase 3 — Omnichannel Expansion

- [ ] **M15. Email channel** (SMTP/IMAP + provider webhook variants)
- [ ] **M16. WhatsApp Business + Telegram channels**
- [ ] **M17. Facebook Messenger + Instagram channels**
- [ ] **M18. SMS channel** (provider-agnostic gateway abstraction)

## Phase 4 — Engagement Intelligence

- [ ] **M19. Workflow Engine**
  Trigger/condition/action model, visual-friendly JSON DSL, execution
  engine, audit trail of workflow runs. Consumes from the M10 event bus.
- [ ] **M20. Knowledge Base, Quick Replies, Internal Notes**
- [ ] **M21. Notifications & real-time layer**
  WebSocket presence/typing/notifications, email/push notification
  dispatch via Celery. Consumes from the M10 event bus and the
  `RealtimePublisher` tier.
- [ ] **M22. AI Engine**
  Provider abstraction (OpenAI / Claude / Ollama), reply suggestions,
  conversation summary, translation, language detection, sentiment
  analysis, auto-tagging, knowledge search, FAQ search, grammar
  improvement, professional rewrite, next-best-action. Consumes from the
  M10 event bus.

## Phase 5 — Reporting & Ecosystem

- [ ] **M23. Reports & Analytics**
  Executive/agent/live dashboards, conversation/performance/queue/SLA/CSAT/
  AI reports, PDF + Excel export. Consumes from the M10 event bus rather
  than querying operational tables directly where a projection suffices.
- [ ] **M24. ERPNext Integration**
  Customers, invoices, sales orders, quotations, support tickets, payments,
  contacts — sync + webhook layer. Consumes from the M10 event bus.
- [ ] **M25. Administration console**
  Company/system configuration, plugin management, audit log viewer.

## Phase 6 — Hardening & Launch

- [ ] **M26. Security hardening**
  OWASP ASVS pass, CSRF/XSS/SQLi verification, secrets management,
  encryption at rest/in transit, dependency scanning, pen-test checklist.
- [ ] **M27. Observability & DevOps**
  Prometheus metrics, Grafana dashboards, Loki log pipeline, alerting,
  automated backups + restore drill, GitHub Actions CI/CD (lint, test,
  build, scan, deploy). Also where nginx moves from a single hardcoded
  `backend` upstream to a load-balanced pool, enabling multiple stateless
  app-server replicas (see `docs/architecture/event-bus.md`'s scaling
  posture note).
- [ ] **M28. Performance & load testing**
  Load/soak testing of conversation + messaging paths, query optimization,
  caching strategy validation, `messages` table partitioning if warranted
  at real data volume.
- [ ] **M29. Documentation & production readiness review**
  Full `docs/api`, `docs/database`, `docs/security`, `docs/deployment`
  content, runbooks, disaster recovery plan, go-live checklist.

---

## Working agreement

1. One milestone in progress at a time; mark `[~]` here when started.
2. Every milestone ships with unit + integration tests passing before commit.
3. Every milestone gets a dedicated commit (or small set of commits) with a
   message describing what was delivered.
4. Architecture decisions that deviate from this roadmap are recorded in
   `docs/architecture/`.
5. This file is updated as part of each milestone's commit.
