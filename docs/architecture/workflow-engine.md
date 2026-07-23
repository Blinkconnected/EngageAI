# Workflow Engine

M19 of the roadmap, opening Phase 4 (Engagement Intelligence). The first
module that consumes from the M10 event bus purely as a subscriber, with
no channel/provider concerns at all — proving the bus actually delivers
on its original promise: "all future modules... consume events from the
bus rather than depending on the conversation engine directly."

## Closing gaps in the original event-bus mandate

The architecture mandate that opened this build named a specific list of
events every future module should be able to rely on: "message received/
sent, customer created, assignment changed, AI completed, ERP updated,
workflow executed." Building the Workflow Engine's trigger surface
exposed that two of those had never actually been published, and a third
only existed in a form too raw to be useful:

- **`message.received`** (M11) fires *before* persistence, straight off
  the provider webhook payload — no `conversation_id`/internal
  `customer_id`, since those don't exist yet at that point. A workflow
  wanting to act on "a message arrived in conversation X" had nothing to
  bind to. Fixed by having `conversation_ingest_consumer` publish a new
  **`message.persisted`** event after persisting, carrying
  `conversation_id`/`message_id`/`customer_id` directly in its payload —
  the enriched, post-persistence event `message.received` was never meant
  to be.
- **`conversation.created`** didn't exist at all — the consumer created
  `Conversation` rows directly with no accompanying event. Added,
  published only on first-message-of-a-thread (mirroring how
  `_route_and_assign` already only runs once per conversation).
- **`conversation.assignment_changed`** was named in the mandate but
  never published — not from the initial auto-assignment in
  `_route_and_assign`, and not from `ConversationService.update()`'s
  manual reassignment path either (both only emitted the generic
  `conversation.updated`). Added to both call sites, as a dedicated event
  *alongside* `conversation.updated` (not replacing it) — additive, no
  existing consumer's behavior changes.
- **`customer.created`** existed for API-driven creation
  (`CustomerService.create`, M8) but not for a customer auto-created on
  first contact from a channel (`conversation_ingest_consumer`'s email
  and generic `CustomerChannelIdentity` branches, M15/M16) — every
  creation path now publishes it.

All four additions are purely additive (new events, new payload keys on
an existing event) — no existing consumer or test needed to change.

## Domain model

`WorkflowDefinition` (company-scoped, soft-deletable): `trigger_event_type`
(a plain string, not a DB enum — same reasoning as `ChannelConfig.
channel_type`: new event types from future milestones need zero
migration), `conditions` (JSON), `actions` (JSON, an ordered list),
`priority` (lower runs first among workflows sharing one trigger),
`is_active`.

`WorkflowRun` (append-only, no `SoftDeleteMixin`/`updated_at` — same
reasoning as `AuditLog`/`EventOutbox`): one row per (workflow, triggering
event) pair, *unconditionally* — whether it matched and succeeded, matched
and failed partway, or was skipped for not matching `conditions`. A
workflow that never fires is exactly as visible in the audit trail as one
that does, which matters for debugging a misconfigured condition.

## The condition DSL (`domain/workflow_condition.py`)

Pure, dependency-free, unit-testable in isolation:

```json
{"all": [
  {"field": "payload.channel_type", "operator": "equals", "value": "whatsapp"},
  {"any": [
    {"field": "payload.body", "operator": "contains", "value": "refund"},
    {"field": "payload.body", "operator": "contains", "value": "cancel"}
  ]}
]}
```

`all`/`any` (AND/OR) nest arbitrarily via recursion. Deliberately not a
full expression grammar (no arithmetic, no cross-field comparison) —
"visual-friendly" per the roadmap means a drag-conditions-into-groups
builder, which this shape maps onto directly without a frontend needing
to generate arbitrary code. An empty condition tree matches
unconditionally. `field` is a dot-path into the event dict (e.g.
`payload.channel_type`); missing fields resolve to `None` and fail
matches rather than raising, so a workflow referencing a field one event
type doesn't carry simply never fires for that event, instead of
crashing evaluation.

## The action plugin system

`WorkflowAction` (`application/workflow_actions/base.py`) + a third
application of the "named lookup from a database-stored string" registry
idiom this codebase keeps reaching for (`ChannelRegistry` → M11,
`SmsGatewayRegistry` → M18, now `WorkflowActionRegistry`). Lives in
`application/`, not `domain/`, unlike `ChannelProvider`: actions
legitimately need `ConversationService`/repositories (internal,
first-party orchestration), where `ChannelProvider` is a contract a
hypothetical third-party plugin author must be able to implement without
ever importing SQLAlchemy.

`WorkflowActionRegistry.register(...)` decorates a class exactly like
`ChannelRegistry` does, but stores one constructed instance per action
type — unlike channel providers (built per-`ChannelConfig`, since each
carries different credentials), actions are stateless.

Built-in catalog (`application/workflow_actions/builtin.py`):

| Action | What it does | Notes |
|---|---|---|
| `add_tag` | Tags the triggering event's customer | Direct `TagRepository`/`CustomerRepository` use — adds one tag, doesn't replace the set |
| `assign_to_queue` | Sets the conversation's queue | Via `ConversationService.update()` |
| `assign_to_agent` | Sets the conversation's assigned agent | Via `ConversationService.update()` |
| `set_conversation_status` | Transitions conversation status | Via `ConversationService.update()` — reuses its existing transition validation, doesn't re-derive it |
| `send_reply` | Sends an outbound reply | Via `ConversationService.send_reply()` — the same channel-agnostic provider-dispatch path every API-driven reply already uses; text-only (no attachment support) |
| `publish_event` | Publishes an arbitrary custom domain event | The extensibility escape hatch — see below |

Every conversation-touching action requires the triggering event's
payload to carry `conversation_id` (or `customer_id` for `add_tag`) — true
for `conversation.created`, `message.persisted`, and
`conversation.assignment_changed`, not true for e.g. `customer.updated`.
Referencing a workflow action against an event type that doesn't carry
the right id is a configuration error, surfaced as a failed `WorkflowRun`
with a clear `error_message`, not a crash.

**Deliberately not built**: a generic outbound-HTTP/webhook action. That
would need URL/SSRF sandboxing (arbitrary user-configured workflows
issuing arbitrary outbound requests from our infrastructure is a real
attack surface) and is better scoped as its own milestone once a concrete
integration (ERPNext, M24) defines what's actually needed, rather than
built speculatively with security controls guessed in advance.

### The `publish_event` escape hatch

Lets a workflow emit any custom `event_type` onto the same bus. This is
how future modules (Notifications, ERP sync) integrate with workflows
with zero changes here or to the Workflow Engine: a company's workflow
publishes `"notification.custom"` or `"erp.sync_requested"`, and whatever
module cares subscribes to it, exactly the same way `audit-log-consumer`
and this milestone's own consumer already subscribe to `#`.

## Execution engine (`WorkflowEngine`)

`handle_event(context)`: loads active `WorkflowDefinition`s for
`context.event["event_type"]`, priority-ordered, and runs each in turn.
Per workflow: evaluate `conditions`; if they don't match, record a
`SKIPPED` run and move on. If they match, execute `actions` in order,
**stopping at the first failure** (an unknown action type or a raised
exception) — a partially-applied side effect from an earlier successful
action in the list is not undone (no saga/compensation logic; actions are
independent, idempotent-enough operations like "add a tag" or "send a
reply," not multi-step transactions needing rollback). One workflow's
failure is caught and recorded, never allowed to propagate — it must
never break evaluation of sibling workflows or crash the consumer's
message-processing loop.

Every run — matched-and-succeeded, matched-and-failed, or skipped —
publishes a **`workflow.executed`** domain event (payload:
`workflow_id`/`status`/`actions_executed`) in addition to the `WorkflowRun`
row, closing the last event named in the original mandate. Publishing it
uniformly (not just on success) means a monitoring consumer can watch
skip/failure rates without querying `workflow_runs` directly.

## The consumer

`workflow_engine_consumer.py` binds `queue_name="workflow-engine"` to
routing key `"#"` — the second consumer (after `audit-log-consumer`) to
subscribe to everything, since a workflow can be configured to trigger on
any event type and there's no way to know which ones in advance. Builds a
real `ConversationService` per event (mirroring `email_imap_poll_task.py`'s
module-level cached engine/redis/minio pattern) so the `send_reply` action
has a fully working provider-dispatch path, not a stub.

**A caveat worth stating plainly**: binding `#` combined with the
`publish_event` action and `workflow.executed` itself means a workflow
*could* be configured into a self-triggering loop (e.g., triggering on its
own `workflow.executed`, whose action republishes the same event type).
This is the same category of risk every workflow-automation product
(Zapier, n8n, ...) carries and manages through user configuration
guardrails, not something this milestone builds a "loop breaker" for
speculatively — flagged here as a known, accepted limitation, worth
revisiting if it becomes a real operational problem.

## Schema impact

Two new tables (`workflow_definitions`, `workflow_runs`) plus a
permission-catalog seed (`workflows.read`/`workflows.manage`, granted to
Owner/Admin; Agent gets read-only) — both migrations follow this
codebase's established patterns exactly (hand-written, `GUID()`, the
"fixed permission snapshot" seeding style). No changes to any other
table's schema — the new events added to close the mandate gaps are
payload-only additions to already-existing `DomainEvent` publish calls.

## Verification performed

33 new tests added (299 → 332 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_workflow_condition.py` (16 tests) — every operator,
  both combinators, nesting, missing-field and unknown-operator handling.
- `tests/integration/test_workflow_engine.py` (6 tests) — condition
  matching → `add_tag` executes and `workflow.executed` publishes
  `succeeded`; non-matching → skipped, no action runs; an unknown action
  type → failed, remaining actions never execute; `send_reply` through
  the real `ConversationService`/Web Chat provider path; an inactive
  workflow never triggers; a run appears in the `/runs` history endpoint.
- `tests/integration/test_workflow_engine_consumer.py` (1 test) — the
  consumer module's own DI wiring, on top of the engine behavior already
  covered above.
- `tests/integration/test_workflows_api.py` (8 tests) — full CRUD,
  pagination, company scoping, authentication, soft delete, 404s, and the
  run-history endpoint.
- `tests/integration/test_conversation_ingest_consumer.py` (+2 tests) —
  `conversation.created`/`message.persisted` publish with the right
  payload on first contact (plus a `customer.created` assertion added to
  an existing email first-contact test), and `message.persisted`-only (no
  re-publish of `conversation.created`) on a second message.
- `tests/integration/test_assignment_and_routing.py` (+1 assertion) —
  `conversation.assignment_changed` publishes with the right agent id on
  initial auto-assignment.
