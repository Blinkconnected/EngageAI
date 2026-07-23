# Reports & Analytics

M23 of the roadmap, opening Phase 5 (Reporting & Ecosystem). Every report
the CLAUDE.md spec names — Executive/Agent/Live dashboards, Conversation/
Performance/Queue/SLA/Customer Satisfaction/AI reports, PDF + Excel
export — built on top of the M10 event bus rather than every report query
aggregating the full `conversations`/`messages` history directly.

## Rollups fed by the event bus, not live aggregation

At the scale this platform targets (5M conversations, 100M messages), a
report query that scans `conversations`/`messages` directly for every
request doesn't hold up. Instead, a new consumer
(`infrastructure/events/consumers/reporting_consumer.py`) binds a fixed,
code-defined set of routing keys — `conversation.created`,
`conversation.updated`, `conversation.assignment_changed`,
`conversation.sla_breached`, `message.sent`, `ai.completed`,
`csat.submitted` — and maintains five small, incrementally-updated rollup
tables, one row per `(company, dimension, day)`:

- `conversation_daily_stats` (company, date, channel_type) — opened/
  closed/resolved counts, first-response/resolution SLA breach counts.
- `agent_daily_stats` (company, agent, date) — conversations assigned/
  closed, messages sent.
- `queue_daily_stats` (company, queue, date) — conversations entered,
  SLA breaches.
- `ai_daily_stats` (company, date, operation) — AI Engine (M22) call
  counts per operation — this is the "AI Reports" line in the roadmap,
  built entirely off the `ai.completed` event `AiService` already
  publishes, with zero new instrumentation needed in the AI Engine
  itself.
- `csat_daily_stats` (company, date) — response count + rating sum, for
  cheap date-range trend queries without scanning every individual
  response.

Every increment is an `INSERT ... ON CONFLICT DO UPDATE
SET metric = metric + <increment>`
(`infrastructure/repositories/daily_stats_repository.py`), not a
read-then-write — safe under concurrent consumer processing without
needing the outbox relay's `SKIP LOCKED` treatment, since both
PostgreSQL and SQLite (test-only) support this upsert form directly.

Where an event's payload doesn't carry a dimension a rollup needs (e.g.
`conversation.updated` doesn't carry `channel_type`, `message.sent`
doesn't carry the sending agent), the consumer looks the current row up
from the database — the same enrichment pattern `notification_consumer`
already established. This is safe here because by the time an event
reaches this consumer (after an outbox-relay round trip), the row it was
published alongside has already committed.

**Detecting a genuine status transition**: `ConversationService.update()`
now includes `previous_status` in `conversation.updated`'s payload
(additive — no existing consumer's behavior changes). Without it, the
reporting consumer would recount `closed_count` every time `update()` is
called on an already-closed conversation (e.g. reassigning it), since the
event only ever carried the *current* status. Only `status != previous_
status` (and the new status being `closed`/`resolved`) increments
anything.

## The one report that isn't a rollup: the Live Dashboard

`GET /reports/live-dashboard` reflects "right now" — who's online, what's
in each queue this instant — which a daily rollup fundamentally can't
represent (rollups are per-day, not per-second). `ReportingRepository`
queries the small, already-indexed `agents`/`conversations`/`queues`
tables directly (`GROUP BY status`, a `LEFT JOIN` counting open/pending
conversations per queue) — cheap because these tables are small relative
to `messages`/historical conversation volume, and because "right now" has
no meaningful cache/staleness tolerance the way a date-ranged report does.
This is the concrete instance of the original event-bus mandate's caveat:
"consume events... rather than querying operational tables directly
*where a projection suffices*" — here, a projection doesn't suffice.

## Customer Satisfaction: a signed survey link, not a new auth flow

CSAT needs a way for a *customer* (not a logged-in agent) to submit a
rating against one specific, already-closed conversation. Building a
whole customer authentication system for this would be wildly
disproportionate. Instead: `POST /conversations/{id}/csat-survey-link`
(authenticated, `conversations.manage`) issues a signed,
conversation-scoped JWT — a new `TokenType.CSAT` alongside the existing
`ACCESS`/`REFRESH` types in `core/security.py`, reusing the exact same
signing key and `create_token`/`decode_token` machinery, just with a
conversation id (not a user id) as the `sub` claim and its own expiry
(`settings.csat_token_expire_days`, default 14 — long enough for a
customer to get around to it, unlike the much shorter access-token
lifetime). `POST /csat/{id}/respond` (public, no auth — mirrors
`web_chat.py`'s public-endpoint trust model) decodes the token, checks its
`sub` matches the conversation id in the URL, and rejects with 401 if
either check fails or the token is expired. One response per conversation
is enforced by a unique constraint on `csat_responses.conversation_id`
(409 on a second attempt) — a rating is a one-time survey response, not
an editable record.

`ConversationRepository.get_by_id_any_company` (new, mirrors
`ChannelConfigRepository.get_by_id_any_company` from the webhook-ingress
path) looks a conversation up unscoped by `company_id` — legitimate here
because the token's signature, not tenant isolation, is what proves the
request is authorized, exactly the same reasoning `get_by_id_any_company`
already established for inbound provider webhooks.

Submitting a response publishes `csat.submitted`
(`{conversation_id, agent_id, rating}`), consumed by the reporting
consumer into `csat_daily_stats`; `csat_responses` itself is queried
directly for the CSAT report's per-agent breakdown (`GROUP BY agent_id`
joined to `Agent`/`User` for a name) — low enough volume relative to
`messages` that a per-row query is cheap without its own rollup.

## No new RBAC permission

Every `/reports/*` endpoint is gated by the existing `reports.read`
permission (already in the catalog since M2, previously unused by any
endpoint) — viewing reports and dashboards was already the exact access-
control question that permission answers; minting a new one would be
redundant. CSAT survey-link generation reuses `conversations.manage`
(an agent action on a conversation they can already manage); CSAT
response submission needs no permission at all, since it's the token,
not a role, that authorizes it.

## PDF and Excel export

Every date-ranged report endpoint accepts an optional `export=pdf|xlsx`
query parameter. `infrastructure/reporting/export.py` holds two
deliberately generic renderers — `render_pdf_table`/`render_excel_table`,
title + headers + rows in, bytes out — rather than one bespoke renderer
per report type, since every report this milestone exports is
structurally "a table with a title"; the report-specific shaping (which
columns, what goes in each cell) already happens in
`api/v1/endpoints/reports.py` before this module ever sees the data.
Built on `reportlab` (PDF) and `openpyxl` (Excel) — the two new runtime
dependencies this milestone adds, both pure-Python, no system
dependencies. Dashboards (Executive/Live) flatten their scalar metrics
into a two-column "Metric | Value" table for export; naturally-tabular
reports (Conversations, Performance, Queues, SLA's per-queue breakdown,
CSAT's daily trend, AI) export their rows directly.

## Schema impact

Six new tables (`conversation_daily_stats`, `agent_daily_stats`,
`queue_daily_stats`, `ai_daily_stats`, `csat_daily_stats`,
`csat_responses`) — no new permission migration needed (`reports.read`
already existed). See `docs/database/schema.md`.

## Verification performed

34 new tests added (424 → 458 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/integration/test_reporting_consumer.py` (9 tests) — each bound
  event type upserts the right rollup row(s): conversation created
  (opened + queue entered), a genuine transition to closed (conversation
  + agent stats) vs. a same-status no-op vs. an ignored transition to
  open, assignment-changed, SLA breach (both breach types, queue +
  conversation stats), message-sent crediting the assigned agent, and
  `ai.completed`/`csat.submitted` accumulating correctly across repeated
  events.
- `tests/integration/test_reporting_repository.py` (7 tests) —
  date-range filtering and per-channel grouping, totals coalescing to
  zero with no data, agent-name/queue-name joins with correct ordering,
  CSAT total/average/daily-trend math, and the Live Dashboard's
  current-state queries.
- `tests/integration/test_reports_api.py` (11 tests) — authentication is
  required, the Executive Dashboard's aggregated totals and both its PDF
  and Excel export paths (verified by magic-byte signature and
  content-type), the Agent Dashboard's 404 for a non-agent user vs. a
  real agent's own stats, the Live Dashboard against real agent/queue
  state, conversation-report channel filtering, and the AI/CSAT reports'
  totals and export.
- `tests/integration/test_csat_api.py` (7 tests) — the full survey-link
  round trip, a duplicate submission rejected with 409, an invalid token
  rejected with 401, a token scoped to a different conversation rejected
  with 401, and an out-of-range rating rejected with 422 at the schema
  layer.

The migration (`b8c9d0e1f2a3`) was verified against the real running
Postgres via `docker compose exec backend alembic upgrade head`, then a
downgrade and re-upgrade cycle. A new `reporting-consumer` service was
added to both `docker-compose.yml` and `docker-compose.prod.yml` (the
latter also gained overrides for `workflow-engine-consumer`/
`notification-consumer`, which were missing from the production runtime-
image overlay since M19/M21 — a pre-existing deployability gap closed
alongside this milestone's own new consumer).
