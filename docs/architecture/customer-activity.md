# Customer Activity

*The single source of truth for what has actually been said, and who is waiting.*

**Status: proposed. No code written.**

---

## 1. Why this exists

Six subsystems need the same handful of facts about a conversation's message
history, and today **not one of them can ask for it** — so each infers it from
something else:

| Subsystem | What it needs | What it uses today |
|---|---|---|
| AI Queue Worker | is a customer waiting, since when | *nothing* — engagement decided once at creation |
| SLA | when the customer last wrote | `customer_replied` called from the message path |
| Inbox | who is waiting on whom | `status` + `assigned_agent_id`, both set by hand |
| Conversation Story | last meaningful event | scans messages and decisions per conversation |
| Routing | — | — |
| Automation, Analytics, Company Intelligence | all of it | not built |

`operational_state()` reports `READY_FOR_REPLY` when *an agent holds it* — not
when the customer is waiting. `last_message_at` moves for outbound messages
too. So the platform genuinely does not know whether a customer is waiting for
a reply, and every module that needs to know guesses differently.

**Customer Activity is that fact set, owned in one place, projected once,
consumed everywhere.**

---

## 2. The facts

| Fact | Type | Meaning |
|---|---|---|
| `awaiting_reply_since` | timestamp, nullable | The **oldest** currently-unanswered inbound message. `NULL` when nothing is unanswered. *How long has this customer been waiting.* |
| `last_customer_message_at` | timestamp, nullable | The **newest** inbound message. *When did they last speak.* |
| `last_customer_message_id` | uuid, nullable | Which message that was. |
| `last_agent_message_id` | uuid, nullable | The newest outbound message written by a **human**. |
| `last_ai_message_id` | uuid, nullable | The newest outbound message written by **AI**. |
| `unanswered_message_count` | int, not null, default 0 | Inbound messages since the last outbound reply. |
| `last_wait_duration_seconds` | int, nullable | How long the customer waited for the **most recent answered** message. Settled when a reply goes out. |

### `customer_wait_duration` is derived, not stored

You listed it as a projected fact. It must not be one: it changes every second,
so any stored value is wrong the moment after it is written, and a column that
is always stale is worse than no column — somebody will read it and believe it.

```
customer_wait_duration = now - awaiting_reply_since     (NULL when not waiting)
```

Computed on read, from a fact that only changes when a message arrives.

What *is* worth storing is the **settled** figure — how long they waited for the
answer they actually got — because that is historical, immutable once written,
and the number every report and analytics module will want. That is
`last_wait_duration_seconds` above. The two are different questions and the
distinction is the same one as `awaiting_reply_since` versus
`last_customer_message_at`: one is live, one is history.

---

## 3. Maintenance rules

| Event | Effect |
|---|---|
| **Inbound customer message** | `last_customer_message_at`/`_id` = this message. `awaiting_reply_since` = this message's time **only if currently NULL**. `unanswered_message_count += 1`. |
| **Outbound reply, human** | `last_agent_message_id` = this message. `last_wait_duration_seconds` = `now - awaiting_reply_since`. `awaiting_reply_since` = NULL. `unanswered_message_count` = 0. |
| **Outbound reply, AI** | as above, but `last_ai_message_id`. |
| **Outbound `SYSTEM` message** | **no effect** — a delivery receipt or a CSAT prompt is not an answer. |
| **Resolve / close** | `awaiting_reply_since` = NULL, `unanswered_message_count` = 0. The other facts are history and stay. |
| **Internal note** | **no effect** — separate table, cannot interfere. |
| **Reopen** | nothing special; the next inbound message sets the facts normally. |

**Human versus AI** is read from the message's own `is_ai_generated` metadata —
the flag `ConversationService.send_reply` already writes, and the same one the
transcript uses to say who spoke.

---

## 4. Ownership and enforcement

**Exactly one writer.** A `CustomerActivityProjector`, called from the message
persistence path and from nowhere else. Every other module **reads**.

This is deliberately the same shape as ownership:

| | Ownership | Customer Activity |
|---|---|---|
| Source of truth | `conversation_ownership`, append-only | the `messages` table |
| Projection | `conversations.assigned_agent_id` | the columns in §2 |
| Writer | `OwnershipService.transfer` only | `CustomerActivityProjector` only |
| Guard | AST allow-list test | AST allow-list test |
| Repairable | yes, from the timeline | yes, from `messages` |

**Storage as columns on `conversations`, not a side table.** The Inbox reads
these on every row of every page, and the AI sweep filters on them across the
whole installation. A join for facts needed on every read is a join that will
be denormalised back within a milestone. The *concept* is first-class — one
domain module, one projector, one guard — while the *storage* stays where it is
queried.

**Every fact is derivable from `messages`.** That is what makes this safe: the
backfill is a recomputation, drift is detectable by recomputing, and repair is
the same operation as the backfill. A projection you cannot rebuild is a second
source of truth wearing a cache's clothes.

---

## 5. Invariants

1. **One writer.** Only `CustomerActivityProjector` writes these columns.
   *AST guard, shaped like `test_ownership_is_the_only_writer.py`.*
2. **Derivable.** For every conversation, the stored facts equal a fresh
   recomputation from `messages`. *Drift checker; runs on backfill and on a
   schedule.*
3. **`awaiting_reply_since` is the oldest, `last_customer_message_at` is the
   newest.** Never collapsed, never swapped.
4. **A SYSTEM message never answers a customer.**
5. **Live durations are computed, never stored.**
6. **No module recomputes message history.** Consumers read Customer Activity.
   *Guard: the set of modules querying `messages` for direction/ordering is an
   allow-list.*

---

## 6. What each consumer stops doing

| Consumer | Stops | Starts |
|---|---|---|
| AI Queue Worker | deciding engagement at creation | reading `awaiting_reply_since` / `last_customer_message_at` |
| SLA | inferring the customer replied from the write path | reacting to the same fact |
| Inbox | inferring "waiting" from status + assignment | showing a real wait, ordered by it |
| Conversation Story | re-deriving the last meaningful event | reading the ids directly |
| Automation | — | triggering on "unanswered for N minutes" without a query |
| Company Intelligence | — | reading response behaviour without touching `messages` |

The Inbox gain is the visible one: **"waiting 4 minutes" becomes a fact rather
than an inference**, and the `WAITING_FOR_CUSTOMER` / `READY_FOR_REPLY`
distinction stops depending on an agent having set a status by hand.

---

## 7. Migration

**Phase A — the columns.** Added nullable, defaulted, read by nothing.

**Phase B — the projector.** Wired into the message path. New messages maintain
the facts; existing rows are still empty.

**Phase C — the backfill.** One pass over `messages`, grouped by conversation,
computing every fact. Chunked and resumable. Then the drift checker asserts
equality across the whole installation.

**Phase D — consumers.** One at a time, each replacing an inference with a read.
AI Queue Worker first, since it is the one with a live defect.

Phases A–C change no behaviour whatsoever. That is the point: the facts become
true and provable before anything depends on them.

---

## 8. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Projection drifts from `messages` | high | One writer; every fact derivable; drift checker; repair = backfill. |
| R2 | Backfill is slow or locks on a large `messages` table | medium | Chunked, resumable, no exclusive locks; runs while columns are read by nothing. |
| R3 | A future message path forgets to call the projector | medium | AST guard; the projector is the only writer and the drift checker catches it. |
| R4 | Failed sends counted as answers | medium | Only `SENT` messages settle the wait — a `FAILED` outbound reached nobody. |
| R5 | Columns multiply as modules ask for more | low | `messages` remains the source; anything derivable stays derived until a query proves it needs materialising. |

---

## 9. Open question

**Does a failed outbound send answer the customer?** I propose **no** — a
message the provider rejected never reached them, so the customer is still
waiting and AI should still be eligible. That means the projector settles the
wait on `SENT`, not on row creation, and a send that later fails must reopen
the wait. Worth confirming, because it is the difference between a customer
being silently dropped and being answered twice.
