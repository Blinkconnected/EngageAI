# Learning Platform — Production Readiness Report (Phase 1.5)

**Scope:** validation of the observation pipeline before clustering.
**Measured against:** the deployed compose stack, real PostgreSQL 16,
pipeline version 2.
**Harness:** [`backend/scripts/validate_learning_pipeline.py`](../../backend/scripts/validate_learning_pipeline.py) — re-runnable, and meant to be re-run.
**Verdict:** [§9](#9-verdict).

---

## 0. The finding that frames every other number

Phase 1.5 was asked to validate the pipeline **under real production
traffic**. There is none.

```
companies                                35
conversations                            26
  finished (RESOLVED/CLOSED)              5
messages                                217
csat_responses                            0
oldest conversation               2026-07-24
newest conversation               2026-08-04
```

Twenty-six conversations across twelve days, five of them finished, zero
customer satisfaction responses. That is a development installation being
exercised by hand, not a platform carrying traffic.

**This is not a reason to stop measuring**, and everything below was
measured. But it splits the deliverables in two, and the split decides
the verdict:

| Kind of number | Can be measured now? | Why |
|---|---|---|
| Latency, throughput, storage, write volume, CPU, memory, cost | **Yes, exactly** | Properties of the code and the schema. A synthetic corpus measures them precisely and the answer does not change when real traffic arrives. |
| Replay, idempotency, duplicate suppression | **Yes, exactly** | Properties of the constraints. Proven by doing it. |
| Observation volume, feedback ratio, real language mix, exclusion rates, outcome-change rate | **No** | Properties of a *population*. No corpus produces them. |

The second group is what phase 2 depends on. Clustering quality is a
function of the real text distribution, and the feedback ratio is the
number that decides whether clustering is safe to run at all.

---

## 1. Observation volume

Read from real rows only; the harness excludes its own tenant.

| Metric | Value |
|---|---|
| Observations (production data) | **10** — 5 conversations × 2 pipeline generations |
| Distinct sources | 5 |
| Companies with observations | 1 |
| Finished conversations in the platform | 5 |
| Coverage of finished conversations | **100 %** |
| Observations / hour | *not computed* |
| Observations / day | *not computed* |
| Observations / company | 10 (one company) |

The rates are **deliberately null rather than extrapolated**. The
observation window is six minutes of deliberate replay; dividing ten
observations by it would produce "100 observations/hour", which is not a
rate, and somebody would eventually plan capacity on it.

Coverage is the number that means something here: **every finished
conversation the platform holds produced an observation**, with no
manual intervention, through the real outbox → RabbitMQ → consumer path.

**Capacity is known** even though volume is not — see §2.

## 2. Extraction and assembly latency

Tier-0/1 extraction, 10 000 samples, no I/O:

| | ms |
|---|---|
| p50 | **0.040** |
| p95 | 0.099 |
| p99 | **0.108** |
| max | 0.249 |
| mean | 0.052 |

Full assembly against PostgreSQL — extraction, envelope validation, the
idempotency lookup, the observation row, its features and ~7 content
refs, committed:

| | ms |
|---|---|
| p50 | **13.2** |
| p95 | 37.0 |
| p99 | **48.8** |
| max | 84.6 |

Throughput, single worker, single connection, no broker:
**58–66 observations/second → ~210 000–238 000 per hour.**

That is a floor, not a ceiling: consumers scale horizontally on their own
queue. It also puts the §14 lag budget (observation ≤ 5 min after settle)
far out of reach of any plausible load — a company producing 10 000
finished conversations a day is 0.12 observations/second.

**Extraction is not the cost. Storage I/O is**, by a factor of ~300. That
is the finding that matters for phase 2's tier-2 budgeting: adding an
embedding call per observation will dominate a cost that currently
rounds to zero.

## 3. Feature quality

Measured against a hand-labelled corpus (Arabic, English, code-switched,
with known entities), 5 000 samples:

| Metric | Value |
|---|---|
| Language detection accuracy | **1.000** |
| Topic coverage (substantive turns) | **1.000** |
| Entity precision | **1.000** |
| Entity recall | **1.000** |
| Empty extraction rate | 0.166 |
| Duplicate observations | **0** |

**These numbers are weak evidence and should be read as such.** The
corpus is twelve labelled turns, and the same hand wrote the labels and
the extractor. A benchmark scoring 1.000 against its author's own
intuitions has demonstrated internal consistency, not accuracy.

The empty rate of 0.166 is by design: two of the twelve labelled turns
are "thanks" and "ok", which are exactly the turns the too-short
exclusion exists for.

**What actually tested feature quality was the production data**, and it
failed — twice. See §5.

## 4. Replay, idempotency and duplicate suppression

5 000 observations assembled, then re-assembled with identical input:

| Metric | Value |
|---|---|
| Duplicate suppression rate | **1.000** |
| Rows created on replay | **0** |
| Rows before / after replay | 5 000 / 5 000 |
| Distinct sources before / after | 5 000 / 5 000 |
| Duplicate observations | **0** |
| Duplicate content refs | **0** |
| Bytes added by replay | **0** |
| Writes per replayed observation | **0.14** |
| Dead tuples after replay | **0** |
| Idempotency success | **true** |

A re-observation of an unchanged conversation writes nothing at all. The
residual 0.14 writes/observation is PostgreSQL's statistics collector
attributing the tail of the load phase to the replay window — corroborated
by zero bytes added and zero dead tuples, which could not both be true if
5 000 rows had genuinely been rewritten.

**Replay was also exercised for real.** Bumping `PIPELINE_VERSION` from 1
to 2 (§5) and re-consuming produced a second generation alongside the
first: 10 rows, 5 distinct sources, both generations intact and
comparable. `replayed = 5` on the dashboard.

## 5. What production data found that the benchmark could not

Four defects, all fixed in this phase. The first two were found only
because real messages went through the pipeline.

### F1 — URLs put identifier fragments into topics

A CSAT survey link carried a UUID and a JWT. The tokeniser split them,
and the pieces became topics:

```
v1: ["feedback", "9d1d", "bc0a287c1184", "charging", "did", "e1b9",
     "e8aa3a07", "gl9pwqnk", "hear", "help", "how", "https", ...]
v2: ["charging", "did", "feedback", "hear", "help", "how", "invoice",
     "looks", "love", "moment", "month", "out", "reaching", "refund",
     "same", "share", "take", "twice", "want", "wrong"]
```

**Six of twenty topic slots were junk**, and they had displaced real
signal — `want`, `wrong`, `twice`, `share` only appear once the noise is
gone. At clustering, a token unique to one conversation is dead weight;
a token shared by every conversation that received a survey link is worse,
because it looks like a pattern.

Fixed: URLs are stripped before topic extraction (they are already kept
as entities), and tokens mixing letters and digits are rejected as
identifier fragments. The rule is *not* a hex test — `cafe`, `dead` and
`decade` are hexadecimal and also words.

### F2 — Platform templates were counted as human evidence

The CSAT invitation is sent by the platform on nobody's behalf. It
carried no provenance marker at all, so Learning read it as
human-authored content and its wording — "feedback", "moment", "share" —
entered the topics of every conversation that received one.

That is the anti-feedback-loop defence with a hole in it: the loop was
being closed by a *template* rather than by AI, which the
`is_ai_generated` filter was never going to catch.

Fixed: a third provenance flag, `is_system_generated`, stamped by the
CSAT dispatcher through the same `_reply_metadata` seam that already
carries the two AI flags. Learning excludes those turns from extraction
and counts them as **neither** human nor AI — a template is not the
platform reasoning, and it is not a person writing.

> **Forward-looking only.** Messages sent before this flag existed carry
> `{}` metadata and are still read as human-authored. On this
> installation that is five conversations. On an installation switching
> Learning on over an existing corpus, a backfill would be needed first.

### F3 — Three sweeps in four recorded nothing

The settle sweep truncated its run window to the hour while running every
fifteen minutes. Consecutive sweeps collided on
`UNIQUE (company_id, run_type, pipeline_version, window_start)` and
returned early — **without recording their errors**.

Observed live: beat fired at 13:13:10, the sweep ran, and
`learning_runs` stayed empty.

The consequence is the dangerous part. `failed` and `last_run_at` on the
health dashboard are derived from run rows, so a sweep failing every
fifteen minutes would have shown `failed = 0` for three runs out of four.
An operator would have read health from a dashboard that could not see
the failure.

Fixed: the window is floored to the sweep's own cadence, and the cadence
and the window now read the **same setting**
(`LEARNING_SETTLE_INTERVAL_SECONDS`) rather than two literals that must
agree. Verified live: two sweeps inside one 15-minute window still produce
exactly one row; consecutive windows each produce their own.

### F4 — Every observation cost two writes where one would do

The observation row was inserted with defaults and then updated with its
outcome and provenance, measured at 1.99 writes per row against
PostgreSQL. Fixed by building the row complete before inserting it.

| | Before | After |
|---|---|---|
| Writes to `learning_observations` | 1.99/row | **1.00/row** |
| Writes per observation (all four tables) | 9.94 | **8.81** |

The two write figures are directly comparable; a storage comparison is
**not** offered, because the before-measurement predates the compaction
fix in §8 and would credit this change with a saving that belongs to the
measurement. Under MVCC the update was also a dead tuple per observation
for autovacuum to clear, which is the part that would have compounded.

## 6. Observation health dashboard

`GET /api/v1/intelligence/health` now reports the five counters this
phase asked for, alongside the danger metric:

```json
{
  "pending": 2, "settled": 4, "excluded": 4,
  "failed": 0, "replayed": 5, "erased": 0,
  "feedback_ratio": 0.125, "feedback_ratio_sample": 32,
  "exclusion_reasons": {"too_short": 4},
  "last_run_at": "...", "pipeline_version": 2
}
```

Two of the five are not columns, and that is deliberate:

- **`failed`** is a fact about a *run*, not a state an observation can be
  in. An observation that failed to settle is still a correct pending
  observation, and giving it a `FAILED` state would make a transient
  database blip look like corrupted data.
- **`erased`** counts erasures from the **audit trail**, because after an
  erasure there is nothing left in Learning's tables to count. The audit
  log outlives the rows it describes, which is what a deletion record is
  for. The per-context row counts now travel in the
  `memory.subject_erased` event payload, so the trail says what the
  report said.

`replayed` counts superseded generations — rows whose source has since
been observed under a newer pipeline version. It stays at **zero through
ordinary redelivery**, which is what makes it worth watching: a counter
that ticked on at-least-once delivery would be counting the broker.

## 7. Resource usage

Consumer containers, idle at current traffic:

| Container | CPU | Memory |
|---|---|---|
| `learning-observation-consumer` | 0.00 % | **71.9 MiB** |
| `learning-signals-consumer` | 0.00 % | **62.8 MiB** |

Under load (5 000 observations, single process):

| Metric | Value |
|---|---|
| CPU per observation | **0.0109 s** |
| Peak RSS | **90 MB** |
| Database writes per observation | **8.81** |
| — `learning_observations` | 1.00 |
| — `learning_observation_features` | 1.00 |
| — `learning_observation_refs` | 6.95 |

Content refs dominate write volume, at roughly one per message. That is
the price of traceability and it is the right trade: the alternative is
copying message text, which is a second store of customer content with
its own retention.

## 8. Cost model

Storage measured against **compacted** tables. This matters: an earlier
measurement taken over pages a previous run had already allocated read
675 bytes/observation against 2 789 on a cold table — a three-fold error
that would have gone straight into the projection. The harness now
`VACUUM FULL`s before measuring.

| Corpus | Bytes/observation |
|---|---|
| 2 000 | 2 867 |
| 5 000 | **2 789** |

| Projection | Value |
|---|---|
| Per conversation observed | **2.7 KiB** |
| Per million conversations | **2.6 GiB** |
| After one year at 10 000 conversations/day | **9.5 GiB** |
| After one year at 100 000 conversations/day | ~95 GiB |

Includes indexes, features and refs. **Excludes message bodies**, which
Learning references and never copies — that is why the number is small,
and it is a direct dividend of the pointers-not-copies rule.

Phase 1 buys no compute: no model calls, no embeddings, no metered
anything. Storage is the entire cost.

## 9. Verdict

**NOT READY**

Not because anything is broken — the engineering half is measured and
sound, and four defects found here are fixed — but because the gate phase
1.5 was set to clear cannot be cleared on this installation.

**The evidence:**

1. **There is no production traffic.** Five finished conversations, zero
   CSAT responses, twelve days of manual testing. Every volume figure,
   the real language mix, the real exclusion rate and the real outcome-
   change rate are unmeasurable, and those are precisely the inputs
   clustering quality depends on.

2. **The feedback ratio is not yet a measurement.** It reads 0.125 over a
   sample of 32 turns. Charter §17 calls it the first danger metric — the
   number that decides whether phase 2 is safe to run — and 32 turns of
   hand-typed test traffic cannot support that decision.

3. **Feature quality has been tested against real text exactly once, and
   it failed twice.** F1 and F2 were both invisible to a 5 000-sample
   benchmark scoring 1.000 across the board, and both were found the
   moment five real conversations went through. That is a strong signal
   about how much the benchmark is worth, and a reason to expect more of
   the same from a real corpus — not a reason to assume the two found are
   the only two.

4. **The `is_system_generated` fix is forward-looking.** Historical
   messages carry no marker. Any corpus that predates this deploy will
   still feed template vocabulary into clustering unless it is backfilled.

**What clears the gate.** Deploy, let the pipeline observe real traffic,
and re-run the harness:

```
DATABASE_URL=... python scripts/validate_learning_pipeline.py --corpus 0
```

`--corpus 0` reads only real rows. The gate is clear when:

| Criterion | Threshold |
|---|---|
| Observations from real traffic | ≥ 10 000, across ≥ 5 companies |
| Observation window | ≥ 14 days, so a weekly cycle appears twice |
| CSAT responses in the corpus | > 0 — the settle path is untested against real late signals |
| Feedback ratio | measured over ≥ 10 000 turns, and **stable or falling** across two windows |
| `failed` | 0 across ≥ 100 recorded runs |
| Topic sample | reviewed by hand for a third F1 — the two found were found by looking |

Nothing in phase 1 needs to change first. It needs to run.

## See also

- [Learning Platform](./learning-platform.md) — what phase 1 built
- [Phase 1 Verification & Review](./learning-platform-phase-1-review.md)
- [Learning Platform Charter](./learning-platform-charter.md) — §15/§17 metrics, §20 phase gates
