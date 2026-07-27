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

`GET /reports/live-dashboard` is also what powers the home page's
Dashboard (`frontend/src/features/dashboard/DashboardPage.tsx`, the
`index` route in `AppRoutes.tsx`) — there is no separate "home dashboard"
backend concept; it's the same single endpoint, gated by the same
`reports.read` permission every Agent already holds by default.

### Total/active/unassigned, and a live per-agent workload (added 2026-07-27)

`LiveConversationCounts` (`reporting_repository.py`) gained `unassigned`
as a real field (active — open/pending — conversations with no
`assigned_agent_id`, one extra `COUNT` in `live_conversation_counts()`)
and `total`/`active` as computed `@property`s (sums of the existing four
status counts — no new query needed; `ConversationStatus` has no
dedicated "active" value, so this is simply `open + pending`).

A live, company-wide per-agent workload had no existing query anywhere —
`agent_performance`'s `AgentDailyStats`-backed rows are a historical,
date-ranged rollup (assigned/closed *over a range*), not "how many
open/pending conversations does this agent hold right now." New
`ReportingRepository.agent_workload()` joins `Agent`/`User` to
`Conversation` (`LEFT JOIN`, same shape as `live_queue_depth`'s
Queue→Conversation join, plus the same cross-tenant defense predicate),
using `func.count(case((status == X, Conversation.id)))` — the exact
portable, no-FILTER-clause idiom `queue_metrics()`'s `waiting_count`/
`sla_breached_count` already established — to split open vs. pending in
one query. Every non-deleted agent in the company appears, defaulting to
0 (an idle agent is not omitted — a supervisor needs to see who's free,
not just who's busy), the same seed-then-overlay shape
`live_agent_counts` already uses for status counts.

`ReportingService.live_dashboard()`/`LiveDashboard` compose this exactly
like `queues`; `LiveDashboardResponse` gained a matching
`agent_workload: list[AgentWorkloadResponse]` field. No RBAC change: this
extends the one existing `reports.read`-gated endpoint, so it inherits
that endpoint's existing broad visibility (every Agent already saw every
other agent's presence status and every queue's full depth on this same
page) rather than introducing a new, narrower permission the roadmap
never asked for.

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
`CustomerRepository.get_by_id_any_company` (new, same reasoning) does the
same for the customer behind the conversation.

Submitting a response publishes `csat.submitted`
(`{conversation_id, agent_id, rating}`), consumed by the reporting
consumer into `csat_daily_stats`; `csat_responses` itself is queried
directly for the CSAT report's per-agent breakdown (`GROUP BY agent_id`
joined to `Agent`/`User` for a name) — low enough volume relative to
`messages` that a per-row query is cheap without its own rollup.

## Sending the survey automatically, on the same channel the conversation happened on

Originally, the survey link only existed if an agent explicitly called
`POST /conversations/{id}/csat-survey-link` — nothing ever sent it
anywhere. `csat_dispatch_consumer.py` (new) closes that gap: it binds
`conversation.resolved` (the dedicated per-terminal-status event
`ConversationService.update()` already publishes — see
`conversation_service.py`'s own comment naming "a CSAT survey trigger" as
this event's intended consumer) and, on receipt, calls
`ConversationService.send_reply()` to send the survey link as an
ordinary outbound message on whatever channel the conversation already
happened on (WhatsApp, web chat, email, SMS, ...) — reusing the exact
same send path an agent's own reply goes through, rather than inventing
a bespoke email/SMS sender for this one feature. Deliberately doesn't
also bind `conversation.closed`: the survey asks "how did we do on this
resolution," once, not again every time a conversation is later formally
closed.

`Conversation.csat_survey_sent_at` (new column) is set the first time
this happens and checked before sending again — without it, a
conversation cycling through RESOLVED → OPEN → RESOLVED (an allowed
transition, e.g. the customer replies and it gets reopened, then
resolved again) or an at-least-once redelivery of the same event would
send the survey more than once for the same conversation.

Whether the customer has a usable `Customer.email`/`phone` on file plays
no part in this dispatch step — the channel the conversation already
happened on is itself how the link gets there. It matters at the next
step instead.

## Asking for missing contact info before the rating form

The frontend's public feedback page (`/feedback/{conversation_id}`, the
link the customer actually receives) needs to know, before rendering
anything, what to show: the rating form, a thank-you screen (already
answered), or a short "how can we reach you" step first. `GET
/csat/{conversation_id}` (public, token-gated, new) answers exactly
that — `CsatService.get_context()` reuses the same token-verification
logic `submit()` already had (now shared as `_verify_token()`) and
reports `already_responded` (from the existing `csat_responses` unique
constraint) and `needs_contact_info` (true when the conversation's
customer has neither `email` nor `phone` set — common for a brand new
Web Chat visitor, or any channel whose external id doesn't map onto
either field).

When `needs_contact_info` is true, the page collects an email or phone
number and posts it to `POST /csat/{conversation_id}/contact-info`
(public, token-gated, new) before showing the rating form.
`CsatService.submit_contact_info()` only *backfills* — it never
overwrites a value the customer or an agent already supplied — and
pre-checks `CustomerRepository.get_by_email` for a same-company
collision before assigning (`EntityAlreadyExistsError`, 409), the exact
same pre-check-before-assign pattern `CustomerService.update()` already
established for agent-driven customer edits. No new permission is
needed — like `respond`, the token itself is what authorizes the write,
not a role.

## No new RBAC permission

Every `/reports/*` endpoint is gated by the existing `reports.read`
permission (already in the catalog since M2, previously unused by any
endpoint) — viewing reports and dashboards was already the exact access-
control question that permission answers; minting a new one would be
redundant. CSAT survey-link generation reuses `conversations.manage`
(an agent action on a conversation they can already manage); CSAT
context/contact-info/response submission need no permission at all,
since it's the token, not a role, that authorizes them.

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

Added later (Enterprise Readiness & UX milestone, Priority 2 item 11):
both renderers take an optional `logo` — the company's own uploaded logo
(`CompanyService.get_logo`, see `docs/architecture/administration.md`),
drawn at the top of the PDF (a `reportlab.platypus.Image` flowable
ahead of the title) or anchored at cell A1 of the Excel sheet (with a
few blank rows reserved above the header row so it doesn't render
underneath the image). Every report endpoint (all seven in
`reports.py`, plus the audit log export in `audit_logs.py`) fetches it
via a small `_fetch_logo` helper that swallows any fetch failure —
a company with no logo, or a transient object-storage error, renders
the report without one rather than failing the export.

## Schema impact

Six new tables (`conversation_daily_stats`, `agent_daily_stats`,
`queue_daily_stats`, `ai_daily_stats`, `csat_daily_stats`,
`csat_responses`) — no new permission migration needed (`reports.read`
already existed). `conversations.csat_survey_sent_at` (added later,
alongside automatic dispatch — see above) is the one later addition. See
`docs/database/schema.md`.

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

### Automatic CSAT dispatch + contact-info backfill (added 2026-07-27)

14 new tests added, all green under `pytest -q`, `ruff check`/`ruff
format --check`, and `mypy src`:

- `tests/integration/test_csat_dispatch_consumer.py` (4 tests) —
  resolving a conversation sends exactly one outbound message containing
  the `/feedback/{id}?token=...` link; a second `conversation.resolved`
  event for the same conversation (simulating a reopen/re-resolve cycle
  or an at-least-once redelivery) sends nothing further; an event
  missing its `conversation_id`, and one for an unknown conversation,
  are both ignored without raising.
- `tests/integration/test_csat_api.py` (+10 tests) — `GET
  /csat/{id}` reports `needs_contact_info=true` for a fresh Web Chat
  visitor (no email/phone), `false` once one is supplied, and
  `already_responded=true` after a rating is submitted; `POST
  /csat/{id}/contact-info` sets an email, sets a phone, rejects a body
  with neither (422, schema-level), rejects an email already used by
  another customer in the same company (409), never overwrites an
  already-set email, and rejects an invalid/expired token (401) same as
  every other CSAT route.

`CsatService.build_survey_url()` now points at the frontend's public
`/feedback/{conversation_id}` page instead of the raw API endpoint —
`docker/nginx/*.conf` routes `/api/*` to the backend and everything else
to the frontend SPA on the same origin (`settings.public_base_url`), so
one setting still produces the right link for both. Verified live
against the real running `docker compose` stack: resolved a real
Web Chat conversation over `PATCH /conversations/{id}`, confirmed
`csat-dispatch-consumer`'s logs showed the event bound and a `Message`
row appeared in the conversation with the survey link, then opened that
link's frontend route directly and completed both the contact-info step
and the rating form against the real API. `csat-dispatch-consumer` was
added to both `docker-compose.yml` and `docker-compose.prod.yml`,
mirroring `reporting-consumer`'s shape.

### Release Dashboard: total/active/unassigned + per-agent workload (added 2026-07-27)

4 new tests added, all green under `pytest -q`, `ruff check`/`ruff
format --check`, and `mypy src`:

- `tests/integration/test_reporting_repository.py` (+2 tests) —
  `live_conversation_counts()` reports `unassigned` counting only
  open/pending rows with no assigned agent (a resolved-but-unassigned
  row correctly excluded), and `total`/`active` sum correctly;
  `agent_workload()` splits an agent's open vs. pending count correctly,
  excludes a resolved conversation from their workload, and shows an
  idle agent at `0` rather than omitting them.
- `tests/integration/test_reports_api.py` (+2 tests) — `GET
  /reports/live-dashboard`'s `conversations` object includes the new
  `unassigned`/`total`/`active` fields, and its new `agent_workload`
  array reflects a real assigned conversation.

Frontend: `DashboardPage.tsx` gained three summary cards (Total, Active,
Unassigned) above the existing per-status cards, and a "Team workload"
table (agent, open, pending, total) alongside the existing Queue depth
table — both fed by the same `useLiveDashboardQuery()` this page already
used, no new query/polling added. 2 new tests in
`DashboardPage.test.tsx` (5 total, was 3) cover the new summary cards and
the workload table including an idle agent at zero.
