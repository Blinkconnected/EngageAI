# SLA Engine

**How Blink Engage decides that a conversation is approaching, or past,
its response and resolution targets — and what it does about it.**

Written for an administrator configuring SLA policies (`/sla`), business
hours, holidays and escalation rules, and for anyone trying to explain a
breach after the fact. It describes the system **as it behaves today**.

Companion documents: [queue-architecture.md](queue-architecture.md),
[queue-lifecycle.md](queue-lifecycle.md),
[assignment-logic.md](assignment-logic.md),
[routing-rules.md](routing-rules.md). Original design records:
[sla.md](sla.md) and [queues-routing.md](queues-routing.md) decision #4.

---

## 1. What the SLA engine is

A **background sweep that runs once a minute** and, for every open
conversation that sits in a queue, asks two questions:

1. Has enough time passed that we should *warn* somebody?
2. Has enough time passed that this has *breached*?

When the answer is yes it stamps a timestamp on the conversation,
publishes an event, and runs whatever escalation rules the policy
defines. That is the whole engine.

It is **detection and reaction, not prevention**. Nothing about the SLA
engine makes a conversation get answered faster; it only makes lateness
visible and, if you configure it to, moves the conversation or notifies
someone.

```mermaid
flowchart LR
    T([Celery beat<br/>every 60 seconds]) --> S[Load every open/pending<br/>conversation that has a queue]
    S --> P[Resolve the effective SLA config<br/>policy, or legacy fields, or none]
    P --> F[Check first-response clock]
    P --> R[Check resolution clock]
    F --> O1{past deadline?}
    F --> O2{past warning?}
    R --> O3{past deadline?}
    R --> O4{past warning?}
    O1 --> E[stamp marker → publish event → run escalations]
    O2 --> E
    O3 --> E
    O4 --> E
```

---

## 2. Which configuration applies

Every conversation resolves to exactly one **effective SLA config**,
chosen in this order:

```mermaid
flowchart TD
    A([Conversation]) --> B{Has a queue_id?}
    B -- no --> N([NO SLA AT ALL.<br/>Not monitored, ever.])
    B -- yes --> C{Queue has sla_policy_id<br/>AND that policy is_active?}
    C -- yes --> P([Use the policy:<br/>targets, warning threshold,<br/>business hours, escalation])
    C -- no --> D{Queue's own<br/>first_response_target_minutes /<br/>resolution_target_minutes set?}
    D -- yes --> L([Use the legacy flat fields:<br/>plain wall-clock, no warning,<br/>no business hours, no escalation])
    D -- no --> N2([No SLA. Never flagged.])
```

Three things follow, and all three catch people out:

**A conversation with no queue has no SLA whatsoever.** The sweep joins
conversations to queues; a conversation that never matched a routing rule
is invisible to it. It cannot breach, cannot warn, and appears in no SLA
report. See [routing-rules.md](routing-rules.md) §6.

**Deactivating a policy does not disable SLA — it silently reverts the
queue to its legacy flat fields.** Setting `is_active = false` on a
policy makes every queue using it fall back to
`first_response_target_minutes`/`resolution_target_minutes`. If those are
still set from before the policy was assigned, the *old* wall-clock
targets quietly come back. If they are null, SLA disappears entirely. Neither
outcome is announced anywhere.

**A queue's flat fields are not cleared when a policy is assigned.** They
sit there, ignored, as a live fallback. The Queues screen's helper text
says they are ignored while a policy is assigned, which is true — right
up until the policy is deactivated.

---

## 3. The two clocks

| Clock | Starts at | Stops when | Target field |
|---|---|---|---|
| **First response** | `conversation.created_at` — the instant the first inbound message was persisted | `first_response_at` is set: the first time **any** outbound message is successfully sent on the conversation | `first_response_target_minutes` |
| **Resolution** | `conversation.created_at` — the same instant | The conversation leaves `open`/`pending`, i.e. reaches `resolved` or `closed` | `resolution_target_minutes` |

Both clocks start at the same moment, and both measure from the
conversation's creation — **not** from `queue_entered_at`, not from the
most recent customer message, and not from when it was assigned.

Notes that matter:

- **A failed send does not stop the first-response clock.** If the
  channel provider rejects the message, the outbound message row is
  persisted with status `failed` and `first_response_at` is left unset.
  The clock keeps running, correctly.
- **An AI Autopilot reply does stop it.** Autopilot sends through the
  same path as a human, so it sets `first_response_at` exactly as a human
  reply would.
- **An internal note does not stop it.** Only a real outbound message
  to the customer counts.
- Either target may be null. A policy with only a first-response target
  never evaluates resolution, and vice versa.

---

## 4. The SLA clock is never paused

Stated as its own section because it is the most common assumption about
SLA systems, and it is **not true here**.

There is no pause, no hold, no "waiting on customer" stop-the-clock, and
no resume. Specifically:

- **`pending` does not pause anything.** Both `open` and `pending`
  conversations are swept identically. Marking a conversation "pending"
  because you are waiting on the customer does not stop the resolution
  clock.
- **Business hours are not a pause mechanism** in the ordinary sense —
  they are baked into the deadline calculation up front (§5), and only
  for a business-hours-aware policy.
- **Transfers, releases and queue moves do not pause or restart
  anything.** They reset `queue_entered_at` (the *queue wait* clock, used
  by dashboard metrics), which is a different thing entirely.
- **There is no API, no field and no UI to suspend a conversation's
  SLA.**

The only way a clock stops is by being satisfied: a reply for
first-response, a terminal status for resolution.

### And once a marker is set, it is permanent

`sla_first_response_breached_at`, `sla_resolution_breached_at`,
`sla_first_response_warned_at` and `sla_resolution_warned_at` are written
once and **never cleared by anything**. Neither is `first_response_at`.

The important consequence: **a reopened conversation has no meaningful
SLA.** A conversation that was resolved and then reopened by a new
customer message keeps its `first_response_at` (so the first-response
check skips it forever) and keeps any breach markers (so those breach
types can never fire again). The customer's new question is not covered
by any first-response target at all.

---

## 5. Business-hours deadlines

Only a policy with `business_hours_aware = true` consults the company's
Business Hours and Holidays. Everything else — legacy flat fields, and
policies with the flag off — uses plain wall-clock arithmetic:
`created_at + target minutes`.

For a business-hours-aware policy, the deadline is computed by spending
`target` minutes of *open* time:

- Closed weekdays are skipped entirely.
- Holidays are skipped entirely (fixed dates, and month/day pairs for
  holidays flagged as recurring annually).
- Time outside the day's open/close window is skipped.
- A start time that is **before** a day's opening is clipped forward to
  that opening before any minutes are spent.
- The closing time is **exclusive**: 17:00 is already closed.
- The calculation is done in the company's configured timezone.

### Worked example 1 — inside business hours

```
Company business hours : Mon-Fri 09:00-17:00 UTC, Sat/Sun closed
Policy                 : first response 15 minutes, business_hours_aware,
                         warning threshold 80%
Message arrives        : Friday 09:58
```

09:58 is inside Friday's window, so 15 open minutes are available
immediately:

```
Warning at   09:58 + 12 minutes  = Friday 10:10      (80% of 15, floored)
Deadline at  09:58 + 15 minutes  = Friday 10:13
```

Identical to what a plain wall-clock policy would produce. Business hours
only start to matter when a target crosses a boundary.

### Worked example 2 — the answer that surprises people

Same company, same policy. **The message arrives at 16:58 on Friday** —
two minutes before close.

```
Friday   16:58 → 17:00     2 open minutes spent, 13 remaining
Saturday                   closed, skipped
Sunday                     closed, skipped
Monday   00:00 → 09:00     clipped forward to opening
Monday   09:00 → 09:13     13 remaining minutes spent

Warning at   Monday 09:10
Deadline at  Monday 09:13
```

A 15-minute target has become a deadline **64 hours and 15 minutes** of
wall-clock time later. That is exactly what "15 minutes of business time"
means, and it is correct — but if you expected a weekend alarm, you will
not get one.

Now change **one** thing: the same queue has **no SLA policy assigned**
and just uses `first_response_target_minutes = 15`. The deadline is
**Friday 17:13** — thirteen minutes after everyone went home — and it
will breach overnight with nobody there to act on it, weekend or not.

### Worked example 3 — a start outside hours, and a holiday

```
Message arrives : Saturday 12:00
Policy          : first response 60 minutes, business_hours_aware
```

Saturday and Sunday are closed, so the cursor lands on Monday 00:00 and
is clipped forward to Monday 09:00. Sixty open minutes are then available
that morning:

```
Deadline = Monday 10:00
```

If Monday is registered as a Holiday, Monday is skipped in its entirety
and the deadline becomes **Tuesday 10:00**.

### The setting that does nothing on its own

**Turning on Business Hours in Company Settings changes no SLA behaviour
by itself.** It is consulted only by policies with
`business_hours_aware = true`, and only for queues that have such a
policy assigned and active. A queue running on its legacy flat fields is
completely unaffected — this is covered by an explicit regression test in
the repository (`test_legacy_queue_without_a_policy_is_unaffected_by_business_hours`).

---

## 6. Warning thresholds

A policy's `warning_threshold_percent` (1–100, default 80) produces a
second, earlier deadline:

```
warning_minutes = target_minutes × threshold_percent ÷ 100    (integer division, floored)
```

computed with the same business-hours arithmetic as the real deadline.

| Target | Threshold | Warning fires after |
|---|---|---|
| 15 min | 80% | 12 minutes |
| 60 min | 80% | 48 minutes |
| 45 min | 90% | **40** minutes (40.5 floored) |
| 1 min | 80% | **0** minutes — warns on the very first sweep |
| 480 min | 50% | 240 minutes |

Warnings fire **at most once per conversation per clock**, guarded by
`sla_first_response_warned_at` / `sla_resolution_warned_at`.

**A warning is not guaranteed.** It is only published if a sweep happens
to run while the conversation is past the warning point and still short
of the deadline. If the first sweep to see the conversation finds it
already past the deadline — because the worker was down, because the
target is very short, or because the threshold rounds to zero — it
breaches with no warning ever emitted. Once breached, the warning branch
is not reached at all.

**A queue on legacy flat fields has no warning concept whatsoever.**
Warnings exist only for policy-driven queues.

---

## 7. Breach, and what happens next

When a deadline passes, in one sweep, in this order:

1. The breach timestamp is stamped on the conversation.
2. `conversation.sla_breached` is published, carrying `conversation_id`,
   `queue_id` and `breach_type` (`first_response` or `resolution`).
3. Every escalation rule on the policy whose `trigger` is `breach` runs.

Warnings do the same with `conversation.sla_warning` (which additionally
carries `warning_threshold_percent`) and `trigger: warning` rules.

Both events are published **exactly once per conversation per breach
type**, guarded by the timestamp markers, so re-running the sweep — or
running several workers — never duplicates them.

### Escalation actions

Configured per policy as a list of `{trigger, action, …}` entries.

| Action | What it does | Required parameter |
|---|---|---|
| `notify` | Creates an in-app notification of type `sla_escalation` for each listed user | `user_ids` (explicit user ids only) |
| `reassign_queue` | Moves the conversation to another queue | `target_queue_id` |
| `reassign_agent` | Sets the conversation's assignee | `target_agent_id` |

Behaviours worth knowing:

- **`reassign_queue` does not unassign the current agent.** It moves
  `queue_id` and resets `queue_entered_at`, but leaves
  `assigned_agent_id` exactly as it was. A conversation escalated from
  Tier 1 to Tier 2 is still assigned to the Tier 1 agent who was already
  too slow.
- **`reassign_queue` does not re-run auto-assignment** in the target
  queue, whatever that queue's strategy is.
- **`reassign_agent` does not validate the agent.** It goes through the
  same unvalidated path described in
  [assignment-logic.md](assignment-logic.md) §6.
- **Escalation does not stop the clock.** Moving a breached conversation
  elsewhere does not reset or re-arm anything; the breach marker is
  already permanent.
- **The clock still runs from the original `created_at`** under the new
  queue's policy. If the destination queue has a shorter resolution
  target, the conversation may breach resolution immediately on the next
  sweep.
- **A failing rule is logged and skipped.** A rule pointing at a deleted
  agent or another company's queue fails, is caught, and the sweep
  continues for every other conversation. Nothing surfaces the failure to
  an administrator.
- **No escalation for legacy queues.** Flat-field queues publish
  `conversation.sla_breached` and nothing else happens.
- **There is no "notify this queue's supervisor" primitive.** No
  supervisor or manager field exists on a queue or department, so
  `notify` must list named people, and those lists go stale silently.

### SLA events can also trigger AI

If the company has enabled the Autopilot SLA activation mode, a warning
or breach can cause AI to answer rather than waiting longer for a human.
This is a company-wide opt-in and does **not** require the queue's
`autopilot_enabled` flag. Escalation rules still run — an AI reply and a
`notify` escalation are independent responses to the same event. See
[sla.md](sla.md) § "SLA events also drive AI Autopilot" and
[ai-engine.md](ai-engine.md).

---

## 8. The sweep itself

- Scheduled by Celery beat as `blinkengage.queues.check_sla_breaches`,
  **every 60 seconds**.
- Runs across **every company** in one pass.
- Loads **every** non-deleted `open`/`pending` conversation joined to a
  queue, then evaluates the deadlines in Python. There is no deadline
  filter in the query, no company filter, no target filter and no limit
  — a company with a large open backlog is walked in full, once a minute.
- The company's business-hours schedule and holidays are resolved once
  per company per sweep and cached for that run.
- Safe to run concurrently and safe to re-run; the timestamp markers make
  every action idempotent.
- **The sweep does not check whether the queue is active or deleted.**
  Conversations sitting in a deactivated — or soft-deleted — queue are
  swept, breached and escalated exactly like any other, even though the
  queue no longer appears anywhere in the UI.
- There is no API to trigger the sweep, and no UI showing when it last
  ran. Its only visible outputs are the timestamps on conversations, the
  events, the notifications, and the SLA report.

---

## 9. Previewing a policy

`POST /sla-policies/preview` takes a policy id and a hypothetical start
time and returns four timestamps: first-response warning and deadline,
resolution warning and deadline. It uses the same business-hours
arithmetic as the sweep, so for an **active policy** the preview is what
would really happen.

Two limits:

- **The preview ignores `is_active`.** Previewing a deactivated policy
  shows you its own business-hours math, while a real conversation on a
  queue holding that policy would fall back to the queue's legacy flat
  fields (§2). The preview is truthful about the policy and misleading
  about the queue.
- **You preview a policy, not a queue.** There is no way to ask "what are
  this queue's real deadlines right now", which is the question an
  administrator with a mix of policy-driven and legacy queues actually
  has.

---

## 10. What the SLA engine does not do

- **No pausing, no stop-the-clock, no business-hours "hold"** (§4).
- **No SLA for a conversation without a queue** (§2).
- **No SLA per channel, per customer, per priority or per tag.** SLA is
  a property of a queue and nothing else. `Conversation.priority` is
  explicitly independent — an `urgent` conversation gets the same targets
  as a `low` one.
- **No per-queue business hours.** Business hours are company-wide.
- **No re-arming on reopen** (§4).
- **No first-response clock per customer message.** Only the very first
  reply on the conversation counts, ever; a customer who asks a second
  question and waits three days triggers nothing.
- **No countdown anywhere in the product.** The deadlines are computed
  only inside the sweep and are never stored, never returned by the
  conversation API, and never rendered on the Inbox or the conversation
  view. An agent cannot see how long they have left. The only
  SLA-related fields on a conversation are the four *after-the-fact*
  timestamps.
- **No way to clear `Queue.sla_policy_id`** back to unset — you can only
  reassign it to a different policy.
- **No editing of holidays** — create and delete only.
- **No warning if a queue has no SLA at all**, and no report of which
  queues are unmonitored.
- **No record of why.** `conversation.sla_breached` carries the
  conversation, the queue and the breach type. It does not carry the
  target that was missed, the deadline that was computed, which policy
  applied, whether business hours were used, or whether a warning was
  issued first. Reading a breached conversation's row tells you *that* it
  breached and *when it was noticed* — not what it was measured against.
  **The system today cannot answer "why did this breach".** This is the
  gap the explainability milestone exists to close.

---

## 11. Where to look next

| Question | Document |
|---|---|
| Why is this conversation in this queue (or in none)? | [routing-rules.md](routing-rules.md) |
| What SLA fields does a queue have? | [queue-architecture.md](queue-architecture.md) §2 |
| Which timestamp means what? | [queue-lifecycle.md](queue-lifecycle.md) §3 |
| Why did an escalation reassign it? | §7 above, then [assignment-logic.md](assignment-logic.md) |
| Why did AI answer instead of a person? | [ai-engine.md](ai-engine.md) |
| Historical SLA reporting | [reports-analytics.md](reports-analytics.md) |
| Original design rationale | [sla.md](sla.md) |

---

## 12. Known discrepancies with existing documentation

Recorded, not resolved. The **code** is what happens.

1. **The sweep is not "one indexed query".** `queues-routing.md`
   decision #4 describes it as "a single periodic sweep … querying open/
   pending conversations **whose queue has a target and whose deadline
   has passed** … O(one indexed query) regardless of conversation
   count". The implementation selects **every** non-deleted open/pending
   conversation that has a queue, for **every company**, with no
   deadline predicate, no target predicate and no limit, and evaluates
   each in Python. The idempotency and correctness claims in that
   decision hold; the cost claim does not.

2. **A deactivated policy is not documented as falling back.**
   `sla.md` describes the legacy flat fields as the fallback "for a queue
   with no `sla_policy_id` assigned". `_EffectivePolicy` also falls back
   whenever the assigned policy has `is_active = false`, silently
   restoring the queue's old wall-clock targets (or removing SLA
   entirely). Neither the document nor the UI mentions this.

3. **"What an admin previews is exactly what would happen in
   production" is conditional.** `sla.md` § "Preview" states this without
   qualification. The preview ignores `policy.is_active` and has no
   notion of which queue the policy is attached to, so it diverges from
   reality for a deactivated policy (§9).

4. **Nothing documents that the sweep ignores queue state.** Neither
   document says that conversations in an inactive or soft-deleted queue
   are still monitored, breached and escalated.

5. **Nothing documents the permanence of the markers on reopen.** Both
   documents describe the `*_breached_at`/`*_warned_at` columns as
   idempotency markers, which they are, without stating the operational
   consequence: a reopened conversation is effectively outside SLA
   forever (§4).

6. **`reassign_queue`'s effect on assignment is undocumented.**
   `sla.md` § "Escalation" says the two reassign actions "call
   `ConversationService.update()`". Because that method treats `None` as
   "leave unchanged", `reassign_queue` moves the conversation while
   leaving the existing agent assigned to it.

---

# The four clocks (M4)

Each clock exists to answer a question a customer would recognise. That is not
decoration — it decides when each starts, stops and pauses, and naming them
after the question is what stops a later change quietly making one measure
something else.

| Clock | The question it answers |
|---|---|
| Queue | How long did the customer wait before someone accepted responsibility? |
| First response | How long until the customer received the first meaningful response? |
| Next response | How long is the customer waiting for the next response? |
| Resolution | How long until the issue is solved? |

The four are **independent**. A service may measure some and not others.
`None` means *not measured*; `0` means *already late the moment it starts*.
Folding them together would invent a deadline nobody set.

The question travels with every recorded row — a timer labelled
`first_response` explains nothing to somebody asking why a conversation is red.

## Pausing is the point

**A clock never simply pauses.** Every pause carries a structured reason:
waiting for customer, outside business hours, manual, supervisor override,
dependency waiting, system maintenance. "The timer is paused" tells a
supervisor nothing; "paused, outside business hours" tells them there is
nothing to do.

Closed vocabulary, so *"how much of our SLA time is lost waiting on
customers?"* is answerable rather than a string-matching exercise. `pause_note`
is free text **beside** the reason, never instead of it — a dependency pause
can name what it is waiting on; it cannot invent a seventh reason.

A clock holds **elapsed time**, not a start moment. That is what lets a paused
clock stop counting while wall-clock does not, and it means the deadline is
derived — so a deadline legitimately moves while paused. Not a bug, and exactly
what the Inspector exists to explain.

`due_at` is cleared on pause rather than left for the sweep to filter, so a
paused clock cannot be breached by a query that forgot.

## The service owns the targets

Copied onto the clock when it starts, from the service version the conversation
is bound to — not read through it on every check. A conversation's targets are
frozen at its start, so an administrator halving a target at noon does not move
the deadline of everything already running.

## SLA Health

**The primary SLA visualisation.** Four timers side by side is a report; one
health indicator is a decision. The timers stay available underneath.

| Health | Means |
|---|---|
| 🟢 `healthy` | Nothing to do — including paused and unmeasured |
| 🟡 `attention` | Past 60% of the target; worth a look |
| 🟠 `at_risk` | Past 80%; needs doing now |
| 🔴 `breached` | Already missed. Nothing gets better by waiting |

A paused conversation is **healthy**, not neglected. An agent has to be able
to skip it without wondering whether they should.

The **worst** clock decides the conversation, never an average. One whose first
response is twenty minutes overdue is not "mostly fine" because its resolution
target is generous.

A clock reads `breached` the moment its target passes, not when the breach
sweep next runs. The sweep *records* a breach — the settlement, the decision
row, the timeline entry — but it does not decide one. A reading that waited
for it would tell an agent a conversation was merely at risk for up to a
minute after it had already missed.

### Sorting the Inbox by it

`GET /conversations` returns `sla_health` on every row and **orders by it
first**, ahead of priority. The two answer different questions and both
belong: health is *is this running out of time*, priority is *does this matter
more*. A breached NORMAL conversation outranks a healthy URGENT one — the
urgent one still has time to be handled and the other does not.

The ranking is computed **in SQL**, in
`infrastructure/repositories/sla_health_rank.py`, not in Python over the page.
Sorting a page would sort the fifty rows some other ordering already chose,
putting the worst of an arbitrary fifty on top and leaving a breached
conversation on page four.

That means the rule exists twice — `Clock.health` for one conversation, the
SQL rank for sorting thousands — so they are held together deliberately:

- both read `ATTENTION_FRACTION` / `AT_RISK_FRACTION` / `SEVERITY` from
  `domain/sla.py`, so moving a threshold moves both;
- `tests/integration/test_inbox_sla_order.py` runs every band through both
  paths on the same rows and asserts they agree, including on the exact band
  edges;
- the SQL side carries a one-millisecond edge tolerance, because SQLite
  computes durations through `julianday` and returns 2400.0000001 seconds
  where PostgreSQL returns 2400. It absorbs representation error and nothing
  larger — a tolerance big enough to hide a real difference would defeat the
  test above.

The rank subquery is scoped by `company_id`, which is required rather than
optional: without it, one company opening its Inbox aggregates every other
tenant's clocks.

Conversations with **no clocks** — a service that measures nothing, anything
predating the SLA engine — are left-joined, not inner-joined, and read
`healthy`. An inner join would have removed them from the Inbox while leaving
the list looking correct.

## Who the SLA is waiting on

Every clock names its **responsible party** — and it is not always the
conversation's owner:

| Situation | Responsible |
|---|---|
| Waiting in a queue | The queue |
| An agent has it | That agent |
| AI has it | AI |
| **Paused for the customer** | **The customer** |
| Escalated | The supervisor |

The customer never *owns* a conversation, and is nevertheless the honest answer
to "who is this waiting for" while the ball is with them. Reporting the agent
there would blame somebody for a delay that is not theirs — the most common way
an SLA report loses an agent's trust.

## Where the clocks are driven from

`SlaEngine` is the mechanism — start, pause, resume, settle. `SlaLifecycle` is
the policy: when each of those is right. Keeping them apart lets the mechanism
be tested exhaustively without a conversation, and the policy be read in one
page rather than reconstructed from two modules.

| Event | What happens |
|---|---|
| Conversation queued | Queue, first-response and resolution clocks start |
| An owner accepts (agent or AI) | Queue clock **achieved** — on acceptance, not on reply |
| A reply goes out | First response achieved if it is the first; next response always |
| The customer replies | Next-response clock starts; paused clocks resume |
| Status → waiting for customer | Response and resolution clocks pause |
| Status → waiting internally | Response clocks pause; resolution keeps running — still our delay |
| Status → resolved | Resolution achieved |
| Status → closed | Everything still running is **stopped**, not achieved |

The next-response clock deliberately does **not** start when a conversation is
queued: nobody is waiting for a *next* reply before the first one has happened,
and starting it there would show every new conversation as overdue on a promise
nobody had made.

Targets come from the **service**. A company with no service directory measures
nothing and behaves exactly as it did before the clocks existed.

A zero target reports as breached rather than dividing by zero — it is a
configuration an administrator is allowed to save, so it must not be a crash.

## Terminal states

`achieved` and `breached` are terminal. A breach is a fact about what happened;
a clock that could un-breach would let a late reply erase the lateness.

`stopped` is deliberately **not** `achieved` — the conversation ended before the
clock could be met or missed, and counting an abandoned conversation as a
success is how a dashboard lies.

## Two representations, on purpose

`conversation_sla_clocks` is **mutable** and answers *where does this stand* in
one indexed read. The append-only decision log answers *how did it get here*.
Neither derives cheaply from the other, so both exist.

The timeline lives in the **existing** decision log, beside the routing, service
and policy decisions — which reserved `SLA_PAUSED`/`SLA_RESUMED` back in M1. An
SLA transition *is* a decision the platform made about a conversation, and a
conversation is explained by reading one history in order rather than
interleaving three by timestamp and hoping the clocks agree.

## Breaching

A clock does not breach itself. It starts, pauses and settles from the events
of the conversation — and running out of time is the one thing that is **not**
an event: nothing happens, which is exactly the problem.

`breach-overdue-sla-clocks` runs every minute and marks what has run out.
Without it the engine measures and records but never *concludes*: a
conversation twenty minutes past its first-response target would still read
`running`, and "how many did we miss" would be zero forever.

One indexed range scan finds the work. Because `due_at` is cleared on pause, a
paused clock is not merely filtered out of the query — it is not in the index
at all, so a conversation waiting on the customer cannot be breached for the
customer's silence.

The sweep touches **only the clock**. Not the status, not the owner, not the
queue. A breach is an SLA fact, and a sweep that also reassigned or reopened
would be three independent concepts moving at once, at 3am, with nobody
watching.

Batched at 500 per run: a company that has just switched on a tight target
across a large backlog would otherwise breach thousands in one transaction, and
the next sweep is a minute away.

## The Inspector

`GET /api/v1/conversations/{id}/sla` answers all six questions: why each clock
is running, why it is paused, why it was breached, why it was resumed, why the
deadline changed (compare two timeline rows — every one carries the deadline as
it then stood), and what needs doing now.

Every clock carries a one-sentence `explanation`, built from the structured
fields so two conversations paused for the same reason read alike and group
together.
