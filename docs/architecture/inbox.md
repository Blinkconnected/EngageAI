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

Six questions, in this order:

1. **Who** — the customer, by name
2. **How healthy** — SLA health, the dominant visual signal
3. **Who owns it** — Queue, Agent, AI, Customer or Supervisor, explicitly
4. **What happened** — the last *meaningful event*, not the last message
5. **How long** — time waiting
6. **What should I do** — pick up, reply, review, or nothing

The previous row answered mostly metadata: channel, avatar, priority, status,
timestamp, assignee. Seven columns of *description* and nothing that said
"act on this".

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

Not a badge hidden inside an assignee column. AI is either responding,
waiting out a pickup delay, or has handed back — and an agent should never
wonder which. The states come from the backend (`ai_state`), the same field
the Conversation Story uses, so the two screens cannot disagree.

### The preview explains why the row is here

"Last message" describes the thread. The last *meaningful event* — customer
replied, AI responded, transferred to Billing, escalated, resolved — explains
why this conversation is in front of you. That is the difference between a
message list and an operations screen.

## What the server must send

The Inbox must never make a request per row. `customer_name` on the list
response replaces one HTTP call per visible conversation — twenty rows meant
twenty requests, each with its own skeleton, so the single most important
identifier arrived last and staggered.

Every derived field on the row (`sla_health`, `owner_*`, `ai_state`,
`last_event`, `next_action`) is computed once on the server for the same
reason severity is: every client must show the same answer, and a browser
working it out from adjacent fields is a browser forming a judgement the
platform never made.

## What was deliberately removed

- **The channel column.** It rarely changes what an agent does first and cost
  a flex column. It survives as a small mark beside the customer.
- **The status column.** Status is a lifecycle fact; the views encode the
  operational meaning of it, and the row shows the owner and the last event
  instead.
- **The mode toggle and the meaning-shifting switch.** Both are views now.
