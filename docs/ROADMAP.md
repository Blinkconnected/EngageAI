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

- [ ] **M10. Channels — plugin architecture**
  Channel abstraction/interface, channel registry, inbound/outbound adapter
  contract, configuration model per company.
- [ ] **M11. Web Chat channel (reference implementation)**
  WebSocket gateway, chat widget contract, session handling.
- [ ] **M12. Conversations, Messages, Attachments**
  Conversation lifecycle (open/pending/resolved/closed), message model
  (text/media/system), attachment storage via MinIO (S3-compatible),
  virus/type validation, delivery/read receipts.
- [ ] **M13. Queues, Assignment Engine, Routing Engine**
  Queue model, skill/load-based assignment strategies, routing rules engine,
  SLA timers, escalation.

## Phase 3 — Omnichannel Expansion

- [ ] **M14. Email channel** (SMTP/IMAP + provider webhook variants)
- [ ] **M15. WhatsApp Business + Telegram channels**
- [ ] **M16. Facebook Messenger + Instagram channels**
- [ ] **M17. SMS channel** (provider-agnostic gateway abstraction)

## Phase 4 — Engagement Intelligence

- [ ] **M18. Workflow Engine**
  Trigger/condition/action model, visual-friendly JSON DSL, execution
  engine, audit trail of workflow runs.
- [ ] **M19. Knowledge Base, Quick Replies, Internal Notes**
- [ ] **M20. Notifications & real-time layer**
  WebSocket presence/typing/notifications, email/push notification
  dispatch via Celery.
- [ ] **M21. AI Engine**
  Provider abstraction (OpenAI / Claude / Ollama), reply suggestions,
  conversation summary, translation, language detection, sentiment
  analysis, auto-tagging, knowledge search, FAQ search, grammar
  improvement, professional rewrite, next-best-action.

## Phase 5 — Reporting & Ecosystem

- [ ] **M22. Reports & Analytics**
  Executive/agent/live dashboards, conversation/performance/queue/SLA/CSAT/
  AI reports, PDF + Excel export.
- [ ] **M23. ERPNext Integration**
  Customers, invoices, sales orders, quotations, support tickets, payments,
  contacts — sync + webhook layer.
- [ ] **M24. Administration console**
  Company/system configuration, plugin management, audit log viewer.

## Phase 6 — Hardening & Launch

- [ ] **M25. Security hardening**
  OWASP ASVS pass, CSRF/XSS/SQLi verification, secrets management,
  encryption at rest/in transit, dependency scanning, pen-test checklist.
- [ ] **M26. Observability & DevOps**
  Prometheus metrics, Grafana dashboards, Loki log pipeline, alerting,
  automated backups + restore drill, GitHub Actions CI/CD (lint, test,
  build, scan, deploy).
- [ ] **M27. Performance & load testing**
  Load/soak testing of conversation + messaging paths, query optimization,
  caching strategy validation.
- [ ] **M28. Documentation & production readiness review**
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
