# Eight-Week Production Pilot Plan

Companion to the [Operational Readiness Review](./operational-readiness-review.md).
The review says **NOT READY** and lists six blocking items; this plan
starts the week after they are cleared.

Eight weeks is not an arbitrary round number. Trend detection compares
eight weekly windows, so **the platform cannot produce its first trend
until week eight** regardless of traffic. A shorter pilot would be judging
clustering only, and calling it a judgement of the platform.

---

## Week 0 — Preconditions

Nothing below starts until all six are done and verified. Each has a
named artefact, because "we did that" is not evidence.

| # | Item | Evidence required |
|---|---|---|
| 1 | Real alert contact point | A screenshot or log of one alert reaching a human |
| 2 | Backups scheduled, off-host | Two consecutive automated backups present off-host |
| 3 | Restore rehearsed | A restored database, row counts compared, time recorded → this is the RTO |
| 4 | Dead-letter exchanges | A deliberately poisoned message landing in the DLQ, alert fired |
| 5 | `/metrics` restricted | `curl` from outside the monitoring network returns 403 |
| 6 | Prod overlay complete | `docker compose -f …prod.yml config` lists all consumers with limits |

**Gate:** all six, verified by someone other than whoever implemented
them.

---

## Weeks 1–2 — Does it stay up?

Learning is enabled for **one pilot company** with real conversation
volume. Nothing else changes.

**Goals**
- The stack runs for fourteen days without unplanned restarts.
- Every scheduled sweep runs on its cadence, every time.
- Observation ingestion keeps pace with resolved conversations.

**Metrics to watch daily**

| Metric | Where | Healthy |
|---|---|---|
| Run errors | Pattern detection → Run errors | 0 |
| Time since last run | Pattern detection | < 2 h |
| Consumer restarts | `docker compose ps` | 0 unplanned |
| DLQ depth | RabbitMQ / new alert | 0 |
| Observations vs resolved conversations | Dashboard vs Reports | Within 10 % after the 72 h settle window |
| Container memory | `docker stats` | Flat — a rising line over days is a leak |

**Success criteria**
- Zero unplanned restarts.
- Zero run errors.
- Zero dead-lettered messages.
- Observation coverage of finished conversations ≥ 90 %.

**Rollback criteria — stop the pilot immediately if any occur**
- Any cross-tenant data appears anywhere.
- Any Learning write outside `learning_*` tables.
- Sustained consumer memory growth (> 20 % week over week).
- Database write latency regression > 20 % against the pre-pilot baseline.

**Operator responsibilities:** one named operator checks the dashboard
each weekday and records the six metrics above in a running log. The log
is the deliverable, not the checking.

**Gate to week 3:** fourteen consecutive days, zero errors, memory flat.

---

## Weeks 3–4 — Is it seeing the right things?

First substantive review of content rather than uptime.

**Goals**
- Enough eligible observations to form clusters (target ≥ 300).
- First operator read of what the platform is grouping.
- Confirm the exclusion reasons are the ones expected.

**Metrics to watch**

| Metric | Healthy | If not |
|---|---|---|
| Eligible fraction | > 0.5 | Read the exclusion reasons — is the platform excluding more than expected? |
| Feedback ratio | Stable or falling | **Rising is the danger signal.** The platform is learning from its own output |
| Groups | Growing | Flat with rising eligible → threshold too high |
| Groups of one | < 0.30 | Threshold too high |

**The feedback ratio is the one to take seriously.** It is the share of
observed content the platform itself wrote. Phase 1.5 found the CSAT
survey template being counted as human evidence; the fix is in, but this
is the number that would catch the next instance, and it is invisible in
every other metric.

**Operator work this fortnight**
- Open ten clusters. For each, write one sentence describing every
  conversation in it. Record which needed an "and also".
- Read the ungrouped list. Judge whether those conversations genuinely
  match nothing.
- Record the size distribution shape.

**Success criteria**
- ≥ 300 eligible observations.
- ≥ 10 clusters past the floors.
- ≥ 7 of 10 reviewed clusters describable in one sentence.
- Feedback ratio stable or falling.

**Rollback criteria**
- Feedback ratio rising week over week → **stop and investigate before
  continuing.** Something is feeding the platform its own output.
- Groups of one above 0.60 → clustering is producing nothing usable.

**Gate to week 5:** the ten-cluster review is written down, with the
failures named.

---

## Weeks 5–6 — Is the dial in the right place?

The one intervention window. Thresholds are tuned here and **nowhere
else**, because a threshold changed in week seven invalidates the
stability measurement week eight depends on.

**Goals**
- Settle on a join threshold for this corpus.
- Confirm stability once the threshold stops moving.
- Confirm cluster growth is decelerating rather than tracking observations.

**Method**
- Change **one threshold at a time**, in steps of 0.05, with a written
  reason. The audit row is what explains the change later.
- Wait a full sweep before judging; nothing regroups until then.
- Judge on the **distribution**, not the count. More clusters is not
  better; describable clusters are better.
- Do not touch the merge threshold. It repairs a badly-set join threshold
  only partially, so moving both makes neither attributable.

**Metrics**

| Metric | Target by end of week 6 |
|---|---|
| Groups of one | < 0.30 |
| Size distribution | Mass in the 3–25 buckets |
| Stability | ≥ 0.7 across two consecutive sweeps |
| Cluster growth vs observation growth | Growing more slowly |
| Threshold changes | None in the final seven days |

**Success criteria:** a threshold nobody wants to change, and a written
record of why it is that value.

**Rollback criteria**
- No threshold in the permitted band produces a usable distribution →
  the lexical approach is wrong for this corpus. That is a finding worth
  having, and it means **stop**, not tune harder.

---

## Weeks 7–8 — Is what it finds worth acting on?

The first weeks in which trend detection can produce anything, because
it needs eight windows.

**Goals**
- First trends and anomalies against real traffic.
- Operator judgement on whether they are real.
- Complete the phase 3 readiness checklist with evidence.

**Metrics**

| Metric | Watch for |
|---|---|
| Confirmed trends | Any at all — and whether an operator agrees |
| Provisional vs confirmed | Far more provisional than confirmed means effects are not surviving a second window |
| Anomalies by kind | A single kind dominating suggests a threshold problem, not a business one |
| Replay rate | Must be 0 unless a version was deliberately bumped |

**Operator work**
- For each confirmed trend: *would I have noticed this without the
  platform, and is it true?* Record both answers.
- For each anomaly: *is this a real operational event?* Record the answer.
- These recorded verdicts are the **first precision data the platform has
  ever had**. Shadow mode collects none by design, so this fortnight is
  the only source.

**Success criteria**
- ≥ 1 000 observations, ≥ 50 stable clusters.
- ≥ 1 confirmed trend that an operator agrees is real.
- Anomaly verdicts recorded for every anomaly raised.
- All seven checklist criteria pass with evidence.

**Rollback criteria**
- Every trend judged spurious → the statistics are not protecting
  against this corpus's noise, and phase 3 would propose nonsense.

---

## Release gates

Sequential. Each is a decision, not a status update.

| Gate | When | Decision |
|---|---|---|
| **G0** | End week 0 | Six blocking items cleared → enable for one company |
| **G1** | End week 2 | Stable for 14 days → begin content review |
| **G2** | End week 4 | Clusters describable, feedback ratio not rising → begin tuning |
| **G3** | End week 6 | Threshold settled and unchanged for 7 days → begin trend evaluation |
| **G4** | End week 8 | Checklist passes with evidence → **recommend phase 3** |

**Any gate can return CONTINUE PILOT**, which extends by two weeks and
repeats that gate. A gate that has been failed twice is a signal to stop
and reconsider the approach rather than to extend a third time.

## Operator responsibilities

| Role | Responsibility | Cadence |
|---|---|---|
| **Pilot operator** | Dashboard check, running log, cluster reviews, trend verdicts | Daily check, fortnightly review |
| **On-call engineer** | Alert response, DLQ triage, restart decisions | As paged |
| **Reviewer** | Gate decisions; must not be the person who implemented the gate's subject | At each gate |

The separation on the last row matters more than it looks. Five of the
six week-0 items are things whose implementer would naturally assume they
work; a restore that has only been verified by the person who wrote the
restore script has not been verified.

## What is deliberately not in this plan

- **No expansion beyond one company** before G4. A second tenant adds
  nothing to the question being asked and doubles the blast radius.
- **No emission.** Learning stays in shadow mode for all eight weeks.
  Phase 3 is what changes that, and it is gated on G4.
- **No threshold changes after week 6.** Stability cannot be measured
  against a moving threshold.
- **No new features.** The pilot measures what exists. Anything added
  mid-pilot invalidates the weeks before it.

## See also

- [Operational Readiness Review](./operational-readiness-review.md) — the six blockers
- [Learning pilot deployment guide](./learning-platform-pilot.md)
- [Operator handbook](../architecture/learning-platform-operator-handbook.md) — how to do the cluster reviews
- [Pilot readiness checklist](../architecture/learning-platform-pilot-checklist.md) — the G4 criteria
