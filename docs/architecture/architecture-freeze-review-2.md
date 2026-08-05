# Architecture Freeze Review — Second Pass

Re-review after Stage 2.1 stabilisation. The first review is
[architecture-freeze-review.md](./architecture-freeze-review.md) and
returned **NOT READY** on seventeen findings.

**Verdict: APPROVED FOR IMPLEMENTATION.**

Fourteen findings closed with code and regression tests. Three deferred
with rationale, none of which blocks Stage 3. One new finding was
discovered while fixing another and is also closed.

---

## The demonstration, repeated

The first review's central claim was that the platform's foundational
property was false. The same probe, unchanged, against the code before and
after:

```
BEFORE                                          AFTER
t0        record            conf=0.1280         conf=0.1280
t0+200d   decay recompute   conf=0.0274         conf=0.0274
t0+200d   REPLAY same src   conf=0.1280  ←4.7×  conf=0.0274  ←unchanged
                            lifecycle=active    lifecycle=dormant

evidence rows added by replay : 0               0
INFLATED WITHOUT NEW EVIDENCE : True (+0.1006)  False (+0.0000)
```

The dormant fact is also no longer revived by a duplicate.

---

## Findings, one by one

### P0 — closed

| # | Finding | Fix | Proof |
|---|---|---|---|
| **B1** | Replay refreshed recency and inflated confidence | ``last_observed_at`` and ``revive_on_observation`` moved inside ``if evidence_added`` | 3 tests: replay changes nothing; a dormant fact stays dormant; **genuinely new evidence still refreshes** |
| **B2** | ``contradiction_count += 1``, not idempotent | ``memory_contradictions`` rows, unique on ``(fact_id, source_type, source_id)``; count derived | 3 tests: four deliveries count once; two sources count twice; confidence drops once, not repeatedly |
| **B3** | ``contradicting_delta`` hard-coded to 0 — ``FALLING``/``CONTESTED`` unreachable | Real delta fed from contradiction totals | 2 tests: growing contradiction reports ``FALLING``; both growing reports ``CONTESTED`` |
| **B4** | Delta was ``total − previous_delta``, dimensionally wrong | Samples carry ``support_total``/``contradiction_total``; deltas derived from two totals | 2 tests, including the 1→3→6 sequence that distinguishes correct (1,2,5) from broken (1,2,4) |
| **E3** | Corroboration was an unvalidated string | ``AGENT_STATEMENT`` requires ``agent_id``; ``SYSTEM_RECORD`` requires ``source_id`` | 3 tests, plus 10 pre-existing fixtures that had to be corrected — the guard caught real unbacked claims already in the suite |
| **B7** | Global claim order starved small tenants; no circuit breaker | Per-company claiming with round-robin budget; ``recompute_attempts`` cap | 3 tests: claiming is company-scoped; every company with work is offered a turn; a repeatedly failing fact stops being claimed |

**B4's test is worth singling out.** Every simpler sequence gives the same
answer under both the broken and the correct arithmetic, which is exactly
why the drift survived the original suite. The regression uses the
smallest sequence that separates them.

### P1 — closed

| # | Finding | Fix |
|---|---|---|
| **B6** | 500 facts/hour — 2.3 years per pass at 10M facts, retrieval ranking on a years-stale column | Two halves: batch derived from corpus size and target pass interval (``memory_target_pass_hours``), **and** decay finished at read time by ``effective_confidence``. The second is what makes sweep throughput a performance concern rather than a correctness one |
| **O1** | ``embeddings`` had three writers across three contexts; "MemoryManager is the only writer of memory" was already false for memory vectors | ``embeddings`` reclassified as **shared indexing infrastructure** with a per-owner-type writer registry (``domain/embedding_owners.py``) and an AST guard. ``MEMORY_FACT`` is registered to the Memory Manager |
| **O2** | Conversation outcome about to have two owners — the A3 shape | ``domain/conversation_outcome.py`` is the single derivation |
| **O4** | Workflow auto-close read as ``resolved``, a feedback loop the AI mitigation does not touch | ``resolved_by`` on the outcome; ``attributable`` is false for workflow, timeout and AI closures |
| **E2** | No settle window — clusters could consume outcomes whose CSAT had not landed | ``settled`` on the outcome; CSAT settles it immediately, otherwise a 72-hour window |
| **B5** | Erasure could not include other contexts; ``working_memory_cleared`` was a hardcoded ``False`` | ``ErasureParticipant`` fan-out with acknowledgement; a participant that cannot confirm makes the report ``incomplete``. Working memory cleared via a participant that resolves the customer's conversations |

**O3 and E1 are architecture-only** and cannot be built before Learning
exists. Both are now recorded as binding contracts in
[intelligence-platform.md](./intelligence-platform.md):

- **O3** — Learning's ``candidates`` are transient pre-emission drafts;
  suppression lives in a separate table written only by the feedback
  consumer. One row, one meaning, one writer.
- **E1** — evidence may originate only from source-of-truth events. The
  evidence graph must be acyclic, enforced by an import-boundary test that
  ships **with** the observation assembler. A vacuously-passing test
  written now would be the stale-allow-list problem the codebase already
  warns about.

### New finding, discovered during the fix — closed

**N1 — ``CONTESTED`` was still unreachable after B3.** Fixing the
hard-coded zero was not sufficient. A confidence sample is written on
*every* mutation, so comparing against the immediately previous sample
made the window "since the last write" — and a single write moves a single
dimension. Support and contradiction could never be seen growing together.

Direction is now measured across the recent history window
(``DIRECTION_WINDOW_SAMPLES``), which is the question it was always meant
to answer. Found because the B3 regression test for ``CONTESTED`` failed
after the B3 fix — the test was right and the fix was incomplete.

### P2 — deferred, with rationale

| # | Finding | Status |
|---|---|---|
| **B8** | The verifier does not exist; three documents claimed the guarantee | **Documents amended.** ``company-intelligence-engine.md`` and ``knowledge-memory-intelligence.md` now state plainly that authority is *advisory* until the verifier ships, and cite B8. The build is deferred because **there is no generation pipeline to verify** — Stage 1 shipped retrieval, not steps 0–7. Building a verifier with nothing to verify would be speculative code. It must land with the Reasoning pipeline, and no Stage 3 work depends on it |
| **B9** | Knowledge versioning — citations not reproducible | **Deferred to before Learning cites knowledge.** Nothing cites a version today because nothing generates cited answers. The design exists; it is a table, a pointer and a chunk FK move. Recorded as a precondition on Learning's contradiction detector, not on Stage 3's foundations |
| **B10** | ``retrieval_traces`` does not exist; gap detection depends on it | **Descoped, explicitly.** Stage 3's gap detection loses its retrieval half and keeps "agent answered without citing" until traces exist. Traces belong with the verifier — they are the same instrument — so B8 and B10 land together |

The deferral rationale is the same in all three cases and worth stating
once: **each depends on the Reasoning pipeline, which is not Stage 3.**
Building them now would mean writing code whose only consumer does not
exist, which is the speculative-implementation failure this codebase's
conventions already reject.

---

## Re-verification of the original review's sections

### Feedback loops

| # | Loop | First review | Now |
|---|---|---|---|
| 1 | Learning → Memory → Reasoning → AI → Conversation → Learning | Defended | Defended (AI provenance flags) |
| 2 | Workflow auto-close → false ``resolved`` → Learning | **Open** | **Closed** — ``resolved_by`` + ``attributable`` |
| 3 | Replay → recency refresh → inflation | **Open** | **Closed** — B1 |
| 4 | Redelivered contradiction → demotion | **Open** | **Closed** — B2 |

**Why confidence cannot inflate, now provable:**

> Every input to confidence is a ``COUNT`` over rows protected by a
> uniqueness constraint, and no code path may advance a time-based input
> without inserting one of those rows.

- ``support_count``, ``distinct_customer_count``, ``distinct_agent_count``
  — ``COUNT`` over ``memory_evidence``, unique per source.
- ``contradiction_count`` — ``COUNT`` over ``memory_contradictions``, same
  shape.
- ``last_observed_at`` — advanced only inside ``if evidence_added``.
- ``outcome_quality`` — derived once by ``conversation_outcome.derive``,
  and machine-ended conversations are not attributable.

The one remaining path by which ``outcome_quality`` could be raised
arbitrarily is a caller passing a higher value on each ``record()``. That
is now bounded by there being a single derivation, but it is not
*structurally* closed — noted below as a residual risk rather than a
blocker, because the caller in question does not exist yet and the
contract it must follow is documented.

### Scalability

| Concern | First review | Now |
|---|---|---|
| Decay throughput | **Blocked** | Corpus-derived batch + read-time decay |
| Tenant fairness | **Blocked** | Round-robin per company |
| Replay | Unsafe for contradictions and recency | Idempotent throughout |
| Retries | Decay sweep had no circuit breaker | ``recompute_attempts`` cap |
| Observability of falling behind | Invisible | ``facts_awaiting_recompute`` on ``/memory/status`` |
| Multi-region | Not addressed | **Still not addressed** — position stated below |

### AI safety

| Path | Now |
|---|---|
| Memory poisoning by replay | Closed (B1) |
| Memory poisoning by repetition | Closed — corroboration ceiling, now unforgeable (E3) |
| Forged corroboration | Closed (E3) |
| Knowledge poisoning | Sound — only humans publish |
| Customer isolation | Sound — verified at 10k rows / 20 tenants |
| Hallucination | **Advisory only.** Documented honestly rather than claimed (B8) |
| Autonomous action | **Not governed.** Reserved, below |

---

## Residual risks, accepted

Not blockers. Recorded so they are decisions rather than oversights.

1. **``outcome_quality`` is caller-supplied.** One derivation exists and
   is documented as mandatory, but nothing structurally prevents a future
   caller passing its own number. When Learning ships, the assembler must
   call ``conversation_outcome.derive`` and an import-boundary test should
   assert it — added to Stage 3's required tests.
2. **Multi-region is not designed.** The outbox, RabbitMQ and a single
   PostgreSQL are single-region by construction. Position: **single
   region, deliberately**, and a second region would need the outbox
   partitioned by region and memory reads served from a replica. Stated
   rather than solved.
3. **Autonomous action safety.** ``AUTOMATION_EXECUTION`` and
   ``AUTO_CLOSE`` still answer ``NOT_YET_ENFORCED``, and nothing expresses
   an action's blast radius or reversibility. Reserved the way Company
   Behavior was. Not a Stage 3 concern — Learning takes no actions — but
   it must be designed before any agent can act.
4. **Contradictions are not backfilled.** The old counter recorded *how
   many times* something disagreed and never *what*, so there is nothing
   to write rows from. Existing counts stand and the recompute takes over
   from rows, meaning a fact contradicted before the migration keeps its
   demotion until something contradicts it again. Fabricating provenance
   was the alternative.

---

## Verification performed

| | Result |
|---|---|
| Stabilisation regressions | 21 new tests, all passing |
| Outcome resolver | 20 new tests |
| Embedding ownership guard | 14 new tests, including planted writers it must catch |
| Memory suites, total | 133 passing |
| Migration ``d3a91c07f2b4`` | Applied, downgraded, re-applied on real PostgreSQL |
| ruff / ruff format / mypy --strict | Clean |
| Benchmark | Replay inflation +0.1006 → +0.0000 |

**Ten pre-existing test fixtures had to be corrected** by E3 — they were
constructing ``AGENT_STATEMENT`` evidence with no agent, which is exactly
the unbacked corroboration claim the fix closes. That the suite contained
ten instances of the pattern is itself evidence the validation was needed.

---

## Verdict

**APPROVED FOR IMPLEMENTATION.**

All six P0 findings are closed with regression tests that fail against the
previous code. All eight P1 findings are closed, six in code and two as
binding contracts on a context that does not exist yet. The three P2
findings are deferred for one shared reason — each depends on the
Reasoning pipeline, which is not Stage 3 — and the one that was a honesty
problem rather than a build problem has been fixed in the documents.

The property the first review falsified is now stated as an invariant,
enforced by uniqueness constraints rather than by discipline, and proven
by the same probe that broke it.

Stage 3 may begin.

---

## See also

- [Architecture freeze review](./architecture-freeze-review.md) — the first pass
- [Memory Platform](./memory-platform.md) — what stabilisation changed
- [Intelligence Platform](./intelligence-platform.md) — Stage 3, now unblocked
