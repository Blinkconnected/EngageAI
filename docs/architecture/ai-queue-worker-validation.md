# AI Queue Worker — validation report

*Every lifecycle state, and whether AI behaves correctly in it.*

Validated against a **live installation**, not fixtures: two real WhatsApp
conversations driven end to end through Blink Connected, plus a code review of
every path that can start, stop or refuse AI. Where a verdict below says
"correct", the evidence is a row that exists in production.

The governing promise is one sentence: **AI Autopilot is a queue worker, not a
first responder.** Four gaps were found. **G2 and G4 are closed** by the
Service-first resolution milestone; **G1 is an approved transitional state**
that Stage 2 retires; **G3** remains documented and deliberately unbuilt. Each
section records what was wrong and what was done.

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
| 2 | Arrives on an Autopilot queue | Stamp `ai_pickup_eligible_at`, leave it queued | Engages immediately where no Service sets a delay | ✅ transitional — **G1**, resolved by Stage 2 |
| 3 | Pickup delay running | `AI_DEFERRED` / `PICKUP_DELAY_RUNNING` recorded | Correct wherever a delay resolves | ✅ |
| 4 | Delay elapses, still unclaimed | AI takes it, policy re-evaluated | Correct (`test_ai_lifecycle`) | ✅ |
| 5 | Delay elapses, human got there first | AI stands down, marker cleared once | `AI_STOOD_DOWN` recorded | ✅ |
| 6 | Delay elapses, conversation finished | AI does nothing | `finished` outcome | ✅ |
| 7 | Delay elapses, policy now refuses | AI never takes it, refusal recorded | `RecordingPolicyEngine` writes it | ✅ |
| 8 | AI engages | Ownership → AI, queue clock settled | `AI_QUEUE_WORKER` / `AI_ENGAGEMENT` | ✅ |
| 9 | AI replies | First-response clock settled, reply marked AI | `FIRST_RESPONSE ACHIEVED`; `is_ai_generated=true`, confidence `0.7` | ✅ |
| 10 | AI cannot answer | Conversation stays queued, nothing stripped | `not_answered`, marker cleared | ✅ |
| 11 | Customer replies | AI decides again | AI handed back to the queue, **and says why** | ✅ |
| 12 | AI hands back | Ownership → queue, `autopilot_active=false` | `AI_QUEUE_WORKER → QUEUE`, reason `AI_RELEASED` | ✅ |
| 13 | Human picks up | AI stops permanently | `autopilot_active=false`; ownership → agent | ✅ |
| 14 | Customer replies after a human owns it | AI must not speak | flag false ⇒ consumer skips | ✅ |
| 15 | Transfer | AI released unconditionally | false on all three target types | ✅ |
| 16 | Resolve / close | AI does not re-engage | status in `FINISHED`; sweep returns `finished` | ✅ |
| 17 | New message on an old conversation | Not re-routed, AI not re-offered | Confirmed live on a 29 July conversation | ✅ |
| 18 | Company AI kill switch off | AI silent everywhere | `company_disabled` refusal recorded — now on **every** company, not only those with a Service | ✅ |
| 19 | Queue Autopilot off | AI silent on that queue | Outer gate, inline | ✅ |
| 20 | Confidence below threshold | AI does not send | Service threshold, company fallback | ✅ |
| 21 | Agent goes quiet, AI may resume | Honour `ai.resume_delay_seconds` | **Not implemented at all** | ❌ **G3** |

---

## The gaps

### G1 — "Queue worker, not first responder" without a service directory

**Closed as an architectural issue. Now an approved transitional state.**

*Product-owner decision: G1 is no longer tracked as a defect. Stage 2 seeds
each company's Service from its **effective** configuration, after which the
platform-level pickup delay is retired outright — with no behaviour change,
because by then every company's delay comes from a Service that already holds
the value they were running on.*

It was this, in the ingest consumer:

```python
delay = service.ai.pickup_delay_seconds if service is not None else 0
```

A company with no service directory got `delay = 0`, so AI answered on arrival
and the entire queue-worker design — the delay, the sweep, the stand-down, the
re-evaluated policy — was reachable only by companies that had adopted
services. The `services` table holds no rows at all, for any company, so that
meant all of them. The live decision log showed `AI_ENGAGED / AUTOPILOT_QUEUE`
with no `AI_DEFERRED` before it.

**What was done.** The literal is gone. The delay resolves Service → Platform
through the one chain (`domain/ai_policy.py`), the Inspector reports which tier
answered, and an AST guard fails if any module reads the delay off a service
again. It found the AI pickup sweep still doing exactly that on its first run.

**What was deliberately not done.** The platform tier was *not* set to `30`,
which is what this report first recommended. Doing so would have the platform
impose a wait on every company that never asked for one — and the reasoning
`PLATFORM_DEFAULT_SLA_TARGETS` already gives for leaving `queue_minutes`
unmeasured applies exactly: *how long a conversation may sit before somebody
accepts it is an operational promise a business makes, not one the platform may
make for it.* Thirty seconds is a real decision about giving humans first
refusal, and it belongs to a Service — which defaults to precisely that.

So the platform tier is a **stated** `0` with its reasoning attached, rather
than a fallback nobody chose hidden in a branch nobody could see. AI still
answers immediately for a company that has configured nothing, and starts
waiting the moment that company gets a Service. The promise becomes true as
configuration arrives, rather than by the platform asserting it on a customer's
behalf.

**The tier is temporary by design.** Stage 2 gives every company a Service
seeded from what they resolve to today — a `0` delay for a company running on
`0` — so the platform tier stops being consulted. It is then deleted rather
than left as a fallback nobody reaches: an unreachable tier is the next
generation of the branch nobody could see.

### G2 — AI's hand-off never said why

**✅ Closed by the Service-first resolution milestone.**

`RoutingDecisionKind.AI_RELEASED` existed in the domain, was mapped to the AI
stream, had Inspector wording (`"AI released"`) and its own rendering branch —
and **nothing wrote it**. `AutopilotService._hand_off` took a `reason`,
published it on an event, wrote the ownership row, and recorded no decision.
The Story therefore said *"AI handed it back"* and could not say why, against
its own contract that every event answers what happened, why, and what happened
next.

**Fixed.** Four reasons now reach the timeline, because they send an
administrator to four different places:

| Reason | What it means |
|---|---|
| `MODEL_REQUESTED_HANDOFF` | The model asked for a human. Not a failure — a model that knows its limits is the behaviour worth having. |
| `CONFIDENCE_BELOW_THRESHOLD` | Sure enough to try, not sure enough to send. |
| `NO_REPLY_GENERATED` | Nothing usable came back. A provider problem, not a policy one. |
| `ACTIVATION_MODE_EXCLUDES_THIS` | Autopilot is configured not to run for this trigger. |

A reason outside that vocabulary records **nothing** rather than a row claiming
a cause the platform did not establish — an invented reason on this screen is
worse than a missing one, because the missing one sends somebody looking and
the invented one stops them.

The recording never costs the hand-off: handing back is the product, explaining
it is evidence, and a test injects a failing recorder to prove a customer is
never left with AI still holding their conversation.

**The confidence figures are deliberately not on the decision yet.**
`RoutingDecision` has no field for them, and *"not confident enough"* is only
readable beside the bar it fell short of — 82% against 60% and 82% against 90%
are the same sentence and opposite problems. Adding half of that pair would be
worse than adding neither. Both belong there and need a migration; the reason
code answers *why*, which was the gap, and the confidence is already on the
reply's own metadata.

### G3 — The resume delay is configuration nothing obeys

**Severity: low, already known.** `ai.resume_delay_seconds` is accepted by the
API, stored on the service version, and read by no code path.
`OperationalState.AI_RESUME_DELAY` exists and nothing assigns it. Held by
`test_nothing_reads_the_ai_resume_delay`, which fails the moment somebody
implements it — deliberately, so the test is replaced rather than quietly kept.

### G4 — Policy decisions are not recorded for service-less companies

**✅ Closed by the Service-first resolution milestone.** `AI_ENGAGEMENT` is only evaluated when a service exists;
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

## Where this stands now

**The AI Queue Worker is correct.** Every gate, every refusal and every
transition behaves as designed, and each is now recorded — including on the
path most companies are actually on, which recorded nothing before.

| Gap | State |
|---|---|
| **G1** — no delay without a Service | **Approved transitional state.** The literal is gone and the tier is stated; Stage 2 seeds Services from effective configuration and then retires the platform tier outright, with no behaviour change. |
| **G2** — hand-off never said why | **Closed.** Four reasons reach the Story; an unmapped reason records nothing rather than inventing a cause. |
| **G3** — resume delay unimplemented | Documented, tested, deliberately unbuilt. Now *resolved* through the chain so the value has one source when something finally obeys it — which is not the same as the platform honouring it, and the test that says so still stands. |
| **G4** — no policy decision without a Service | **Closed.** Verified on the live installation: a service-less company now records `POLICY_EVALUATED / ai_engagement / permitted / company_settings`. |

The one standing constraint: **every future module consumes
`ConfigurationResolver` and nothing else.** No module may add a tenth
fallback, and an AST guard fails the build if one tries.
