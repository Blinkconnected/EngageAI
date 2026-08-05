# Pattern Detection Dashboard — Reference

Every number on the **Pattern detection** page: what it measures, what a
healthy value looks like, and what to do when it is not.

Backed by `GET /api/v1/intelligence/shadow`, one request for the whole
page. Twelve spinners resolving in an order that tells you nothing is not
a dashboard.

---

## The rule that governs the whole page

**A number the platform cannot compute is shown as `—`, never as zero.**

This is not a display nicety. *"Stability: 0"* says groups are churning —
something is wrong. *"Stability: —"* says nothing has settled yet, which
on a new installation is exactly what should be true. Rendering the
second as the first sends somebody to investigate a fault that does not
exist, and by the third time they will stop investigating anything.

Hover any `—` for the reason it could not be computed.

## The shadow banner

First on the page, and unmissable by design. It states that nothing here
acts on what it shows: no memory written, no articles suggested, nobody
notified, nothing sent onward.

It is a **fact about the build**, not a switch — the emission code does
not exist, and a test fails the build if it appears. It is displayed
because an operator looking at a pattern-detection screen should not have
to read the source to know what it is safe to look at.

## Section 1 — Is it running?

The only section that indicates a *fault* rather than a finding.

| Tile | Measures | Healthy | If not |
|---|---|---|---|
| **Grouping run** | Duration of the last clustering pass | < 30 s at pilot volumes | Rising sharply → group count is growing; check the distribution |
| **Analysis run** | Duration of the last trend/anomaly pass | < 5 s | As above |
| **Since last run** | Time since clustering last ran | < 2 h (it is hourly) | **Beat is not running the sweep.** See the deployment guide's step 3 |
| **Run errors** | Failures across recent runs | **0** | Worker logs; one tenant's data is failing and the others continued |

"Since last run" is measured rather than "queue lag" because these sweeps
are *scheduled*, not queue-driven. There is no backlog to be behind on;
the failure is a run that did not happen, and that is what this catches.

## Section 2 — Is it seeing anything?

| Tile | Measures | Healthy | If not |
|---|---|---|---|
| **Observations** | Completed conversations summarised | Rising with traffic | Flat with traffic → the observation consumer is down |
| **Eligible** | Observations settled enough to group | Rising, trailing Observations by ~72 h | Flat while Observations rise → the settle sweep is not running |
| **Per day** | Mean observations/day over the window | Matches your resolved-conversation rate | Much lower → conversations are being excluded; check the exclusion reasons |
| **Replayed** | Observations re-recorded under a newer extraction version | **0** | Non-zero without a deliberate version bump is a defect. Ordinary redelivery is *not* a replay and must never appear here |

The gap between **Observations** and **Eligible** is where exclusions
live, and it is meant to be non-zero: conversations with no human
content, conversations too short to say anything, and companies that
switched learning off all land there deliberately.

## Section 3 — Is what it found any good?

This is the pilot's actual subject.

| Tile | Measures | Healthy | If not |
|---|---|---|---|
| **Groups** | Groups found so far | Growing, then flattening | Growing without limit → fragmentation |
| **New groups** | Groups created in the window | Falling as the corpus is covered | Rising while observations are flat → threshold drift |
| **Stability** | Membership overlap with the previous run | ≥ 0.7 | Low → groups still forming, or the threshold is moving |
| **Merge rate** | Share of groups absorbed into another | Near 0 | High → the join threshold is too tight and the merge pass is repairing it |
| **Groups of one** | Share of groups with a single member | **< 0.30** | **The clearest threshold signal there is.** Above 0.30 → fragmentation |
| **Grouped** | Share of eligible observations in a group | > 0.7 | Low → most conversations match nothing |
| **Ungrouped** | Eligible observations in no group | Small and stable | Growing → threshold too high |
| **Duplicates** | Observations counted twice | **0, structurally** | Membership is unique per (group, observation); a non-zero value would be a schema violation, not a tuning problem |

### Group sizes

The distribution, in buckets around the size floor of 3 — the point at
which a group stops being a coincidence.

A mean cannot distinguish *"twenty healthy groups"* from *"one enormous
group and nineteen singletons"*, and those need opposite responses. So
the shape is shown rather than summarised. The `1` bucket is coloured as
a warning because it is the failure signal, not merely a count.

- **Mass in 1–2** → threshold too high to group anything.
- **One bucket at 100+ holding most of the corpus** → too low to separate
  anything.
- **Mass in 3–25** → working.

### Findings

Trend and anomaly counts. **Precision is deliberately absent**, and the
card says so rather than showing an empty chart.

Precision needs a verdict — somebody saying *"that one was real"* — and
shadow mode shows findings to nobody and collects nothing. A precision
figure here would be a guess wearing a percentage sign, and somebody
would eventually decide from it.

## The similarity threshold

The one control on the page, and the only thing here that changes what
the platform finds. Behind `intelligence.manage`; everyone with
`intelligence.read` can see it and cannot move it.

- The slider stops at the **measured** safe range. Outside it, clustering
  either conflates distinct problems or fragments one problem into
  invisibility — both measured, see the [shadow validation report](./learning-platform-shadow-validation.md).
- A pending change shows a warning: existing groups were built under the
  current value, are **kept**, and are not comparable to what follows.
- The **reason** field is recorded in the audit log. It is what explains
  the change six months later, when the numbers alone no longer do.
- Nothing regroups until the next hourly sweep.

Every change is audited with the old value, the new value, who made it,
the reason, and how many grouped conversations were built under the
previous setting.

## Permissions

| Permission | Sees | Changes |
|---|---|---|
| `intelligence.read` (Owner, Admin) | Everything on the page | Nothing |
| `intelligence.manage` (Owner) | Everything | The threshold |
| Agents | — | — |

Not on Agent by design: a group is a set of customer conversations seen
sideways — provenance counts, outcome attribution, extracted entities —
which is an operator's view of the platform's own behaviour rather than
part of an agent's working day.

## Beyond the page

Three endpoints the dashboard does not render, for when a number looks
wrong:

| Endpoint | Answers |
|---|---|
| `GET /intelligence/unclustered` | *Which* observations did not group, with the reason for each |
| `GET /intelligence/clusters/{id}` | Every member of a group, with the similarity it joined at |
| `GET /intelligence/clusters/{id}/neighbours` | The nearest other groups, and whether the platform would merge them |

The last is the threshold diagnostic that matters: two groups a person
reads as the same thing, sitting below the merge threshold, *is* the
evidence the threshold is wrong — and no aggregate can show it.

## See also

- [Operator handbook](./learning-platform-operator-handbook.md) — how to judge what you see
- [Pilot readiness checklist](./learning-platform-pilot-checklist.md)
- [Deployment guide](../deployment/learning-platform-pilot.md)
