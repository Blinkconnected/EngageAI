# The Inbox

**The Inbox is not a table.** It is the operations screen an agent lives in,
and its success criterion is a second: an experienced agent should understand
their workload without reading rows.

Everything below exists to serve that. An element that does not help somebody
decide *what to do next* does not belong on this screen.

## Views, not filters

The old Inbox asked the agent to construct a query — a mode toggle, a status
tab strip, and a switch whose meaning changed depending on the mode. Three
controls, most of whose combinations mean nothing, and all of which require
knowing the data model before you can ask a question.

Views replace that. Each is an operational question with one answer:

| View | Means | Defined as |
|---|---|---|
| `needs_attention` | Somebody must act, now | Unfinished, and either the SLA is at risk or breached, or it is sitting in a queue with nobody and no AI on it |
| `waiting_pickup` | Nobody has taken it | In a queue, no agent, AI not active |
| `mine` | On my plate | Assigned to the calling agent |
| `waiting_customer` | The ball is with them | Status `waiting_customer` |
| `ai_working` | AI has it | Autopilot active, or waiting out its pickup delay |
| `breached` | A promise was broken | SLA health `breached` |
| `at_risk` | About to break | SLA health `at_risk` |
| `resolved_today` | Finished today | Resolved or closed, today |

Filters (queue, channel, priority) still exist and are **secondary** — they
narrow a view rather than constitute one.

Each view is a first-class query on the server. Computing them in the browser
would mean filtering the page in hand, which is not filtering the Inbox — the
same mistake the SLA ordering avoided in M4.

## The workload strip

Counts for every view, above the list, each one clickable and each one
becoming the view. This is the part that answers the workload in a second:
*"4 breached, 11 waiting for pickup, 6 mine"* is a sentence an agent reads
without scanning anything.

Counts are computed server-side across the whole company, not from the loaded
page. A count derived from fifty rows would be wrong in exactly the situation
it matters — a busy queue.

## What a row must answer

Seven questions, in this order — and the order is the design:

1. **Who is this?** — the customer, by name
2. **Why am I seeing this?** — the operational state
3. **Who owns it?** — Queue, Agent, AI, Customer or Supervisor, explicitly
4. **How urgent is it?** — SLA health
5. **How long has it been like this?** — time in the current state
6. **What happened most recently?** — the last meaningful event
7. **What did the customer actually say?** — the last message

The last message is deliberately last. The previous row answered mostly
metadata — channel, avatar, priority, status, timestamp, assignee — seven
columns of *description*, and nothing that explained why the conversation was
in front of anybody.

An agent should understand why a conversation is here **before** reading its
content.

### SLA dominates, priority does not

They are different questions and were sharing a cell. Priority is business
importance — *does this matter more?* SLA health is operational urgency —
*is this running out of time?* Only one of them can be fixed by acting now,
and that one gets the visual weight.

### Ownership is shown, never inferred

Ownership became a first-class concept in M3 and was visible only inside the
conversation. An agent should not open a conversation to learn who is
answerable for it. The row names the owner and their kind.

### AI is an operational state

Not a badge hidden inside an assignee column. AI is either responding or
waiting out a pickup delay, and an agent should never wonder which. Both are
values of `state`, beside every other thing a conversation can be waiting on
— so AI is read in the same glance as everything else rather than in a
separate place.

### The preview explains why the row is here

"Last message" describes the thread. The last *meaningful event* — customer
replied, AI responded, transferred to Billing, escalated, resolved — explains
why this conversation is in front of you. That is the difference between a
message list and an operations screen.

## Operational state

`domain/operational_state.py` names what a conversation is waiting on:
waiting for pickup, ready for reply, waiting for customer, AI responding, AI
pickup delay, escalated, transferred, resolved, awaiting feedback, closed.

**Described, never prescribed.** A field that said "Pick up" or "Reply" would
be the platform issuing instructions from a partial view — it does not know
that this agent is already on a call, or that a supervisor asked for
something else first. A field that says *waiting for pickup* is a fact, and an
experienced agent reads a fact faster than they evaluate advice.

Derived from facts already kept, never stored, so it cannot drift out of step
with the conversation it describes. Computed on the server for the same reason
severity is: every client must describe the same conversation the same way.

The precedence is stated because a rule set this size is right by accident
otherwise. A closed conversation is closed whatever else is true of it; AI
holding one outranks the queue it came from; and *how* somebody came to own it
— escalated, transferred — outranks the plain status, because that is what an
agent scanning needs to notice rather than have buried among ordinary work.

`AI_RESUME_DELAY` exists in the vocabulary and nothing assigns it:
`ai.resume_delay_seconds` is configuration nothing reads yet. A conversation
must never be described as waiting for a behaviour the platform does not have,
and a test fails the day somebody wires resume without revisiting it.

## Ownership comes from the timeline

The row reads the current owner from the ownership history — a window function
over `conversation_ownership`, not `assigned_agent_id`. Those are separate
concepts, and an Inbox that showed one while calling it the other would undo
the distinction the ownership model exists to make. `owner_since` is the
closest thing the platform records to "how long has it been like this".

A window function rather than `DISTINCT ON`: PostgreSQL has the latter and
SQLite does not, and a query that only works in production is one that fails
where it matters.

## What the server must send

The Inbox must never make a request per row. `customer_name` on the list
response replaces one HTTP call per visible conversation — twenty rows meant
twenty requests, each with its own skeleton, so the single most important
identifier arrived last and staggered.

Every derived field on the row — `sla_health`, `state`, `owner_*`,
`owner_since`, and the last meaningful event — is computed once on the server
for the same reason severity is: every client must show the same answer, and a
browser working it out from adjacent fields is a browser forming a judgement
the platform never made.

The Inbox and the Conversation Story describe the same conversation, and they
must never disagree about it. Both read the same fields from the same place.

## Two bugs the views found

**"Assigned to me" returned the entire unassigned backlog.** `assigned_agent_id
== agent_id` with a null id compiles to `IS NULL` in SQL, so anybody without an
agent profile — an owner, a supervisor — was told every conversation nobody had
picked up was personally theirs. No agent identity now means an empty list,
which is the honest answer.

**An unknown view returned everything.** Now a 422. A typo that quietly showed
the wrong work is worse than an error, on a screen whose value is being trusted
at a glance.

## What was deliberately removed

- **The channel column.** It rarely changes what an agent does first and cost
  a flex column. It survives as a small mark beside the customer.
- **The status column.** Status is a lifecycle fact; the views encode the
  operational meaning of it, and the row shows the owner and the last event
  instead.
- **The mode toggle and the meaning-shifting switch.** Both are views now.
