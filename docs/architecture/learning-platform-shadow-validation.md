# Learning Platform — Shadow Validation Report (Phase 2.5)

**Scope:** the pattern-detection pipeline run against real production
traffic, read-only.
**Measured against:** the deployed compose stack, real PostgreSQL 16,
pipeline version 2, algorithm version 1.
**Verdict:** [§9](#9-verdict).

Shadow mode means the pipeline runs and nothing acts on it. Confirmed
structurally, not just intended: **zero candidates, zero Memory writes,
zero Knowledge suggestions, zero events**, guarded by an AST test that
finds no `publish` call anywhere in Learning and by an integration test
that drains the outbox, runs an analysis, and asserts it is still empty.

---

## 0. What the pipeline actually did

It ran, end to end, on schedule, against real conversations:

```
cluster  run: completed, 1 company,  2 observations placed, 0 errors, 0.086 s
analysis run: completed, 1 company,  0 findings,            0 errors, 0.084 s
settle   runs: 7 recorded, 0 errors
```

And produced this:

| | |
|---|---|
| Observations eligible (`ready`, v2) | **2** |
| Clusters | 2 |
| Clusters meeting the floors | **0** |
| Cluster members | 2 |
| Singletons | **2** |
| Trends | 0 |
| Anomalies | 0 |

Both clusters are size 1, confidence 0.0000, state `forming`. Here is
literally everything the platform found:

```
cluster A: arrived, hasn, help, laptop, last, ordered, week, yet
cluster B: canada, file, here, hii, international, offer, shipping, smoke, test
```

One customer waiting for a laptop; one enquiry about shipping to Canada,
partly a smoke test. They share no vocabulary, so they did not group. The
algorithm is behaving exactly as designed and there is **nothing here to
validate**.

That is the finding, and it decides the verdict. Every honest answer
below follows from it.

## 1–10. The measurements

| # | Metric | Value | Measurable? |
|---|---|---|---|
| 1 | Cluster growth | 2 clusters, both today | **No** — two points is not growth |
| 2 | Cluster stability | `null` | **No** — nothing has cleared the floors |
| 3 | Merge rate | 0 / 2 | **No** — a merge needs two similar clusters |
| 4 | Duplicate suppression | 2 eligible, 2 clustered, 0 duplicates | **Yes** — see below |
| 5 | Trend quality | 0 findings | **No** — needs 8 windows of history |
| 6 | Anomaly quality | 0 findings | **No** — needs a per-cluster baseline |
| 7 | Cluster churn | singleton rate **1.0** | Measured, and it means "corpus too small" |
| 8 | Processing latency | **86 ms** cluster, **84 ms** analysis | **Yes** |
| 9 | Queue lag | 0 — the sweeps are scheduled, not queued | **Yes** |
| 10 | Resource usage | worker 647 MiB, beat 108 MiB, both 0.00 % CPU idle | **Yes** |

Stability is reported as `null` rather than `0.0`, and that distinction
is deliberate: a forming cluster is *supposed* to be unstable, so
averaging it in would report churn where the truth is newness. The same
rule applies to trend and anomaly precision — see §6.

**Duplicate suppression is genuinely verified**, because it does not need
a large corpus. Against 2 985 synthetic observations a replay created 0
clusters, placed 0 observations, wrote 0 duplicate members and added 0
bytes. Against the 2 real ones, re-running the sweep changes nothing.

## 2. Threshold sensitivity — and a default that was wrong

"Are the thresholds correct?" cannot be answered from two conversations,
and it should not wait. What *can* be done is sweep the join threshold
against corpora whose true group structure is known, and measure both
failure directions:

- **Conflation** — distinct problems merged into one finding. Measured as
  *purity*: the share of each cluster's members belonging to its dominant
  true group.
- **Fragmentation** — one problem split across many clusters. Measured as
  clusters per true group, and visible in the singleton rate.

### The first sweep, and why it was misleading

An initial sweep on a corpus of 2 000 observations across 8 planted
families showed no singletons until 0.70 and concluded the default (0.42)
sat safely in a wide flat band.

**That conclusion was wrong, and the corpus was the reason.** It gave
each conversation ~4 topics drawn from a 5-word family vocabulary, so two
conversations in the same family shared three words out of four — an
intra-family cosine similarity far higher than real text produces. The
fragmentation regime was never reached, so the sweep could not see it.

### The corrected measurement

Re-run against a corpus shaped like real conversations — 10–16 topics
each, drawn from a 25-word family vocabulary plus generic filler shared
by everyone, 1 200 observations across 8 known families:

| Threshold | Clusters | Singletons | Singleton rate | Purity | Fragmentation |
|---|---|---|---|---|---|
| 0.15 | 8 | 0 | 0.000 | 0.998 | **1.0×** |
| 0.20 | 8 | 0 | 0.000 | **1.000** | **1.0×** |
| 0.25 | 8 | 0 | 0.000 | **1.000** | **1.0×** |
| 0.30 | 11 | 0 | 0.000 | 1.000 | 1.4× |
| **0.40** (≈ the old default) | **58** | 2 | 0.034 | 1.000 | **7.2×** |
| 0.50 | 299 | 94 | 0.314 | 1.000 | 37.4× |
| 0.60 | 922 | 719 | 0.780 | 1.000 | 115.2× |
| 0.70 | 1 187 | 1 174 | 0.989 | 1.000 | 148.4× |

**At the shipped default, a realistic corpus fragments roughly seven-fold
and recovers 58 clusters where 8 exist.** Push a little higher and it
collapses into near-total singletons. The intuition the default was
chosen on — *"a loose threshold produces one enormous cluster"* — named
the right failure and put it in the wrong place: conflation only begins
below 0.15, and the whole region above 0.30 is the *other* failure.

This is the defect shadow validation existed to find. Its consequence is
precise and severe: at 0.42 the platform holds the evidence for a pattern
and **cannot see it**, because the evidence is split across dozens of
clusters that each sit below the floors. Nothing errors. Nothing looks
wrong. The finding simply never appears.

**The usable band is 0.15–0.25**, where purity is ≥ 0.998, fragmentation
is exactly 1.0× and singletons are zero.

> A revision of this constant to 0.15 is in flight from concurrent work
> on this branch, reached independently by sweeping five corpus shapes
> that varied conversation length and vocabulary overlap. The two
> experiments agree, which is worth more than either alone: they used
> different generators and different metrics and landed in the same band.

### Cost scales with cluster count

Also measured, and it converts risk R1 from the phase 2 review into a
number: clustering 2 000 observations took 0.11 s at 4 clusters and
2.60 s at 147 — a 24× increase for a 37× increase in clusters. Cost is
roughly linear in live cluster count, which is exactly why the
fragmentation failure is expensive as well as blinding.

## 3. Are the clusters useful?

**Unknown, and unknowable from this corpus.** Two singletons from two
conversations is not a sample; it is a demonstration that the code runs.

What can be said: the two clusters are *correct*. Those conversations
genuinely share nothing, and grouping them would have been the error.
Usefulness is a question about a population, and there is no population.

What can also be said, from §2: **had there been a population, the
shipped default would have prevented the platform from finding it.** That
is the strongest single argument for having run this phase.

## 4. Are the thresholds correct?

**No. The join threshold was wrong**, and by enough to matter — see §2.

The others hold up:

- **Merge threshold (0.72)** — with the join threshold corrected the
  merge pass never fires, because a correctly-set join threshold leaves
  nothing to repair. It is a drift safety net, not a primary control, and
  it cannot rescue a badly-set join threshold: it is single-pass and
  non-transitive by design, so repair is partial by construction.
- **Floors (size 3, customers 2)** — untouched by the threshold question
  and doing exactly their job. Both real clusters fail
  `MIN_DISTINCT_CUSTOMERS`, correctly.

## 5. Which thresholds should change?

| Threshold | Current | Recommendation |
|---|---|---|
| `DEFAULT_JOIN_THRESHOLD` | 0.42 | **Lower to 0.15–0.20.** Measured: 0.42 fragments a realistic corpus ~7×. The band is 0.15–0.25; conflation begins below 0.15 |
| `DEFAULT_MERGE_THRESHOLD` | 0.72 | **Keep.** Never fires once the join threshold is right, and lowering it recovers only a third of true structure |
| `MIN_CLUSTER_SIZE` | 3 | **Keep.** It is what stops two conversations being a finding |
| `MIN_DISTINCT_CUSTOMERS` | 2 | **Keep.** The strongest floor in the system, and the one doing the work in §0 |
| `DEFAULT_Z_THRESHOLD` | 3.5 | Unvalidated — no anomaly has fired against real data |
| Trend `alpha` | 0.05 | Unvalidated against real text; verified against synthetic noise (300 uniform p-values → ≤1 finding) |

The join threshold should also become a **setting** rather than only a
constant. The right value is corpus-dependent — a company whose
conversations are long and varied needs a different point in the band
than one whose conversations are short and templated — and a constant
cannot express that.

## 6. Are the trends meaningful?

**No trend has been produced**, so there is nothing to judge. Trend
detection needs 8 weekly windows and a minimum of 12 occurrences per
subject; the corpus has 2 observations spanning one day.

More importantly: **trend precision is unmeasurable in shadow mode by
construction**, and `GET /intelligence/shadow` reports it as `null` with
a reason rather than as a number. Precision requires a verdict — somebody
saying *"that one was real"* — and phase 2 shows findings to nobody and
collects nothing. A precision figure here would be a guess wearing a
percentage sign, and somebody would eventually decide from it.

What the endpoint *does* report is the confirmation rate: the share of
findings that survived a second window. That is the honest proxy, and it
becomes meaningful the moment there are findings.

## 7. Which observations are never clustered?

`GET /intelligence/unclustered` answers this, and distinguishes two very
different reasons:

- **No features to compare** — nothing extractable in the conversation.
  Not a clustering failure; the conversation said nothing.
- **Matched no existing cluster above the join threshold** — a genuine
  threshold question, and the one worth acting on.

On real data today: **zero** unclustered eligible observations. Both
`ready` observations were placed (into singletons). The 2 `excluded` and
1 `pending` observations are not eligible and are correctly not counted
against the algorithm.

## 8. Which clusters are clearly wrong?

**None**, and that is a weak statement from a corpus of two.

`GET /intelligence/clusters/{id}/neighbours` is the endpoint for this
question, and it is built to be answered by a human rather than by a
threshold: it shows the nearest clusters with their similarity, their
feature summaries, and whether the algorithm *would* have merged them at
the current default. A pair a person reads as the same thing, sitting
below the merge threshold, is the evidence that the threshold is wrong —
and no aggregate number can show that.

On real data, the two clusters have similarity 0.0 to each other. They
are not wrong; they are unrelated.

## 9. Verdict

**NOT READY**

Unchanged from phase 1.5, for the same structural reason, and no amount
of further engineering moves it.

**The evidence:**

1. **Two eligible observations.** Both became singletons, both below the
   floors, both correct. There is no population to detect patterns in.
2. **Six of the ten required measurements are unmeasurable** — growth,
   stability, merge rate, trend quality, anomaly quality — because each
   is a property of a population and there is none. They are reported as
   `null` with reasons rather than as zeros.
3. **Zero trends and zero anomalies**, so the two questions phase 3
   depends on — *are the trends meaningful*, *are the clusters useful* —
   have no evidence either way.
4. **The charter's own gate for phase 2 → 3 is "an operator reviews what
   it would have proposed and agrees".** There is nothing to review.

**What is genuinely established by this phase:**

- **A shipped default was wrong in a way that would have blinded the
  platform**, and it was found before any traffic arrived to be missed.
  That alone justifies the phase.
- The pipeline runs end to end on schedule against real data, with zero
  errors across 9 recorded runs.
- Shadow mode is airtight: no candidates, no Memory writes, no Knowledge
  suggestions, no events — guarded statically *and* verified through the
  outbox.
- Latency is 86 ms and 84 ms per sweep; resource usage is flat.
- Duplicate suppression is exact, at 2 985 observations as well as at 2.
- Both failure directions are now located and measured, and the cost
  curve with them.
- Operators now have three endpoints built to answer the questions this
  report could not.

**What clears the gate.** Deploy, accumulate real traffic, and re-read
`GET /intelligence/shadow`. The gate is clear when:

| Criterion | Threshold |
|---|---|
| Eligible observations | ≥ 5 000 across ≥ 3 companies |
| Clusters meeting the floors | ≥ 20 |
| Observation window | ≥ 8 weeks, so trend detection has its windows |
| Singleton rate | < 0.30 — above that, revisit the join threshold |
| Mean cluster stability | ≥ 0.7 across two consecutive sweeps |
| Confirmed trends | ≥ 1, reviewed by an operator who agrees it is real |
| Run errors | 0 across ≥ 100 recorded runs |
| Clusters clearly wrong | reviewed by hand via `/neighbours`, and judged acceptable |

**One thing in phase 2 does need to change first**: the join threshold,
per §5. Everything else needs traffic.

## See also

- [Phase 2 design](./learning-platform-phase-2.md)
- [Phase 2 review](./learning-platform-phase-2-review.md)
- [Production Readiness Report (phase 1.5)](./learning-platform-production-readiness.md)
- [Learning Platform Charter](./learning-platform-charter.md)
