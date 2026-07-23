# Queues, Assignment Engine, Routing Engine

M14 of the roadmap, closing out Phase 2 (Conversations Core). Decides
*where* a new conversation goes (routing), *who* handles it (assignment),
and *whether it's late* (SLA/escalation) — all triggered from the same
seam M13 already built: the conversation-ingest consumer, on a
newly-created conversation only, never on a conversation's later messages.

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
this milestone. Likewise, SLA breach detection here only *publishes an
event*; the actual escalation *action* (reassign, page a supervisor,
notify) is Workflow Engine (M19) / Notifications (M21) territory —
consuming `conversation.sla_breached` is exactly what those milestones
are for, not something to fake here with a half-built notification path.

## Data model

```
queues
------
id (PK), company_id (FK, CASCADE)
name                        unique per company among active rows
department_id (FK, SET NULL, nullable)   organizational label only —
                                          NOT an eligibility filter (see
                                          decision #2)
assignment_strategy         round_robin | least_load
first_response_target_minutes (nullable) — null = no SLA on this queue
resolution_target_minutes (nullable)
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
```

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

## API

`GET/POST /queues`, `GET/PATCH/DELETE /queues/{id}` (`queues.read`/
`queues.manage` — new permissions), `POST/DELETE
/queues/{id}/required-skills/{skill_name}`, `GET/POST /agents/{id}/skills`,
`DELETE /agents/{id}/skills/{skill_name}` (all under `queues.manage`/
`agents.manage` respectively — no new permission needed for the agent
side), `GET/POST /routing-rules`, `GET/PATCH/DELETE /routing-rules/{id}`
(`queues.manage`).

## Verification performed

25 new tests. `RoutingEngine`: priority-order evaluation, `channel_type`/
`body_contains` matching (case-insensitively), inactive rules ignored,
and no-match returns `None` rather than a default queue. Queue/routing-
rule/agent-skill CRUD APIs: creation, duplicate-name conflicts, SLA
target updates, soft-delete, required-skill add/remove, tenant isolation,
unauthenticated rejection, skill-assignment idempotency. Assignment/
routing end-to-end: a brand-new conversation is both routed to the
matching rule's queue and assigned to the (only) eligible online agent;
a second message on the same thread does not re-route or re-assign;
`LeastLoadStrategy` prefers the agent with fewer open conversations over
one with two already assigned; a queue's required skill correctly
excludes an unskilled agent and selects the skilled one; a queue whose
required skill nobody has leaves the selection `None` rather than
falling back to an ineligible agent. `SlaMonitorService`: a conversation
past its first-response deadline publishes `conversation.sla_breached`
exactly once — a second sweep run does not re-publish. 171 tests total
passing across the whole suite; `ruff check`/`mypy` clean.
