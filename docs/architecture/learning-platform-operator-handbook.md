# Learning Platform — Operator Handbook

For whoever is running the pilot. Three questions, in the order they
matter:

1. [Are the groups any good?](#1-are-the-groups-any-good)
2. [Is a threshold wrong?](#2-is-a-threshold-wrong)
3. [May phase 3 begin?](#3-may-phase-3-begin)

None of them can be answered by a number alone, which is why this
document exists rather than an alert.

---

## What the platform is doing

It groups completed conversations that resemble each other, and measures
those groups over time. **It tells nobody and changes nothing.** No
alerts, no tickets, no suggested articles, no additions to what the
platform remembers.

That restraint is the pilot. A detector wired to alerting before anybody
has checked whether it is right teaches people to mute it, and the mute
outlives the fix.

## 1. Are the groups any good?

### Start with the shape, not the count

Open **Pattern detection** and look at **Group sizes** before anything
else. The count of groups tells you almost nothing; the distribution
tells you what kind of wrong you have, if any.

| What you see | What it means | What to do |
|---|---|---|
| Mass in the 3–5 and 6–10 buckets | Working | Move on to reading them |
| Most groups in the "1" bucket | Threshold too high — nothing is grouping | [§2](#2-is-a-threshold-wrong) |
| One bucket at 100+ holding most of the corpus | Threshold too low — nothing is separating | [§2](#2-is-a-threshold-wrong) |
| Nothing at all | Not enough eligible observations yet | Wait; check "Eligible" is rising |

**Groups of one is the single most useful number on the page.** Above
0.30 the platform is holding evidence it cannot see: each fragment sits
below the floors, so nothing becomes a finding even though the underlying
pattern is right there. It is measured, not guessed — see the [shadow
validation report](./learning-platform-shadow-validation.md).

### Then read five groups by hand

There is no substitute for this and no metric that replaces it. Open five
groups, largest first, and for each ask one question:

> **Would I describe these conversations as the same problem?**

Not "are they related". Not "do they share words". *The same problem* —
because phase 3 will propose to a human from exactly this, and the
proposal is only as good as the grouping under it.

A group passes if you can write one sentence that describes every
conversation in it. If your sentence needs an "and also", the group is
two things.

**Where to look:** the group's page lists every member with the
similarity it had when it joined. A member with a much lower similarity
than the rest is usually the one that does not belong, and it is the
fastest way to find a bad group without reading all of it.

### Check what did not group

**Ungrouped** on the dashboard, then the list behind it. Two reasons
appear, and they mean opposite things:

- *"no features to compare"* — the conversation had nothing extractable.
  Not a failure of the grouping; a conversation that said nothing. A
  steady trickle of these is normal.
- *"matched no existing cluster above the join threshold"* — this is the
  one to read. If you look at several and think *"but that is obviously
  the same as group 3"*, the threshold is too high.

### Three things that are **not** evidence of quality

- **A large number of groups.** Fragmentation produces plenty of groups
  and no findings.
- **High confidence scores.** Confidence measures spread across customers
  and days. A tight, wrong group scores well.
- **Zero anomalies or trends.** Silence is the correct default on a small
  corpus. It becomes informative only above the volumes in [§3](#3-may-phase-3-begin).

## 2. Is a threshold wrong?

### The two failures, and how to tell them apart

Clustering fails in exactly two directions, and they need opposite fixes.

**Fragmentation** — one problem split across many groups. Symptoms:
groups of one above 0.30, many small groups, ungrouped observations that
obviously belong somewhere. **The threshold is too high.**

This is the dangerous one, because nothing looks broken. The platform
holds the evidence for a pattern and cannot see it — every piece sits
below the floors, no finding appears, and no error is logged.

**Conflation** — distinct problems merged into one group. Symptoms: one
group holding most of the corpus, groups you cannot describe in a
sentence. **The threshold is too low.**

### The measured band

From the [shadow validation report](./learning-platform-shadow-validation.md),
against corpora with known group structure:

| Join threshold | What happens |
|---|---|
| Below 0.15 | Conflation begins — distinct problems merge |
| **0.15 – 0.25** | **The usable band.** Purity ≥ 0.998, no fragmentation |
| 0.30 | Mild fragmentation (1.4×) |
| 0.40 | **7× fragmentation** — this was the original default, and it was wrong |
| 0.50 | 31 % groups of one |
| 0.70 | 99 % groups of one — the platform sees nothing |

The default is **0.15**. The slider stops at 0.05 and 0.60 because
outside that range one of the two failures is certain, and a control that
can express a refused value teaches you to distrust the form.

### Changing it

Small steps, one at a time, and **write the reason**. The reason is what
answers *"why did the platform stop finding anything in March?"* six
months from now; without it the audit row only records that somebody
changed a number.

After a change:

- Existing groups are **kept, not deleted**. They are the record of what
  the platform believed, and deleting them would destroy the comparison
  that makes the change reviewable. The dashboard tells you how many were
  built under the old value.
- **Nothing regroups until the next hourly sweep.** Do not judge the
  change before then.
- Judge it on the *distribution*, not the count. More groups is not
  better; describable groups are better.

Do not change both thresholds at once. The merge threshold repairs a
badly-set join threshold only partially — it is single-pass and
non-transitive by design — so if you move both you cannot tell which one
did what.

## 3. May phase 3 begin?

Phase 3 proposes to humans. The gate is not "does it run" — it does —
but "is what it finds worth putting in front of somebody".

All seven must hold:

| # | Criterion | Where to check | Why this one |
|---|---|---|---|
| 1 | ≥ 1 000 production observations | Dashboard → Observations | Below this, group structure is noise |
| 2 | ≥ 50 stable groups | Dashboard → Groups, Stability | Fewer means no pattern population to draw from |
| 3 | Operator review completed | This handbook, [§1](#1-are-the-groups-any-good) | The only judgement a metric cannot make |
| 4 | Thresholds finalised | Dashboard → Similarity threshold | A moving threshold means the groups keep changing underneath |
| 5 | No replay defects | Dashboard → Replayed | Non-zero without a version bump is a defect |
| 6 | No queue lag issues | Dashboard → Since last run | Sweeps must be running on time |
| 7 | No unexpected group growth | Dashboard → New groups | Growth outpacing observations means fragmentation |

Criterion 3 is the one that cannot be automated and the one most likely
to be skipped. It means: an operator opened at least ten groups, could
describe each in a sentence, and would be comfortable if the platform
proposed something to a colleague on the strength of them.

**If any criterion fails, the answer is CONTINUE PILOT.** There is no
partial pass. The full checklist, with the evidence to record against
each, is in the [pilot readiness checklist](./learning-platform-pilot-checklist.md).

## When something looks wrong

| Symptom | Most likely cause | First check |
|---|---|---|
| Every number is zero | Beat was not restarted after deploy | `beat_schedule` contains the learning entries |
| Observations rising, Eligible flat | Settle sweep not running | `learning_runs` for `settle` rows |
| Eligible rising, Groups flat | Threshold too high, or nothing similar yet | Ungrouped list |
| Run errors above zero | A tenant's data is failing | Worker logs, `learning_clustering_failed` |
| Groups of one climbing over weeks | Threshold drifted wrong for this corpus | [§2](#2-is-a-threshold-wrong) |

## See also

- [Dashboard reference](./learning-platform-dashboard.md) — every number, defined
- [Pilot readiness checklist](./learning-platform-pilot-checklist.md)
- [Deployment guide](../deployment/learning-platform-pilot.md)
- [Shadow validation report](./learning-platform-shadow-validation.md) — where the measured bands come from
