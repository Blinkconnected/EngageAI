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
- [~] **M1. Repository bootstrap**
  Git repo, directory structure (`docs/`, `frontend/`, `backend/`, `docker/`,
  `scripts/`, `tests/`, `monitoring/`, `backups/`, `.github/`), `.gitignore`,
  `README.md`, `CLAUDE.md`, this roadmap, license/editorconfig, CI skeleton.
- [ ] **M2. Docker Compose infrastructure**
  PostgreSQL, Redis, RabbitMQ, MinIO, backend, frontend, NGINX reverse proxy,
  Prometheus, Grafana, Loki + Promtail, Celery worker/beat. Local
  `docker-compose.yml` (dev) + `docker-compose.prod.yml` overlay. Health
  checks on every service.
- [ ] **M3. Backend application skeleton**
  FastAPI app factory, layered Clean Architecture package layout
  (`domain/`, `application/`, `infrastructure/`, `api/`), settings via
  Pydantic Settings, structured logging, dependency-injection container,
  `/health` and `/health/ready` endpoints, OpenAPI metadata, pytest +
  coverage config, pre-commit (ruff, black, mypy).
- [ ] **M4. Database layer**
  SQLAlchemy 2 async engine/session management, Alembic migration
  environment, base repository pattern + unit of work, first migration
  (extensions, audit columns, soft-delete convention).
- [ ] **M5. Frontend application skeleton**
  Vite + React + TypeScript, Material UI theme (light/dark/RTL), Redux
  Toolkit store, React Query client, routing, API client with auth
  interceptor, ESLint/Prettier/Vitest config.

## Phase 1 — Identity & Core Directory

- [ ] **M6. Auth & RBAC domain**
  User/Agent identity, JWT access + refresh tokens, password hashing,
  login/refresh/logout endpoints, Role/Permission model, policy-based
  authorization dependency, rate limiting on auth endpoints.
- [ ] **M7. Companies, Departments, Teams, Agents**
  Multi-tenant company model, department/team hierarchy, agent profiles,
  membership and role assignment, admin CRUD APIs + tests.
- [ ] **M8. Customers**
  Customer profile model, identity resolution across channels, custom
  fields, tagging, merge/dedupe.
- [ ] **M9. Audit logging foundation**
  Append-only audit log table, domain event hooks, audit query API.

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
