# Policy Engine

Every business rule in Blink Engage lives here, and only here.

A rule like *"AI may not answer a customer who asked for no automated
messages"* is true everywhere or it is not true at all. Left to each module to
implement, it gets written in the AI service, forgotten in the automation
service, and written slightly differently in the third place somebody needed
it — and the platform then behaves differently depending on which door a
conversation came through. Preventing that is the entire purpose of this
module.

**Modules do not evaluate business rules. They ask.**

```python
decision = engine.evaluate(Policy.AI_ENGAGEMENT, execution)
if decision.allowed:
    ...
```

Source: [`domain/policies.py`](../../backend/src/blinkengage/domain/policies.py).

---

## The shape of a decision

An evaluation never answers with a boolean. It answers with a
`PolicyDecision`:

| Field | Meaning |
| --- | --- |
| `policy` | Which question was asked |
| `effect` | `allow` or `deny` |
| `reason` | Why, from a closed set |
| `source` | **Where the answer came from** |
| `detail` | Anything a reader needs beyond the reason code |

The `source` field is the one an administrator actually needs. "Denied" sends
them hunting. "Denied, from the Customer Context" tells them which screen to
open.

```
Policy    AI_ENGAGEMENT
Decision  Denied
Reason    The customer asked for no automated messages
Source    Customer Context
```

Reasons are a closed enum, not free text, so the Routing Inspector can group
and filter them — and every reason has stored wording, enforced by a test,
because a reason with no sentence renders as a raw enum name, which is the
console equivalent of a raw translation key.

Decisions are frozen. They get written to the decision log, and a caller able
to edit one would be a caller able to rewrite history.

---

## Policies are pure

A policy is handed an [`ExecutionContext`](./execution-context.md) — which
already carries the resolved service, customer and conversation facts — and
returns a decision. No repository, no clock, no I/O.

This is why the context architecture had to exist first. A policy that could
look things up would be a policy whose answer depended on *when* you asked
it, and the platform would stop being deterministic in exactly the way this
design exists to prevent.

---

## The policies

| Policy | Question | Enforced today |
| --- | --- | --- |
| `AI_ENGAGEMENT` | May AI answer this conversation? | Yes |
| `ROUTING` | May this conversation be routed? | Yes |
| `VIP_QUEUE_ENTRY` | May it enter the VIP lane? | Yes |
| `QUEUE_BYPASS` | May it skip the queue entirely? | Yes |
| `AGENT_PICKUP` | May an agent take it? | Yes |
| `OWNERSHIP_CONTINUATION` | May a previous agent keep it? | Partly |
| `SLA_PAUSE` | May the SLA clock stop? | Not yet |
| `AUTOMATION_EXECUTION` | May an automation run? | Not yet |
| `AUTO_CLOSE` | May it be closed without a human? | Not yet |

### Rules whose modules have not shipped

Three policies belong to milestones that have not landed. Rather than omit
them — which would leave each future module free to invent its own answer —
they exist and answer `NOT_YET_ENFORCED` from `PLATFORM_DEFAULT`.

A reader of the Routing Inspector sees *"allowed because this policy is not
yet enforced"*, which is the truth, instead of a fabricated rationale that
reads like a real decision.

`OWNERSHIP_CONTINUATION` shows the middle case: the 24-hour window belongs to
the ownership milestone, but that a *finished* conversation has no owner to
continue is knowable today, so that much is enforced now.

---

## Denial order: narrowest first

When more than one rule would deny, the reported reason is the one that stays
true after the broader ones are fixed.

For `AI_ENGAGEMENT` the order is:

1. The customer asked for no automated messages
2. The company's AI switch is off
3. No AI provider is configured
4. The service has AI switched off
5. An agent already owns the conversation
6. The conversation is finished

A customer's refusal survives an administrator re-enabling AI company-wide,
so it is reported first. An administrator told *"the company has AI off"* who
turns it on and finds AI still silent for this customer has been sent the
wrong way.

For the same reason, *"switched on but never set up"* is a different answer
from *"switched off"*: different problem, different screen, and collapsing
them sends somebody to toggle a switch that is already on.

---

## `AI_ENGAGEMENT` fails closed

Every other policy defaults to allowing. This one does not.

`ai_enabled` is a **compliance kill switch** — a company turns it off to
guarantee no AI-generated content reaches its customers. It is not a routing
preference; it is a promise the company has made, and neither a service
configured for AI nor a customer happy to receive it may override it.

So `CompanyCapabilities` defaults every field to the *unavailable* answer, and
an execution carrying no capabilities at all is refused with
`CAPABILITIES_UNKNOWN` rather than treated as permission. A caller that
forgets to populate the field gets a refusal, not an unintended AI reply.

Refusing costs a reply. The other direction costs the promise — and nothing
would fail, no test would go red, and customers would receive AI replies from
a company that had switched AI off.

`CAPABILITIES_UNKNOWN` appearing in the decision log means **a caller needs
fixing**, not that a customer was legitimately refused.

Only AI fails closed. Failing every policy closed would mean the engine could
not be adopted one module at a time.

---

## Facts versus decisions

`ExecutionContext.is_priority` says what is *true of the customer*. It does
not say what the platform may *do* about it — and the two policies built on
that one fact deliberately disagree:

- `VIP_QUEUE_ENTRY` — **allowed**. A VIP goes to the front of a lane.
- `QUEUE_BYPASS` — **denied**, unless a service explicitly opts in.
  Bypassing means never queuing at all, which contradicts the Queue First
  Principle. Folding these into one rule is how a platform quietly acquires
  conversations that exist nowhere.

`ExecutionContext` carries facts. The Policy Engine makes decisions. Anything
answering *"may we…"* on the context itself is a rule in the wrong place —
which is why `ai_may_engage` was removed from it when this engine landed, and
why a test asserts it cannot come back.

---

## Replacing a rule

`PolicyEngine(rules={...})` overrides individual rules without editing the
engine. This is the seam that keeps the module from becoming something people
work around: an installation with genuinely different policy overrides a
rule; it does not fork the engine or reimplement the check locally.

---

## The Inspector

`evaluate_all(execution)` answers every policy in one call. It is how somebody
answers *"why can't AI reply to this?"* without reproducing the conditions
that made it stop — four rules, one screen, no reproduction.

`decision_for_log()` renders a decision in the shape the routing decision log
stores, so the log's format and the policy vocabulary cannot drift apart.

---

## Outstanding migrations

The Policy Engine is the destination; not everything has moved in yet.

- **`conversation_ingest_consumer.py`** carries a five-condition AI Autopilot
  gate (queue opt-in, company AI switch, Autopilot opt-in, activation mode,
  provider configured). It is correct today. When it migrates, the activation
  modes and the queue opt-in need homes in `CompanyCapabilities` or the
  Service Context first — migrating before then would drop them.
- **`api/deps.py`** gates the agent-facing AI endpoints on the same company
  switch.

Until a caller migrates, it keeps its own check. Two implementations of one
rule is the problem this module exists to end, so each migration deletes the
local copy rather than leaving both.

---

## See also

- [Execution Context](./execution-context.md)
- [Queue architecture](./queue-architecture.md)
- [Routing rules](./routing-rules.md)
- [AI engine](./ai-engine.md)
