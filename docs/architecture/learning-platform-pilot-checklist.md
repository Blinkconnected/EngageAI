# Production Pilot — Readiness Checklist

The gate between the pilot and phase 3. Seven criteria, and **all seven
must hold**. There is no partial pass and no weighted score: each one
guards a different way the platform could propose something wrong to a
human, and a criterion that can be traded away is not a gate.

Record the evidence, not the verdict. "Reviewed, looked fine" six months
ago is not something anybody can check.

---

## Current status

| # | Criterion | Target | Actual | Pass |
|---|---|---|---|---|
| 1 | Production observations | ≥ 1 000 | **5** | ❌ |
| 2 | Stable clusters | ≥ 50 | **0** | ❌ |
| 3 | Operator review completed | Yes | Not possible | ❌ |
| 4 | Thresholds finalised | Yes | Provisional | ❌ |
| 5 | No replay defects | 0 | **0** | ✅ |
| 6 | No queue lag issues | 0 | **0** | ✅ |
| 7 | No unexpected cluster growth | — | Not measurable | ❌ |

**Two of seven.** The five that fail all fail for one reason: there is
almost no production traffic. This installation holds 26 conversations,
5 of them finished, of which 2 are eligible for clustering.

---

## 1 — At least 1 000 production observations

**Where:** Pattern detection → Observations, or
`GET /intelligence/shadow` → `throughput.observations_total`.

**Why 1 000.** Below roughly this, group structure is indistinguishable
from noise. Eight true issue families need a few hundred conversations
before the shape is stable enough to judge, and the pilot has to be
judged on shape rather than on whether the code ran.

**Also record:** the eligible share. A thousand observations of which
fifty are eligible does not clear this — the criterion is about material
to learn from, and `throughput.eligible` is the number that says so.

## 2 — At least 50 stable clusters

**Where:** Pattern detection → Groups and Stability.

**Stable** means past the floors (`meets_floors`) *and* with mean
stability ≥ 0.7 across two consecutive sweeps. A cluster whose membership
is still moving is not a shape yet, and proposing from it would propose
from something that will be different tomorrow.

**Why 50.** Phase 3 ranks candidates. Ranking needs a population; below
about fifty there is nothing to rank and the "best" cluster is whichever
one happens to exist.

## 3 — Operator review completed

**The only criterion no metric can close**, and the one most likely to be
skipped because it takes an afternoon.

It means an operator has:

- Opened **at least ten clusters**, largest first.
- For each, written one sentence describing every conversation in it. If
  the sentence needs an "and also", the cluster is two things — record
  that.
- Read the **ungrouped** list and judged whether those observations
  genuinely match nothing.
- Checked **neighbours** for two or three clusters and confirmed that
  nothing sitting just below the merge threshold is obviously the same
  thing.

**Record:** how many clusters were opened, how many were describable in
one sentence, and the identifiers of any that were not. A review that
found three bad clusters out of ten is a *useful* review; one that found
none and says so without listing what was opened is not evidence.

The bar: *would you be comfortable if the platform proposed something to
a colleague on the strength of these?*

## 4 — Thresholds finalised

**Where:** Pattern detection → Similarity threshold; changes in the audit
log under `learning.thresholds_changed`.

**Finalised** means: no change in the last two weeks, and the current
value produces a size distribution with mass in the 3–25 buckets and
groups-of-one below 0.30.

A threshold still being tuned means the clusters keep changing
underneath, so criteria 2 and 3 are measuring something that will not
exist next week.

**Record:** the final value, the date of the last change, and the reason
given for it.

## 5 — No replay defects

**Where:** Pattern detection → Replayed;
`GET /intelligence/shadow` → `replay.superseded_generations`.

**Zero unless a pipeline version was deliberately bumped.** Ordinary
at-least-once redelivery is *not* a replay and must never appear here — a
non-zero value without a version bump means observations are being
re-recorded, which would double every count derived from them.

Also verify: re-running the clustering sweep creates no clusters and
places no observations. Measured at 2 985 synthetic observations — 0
created, 0 placed, 0 duplicate members, 0 bytes added.

**Currently passing**, and it is a property of the schema rather than of
the traffic, so it stays true at volume.

## 6 — No queue lag issues

**Where:** Pattern detection → Since last run and Run errors.

- Clustering ran within the last 2 hours (it is hourly).
- Analysis ran within the last 48 hours (it is daily).
- Run errors across recent runs: **0**.
- `learning_runs` shows one row per window per run type — consecutive
  windows each recorded, no gaps.

The last point matters more than it looks: a window that recorded nothing
also recorded no failures, so a gap in run rows is a blind spot rather
than an absence of problems.

**Currently passing:** 9 runs recorded, 0 errors, 86 ms and 84 ms.

## 7 — No unexpected cluster growth

**Where:** Pattern detection → New groups, against Observations.

Cluster count should grow, then flatten as the corpus is covered. What
must not happen is growth that keeps pace with observations — that is
fragmentation, and it means the platform is producing one group per
conversation and finding nothing.

**The test:** over a week, does cluster count grow more slowly than
observation count? If clusters grow roughly one-for-one with
observations, criterion 4 is wrong regardless of what the threshold page
says.

**Also watch cost.** Clustering time scales with live cluster count —
measured at 0.11 s for 4 clusters and 2.60 s for 147 over the same
corpus. Unexpected growth is expensive as well as blinding.

---

## Verdict

**CONTINUE PILOT.**

Five of seven criteria fail, all for the same reason, and none of them is
a defect in the platform. What is built has been deployed, run against
real traffic, and measured; what it needs is traffic to measure.

**The one thing that would change this fastest** is enabling the pilot
for a company with real conversation volume and waiting eight weeks — the
span trend detection needs before it can produce anything at all.

Re-run this checklist against `GET /intelligence/shadow` and the operator
handbook when observations pass 1 000.

## See also

- [Operator handbook](./learning-platform-operator-handbook.md)
- [Dashboard reference](./learning-platform-dashboard.md)
- [Deployment guide](../deployment/learning-platform-pilot.md)
- [Shadow validation report](./learning-platform-shadow-validation.md)
