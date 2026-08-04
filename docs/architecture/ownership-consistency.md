# Ownership consistency

*Who is answerable for a conversation has exactly one source of truth.*

`conversation_ownership` is the business history. `Conversation.assigned_agent_id`
is a projection of it. This document is the audit that made that true, and the
report on what remains.

---

## The problem this closes

Two facts were live at once, and they were written independently.

| | `Conversation.assigned_agent_id` | `conversation_ownership` |
|---|---|---|
| Shape | A mutable column | An append-only timeline |
| Answers | "who is assigned" | "who is answerable" |
| Written by | 7 call paths | 6 call paths — **not the same 7** |

M3 introduced ownership precisely because assignment could not express *"the
queue is responsible while nobody holds it"*. Both then continued to be
written, by overlapping but not identical sets of callers, and nothing
compared them.

**The defect that proved it.** `workflow_actions/builtin.py::AssignToAgentAction`
called `ConversationService.update(assigned_agent_id=…)`, which set the column,
cleared `autopilot_active` and wrote no ownership row. A workflow that assigned
a conversation produced an Inbox row saying **the queue owns this** and an
assignment saying **an agent has this** — on the screen built to make
responsibility obvious.

The audit found three more things the original report did not:

1. **`take_over_from_autopilot` recorded nothing.** A human taking a
   conversation back from AI moved the column and left the timeline saying AI
   still held it. This is the transition every "AI must not speak after a human
   steps in" rule reads.
2. **`release()` on a queue-less conversation recorded nothing**, leaving the
   timeline naming an agent who had just let go.
3. **Three production wiring sites built `ConversationService` with
   `ownership=None`** — the SLA sweep, the workflow engine consumer and the CSAT
   dispatch consumer. Two of those are the exact paths defect #1 was about, so
   even a corrected `update()` would have been a no-op there. The missing call
   was the visible half of the bug; the missing wiring was the other half.

---

## The model

**Ownership is the source. Assignment is a projection.**

```
domain/ownership.assigned_agent(owner)      the rule, framework-free
  HUMAN_AGENT  -> that agent's id
  QUEUE        -> None
  AI_QUEUE_WORKER -> None
  TEAM         -> None
  NOBODY       -> None
```

Total by construction: every `OwnerKind` has an answer, so a kind added later
cannot silently fall through to "leave whatever was there" — which is the shape
the original defect took.

`OwnershipService.transfer` is the one place a transition happens. It writes the
history row and then the projection, in that order, in the same transaction. The
order is not cosmetic: a failure between them leaves the truth written and a
projection to rebuild, never a projection with no history behind it.

### Two consequences that had to follow

**Ownership is no longer optional.** `ConversationService` took
`ownership: OwnershipService | None = None`. It is now required. A service
without one would accept an assignment and quietly not perform it.

**Ownership failures are no longer swallowed.** `_record_ownership` caught and
logged every exception, on the reasoning that the handover was the product and
the row was evidence. That reasoning expired the moment the row *became* the
handover. Swallowing now would mean reporting a conversation assigned to
somebody who does not have it.

---

## The report

Every operation that can change who is answerable for a conversation.

| Operation | Entry point | Ownership event | `assigned_agent_id` | Timeline | Decision log | SLA | AI |
|---|---|---|---|---|---|---|---|
| **Arrival, routed to a queue** | `conversation_ingest_consumer` | `NEW_CONVERSATION` → queue | projected `None` | ✅ | `QUEUE_SELECTED` | queue clock starts | eligible, may defer |
| **Arrival, auto-assigned** | `conversation_ingest_consumer::_route_and_assign` | `ASSIGNED_BY_STRATEGY` → agent | **projected** *(was set directly)* | ✅ | `AGENT_ASSIGNED` | `owner_accepted` | — |
| **Arrival, nothing matched** | `conversation_ingest_consumer` | none — nothing to own it | unchanged | — | `LEFT_UNROUTED` | — | never offered |
| **Pick** | `POST /conversations/{id}/pick` | `PICKED_BY_AGENT` → agent | claim (CAS) + projection | ✅ | — | `owner_accepted` | autopilot cleared |
| **Release** (has queue) | `POST /conversations/{id}/release` | `RELEASED_BY_OWNER` → queue | projected `None` | ✅ | — | queue clock restarts | — |
| **Release** (no queue) | same | `RELEASED_BY_OWNER` → **`NOBODY`** *(new)* | projected `None` | ✅ | — | — | — |
| **Transfer to agent** | `POST /conversations/{id}/transfer` | `MANUAL_TRANSFER` → agent | **projected** *(was set directly)* | ✅ | — | — | autopilot cleared |
| **Transfer to department** | same | `MANUAL_TRANSFER` → queue/team | **projected** *(was set directly)* | ✅ | — | — | autopilot cleared |
| **Manual assignment** | `PATCH /conversations/{id}` | `MANUAL_TRANSFER` → agent **(new)** | **projected** *(was the defect)* | ✅ | — | — | autopilot cleared |
| **Workflow assignment** | `assign_to_agent` action | `ASSIGNED_BY_STRATEGY` → agent **(new)** | **projected** | ✅ | — | — | autopilot cleared |
| **Workflow queue move** | `assign_to_queue` action | `ASSIGNED_BY_STRATEGY` → queue **(new, conditional)** | projected `None` | ✅ | — | — | — |
| **SLA escalation → agent** | `sla_sweep_task` | `ESCALATION` → agent **(new)** | **projected** | ✅ | — | — | autopilot cleared |
| **SLA escalation → queue** | `sla_sweep_task` | `ESCALATION` → queue **(new, conditional)** | projected `None` | ✅ | — | — | — |
| **AI pickup** | `ai_pickup_sweep_task` | `AI_ENGAGEMENT` → AI | projected `None` | ✅ | `AI_PICKED_UP` | `owner_accepted` | engages |
| **AI stands down** | `ai_pickup_sweep_task` | none — owner unchanged | unchanged | — | `AI_STOOD_DOWN` | — | never engages |
| **AI hand-off** | `AutopilotService._hand_off` | `AI_RELEASED` → queue | projected `None` | ✅ | — | — | autopilot cleared |
| **Human takes over from AI** | `POST /conversations/{id}/autopilot/stop` | `AI_RELEASED` → agent or queue **(new)** | **projected** *(was set directly)* | ✅ | — | — | autopilot cleared |
| **Lapsed sticky hold** | `ownership_sweep_task` | `OWNERSHIP_EXPIRED` → queue | projected `None` | ✅ | — | — | — |

**Queue moves are conditional on purpose.** Changing which queue a conversation
belongs to moves the *owner* only when the queue is who currently holds it. If an
agent has it, changing its queue does not take it off their desk, and writing a
transition would record a handover that did not happen.

### Operations that are not ownership changes

Listed because they were asked about, and "it deliberately does nothing" is an
answer that has to be written down or it gets re-litigated.

| Operation | Why not |
|---|---|
| **Resolve** | The owner who resolved it keeps it — that is what makes a customer's follow-up reach the person who already knows them. |
| **Close** | Same. |
| **Reopen** | `CLOSED → WAITING` restores a live conversation to whoever the timeline already says holds it. |
| **Bulk assignment** | Does not exist. There is no bulk-assign endpoint, service method or task. |

---

## What enforces this

`tests/unit/test_ownership_is_the_only_writer.py` — an AST guard over `src/`,
in the shape of the existing wiring and task-disposal guards.

It fails when any function writes `assigned_agent_id` and is not on a
two-entry allow-list:

- `OwnershipRepository.project_assignment` — the projection itself, reachable
  only from `OwnershipService.transfer` (asserted separately).
- `ConversationRepository.claim` — the compare-and-set that decides which of two
  agents pressing *Pick* at the same instant wins. Its `WHERE` clause **is** the
  race, so it cannot be expressed as a transition. `pick()` records the
  transition immediately after a successful claim, and a companion test fails if
  it ever stops doing so.

The guard also fails on a **stale** allow-list entry, because an exemption for
code that no longer exists reads like coverage and is not.

Verified by planting a real writer in a real module: the guard failed and named
it, `application/services/csat_service.py::_planted_violation (line 171)`.

---

## Transitional architecture

**`assigned_agent_id` is a maintained projection, not yet a derived one.**

It is still a stored column. Nothing writes it independently any more — every
value in it is the consequence of an ownership transition — but it is written
rather than computed, so a direct `UPDATE` outside the application would still
put it out of step with the timeline.

It stays stored because it is read in query positions where a join to "the
newest ownership row per conversation" would be a window function inside the
Inbox's hot path: `conversation_repository` filters and the Inbox view SQL,
`reporting_repository`'s live dashboard and agent workload, the notification
rules, CSAT attribution.

Two things would have to exist before the column could go:

1. **A current-owner projection table or indexed view** that `WHERE
   owner_id = ?` can use as cheaply as the column does today.
2. **A reconciliation sweep**, so drift introduced outside the application is
   found rather than assumed impossible.

Neither is required for correctness now, and both are ordinary work rather than
research. Until then the guarantee is exactly the one stated above: one writer,
one rule, one test that fails when a second appears.
