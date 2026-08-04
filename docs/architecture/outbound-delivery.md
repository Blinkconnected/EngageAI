# Outbound Delivery

*Whether the customer actually received what we sent.*

**Status: proposed. No code written.**

---

## 1. Why this is its own domain

Today the platform records three things about an outbound message: `PENDING`,
`SENT`, `FAILED`. `SENT` means **the provider's API accepted the request** — it
does not mean the message reached a phone, and nothing anywhere claims
otherwise. But every consumer reads it as if it did.

That is the assumption Conversation Activity would inherit if it settled the
customer's wait on an outbound row existing. A message WhatsApp accepted and
then failed to deliver would mark the customer as answered, stop the SLA clock,
and make AI ineligible — for a reply nobody received.

**No provider parses delivery receipts at all.** The webhook path handles
inbound messages only; Meta's `statuses` array — which carries `sent`,
`delivered`, `read` and `failed` for every outbound message — is received and
discarded. So delivery is not a field to expose. It is a domain that does not
exist yet.

---

## 2. The states

```
        ┌──────────┐
        │  QUEUED  │  we intend to send it; nothing has left yet
        └────┬─────┘
             ↓
        ┌──────────┐
        │ ACCEPTED │  the provider took it. NOT delivery.
        └────┬─────┘
        ┌────┴─────────────┬──────────────┐
        ↓                  ↓              ↓
  ┌───────────┐      ┌──────────┐   ┌──────────┐
  │ DELIVERED │      │  FAILED  │   │ UNKNOWN  │  no receipt within the
  └─────┬─────┘      └──────────┘   └──────────┘  confirmation window
        ↓
   ┌────────┐
   │  READ  │  the customer opened it
   └────────┘
```

`QUEUED` and `ACCEPTED` are **in flight**. `DELIVERED`, `READ` and `FAILED` are
terminal. `UNKNOWN` is terminal-by-timeout and deliberately distinct from both
success and failure — it means *we do not know*, which is a different fact from
*it failed*, and a platform that conflated them would either alarm falsely or
hide real losses.

---

## 3. Channels cannot all confirm the same thing

This is the constraint that shapes everything, and taking *"answered only after
successful delivery"* literally without it would break the platform: for a
channel that can never report delivery, the customer's wait would never settle,
and AI would answer the same person again and again forever.

Each channel declares the **strongest confirmation it can produce**:

| Channel | Strongest confirmation | Why |
|---|---|---|
| **Web chat** | `DELIVERED` | We own the socket. Publishing to a connected session *is* delivery. |
| **WhatsApp** | `READ` | Meta sends `sent` / `delivered` / `read` / `failed` per message. |
| **Messenger / Instagram** | `DELIVERED` | Same webhook family. |
| **SMS** | `DELIVERED` | Gateway delivery receipts. |
| **Telegram** | `ACCEPTED` | The Bot API confirms the send; there is no outbound delivery receipt. |
| **Email** | `ACCEPTED` | SMTP acceptance is all there is. Bounces are asynchronous and negative-only — absence of a bounce is not delivery. |

**A reply is "answered" when it reaches that channel's strongest available
confirmation.** On WhatsApp, `ACCEPTED` does not settle the customer's wait —
`DELIVERED` does. On email, `ACCEPTED` settles it, because nothing better will
ever arrive.

This keeps your rule intact — *never assume an outbound message arrived* —
while staying honest about channels that physically cannot tell us.

**A channel must not claim a capability it has not implemented.** Declaring
`DELIVERED` before the status webhook is built would hold every conversation's
wait open until the timeout. Capability is a property of the *implementation*,
not of the protocol's potential, and Phase 1 declares `ACCEPTED` for every
channel except web chat.

---

## 4. What each consumer does with it

| Consumer | Reads | Behaviour |
|---|---|---|
| **Conversation Activity** | terminal delivery state | Settles the wait on success. **Reopens** it on `FAILED`. Leaves it open on `UNKNOWN`. |
| **SLA** | same | A clock is answered by a delivered reply, not an attempted one. A failed send resumes the clock. |
| **AI Queue Worker** | in-flight *and* terminal | Not eligible while a reply is in flight; eligible again if it fails. |
| **Conversation Story** | every transition | "Delivered 21:19:22", "Failed — number not on WhatsApp". |
| **Inbox** | terminal failures | A conversation whose last reply failed is work, not history. |
| **Analytics / Intelligence** | rates | Delivery and read rates per channel — impossible today. |

### The safety property that makes this workable

> **A conversation with an outbound reply in flight is not AI-eligible, even
> though the customer's wait has not settled.**

Without it, the model has a catastrophic mode: WhatsApp accepts a reply,
delivery confirmation takes four seconds, the sweep runs every ten — and
because the wait has not settled, AI writes again. And again.

So eligibility needs both facts, and they are genuinely different:

- *Has the customer been answered?* → terminal delivery state. Drives SLA and
  the wait.
- *Is an answer already on its way?* → in-flight state. Drives AI eligibility.

Conflating them produces either a silent customer or a spamming one.

---

## 5. Where it lives

| Concern | Owner |
|---|---|
| Delivery state and its transitions | `domain/delivery.py` — framework-free |
| Per-channel capability | `domain/delivery.py`, beside the states |
| Recording a transition | `DeliveryService` — the one writer |
| Receiving receipts | Each provider's webhook parser |
| Storage | `message_delivery_events`, append-only; `messages.delivery_state` as the projection |

**Append-only, with a projected current state** — the same shape as ownership
and for the same reason: "delivered at 21:19:22 then failed at 21:19:40" is a
history somebody will need to read, and a single mutable column collapses it to
whatever happened last.

**Transitions are monotonic.** `DELIVERED` never returns to `ACCEPTED`; a late
duplicate receipt is ignored rather than moving the state backwards. Providers
retry webhooks and deliver them out of order, so this is ordinary, not
exceptional.

---

## 6. Invariants

1. **`ACCEPTED` is not delivery.** No consumer may treat provider acceptance as
   receipt except where §3 declares it the channel's strongest confirmation.
2. **One writer.** Only `DeliveryService` writes delivery state. *AST guard.*
3. **Transitions are monotonic**; out-of-order receipts cannot regress a state.
4. **`UNKNOWN` is neither success nor failure** and is never rendered as either.
5. **A channel's declared capability matches its implementation.** *Test: for
   every channel declaring better than `ACCEPTED`, a receipt parser exists.*
6. **In flight blocks AI; terminal state settles the wait.** Never merged.

---

## 7. Implementation plan

**Phase 1 — the domain, honest about today.** States, transitions, capability
map. Every channel declares `ACCEPTED` except web chat, which declares
`DELIVERED`. Conversation Activity settles on the declared strongest
confirmation, so behaviour is **identical to settling on `SENT`** — because
`ACCEPTED` is what `SENT` already means. Nothing changes; the seam exists.

**Phase 2 — the record.** `message_delivery_events` and the projection.
Transitions written from the existing send path: `QUEUED → ACCEPTED`, or
`QUEUED → FAILED` on a rejected send. This is where failed sends start
reopening the wait — the first real behaviour change, and the one that fixes a
customer being silently dropped.

**Phase 3 — real receipts, one channel at a time.** WhatsApp first: parse the
`statuses` array already arriving and discarded, raise the capability to
`DELIVERED`, then `READ`. Each channel is independent and independently
reversible by lowering its declared capability.

**Phase 4 — consumers.** SLA, Inbox, Story, Analytics read delivery state
instead of assuming it.

**The confirmation window** arrives with Phase 3: a channel promising
`DELIVERED` that produces no receipt within it moves to `UNKNOWN`. Per-channel,
because an SMS receipt takes seconds and an email bounce can take hours.

---

## 8. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | A channel declares a capability it cannot deliver → waits never settle, AI loops | **critical** | Invariant 5 with a test; Phase 1 declares only what is built. |
| R2 | AI replies repeatedly while a send is in flight | **critical** | The in-flight block in §4. Tested before Phase 2 ships. |
| R3 | Reopening on failure produces a second reply the customer eventually sees twice | medium | Reopen only on *permanent* failure. A retryable error stays in flight. |
| R4 | Out-of-order or duplicate receipts corrupt state | medium | Monotonic transitions; append-only history. |
| R5 | Receipt volume — one webhook per message per state | medium | Append-only insert, no read-modify-write; the projection is a single indexed UPDATE. |
| R6 | `UNKNOWN` accumulates silently | low | It is a reportable state; a rising `UNKNOWN` rate is a channel health signal. |

---

## 9. Consequences for Conversation Activity

`customer-activity.md` §3 said the wait settles on an outbound reply of type
≠ `SYSTEM`. It becomes:

> The wait settles when an outbound reply reaches its channel's **strongest
> available delivery confirmation**. A permanently failed reply **reopens** the
> wait. A reply in flight leaves the wait open and blocks AI.

`last_agent_message_id` and `last_ai_message_id` still record the newest
outbound message regardless of delivery — they answer *what did we send*, which
is a different question from *did it arrive*.
