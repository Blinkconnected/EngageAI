# Memory Platform

What the platform has observed, kept so it can be explained, aged, and
erased.

Stage 2 of the Company Intelligence Engine, and a **platform bounded
context** rather than a feature of the AI Engine. Knowledge answers *"what
is true?"*; Memory answers *"what happened?"*. The AI Engine will be one
consumer among several — the Workflow Engine, CRM, Reporting, the Customer
Timeline and Analytics are the others — and none of them writes here
except through the Memory Manager.

Status: **built.** Domain boundaries are in
[Knowledge, Memory and Intelligence](./knowledge-memory-intelligence.md);
this document is the implementation.

---

## What stage 2 deliberately does not do

**Nothing here decides what is worth remembering.** That is a judgement,
and judgement belongs to the callers. The platform offers one way to
record an observation with its evidence, one way to read what is
remembered, and one way to erase it.

So there is no extraction, no clustering, no distillation from
conversations — those need a model deciding what matters, which is an
Intelligence concern and a later stage. What exists today are the callers
that need no model: an agent writing a note, a CRM sync, a workflow
action, an import.

This ordering is deliberate. Building the store first means the learning
pipeline arrives into a context where evidence is mandatory, confidence is
computed, erasure works and the write path is already one door — rather
than into an empty schema where each of those becomes something to
remember to do.

---

## The four tiers

| Tier | Scope | Subject | Store | Erasable |
|---|---|---|---|---|
| **Organizational** | The business | Company | `memory_facts` | Aggregate only |
| **Customer** | One customer | Customer | `memory_facts` | **Yes, on request** |
| **Experience** | What has worked | Company or Agent | `memory_facts` | Aggregate only |
| **Conversation** | One live thread | — | Redis, TTL | With the conversation |

### One table for three tiers

Organizational, Customer and Experience share the entire contract —
subject, evidence, confidence, lifecycle, steward, human state — and
differ only in their fact-type vocabulary and in what their subject is.
Three tables would mean three repositories, three copies of the decay and
lifecycle code, and three migrations every time the contract grows.

The decisive argument is erasure. A customer request must delete that
customer's facts **and** weaken the aggregate facts their conversations
supported, in one transaction. Against one table that is one delete and
one recompute; across three it is a dance where a missed table is a
compliance failure that looks like nothing.

Tier-specific shape lives in `attributes` (portable `JSON`, per this
codebase's SQLite rule) carrying its own `attributes_schema_version`,
which is what makes the payload evolvable without a migration per fact
type.

### Conversation Memory is not a fourth row type

It has no confidence, no evidence, no lifecycle, no steward and no human
state. Every field of the fact contract is meaningless for state that dies
when the conversation closes, so modelling it as a fact would mean either
eight permanently-null columns or loosening the contract for the tiers
that need it — and the contract is the reason the platform is trustworthy.

It lives in Redis with a TTL: the "fine to drop if nobody is listening"
tier `event-bus.md` already distinguishes from durable events. The TTL is
the design, not a detail — working memory that outlived its conversation
would be a growing store of customer content with no retention story, and
a TTL means the default outcome is deletion while remembering requires a
deliberate act.

---

## The fact contract

Every durable fact carries all of this. It is enforced by
`domain/memory.validate_fact_shape`, called by the Manager before anything
reaches the session.

| Field | Why it exists |
|---|---|
| `subject_type` / `subject_id` | What the fact is *about*. **The erasure key** |
| `evidence` | Why it is believed. At least one, always |
| `created_from` | Agent, customer-stated, inference, system of record, import |
| `confidence` | Computed from evidence, never claimed |
| `confidence_state` | observed → candidate → confirmed → trusted |
| `confidence_direction` | rising / stable / falling / contested |
| `lifecycle_state` | active → dormant → archived → purged |
| `steward_user_id` / `steward_role` | Where a contradiction gets routed |
| `human_state` | unreviewed / confirmed / suppressed / corrected |
| `last_observed_at` | New evidence arrived |
| `last_confirmed_at` | **Corroborated** — a stricter thing |
| `attributes_schema_version` | The payload evolves without a migration |

### Evidence is mandatory, and it is a pointer

A fact with no evidence cannot be explained, re-derived, or correctly
weakened when an erasure removes what supported it. It is not a memory, it
is an assertion, and this platform does not store assertions.

Evidence is a **pointer, never a copy**. No excerpt, no transcript. A
conversation excerpt here would put customer content into a second store
with different retention and a different permission — precisely the leak
the audit consumer's `_REDACTED_PAYLOAD_FIELDS` already exists to close —
and it would turn erasure from a row deletion into a text-editing problem.

`customer_id` and `agent_id` are denormalised onto the evidence row rather
than resolved through the conversation later, for two load-bearing
reasons: the distinct-customer and distinct-agent counters are what stop
one person's habit becoming company policy, and **erasure joins on
`customer_id`** — resolving it lazily would make erasure depend on a row a
conversation purge may already have removed.

### `last_observed_at` is not `last_confirmed_at`

Two fields, because if repetition counted as confirmation a customer
repeating a wrong belief would confirm it. Observation is new evidence;
confirmation is corroboration by a human or a measured outcome.

This is also the structural defence against belief-by-repetition. A fact
supported only by customer-authored content cannot pass `CANDIDATE`
whatever the arithmetic says — `has_corroboration` gates the ceiling. The
prompt-injection path where somebody repeats "the refund policy is 100%
cash" forty times is defeated by a counter, not by detection.

---

## Confidence

Computed, never claimed. The platform's existing habit is to ask the model
— `suggest_autopilot_reply` parses a `CONFIDENCE:` line, and
`ai-engine.md` concedes it is "still ultimately the model's own opinion".
That is defensible for one reply a threshold gates. It is not defensible
for a fact that will be quoted to thousands of customers, because a
model's self-assessment is uncorrelated with whether a claim is true *of
this company* — the one thing the model cannot know.

```
raw  = bias
     + w₁·log₁₊(support)
     + w₂·log₁₊(distinct_customers)
     + w₃·log₁₊(distinct_agents)
     + w₄·outcome_quality
     − w₅·log₁₊(contradictions)

conf = sigmoid(raw) · 0.5^(age / half_life(fact_type))
```

**Breadth is weighted separately from volume.** Forty repetitions by one
agent to one customer is one person's habit observed forty times; six
agents converging independently is a practice. A formula that cannot tell
them apart will confidently promote the first into company policy.

**Logarithmic in the counts**, because the tenth observation genuinely
tells you less than the second, and linear growth would let a high-volume
topic reach certainty on nothing but traffic.

**Per-type half-lives.** Terminology decays over four years; a promise
over thirty days; seasonal patterns over slightly more than a year,
because a pattern *about* a yearly cycle must not expire before its season
comes round again. A single global half-life would either expire stable
facts or preserve stale ones, and both failures are silent.

**`outcome_quality` is neutral when absent, not bad.** Most conversations
have no CSAT, and treating unmeasured as poor would mean only the surveyed
minority could ever be believed.

### Direction is decay-adjusted

`confidence_direction` is computed from the evidence stream in
`memory_confidence_samples`, **never** by differencing the confidence
column. Confidence already includes recency decay, so a naive difference
reports FALLING for every fact that is merely quiet — which is most facts,
most of the time — and the column would become a slower, noisier
restatement of `DORMANT`.

`CONTESTED` — supporting *and* contradicting evidence both growing — is a
distinct and more actionable finding than either direction alone. Two
departments quoting different lead times produce exactly this, and it is
usually the first time anyone notices.

---

## Two axes, not one chain

The obvious lifecycle is a single progression: observed → candidate →
confirmed → trusted → stale → archived → forgotten. It reads well and it
breaks on a case that happens constantly.

A fact reaches `TRUSTED` over six months — 200 conversations, 14 agents.
The topic goes quiet for a quarter and decays to stale. Then it is
observed again. On one chain, where does it go? Back to candidate discards
200 conversations of evidence, so the fact is *less* believed on strictly
*more* evidence. Jumping straight to trusted makes "stale" a label that
meant nothing. There is no right answer because the question is malformed.

```
confidence_state   OBSERVED → CANDIDATE → CONFIRMED → TRUSTED
                       ▲          ▲           ▲          │
                       └──────────┴───────────┴──────────┘
                              demotion, with hysteresis

lifecycle_state    ACTIVE → DORMANT → ARCHIVED → PURGED
                      ▲        │
                      └────────┘
                      re-observation revives

orthogonal         contradiction_count · human_state
```

The broken case resolves cleanly: `DORMANT` → `ACTIVE`, confidence
untouched, because the evidence never went anywhere.

**Hysteresis** on the confidence thresholds — promotion at 0.80, demotion
at 0.72 — so a fact hovering on a boundary does not flap on every
recompute. Each flap is a state change something downstream reacts to.

**The product vocabulary survives.** `display_label()` derives the
one-dimensional word a human reads (`stale`, `archived`, `suppressed`,
`contradicted`, `forgotten`) from the two axes, so the schema can express
what a chain cannot while nobody has to read two columns to understand one
row.

---

## Forgetting is not erasure

The most important distinction in this platform.

| | Forgetting | Erasure |
|---|---|---|
| Cause | Decay, retention | A legal request |
| Trigger | Scheduled sweep | On demand, must complete |
| Scope | One fact | Every fact, evidence row and vector for a subject |
| Evidence | Pruned on archive | Deleted |
| Reversible | Until purge | **Never, by design** |
| Answer to an auditor | "It decayed" | "It is gone" |

"It was forgotten" is not an answer to *"prove this customer's data is
deleted"*, so they are separate operations with separate audit records.
`MemoryDecayService` never erases; `MemoryErasureService` never decays.

### The half of erasure that is easy to miss

Deleting the facts *about* a customer is obvious. The subtle half is the
aggregate facts their conversations **contributed to**. "Card declines
spike at month-end" is a fact about the business, not about them, and it
survives — but its support must be recomputed once their evidence is gone,
or it keeps claiming a confidence it can no longer justify.

An erasure that deleted those would remove more than it was asked to; one
that left them untouched would leave a number standing on evidence that no
longer exists. So erasure does the third thing:

1. Find the aggregate facts they contributed to **first**, while their
   evidence still exists to identify them.
2. Delete the facts about them, and their vectors.
3. Delete their evidence everywhere else.
4. Recompute what is left. A fact that loses its last support is
   **archived, not deleted** — the row is the record that the platform
   once believed this, and an erasure request did not ask for the
   company's own history to be rewritten.

Aggregate facts survive only because they are non-attributable by
construction: a fact supported by a single customer is not aggregate, and
the distinct-customer weighting is what keeps that line real rather than
asserted.

`ErasureReport` returns counts rather than an acknowledgement, because
"we ran erasure" is not evidence and this is the response somebody
forwards to a regulator.

---

## The Memory Manager is the only writer

Every guarantee above rests on this. With two doors, confidence gets set
by hand somewhere, evidence gets skipped on the path somebody was in a
hurry on, lifecycle transitions happen outside the state machine, and the
audit trail acquires holes nobody can enumerate.

Enforced three ways, because a rule that depends on people remembering it
is a rule that erodes:

1. **An AST guard** —
   `tests/unit/test_memory_manager_is_the_only_writer.py` — fails if any
   module outside the Manager calls a memory write method, and a second
   check fails if a module merely *constructs* a memory repository outside
   a known list. Static rather than behavioural, deliberately: a
   behavioural test covers the paths somebody thought to write, and this
   covers the paths nobody has written yet. Modelled on
   `test_ownership_is_the_only_writer.py`, which exists for the same
   reason.
2. **The contract is checked at the door**, by the pure validator, before
   anything reaches the session.
3. **One transaction boundary.** A fact, its evidence, its recomputed
   confidence and its lifecycle transition commit together or not at all.

Three modules are on the allow-list, each with its reason recorded in the
guard: the Manager itself; erasure (which deletes and must complete even
where no Manager is wired, and reaches recompute through a narrow port);
and the decay sweep (which purges rows the state machine already marked
and prunes history — every *recompute* in it goes through the Manager).

**Counters are recomputed from evidence, never incremented.** An increment
is wrong the moment anything deletes evidence — which erasure does,
constantly — and a counter that has drifted from its evidence is a
confidence nobody can justify.

**Re-observation is idempotent** on `(fact, source_type, source_id)`.
At-least-once delivery makes replay the normal case, and a replay that
inflated the counters would inflate exactly the numbers confidence is
computed from.

---

## Policy and permissions

`Policy.MEMORY_RECORDING` gates whether the platform may remember anything
for a company. It **fails closed**, like `AI_ENGAGEMENT`: a caller that
did not populate capabilities is refused rather than granted permission to
retain what somebody said.

Deliberately **independent of `AI_ENGAGEMENT`**. Memory is consumed by
Reporting, CRM, the Customer Timeline and Analytics as well as by AI, so
gating it on the AI switch would mean turning AI off silently emptied the
Customer Timeline — a consequence nobody flipping that switch is asking
for. A hospital may want AI answering from approved articles while
retaining nothing about what patients said; one switch cannot express
that.

A customer who has asked for no automated messages is **not** refused
here. That preference is about being contacted by a machine, not about the
company keeping notes on its own relationship with them, and conflating
the two would let a contact preference quietly delete a business record.

| Permission | Gates | Default roles |
|---|---|---|
| `memory.read` | Reading memory | Owner, Admin, Agent |
| `memory.manage` | Record, confirm, correct, suppress | Owner, Admin |
| `memory.erase` | Irreversible erasure of a subject | **Owner only** |

Three rather than one, split by blast radius. Suppressing a fact is
reversible and visible; erasure is neither, and it is the permission a
regulator asks who holds.

`memory.enabled` defaults to **on**, unlike the AI switches. AI defaults
off because it generates content a company may not want sent; memory
defaults on because it is how the Customer Timeline and Reporting already
describe a relationship, and shipping it off would mean every existing
company silently lost a capability the moment the platform gained it.

---

## Storage

| Table | Holds | Soft delete |
|---|---|---|
| `memory_facts` | All three durable tiers | **No** |
| `memory_evidence` | Pointers supporting a fact | **No** |
| `memory_confidence_samples` | Rolling confidence history | **No** |

No soft delete on any of them, which is deliberate and unlike every other
entity in this schema. These tables are subject to erasure requests, and a
store promising both immutability and deletion is promising one of them
falsely.

**`uq_memory_facts_identity`** on `(company, tier, subject_type,
subject_id, fact_type, fact_key)` is the dedupe identity. Without it a
second observation creates a sibling row, the support splits between them,
and a fact seen a hundred times crosses no threshold.

The key is **never the statement text** — a caller may reword its output
between runs, and keying on prose would fork a fact's history every time
the wording changed. `domain/memory_identity.py` normalises: Unicode
NFKC, case folding, Arabic diacritic removal and orthographic folding
(أ/إ/آ → ا, ة → ه), and hashing rather than truncation past 180
characters, because truncation makes two long distinct keys collide on
their shared prefix.

For Experience, the **stratum is part of the identity**. The same claim
about two segments is two facts; merging them would reintroduce the
confounding that stratification exists to remove.

`OWNER_MEMORY_FACT` is declared for stage 1's polymorphic `embeddings`
table, so semantic recall over memory needs no schema change when it
arrives.

---

## Events

Published through the existing outbox, so the audit consumer (bound to
`#`) records them with no new machinery.

| Event | When |
|---|---|
| `memory.fact_recorded` | A new fact exists |
| `memory.fact_reinforced` | An existing fact gained evidence |
| `memory.fact_state_changed` | Confidence crossed a threshold |
| `memory.fact_lifecycle_changed` | Active/dormant/archived moved |
| `memory.fact_confirmed` | A human vouched for it |
| `memory.fact_suppressed` | A human muted it |
| `memory.fact_corrected` | A human rewrote it |
| `memory.fact_contradicted` | Something authoritative disagreed |
| `memory.fact_archived` | Retired from the working set |
| `memory.subject_erased` | An erasure completed, with counts |

**Payloads carry ids, counts and structure — never the statement.** The
audit log has longer retention and a different permission than the
conversations a memory derives from, so a statement in the payload would
be a second, longer-lived copy of customer content. `memory.subject_erased`
in particular carries only counts: an erasure event naming what was erased
would defeat the erasure.

---

## Background work

`blinkengage.memory.age_memory`, hourly. Three jobs in one pass:

1. **Recompute confidence.** Decay is *computed*, not applied — the sweep
   re-evaluates a function whose recency term has moved rather than
   decrementing a number. That is why "why is this 0.31 now when it was
   0.88 in March?" is always answerable.
2. **Move the lifecycle**, using each company's own retention where it has
   one, resolved per company rather than once per sweep — a sweep applying
   one company's shorter window to another's rows would delete data nobody
   asked it to.
3. **Purge and prune.** Rows the state machine marked purged are deleted;
   confidence history past its window is trimmed.

Hourly is far more often than any fact's confidence meaningfully moves —
half-lives here are months — but keeps each run's backlog small. Because
decay is computed rather than applied, a missed run costs only staleness
in the stored number; the next run is correct without catching up.

---

## What is verified

| | |
|---|---|
| Pure domain rules | 36 tests — contract, confidence, lifecycle, identity |
| Exclusive-writer guard | 8 tests, including planted writers it must catch |
| Platform behaviour | 18 tests — recording, dedupe, idempotency, ageing, erasure, isolation |
| HTTP surface | 16 tests — API, permissions, working memory |
| Migration | Applied, downgraded and re-applied on real PostgreSQL |

The tests that matter most are the erasure ones: that an aggregate fact
survives but loses the erased customer's support, that one which loses
*all* support is archived rather than deleted, and that erasing in one
company does not touch another company holding the same customer id.

---

## See also

- [Knowledge, Memory and Intelligence](./knowledge-memory-intelligence.md) — the domain boundaries
- [Company Intelligence Engine](./company-intelligence-engine.md) — stage 1, semantic retrieval
- [Policy Engine](./policy-engine.md)
- [Domain Event Bus](./event-bus.md)
- [Domain ownership audit](./domain-ownership.md)
