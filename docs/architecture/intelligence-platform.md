# Intelligence Platform

Turning evidence into candidates. The context that observes, reasons about
populations, and recommends — and writes into nobody else's store.

Stage 3 of the Company Intelligence Engine. **Architecture only; nothing
here is built.** Stage 1 (semantic retrieval) and Stage 2 (the Memory
Platform) are.

---

## Challenges to the brief

Eight, each with a verdict. The rest of the document assumes these are
settled.

### 1. "Intelligence" now names three different things — **rename this one**

The brief asks for four contexts: Memory, Intelligence, Reasoning, AI
Engine. The split is right. The **name is not**, and the collision is with
this project's own documents:

| Where | "Intelligence" means |
|---|---|
| `knowledge-memory-intelligence.md` | The layer that answers *"what should we do now?"* — which the brief now calls **Reasoning** |
| `company-intelligence-engine.md` | The whole programme, all stages |
| This brief | The offline learning context |

Three meanings, one word, in one architecture. This is the same class of
problem the KMI document already spent a section fixing — Intelligence
versus the Policy Engine both claiming "decides" — and it was worth fixing
there for the same reason it is worth fixing here: the first thing that
happens is somebody writes reasoning code in the learning context because
that is where intelligence lives.

**Recommendation:** this bounded context is **Learning**.

- **Company Intelligence Engine** — the programme. Unchanged.
- **Learning** — evidence → candidates. Population-scale, asynchronous.
- **Reasoning** — question → grounded answer. Instance-scale, synchronous.
- **AI Engine** — model access.

"The intelligence layer" survives as informal shorthand for Learning +
Reasoning together, the way "the billing side" is understood without being
a context.

This document uses **Learning** from here on. If the name
"Intelligence Platform" is kept anyway, the cost is real and worth naming
explicitly: `knowledge-memory-intelligence.md` must be rewritten so
"Intelligence" means the offline context there too, and the online layer
needs a name in that document as well. Half-renaming is worse than either
choice.

### 2. The pipeline is four schedulers drawn as one chain — **decomposed**

The brief's pipeline reads as a line:

```
Observation → Feature Extraction → Classification → Clustering →
Evidence Aggregation → Confidence → Suggestion → Review → Promotion
```

Those stages have wildly different triggers and cadences, and drawing them
as one chain hides that:

| Stage | Actually triggered by | Cadence |
|---|---|---|
| Observation, extraction | A conversation resolving | Per event |
| Clustering | Enough new observations | Incremental, then periodic |
| Trend detection | A time window closing | Windowed |
| Contradiction detection | **Knowledge being published** | Per event, different source |
| Gap detection | Retrieval finding nothing | Per event, different source |
| Candidate + suggestion | A cluster crossing a floor | Periodic |

Contradiction detection in particular is not downstream of observation at
all — it fires when *Knowledge* changes, and pretending it is stage six of
a chain that starts at a conversation would mean it only ran when
conversations happened. Decomposed into four cadence tiers below.

### 3. Learning must not have its own belief model — **added**

Stage 2 already computes confidence from evidence:
`domain/memory_confidence.py`, weighted for breadth over volume, with
per-type half-lives and a corroboration ceiling. If Learning computes a
second confidence, the two drift, and a fact means different things
depending on which produced it.

But Learning does need something Memory's model cannot express, and the
distinction is real:

| Question | Owner | Score |
|---|---|---|
| *Is this pattern actually there?* | **Learning** | Detection quality |
| *Is the claim it implies true?* | **Memory** | Belief confidence |

A cluster can be statistically solid and imply a false claim; a true claim
can be detected from a thin cluster. Learning computes cohesion, sample
size, effect size against a baseline and stability across windows, and
hands over **evidence**. Memory computes belief from that evidence, using
the model it already owns.

Two scores, two owners, one direction of flow, and no second belief model.

### 4. The feedback loop is the existential risk, and it is not on the list

Learning observes conversations. Some of those conversations were answered
by Autopilot, using knowledge and memory that Learning produced. Learn
from those without discrimination and the platform starts confirming its
own output: confidence rises on no new information, and the loop is
invisible because every counter looks healthy.

This is the failure that ends systems of this shape, and it is absent from
the brief.

**Mitigation, and it already exists in the schema.**
`ConversationService` stamps `message_metadata.is_ai_generated` (Autopilot
composed and sent it, no human involved) and `is_ai_assisted` (an agent's
own reply whose draft came from AI). Billing already reads them. Learning
must too:

- `is_ai_generated` content is **excluded from evidence** entirely. It is
  the platform's own output; treating it as observation is circular by
  construction.
- `is_ai_assisted` content is **admitted but not corroborating** — a human
  reviewed and sent it, which is real signal, but the wording came from
  the platform and must not vote on its own phrasing.
- Every cluster records its **human-authored fraction**, and a cluster
  below a floor is not eligible to produce a candidate.

This makes the outcome measurable rather than hoped for: the fraction is a
number on a dashboard, and a rising one is the early warning.

### 5. Trend detection will produce confident nonsense without correction

Scanning hundreds of topics for a change every week is hundreds of
hypothesis tests. At p<0.05, twenty topics produce one "significant"
finding from noise alone — and a platform that surfaces it will be
believed, because it arrived with a number attached.

Three requirements, none of which is optional:

1. **Multiple-testing correction** (Benjamini–Hochberg) across every
   comparison in a scan, not per comparison.
2. **Stability**: a trend must hold across at least two consecutive
   windows before it is emitted. Regression to the mean kills most
   one-window findings.
3. **Baseline-relative, seasonally aware**: "up 30% on last week" during
   Ramadan is a calendar fact, and the Memory Platform already models
   `seasonal_pattern` facts that a comparison should consult.

### 6. AI Engine should be demoted to model access — **recommended, with a migration**

Today `AiService` owns both provider access *and* ten capabilities'
prompts — reply suggestion, summary, sentiment, tagging, next best action.
Those prompts are **reasoning**: what to ask the model, and how to check
the answer. Leaving them in the model-access layer means Reasoning's rules
live in the context that is supposed to know nothing about conversations.

Target:

- **AI Engine** — providers, completion, embeddings, rate limits, cost
  metering. Takes text, returns text or vectors. Knows nothing about
  conversations, knowledge or memory.
- **Reasoning** — what to ask, what to ground it in, and whether the
  answer is acceptable.

This is a direction, not a prerequisite. Stage 3 does not require it, and
doing it as a side quest would mean touching ten shipped capabilities for
a boundary nothing is currently violating in a harmful way. It becomes
worth doing when the verifier lands, because that is when Reasoning starts
having rules of its own.

### 7. A context that owns nothing cannot exist — **clarified**

The brief says Learning owns none of Knowledge, Memory, Conversations,
Customers, CRM, Workflow or AI replies. All correct. But it must own its
own artifacts or it has no state to be incremental with, no way to be
idempotent, and no way to roll back a bad pipeline version.

Learning owns: observations, clusters, candidates, trends, gaps and
detection runs. All of them **derived and rebuildable** from source events
— which is what makes `pipeline_version` rollback real rather than
aspirational. Same clarification the Behavior reservation needed.

### 8. Most conversations must never reach a model

"Feature Extraction → Classification" reads as an LLM call per
conversation. At any real volume that is the entire cost of the platform,
it scales linearly with traffic, and it has no ceiling.

**A tiered ladder, where each tier only escalates what it cannot settle:**

| Tier | Cost | Handles |
|---|---|---|
| 0 — Structural | Free | Outcome, timings, channel, reopen, escalation, CSAT, ownership |
| 1 — Lexical | Negligible | Language, entity extraction, trigram topic match against known topics |
| 2 — Embedding | Cheap | Intent clustering, similarity to existing clusters (Stage 1's index) |
| 3 — Small model | Metered | Only what tier 2 could not assign to a cluster |
| 4 — Strong model | Expensive | Only cluster summarisation and candidate drafting — per *cluster*, not per conversation |

The design target is that the strong model runs **once per candidate**,
not once per conversation. Everything else is arithmetic, vectors and a
cheap model.

---

## The four contexts

```
┌──────────────────────────────────────────────────────────────────────┐
│                          SOURCES OF TRUTH                            │
│  Conversations · Customers · Knowledge · Workflow · CRM · Billing    │
│  They emit events. They do not know Learning exists.                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  domain events (outbox → RabbitMQ)
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  LEARNING                          population scale · asynchronous   │
│  ──────────────────────────────────────────────────────────────────  │
│  Observes many conversations. Detects what recurs. Proposes.         │
│                                                                      │
│  Owns:  observations · clusters · candidates · trends · gaps · runs  │
│  Never writes: Memory, Knowledge, Conversations, Customers           │
│  Emits:  MemoryCandidateDetected · KnowledgeSuggestionProposed       │
│          TrendDetected · ContradictionDetected · KnowledgeGapDetected│
└───────┬───────────────────────────────────────────┬──────────────────┘
        │ events                                    │ events
        ▼                                           ▼
┌───────────────────────┐                 ┌──────────────────────────┐
│  MEMORY               │                 │  KNOWLEDGE               │
│  MemoryManager is the │                 │  Humans approve.         │
│  only writer. Its own │                 │  Its own consumer turns  │
│  consumer turns a     │                 │  a proposal into a       │
│  candidate into a     │                 │  review-queue row.       │
│  fact. Automatic.     │                 │  Never automatic.        │
└───────────┬───────────┘                 └────────────┬─────────────┘
            │ read-only                                │ read-only
            └────────────────┬───────────────────────-─┘
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  REASONING                          instance scale · synchronous     │
│  ──────────────────────────────────────────────────────────────────  │
│  Answers one message. Gate → understand → plan → retrieve → ground   │
│  → generate → verify. Owns no durable data but its traces.           │
└───────────────────────────────┬──────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  AI ENGINE                                                           │
│  Providers · completion · embeddings · rate limits · cost metering.  │
│  Takes text, returns text or vectors. Knows nothing else.            │
└──────────────────────────────────────────────────────────────────────┘
```

### Where each starts and ends

| | **Learning** | **Reasoning** |
|---|---|---|
| Subject | A *population* of conversations | *One* conversation |
| Timing | Asynchronous, minutes to nightly | Synchronous, inside a reply |
| Question | "What should we come to believe?" | "What should we say now?" |
| Output | Candidates and suggestions, for review | An answer, for a customer |
| Being wrong costs | A bad row in a queue | A wrong answer to a customer |
| Latency budget | Hours | Milliseconds |
| Owns | Its own derived artifacts | Traces only |

That last row is the test that settles most boundary arguments: if getting
it wrong reaches a customer directly, it is Reasoning.

**AI Engine** starts at "here is text, give me a completion" and ends at
the response. It never knows what the text was about.

**Memory** starts at `MemoryManager.record()` and ends at erasure. It
never decides what is worth remembering — Learning does, and Memory
decides how it is *kept*.

---

## Ownership matrix

In the style of `domain-ownership.md`, so the two read together.

| Business fact | Owner | Consumers | Exposed as |
|---|---|---|---|
| What was observed in one conversation | **Learning** | Learning only | `observations` |
| Which conversations form a pattern | **Learning** | Learning, review UI | `clusters` |
| That a pattern is worth believing | **Learning** | Memory (via event) | `candidates` |
| That something is changing over time | **Learning** | Analytics, alerts | `trends` |
| That a question has no good answer | **Learning** | Knowledge review | `gaps` |
| Detection quality of a pattern | **Learning** | Review UI | Cohesion, effect size, n |
| **Whether a claim is believed** | **Memory** | Everyone | Computed `confidence` |
| **Whether a statement is official** | **Knowledge** | Everyone | Approved versions |
| Whether a suggestion is approved | **Humans** | — | `suggestion_reviews` |
| What may be said to this customer | **Policy Engine** | Reasoning | `PolicyDecision` |
| The answer to this message | **Reasoning** | Conversation | Response + citations |
| Which model, and what it cost | **AI Engine** | Billing | Provider + usage events |

**One rule, applied everywhere:** *Learning writes only its own artifacts
and emits events. Each destination context owns the consumer that writes
its own store.* That is what keeps `MemoryManager` the only writer of
memory while Learning is the thing that discovered the fact.

---

## The event model

### Inputs

Learning subscribes; it never calls. Sources do not know it exists, which
is what lets a new source be added without touching them.

| Event | From | Learning uses it for |
|---|---|---|
| `conversation.resolved` / `.closed` | Conversation | The primary observation trigger |
| `message.persisted` | Conversation | Turn-level features, AI provenance |
| `conversation.autopilot_replied` | AI | Marking evidence as platform-generated |
| `conversation.sla_breached` / `.warning` | SLA | Failure-side signal |
| `conversation.transferred` | Conversation | Escalation patterns |
| `csat.submitted` | CSAT | Outcome quality |
| `memory.fact_recorded` / `.contradicted` | Memory | Closing the loop, detecting contested facts |
| `knowledge.article_published` / `.retired` | Knowledge | **Contradiction detection trigger** |
| `workflow.executed` | Workflow | Which automations precede which outcomes |
| `erp.record_synced` / CRM equivalents | ERP/CRM | External outcome signals |
| `customer.updated` | Customer | Segment changes that invalidate a stratum |

Everything arrives through the existing transactional outbox → RabbitMQ
topic exchange. Learning adds consumers; it changes no publisher.

### The normalised Observation envelope — the extensibility seam

Learning must never see a channel. It consumes one shape, and every source
adapts into it:

```
Observation
├── observation_id, company_id, pipeline_version
├── source: { kind: conversation|ticket|call|email|form|api,
│             id, channel, occurred_at }
├── participants: { customer_id?, agent_ids[], ai_involved: bool }
├── content_refs: [ message_id | segment_id | document_id ]   ← pointers
├── outcome:  { resolved, reopened, escalated, handling_seconds,
│               first_contact_resolution, csat? }
├── provenance: { human_authored_fraction, ai_generated_fraction }
└── features:  { language, intent?, entities[], topics[], sentiment_arc? }
```

**Voice, email and calls need no redesign** because they produce this same
envelope: a call becomes a transcript with segments, an email thread
becomes turns, an ERP ticket becomes a source kind. The extensibility
promise reduces to one enforceable rule:

> The first `if source.channel == ...` inside Learning is the change that
> breaks it. Channel belongs to the adapter, never to the pipeline.

`content_refs` are **pointers, never copies** — the same rule the Memory
Platform already enforces for evidence, for the same reason: a copy here
is a second store of customer content with its own retention, and it turns
erasure into a text-editing problem.

### Outputs

Learning emits. It never writes another context's store.

| Event | Consumed by | Effect |
|---|---|---|
| `MemoryCandidateDetected` | **Memory**'s own consumer | Calls `MemoryManager.record()` |
| `KnowledgeSuggestionProposed` | **Knowledge**'s own consumer | Creates a review-queue row |
| `ContradictionDetected` | **Memory**'s own consumer | `MemoryManager.contradict()` |
| `TrendDetected` | Analytics, Notifications | A chart, an alert |
| `KnowledgeGapDetected` | Knowledge review, Analytics | "Write this next" |
| `RecommendationCreated` | Notifications, agent UI | Advisory only |
| `LearningRunCompleted` | Observability | Counters, cost |

### The line that decides automatic from reviewed

| Destination | Automatic? | Why |
|---|---|---|
| **Memory** | **Yes** | Memory *is* observation. Its contract already expresses uncertainty as confidence, refuses facts without evidence, and caps belief-by-repetition at `CANDIDATE` without corroboration. A candidate clearing the evidence floor becoming a fact adds no new risk — Stage 2 made this safe. |
| **Knowledge** | **Never** | Knowledge is what the company *states*. Only a human publishes. |

This is the whole reason Stage 2 came first. Because Memory's contract
constrains belief structurally, Learning can be allowed to write into it
through an event without a review queue for every inferred language
preference — and the prompt-injection path stays closed by the
corroboration ceiling rather than by a reviewer's attention.

---

## The pipeline, by cadence

Four tiers, four triggers. Not one chain.

### Tier A — Per observation (event-driven, seconds)

```
conversation.resolved
   → gate: Policy.KNOWLEDGE_LEARNING          (refuse → stop, recorded)
   → assemble Observation envelope
   → tier 0/1 features: outcome, timings, language, entities  (free)
   → tier 2: embed summary, assign to nearest cluster          (cheap)
   → tier 3 only if unassigned: small-model intent             (metered)
   → persist observation, update cluster membership incrementally
```

Incremental assignment matters: a nightly full re-cluster is O(n²) and
becomes the platform's largest job. Assignment against existing centroids
via Stage 1's vector index is O(log n) per observation, and a periodic
re-fit corrects drift.

### Tier B — Per knowledge change (event-driven, seconds)

```
knowledge.article_published
   → embed the new version
   → retrieve semantically near memory facts and clusters
   → for each near item: does it contradict?    (small model, bounded set)
   → emit ContradictionDetected
```

Not downstream of conversations at all. Publishing a refund policy must
demote every learned fact that disagrees *whether or not* a conversation
happened that day.

### Tier C — Periodic (hourly)

```
for each cluster that gained members since last run:
   → recompute cohesion, sample size, breadth, human-authored fraction
   → evaluate detection floors
   → if it clears: draft candidate  (strong model, once per candidate)
   → emit MemoryCandidateDetected / KnowledgeSuggestionProposed
```

### Tier D — Windowed (nightly / weekly)

```
→ trend scan across topics, with BH correction and a stability requirement
→ gap scan: retrievals that returned nothing; agent answers with no citation
→ cluster re-fit and merge
→ candidate expiry
```

### The stage the brief omits

Between "Suggestion Creation" and "Human Review" there is a step with no
name in the brief and a large effect on whether the platform is usable:
**suppression**.

A rejected suggestion that keeps being re-proposed every week is the
default behaviour of any clustering pipeline whose rejections are terminal
states. Learning must consume `knowledge.suggestion_reviewed` and apply
the structured rejection reason — `FACTUALLY_WRONG` suppresses the dedupe
key permanently; `POORLY_WRITTEN` keeps the evidence and re-drafts;
`ALREADY_COVERED` records a citation edge and never re-proposes. Without
this, review queue fatigue kills the feature in month two.

---

## Confidence, without asking a model

Learning computes **detection quality** only. Every input is measurable
and none is a model's opinion — the platform's existing habit of parsing a
`CONFIDENCE:` line is explicitly not reused here, because a model's
self-assessment is uncorrelated with whether a pattern is real.

```
detection_quality = f(
    cohesion,                 # mean intra-cluster similarity vs nearest other cluster
    sample_size,              # members, per stratum
    breadth,                  # distinct customers · distinct agents  (not volume)
    effect_size,              # outcome delta vs the stratum baseline
    stability,                # agreement across consecutive windows
    human_authored_fraction,  # the anti-feedback-loop term
    contradiction_pressure,   # near items that disagree
)
```

**Floors before scores.** A candidate is not emitted because its score is
high; it is emitted because it clears every floor *and* scores well. Floors
are hard: minimum members, minimum distinct customers, minimum distinct
agents, minimum human-authored fraction, minimum stability. A score can be
argued with; a floor cannot, and the floors are what keep one loud agent
from becoming company policy.

**Stratification before comparison.** Outcomes are compared within tier,
intent, channel and language — never pooled. Pooling is how an approach
that wins in every segment loses overall, and Stage 2's `fact_key` already
makes the stratum part of a fact's identity.

**Belief is Memory's.** Learning hands over evidence — supports, distinct
counts, outcome quality — and Memory's existing model produces the number
anybody acts on.

---

## Learning's own store

All of it derived and rebuildable from source events. That property is
what makes `pipeline_version` rollback real: drop and replay.

| Table | Holds | Notes |
|---|---|---|
| `observations` | One row per analysed unit | Unique per `(source_id, pipeline_version)` — replayable |
| `observation_features` | Extracted features | Versioned payload, like `memory_facts.attributes` |
| `clusters` | Detected patterns | Centroid embedding, stratum, quality metrics |
| `cluster_members` | Membership + similarity | Carries the AI-provenance flags |
| `candidates` | Proposed facts/suggestions before emission | `dedupe_key`, suppression state |
| `trends` | Detected changes | Window, statistic, corrected p-value, stability |
| `gaps` | Unanswerable questions | Clustered by topic, volume-ranked |
| `learning_runs` | Versioned, idempotent runs | Unique per `(company, run_type, version, window)` |

Every table carries `company_id`, and **clustering is company-scoped
absolutely** — a cluster spanning tenants is not a degraded result, it is a
cross-tenant data leak wearing a statistics costume. This is the single
highest-severity failure mode in the whole context.

`observations` unique per `(source_id, pipeline_version)` is the same
idempotency shape `conversation_insights` was designed with in Stage 1:
a bad extraction prompt is rolled back by bumping the version and
re-running, with both generations present and comparable.

---

## Service map

```
application/learning/
  ObservationAssembler      events → normalised envelope
  FeatureExtractor          tiered ladder, escalating only what it must
  ClusterService            incremental assignment; periodic re-fit
  EvidenceAggregator        supports, breadth, outcomes, provenance
  DetectionScorer           pure: floors + detection quality
  CandidateService          drafting, dedupe, suppression, expiry
  TrendDetector             windowed, corrected, stability-gated
  ContradictionDetector     triggered by knowledge publication
  GapDetector               unanswered questions
  LearningBudgetService     sampling and back-pressure under a cost ceiling

domain/
  learning_observation.py   pure: the envelope and its invariants
  learning_detection.py     pure: floors, cohesion, effect size, stability
  learning_identity.py      pure: cluster and candidate dedupe keys
  learning_statistics.py    pure: BH correction, baselines, significance
```

`DetectionScorer` and `learning_statistics.py` being **pure** is
load-bearing: statistical rules that could reach a database would be rules
whose answer depended on when you asked them, and these are the rules that
decide what a company comes to believe.

---

## Data flow, end to end

```
A conversation resolves
   │
   ├─ Policy.KNOWLEDGE_LEARNING refuses  → stop. Recorded, explainable.
   │
   ▼
Observation assembled (pointers, no content copied)
   │  AI-generated content excluded from evidence here, not later
   ▼
Features extracted (tier 0→3, escalating only what it must)
   │
   ▼
Assigned to a cluster, or seeds a new one
   │
   ▼  [hourly]
Cluster clears its floors?  ── no ──→ wait. Most never clear.
   │ yes
   ▼
Candidate drafted (strong model, once)
   │
   ├──→ MemoryCandidateDetected ──→ Memory's consumer ──→ MemoryManager.record()
   │         automatic, because Memory's contract constrains belief
   │
   └──→ KnowledgeSuggestionProposed ──→ Knowledge's consumer ──→ review queue
             never automatic; a human publishes

Meanwhile, independently:
   knowledge.article_published ──→ ContradictionDetected ──→ MemoryManager.contradict()
   retrieval finds nothing     ──→ KnowledgeGapDetected  ──→ "write this next"
   window closes               ──→ TrendDetected (corrected, stable)
   suggestion reviewed         ──→ suppression applied to the dedupe key
```

---

## Background workers

Consumers, each its own process and compose service, per `event-bus.md`:

| Consumer | Binds | Does |
|---|---|---|
| `learning-observation` | `conversation.resolved`, `.closed` | Tier A |
| `learning-signals` | `csat.submitted`, `conversation.sla_*`, `.transferred` | Attaches outcomes to observations |
| `learning-contradiction` | `knowledge.article_published`, `.retired` | Tier B |
| `learning-feedback` | `knowledge.suggestion_reviewed` | Suppression |

Celery beat:

| Task | Cadence |
|---|---|
| `evaluate_clusters` | Hourly — Tier C |
| `detect_trends` | Nightly — Tier D |
| `detect_gaps` | Nightly |
| `refit_clusters` | Weekly |
| `expire_candidates` | Daily |

The split is the same one Stage 1 made and for the same reason: consumers
do the cheap, transactional half; sweeps do the metered half, where a
bounded batch, retries and back-pressure are what a slow vendor requires.

---

## APIs

Read and review only. Nothing here writes memory or knowledge.

```
GET    /intelligence/observations/{conversation_id}   what was extracted, and by which version
GET    /intelligence/clusters                          patterns, ranked by quality
GET    /intelligence/clusters/{id}                     members, stratum, metrics, provenance mix
GET    /intelligence/candidates                        pending, with their floors and scores
POST   /intelligence/candidates/{id}/dismiss           suppress without a knowledge review
GET    /intelligence/trends                            corrected, stability-gated
GET    /intelligence/gaps                              ranked by volume × tier × escalation
GET    /intelligence/runs                              versions, coverage, cost, failures
POST   /intelligence/replay                            re-run a version over a window (Owner)
GET    /intelligence/health                            queue depth, budget burn, feedback ratio
```

`GET /intelligence/health` is the one an operator opens first, and
`feedback ratio` — the share of evidence originating from AI-generated
content — is the number that says whether the platform is learning from
the world or from itself.

Permissions: `intelligence.read` (Admin, Owner), `intelligence.manage`
(Owner) for dismissal and replay. Not granted to Agent: these are
population-level views, and an agent's questions are answered by Memory's
own endpoints.

---

## Risks

Ordered by how badly each ends, not by likelihood.

| Risk | Consequence | Mitigation |
|---|---|---|
| **Cross-tenant clustering** | One company's patterns built from another's conversations. Catastrophic and silent | `company_id` on every table and every query; an isolation test that asserts no cluster ever spans tenants |
| **Feedback loop** | The platform confirms its own output; confidence rises on no information | Exclude `is_ai_generated` evidence, discount `is_ai_assisted`, floor the human-authored fraction, and put the ratio on the health endpoint |
| **False trends at scale** | Confident nonsense, believed because it has a number | BH correction, two-window stability, seasonal baselines |
| **Cost explosion** | Per-conversation model calls scale with traffic, uncapped | Tiered ladder; strong model once per *candidate*; per-company budget with sampling that degrades honestly rather than stopping |
| **Review queue fatigue** | Nobody opens it by month two | Floors before scores; structured rejection feeding suppression; candidate expiry |
| **Prompt injection via learning** | Poisoned memory | Already closed by Stage 2: customer-authored content alone cannot corroborate, and belief is capped at `CANDIDATE` without it |
| **Bad pipeline version** | Wrong facts recorded at scale | `pipeline_version` on every artifact, replay endpoint, and Memory rows carry the version that produced them |
| **Privacy surface** | Learning reads every conversation | Gated by `Policy.KNOWLEDGE_LEARNING`; pointers not copies; erasure already cascades through Memory evidence |
| **Silent underperformance** | It runs, finds nothing, nobody notices | Coverage and candidate-yield on the health endpoint; a run that produced nothing is reported, not merely logged |

---

## Migration strategy

Four phases. Each is independently valuable and independently reversible,
and the platform is deployable throughout — the sequencing rule
`CLAUDE.md` already sets.

**Phase 1 — Observe only.** Consumers, envelope, tier 0–2 features,
`observations`. No clustering, no candidates, no events out. Value on its
own: conversation analytics nothing currently produces, and a real
measurement of extraction cost before anything is spent at scale.

**Phase 2 — Detect, in shadow.** Clustering, floors, detection scoring,
trends and gaps. Candidates are **written but not emitted**. An operator
reviews what the platform *would* have proposed. This is the phase that
answers "is this any good?" before a single memory row is written by it,
and it is the phase most teams skip.

**Phase 3 — Emit to review.** `KnowledgeSuggestionProposed` and
`KnowledgeGapDetected` go live; humans see suggestions. Memory candidates
still shadowed. Knowledge stays human-approved forever, so this phase
carries no automatic-write risk at all.

**Phase 4 — Emit to Memory.** `MemoryCandidateDetected` goes live behind a
per-company switch, default off, with the feedback ratio and candidate
yield already on a dashboard from phase 2.

**The kill switch is `Policy.KNOWLEDGE_LEARNING`**, which already exists in
the design and fails closed. Turning it off stops observation at the gate
for a company, without a deploy, and the refusal is recorded like any
other policy decision.

**No backfill.** Existing conversations are not replayed into observations
on first deploy. Inventing a history the platform did not observe is a
guess presented as a record — the same reasoning `routing_decisions` and
the service directory already apply — and a corpus assembled from a
year of conversations under a brand-new extraction version is the worst
possible input to a system whose whole value is that its beliefs are
traceable. Learning starts from the day it is switched on, and a
deliberate, windowed replay is available through the API for a company
that wants one.

---

## What this design does not do

- **It does not write memory or knowledge.** It emits; each destination
  context owns its own writer. `MemoryManager` remains the only writer of
  memory.
- **It does not decide what may be said.** That is the Policy Engine.
- **It does not answer conversations.** That is Reasoning.
- **It does not call models directly.** That is the AI Engine.
- **It does not learn across tenants**, and there is no configuration flag
  for it.
- **It does not promote anything to Knowledge automatically**, ever.

---

## Binding contracts from the freeze review

Two findings could not be built before this context exists. They are
recorded here as requirements on Stage 3 rather than as advice, because
the first review's lesson was that an architecture document asserting
something the code does not do is worse than one that says nothing.

**O3 — suggestion state must not live in two tables.** Learning's
``candidates`` are **transient pre-emission drafts** and are deleted at
emission. Suppression lives in a separate, small ``suppressions`` table
keyed by ``dedupe_key``, written only by the feedback consumer from
``knowledge.suggestion_reviewed``. One row, one meaning, one writer. The
alternative — suppression state on both sides of an event boundary — will
drift, and the drift is invisible until a rejected suggestion reappears.

**E1 — the evidence graph must be acyclic.** Evidence may originate only
from source-of-truth events: conversation, message, CSAT, workflow, CRM,
knowledge. Learning's own downstream effects — ``memory.*`` topics — may
be read for reconciliation and **may never become evidence**. An
import-boundary test asserting that the observation assembler consumes no
``memory.*`` topic must ship *with* the assembler; writing it now would
pass vacuously, which is the stale-allow-list problem
``test_ownership_is_the_only_writer.py`` already warns about.

**Plus one carried forward.** ``outcome_quality`` must come from
``domain/conversation_outcome.derive`` and never be recomputed locally —
that module is now the single definition, and a second one would
reintroduce the A3 shape the freeze review flagged as O2. An
import-boundary test should assert the assembler calls it.

**And one descope.** Gap detection loses its retrieval half until
``retrieval_traces`` exists (B10). Stage 3 detects gaps from "an agent
answered without citing" only, and says so rather than shipping a detector
that silently sees half the gaps.

---

## Open questions

Named rather than guessed at.

- **Where clusters live physically.** Centroids in `embeddings` (Stage 1's
  polymorphic table already anticipates a `CLUSTER` owner type) or in
  Learning's own table? The first reuses the HNSW index; the second keeps
  the contexts separate. Leaning toward reuse, because a second vector
  index is a second thing to tune.
- **Whether `RecommendationCreated` belongs here at all.** A recommendation
  aimed at *one* conversation is Reasoning's output by the population/
  instance test. A recommendation aimed at a manager ("write this
  article") is a gap or a suggestion under another name. There may be no
  third case, in which case the event should be dropped rather than
  shipped empty.
- **Experience-tier causal claims.** Stage 2 built the tier and its
  guardrails; the machinery that actually establishes an effect —
  stratified comparison with confounder controls — is the largest single
  piece of statistical work here, and it may deserve its own stage rather
  than being one detector among ten.

---

## See also

- [Knowledge, Memory and Intelligence](./knowledge-memory-intelligence.md) — the domain boundaries
- [Memory Platform](./memory-platform.md) — stage 2, built
- [Company Intelligence Engine](./company-intelligence-engine.md) — stage 1, built
- [Policy Engine](./policy-engine.md)
- [Domain Event Bus](./event-bus.md)
- [Domain ownership audit](./domain-ownership.md)
