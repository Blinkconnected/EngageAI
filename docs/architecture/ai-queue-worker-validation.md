# AI Queue Worker — validation report

*Every lifecycle state, and whether AI behaves correctly in it.*

Validated against a **live installation**, not fixtures: two real WhatsApp
conversations driven end to end through Blink Connected, plus a code review of
every path that can start, stop or refuse AI. Where a verdict below says
"correct", the evidence is a row that exists in production.

The governing promise is one sentence: **AI Autopilot is a queue worker, not a
first responder.** Most of it holds. Four things do not, and the first means
that sentence is currently false for every company on this installation.

---

## What was exercised

```
WhatsApp inbound → routing → queue → SLA clocks → AI engages → AI replies
  → customer replies → AI hands back → agent picks up → transfer → resolve
  → close → Conversation Story → decision log → usage metering
```

Conversation `e8aa3a07…`, Blink Connected, WhatsApp, 21:19–21:24 UTC. The
transfer leg ran on a second conversation (`a86ad882…`) because the first was
already closed by then.

**What each subsystem recorded for the same conversation** — the point of the
exercise is that these agree, not that each works alone:

| Subsystem | Record |
|---|---|
| Routing | `QUEUE_SELECTED` / `RULE_MATCHED` → "General" |
| SLA | `FIRST_RESPONSE` 3 min and `RESOLUTION` 15 min, both `target_source=QUEUE`, both later `ACHIEVED` |
| Ownership | `NOBODY → QUEUE → AI_QUEUE_WORKER → QUEUE → HUMAN_AGENT` |
| AI | `AI_ENGAGED` / `AUTOPILOT_QUEUE`; reply `is_ai_generated=true`, confidence `0.7`, status `SENT` |
| Conversation | `IN_PROGRESS → RESOLVED → CLOSED`, `closed_at` set |
| Story | 14 entries, in causal order, every actor named |
| Metering | one `BILLABLE_MESSAGE` at `1.000000` per message, no price anywhere near it |

The transfer leg recorded `AI_QUEUE_WORKER → QUEUE` with reason
`MANUAL_TRANSFER`, a `conversation_transfers` row carrying the note, and
`department_id` set — see **L9** in the freeze report for the one thing that
does not read well there.

---

## State by state

| # | Lifecycle state | Expected | Observed | Verdict |
|---|---|---|---|---|
| 1 | Arrives, no rule matches | AI never offered it | `LEFT_UNROUTED`, no queue, AI never invoked | ✅ |
| 2 | Arrives on an Autopilot queue | Stamp `ai_pickup_eligible_at`, leave it queued | **Engaged immediately** | ❌ **G1** |
| 3 | Pickup delay running | `AI_DEFERRED` / `PICKUP_DELAY_RUNNING` recorded | Correct only where a service exists | ⚠️ **G1** |
| 4 | Delay elapses, still unclaimed | AI takes it, policy re-evaluated | Correct (`test_ai_lifecycle`) | ✅ |
| 5 | Delay elapses, human got there first | AI stands down, marker cleared once | `AI_STOOD_DOWN` recorded | ✅ |
| 6 | Delay elapses, conversation finished | AI does nothing | `finished` outcome | ✅ |
| 7 | Delay elapses, policy now refuses | AI never takes it, refusal recorded | `RecordingPolicyEngine` writes it | ✅ |
| 8 | AI engages | Ownership → AI, queue clock settled | `AI_QUEUE_WORKER` / `AI_ENGAGEMENT` | ✅ |
| 9 | AI replies | First-response clock settled, reply marked AI | `FIRST_RESPONSE ACHIEVED`; `is_ai_generated=true`, confidence `0.7` | ✅ |
| 10 | AI cannot answer | Conversation stays queued, nothing stripped | `not_answered`, marker cleared | ✅ |
| 11 | Customer replies | AI decides again | AI handed back to the queue | ✅ behaviour — ⚠️ **G2** on the record |
| 12 | AI hands back | Ownership → queue, `autopilot_active=false` | `AI_QUEUE_WORKER → QUEUE`, reason `AI_RELEASED` | ✅ |
| 13 | Human picks up | AI stops permanently | `autopilot_active=false`; ownership → agent | ✅ |
| 14 | Customer replies after a human owns it | AI must not speak | flag false ⇒ consumer skips | ✅ |
| 15 | Transfer | AI released unconditionally | false on all three target types | ✅ |
| 16 | Resolve / close | AI does not re-engage | status in `FINISHED`; sweep returns `finished` | ✅ |
| 17 | New message on an old conversation | Not re-routed, AI not re-offered | Confirmed live on a 29 July conversation | ✅ |
| 18 | Company AI kill switch off | AI silent everywhere | `company_disabled` refusal recorded | ✅ |
| 19 | Queue Autopilot off | AI silent on that queue | Outer gate, inline | ✅ |
| 20 | Confidence below threshold | AI does not send | Service threshold, company fallback | ✅ |
| 21 | Agent goes quiet, AI may resume | Honour `ai.resume_delay_seconds` | **Not implemented at all** | ❌ **G3** |

---

## The gaps

### G1 — "Queue worker, not first responder" is false without a service directory

**Severity: high. Affects every company on this installation.**

```python
delay = service.ai.pickup_delay_seconds if service is not None else 0
```

A company with no service directory gets `delay = 0`, so `engaged` stays true
and **AI answers on arrival**. The entire queue-worker design — the delay, the
sweep, the stand-down, the re-evaluated policy — is reachable only by companies
that have adopted services.

The `services` table holds **no rows at all**, for any company. The live
decision log shows `AI_ENGAGED / AUTOPILOT_QUEUE` with no `AI_DEFERRED` before
it: AI as a first responder, which is what M5 set out to stop.

This is not a defect in the sweep, which is correct and tested. It is a
**default**: zero is the wrong fallback for *"this company has not configured a
service"*, because it silently opts them out of the milestone.

**The domain already has the right answer.** `AiPolicy.pickup_delay_seconds`
defaults to `30`, and so does the `ai_pickup_delay_seconds` column. Only the
ingest fallback disagrees, substituting `0` where no service exists. So the fix
is to fall back to the domain default rather than to zero — one line, and the
number it would use is one somebody already chose.

*Not fixed here* even so. It changes AI behaviour for every company on the
installation at once — conversations that are answered instantly today would
begin waiting thirty seconds — and that is a product decision, not a bug fix.

### G2 — AI's hand-off never says why

**Severity: medium.**

`RoutingDecisionKind.AI_RELEASED` exists in the domain, is mapped to the AI
stream, has Inspector wording (`"AI released"`) and its own rendering branch —
and **nothing writes it**. `AutopilotService._hand_off` takes a `reason`,
publishes it on an event, writes the ownership row, and records no decision.

The Conversation Story therefore says *"AI handed it back"* and cannot say
*why* — against M6's own contract that every event answers what happened, why,
and what happened next. The reason exists; it is not written where the Story
reads.

Confirmed live: `e8aa3a07…` has an `AI_RELEASED` **ownership** row and no
`AI_RELEASED` **decision** row.

### G3 — The resume delay is configuration nothing obeys

**Severity: low, already known.** `ai.resume_delay_seconds` is accepted by the
API, stored on the service version, and read by no code path.
`OperationalState.AI_RESUME_DELAY` exists and nothing assigns it. Held by
`test_nothing_reads_the_ai_resume_delay`, which fails the moment somebody
implements it — deliberately, so the test is replaced rather than quietly kept.

### G4 — Policy decisions are not recorded for service-less companies

**Severity: medium.** `AI_ENGAGEMENT` is only evaluated when a service exists;
otherwise ingest falls back to five inline conditions. The fallback is
functionally correct but writes **no `POLICY_EVALUATED` row**. So for every
company here, *"why did AI answer this one and not that one"* has no recorded
answer — the explainability exists only on the path nobody is on yet. Same
shape as G1, and it closes the same way.

---

## What is genuinely solid

- **AI never speaks after a human takes control.** Three independent paths set
  `autopilot_active = False` — pick, transfer, manual assignment — and the
  consumer's first check is that flag. Verified live and held by
  `test_autopilot_activation_modes`.
- **AI is an owner, not an absence.** Every engagement and hand-off writes an
  ownership transition, so "AI has it" is findable and the moment it stops is a
  row somebody can point at.
- **A conversation is settled exactly once.** `ai_pickup_eligible_at` is
  cleared on every outcome, so no marker is swept forever.
- **AI takes a conversation only once it has an answer.** If the model is
  unavailable or unsure, the conversation stays where a human can reach it.
- **Metering is channel-agnostic.** WhatsApp and web chat both produced
  `BILLABLE_MESSAGE` at `1.000000`, and metering never saw a price.

---

## Recommendation

**The AI Queue Worker is correct where it runs.** Every gate, every refusal and
every transition behaves as designed, and the defects from earlier this cycle —
mute AI, unrecorded hand-backs, unsettled SLA clocks — are closed and tested.

**G1 is the one that matters before V1.0**, because it makes the milestone's
headline promise untrue for 100% of current tenants. It is a one-line default
with a product decision behind it: either a platform default pickup delay
applies when no service defines one, or the Services screen becomes part of
onboarding so every company has one. Both are small changes once the decision
is made.

G2 and G4 are explainability gaps, not behavioural ones — nothing behaves
wrongly, the platform simply cannot say why afterwards. G3 is documented,
tested, and deliberately unbuilt.
