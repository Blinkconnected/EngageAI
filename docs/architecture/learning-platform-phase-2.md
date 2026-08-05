# Learning Platform — Phase 2: Pattern Detection

Stage 3, phase 2 of the [Company Intelligence Engine](./company-intelligence-engine.md),
built to the [Learning Platform Charter](./learning-platform-charter.md).
Phase 1 is [learning-platform.md](./learning-platform.md); phase 1.5's
validation is [learning-platform-production-readiness.md](./learning-platform-production-readiness.md).

**This phase discovers. It proposes nothing.** No memory fact, no
knowledge suggestion, no candidate event, no human review queue, no model
call. Those are phases 3 and 4, and their absence here is enforced by
tests rather than remembered.

One sentence: **settled observations become populations that recur, and
those populations are measured over time.**

---

## What a cluster is

A **population of finished work that recurs**. Not a topic, not an
intent, not a category — those are labels somebody chose. A cluster is a
shape the corpus already had.

The distinction is not academic. Phase 3 will propose to humans from
these, and *"eleven customers asked this in two weeks"* is an argument
where *"this looks like a billing question"* is an opinion.

| Column group | Holds |
|---|---|
| Identity | `signature`, `algorithm_version`, `pipeline_version` |
| Shape | `centroid`, `centroid_count`, `feature_summary`, `language_distribution` |
| Evidence | `size`, `distinct_customers`, `distinct_days` |
| Standing | `confidence`, `stability`, `meets_floors`, `state` |
| Time | `first_seen`, `last_seen` |

Membership lives in `learning_cluster_members`, one row per observation,
with the similarity it had when it joined — because *"why is this in
here"* is the first question anybody asks of a cluster they disagree
with.

## Why lexical, not embedded

The charter pencils in tier-2 embeddings for this phase. Phase 2 clusters
**lexically** instead, on the topics and entities phase 1 already
extracts, and the reason is the charter's own requirement two lines
above: *clusters must be deterministic*.

An embedding centroid is not reproducible. Re-embed the same corpus after
a provider change, a model upgrade or a dimension change and the vectors
differ, so the clusters differ — silently, with no version bump and no
way to tell a real change in the corpus from a change in the encoder.
Lexical similarity over stored tokens is reproducible for as long as the
text is.

It is also free, needs no provider (the platform default is
`EMBEDDING_PROVIDER=disabled`), and works on every installation rather
than only the ones that have paid for embeddings.

**Cost:** lexical similarity cannot see that "cannot log in" and "password
won't work" are the same thing when they share no words. That is a real
limitation and it is the argument for adding embeddings later — as a
*second* signal, behind a version bump, measured against this baseline.

## Determinism, and what it costs

Three properties make the output a pure function of the input:

1. **Total order on input.** Observations are processed by
   `(observed_at, observation_id)`. A query plan change, a different
   index, a parallel scan — none can alter what the platform believes.
2. **Single-pass leader clustering.** Not k-means (seeded), not DBSCAN
   (border points depend on scan order), not agglomerative (depends on a
   merge queue's tie-breaking). Each of those produces different clusters
   from identical data on a second run.
3. **Ties broken by key**, never by iteration order.

Leader clustering's known weakness is drift: several clusters that are
really one, when early members happen to be unrepresentative. A **merge
pass** folds clusters whose centroids have converged, and it is
deterministic too — sorted by key, and a cluster **with history always
absorbs a new one**, whatever their keys sort like. A cluster with
members, a first-seen date and a confidence somebody may have read must
not dissolve into one discovered thirty seconds ago.

The merge pass is single-pass and **non-transitive** on purpose: if A
merges into B and B would merge into C, A∪B is compared against C on the
*next* run, against a centroid that has settled. Chasing transitivity
inside one pass is how a merge cascade eats a corpus in one sweep, and it
cannot be undone.

### The IDF is window-scoped, deliberately

Term weights are computed over the observations in the pass, not over all
history. A corpus-wide IDF would change with every write, so yesterday's
clusters could not be reproduced today — which would make
`algorithm_version` a label on a moving target.

## Floors before scores

Charter I-9. A cluster clears these or it is not a cluster, **regardless
of how well it scores**:

| Floor | Value | Why |
|---|---|---|
| `MIN_CLUSTER_SIZE` | 3 | Two conversations is a coincidence |
| `MIN_DISTINCT_CUSTOMERS` | 2 | Three from one customer is one person repeating themselves |

`meets_floors` and `confidence` are separate functions on purpose. A floor
says what may be *considered*; a score ranks what already qualifies. One
function doing both would let a high score buy its way past a floor,
which is exactly the failure the floors prevent.

## Confidence is computed, never asserted

Multiplicative, so no single term can carry a cluster:

```
size × customer_spread × day_spread × stability × attribution
```

- **Customer spread dominates.** Ten conversations from one customer is
  one person; ten from ten is a pattern.
- **Day spread** stops a single bad afternoon — an outage, a broken
  deploy — reading as a standing issue.
- **Size** has diminishing returns: the fortieth member says much less
  than the fourth.
- **Stability** discounts a cluster still in motion.
- **Attribution** discounts a cluster the platform mostly resolved
  itself, since phase 1 already refuses to treat its own work as
  evidence.

Additive scoring would let a large single-customer cluster rescue itself.
Multiplication means it cannot.

## Lifecycle

| State | Meaning |
|---|---|
| `forming` | Below the floors. Real, recorded, not yet a finding |
| `active` | Above the floors, still receiving members |
| `dormant` | Above the floors, nothing new for 30 days — a problem that stopped |
| `archived` | 120 days idle. Out of the working set, still on the record |
| `merged` | Absorbed. **Terminal** — a resurrected tombstone would put its members in two clusters |

A cluster ages **because time passed**, not because something happened,
so a quiet tenant's clusters still advance. Without that, "what is live
right now" would be wrong for every company that went quiet.

Falling below the floors returns a cluster to `forming` rather than
deleting it: membership shrinks when an erasure removes a customer's
observations, and deleting would destroy the record that it had once been
real.

## Trends

A trend is a claim about **direction over time**. The hard part is not
detecting one — it is not detecting the hundreds that are not there. A
support corpus produces hundreds of topics; testing each at 5% and
printing the results yields roughly one false trend per twenty topics on
every run, forever, and that inbox teaches its reader to ignore it.

Three defences, all required together (charter I-10):

1. **Floors before any test.** Under `MIN_RECENT_COUNT` (5) on *either*
   side and `MIN_TOTAL_COUNT` (12) overall, nothing is tested. Checked
   against either side because a floor on the recent window alone hides
   the most valuable decline there is — something that ran at forty a
   week and collapsed to two.
2. **Benjamini-Hochberg correction** across every hypothesis in the run,
   as one family. Bonferroni controls the chance of *any* false positive
   and, over three hundred topics, admits only a catastrophe — trading an
   inbox of noise for an inbox of nothing. BH bounds the expected *share*
   of reported findings that are wrong, which is the promise worth making
   to somebody who will act on a list.
3. **Persistence across two consecutive windows.** A finding that clears
   the statistics once is stored as `provisional` and is not a trend
   until the next window agrees.

| Kind | Test |
|---|---|
| `rising` / `declining` | Two-sample Poisson, as an exact conditional binomial |
| `spike` | Poisson upper tail against the cluster's own baseline mean |
| `seasonal` | Binomial on weekday share vs 1/7, ≥2 complete cycles |
| `recurring` | A shape in the counts — non-zero, zero, non-zero, twice over |

`recurring` reports a q-value of 0.0 and says so in its detail: no
hypothesis was tested, and giving it a borrowed one would let it rank
against findings that earned theirs. It exists as its own kind because
the message differs — *"this was fixed and came back"* is a different
conversation, usually with different people, than *"this is growing"*.

## Anomalies

An anomaly is a claim about **one thing being unlike its own history**.
Separated from trends because they fail differently: a trend detector
that is too eager floods a list, an anomaly detector that is too eager
pages somebody.

| Kind | Measured against |
|---|---|
| `new_issue` | Nothing — the absence of a baseline *is* the finding |
| `unusual_frequency` | The cluster's own recent window counts (Poisson) |
| `abnormal_resolution_time` | The cluster's own handling times (robust z) |
| `abnormal_csat` | The cluster's own ratings, **low only** |
| `abnormal_escalation` | The cluster's own escalation rates |

**Baselines are per-cluster, never per-company.** Billing disputes take
longer than password resets; measured against a company-wide median the
billing cluster is abnormal every window forever, and the finding says
nothing except that two kinds of work are different.

**Robust statistics throughout.** Mean-and-standard-deviation detection
has a failure built into it: the outlier being hunted is in the sample
and inflates the threshold meant to catch it. One nine-day conversation
can raise the standard deviation enough that nothing is abnormal again
for a month. The median and MAD do not move.

One consequence needed handling explicitly. CSAT is a bounded five-point
integer scale, so a healthy baseline of fours and fives has a MAD of
**zero** — and a robust z against zero spread is undefined. Without a
floor on the denominator (`MIN_CSAT_SPREAD = 0.5`) the CSAT detector
would be silent on exactly the case it exists for: a cluster whose
ratings collapse from five to one.

Satisfaction *improving* is not reported. A good day is not an incident,
and reporting it doubles a list nobody acts on differently.

No multiple-testing correction is applied here, and that is deliberate:
these are threshold rules on robust distances, not hypothesis tests, and
attaching a q-value to a z-score would dress a heuristic in statistics it
did not earn. The protection is the minimum-sample floors and a threshold
set high enough to be quiet — both stated, both testable, both easy to
argue with.

## Deduplication, at three levels

| Level | Mechanism |
|---|---|
| Duplicate clusters | `UNIQUE (company_id, algorithm_version, signature)` — identity *is* the centroid |
| Duplicate observations | Already-clustered ids are dropped **before** assignment, so they never move a centroid |
| Duplicate members | `UNIQUE (cluster_id, observation_id)` |
| Replay-created clusters | A rediscovered shape collides with itself and updates |

Measured: re-running over 2 985 clustered observations creates **0**
clusters, places **0** observations and writes **0** duplicate members.

## Runtime

| Sweep | Cadence | Does |
|---|---|---|
| `cluster-learning-observations` | hourly | Places settled observations, merges converged clusters, ages lifecycle |
| `analyse-learning-patterns` | daily | Trends and anomalies |

Hourly clustering is affordable because it is **incremental**: an
observation already in a cluster is never reconsidered, so a sweep costs
what the hour produced.

Daily analysis is a *statistical* decision, not a cost one. Running the
same weekly-window tests hourly would give them twenty-four chances a day
to cross a threshold — multiple testing through the back door, defeating
the correction applied at the front.

Both serve companies **in id order**, each in its own transaction. Not
busiest-first: a sweep that served the largest tenant first would starve
the rest whenever it ran out of budget, which is the exact failure the
memory decay sweep already had once.

## Measured

Against real PostgreSQL, 2 985 settled observations:

| Metric | Value |
|---|---|
| Clustering throughput | **444 observations/second** (~1.6 M/hour) |
| Clustering wall time | 6.7 s for 2 985 observations |
| Clusters produced | 15, mean size 199, all above the floors |
| Merges | 1 |
| Replay | 0 created, 0 placed, 2 985 skipped, **replay-safe** |
| Replay wall time | 0.33 s |
| Storage | ~439 bytes per membership; 1.31 MB total |

Clustering is roughly **seven times faster than the observation pipeline
that feeds it** (444/s against 66/s), so it is not the bottleneck and is
not close to becoming one.

## API

All read-only, under `intelligence.read`.

| Endpoint | Answers |
|---|---|
| `GET /intelligence/clusters` | What recurs, strongest first |
| `GET /intelligence/clusters/{id}` | One cluster, its centroid and every member |
| `GET /intelligence/trends` | Confirmed trends; `?include_provisional=true` for the rest |
| `GET /intelligence/anomalies` | Things unlike their own history |
| `GET /intelligence/metrics` | What phase 2 built, and how settled it is |

The cluster detail endpoint is phase 2's traceability story, and the
argument is phase 1's: a finding nobody can trace back to the
conversations behind it is an assertion.

Provisional trends are hidden by default. Returning them beside confirmed
ones would defeat the persistence gate entirely.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `LEARNING_CLUSTER_INTERVAL_SECONDS` | 3600 | Cadence **and** run-window width |
| `LEARNING_CLUSTER_BATCH_SIZE` | 5000 | Observations per company per pass |
| `LEARNING_CLUSTER_COMPANIES_PER_RUN` | 50 | Tenants served per sweep |
| `LEARNING_CLUSTER_LOOKBACK_DAYS` | 14 | How far back a pass looks |
| `LEARNING_TREND_WINDOWS` | 8 | Windows of history |
| `LEARNING_TREND_WINDOW_DAYS` | 7 | Window width |
| `LEARNING_ANALYSIS_INTERVAL_SECONDS` | 86400 | Analysis cadence |

Nothing here costs money. Clustering is lexical and the statistics are
arithmetic.

## What is verified

`tests/unit/test_learning_clustering.py` (30) — determinism against
shuffled input, signature stability, per-tenant signatures, floors before
scores, confidence ordering, centroid order-independence and bounds,
merge rules, lifecycle transitions.

`tests/unit/test_learning_statistics.py` (35) — exact binomial and
Poisson tails, the upper/lower identity, BH monotonicity, **300 uniform
p-values yielding ≤1 finding**, real effects still surviving, robust
statistics under an outlier, 40 noisy series yielding **zero** trends,
persistence gating, seasonal and recurring detection, anomaly floors.

`tests/integration/test_learning_patterns.py` (24) — clustering end to
end, replay creating nothing, an observation never in two clusters,
determinism from scratch through the database, two tenants with identical
vocabulary staying separate, lifecycle ageing, **the outbox staying empty
across an analysis**, and RBAC.

`tests/unit/test_learning_writes_only_its_own_tables.py` (10) — the AST
guards, now covering phase 2: no foreign model constructed, no publish
call anywhere in Learning, no import of another context's writer, no
model provider imported at all.

## See also

- [Learning Platform (phase 1)](./learning-platform.md)
- [Production Readiness Report (phase 1.5)](./learning-platform-production-readiness.md)
- [Phase 2 Review](./learning-platform-phase-2-review.md)
- [Shadow Validation Report (phase 2.5)](./learning-platform-shadow-validation.md)
- [Learning Platform Charter](./learning-platform-charter.md)
