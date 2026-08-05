# Learning Platform — Implementation Charter

**This is a contract, not a design.** The design is
[intelligence-platform.md](./intelligence-platform.md); where the two
disagree, this wins, and where this is silent the design applies.
Approved by
[architecture-freeze-review-2.md](./architecture-freeze-review-2.md).
Stage 1 (semantic retrieval) and Stage 2 (Memory, stabilised) are built.

**MUST / MUST NOT are binding.** A violation is a defect, not a style
preference, and every one below is enforced by a test named in §10.

---

## 1. Responsibility

Learning observes populations of finished work, detects what recurs, and
**proposes**. It answers *"what should we come to believe?"* — never
*"what should we say now?"*, which is Reasoning.

One sentence: **evidence in, candidates out, nothing written outside its
own tables.**

## 2. Problems it solves

Recurring issues, effective and ineffective responses, escalation
triggers, terminology and seasonal patterns — *detected* instead of
noticed. Contradiction between published Knowledge and remembered
observation. Knowledge gaps: questions the corpus cannot answer. Trends,
with statistical honesty. And turning all of it into reviewable
candidates.

## 3. Problems it is forbidden to solve

MUST NOT: answer a conversation · rank retrieval at request time · decide
what may be said or done · write Memory, Knowledge, Conversations,
Customers, CRM or Workflow · publish anything to Knowledge without a human
· call a model on the customer request path · learn across tenants.

There is no configuration flag for any of these.

## 4. Who may call Learning

| Caller | May |
|---|---|
| Operators (HTTP, `intelligence.read`) | Read observations, clusters, candidates, trends, gaps, runs |
| Operators (`intelligence.manage`) | Dismiss a candidate, replay a window |
| Nobody else | — |

No context calls Learning synchronously. Learning is reached by **events
and by humans**, never by another service's request path.

## 5. Who may never depend on Learning

**Reasoning, Memory, Knowledge, Conversations, Policy, AI Engine,
Workflow, Billing.** None may import from `application/learning/` or block
on a Learning result. If Learning is down, every one of them MUST continue
unaffected. Enforced by an import-boundary test.

## 6. Events in

| Event | Used for |
|---|---|
| `conversation.resolved` / `.closed` | Primary observation trigger |
| `message.persisted` | Turn features, AI provenance |
| `conversation.autopilot_replied` | Marking evidence platform-generated |
| `conversation.sla_breached` / `.warning` / `.transferred` | Failure signals |
| `csat.submitted` | Outcome quality; settles an observation |
| `knowledge.article_published` / `.retired` | Contradiction trigger |
| `knowledge.suggestion_reviewed` | Suppression feedback |
| `workflow.executed` | Automation-outcome correlation |
| `memory.subject_erased` | **Erasure participation** |
| `erp.record_synced`, CRM equivalents | External outcomes |

`memory.fact_*` MUST NOT be consumed as evidence (see §10, I-4).

## 7. Events out

| Event | Consumer | Automatic? |
|---|---|---|
| `MemoryCandidateDetected` | Memory's own consumer → `MemoryManager.record()` | **Yes** |
| `KnowledgeSuggestionProposed` | Knowledge's own consumer → review queue | **Never** |
| `ContradictionDetected` | Memory's own consumer → `MemoryManager.contradict()` | Yes |
| `TrendDetected` | Analytics, Notifications | Advisory |
| `KnowledgeGapDetected` | Knowledge review, Analytics | Advisory |
| `LearningRunCompleted` | Observability | — |

`RecommendationCreated` is **dropped** from scope. By the
population/instance test it is either Reasoning's output or a gap under
another name; it will not ship empty.

## 8. Tables Learning owns

`observations` · `observation_features` · `clusters` · `cluster_members` ·
`candidates` · `suppressions` · `trends` · `gaps` · `learning_runs`

All carry `company_id`, and all are **derived and rebuildable** from
source events — the property that makes `pipeline_version` rollback real.

## 9. Tables owned elsewhere

`memory_facts`, `memory_evidence`, `memory_contradictions`,
`memory_confidence_samples` → **Memory**.
`knowledge_articles`, `knowledge_chunks`, `knowledge_suggestions`,
`suggestion_reviews` → **Knowledge**.
`conversations`, `messages`, `customers`, `agents` → their contexts.
`embeddings` → **shared indexing infrastructure**; Learning may register
`CLUSTER_CENTROID` in `domain/embedding_owners.py` and write only that.

Learning MUST NOT write any of the above except its registered owner type.

## 10. Invariants

| # | Invariant | Enforced by |
|---|---|---|
| **I-1** | No cluster, candidate or query spans tenants | Isolation test asserting no `cluster_members` row's company differs from its cluster's |
| **I-2** | Learning writes only §8 tables | AST guard, modelled on `test_memory_manager_is_the_only_writer.py` |
| **I-3** | Nothing reaches Knowledge without human approval | No code path from Learning to `knowledge_articles` |
| **I-4** | The evidence graph is acyclic | Import-boundary test: the observation assembler consumes no `memory.*` topic |
| **I-5** | `is_ai_generated` content is never evidence; `is_ai_assisted` never corroborates | Assembler test with both flag combinations |
| **I-6** | Outcome comes from `domain/conversation_outcome.derive`, never recomputed | Import-boundary test |
| **I-7** | Only `settled` observations are eligible for clustering | Eligibility is a column; test asserts unsettled rows are never claimed |
| **I-8** | Candidates are transient; suppression lives only in `suppressions` | Test asserts a candidate is deleted at emission |
| **I-9** | A candidate clears **floors** before any score is considered | Floors tested independently of scoring |
| **I-10** | Every emitted trend survives multiple-testing correction and ≥2 windows | Statistics tests with synthetic noise |

## 11. Failures that MUST stop the pipeline

| Failure | Stop means |
|---|---|
| Tenant isolation violation (I-1) | Halt, alarm, do not continue |
| `Policy.KNOWLEDGE_LEARNING` denied | Stop for that company. A recorded decision, not an error |
| `pipeline_version` mismatch | Drop that observation — a mixed-version cluster is meaningless |
| Learning budget exhausted | Stop escalating to models, continue tiers 0–2. Sampling is reported, never silent |
| Erasure participation cannot complete | Surface as **incomplete erasure**; never swallow |

## 12. Failures that MAY be retried

Provider timeouts and rate limits · broker redelivery · database
deadlocks · transient embedding failures · a single observation failing
extraction.

All retries are bounded by a `max_attempts` circuit breaker with the error
recorded on the row. **A permanently failing row MUST stop being claimed**
and stay visible — the relay-starvation and decay-sweep lesson, which this
codebase has now learned twice.

## 13. Idempotent operations

| Operation | Idempotency key |
|---|---|
| Observation assembly | `(source_id, pipeline_version)` unique |
| Evidence attachment (in Memory) | `(fact_id, source_type, source_id)` unique |
| Cluster membership | `(cluster_id, observation_id)` unique |
| Candidate emission | `dedupe_key` unique among un-emitted |
| `MemoryCandidateDetected` consumption | Memory's own dedupe; replay adds nothing |
| `ContradictionDetected` consumption | `memory_contradictions` unique per source |
| Suppression | `dedupe_key` upsert |

Every consumer MUST be safe to replay. At-least-once delivery is the
contract, not an edge case.

## 14. Eventually consistent

Cluster membership · detection quality · trends · gaps · candidate
emission · the memory fact a candidate becomes. Acceptable lag:
observation ≤ 5 min after settle; clustering ≤ 1 h; trends ≤ 24 h.

**Never eventually consistent:** tenant isolation, policy decisions,
erasure. Those are immediate or they are failures.

## 15. Metrics — is Learning healthy?

- Consumer lag per topic (seconds behind head)
- Queue depth per consumer
- Run success rate; failures per run
- Circuit-breaker population (rows past `max_attempts`)
- Budget burn vs. ceiling, per company
- Observations assembled / hour vs. conversations resolved / hour

## 16. Metrics — is Learning useful?

- Candidate yield: candidates per 1,000 observations
- **Approval rate** of emitted suggestions (the honest quality signal)
- Gap → published article conversion
- Memory facts reaching `CONFIRMED` or better with a Learning origin
- Clusters that ever cross a floor (a corpus that never does is noise)

## 17. Metrics — is Learning dangerous?

The set that must be on a dashboard **before** phase 4.

- **Feedback ratio** — share of evidence originating from
  `is_ai_generated` or `is_ai_assisted` content. Rising means the platform
  is learning from itself.
- **Re-proposal rate** — suppressed `dedupe_key`s proposed again.
  Non-zero means suppression is broken and reviewers will stop reading.
- **Cross-tenant assertion failures** — must be exactly zero, alarmed.
- **Unsettled-consumption rate** — observations clustered before settling.
- **Trend false-positive rate** — trends emitted that fail their next
  window. Rising means the correction is not working.
- **Agent-attributed fact volume** — employment-adjacent data;
  disproportionate growth is a governance signal.

## 18. Assumptions relied upon

From **Stage 1**: `embeddings` + HNSW with company pre-filtering (recall
1.000, zero cross-tenant, p50 9.2 ms) · `EmbeddingProvider` /
`VectorIndex` ports · RRF fusion · chunking.

From **Stage 2**: `MemoryManager` is the sole writer · evidence is
mandatory and is a pointer · confidence computed from evidence, never
model-claimed · corroboration ceiling caps belief-by-repetition ·
two-axis lifecycle · erasure ≠ forgetting · `conversation_outcome.derive`
is the single outcome definition, carrying `resolved_by` and `settled`.

Platform: transactional outbox → RabbitMQ · Policy Engine fails closed ·
SQLite-portable repositories · `company_id` on every table.

**If any of these change, this charter is void and must be re-approved.**

## 19. Assumptions deferred

| Deferred | Consequence for Stage 3 |
|---|---|
| **B8** verifier | Authority is advisory; Learning MUST NOT claim otherwise |
| **B9** knowledge versioning | Contradiction detection cites a mutable article. MUST land before Learning cites versions |
| **B10** retrieval traces | Gap detection ships with the *agent-answered-without-citing* half only, and says so |
| Multi-region | Single region, deliberately |
| Autonomous action safety | Out of scope; Learning takes no actions |
| Experience causal machinery | Stratified comparison with confounder controls is its own stage |

## 20. Implementation phases

| Phase | Delivers | Gate to next |
|---|---|---|
| **1. Observe** | Consumers, Observation envelope, tiers 0–2 features, `observations`, erasure participation, health metrics (§15) | Extraction cost measured; lag within §14 |
| **2. Detect (shadow)** | Clustering, floors, detection scoring, trends, gaps. Candidates **written, not emitted** | An operator reviews what it *would* have proposed and agrees |
| **3. Emit to review** | `KnowledgeSuggestionProposed`, `KnowledgeGapDetected`, suppression feedback | Approval rate acceptable; re-proposal rate zero |
| **4. Emit to Memory** | `MemoryCandidateDetected`, `ContradictionDetected`, behind a per-company switch, default off | §17 dashboard live first |

Phase 2 is not optional. It is the phase that answers *is this any good?*
before a single memory row is written by it.

**Kill switch:** `Policy.KNOWLEDGE_LEARNING`, which already exists and
fails closed. Turning it off stops observation at the gate, per company,
without a deploy.

**No backfill.** Learning starts the day it is switched on. A windowed
replay is available through the API for a company that asks.
