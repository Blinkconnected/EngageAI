# AI eligibility — customer activity, not conversation age

*Redesigning when AI Autopilot may take a conversation.*

**Status: proposed. No code written. No production data touched.**

---

## 1. The defect this replaces

AI engagement is decided **once, at conversation creation**, inside
`_route_and_assign` — a routing concern that ingest calls only
`if is_new_conversation`. Every message after the first goes straight to
storage. The Autopilot consumer that handles follow-ups acts only when
`autopilot_active` is already `true`.

So a conversation that exists and is not already on Autopilot can never become
eligible, however many times the customer writes.

Observed on Blink Connected: a customer wrote on 2 Aug 14:30, 3 Aug 09:17 and
3 Aug 21:24, on a conversation created 29 July. None were answered, none were
offered to AI, and nothing recorded that anything was wrong — the conversation
has zero SLA clocks and zero routing decisions.

**AI engagement is in the wrong place.** It belongs to the Queue Worker, which
already runs every ten seconds, already re-evaluates policy, already records
every outcome — and today is fed by a single stamp written at birth.

---

## 2. The fact the platform does not have

Nothing in the system answers **"is a customer waiting for a reply, and since
when?"**

`operational_state()` infers it from `status` and `assigned_agent_id`, both set
by hand. `READY_FOR_REPLY` means *an agent holds it*, not *the customer is
waiting*. `last_message_at` moves for outbound messages too. The SLA engine's
`NEXT_RESPONSE` clock is the closest thing, and it only exists when the resolved
targets define `next_response_minutes` — which the queue tier never supplies.

So the model needs one new fact, and everything else follows from it.

---

## 3. Two timestamps, not one

This is the crux, and getting it wrong produces either a rude AI or a silent
one.

| Fact | Meaning | Used for |
|---|---|---|
| **`awaiting_reply_since`** | The **oldest** currently-unanswered inbound customer message. `NULL` when nothing is unanswered. | *How long has this customer been waiting.* Urgency, ordering, SLA, escalation. |
| **`last_customer_message_at`** | The **newest** inbound customer message. | *When did they last speak.* The anchor the pickup delay runs from. |

They differ exactly when it matters. A customer sending three messages in a row
at 10:00, 10:05 and 10:06 has been waiting since **10:00** — that is what the
SLA and the Inbox must show — but AI must not start composing at 10:00:30 while
they are still typing. The delay runs from **10:06**.

Anchoring the delay to the oldest message makes AI interrupt a burst.
Anchoring urgency to the newest one resets the customer's wait every time they
chase, which is the opposite of what a chasing customer deserves.

**A conversation's own age is not an input anywhere.** A conversation opened a
year ago whose customer wrote thirty seconds ago is as eligible as one opened
this morning. That is the whole point of the redesign.

---

## 4. The eligibility predicate

AI may take a conversation when **all** of the following hold.

| # | Signal | Condition | Source |
|---|---|---|---|
| 1 | Unanswered customer message exists | `awaiting_reply_since IS NOT NULL` | new projection (§5) |
| 2 | Conversation is live | `status NOT IN (RESOLVED, CLOSED)` | `Conversation.status` |
| 3 | Ownership permits it | current owner is `QUEUE` or `NOBODY` | `conversation_ownership` — the single source of truth |
| 4 | AI policy allows it | `Policy.AI_ENGAGEMENT` evaluates *allowed* | Policy Engine, recorded |
| 5 | Pickup delay elapsed | `now >= last_customer_message_at + effective_delay` | resolver (§6) |
| 6 | Within the activity window | `now - last_customer_message_at <= window` | **per Service**, business-hours dependent — section 12 |
| 7 | Not already handled | `autopilot_last_handled_message_id != <newest inbound id>` | existing column |
| 8 | Queue opted in | `queue.autopilot_enabled` | runtime queue |

Signals 3 and 4 are re-evaluated **at sweep time**, never carried forward — the
guarantee the current sweep already makes and the reason a compliance officer
switching AI off takes effect within ten seconds.

### Ownership is the gate, not `autopilot_active`

Today the check is `autopilot_active`, a flag. Under this model it is
**ownership**: AI may take a conversation the *queue* owns, and may not touch
one a *human* owns. That is what the ownership work this milestone made
possible, and it is strictly stronger — the flag could disagree with the
timeline, the timeline cannot disagree with itself.

`autopilot_active` remains as the AI-is-currently-answering marker, projected
from ownership rather than independently managed.

---

## 5. The new fact, as a projection

`awaiting_reply_since` and `last_customer_message_at` are **projections
maintained at message-write time**, exactly as `assigned_agent_id` is a
projection of ownership:

| Event | `awaiting_reply_since` | `last_customer_message_at` |
|---|---|---|
| Inbound customer message | set to `now` **only if currently NULL** | set to `now` |
| Outbound reply (human or AI), type ≠ `SYSTEM` | cleared to `NULL` | unchanged |
| Outbound `SYSTEM` message | unchanged — a delivery receipt is not an answer | unchanged |
| Resolve / close | cleared to `NULL` | unchanged |
| Internal note | unchanged — separate table, cannot interfere | unchanged |

**One writer.** Both columns move only through the message-persistence path,
guarded by an AST test in the shape of the ownership guard.

**Why projections rather than a query.** The sweep runs every ten seconds
across every company. Deriving "is there an unanswered inbound message" by
querying `messages` each time is a per-conversation subquery over the largest
table in the system. A partial index on `awaiting_reply_since IS NOT NULL`
makes the candidate set proportional to *conversations currently awaiting a
reply* — real workload — rather than to table size. Same shape and cost as the
existing `ix_conversations_ai_pickup`.

**Backfill is derivable.** Both columns can be reconstructed for existing rows
from `messages` in one pass, so the migration needs no guesswork.

---

## 6. The effective pickup delay

The delay is **resolved, never stamped** — `ai_pickup_eligible_at` is removed.

A stamped deadline is a decision frozen at write time: change a service's delay
and existing conversations keep the old one until their next message. Resolving
at sweep time means configuration takes effect immediately, and there is no
column that can go stale.

```
base delay      = Service → Queue → Platform default   (per §1 of the migration proposal)
```

Two modifiers — see section 12 for the approved form of each.

**Outside business hours the delay collapses to zero.** *(approved)* The delay
exists to give a human first refusal. At 03:00 there is no human to defer to,
and thirty seconds of deliberate silence serves nobody. This *inverts* the
naive reading of "business hours" as a gate that stops AI — outside hours is
when AI is most valuable. It never overrides the Service AI policy.

**An at-risk SLA clock collapses the delay to zero.** *(opt-in only, default
off)* Rejected as an automatic behaviour, on the principle that **SLA measures
the business and must not change business behaviour**. Available only where a
Service explicitly enables "Allow AI to accelerate near SLA breach". The
existing `activate_on_sla` mode folds into this flag rather than remaining a
parallel activation path.

Both are recorded as decisions, so "why did AI answer instantly here and wait
thirty seconds there" has an answer.

---

## 7. The sweep

```sql
SELECT ... FROM conversations
WHERE awaiting_reply_since IS NOT NULL          -- partial index
  AND deleted_at IS NULL
  AND status NOT IN ('RESOLVED','CLOSED')
  AND last_customer_message_at <= :now - :min_possible_delay
ORDER BY awaiting_reply_since                    -- longest-waiting customer first
LIMIT :batch
```

A **coarse** SQL filter, then the precise per-conversation evaluation in Python
using that conversation's own resolved delay, policy, ownership and SLA state.

Deliberately not a single exact SQL predicate: the delay varies per service, so
an exact query needs either a materialised deadline (which goes stale — §6) or
a join to service versions inside the hot path. The candidate set after the
partial index is bounded by *customers currently waiting*, so precise filtering
in Python is cheap and always correct.

`ORDER BY awaiting_reply_since` means the longest-waiting customer is decided
first — the same ordering the Inbox uses, so the sweep and the screen agree
about who is most overdue.

---

## 8. What this removes

| Removed | Replaced by |
|---|---|
| `conversations.ai_pickup_eligible_at` + its index | resolved at sweep time |
| AI engagement inside `_route_and_assign` | the Queue Worker sweep |
| `AutopilotTrigger.NEW_MESSAGE` vs `QUEUE_PICKUP` as separate paths | one path; the trigger stays as provenance |
| `activate_on_sla` as a parallel activation mode | an SLA modifier inside one predicate |
| `autopilot_active` as the AI gate | ownership; the flag becomes a projection |

Ingest stops deciding anything about AI. It routes, starts clocks, records
ownership — and sets the projection. **That is the architectural win**: AI
engagement leaves the creation path entirely and lives in exactly one place.

---

## 9. Implementation plan

### Phase 1 — the fact *(no behaviour change)*

Add `awaiting_reply_since` and `last_customer_message_at`, maintained on the
message-write path, with a backfill migration reconstructing both from
`messages`. Nothing reads them yet.

Ship, verify the projections track reality on live data for a day, and confirm
the backfill matches a recomputation.

*Exit:* for every conversation, the columns agree with a fresh derivation from
`messages`. **AI behaviour identical.**

### Phase 2 — the eligibility domain *(pure, no wiring)* ✅ **shipped**

`domain/ai_eligibility.py`: a framework-free function taking the eight facts and
returning *eligible* / *not eligible with a reason*. Unit-tested exhaustively —
every signal, every boundary, the burst case, the year-old-conversation case.
The reason vocabulary is closed, so every refusal is recordable.

*Exit:* the rule exists and is tested. **Nothing calls it.**

### Phase 3 — the sweep reads it *(behaviour changes, guarded)*

The sweep selects on the new projection and evaluates the domain function.
Ingest stops stamping `ai_pickup_eligible_at`.

Behind a **per-company opt-in** so it can be enabled for one tenant — Blink
Connected — verified against real traffic, and widened deliberately.

*Exit:* new conversations behave exactly as today; follow-up messages on
unowned conversations now reach AI.

### Phase 4 — removal

Remove AI engagement from `_route_and_assign`, drop `ai_pickup_eligible_at`,
fold `activate_on_sla` into the predicate, make `autopilot_active` a projection.
Ships alone, after Phase 3 has run clean for a full period.

### Ordering against the other work

Phase 3 depends on the **Service → Queue → Platform** resolver from Stage 1 of
the migration proposal, because "effective delay" must be readable from one
place. Doing this first would mean writing a tenth ad-hoc fallback. G1 (the
delay falling back to `0`) is fixed by that resolver, not separately.

---

## 10. Verification

- **Projection equivalence.** A checker recomputes both columns from `messages`
  and asserts equality. Runs on the backfill and as a scheduled drift check
  through Phase 3.
- **Replay.** For a sample of historical conversations, evaluate the predicate
  as of each inbound message and assert AI would have engaged exactly where a
  human eventually replied — and never where a human already held it.
- **The Nour Eddin case as a named test.** A conversation created a year ago,
  unowned, in a queue, with a customer message thirty seconds old, becomes
  eligible. This is the regression that must never come back.
- **The burst case.** Three messages in ninety seconds produce one AI reply,
  after the delay from the *last* one.
- **The staleness case.** A sweep restarted after two days' downtime answers
  nothing outside the activity window.
- **Live smoke test** on Blink Connected during Phase 3, in the shape of the
  one run this milestone.

---

## 11. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Enabling this answers a backlog of stale messages | **high** | Signal 6, the activity window. Verified by the staleness test before Phase 3. |
| R2 | AI interrupts a customer mid-burst | high | Delay anchored to `last_customer_message_at`, not `awaiting_reply_since`. |
| R3 | Projection drifts from `messages` | high | One writer, AST-guarded; drift checker; both columns derivable so drift is always repairable. |
| R4 | AI answers the same message twice | medium | `autopilot_last_handled_message_id`, already present, becomes part of the predicate. |
| R5 | AI takes a conversation a human is working | medium | Ownership is the gate, and ownership is now a single source of truth. |
| R6 | Sweep cost grows with the table | medium | Partial index; candidate set is *customers currently waiting*, not conversations. |
| R7 | Business-hours inversion surprises an operator | low | Recorded as a decision; visible in the Story. Product decision, flagged as such. |
| R8 | Phase 4 drops a column something still reads | low | Grep-and-guard; one release of overlap. |

---

## 12. Decisions (approved)

### Activity window — per Service, not a platform constant

| Context | Default |
|---|---|
| Inside business hours | **1 hour** |
| Outside business hours | **12 hours** |
| Platform fallback | **1 hour** |

Configurable per Service, resolved through the same Service -> Queue ->
Platform chain as everything else. The rationale: *a conversation should become
eligible again when a customer actively returns, and AI should never revive a
stale one indefinitely.*

**Which window applies is decided at evaluation time, not at arrival time.** A
message arriving at 23:00 (outside hours, 12h window) and still unanswered at
09:00 is evaluated against the *business-hours* window then -- one hour -- and
is therefore out of window. This is not obvious and matters: freezing the
window when the message lands would let an overnight message stay answerable
deep into a working morning during which humans were available and chose not to
answer it. The window is a property of *now*, like every other signal here.

### Business hours — approved inversion

- **Inside business hours:** the pickup delay applies. Humans get first refusal.
- **Outside business hours:** the delay is **zero**. There is no human to defer
  to, so deliberate silence serves nobody.

Business hours never *block* AI, and never override the Service AI policy — a
service with AI switched off stays off at 03:00.

### SLA acceleration — off by default, and the principle behind it

> **SLA measures the business. It must not change business behaviour.**

This is the correcting principle, and it is broader than AI: a measurement that
alters what it measures stops being a measurement. Recorded as an invariant
because it constrains every future module — an SLA clock may raise an alarm,
order a queue or colour a row, and may never make the platform act differently.

AI therefore keeps the configured pickup delay under SLA pressure. Only where a
Service explicitly enables **"Allow AI to accelerate near SLA breach"** may the
delay be shortened. **Default: disabled.**

*(This reverses the proposal in section 6, which had SLA state collapsing the
delay automatically. That was wrong, for the reason above.)*

### WAITING_CUSTOMER — returns to the queue on a new customer message

A customer who writes is no longer being waited on. An inbound message on a
`WAITING_CUSTOMER` conversation transitions it back to `WAITING`, and the Queue
Worker evaluates it like any other waiting conversation. The transition is
already legal (`WAITING_CUSTOMER -> WAITING` is in `_ALLOWED`) and is recorded,
so the Conversation Story still shows that an agent parked it and what brought
it back.

**Status returns to the queue. Ownership does not.** These are separate facts
and the distinction decides who answers:

- If an **agent owns** it, they keep it. Sticky ownership is what makes a
  returning customer reach the person who already knows them. The Queue Worker
  evaluates the conversation, finds a human owner, and declines — correctly.
- If the **queue owns** it, AI becomes eligible normally.

Reading "transition back into the queue" as also releasing ownership would take
the conversation off the desk of the agent who parked it, which is the opposite
of what parking it meant.

---

## 13. Consequences for section 6

Effective delay becomes:

```
base delay                        = Service -> Queue -> Platform default
outside business hours            -> 0
SLA at risk AND service opts in   -> 0
otherwise                         -> base delay
```

And the activity window joins it as a resolved value rather than a constant:

```
window = Service -> Platform, selected by the business-hours state at
         evaluation time
```

Both are recorded as decisions, so "why did AI answer instantly here and wait
thirty seconds there" has an answer on the conversation's own timeline.

---

## 14. Remaining open question

**Does a failed outbound send answer the customer?** See
`customer-activity.md` section 9 — I propose no, which means eligibility must
survive a send the provider rejected.
