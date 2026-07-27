# Queues, Assignment Engine, Routing Engine

M14 of the roadmap, closing out Phase 2 (Conversations Core). Decides
*where* a new conversation goes (routing), *who* handles it (assignment),
and *whether it's late* (SLA/escalation) — all triggered from the same
seam M13 already built: the conversation-ingest consumer, on a
newly-created conversation only, never on a conversation's later messages.

Sprint 2 ("Queue & Routing Engine — manual pickup, queue metrics and
dashboard") extends this without touching the shape above: manual queues
that never auto-assign, self-service pick()/release() so an agent can
claim/give back a conversation, a `busy` self-service agent status, and
a Live Dashboard metrics upgrade (per-queue assigned/pickup/abandonment/
throughput, not just open/waiting counts). See decisions #6–#10 and the
new sections below for what changed; everything under "Key architectural
decisions #1–#5" and "Scope boundary" is unchanged and still accurate.

## Scope boundary: this is not the Workflow Engine

M19 (Phase 4) is a general trigger/condition/action engine with a JSON
DSL. Building a second, competing rules abstraction here would be exactly
the technical debt this project is explicitly trying to avoid. M14's
`RoutingRule` is deliberately narrow — a short list of
`(priority, {channel_type?, body_contains?}, target_queue_id)` rows,
evaluated in priority order, first match wins, no nesting, no actions
beyond "route to this queue." When M19 lands, it either subsumes this
(routing becomes one more workflow trigger type) or the two coexist with
routing staying first-touch-only — that decision belongs to M19, not
this milestone.

~~Likewise, SLA breach detection here only *publishes an event*; the
actual escalation action is Workflow Engine (M19) / Notifications (M21)
territory.~~ **Superseded 2026-07-27 by the SLA Builder** —
`docs/architecture/sla.md` — which adds business-hours-aware deadlines,
warning thresholds, and a policy-level escalation action (reassign/
notify), executed directly rather than through the Workflow Engine (see
that doc's "Escalation" section for why). The queue-level SLA fields
documented below remain exactly as they were as the fallback for any
queue with no `SlaPolicy` assigned.

## Data model

```
queues
------
id (PK), company_id (FK, CASCADE)
name                        unique per company among active rows
department_id (FK, SET NULL, nullable)   organizational label only —
                                          NOT an eligibility filter (see
                                          decision #2)
assignment_strategy         round_robin | least_load | manual
                             default: manual (see decision #6)
first_response_target_minutes (nullable) — null = no SLA on this queue
resolution_target_minutes (nullable)
sla_policy_id (FK sla_policies, SET NULL, nullable) — see sla.md; when
                                          set, takes over from the two
                                          fields above entirely
is_active
soft-delete

agent_skills (catalog, company-scoped)     agent_skill_assignments (join)
-----------------------------------        ----------------------------
id, company_id, name                       agent_id (FK) + skill_id (FK)
unique per company                         composite PK

queue_required_skills (join)
-----------------------------
queue_id (FK) + skill_id (FK)               composite PK — a queue with
                                             zero rows here has no skill
                                             restriction (every active
                                             agent is eligible)

routing_rules
-------------
id (PK), company_id (FK, CASCADE)
priority (int)              lower evaluates first
conditions (JSON)            {"channel_type": "..."} and/or
                              {"body_contains": "..."}
target_queue_id (FK -> queues)
is_active

conversations  (altered)
-----------------------
+ queue_id (FK -> queues, SET NULL, nullable)
+ first_response_at (nullable)              set on the first outbound
                                             message — see decision #3
+ sla_first_response_breached_at (nullable) idempotency marker
+ sla_resolution_breached_at (nullable)     idempotency marker
+ queue_entered_at (nullable)                set when routed into a queue;
                                             feeds avg/longest wait
+ picked_up_at (nullable)                   set on every claim (auto- or
                                             manually-assigned); cleared
                                             back to null by release()
+ first_picked_up_at (nullable)             set once, on the FIRST ever
                                             claim, and never cleared or
                                             overwritten again — see
                                             decision #7
+ closed_at (nullable)                      set on RESOLVED/CLOSED;
                                             feeds throughput_24h

agents  (altered)
-----------------
status: online | away | busy | offline     BUSY is new — see decision #10
```

Both `assignment_strategy`'s and `status`'s columns are
`Enum(..., native_enum=False)` (an application-level `VARCHAR` check, not
a Postgres native enum type) — adding `manual`/`busy` as new valid values
was a pure application-code change, **no schema migration needed for
either**. The two migrations Sprint 2 *did* add
(`8bf1eb4aad4e_add_conversation_queue_pickup_timestamps`,
`1f2a3b4c5d6e_add_conversation_first_picked_up_at`) are exclusively for
the four new `conversations` timestamp columns above, the last of which
also backfills `first_picked_up_at` from the pre-existing `picked_up_at`
for any conversation already claimed before the column existed — without
that backfill, `abandoned_count_24h` would momentarily misclassify every
already-claimed conversation as "never handled" until its next `pick()`.

## Key architectural decisions

1. **Routing and assignment run synchronously inside
   `conversation_ingest_consumer`, in the same transaction as the
   conversation's creation — only when the conversation is new.** A
   second/third/... message on an already-routed, already-assigned
   conversation skips both steps entirely (it already has a
   `queue_id`/`assigned_agent_id`). This reuses the exact seam M13 built
   rather than adding a second consumer or a synchronous call from the
   webhook route/WebSocket gateway — the ingest consumer is already the
   one place "a conversation was just created" is known.

2. **`Queue.department_id` is an organizational label, not an eligibility
   filter.** Coupling assignment eligibility to M7's Department/Team
   membership graph (which team is on which department, who's a member of
   which team) is a real feature but a separate, larger one — "eligible
   agents for this queue" here is simply "every active agent in the
   company," narrowed by `queue_required_skills` if any exist. Wiring
   queue eligibility through team membership is a documented possible
   follow-up, not built now, to avoid speculative coupling between two
   milestones that don't need it yet.

3. **`first_response_at` is set the first time `ConversationService.send_reply`
   is called on a conversation with no prior outbound message**, not by a
   separate "mark first response" step — it's a natural side effect of the
   one place outbound messages are already created (M13).

4. **SLA breach detection is a Celery-beat-scheduled task, not a
   per-conversation timer.** A per-conversation scheduled job (one Celery
   task per open conversation) doesn't scale to 5M conversations; a single
   periodic sweep (`check_sla_breaches`, every minute) querying open/
   pending conversations whose queue has a target and whose deadline has
   passed is O(one indexed query) regardless of conversation count. Each
   breach is published exactly once, guarded by
   `sla_first_response_breached_at`/`sla_resolution_breached_at` — the
   sweep is idempotent under re-runs and under horizontal scaling of
   `celery-beat`/`celery-worker` (the same "mark it and move on" pattern
   M10's outbox relay already established for a different idempotency
   need).

5. **Assignment strategies are a small strategy-pattern interface
   (`AssignmentStrategy.select(candidates, *, session) -> Agent | None`),
   not a single branching function.** `RoundRobinStrategy` picks the
   candidate least-recently assigned anything in this queue;
   `LeastLoadStrategy` picks whoever currently has the fewest open/pending
   conversations assigned company-wide. Adding a third strategy (e.g.
   business-hours-aware, priority-customer-aware) is a new class + one
   registry entry, not a rewrite — the same shape as `ChannelProvider`
   registration, scaled down to two implementations because that's all
   this milestone needs.

6. **A third strategy, `ManualPickupStrategy`, always returns `None` and
   is the default for new queues.** Not every queue should auto-assign —
   a "VIP" or triage queue often needs a conversation to sit visible to
   every eligible agent until one of them actively claims it, rather than
   being silently handed to whoever round-robin/least-load picks next.
   Making this a third `AssignmentStrategy` implementation (not a
   separate `if queue.assignment_strategy is None` branch bypassing the
   strategy dict) keeps `AssignmentEngine.select_agent` itself
   unmodified — see the OCP confirmation below. Manual is the *default*
   for newly-created queues specifically so that "add a queue" doesn't
   silently start auto-assigning until an operator deliberately opts in
   to round-robin/least-load.

7. **`first_picked_up_at` is a distinct column from `picked_up_at`,
   written once and never cleared.** `picked_up_at` reflects the
   *current* assignment (set on claim, cleared back to `null` by
   `release()`, so it can cycle many times over a conversation's life);
   `first_picked_up_at` answers "was this conversation *ever* handled by
   anyone, even once, even if later released?" — the distinction
   `ReportingRepository.queue_metrics()`'s `abandoned_count_24h` needs.
   Without a separate column, a conversation claimed and then released
   (e.g. an agent picks it up, realizes it's not for them, and releases
   it back to the queue) would look identical to one nobody ever touched
   if it were then abandoned — collapsing two different failure modes
   ("nobody ever engaged" vs. "someone engaged, then it stalled anyway")
   into one number. Written from two places — `ConversationRepository
   .claim()` (manual `pick()`) and the ingest consumer's initial
   auto-assignment — both via `func.coalesce(first_picked_up_at, now)`,
   so whichever path claims a conversation first is the one that sticks.

8. **The Live Dashboard's per-queue metrics are computed entirely from
   columns that already exist for other reasons — no new tracking
   infrastructure, no new tables.** `queue_entered_at`/`picked_up_at`/
   `closed_at`/`first_picked_up_at` were each added because some other
   metric or business rule needed them (decision #7 above); the 8 Live
   Dashboard metrics (see the dedicated section below) are all derived
   from these four columns plus the pre-existing SLA breach timestamps —
   a single indexed query per queue, not a background aggregation job or
   a new event-sourced metrics table. This mirrors decision #4's
   preference for "cheap to compute from what's already there" over
   speculative new infrastructure.

9. **The event catalog reuses `conversation.assignment_changed` and
   `conversation.sla_breached` rather than adding `conversation.assigned`/
   `queue.sla_breached` as separate, redundant events.**
   `assignment_changed` already fires on *every* assignment change —
   the ingest consumer's initial auto-assignment (`previous_agent_id:
   null`) and `ConversationService.update()`'s later reassignment
   (`previous_agent_id` set) both publish it with the same shape, so a
   consumer that cares about "this conversation now has an assigned
   agent" already has exactly one event name to subscribe to regardless
   of whether it's the first assignment or the fifth. `conversation
   .sla_breached` already carries `queue_id` in its payload (see
   `SlaMonitorService._publish`), so a queue-scoped consumer doesn't need
   a second, queue-namespaced event to filter on the same information a
   third time. See the full domain event catalog below for the complete
   mapping.

10. **`AgentStatus.BUSY` is self-service-only — never set automatically
    by the WebSocket gateway's connect/disconnect lifecycle, unlike
    `ONLINE`/`OFFLINE`.** An agent already mid-conversation and not ready
    for a new auto-assigned pickup can mark themselves `busy` via
    `PATCH /agents/me/status`; this excludes them from
    `AssignmentEngine.select_agent`'s auto-assignment candidate pool
    (alongside `OFFLINE`) without the system ever guessing "busy" on
    their behalf from connection state — that would require inferring
    workload/attention from a signal (a live WebSocket connection) that
    doesn't actually indicate either. `AWAY` is unaffected and stays
    eligible, unchanged from before this sprint.

## Manual pickup: `pick()` / `release()`

The self-service half of decision #6 — how a conversation sitting in a
`manual` queue (or any queue nobody happened to auto-claim) actually gets
handled:

- **`ConversationService.pick(company_id, conversation_id, actor_agent_id)`**
  — looks the conversation up via the caller's own `company_id` (tenant
  isolation: a cross-tenant call 404s here before anything else runs, not
  403s), confirms it's still queued and unassigned, narrows eligibility
  through the same `filter_by_required_skills` helper
  `AssignmentEngine.select_agent` uses (so manual pickup and
  auto-assignment can never disagree about who's allowed into a skill-
  gated queue), then claims it via `ConversationRepository.claim()` — a
  single atomic conditional `UPDATE ... WHERE assigned_agent_id IS NULL`
  (`rowcount == 1` or the claim is rejected) rather than a
  read-then-write, so two agents clicking "Pick" on the same row at the
  same instant can't both win. Publishes `conversation.picked`.
- **`ConversationService.release(company_id, conversation_id, actor)`** —
  clears `assigned_agent_id`/`picked_up_at` back to `null` (never
  `first_picked_up_at`, per decision #7), returning the conversation to
  its queue's shared pool. Ownership rule: the currently-assigned agent
  may always release their own conversation; releasing *someone else's*
  requires `conversations.transfer` — otherwise `conversations.release`
  (granted to every Agent by default, since releasing your own work is
  routine) would let anyone bypass the supervisory
  `conversations.transfer` gate via release-then-pick. Publishes
  `conversation.released`.
- **RBAC**: `conversations.pick`/`conversations.release` are routine
  agent actions (pick only ever assigns *the caller*, release only ever
  clears back to the shared queue pool — neither can hand a conversation
  to a specific other agent or department), granted to Owner/Admin/Agent
  by default; `conversations.transfer` stays Owner/Admin-only.
- **Frontend**: the Inbox has a "Status | Queue" filter toggle — Queue
  mode lists conversations by `queue_id`/unassigned-only, polls every 10s
  (faster than the Inbox's default 30s, since an agent in this mode is
  actively hunting for work), and shows a "Pick" row action for anyone
  holding `conversations.pick`; a 409 (someone else claimed it first)
  triggers an immediate refetch instead of leaving a stale row visible.
  `ConversationSidebar` gets a matching "Release" button, shown only when
  the viewer is the assignee or holds `conversations.transfer`, mirroring
  the backend rule exactly.

## Live Dashboard metrics

`GET /reports/live-dashboard` returns, per active queue, all 8 metrics
below in one query per queue (`ReportingRepository.queue_metrics()`) —
see decision #8 for why no new tracking infrastructure was needed:

| # | Metric | Field | Computed as |
|---|--------|-------|-------------|
| 1 | Waiting Count | `waiting_count` | open/pending, this queue, `assigned_agent_id IS NULL` |
| 2 | Assigned Count | `assigned_count` | open/pending, this queue, `assigned_agent_id IS NOT NULL` (the other half of `open_conversations`) |
| 3 | Average Wait | `avg_wait_seconds` | `AVG(now - queue_entered_at)` over the current waiting set; `null` if `waiting_count` is 0 |
| 4 | Longest Wait | `longest_wait_seconds` | `MAX(now - queue_entered_at)` over the same waiting set |
| 5 | Average Pickup Time | `pickup_avg_seconds_24h` | `AVG(picked_up_at - queue_entered_at)` for conversations picked up in the last 24h; `null` if none were |
| 6 | SLA Breaches | `sla_breached_count` | open/pending in this queue with either SLA breach timestamp set (reuses the existing M14 columns) |
| 7 | Abandoned Count | `abandoned_count_24h` | queued in the last 24h, now closed, **and `first_picked_up_at IS NULL`** — a heuristic proxy for "never handled," not a tracked "abandoned" state (see decision #7 and the repository's own docstring for the known limitation of this proxy) |
| 8 | Throughput | `throughput_24h` | conversations that reached RESOLVED/CLOSED in the last 24h for this queue, regardless of pickup history — a raw completion-rate signal, independent of #7's narrower "never handled" definition |

`LiveQueueMetrics` (the dataclass backing all 8 fields) is a strict
superset of the older `LiveQueueDepth`/`live_queue_depth()` pair, which
is kept as-is (unused but valid) rather than removed, per this project's
"never remove existing functionality without replacing it" rule — the
live dashboard endpoint now composes from `LiveQueueMetrics` instead.
The dashboard's queue-depth table surfaces metrics #1, #3, #4, #6 as
columns (Waiting/Avg wait/Longest waiting/SLA breached), alongside Open
and Department. Metrics #5/#7 (`pickup_avg_seconds_24h`/
`abandoned_count_24h`) are computed and returned by the API today but
still not given their own table columns — kept as a frontend-only,
additive follow-up, not a backend gap.

### P3.14 — queue stages (waiting/picked/active/resolved/closed)

The Enterprise Readiness & UX milestone (Priority 3, item 14) asked for
the queue dashboard to "clearly present queue stages such as waiting,
picked, active, resolved, and closed" **without changing the existing
`ConversationStatus` model** (still exactly `OPEN`/`PENDING`/`RESOLVED`/
`CLOSED` — there is no dedicated `active` status value). This is solved
by splitting two of the 8 metrics above using a column that already
existed for SLA purposes, `Conversation.first_response_at` (set once, by
`ConversationService.send_reply()`, the first time an agent sends an
OUTBOUND message on that conversation) — no migration, no new column:

| Stage | Definition |
|---|---|
| Waiting | `assigned_agent_id IS NULL` (== metric #1, `waiting_count`) |
| Picked | `assigned_agent_id IS NOT NULL AND first_response_at IS NULL` — assigned, no reply sent yet |
| Active | `assigned_agent_id IS NOT NULL AND first_response_at IS NOT NULL` — assigned and already replied to |
| Resolved (24h) | reached `RESOLVED` in the last 24h, this queue |
| Closed (24h) | reached `CLOSED` in the last 24h, this queue |

`LiveQueueMetrics`/`LiveQueueDepthResponse` add `picked_count`,
`active_count` (split of metric #2, `assigned_count`) and `resolved_24h`,
`closed_24h` (split of metric #8, `throughput_24h`) as new fields
alongside the originals — `assigned_count` and `throughput_24h` are kept
byte-for-byte unchanged (`assigned_count == picked_count + active_count`
and `throughput_24h == resolved_24h + closed_24h` always hold) so no
existing consumer of the API breaks.

The dashboard now renders these stages three ways: a company-wide funnel
chart (`QueueFlowChart`, `@mui/x-charts` `BarChart`) above the per-queue
table totalling waiting/picked/active/resolved/closed across every
queue; a compact per-row stacked "flow" bar (`QueueStageBar`) giving an
at-a-glance proportional view of each queue's waiting/picked/active mix
(with a text `aria-label` carrying the same breakdown for assistive
tech, since color alone conveys nothing without sight); and the
queue-depth table itself, restructured with a two-row grouped header
("Pipeline" for waiting/picked/active, "Last 24h" for resolved/closed,
"Wait times" for avg/longest) so throughput is never visually confused
with what's still in the queue.

## Domain event catalog

Every queue/routing/assignment/pickup operation is event-driven — no
step silently mutates state without a corresponding `DomainEvent` through
the existing M10 outbox → consumer pipeline (audit-log, notification,
reporting, workflow-engine, erp-sync all subscribe to what's relevant to
each).

| Event | Literal `event_type` | Published from | Notes |
|---|---|---|---|
| Conversation queued | `conversation.queued` | `conversation_ingest_consumer` (routing step) | Fires whenever a new conversation is routed into a queue, whether or not auto-assignment then also succeeds |
| Conversation picked | `conversation.picked` | `ConversationService.pick()` | Manual, self-service claim |
| Conversation released | `conversation.released` | `ConversationService.release()` | Back to the queue's shared pool |
| Conversation assigned | `conversation.assignment_changed` | `conversation_ingest_consumer` (initial auto-assign) **and** `ConversationService.update()` (reassignment) | Reused rather than a separate `conversation.assigned` — see decision #9. `previous_agent_id` in the payload is `null` on first assignment, set on reassignment |
| Conversation transferred | `conversation.transferred` | `ConversationService.transfer()` | Distinct from assignment_changed — carries transfer history (note, department-vs-agent target) |
| Conversation resolved | `conversation.resolved` | `ConversationService.update()` | Dynamically constructed as `f"conversation.{status.value}"` when transitioning into `RESOLVED` — not a literal string in the source, but a real, tested event |
| Conversation closed | `conversation.closed` | `ConversationService.update()` | Same dynamic construction, `status.value == "closed"` |
| Agent status changed | `agent.status_changed` | `AgentService.update()` | Fires only when status actually changes; payload carries `previous_status`/`status`. Includes the WS gateway's connect→`online`/disconnect→`offline` transitions and the self-service `online`/`away`/`busy` toggle — all go through the same service method |
| Queue SLA breached | `conversation.sla_breached` | `SlaMonitorService` | Reused rather than a separate `queue.sla_breached` — payload already carries `queue_id`; published exactly once per breach type via the idempotency markers in decision #4 |

## API

`GET/POST /queues`, `GET/PATCH/DELETE /queues/{id}` (`queues.read`/
`queues.manage` — new permissions), `POST/DELETE
/queues/{id}/required-skills/{skill_name}`, `GET/POST /agents/{id}/skills`,
`DELETE /agents/{id}/skills/{skill_name}` (all under `queues.manage`/
`agents.manage` respectively — no new permission needed for the agent
side), `GET/POST /routing-rules`, `GET/PATCH/DELETE /routing-rules/{id}`
(`queues.manage`).

Sprint 2 additions: `POST /conversations/{id}/pick` (`conversations
.pick`), `POST /conversations/{id}/release` (`conversations.release`),
`PATCH /agents/me/status` (self-service, any authenticated agent — see
decision #10). `GET /reports/live-dashboard` (`reports.read`) is
unchanged in shape at the endpoint level but now returns all 8 metrics
above per queue instead of just open/waiting counts.

## Frontend admin UI

A Product & UX Review flagged this directly: every piece of this
milestone above had a complete backend and zero admin screen — creating
a queue or authoring a routing rule required calling the API by hand.
`frontend/src/features/queues/QueuesPage.tsx` (routed at `/queues`,
gated on `queues.read`, mutating actions further gated on
`queues.manage`) closes that gap with two tabs:

- **Queues** — the standard list/create/edit/delete pattern this
  codebase already established for Departments (`DataTable` +
  `FormDialog` + `ConfirmDialog`), covering name, description,
  department (organizational label only, decision #2), assignment
  strategy, both legacy SLA targets, an SLA policy picker (added by the
  SLA Builder — `docs/architecture/sla.md` — the two flat fields' helper
  text now notes they're ignored while a policy is assigned), and the
  active flag.
- **Routing Rules** — a plain, priority-sorted `Table` rather than a
  paginated `DataGrid`, deliberately: `GET /routing-rules` itself is
  unpaginated (decision: this is a short list meant to be seen as a
  whole priority order, not browsed a page at a time), so the frontend
  matches that shape instead of forcing pagination onto data that
  doesn't have it. Each rule's `conditions` (`channel_type`/
  `body_contains`) are authored via a channel-type dropdown (reusing
  `channels/types.ts`'s `CHANNEL_TYPES`) and a plain text field, then
  composed into the same `{channel_type?, body_contains?}` shape the
  backend already expects — no raw JSON exposed to the user.

**Deliberately out of scope**: Required Skills management. The backend
has no endpoint to *list* a queue's current required skills (only
`POST`/`DELETE` to add/remove one by name — `QueueRepository
.required_skill_ids()` exists at the repository layer but was never
exposed through the service or API layer as named skills). Building an
"add a skill" UI with no way to see what's already there would be a
half-feature; this needs a small backend addition (a `GET` endpoint
returning skill names) before it can be built properly, tracked as a
follow-up rather than done speculatively here.

## Extension points

- **A new assignment strategy** is one new `AssignmentStrategy` subclass
  plus one `_STRATEGIES` dict entry (see the OCP confirmation below) —
  e.g. business-hours-aware or priority-customer-aware assignment, named
  as a future refinement in decision #5, remains exactly this shape after
  Sprint 2's `ManualPickupStrategy` addition.
- **Queue eligibility via team membership** (decision #2's documented
  follow-up) would extend `filter_by_required_skills`'s sibling-function
  shape with a second, analogous narrowing function, not a rewrite of
  `AssignmentEngine`/`ConversationService.pick()`.
- **A new Live Dashboard metric** derived from existing columns is a new
  field on `LiveQueueMetrics` plus one more `SELECT` expression in
  `queue_metrics()` — no new tables needed unless the metric requires
  tracking something no existing column captures.
- **A new domain event consumer** (e.g. a future analytics or ERP
  sync need) subscribes to the existing outbox with a new routing-key
  binding, per M10's established pattern — no changes to any publisher
  in the table above.

## Open/Closed Principle confirmation

`AssignmentEngine.select_agent()` and its `_STRATEGIES` registry were
**not modified** to add `ManualPickupStrategy` — the diff that
introduced it is purely additive: one new class implementing the
existing `AssignmentStrategy` ABC, one new dict entry mapping
`QueueAssignmentStrategy.MANUAL` to an instance of it, and one new
`_INELIGIBLE_FOR_AUTO_ASSIGNMENT` tuple entry (`BUSY`, alongside the
pre-existing `OFFLINE`) consumed by the same unchanged eligibility query
`select_agent()` already ran. `RoundRobinStrategy`/`LeastLoadStrategy`
and the method bodies that call into the strategy dict are untouched.
This is the same shape decision #5 committed to at M14: a new assignment
policy is closed for modification, open for extension.

## Verification performed

M14 baseline: 25 new tests. `RoutingEngine`: priority-order evaluation,
`channel_type`/`body_contains` matching (case-insensitively), inactive
rules ignored, and no-match returns `None` rather than a default queue.
Queue/routing-rule/agent-skill CRUD APIs: creation, duplicate-name
conflicts, SLA target updates, soft-delete, required-skill add/remove,
tenant isolation, unauthenticated rejection, skill-assignment
idempotency. Assignment/routing end-to-end: a brand-new conversation is
both routed to the matching rule's queue and assigned to the (only)
eligible online agent; a second message on the same thread does not
re-route or re-assign; `LeastLoadStrategy` prefers the agent with fewer
open conversations over one with two already assigned; a queue's
required skill correctly excludes an unskilled agent and selects the
skilled one; a queue whose required skill nobody has leaves the
selection `None` rather than falling back to an ineligible agent.
`SlaMonitorService`: a conversation past its first-response deadline
publishes `conversation.sla_breached` exactly once — a second sweep run
does not re-publish.

Sprint 2 additions: `pick()`/`release()` success, ownership/
authorization (assignee-or-transfer-holder release rule), atomic-claim
race safety, skill-gated pickup eligibility parity with auto-assignment,
and — added this pass to close a verification gap with no prior
dedicated test — explicit cross-tenant `pick()`/`release()` checks
(`test_pick_404s_for_a_conversation_belonging_to_another_company`,
`test_release_404s_for_a_conversation_belonging_to_another_company`),
confirming a Company B caller (even one holding `conversations.transfer`
in their own company) gets a 404 against Company A's conversation, not a
403 or a successful bypass. `busy` status exclusion from
auto-assignment. Live Dashboard: all 8 metrics computed correctly
against seeded data, including the `assigned_count`/`throughput_24h`
endpoint-wiring gap found and fixed this pass (see the Sprint 2 Queue
Ops release report). Full domain-event audit: all 9 named events
confirmed present and correctly triggered (2 of the 9 intentionally
reuse existing, broader events — `assignment_changed`/`sla_breached` —
per decision #9, not gaps). `AssignmentEngine` OCP compliance confirmed
by diff inspection (no existing strategy class or registry-consuming
method modified).

762 backend tests passing (up from the M14-era 171), `ruff check`/
`ruff format --check`/`mypy` clean. 161 frontend tests passing, `tsc -b`/
`eslint` clean. Verified live against the full 9-container Docker stack
(all services rebuilt from the shared `docker/backend/Dockerfile`):
created a queue, confirmed `GET /reports/live-dashboard` returns
`assigned_count`/`throughput_24h` correctly (previously a
`ValidationError` — see the release report) against the real running
Postgres-backed stack, not just the test suite.
