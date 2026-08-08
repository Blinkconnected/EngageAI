# API Reference

This is a curated guide to conventions, authentication, and navigation —
not a hand-maintained copy of every endpoint's exact request/response
schema. That copy would drift out of date the moment a schema changed;
the **authoritative, always-current** reference is the live,
auto-generated OpenAPI documentation:

- **Swagger UI**: `GET /docs` (interactive — try requests directly)
- **ReDoc**: `GET /redoc` (read-only, better for browsing)
- **Raw OpenAPI schema**: `GET /api/v1/openapi.json`

All three are disabled in production (`settings.is_production`) — see
`docs/security/hardening.md` for why (an unauthenticated API surface map
is reconnaissance information, not something to expose publicly). Access
them against a `development`/`staging` deployment, or generate the schema
locally.

## Building a mobile or native client

Read [mobile-integration-guide.md](./mobile-integration-guide.md) before
you start. It covers token refresh (and the single-flight rule that stops
a resume from logging users out), the two WebSocket endpoints — which do
**not** appear in the OpenAPI schema, because FastAPI does not document
WebSocket routes — paging behaviour on lists that change while you read
them, attachment streaming, push registration, and an honest audit of the
gaps a native client will hit.

## Events

Integrating with the platform asynchronously? The
[Event Catalogue](../architecture/event-catalogue.md) lists all 99 domain
event types with their producers and consumers. A workflow can trigger a
webhook on any of them.

## Base URL and versioning

Every endpoint is namespaced under `settings.api_v1_prefix`
(`/api/v1` by default). There is no `v2` yet; when one is needed, the
existing pattern (`api/v1/`, `api/v2/` as sibling packages sharing
`domain`/`application` layers) is the intended path — see
`docs/architecture/backend.md`.

## Authentication

Bearer JWT, not cookies (deliberately — see
`docs/security/hardening.md`'s CSRF section).

```
POST /api/v1/auth/register   { company_name, owner_full_name, owner_email, owner_password }
POST /api/v1/auth/login      { email, password }
POST /api/v1/auth/refresh    { refresh_token }
POST /api/v1/auth/logout     { refresh_token }
GET  /api/v1/auth/me
```

`register`/`login` return `{ access_token, refresh_token, token_type }`
(register also returns the created user profile). Attach the access
token to every subsequent request:

```
Authorization: Bearer <access_token>
```

Access tokens are short-lived (`settings.access_token_expire_minutes`,
default 15 minutes) and carry the caller's **resolved permission set** as
a claim — every `require_permission(...)`-gated endpoint checks that
claim directly, with zero database round trip per request. This means a
permission change (editing a role) only takes effect for a user's
*next* login/refresh, not their currently-held access token — a
deliberate trade-off for request-path performance, not an oversight.

Refresh tokens are individually revocable (rotated on every `/refresh`
call, tracked in Redis) — `logout` revokes the specific token used, not
every session.

`register`/`login`/`refresh`/`logout` are all rate limited per client IP
(`core/rate_limit.py`) — expect `429 Too Many Requests` with a
`Retry-After` header well before any real brute-force attempt succeeds.

## Multi-tenancy

Every resource is scoped to the caller's company (`auth.company_id`,
resolved from the access token, never a client-supplied parameter) —
there is no way to address another company's data by ID guessing; every
repository query filters by `company_id` at the database layer. See
`docs/architecture/auth-rbac.md`.

## Pagination

Every list endpoint accepts `page` (1-indexed, default 1) and
`page_size` (default 20, max 100), returning:

```json
{ "items": [...], "total": 123, "page": 1, "page_size": 20 }
```

## Errors

Every error response is `{ "detail": "..." }` (or, for request-body
validation failures, FastAPI/Pydantic's standard
`{ "detail": [{"loc": [...], "msg": "...", "type": "..."}] }` array) —
one consistent shape across the entire API, mapped centrally
(`core/exceptions.py`) from domain exceptions to HTTP status, so no
individual endpoint hand-rolls its own error shape:

| Status | Meaning |
|---|---|
| 400 | Invalid input/state not covered by a more specific code below |
| 401 | Missing/invalid/expired credentials |
| 403 | Authenticated, but lacking the required permission |
| 404 | Resource not found (or not visible to this company) |
| 409 | Conflict (duplicate email, already-submitted CSAT response, ...) |
| 422 | Request body failed schema validation |
| 429 | Rate limited (`Retry-After` header present) |
| 503 | A configured-but-unavailable dependency (e.g. AI Engine/ERPNext not configured for this company) |

## Public (unauthenticated) endpoints

A small, deliberate set of endpoints require no bearer token — each
has its own documented trust model rather than being an oversight:

| Endpoint | Trust model |
|---|---|
| `GET /health`, `GET /health/ready` (both under `/api/v1`, like every other endpoint — see below) | None — orchestration/monitoring probes |
| `POST /webhooks/{channel_config_id}` | Provider signature verification (`ChannelProvider.verify_signature`) |
| `POST /webhooks/erpnext/{erp_config_id}/{doctype}` | Shared secret header (`X-Webhook-Secret`) |
| `POST /web-chat/{channel_config_id}/sessions`, the web-chat WebSocket | Rate limited; a session token scopes what a caller can do |
| `GET /csat/{conversation_id}`, `POST /csat/{conversation_id}/contact-info`, `POST /csat/{conversation_id}/respond` | A signed, conversation-scoped token (`TokenType.CSAT`), not a session |

See `docs/architecture/channels.md`, `docs/architecture/erp-integration.md`,
`docs/architecture/web-chat.md`, `docs/architecture/reports-analytics.md`.

## Resource index

Every router, its permission(s), and where to read the full design
rationale:

| Prefix | Permissions | Architecture doc |
|---|---|---|
| `/auth` | none (pre-auth) / any authenticated user (`/me`) | `docs/architecture/auth-rbac.md` |
| `/company` | none (GET) / `company.manage` (PATCH) | `docs/architecture/administration.md` |
| `/admin/plugins` | `company.manage` | `docs/architecture/administration.md` |
| `/departments` | `departments.read`/`.manage` | `docs/architecture/core-crm.md` |
| `/teams` | `teams.read`/`.manage` | `docs/architecture/core-crm.md` |
| `/agents` (incl. `/agents/{id}/role`) | `agents.read`/`.manage`; the `role` sub-route needs `roles.manage` instead | `docs/architecture/core-crm.md`, `docs/architecture/auth-rbac.md` |
| `/customers` | `customers.read`/`.manage`; ERP sub-routes need `erp.manage` | `docs/architecture/core-crm.md`, `docs/architecture/erp-integration.md` |
| `/audit-logs` | `audit_logs.read` | `docs/architecture/audit-logging.md` |
| `/channel-configs` | `channels.read`/`.manage` | `docs/architecture/channels.md` |
| `/webhooks`, `/web-chat` | see "Public endpoints" above | `docs/architecture/channels.md`, `docs/architecture/web-chat.md` |
| `/conversations` | `conversations.read`/`.manage`/`.delete` | `docs/architecture/conversations.md` |
| `/queues`, `/routing-rules` | `queues.read`/`.manage` | `docs/architecture/queues-routing.md` |
| `/roles`, `/permissions` | `roles.manage` (covers both read and write) | `docs/architecture/auth-rbac.md` |
| `/sla-policies`, `/holidays` | `sla_policies.read`/`.manage` | `docs/architecture/sla.md` |
| `/workflows` | `workflows.read`/`.manage` | `docs/architecture/workflow-engine.md` |
| `/knowledge`, `/quick-replies` | `knowledge_base.*`/`quick_replies.*` | `docs/architecture/knowledge-quick-replies-notes.md` |
| `/notifications` | none — personal inbox, scoped by caller identity | `docs/architecture/notifications.md` |
| `/ws/agent` (WebSocket) | JWT via `?token=` query param | `docs/architecture/notifications.md` |
| `/ai` | `ai.use` (rate limited per user) | `docs/architecture/ai-engine.md` |
| `/reports` | `reports.read` | `docs/architecture/reports-analytics.md` |
| `/search` | authentication only — filtered per entity type inside (see architecture doc) | `docs/architecture/global-search.md` |
| `/conversations/{id}/deletion-request` | `conversations.delete_request` to ask; `conversations.read` to see one | `docs/architecture/conversation-deletion.md` |
| `/conversation-deletion-requests` | `conversations.delete_approve` — deciding, not asking | `docs/architecture/conversation-deletion.md` |
| `/csat` | see "Public endpoints" above (respond) / `conversations.manage` (generate link) | `docs/architecture/reports-analytics.md` |
| `/erp-configs`, `/webhooks/erpnext` | `erp.manage` / shared secret | `docs/architecture/erp-integration.md` |
| `/billing` | `billing.read` — the caller's **own** company only; there is deliberately no `company_id` parameter | `docs/architecture/billing.md` |
| `/platform/*` | platform authority (`get_platform_auth`), outside tenant RBAC entirely; writes additionally need a non-read-only operator | `docs/architecture/billing.md` |
| `/platform/pricing/metrics`, `/platform/pricing/models` | platform authority; read-only catalogues — metrics are code, and models are what this build supports | `docs/architecture/billing.md` |
| `POST /platform/pricing/quote` | platform authority; **writes nothing** — prices caller-supplied terms so a console never does the arithmetic itself, and so a closed period can be re-priced hypothetically | `docs/architecture/billing.md` |

## Health and OpenAPI

`GET /api/v1/health` (liveness) and `GET /api/v1/health/ready`
(dependency-checked readiness — Postgres/Redis/RabbitMQ) sit outside the
resource index above since they're operational, not business, endpoints,
but — unlike `/metrics` below — they're mounted through the same
versioned `api_router` as everything else, not registered separately on
the app. Docker's own healthcheck (`docker-compose.yml`) and every
runbook in `docs/deployment/` call them with the full `/api/v1/` prefix;
don't be misled by their absence from the resource index table above.
`GET /api/v1/openapi.json` is versioned for the same reason.

`GET /metrics` (Prometheus exposition format) is the one genuinely
**unversioned** operational endpoint — `Instrumentator().expose(app,
endpoint="/metrics")` registers it directly on the FastAPI app, bypassing
`api_router`/`api_v1_prefix` entirely. See
`docs/architecture/observability.md`.
