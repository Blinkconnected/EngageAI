# Knowledge, Memory and Intelligence

Three independent domains, with different owners, different guarantees and
different lifecycles. This is a platform-wide separation, not a structure
inside one engine — every module that reads or writes what the company knows
sits on one side of these lines.

## Five questions, three owners

The product vocabulary is five questions, and it is the right vocabulary —
it is how a person explains this platform to another person:

| Question | Answered by |
|---|---|
| What is true? | **Knowledge** |
| What do we know? | **Memory** |
| What has historically worked? | **Experience** |
| How do we sound? | **Company DNA** |
| What should we do now? | **Intelligence** |

But a *domain* in this architecture is not a question. It is a **write path
and an erasure boundary** — who may create a row, and who must be able to
prove it is gone. On that test there are three, and Experience and Company DNA
resolve into them rather than standing beside them:

- **Experience is a Memory tier**, not a fourth peer. The argument is erasure,
  and it is developed in [Experience](#experience).
- **Company DNA splits in two**, and the split is the point: binding wording is
  Knowledge, and characteristic style is Memory. Developed in
  [Company DNA](#company-dna).

Five questions, three owners. The vocabulary survives intact; the ownership
boundaries stay countable, which is what keeps erasure and audit provable.

| | **Knowledge** | **Memory** | **Intelligence** |
|---|---|---|---|
| Represents | Official business truth | What the platform observed | Reasoning over both |
| Written by | Humans, through approval | The Memory Manager, from evidence | **Nothing. It owns no data.** |
| Guarantee | Versioned, immutable per version, auditable | Evidence-based, confidence-scored, erasable | Reproducible from its inputs |
| Wrong looks like | A wrong price quoted to every customer | A pattern that stops being true | An answer that cited the wrong source |
| Lifecycle | Draft → published → superseded → retired | Two axes, below | None — it holds nothing between turns |
| Erasable | No (retired, never deleted) | **Yes, and it must be** | N/A |

Status: **design.** Nothing here has shipped. Companion to
[Company Intelligence Engine](./company-intelligence-engine.md), which
designs the Intelligence layer's retrieval and learning machinery; this
document owns the domain boundaries the engine must respect.

---

## Why the separation exists

The failure it prevents is specific, and it is the one that kills systems of
this shape.

Without the separation, "the AI learned that our refund window is 14 days" and
"our refund policy states 14 days" are the same sentence in the same store,
distinguishable only by a column somebody remembered to check. Six months in,
a retrieval ranks the learned one higher because it was observed more
recently, and the platform quotes a refund window nobody approved. Nothing
fails, no test goes red, and the company finds out from a customer holding the
platform to a promise it invented.

The separation makes that structurally impossible rather than carefully
avoided: the two facts live in different tables, carry different authority,
enter retrieval through different retrievers, and only one of them can ground
a restricted claim.

`domain-ownership.md` already runs this discipline for the operational
platform — every business fact has a named owner, and the audit records where
two owners disagree. This extends the same discipline to what the company
knows.

---

## Ownership matrix

In the style of `domain-ownership.md`, so the two read together.

| Business fact | Owner | Consumers | Exposed as |
|---|---|---|---|
| What the company officially states | **Knowledge** | Intelligence, agents, customers | `knowledge_article_versions`, immutable |
| Whether a statement is approved | **Knowledge** | Intelligence (authority filter) | `Authority.AUTHORITATIVE` |
| What the platform has observed | **Memory** | Intelligence, analytics | `*_memory_facts`, confidence-scored |
| How sure we are of an observation | **Memory** | Intelligence (ranking), review queues | Computed `confidence` |
| Why we believe an observation | **Memory** | Review, audit, erasure | `memory_evidence` |
| What is true right now in this conversation | **Memory** (working) | Intelligence | Conversation Memory |
| Live stock, invoices, balances | **Systems of Record** | Intelligence | Queried, never stored |
| What may be said to this customer | **Policy Engine** | Intelligence | `PolicyDecision` |
| What the answer should be | **Intelligence** | Conversation, agents | A response with citations |
| What becomes official | **Humans** | — | `suggestion_reviews`, append-only |

Read the last four rows together. They are the platform's actual chain of
authority, and each link is owned by something different: **Systems of Record
supply facts, Memory supplies observations, Intelligence proposes, Policy
decides, Humans approve.** No module holds two of those.

---

## A vocabulary collision, resolved

The brief says Intelligence produces "decisions, recommendations and
responses." Two of those three are right. The third collides with something
this codebase already owns.

`domain-ownership.md` assigns *"Whether AI may engage"* to the Policy Engine,
and `policy-engine.md` opens with *"Every business rule in Blink Engage lives
here, and only here."* A `PolicyDecision` is a specific, frozen, recorded
object with an effect, a reason and a source. If Intelligence also makes
"decisions," two modules claim the word, and the first thing that happens is
someone writing a business rule inside the reasoning layer because that is
where decisions are made — which is precisely the fragmentation the Policy
Engine exists to end.

The vocabulary, fixed:

| Verb | Owner | Produces |
|---|---|---|
| **Reasons / proposes** | Intelligence | An answer, a recommendation, a suggestion |
| **Decides** | Policy Engine | A `PolicyDecision` — allowed or not, and why |
| **Approves** | Humans | A published knowledge version |
| **Remembers** | Memory Manager | A confidence-scored fact with evidence |

Intelligence may propose an action it is not permitted to take, and that is a
normal, healthy state — the proposal is recorded, the refusal is recorded, and
a supervisor can see both. An Intelligence layer that could only propose what
it was allowed to do would be one that had absorbed the policy rules.

---

## The fourth input: Systems of Record

The brief lists "live company data" among Intelligence's inputs without giving
it a name or a rule. It needs both, because it is neither Knowledge nor
Memory and will otherwise be filed under whichever is closer to hand.

**A system of record is queried, never remembered.** ERP stock levels,
invoice balances, order status, calendar availability, CRM account state.

The rule exists because a remembered stock level is wrong by the time it is
retrieved, and a confidently-cited wrong balance is worse than no answer. The
distinction is not about freshness preference; it is about which store is
*authoritative for that fact*. ERPNext owns invoice balances. Memory inferring
one from a conversation and Intelligence citing it would be the platform
guessing at a number a connected system knows exactly.

| | Knowledge | Memory | System of Record |
|---|---|---|---|
| "Our refund window is 14 days" | ✅ | — | — |
| "This customer's card declined twice" | — | ✅ | — |
| "This customer owes 42.50 JOD" | — | ❌ never | ✅ |
| "Card declines spike at month-end" | — | ✅ | — |

Where a system of record is connected, it wins over both Knowledge and Memory
for the facts it owns, and Memory stores only what it does not know. Where it
is disconnected, the honest answer is that the platform cannot say — not a
remembered figure from March.

---

## Knowledge

### "Immutable once published" — restated

The brief says Knowledge is "immutable once published." Taken literally that
is a rule that makes a wrong published price uncorrectable, and somebody will
implement it literally.

**Versions are immutable. The article is a moving pointer.**

```
knowledge_articles.current_version_id ──► knowledge_article_versions   (append-only)
        (mutable pointer)                  v1  v2  v3 ...  each frozen forever
```

A correction mints v4 and moves the pointer. v3 is never rewritten, stays
readable, and stays the answer to "what did this say in March?" — which is the
entire purpose. This is the exact mechanism `services.current_version_id`
already uses, for the reason `execution-context.md` gives: "the current one" is
a single fact and two rows both claiming it is a state no query can resolve.

Three operations, deliberately distinct, because collapsing them is how a
knowledge base loses its audit trail:

| Operation | Effect on retrieval | Effect on history | Approval |
|---|---|---|---|
| **Correction** | New version retrieved | Old version readable forever | Normal workflow |
| **Retraction** | Nothing retrieved | Every version readable forever | Normal workflow |
| **Emergency withdrawal** | Nothing retrieved, immediately | Everything readable | **One authorised human, no queue** |

Emergency withdrawal is the one the workflow diagram would otherwise omit. A
published price that is wrong is being quoted right now, and a process that
requires a second reviewer before it can stop is a process that will be
bypassed by an engineer with database access — which is worse in every way,
including the audit trail. So it exists, it is a permission
(`knowledge.withdraw_emergency`), it takes effect on the next retrieval, and
it writes a `suggestion_reviews`-style record naming who did it. Restoring
requires the normal workflow.

### What Knowledge is not

It is not everything a human wrote. An uploaded PDF is unreviewed content that
happens to have a human author, and it enters through the same suggestion
workflow as an inferred pattern — because the platform's promise is about
*approval*, not about who typed the characters.

---

## Memory as a first-class domain

Adopted, including the brief's naming. **Organizational Memory** replaces the
"Company Memory" of the engine document: `Company` is the tenant entity in
this codebase, and "company memory" reads as memory *of the company record*.

### Four tiers, and a challenge to the first

| Tier | Scope | Lifetime | Confidence? | Claim type | Erasable |
|---|---|---|---|---|---|
| **Conversation Memory** | One conversation | The conversation | **No** | — | With the conversation |
| **Customer Memory** | One customer | Years, decaying | Yes | Descriptive | **Yes, on request** |
| **Organizational Memory** | The company | Indefinite, decaying | Yes | Descriptive | Aggregate only |
| **Experience** | The company | Indefinite, decaying | Yes | **Causal** | Aggregate only |

The `Claim type` column is the one that earns Experience a section of its own,
and it is a distinction the brief does not draw. Descriptive claims are
established by counting. Causal claims are not, and nothing else in this
architecture makes one.

Conversation Memory is a genuine gap in the engine document and a good
addition — without it, a customer who gave their order number at turn 3 is
asked for it again at turn 20, which is the single most recognisable way an
AI reveals it is not really following the conversation.

**But it does not belong in the same contract as the other two.** It has no
confidence, no evidence rows, no approval state, no decay, no contradiction
count. Every field the brief specifies for a learned fact is meaningless for
it. Modelling it as a `memory_fact` would mean either giving it eight columns
that stay null or loosening the contract for the two tiers that need it.

**Resolution:** Conversation Memory is *working memory*, an explicitly
different kind with its own contract, and the boundary between it and learned
memory is a named operation.

```
  ┌────────────────────────────────────────────────┐
  │  Conversation Memory  (working)                │
  │  Redis, TTL-bound, no confidence, no evidence  │
  │  entities · unresolved questions · commitments │
  │  stated preferences · turn summaries           │
  └───────────────────┬────────────────────────────┘
                      │  conversation.resolved
                      ▼
              ═══ DISTILLATION ═══
                      │
      ┌───────────────┴───────────────┐
      ▼                               ▼
  Customer Memory              Organizational Memory
  (evidence-backed)            (evidence-backed, aggregate)
```

Working state lives in Redis with a TTL, not Postgres — it is exactly the
"fine to drop if nobody's listening" tier `event-bus.md` already distinguishes
from durable events, and a row per turn per conversation in Postgres buys
durability for something that is worthless once the conversation ends. One
durable summary row survives, as the input to distillation and to the
similar-conversation retriever.

Distillation is where working memory becomes evidence. It is the only path,
it runs asynchronously after resolution, and it is subject to
`Policy.KNOWLEDGE_LEARNING` — so a company that forbids learning gets full
working memory during conversations and nothing retained after them, which is
a coherent product for a regulated tenant rather than an all-or-nothing switch.

---

## Experience

**Adopted in full as a concept. Declined as a fourth peer domain.** The
content is right and there is a real gap in the engine document that this
closes; the disagreement is only about where it lives, and the reason is
erasure.

### Why not a fourth domain

Test Experience against every axis this architecture uses to separate domains:

| Axis | Memory | Experience |
|---|---|---|
| Written by | Memory Manager, from evidence | Memory Manager, from evidence |
| Confidence | Computed from evidence | Computed from evidence |
| Lifecycle | Two axes, decaying | Two axes, decaying |
| Erasure | Cascades from a subject | Cascades from a subject |
| Contradicted by Knowledge | Yes, demoted on sight | Yes, demoted on sight |

Identical on all five. But the decisive argument is the last one, and it is
not about tidiness.

**A customer erasure request must remove that customer's contribution from
Customer Memory, Organizational Memory and Experience in one transaction.**
If Experience is a peer domain with its own manager and its own write path,
erasure becomes a distributed transaction across two owners — and the
guarantee degrades from "it is gone" to "we asked both and neither reported an
error." A platform that sells to healthcare and government cannot answer a
regulator that way. One erasure boundary means one owner.

So Experience is a **Memory tier**: same Manager, same lifecycle, same
transaction, same erasure cascade. What it gets that no other tier has is the
causal machinery below — which is the part that genuinely deserved to be
called out, and which I under-modeled.

### What was actually missing: failure

The engine document's Agent Experience tier had a quality gate that admitted
only resolved, un-reopened, un-escalated conversations. That gate is correct
for learning *what to say* — and it means the platform could never learn what
**not** to say, because every conversation that went wrong was filtered out
before clustering ever saw it.

The brief's "failed resolutions" and "escalation patterns" close a real hole.
Learning from failure is the higher-value half: a phrasing that reliably
precedes an escalation is more actionable than a phrasing that correlates with
success, because the failure has a clear owner and a clear fix.

So the corpus splits, and both halves are learned:

| Outcome corpus | Gate | Produces |
|---|---|---|
| **Succeeded** | Resolved, not reopened, not escalated, CSAT ≥ threshold or absent | `EFFECTIVE_RESPONSE`, `EFFECTIVE_WORKFLOW` |
| **Failed** | Escalated, reopened, abandoned, or CSAT below threshold | `ESCALATION_TRIGGER`, `INEFFECTIVE_RESPONSE`, `CHURN_SIGNAL` |

Fact types, all sharing the standard contract:

| `fact_type` | Claim |
|---|---|
| `EFFECTIVE_RESPONSE` | This response, for this intent, precedes resolution |
| `INEFFECTIVE_RESPONSE` | This response precedes reopen or escalation |
| `ESCALATION_TRIGGER` | This condition precedes escalation |
| `EFFECTIVE_WORKFLOW` | This sequence of steps resolves this issue class |
| `FCR_PATTERN` | This approach resolves on first contact |
| `CSAT_DRIVER` | This factor moves CSAT for this segment |
| `HANDLING_TIME_PATTERN` | This approach shortens or lengthens resolution |

### Causal claims from observational data

This is the part that needs machinery nothing else in the platform needs, and
the reason Experience is worth naming even as a tier rather than a domain.

"Card declines spike at month-end" is descriptive. You establish it by
counting, and counting is sufficient.

"This phrasing resolves faster" is **causal**, and counting cannot establish
it. The platform has observational data and no experiment, which means every
Experience fact is exposed to inferences that are confidently wrong:

- **Confounding.** The agent whose refund responses show 4.8 CSAT may handle
  VIP customers, who rate everything higher. The phrasing did nothing.
- **Selection.** Easy tickets get resolved on first contact regardless of
  approach. An approach used mostly on easy tickets looks excellent.
- **Reverse causation.** Escalation-linked phrasing may be what agents reach
  for when a conversation is *already* going badly. The phrasing is a symptom
  being recorded as a cause.
- **Simpson's paradox.** An approach that wins in every segment can lose
  overall, or the reverse, purely from segment mix.

Four guardrails, all required, none of which the other memory tiers need:

1. **Stratify before comparing.** Outcomes are compared within strata —
   customer tier, intent, channel, language, conversation complexity — never
   pooled across them. A comparison whose strata are too thin produces no
   fact rather than a pooled one.
2. **Minimum sample and diversity floors**, per stratum, with distinct agents
   and distinct customers counted separately — the same reason the confidence
   formula weights them separately.
3. **Baseline-relative statements.** An Experience fact stores an effect *and*
   the baseline it beat, so its claim is "resolves 18 points above the stratum
   baseline (n=340)" rather than "resolves 87%." A bare rate is a number
   nobody can evaluate.
4. **Honest language.** Statements are generated as *associations*, not
   mechanisms: "precedes resolution more often than the baseline" rather than
   "causes resolution." The wording reaches a manager in a review queue, and a
   claim that overstates its evidence is one that gets approved on the strength
   of its grammar.

Where a company runs enough volume, the honest upgrade is a real experiment —
randomising between two candidate responses and measuring. That is a genuine
future capability, it is the only thing that turns these associations into
causal claims, and it is deliberately not designed here.

### Experience influences Intelligence as evidence, never as instruction

The brief is right that this must not become official knowledge
automatically, and it already cannot: Experience is `OBSERVED`, so the
authority rules apply unchanged — it never grounds a restricted-class claim,
it ranks below official knowledge, and it reaches Knowledge only through a
human-approved Suggestion.

One addition specific to this tier: `INEFFECTIVE_RESPONSE` and
`ESCALATION_TRIGGER` are **negative** evidence, and negative evidence must not
be handed to a generator as text. Injecting "do not say X" into a prompt is a
reliable way to make a model say X. Negative experience is applied as a
**re-ranking penalty on candidates** and as a verifier check, never as a
prompt instruction.

### The agent-attribution problem

Experience is the only tier whose subject can be an **employee**, and that
changes its regulatory weight. Automated performance inference about staff is
employment data in most of the jurisdictions this platform sells into, and in
some it requires consultation before it exists at all — not before it is
displayed.

Three constraints, applied at the tier:

- Agent-attributed facts require a higher distinct-conversation floor than
  aggregate ones, so a fact about a person is never thin.
- `Policy.AGENT_LEARNING` — a company may learn organisational patterns while
  attributing nothing to individuals. Configured off by default in the
  restricted-segment deployment profile.
- Agent-attributed Experience is readable under a permission separate from
  `intelligence.read`, because "what works here" and "how is Layla performing"
  are different questions with different audiences, and one query away from
  each other if they share a permission.

---

## The fact contract

Every learned fact in Customer Memory and Organizational Memory carries this.
The brief's list, with four corrections argued below.

| Field | Meaning |
|---|---|
| `confidence` | **Computed** from evidence, never model-claimed |
| `confidence_state` | OBSERVED / CANDIDATE / CONFIRMED / TRUSTED |
| `lifecycle_state` | ACTIVE / DORMANT / ARCHIVED / PURGED |
| `evidence_count`, `distinct_customers`, `distinct_agents` | Support breadth |
| `outcome_quality` | CSAT and resolution rate of supporting conversations |
| `contradiction_count` | Times contradicted by Knowledge or a stronger fact |
| `contradicted_by` | What contradicted it |
| `created_at`, `updated_at` | Standard |
| `last_observed_at` | New evidence arrived |
| `last_confirmed_at` | **Corroborated — a stricter thing than observed** |
| `subject_ref` | What the fact is *about*; the erasure key |
| `steward_user_id` / `steward_role` | Who to route contradictions to |
| `human_state` | UNREVIEWED / CONFIRMED / SUPPRESSED / CORRECTED |
| `learning_run_id`, `pipeline_version` | Reproducibility |

### Correction 1 — `last_confirmed_at` needs "confirmed" defined

The brief lists the field without saying what confirms a fact. Three candidate
meanings, with very different consequences:

| Signal | Is it confirmation? |
|---|---|
| New evidence observed | **No** — this is `last_observed_at` |
| The fact was cited in an answer that resolved the conversation | **Yes** |
| A human explicitly confirmed it | **Yes**, and it is the strongest form |
| A customer repeated the same claim | **No** |

If observation counted as confirmation, a customer repeating a wrong belief
forty times would confirm it — which is the poisoning path the engine document
already defends against, arriving through a field name instead of a prompt.
Two fields, and only corroboration by *outcome* or *human* moves the second.

### Correction 2 — `owner` splits into subject and steward

"Owner" on a memory fact is ambiguous in a way that matters: the customer it
is about, the agent whose behaviour produced it, or the department accountable
for the topic?

They must be separate because they serve different mechanisms. `subject_ref`
is what erasure keys on and it must be exact — an erasure request that misses
a fact because "owner" held a department id is a compliance failure.
`steward_user_id` is where a contradiction gets routed for review and is
allowed to be null, defaulting to the topic's department.

### Correction 3 — `approval_state` is not a workflow here

The brief gives every learned fact an approval state. Applied literally, every
inferred language preference enters a review queue, and a queue containing
every learned preference is one nobody opens — the same failure mode the
engine document already guards against for suggestions.

Approval is the **Suggestion's** workflow. On a fact, what is worth recording
is whether a human has intervened at all, which is a different and much
sparser thing: `human_state` defaults to `UNREVIEWED` and moves only when
somebody acts. A human confirming or suppressing a fact is a strong signal and
overrides computed confidence in both directions.

### Correction 4 — confidence is computed, and decay does not mutate evidence

Restated from the engine document because the lifecycle depends on it:

```
confidence = f(evidence, recency, outcomes, contradictions)
```

A pure function over the evidence rows, recomputed on a schedule and stored
with `confidence_computed_at` for query performance. Two consequences that
matter:

- **Decay is computed, not applied.** The nightly job does not decrement a
  number; it recomputes a function whose recency weighting has moved. This is
  why "why is this 0.31 now when it was 0.88 in March?" is always answerable —
  the inputs are all still there.
- **Evidence rows are never deleted by decay.** Only erasure deletes evidence.
  A fact that decays keeps its history and can be re-confirmed with its
  accumulated support intact, which the next section shows is the case a
  linear lifecycle cannot express.

---

## The Memory Lifecycle

The brief proposes a seven-state chain:

```
Observed → Candidate → Confirmed → Trusted → Stale → Archived → Forgotten
```

**Challenged.** The seven names are good and the product vocabulary should
keep them. But the chain conflates two independent axes, and the conflation
breaks on cases that will happen constantly.

### The case that breaks it

A fact reaches `Trusted` over six months — 200 supporting conversations, 14
agents, high outcome quality. The topic goes quiet for a quarter. It decays to
`Stale`.

Then it is observed again.

On a single chain, where does it go? Back to `Candidate` throws away 200
conversations of accumulated evidence — the fact is now less believed than it
was, on strictly more evidence, which is incoherent. Jump straight to
`Trusted` and `Stale` was a label that meant nothing. There is no correct
answer because the question is malformed: **how much we believe a fact and how
alive the row is are different questions.**

Three more the chain cannot express:

- **Contradicted.** A `Trusted` fact contradicted by a newly published policy
  is not `Stale` — its evidence is fine and recent. Contradiction is a reason,
  orthogonal to position on any chain.
- **Suppressed by a human.** Not `Stale` (evidence is fine), not `Forgotten`
  (it is still there, and must stay there so it is not re-learned next week).
- **Erased.** Legally distinct from `Forgotten` — see below.

### Two axes, seven labels

```
confidence_state    OBSERVED ──► CANDIDATE ──► CONFIRMED ──► TRUSTED
                        ▲            ▲             ▲            │
                        └────────────┴─────────────┴────────────┘
                                  demotion on contradiction

lifecycle_state     ACTIVE ──► DORMANT ──► ARCHIVED ──► PURGED
                       ▲          │
                       └──────────┘
                       re-observation revives

orthogonal flags    contradicted · human_state
```

`confidence_state` is derived from computed confidence crossing thresholds,
with hysteresis — promotion and demotion thresholds differ, so a fact hovering
at a boundary does not flap between states nightly and generate a notification
every time.

| State | Means | Retrievable |
|---|---|---|
| `OBSERVED` | Seen once or twice. Below candidate threshold. | No |
| `CANDIDATE` | Enough support to be worth considering | Ranked low |
| `CONFIRMED` | Corroborated by outcome or human | Yes |
| `TRUSTED` | Broad, durable, high-outcome support | Yes, boosted |

`lifecycle_state` is about the row, not the belief:

| State | Means | Retrievable | Data |
|---|---|---|---|
| `ACTIVE` | Normal | Per confidence | Full |
| `DORMANT` | Not observed within its type's window | No | Full, revivable |
| `ARCHIVED` | Past retention; kept for audit and analytics | No | Fact + counts, evidence pruned |
| `PURGED` | Gone | No | Nothing |

The brief's vocabulary survives as **derived display labels**, which is what
the product and the UI should keep saying:

| Shown to a human | Derived from |
|---|---|
| Observed | `OBSERVED` + `ACTIVE` |
| Candidate | `CANDIDATE` + `ACTIVE` |
| Confirmed | `CONFIRMED` + `ACTIVE` |
| Trusted | `TRUSTED` + `ACTIVE` |
| Stale | any confidence + `DORMANT` |
| Archived | `ARCHIVED` |
| Forgotten | `PURGED` by decay |
| Contradicted | `contradicted = true` |
| Suppressed | `human_state = SUPPRESSED` |

And the case that broke the chain now resolves cleanly: re-observation moves
`lifecycle_state` from `DORMANT` back to `ACTIVE` and leaves `confidence_state`
at `TRUSTED`, because the evidence never went anywhere. Displayed: `Stale` →
`Trusted`. Exactly what a human would expect, and unreachable on one axis.

### Forgetting is not erasure

The most important distinction in this document, and the brief's single
`Forgotten` state hides it.

| | **Forgetting** | **Erasure** |
|---|---|---|
| Cause | Decay, irrelevance, retention | A legal request or a deleted customer |
| Trigger | Scheduled | On demand, must complete |
| Scope | This fact | Every fact, evidence row, embedding and graph edge for a subject |
| Aggregate memory | Survives | Survives **only if** it is non-attributable |
| Evidence | Pruned on archive | **Deleted** |
| Reversible | Yes, from evidence, until purge | **No, by design** |
| Answer to an auditor | "It decayed" | "It is gone" |

They must be separate operations with separate audit records, because "it was
forgotten" is not an answer to "prove this customer's data is deleted."
Erasure is a transaction; forgetting is a schedule.

Organizational Memory surviving erasure is defensible only because a fact
cannot be supported by a single customer — `distinct_customers` thresholds
make "card declines spike at month-end" genuinely non-attributable. That
threshold is what keeps the line real rather than asserted, and it is why it
is a hard floor rather than a tunable that could be set to 1.

---

## The Memory Manager

Adopted, with the responsibility list restructured.

### The challenge

Seven responsibilities — learning, consolidation, deduplication, contradiction
detection, decay, forgetting, evidence scoring — in one component is a service
that touches every memory table and every learning path. This codebase already
carries a scar from that shape: `core/wiring.py` exists because services
assembled from many optional collaborators fail *silently*, and two such
defects ran in production undetected because "nothing raises, nothing logs,
every test that builds the service directly keeps passing."

### What is actually valuable in the idea

Not colocation of logic. **Exclusive write ownership.**

> **The Memory Manager is the only writer to memory tables.**

That is a strong, enforceable, testable invariant, and it is what makes every
guarantee in this document hold. If any service can write a memory fact, then
confidence can be set by hand somewhere, evidence can be skipped, lifecycle
transitions happen outside the state machine, and the audit trail has holes
nobody can enumerate.

So: a facade owning the write path, over pure policies that are independently
testable.

```
MemoryManager                       ← the ONLY writer. Owns transactions.
├── domain/memory_confidence.py     pure: evidence → confidence     (no I/O)
├── domain/memory_lifecycle.py      pure: state + signals → state   (no I/O)
├── domain/memory_identity.py       pure: fact → dedupe key         (no I/O)
├── MemoryConsolidationService      merges facts, transfers evidence
├── ContradictionDetectionService   Knowledge ⨯ Memory, Memory ⨯ Memory
├── MemoryDecayService              scheduled recompute
└── MemoryErasureService            the transaction, and its audit record
```

The three `domain/` modules take no repository and no clock — the same
constraint that makes `domain/policies.py` exhaustively testable, and for the
same reason: a confidence function that could look things up would be one
whose answer depended on when you asked it.

Everything else takes a repository and is separately testable. The Manager
composes them and owns the transaction boundary, so a fact, its evidence, its
lifecycle transition and its graph edges commit together or not at all.

`MemoryErasureService` is separate from decay deliberately, per the
distinction above — one is a schedule, the other is a promise with a deadline.

### Responsibilities, mapped

| Brief's responsibility | Where it lives |
|---|---|
| Learning | Manager write path, fed by learning consumers |
| Evidence scoring | `domain/memory_confidence.py`, pure |
| Consolidation | `MemoryConsolidationService` |
| Deduplication | `domain/memory_identity.py` + Manager upsert |
| Contradiction detection | `ContradictionDetectionService` |
| Decay | `MemoryDecayService`, recompute not mutate |
| Forgetting | `MemoryDecayService` (archive/purge) — **not** erasure |

---

## Enforcing "Intelligence never owns data"

The rule is right and it will erode by default. Someone adds a write to save a
round trip, it passes review because it is one line, and the boundary is gone
without any test noticing. Three mechanisms, structural rather than
conventional — the posture `core/wiring.py` and the `ai_may_engage` regression
test already establish.

**1. Read-only ports.** Intelligence services are constructed with reader
protocols only — `KnowledgeReader`, `MemoryReader`, `GraphReader` in `domain/`
— which expose no write method. Not "should not write": *cannot*, because
there is no method in scope to call. This is the same structural trick
`ExecutionContext` uses, where a module "cannot look anything up again, because
it holds no ids to look up with."

**2. An import-boundary test.** A unit test walks the modules under the
intelligence package and fails if any imports a memory or knowledge writer, a
repository with a write method, or a unit of work. The precedent is
`test_wiring.py`, whose second test exists to catch the guard's own list
falling behind — a check that silently stops covering something "reads like
coverage."

**3. Intelligence emits events, never writes.** Learning is a consumer of
`ai.answer_produced`, not a call at the end of the pipeline. The asynchronous
boundary the brief asks for is therefore also the ownership boundary, and one
mechanism enforces both.

### Package structure

Bounded contexts under `application/`, with pure rules staying in `domain/` —
`domain/` in this codebase means the framework-free layer, not "a business
domain," and overloading it would be its own confusion:

```
application/knowledge/       versions, sources, ingestion, publication
application/memory/          the Manager and its services
application/intelligence/    retrieval, reasoning, verification  ← readers only

domain/knowledge_authority.py   pure    what may ground what
domain/memory_confidence.py     pure    evidence → confidence
domain/memory_lifecycle.py      pure    state transitions
domain/memory_identity.py       pure    dedupe keys
domain/intelligence_context.py  frozen  the resolved retrieval result
```

---

## Where the three domains meet

Exactly three sanctioned crossings. Anything else is a boundary violation.

| Crossing | Mechanism | Direction |
|---|---|---|
| Memory → Knowledge | **Knowledge Suggestion**, human-approved | Never automatic |
| Knowledge → Memory | **Contradiction**, demotes or retires a fact | Automatic, one-way |
| Knowledge + Memory → Intelligence | **Read-only retrieval** into `IntelligenceContext` | Read only |

The second is worth stating explicitly because it is asymmetric and that
asymmetry is the point: Knowledge may *invalidate* Memory automatically —
publishing an official refund policy immediately demotes every learned fact
that disagrees, with no human in the loop — while Memory may only ever
*propose* to Knowledge. Official truth corrects observation on sight;
observation asks permission. That single asymmetry is what "official knowledge
wins" means when it is a mechanism rather than a sentence.

---

## What changes in the engine document

[Company Intelligence Engine](./company-intelligence-engine.md) is the
Intelligence layer's implementation, and needs these alignments before build:

1. "Company Memory" → **Organizational Memory** throughout.
2. **Conversation Memory added** as working memory — Redis, TTL-bound, one
   durable summary row, distilled at resolution.
3. Memory tables carry **`confidence_state` + `lifecycle_state`**, replacing
   the single `status` column, plus `last_confirmed_at`, `subject_ref`,
   `steward_user_id`, `human_state`.
4. `MemoryManager` and its services join the service table as the **exclusive
   writer**; the individual memory services lose their write paths.
5. Retrieval services take **reader protocols**, not repositories.
6. Article immutability restated: **versions immutable, article a pointer**,
   plus retraction and emergency withdrawal.
7. **Systems of Record** named as a fourth input with its own rule.
8. Build order: the Memory Manager and the two pure lifecycle modules land at
   the start of stage 4, before any learning consumer writes a fact — a fact
   written before the Manager exists is one written outside the invariant, and
   backfilling an invariant is harder than starting with it.

---

## Open questions

Named rather than answered, because guessing at them in a document reads like
a decision.

- **Conversation Memory across conversations.** A customer opening a second
  chat about the same order — is that one working context or two? Leaning two,
  with Customer Memory carrying the continuity, because merging live working
  state across conversations creates a shared mutable object two agents can be
  reading simultaneously.
- **Confidence thresholds per fact type.** `TERMINOLOGY` should reach
  `TRUSTED` on far less evidence than `PROMISE_MADE`. The per-type table is
  worth calibrating against real data rather than inventing now.
- **Whether Organizational Memory can outlive erasure of every supporting
  customer.** The `distinct_customers` floor makes it non-attributable, but a
  fact whose entire evidence base has been erased is one nothing can
  re-derive. Leaning toward retaining the fact and marking its evidence
  irrecoverable — but this is a question for counsel, not architecture.

---

## See also

- [Company Intelligence Engine](./company-intelligence-engine.md)
- [Domain ownership audit](./domain-ownership.md)
- [Policy Engine](./policy-engine.md)
- [Execution Context](./execution-context.md)
- [AI Engine](./ai-engine.md)
- [Domain Event Bus](./event-bus.md)
