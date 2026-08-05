# Learning Platform — Phase 2 Review

**Scope reviewed:** pattern detection as built, against the phase 2 brief
and the [Learning Platform Charter](./learning-platform-charter.md).
**What was built:** [learning-platform-phase-2.md](./learning-platform-phase-2.md).

Written to be disagreed with. Where phase 2 departs from the charter it
says so with the reason; where a requirement is met by construction
rather than by test, it says which.

---

## 1. Scope compliance

The brief listed eight objectives and seven prohibitions.

| Objective | Built |
|---|---|
| Conversation clustering | `domain/learning_clustering.py` + `LearningClusteringService` |
| Pattern detection | Clusters *are* the patterns; `feature_summary` is what each is about |
| Trend detection | `domain/learning_trend.py` — rising, declining, recurring, seasonal, spike |
| Anomaly detection | `domain/learning_anomaly.py` — five kinds |
| Duplicate detection | Three levels, two of them schema constraints |
| Cluster lifecycle | Five states, advanced by time as well as by membership |
| Cluster confidence | Multiplicative, computed from evidence |
| Cluster health metrics | `GET /intelligence/metrics` |

| Prohibited | Present? |
|---|---|
| Create Memory facts | **No** — guarded by AST test |
| Create Knowledge suggestions | **No** |
| Write to Memory | **No** — no memory repository is constructed anywhere in Learning |
| Write to Knowledge | **No** |
| Trigger Human Review | **No** — the API is read-only, no queue exists |
| Call the Reasoning Engine | **No** — guarded: no AI provider is even *imported* |
| Publish candidate events | **No** — guarded, and measured: the outbox is empty after an analysis |

The publish prohibition is guarded two ways because it is the one most
likely to be broken by a well-meaning change. Statically, no `publish`,
`send_task`, `notify` or `dispatch` call exists in any Learning module.
Behaviourally, an integration test drains the outbox, runs an analysis,
and asserts the outbox is still empty — the outbox being the only way
anything leaves this platform.

Every required cluster field is present: `cluster_id`, `company_id`,
`observation_ids` (as membership rows), `centroid`, `feature_summary`,
`language_distribution`, `confidence`, `stability_score`, `first_seen`,
`last_seen`, `pipeline_version`.

## 2. Charter compliance

| # | Invariant | Status | Enforced by |
|---|---|---|---|
| **I-1** | No cluster spans tenants | **Enforced** | Signature is company-scoped, so identical vocabulary in two tenants produces different signatures; every repository method takes `company_id`; tested with two companies on identical text |
| **I-2** | Learning writes only its own tables | **Enforced** | AST guard, extended to phase 2's four tables |
| **I-3** | Nothing reaches Knowledge without a human | **Vacuous** | No path from Learning to Knowledge exists. Real in phase 3 |
| **I-4** | Evidence graph acyclic | **Enforced** | No consumer added; the sweeps read observations and clusters only |
| **I-5** | AI content is never evidence | **Inherited** | Phase 2 reads phase 1's features, which already exclude it |
| **I-6** | Outcome from the single resolver | **Inherited** | Phase 2 copies outcome columns; it derives nothing |
| **I-7** | Only settled observations are eligible | **Enforced** | `state = 'ready'` in the query, tested |
| **I-8** | Candidates transient, suppression separate | **Not applicable** | No candidates in phase 2 |
| **I-9** | Floors before scores | **Enforced** | Separate functions; tested that a 6-member single-customer cluster stays `forming` |
| **I-10** | Correction and ≥2 windows | **Enforced** | BH across the family; provisional until a second window agrees; tested against 40 noisy series and 300 uniform p-values |

## 3. Departures from the charter

### 3.1 Lexical clustering, not tier-2 embeddings

The charter's phase-2 row says "tiers 0–2 features"; phase 2 clusters on
tiers 0–1.

This is the same clause phase 1 narrowed, and the argument has got
stronger rather than weaker. The charter requires clusters to be
**deterministic** and **replay-safe**. An embedding centroid is neither
across a provider or model change: re-embedding the same corpus produces
different vectors, therefore different clusters, with no version bump and
no way to distinguish a change in the corpus from a change in the
encoder. Lexical similarity over stored tokens is reproducible for as
long as the text is.

It is also universal — the platform default is
`EMBEDDING_PROVIDER=disabled`, so an embedding-based phase 2 would simply
not run on most installations.

**The cost is real and is not hidden.** Lexical similarity cannot see
that "cannot log in" and "password won't work" are the same complaint
when they share no words. Two conversations about one order *are* caught,
because entities are weighted above topics. But synonymy is invisible.

**Requires your decision:** accept lexical clustering as the phase 2
baseline, or require embeddings — which would mean registering
`CLUSTER_CENTROID` in `domain/embedding_owners.py`, making the phase
depend on a configured provider, and accepting that a model upgrade
silently re-partitions history.

My recommendation is to accept it now and add embeddings later as a
*second* signal behind an `algorithm_version` bump, measured against this
baseline. That way the question "did embeddings help?" has an answer.

### 3.2 A separate `algorithm_version`

The charter has one `pipeline_version`. Phase 2 adds
`CLUSTER_ALGORITHM_VERSION`, and clusters carry both.

Re-extracting features and re-clustering the same features are different
acts with different costs. One version for both would mean every
clustering-threshold tweak forced a full re-observation of the corpus —
expensive enough that the tweak would not happen, which is how thresholds
end up frozen at whatever they were first guessed to be.

**Requires your acknowledgement.** It is additive; nothing in the charter
forbids it.

### 3.3 A defect found while testing, and fixed

The floor on trend testing was originally applied to the recent window
only. That silently hid the most valuable decline there is: a cluster
running at forty a week that collapses to two has a recent count *below*
the floor, so it was never tested. The floor now applies to either side.
Found by a test asserting a decline is reported, which failed.

## 4. Scalability

**Clustering is incremental**, which is the property that makes hourly
cadence affordable. Already-clustered observations are dropped before
assignment, so a sweep costs what the hour produced, not what the corpus
contains.

**Cost per pass** is `O(new × live_clusters)` similarity comparisons,
each a dot product over ≤40 terms. Measured at 444 observations/second
against 15 clusters. The term that grows is `live_clusters`, and it is
bounded in practice by three things: the merge pass folds converged
clusters, dormancy removes stale ones from the working set at 30 days,
and archival removes them entirely at 120.

**The honest risk is cluster-count growth on a diverse corpus.** The
benchmark's 2 985 observations produced 15 clusters because the synthetic
corpus is built from 12 templates. A real corpus is far more varied and
will produce hundreds. At 1 000 live clusters the per-observation cost is
roughly 60× the measured figure — still around 7 observations/second per
worker, which covers a company producing 10 000 conversations a day with
three orders of magnitude to spare, but it is no longer free. **This is
the number to watch first**, and `GET /intelligence/metrics` reports
`clusters_by_state` for exactly that reason.

**Per-tenant fairness** is structural: companies are served in id order,
each in its own transaction, with a per-company batch ceiling. One large
tenant cannot starve the rest — the failure the memory decay sweep had
once and which took a stabilisation phase to find.

**Analysis** reads up to 50 000 observations per company per day and does
arithmetic on them. Bounded, and the ceiling is a setting.

## 5. Performance

| Metric | Measured |
|---|---|
| Clustering throughput | **444 obs/s** (~1.6 M/hour), single worker |
| Clustering wall time | 6.7 s for 2 985 observations |
| Replay wall time | 0.33 s for the same corpus |
| Replay writes | **0 clusters, 0 placements, 0 duplicate members** |
| Storage | ~439 bytes per membership |
| Trend/anomaly detection | Pure arithmetic; no measurable cost at this corpus size |

Clustering runs ~7× faster than the observation pipeline that feeds it
(444/s vs 66/s), so phase 2 does not become the bottleneck at any volume
phase 1 can produce.

## 6. Remaining risks

**R1 — Cluster-count growth is unmeasured on real text.** §4 explains
why. The synthetic corpus cannot answer it; only production can. Watch
`clusters_by_state` and the clustering sweep's duration.

**R2 — Threshold choices are guesses.** `DEFAULT_JOIN_THRESHOLD = 0.42`
and `DEFAULT_MERGE_THRESHOLD = 0.72` were chosen to behave sensibly on a
synthetic corpus. Too low produces one enormous cluster containing
everything, which reads as a finding and is an artefact; too high
produces a cluster per conversation. Both failure modes are visible in
`clusters_by_state` and `mean_cluster_size`, and both are settings.

**R3 — Trend and anomaly precision are unmeasurable today**, and the
metrics endpoint deliberately does **not** report them. Precision needs
verdicts — somebody saying "that one was real" — and phase 2 shows
findings to nobody and collects nothing. Reporting a precision figure
now would be reporting a guess. This is the same honesty the phase 1.5
report applied to the feedback ratio, and it is the strongest argument
for phase 3 being a *review* phase rather than an *emission* phase.

**R4 — Lexical similarity misses synonymy.** §3.1. Two customers
describing the same problem in different words land in different
clusters, and both may sit below the floors as a result — so the platform
would miss a pattern that a human would see immediately.

**R5 — Seasonality needs two full cycles.** Fourteen days minimum, and
the analysis span is eight weeks. A quarterly or annual pattern is
invisible, and phase 2 does not claim otherwise.

**R6 — The corpus is still hypothetical.** Phase 1.5's verdict has not
changed: this installation has five finished conversations. Phase 2 is
built, tested and benchmarked against synthetic data. Every number in §5
is an engineering measurement; none is a statement about what this
platform will actually find.

## 7. Verdict

**Phase 2 is complete as specified.** Eight objectives built, seven
prohibitions enforced — two of them by static guard *and* behavioural
test. Ten charter invariants: six enforced, two inherited from phase 1,
one vacuous until phase 3, one not applicable.

**Two decisions are yours** (§3.1 lexical clustering, §3.2 the separate
algorithm version), and one defect found during testing is already fixed
(§3.3).

**Phase 3 should not begin on this document alone**, and the reason is
R3. Phase 2's usefulness cannot be measured without somebody reviewing
what it found, and the charter's own gate for phase 2 → 3 is *"an
operator reviews what it would have proposed and agrees"*. That review
needs a corpus, and the corpus does not exist yet.

The honest sequence is unchanged from phase 1.5: deploy, accumulate real
traffic, look at the clusters, and *then* decide whether the shapes it
finds are worth proposing from.

## See also

- [Phase 2 design](./learning-platform-phase-2.md)
- [Phase 1 review](./learning-platform-phase-1-review.md)
- [Production Readiness Report (phase 1.5)](./learning-platform-production-readiness.md)
- [Learning Platform Charter](./learning-platform-charter.md)
