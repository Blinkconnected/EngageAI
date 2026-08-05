# Architecture Freeze Review

Final review of Stage 1 (semantic retrieval, built), Stage 2 (Memory
Platform, built) and the Learning Platform design, before implementation
of Stage 3.

**Verdict: NOT READY.**

Ten blockers, four ownership collisions, three event defects. Four of the
blockers are live defects in shipped code, and one of them is the exact
property this architecture claims as its foundation: *confidence cannot
inflate without new evidence.* It can. It is demonstrated below.

This is not a list of nice-to-haves. Nine of the seventeen findings are
cheap to fix now and expensive to fix after the Learning Platform starts
writing at volume, because Learning multiplies every one of them by its
event rate.

---

## B1 — Confidence inflates on replay. Proven.

**Severity: critical. Live in shipped code.**

The brief asks for a demonstration that confidence cannot inflate without
new evidence. Here is the demonstration, and it fails.

`MemoryManager.record()` sets `last_observed_at = moment` and calls
`revive_on_observation()` **before** `_attach_evidence()` has determined
whether any evidence was actually new. A replay of an identical
observation — same fact, same `source_id`, therefore zero new evidence
rows — refreshes recency anyway. Recency is a multiplicative term in the
confidence function, so it resets decay to 1.0.

Measured against the real code:

```
t0          record            conf=0.1280  support=1  lifecycle=active
t0+200d     decay recompute   conf=0.0274  support=1  lifecycle=dormant
t0+200d     REPLAY same src   conf=0.1280  support=1  lifecycle=active
                                                      evidence_added=False

evidence rows added by replay : 0
confidence before replay      : 0.0274
confidence after  replay      : 0.1280   ← 4.7× on nothing
```

The system *knows* nothing was added — `evidence_added=False` is returned
to the caller — and inflates anyway. A dormant fact is also revived.

At-least-once delivery makes replay the normal case, not the exceptional
one. The Learning Platform will emit `MemoryCandidateDetected` on every
cluster evaluation, hourly; RabbitMQ redelivery, a consumer restart, or a
sweep overlapping itself all produce exactly this call. **A quiet fact can
be held at full confidence indefinitely by a pipeline that observes
nothing new.**

**Fix.** `last_observed_at` and `revive_on_observation` must be
conditional on `evidence_added`. Move both after `_attach_evidence` and
gate them. Add a regression test asserting that a replay leaves
confidence, `last_observed_at` and `lifecycle_state` untouched — the test
that should have existed and did not, because every existing replay test
asserts on `support_count`, which is correctly unaffected.

---

## B2 — `contradict()` is not idempotent

**Severity: critical. Live in shipped code.**

```python
fact.contradiction_count += 1
```

No idempotency key, no evidence row, nothing that makes a second delivery
a no-op. Contradiction enters the confidence function as
`− w₅·log1p(contradictions)`, so a redelivered `ContradictionDetected`
demotes a true fact on no new information — the mirror image of B1, in the
other direction.

This matters more once Learning exists than it does today, because Stage 3
makes contradiction detection an event-driven consumer fired by every
knowledge publication. Redelivery is routine.

**Fix.** Contradictions must be rows, not a counter: a
`memory_contradictions` table keyed `(fact_id, source_type, source_id)`
with the same unique constraint `memory_evidence` already uses, and
`contradiction_count` recomputed from it — exactly the pattern
`support_counts()` already applies to evidence, and for exactly the same
reason ("an increment is wrong the moment anything deletes evidence").
The counter was written the way the codebase already documents as wrong.

---

## B3 — `confidence_direction` can never report FALLING or CONTESTED

**Severity: high. Live in shipped code.**

Both call sites in `MemoryManager._recompute` pass
`contradicting_delta=0` as a literal. `compute_direction` can therefore
only ever return `RISING`, `STABLE` or `UNKNOWN`.

`FALLING` and `CONTESTED` are unreachable code.

The Memory Platform document devotes a section to direction being "the
business-change detector" and calls a falling trusted fact "worth an alert
rather than a badge". `CONTESTED` is described as the finding that reveals
a company being inconsistent with itself. Neither can fire. The feature is
documented, tested at the pure-function level, wired end to end, and inert
in production.

**Fix.** Feed the real contradiction delta, which requires B2's table
first. The two are one change.

---

## B4 — `supporting_delta` compares a total against a delta

**Severity: high. Live in shipped code.**

```python
supporting_delta = support - _support_at(previous_sample)
```

`support` is a running total. `_support_at` returns the previous sample's
`supporting_delta` — a delta. Subtracting a delta from a total is
dimensionally meaningless and drifts:

| Run | support (total) | previous delta | computed delta | correct |
|---|---|---|---|---|
| 1 | 1 | — | 1 | 1 |
| 2 | 2 | 1 | 1 | 1 |
| 3 | 3 | 1 | **2** | 1 |
| 4 | 5 | 2 | **3** | 2 |

Direction is computed from this number, so what little of the feature B3
leaves working is fed a wrong input.

**Fix.** Store the running total on the sample (or store both), and
compute the delta against the previous total. `_support_at`'s docstring
claims "the running total is reconstructed by the caller" — no caller
reconstructs it.

---

## B5 — Erasure is incomplete, and the report will lie

**Severity: critical (compliance). Design defect that lands with Stage 3.**

`MemoryErasureService` removes memory facts, evidence and vectors. Once
Learning exists it will also hold, per erased customer:

- `observations` with `content_refs` pointing at their conversations
- `cluster_members` recording their participation
- `candidates` drafted from clusters they are in
- `gaps` derived from questions they asked

None of it is reached by the current erasure path. `ErasureReport` is
documented as "the response somebody forwards to a regulator" — after
Stage 3 it would be a document asserting complete deletion while four
tables still hold the subject's data.

Separately and already live: the erasure endpoint returns
`working_memory_cleared=False` as a **hardcoded literal**. Working memory
is keyed by conversation, and erasure has no way to enumerate a customer's
conversations, so their live working memory survives until its TTL.

**Fix.**
1. Erasure emits `memory.subject_erased`; **Learning owns a consumer that
   purges its own artifacts** and reports counts back. Same rule as
   everywhere else — each context erases its own store.
2. `ErasureReport` becomes a composite that is not complete until every
   registered context has acknowledged. An erasure that cannot confirm all
   participants must fail loudly, not report success.
3. Working memory: resolve the customer's open conversations and clear
   them, or accept the TTL and say so in the response instead of returning
   a hardcoded `False`.

---

## B6 — The decay sweep cannot reach the corpus

**Severity: high. Scalability.**

`memory_decay_batch_size = 500`, hourly. That is 12,000 facts per day.

| Corpus | Time for one full pass |
|---|---|
| 100k facts | 8 days |
| 1M facts | 83 days |
| 10M facts | **2.3 years** |

Retrieval sorts and filters on the **stored** `confidence` column. At any
serious scale that column is years stale, which means dormant facts rank
as fresh and the entire decay model is decorative. The Memory Platform
document's claim that "a missed run costs only staleness in the stored
number" is true for one run and false for a permanent shortfall.

**Fix — pick one, and it is an architectural choice, not a tuning knob:**

- **(a) Compute on read.** Confidence is already a pure function of
  evidence and `now`. Readers apply the recency factor at query time; the
  stored column becomes a cache used only for coarse filtering. Correct at
  any scale, costs a little query complexity.
- **(b) Size the sweep to the corpus.** Batch derived from row count and
  target pass interval, not a constant. Simple, but makes the worker's
  cost a function of the largest tenant.

(a) is the right answer for a ten-year platform. The current design chose
neither.

---

## B7 — The decay sweep starves small tenants

**Severity: high. Scalability, and a repeat of a documented incident.**

```python
.order_by(MemoryFact.confidence_computed_at.nulls_first()).limit(limit)
```

Global ordering, no tenant fairness. A tenant with ten million facts owns
every batch until its own backlog clears, and every other company's memory
stops ageing entirely.

This is the exact shape of the relay-starvation incident this repository
already documents: the oldest rows monopolised every claim, one row
reached 14,586 attempts, and healthy events behind it were never claimed.
That incident produced a documented lesson and this code repeats its
shape.

**Fix.** Claim round-robin by company — a bounded slice per tenant per
run — or partition the sweep by company hash across workers. Add the test
that would have caught it: two tenants, one enormous, assert the small one
is still swept.

---

## B8 — The verifier does not exist, and three documents claim it does

**Severity: critical (correctness of a safety claim).**

Stage 1's design specifies step 6, `AnswerVerifier`, and argues at length
that it is "what makes official knowledge wins true" and that ranking
alone "is the version that eventually quotes a price the AI inferred from
a conversation."

It was never built. Stage 1 shipped retrieval only.

So today, "Official Knowledge always wins" is a **rank boost and a class
filter on retrieval** — nothing checks that the generated answer is
actually supported by what was retrieved, and nothing blocks a
restricted-class claim that cites no authoritative source. The
`company-intelligence-engine.md`, `knowledge-memory-intelligence.md` and
`intelligence-platform.md` documents all describe the guarantee as
enforced.

**Fix.** Either build the verifier before Learning starts producing
knowledge suggestions, or amend all three documents to state plainly that
authority is currently advisory. The second is cheap and honest; the first
is the actual product. What is not acceptable is shipping Stage 3 while
three architecture documents assert a safety property that does not exist.

---

## B9 — Citations are not reproducible

**Severity: high.**

`knowledge_article_versions` was designed in Stage 1 and not built.
`knowledge_chunks.article_id` points at the mutable article, and Stage 1's
own "as shipped" section records this as deliberate for stage 1.

The consequence for Stage 3 is larger than it was for Stage 1. Learning
will produce suggestions whose evidence is "these conversations cited this
article", and contradiction detection compares memory against published
knowledge. Both reference an article that can change underneath them. When
a customer disputes what they were told in March, the platform cannot
produce what the article said in March.

**Fix.** Versioning must land before Learning cites knowledge. It is
already designed; it is a table, a pointer and a chunk FK move.

---

## B10 — `retrieval_traces` does not exist, and gap detection depends on it

**Severity: medium.**

Stage 3's Tier D gap scan is specified as "retrievals that returned
nothing" plus "agent answers with no citation". The first requires
`retrieval_traces`, which was designed in Stage 1 and never built. There
is currently no record of what retrieval returned for any query.

**Fix.** Build traces with the verifier (B8) — they are the same
instrument — or drop the retrieval half of gap detection from Stage 3's
scope and say so.

---

## Ownership collisions

### O1 — `embeddings` has three writers across three contexts

**Severity: critical. It falsifies the platform's central invariant.**

| Owner type | Written by | Context |
|---|---|---|
| `KNOWLEDGE_CHUNK` | `EmbeddingService` | Knowledge |
| `MEMORY_FACT` | *declared, unassigned* | Memory |
| Cluster centroids | *proposed* | Learning |

"`MemoryManager` is the only writer of memory" is **already false for
memory vectors**, and the AST guard does not catch it because the guard
watches memory repositories, not the embeddings table. A memory fact's
vector is memory-derived data written by a Knowledge-context service.

**Fix.** Reclassify `embeddings` as a **shared Indexing capability** owned
by no domain context — infrastructure, like the outbox — with a
per-`owner_type` writer registry and a guard extension asserting that only
the registered writer for an owner type may write it. The alternative
(each context owns its own vector table) costs a second HNSW index and is
worse.

### O2 — Conversation outcome has two owners

Learning's `Observation.outcome` carries `{resolved, reopened, escalated,
handling_seconds, first_contact_resolution, csat}`. Reporting already
derives the same facts into `ConversationDailyStats`.

If Learning computes FCR one way and Reporting another, the platform has
two answers to "was this resolved on first contact?" — and Learning's
beliefs are built on a definition Reporting contradicts. This is precisely
the **A3 defect** the ownership audit already records (two answers to "what
is the SLA target", consequence: zero SLA clocks platform-wide).

**Fix.** Outcome is derived **once**, by Conversation or Reporting, and
published. Learning consumes it and never recomputes. One resolver, the
way `effective_autopilot_confidence_threshold` is one resolver.

### O3 — Suggestion state will live in two tables

Learning owns `candidates` with `dedupe_key` and suppression state.
Knowledge owns `knowledge_suggestions` with review state. Rejection in
Knowledge must suppress in Learning, so suppression exists on both sides
of an event boundary and will drift.

**Fix.** `candidates` are **transient pre-emission drafts** and are
deleted at emission. Learning owns a separate, small `suppressions` table
keyed by `dedupe_key`, written only by the feedback consumer from
`knowledge.suggestion_reviewed`. One row, one meaning, one writer.

### O4 — Workflow auto-close pollutes the outcome signal

The Workflow Engine can close conversations. A workflow-closed
conversation reads as `resolved` to Learning, which will conclude that
whatever preceded it worked.

This is a **second feedback loop**, structurally distinct from the AI one
and not covered by the `is_ai_generated` mitigation, because a workflow is
not AI.

**Fix.** `outcome` must carry *who* resolved it — human, AI, workflow,
timeout — and `outcome_quality` must exclude or discount non-human
closures. The ownership timeline already records this; Learning must read
it rather than trusting `status`.

---

## Event defects

### E1 — The evidence graph has a cycle

Stage 3 lists `memory.fact_recorded` as an input ("closing the loop,
detecting contested facts"), and Learning emits `MemoryCandidateDetected`,
which causes `memory.fact_recorded`. That is a cycle, and nothing in the
design forbids evidence being derived from it.

**Fix — state it as an invariant and test it:** *evidence may originate
only from source-of-truth events (conversation, message, CSAT, workflow,
CRM, knowledge). Learning's own downstream effects may be read for
reconciliation and may never become evidence.* The evidence graph must be
acyclic, and an import-boundary test can assert that the observation
assembler never consumes a `memory.*` topic.

### E2 — No settle window before a conversation is eligible

`csat.submitted` arrives minutes to days after `conversation.resolved`.
Learning creates the observation on resolution and attaches outcomes
later, but nothing prevents the hourly cluster evaluation from consuming
an observation whose CSAT has not landed. `outcome_quality` then enters
confidence as neutral for conversations that were in fact rated badly.

**Fix.** An observation is not **eligible** until a settle window has
elapsed (CSAT expiry is already 14 days — the window should be a
configured shorter horizon, not the full token life) or every expected
signal has arrived. Eligibility is a column, not a timestamp comparison
scattered across queries.

### E3 — Memory trusts the caller's claim of corroboration

`EvidenceSourceType.AGENT_STATEMENT` and `SYSTEM_RECORD` corroborate, and
corroboration is what lifts a fact past `CANDIDATE`. Nothing validates
that an `AGENT_STATEMENT` actually carries an `agent_id`, or that a
`SYSTEM_RECORD` came from a connected system.

The prompt-injection defence rests entirely on this classification being
honest. A buggy Learning extractor that labels customer-derived
observations `AGENT_STATEMENT` defeats it silently.

**Fix.** Validate at the door: `AGENT_STATEMENT` requires `agent_id`;
`SYSTEM_RECORD` requires a source id. Both are one-line checks in
`validate_fact_shape` and both close the hole structurally rather than by
trusting the caller.

---

## Feedback loops — the full inventory

The brief names one loop. There are four.

| # | Loop | Closed by |
|---|---|---|
| 1 | Learning → Memory → Reasoning → AI → Conversation → Learning | `is_ai_generated` excluded from evidence; `is_ai_assisted` admitted but non-corroborating; human-authored floor per cluster |
| 2 | Workflow auto-close → false `resolved` → Learning | **Open — O4** |
| 3 | Replay → recency refresh → confidence inflation | **Open — B1** |
| 4 | Redelivered contradiction → demotion → suppression → re-detection | **Open — B2** |

Loop 1 is genuinely well-defended, and the defence is measurable rather
than hoped for: the human-authored fraction is a number on a dashboard.

Loops 2, 3 and 4 are open, and 3 is the one the brief specifically asked
to be proven impossible.

**Why confidence cannot inflate, once B1–B4 are fixed:**

Every term in the confidence function is recomputed from rows that carry a
uniqueness constraint:

- `support_count`, `distinct_customer_count`, `distinct_agent_count` —
  `COUNT` over `memory_evidence`, unique on
  `(fact_id, source_type, source_id)`. A replay inserts nothing.
- `contradiction_count` — after B2, `COUNT` over a table with the same
  shape. A replay inserts nothing.
- `outcome_quality` — supplied by the caller and **currently overwritable
  upward without limit**. After O2 it is derived once by Reporting from
  CSAT rows that are themselves unique per conversation.
- `recency` — after B1, only advances when an evidence row is actually
  inserted.

The invariant to state and test: **every input to confidence is a pure
function of rows protected by a uniqueness constraint, and no code path
may advance a time-based input without inserting one of those rows.**
That is provable and testable. Today it is false in two places.

---

## Scalability

| Concern | Status |
|---|---|
| Event throughput | Outbox relay is `SKIP LOCKED` and scales with workers. Fine |
| Decay throughput | **Blocked — B6** |
| Tenant fairness | **Blocked — B7** |
| Replay | Idempotent for evidence; **not for contradictions (B2) or recency (B1)** |
| Retries | Circuit breaker exists on the knowledge index sweep; **memory decay has none** — a permanently failing fact is reclaimed forever |
| Distributed workers | `SKIP LOCKED` on Postgres, correct |
| Re-indexing | Model migration path exists (Stage 1); memory has no equivalent for a `pipeline_version` bump |
| Large tenants | HNSW is one global index; partitioning designed, not built. `memory_confidence_samples` grows at one row per fact per sweep and is the fastest-growing table in the platform |
| **Multi-region** | **Not addressed anywhere.** Outbox + RabbitMQ + one Postgres is single-region by construction. A ten-year horizon needs at least a stated position |
| Eventual consistency | Reader-visible: a fact recorded is immediately visible, but its confidence is only correct after the next sweep — which B6 makes years. Compute-on-read fixes both |

**Additional finding:** the memory decay sweep has no `max_attempts`
circuit breaker. The knowledge index sweep has one, added specifically
because of the relay incident. A fact that fails to recompute is reclaimed
on every run forever.

---

## AI safety

| Path | Structural mitigation | Status |
|---|---|---|
| Hallucination | Verifier blocks uncited claims | **Absent — B8** |
| Prompt injection → Knowledge | Human approval, always | Sound |
| Prompt injection → Memory | Corroboration ceiling caps belief at `CANDIDATE` | Sound **but forgeable — E3** |
| Memory poisoning by repetition | `distinct_customer`/`distinct_agent` weighting; corroboration ceiling | Sound |
| Memory poisoning by replay | — | **Absent — B1** |
| Knowledge poisoning | Only humans publish; no automatic path exists | Sound |
| Customer isolation | `company_id` on every table; required argument on every retrieval method; cross-tenant test | Sound. Verified at 10k rows / 20 tenants with zero leakage |
| Cross-tenant clustering | Company-scoped clustering | Designed, unbuilt — must be tested on day one |
| Replay attacks | Evidence uniqueness | Partial — see B1, B2 |
| **Autonomous action** | `Policy.AUTOMATION_EXECUTION` | **`NOT_YET_ENFORCED`.** Nothing governs an AI taking an action with side effects |

The isolation story is genuinely strong. The hallucination story is
currently a promise.

---

## Observability

Required per context, and what exists:

| Context | Health | Metrics | Lag | Queue depth | Failure rate | Confidence dist. |
|---|---|---|---|---|---|---|
| Knowledge | `/knowledge/index-status` | partial | ✗ | ✗ | ✓ (failed articles) | n/a |
| Memory | `/memory/status` | counts by tier/state | ✗ | ✗ | ✗ | ✗ |
| Learning | `/intelligence/health` (designed) | designed | designed | designed | designed | designed |
| Reasoning | **nothing** | ✗ | ✗ | ✗ | ✗ | n/a |
| AI Engine | `/reports/ai/usage` | ✓ | n/a | n/a | ✗ | n/a |
| Policy | decision log | ✓ | n/a | n/a | n/a | n/a |

**Two systemic gaps.**

**Consumer lag and queue depth are measured nowhere.** Every context runs
consumers and sweeps; none reports how far behind it is. `SchedulerRun`
records that a run happened and its counters, which answers "did it run"
and not "is it keeping up" — and B6 is precisely a not-keeping-up failure
that no dashboard would show.

**Confidence distribution is not exposed by Memory**, despite being the
number that says whether the platform is learning anything. A histogram
per tier, plus the count of facts whose `confidence_computed_at` is older
than the target interval, would have made B6 visible immediately.

---

## Extensibility

| Capability | Verdict |
|---|---|
| Voice, meetings, phone | **Works.** The Observation envelope is source-kind agnostic; a call becomes a transcript with segments. One rule to enforce: no `if source.channel ==` inside Learning |
| Email | Works. Already a channel |
| ERP, CRM | Works as both an evidence source and a `SYSTEM_RECORD` corroborator. The "queried, never remembered" rule for systems of record is stated and correct |
| MCP tools | **Partially.** Tool calls land at Reasoning step 5, which is designed but explicitly not specified. The gap is not the plumbing — it is that a tool call has side effects and nothing governs them |
| **Autonomous agents** | **No.** This is the one that needs redesign |

**On autonomous agents.** The architecture governs what may be *said*
(`AI_ENGAGEMENT`, the verifier, Voice Constraints) and what may be
*believed* (Memory's contract). It governs almost nothing about what may
be *done*. `AUTOMATION_EXECUTION` and `AUTO_CLOSE` both answer
`NOT_YET_ENFORCED`, and there is no concept of an action's blast radius,
reversibility, or an approval threshold that scales with it.

An agent that can issue a refund needs a different safety model than one
that can draft a reply, and the current architecture cannot express the
difference. This is not a blocker for Stage 3 — Learning takes no actions
— but it is the largest unaddressed area on a ten-year horizon, and it
should be reserved now the way Company Behavior was, before something
improvises it.

---

## What is genuinely sound

Not everything is a finding, and the freeze should record what holds:

- **Tenant isolation.** Required arguments rather than conventions,
  verified at scale with zero leakage across 20 tenants.
- **The exclusive-writer invariant**, and the AST guard that keeps it —
  with the O1 exception, which is a scope gap in the guard rather than a
  flaw in the idea.
- **Evidence-based confidence** as a design. The arithmetic has four
  defects; the decision to compute rather than ask a model is right and is
  what makes the defects *findable*.
- **Two-axis lifecycle.** It survives the re-observation case that breaks
  a single chain, and the derived display label keeps the product
  vocabulary intact.
- **Forgetting separated from erasure.** The distinction is correct and
  load-bearing; B5 is an incompleteness in the fan-out, not an error in
  the model.
- **Knowledge is never written automatically.** Held consistently across
  all three stages with no exception path.
- **The Observation envelope** as the extensibility seam. It is the right
  abstraction and it is why voice and ERP need no redesign.

---

## Required before implementation

**Must fix — code, ~2–3 days:**

1. B1 — gate `last_observed_at` and revival on `evidence_added`
2. B2 — contradictions become rows with a uniqueness constraint
3. B3/B4 — real contradiction delta; store running totals on samples
4. E3 — validate corroborating source types at the door
5. B7 — tenant-fair claiming in the decay sweep, plus a `max_attempts` cap

**Must fix — architecture, decide before building Stage 3:**

6. B6 — compute-on-read for confidence, or corpus-sized sweeps
7. O1 — `embeddings` reclassified as shared Indexing with a writer registry
8. O2 — one owner for conversation outcome
9. O3 — transient candidates, separate suppression table
10. O4 — outcome carries its resolver; non-human closure discounted
11. E1 — evidence-graph acyclicity as a tested invariant
12. E2 — an explicit settle window and eligibility column
13. B5 — erasure fan-out to Learning, composite report, working memory

**Must fix — honesty, ~1 hour:**

14. B8 — build the verifier, or amend three documents to stop claiming a
    guarantee that does not exist. This one is not optional in either
    direction

**Should fix before Learning cites knowledge:**

15. B9 — knowledge versioning
16. B10 — retrieval traces, or descope gap detection

**Should reserve now:**

17. Autonomous action safety — blast radius, reversibility, approval
    thresholds. Reserved, not designed, the way Company Behavior was

**Should state:**

18. A multi-region position, even if the answer is "single region, and
    here is what would change"

---

## Verdict

**NOT READY.**

The architecture is sound in its bones — the context boundaries hold, the
exclusive-writer invariant is real, tenant isolation is verified, and the
decision to compute confidence from evidence rather than ask a model is
what made four arithmetic defects findable at all. None of the seventeen
findings requires rethinking the shape of the platform.

But four of them are live defects in shipped code, one falsifies the
foundational property this design is built on, and one lets an
architecture document assert a safety guarantee the code does not
implement. Building the Learning Platform on top would multiply every one
of them by its event rate, and B1 in particular turns a high-volume
learning pipeline into a confidence inflator.

Fix items 1–14. Then this is approved.

---

## See also

- [Memory Platform](./memory-platform.md)
- [Company Intelligence Engine](./company-intelligence-engine.md)
- [Intelligence Platform](./intelligence-platform.md)
- [Knowledge, Memory and Intelligence](./knowledge-memory-intelligence.md)
- [Domain ownership audit](./domain-ownership.md)
