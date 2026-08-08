# Post-Launch Roadmap

**Every remaining item, grouped by when it should be done and why.**

- **GA tag:** `v1.2.0`
- **Baseline:** [V1.0 Baseline](./v1.0-baseline.md) (commit `08a9147`)
- **Sources:** [Technical Debt](./v1.0-technical-debt.md) ·
  [Known Limitations](./v1.0-known-limitations.md) ·
  [RC1 Audit](./v1.0-engineering-audit.md) ·
  [Learning Charter](../architecture/learning-platform-charter.md) ·
  [Architecture Freeze Review](../architecture/architecture-freeze-review.md)

Every item states five things. The last one — **why it was deferred** —
is the most useful field on the page: it is the difference between a
backlog and a record of decisions, and it stops the same argument being
had twice.

Effort is engineering effort, not calendar time. Operational risk is the
risk of **doing** the work, not of leaving it undone.

---

## Priority summary

| | Items | Theme |
|---|---|---|
| **P1 — first month** | 9 | Make the launch safe. Nothing here is a feature. |
| **P2 — this quarter** | 8 | Earn the right to do Phase 3, and unblock mobile. |
| **P3 — future** | 8 | Everything gated on evidence, demand, or both. |

**A recurring pattern:** most of the intelligence work is deferred not
because it is hard but because it is **unearned**. The platform has fewer
than 1,000 production observations and has produced zero trends. Building
inference on top of that would produce confident output with nothing
behind it, which is worse than producing nothing.

---

# P1 — First month

Nothing in this section is a feature. It is the work that makes a live
platform safe to leave running.

## P1-1 · Exercise the off-host backup leg

| | |
|---|---|
| **Business value** | Survival. Without it a host loss is total data loss, and no other item on this page matters. |
| **Engineering effort** | 30 minutes — configuration only. |
| **Operational risk** | None. Adding a destination cannot break the local backup. |
| **Dependencies** | A backup host with SSH access. |
| **Why deferred** | Not deferred by choice — the code shipped and the destination was never configured on the dev host. It is [L-3](./v1.0-known-limitations.md), listed as blocking. |

Also store `BACKUP_PASSPHRASE` off-host. It decrypts the `.env` in every
set; lost with the host, the backups restore a platform that cannot start.

## P1-2 · Point critical alerts at a human

| | |
|---|---|
| **Business value** | Alerting that nobody receives is theatre. This converts every other failure from silent to noticed. |
| **Engineering effort** | 15 minutes. |
| **Operational risk** | Low. Alert fatigue if thresholds prove noisy — tune, do not mute. |
| **Dependencies** | A Slack/PagerDuty destination and an on-call rotation. The rotation is the harder half and is not an engineering task. |
| **Why deferred** | Deliberately: which channel or key receives alerts is a business decision the codebase cannot make. The routing is built and verified end to end. |

## P1-3 · Reclaim 156 MB and get the disk under 80% · [TD-3](./v1.0-technical-debt.md#td-3)

| | |
|---|---|
| **Business value** | The disk is at 93%. A full disk stops Postgres writing and takes the platform down. |
| **Engineering effort** | Minutes — one `REINDEX INDEX CONCURRENTLY`. |
| **Operational risk** | Low with `CONCURRENTLY`. Without it, an ACCESS EXCLUSIVE lock on a table with no rows to rewrite. |
| **Dependencies** | None. |
| **Why deferred** | It was not understood until the RC1 audit. The readiness review recorded it as table bloat and recommended `VACUUM FULL`; the heap is empty and all 156 MB is a pgvector HNSW index, which does not shrink on delete. |

**Answer the second question too:** why does `embeddings` have zero rows?
Either the knowledge base is genuinely empty here, or something deleted
the embeddings and the reindex sweep has not repopulated them.

## P1-4 · Delete two dead environment variables · [TD-1](./v1.0-technical-debt.md#td-1)

| | |
|---|---|
| **Business value** | `PAYPAL_ENVIRONMENT=live` does nothing. An operator could believe they had switched to live payments and still be in sandbox, taking no real money, with no error. |
| **Engineering effort** | 5 minutes, plus ~1 hour for the guard test that stops a third appearing. |
| **Operational risk** | None. Removing a variable nothing reads changes no behaviour. |
| **Dependencies** | None. |
| **Why deferred** | Not deferred — undetected until RC1, and RC1 was documentation-only by instruction. |

## P1-5 · Land or revert the two failing tests · [TD-4](./v1.0-technical-debt.md#td-4)

| | |
|---|---|
| **Business value** | A persistently red suite teaches a team to stop reading test output, and that habit costs more than any two tests. |
| **Engineering effort** | Unknown — owned by the concurrent work that caused it. |
| **Operational risk** | None. |
| **Dependencies** | Whoever owns the routing-decision and version-consistency changes. |
| **Why deferred** | Not ours. Both fail at `HEAD` independently of the release, verified in a clean worktree. |

**GA should not be tagged while the suite is red.**

## P1-6 · Monitor the monitoring · [TD-2](./v1.0-technical-debt.md#td-2)

| | |
|---|---|
| **Business value** | If Prometheus or Grafana stops, dashboards go blank and alerts stop firing — indistinguishable from a healthy, quiet platform. nginx is worse: an edge outage is invisible because Prometheus scrapes the backend directly. |
| **Engineering effort** | ~1 day: a generic `up{job=~".+"} == 0` rule, a blackbox probe through nginx, `blackbox-exporter` added to the monitoring tier. |
| **Operational risk** | Low. New alerts may be noisy for a week. |
| **Dependencies** | None for the two rules. Full coverage needs an **external** dead-man's switch — an alert about Prometheus being down cannot be evaluated by Prometheus. |
| **Why deferred** | The previous release fixed alerting that did not work at all; this is the layer above it. It is the last member of the silent-failure family, and it was found by the RC1 audit rather than being knowingly skipped. |

## P1-7 · Onboarding wizard gating · [spec](../product/tenant-onboarding-wizard.md)

| | |
|---|---|
| **Business value** | Highest-impact change to time-to-first-value. Today a tenant can finish setup with no channel connected — a workspace no customer can reach, reporting itself as configured. |
| **Engineering effort** | ~4 days (+½ day for the optional `onboarding-status` endpoint). |
| **Operational risk** | Low, and contained to onboarding. The main risk is over-gating: requiring things the platform does not actually need. The spec resists this — team invitation stays optional, because a single-owner workspace is legitimate. |
| **Dependencies** | None. Every step uses existing endpoints; the channel test event already exists. |
| **Why deferred** | The wizard was built as a navigation shell around settings panels, which was the right first step and shipped value. Gating requires deriving completion from server state rather than from screens visited — a different design, correctly done second. |

## P1-8 · Navigation redesign · [TD-5](./v1.0-technical-debt.md#td-5) · [proposal](../architecture/navigation-information-architecture.md)

| | |
|---|---|
| **Business value** | Seventeen flat items mixing daily work with one-time setup. An agent scans past fifteen they never open; an administrator gets no hint which must be configured first. Compounds with P1-7 — both are about finding what to do next. |
| **Engineering effort** | ~1 day including tests, i18n for en + ar, and two icons. |
| **Operational risk** | Very low. No routing, permission or backend change; bookmarks survive. RTL needs checking. |
| **Dependencies** | None. |
| **Why deferred** | The sidebar grew feature-by-feature, one entry per milestone, deliberately never pointing at an unbuilt page. That rule is right and is why the ordering carries no meaning. Grouping only became worth doing once the item count made it a problem. |

## P1-9 · Re-run the DR rehearsal against production data

| | |
|---|---|
| **Business value** | The published RTO was measured against a 1.5 MB dump. Once real conversations and attachments exist, that number is fiction unless re-measured. |
| **Engineering effort** | 30 minutes — the script exists and is non-destructive. |
| **Operational risk** | None. Restores into scratch resources; production is read from, never written to. |
| **Dependencies** | Real production data, so this lands at the end of the first month rather than the start. |
| **Why deferred** | Cannot be done before there is production data to rehearse against. |

---

# P2 — This quarter

Two themes: **earning the right to run Learning Phase 3**, and
**unblocking a mobile client**. Neither can be short-circuited.

## P2-1 · B9 — Knowledge versioning

| | |
|---|---|
| **Business value** | A citation is not reproducible today. "What did this article say in March?" cannot be answered, because `knowledge_chunks.article_id` points at the mutable article. Any AI answer citing knowledge cites a moving target. |
| **Engineering effort** | ~3 days. The design exists: a `knowledge_article_versions` table, a pointer, and moving the chunk FK. |
| **Operational risk** | Medium. It changes the retrieval join and touches the embedding pipeline. Reindexing is required, and `embeddings` currently has zero rows — which makes this the cheapest moment there will ever be to do it. |
| **Dependencies** | None technically. It is a **hard precondition** on Learning's contradiction detector. |
| **Why deferred** | "Nothing cites a version today because nothing generates cited answers." Correct at the time, and it stops being correct the moment Phase 3 starts producing knowledge suggestions. |

**Do this before Phase 3, not during it.** Retrofitting versioning under a
live contradiction detector means migrating citations that already exist.

## P2-2 · B10 — Retrieval traces

| | |
|---|---|
| **Business value** | Gap detection — "questions the corpus cannot answer" — is one of Learning's headline outputs and currently ships with only half its evidence: the *agent-answered-without-citing* signal. The other half needs a record of what retrieval actually returned. |
| **Engineering effort** | ~3 days: a `retrieval_traces` table, write path, retention policy. |
| **Operational risk** | Medium. A trace per retrieval on the request path is a write on a hot path, and an unbounded table — it needs a retention policy from day one, not later ([L-4](./v1.0-known-limitations.md) is the cautionary example). |
| **Dependencies** | Lands with B8; they answer the same question from opposite ends. |
| **Why deferred** | Descoped honestly rather than faked: gap detection shipped with the half it could evidence and **says so**. That is the right call — the alternative was a feature that looked complete and reported half the gaps. |

## P2-3 · B8 — The reasoning verifier

| | |
|---|---|
| **Business value** | **Correctness of a safety claim.** "Official Knowledge always wins" is today a rank boost and a class filter on retrieval. Nothing checks that the generated answer is actually supported by what was retrieved, and nothing blocks a restricted-class claim citing no authoritative source. |
| **Engineering effort** | ~2 weeks. `AnswerVerifier` was specified in the Stage 1 design and never built. |
| **Operational risk** | **High.** It sits on the answer path. A verifier that is too strict blocks correct answers; too lenient and it is decoration. It also adds latency to every generated reply. It needs shadow-mode operation before it can gate anything. |
| **Dependencies** | B9 (verifying a citation means verifying a *version*). Pairs with B10. |
| **Why deferred** | Three documents claimed the guarantee was enforced. The chosen fix was the cheap and honest one: **amend the documents to state that authority is advisory**. That closed the correctness-of-claim defect immediately at near-zero risk. Building the verifier remains the real fix and must land before Learning produces knowledge suggestions. |

> This is the clearest example on the page of a deferral that was
> correct. Shipping a rushed verifier on the answer path would have been
> worse than shipping an honest sentence about what the platform does.

## P2-4 · Delta sync and cursor pagination · [Mobile §8.1–8.2](../api/mobile-integration-guide.md)

| | |
|---|---|
| **Business value** | Prerequisite for any mobile client. Offset paging over a live conversation list can show an item twice or skip it entirely. |
| **Engineering effort** | ~3 days: `?updated_since=` on the list endpoint, cursor pagination on conversations and messages. |
| **Operational risk** | Low–medium. Changing pagination on a live endpoint needs the web client updated in the same release, or it breaks. |
| **Dependencies** | None. `conversations.updated_at` is already indexed. |
| **Why deferred** | No client needed it. The web app polls and re-fetches page 1, where offset drift is invisible. It becomes a real defect only when a client tries to sync incrementally. |

## P2-5 · Idempotency keys · [Mobile §8.4](../api/mobile-integration-guide.md)

| | |
|---|---|
| **Business value** | Without them no client can safely retry a `POST` after a timeout — which on mobile is routine, not exceptional. Today the mitigation is "do not auto-retry anything that creates a customer-visible artefact." |
| **Engineering effort** | ~2 days: accept `Idempotency-Key`, store key→result, return the original response on replay. |
| **Operational risk** | Low. Additive; a request without the header behaves exactly as now. |
| **Dependencies** | None. |
| **Why deferred** | The web client runs on a reliable network and does not auto-retry. The need arrives with mobile. |

## P2-6 · Document the WebSocket contract · [Mobile §8.5](../api/mobile-integration-guide.md)

| | |
|---|---|
| **Business value** | Real time exists — `/api/v1/ws/agent` — and is invisible to anyone reading the OpenAPI schema, because FastAPI does not document WebSocket routes. A mobile developer would conclude the platform has no real-time support. |
| **Engineering effort** | ~1 day. Documentation, not code. |
| **Operational risk** | None. |
| **Dependencies** | None. |
| **Why deferred** | The web client was written alongside the server, so its authors never needed the contract written down. The cost only appears with a second client. |

**Cheapest item in P2 by a wide margin.**

## P2-7 · Consumer heartbeat health checks · [TD-7](./v1.0-technical-debt.md#td-7)

| | |
|---|---|
| **Business value** | The current check greps `/proc` — it proves the process exists, not that it is still consuming. A consumer wedged on a blocked `await` passes indefinitely. |
| **Engineering effort** | ~2 hours: touch a heartbeat file after each message; assert freshness. |
| **Operational risk** | Low. |
| **Dependencies** | None. |
| **Why deferred** | Partially mitigated: the per-queue consumer-count alert is the authoritative signal, and RabbitMQ deregisters a consumer when its connection dies. Only a wedged process holding its AMQP connection open evades both. |

## P2-8 · CODEOWNERS · [TD-8](./v1.0-technical-debt.md#td-8)

| | |
|---|---|
| **Business value** | Ownership is now recorded in the baseline — a document nobody is obliged to read. CODEOWNERS puts it on the pull request. |
| **Engineering effort** | 15 minutes. |
| **Operational risk** | None. |
| **Dependencies** | Roles must map to real GitHub teams. |
| **Why deferred** | The register did not exist until RC1, and mapping roles to teams needs teams to exist. |

---

# P3 — Future

Gated on evidence, demand, or both. **None of these should be started
because there is capacity to start them.**

## P3-1 · Learning Phase 3 — Candidate Generation

| | |
|---|---|
| **Business value** | The point of the entire intelligence investment. Learning's contract is *evidence in, candidates out*; today it produces evidence and stops. Candidate generation turns clusters, trends and gaps into reviewable proposals. |
| **Engineering effort** | ~3 weeks: candidate emission, dedupe (`dedupe_key` unique among un-emitted), floors evaluated before any score, suppression records, `MemoryCandidateDetected` emission. |
| **Operational risk** | **High.** It is the first time Learning writes anything consumed outside its own tables. Invariants make this survivable: candidates are transient and deleted at emission, suppression lives only in `suppressions`, and a candidate clears **floors** before any score is considered. A bug here proposes wrong beliefs at scale. |
| **Dependencies** | Phase 3 entry criteria (below), **B9**, and P3-2 — a candidate nobody reviews must not be actionable. |
| **Why deferred** | **Gated on evidence, not effort.** Entry criteria: ≥ 1,000 production observations, ≥ 50 stable clusters, operator review complete, thresholds finalised, no replay defects, no queue lag, no unexpected cluster growth. None are met. Shadow validation returned NOT READY for exactly this reason. No amount of engineering advances these — only production traffic does. |

## P3-2 · Learning Phase 3 — Human Review

| | |
|---|---|
| **Business value** | The **only** path from `OBSERVED` to `AUTHORITATIVE`. Learning's output is a `knowledge_suggestion`, never a published article. This is the control that makes the whole platform safe to trust. |
| **Engineering effort** | ~2 weeks: review queue UI, approve/dismiss/edit, provenance display, audit trail. |
| **Operational risk** | Medium — but **not building it is the higher risk**. A candidate pipeline without a review surface either publishes unreviewed (forbidden by charter) or accumulates silently. |
| **Dependencies** | P3-1. Also needs `intelligence.manage` permission wiring, which exists. |
| **Why deferred** | There is nothing to review. Building a review queue before candidates exist produces an empty screen and a UI designed against imagined data. |

**Ship P3-1 and P3-2 together.** Separating them creates a window where
candidates exist with nowhere to go.

## P3-3 · Trend precision validation

| | |
|---|---|
| **Business value** | Trends are a headline output and are currently unvalidated against real text. `alpha = 0.05` was verified only against synthetic noise (300 uniform p-values → ≤ 1 finding). A trend detector with the wrong threshold reports seasonality that is not there, and people act on it. |
| **Engineering effort** | ~1 week of analysis, assuming data exists. Mostly measurement, not building. |
| **Operational risk** | Low to run; **high to skip**. Confident wrong trends are worse than none. |
| **Dependencies** | **Eight windows of history.** Shadow validation reported zero trends produced — there is literally nothing to judge yet. |
| **Why deferred** | Arithmetic: eight weekly windows cannot exist before eight weeks of production traffic. This is the purest example of a data gate on the page. |

## P3-4 · Experience causal learning

| | |
|---|---|
| **Business value** | "What has historically worked, and what has historically failed" — the highest-value and highest-risk thing the platform could learn. |
| **Engineering effort** | ~4 weeks, most of it inference guardrails rather than pipeline. |
| **Operational risk** | **Highest of any item here.** "Agents repeatedly solve similar problems successfully" is the right instinct and a trap: agents also repeat workarounds, stale prices, promises they should not make, and the phrasing that generates fewest follow-up questions rather than the most correct answer. **A pipeline that clusters on frequency and calls the centroid a best practice will faithfully institutionalise a mistake.** The named confounders — VIP customers rating everything higher, easy tickets resolving regardless of approach, escalation-linked phrasing being a symptom recorded as a cause — each independently produce a confidently wrong result. |
| **Dependencies** | P3-1, P3-2, and the causal guardrails: stratum baselines with sample sizes, comparison before claiming, wording as association rather than mechanism. |
| **Why deferred** | Deferred on **correctness**, not schedule. The negative half of the corpus was missing from an earlier design — only conversations that went well were admitted, which cannot support a causal claim. It also needs the discipline that negative experience is applied as a **re-ranking penalty and a verifier check**, never as a prompt instruction: injecting "do not say X" is a reliable way to make a model say X. |

## P3-5 · Autonomous actions

| | |
|---|---|
| **Business value** | The AI acting rather than proposing — resolving, escalating, updating records without a human. |
| **Engineering effort** | Unknown; not designed. Weeks at minimum. |
| **Operational risk** | **Highest possible.** Every current AI safety property depends on a human being between the model and the customer-visible action. |
| **Dependencies** | P2-3 (the verifier), P3-1, P3-2, and a track record from all of them. |
| **Why deferred** | **Explicitly excluded by design, not merely unscheduled.** The intelligence work "does not make Autopilot more autonomous — every existing gate remains." Learning MUST NOT decide what may be said or done, and there is no configuration flag for that prohibition. Doing this means revisiting the charter, which is a deliberate decision requiring an argument, not a backlog item to pick up. |

> Listed because it was asked for. It should be the last thing built, and
> only after the verifier has a production track record.

## P3-6 · APNs push sender · [Mobile §8.3](../api/mobile-integration-guide.md)

| | |
|---|---|
| **Business value** | Removes an iOS build's dependency on a Firebase project — which some customers will not accept. |
| **Engineering effort** | ~3 days. The `PushSender` interface and factory already exist; this is an addition, not a change. |
| **Operational risk** | Low. Certificate management is the ongoing cost — APNs certificates expire, and expiry is silent. |
| **Dependencies** | An iOS app that needs it, and an Apple developer account. |
| **Why deferred** | FCM covers both platforms via Firebase, which is a supported and normal configuration. Building a second sender before an iOS client exists is maintaining a code path nobody exercises. The architecture anticipated it — hence an interface rather than a hard-coded FCM call. |

## P3-7 · Native mobile application · [L-8](./v1.0-known-limitations.md)

| | |
|---|---|
| **Business value** | Agents answering from a phone without a browser. |
| **Engineering effort** | Months. A separate product with its own release cycle. |
| **Operational risk** | Medium — app-store release cycles mean an old client version is in the field indefinitely, so the API must stay backward compatible for far longer than a web client requires. |
| **Dependencies** | P2-4, P2-5, P2-6; P3-6 for iOS. |
| **Why deferred** | The responsive web app covers the use case at pilot scale. The API foundations already exist — auth with refresh, device registry, FCM, agent WebSocket — which is why the remaining gaps are narrow and specific rather than architectural. |

## P3-8 · Multi-region / alternative topologies · [L-10](./v1.0-known-limitations.md)

| | |
|---|---|
| **Business value** | Latency for distant users; data residency for regulated customers; survival of a regional outage. |
| **Engineering effort** | Months, and it is not one item. Multi-region means solving data residency, cross-region replication lag, and tenant-to-region routing — three separate problems often bundled under one word. |
| **Operational risk** | **High.** It changes every operational procedure on the platform: backup, restore, deployment, migration. The DR rehearsal would need rewriting. |
| **Dependencies** | Tighter RPO ([L-1](./v1.0-known-limitations.md)) and HA ([L-2](./v1.0-known-limitations.md)) first — multi-region without replication is several single points of failure in different places. |
| **Why deferred** | Docker Compose on one host is the only topology built, tested and **rehearsed**. Building a second speculatively means maintaining a deployment nobody runs, and the rehearsed one is worth more than an untested sophisticated one. **Trigger: a customer's procurement requires it.** |

---

## Sequencing

```
P1  ──────────────────────────────────────────────────
     backup ─ alerts ─ disk ─ env ─ tests        (safety)
     monitoring ─ wizard ─ navigation            (quality)
     DR re-rehearsal                             (needs data)

P2  ──────────────────────────────────────────────────
     B9 ──────────┐
                  ├──► B8 verifier                (safety claim)
     B10 ─────────┘
     delta sync ─ cursor ─ idempotency ─ WS docs  (mobile foundations)
     heartbeat ─ CODEOWNERS

P3  ──────────────────────────────────────────────────
     [8 weeks of traffic] ──► trend precision
     [entry criteria met] ──► candidate generation ─┬─► human review
                                                    └─► experience causal
     mobile app ─ APNs
     multi-region                    (customer demand)
     autonomous actions              (charter change)
```

**Two hard orderings:**

1. **B9 before Phase 3.** Retrofitting knowledge versioning under a live
   contradiction detector means migrating citations that already exist.
2. **Candidate generation and human review ship together.** Separately,
   there is a window where candidates exist and nothing can review them.

## What is not on this roadmap

Restated so it is not re-proposed:

- **Exactly-once delivery.** At-least-once with idempotent consumers is
  the correct design.
- **A second configuration resolution path.** One chain, enforced by a
  build-failing test. Nine once disagreed.
- **Direct broker publishing.** Everything goes through the outbox.
- **Removing the catch-all routing rule.** It is what makes "a message
  arrives with nowhere to go" impossible.
- **Domain-layer I/O.** The most load-bearing rule in the codebase.
- **Learning answering conversations, ranking retrieval at request time,
  or deciding what may be said.** Charter prohibitions with no
  configuration flag.

## How to use this

**Before starting an item**, read its *why deferred*. If the reason still
holds, the item is not ready — regardless of available capacity.

**Before adding an item**, fill in all five fields. An item without a
stated business value and a stated reason for its position is a wish.

**When a gate opens** — the observation count is met, a customer demands
a topology — say so explicitly and move the item. Gates that quietly
stop being enforced are how a charter erodes.

---

## See also

- [V1.0 Baseline](./v1.0-baseline.md) — invariants any of this must not contradict
- [Technical Debt Register](./v1.0-technical-debt.md)
- [Known Limitations](./v1.0-known-limitations.md)
- [Learning Platform Charter](../architecture/learning-platform-charter.md) — what Learning is forbidden to do
- [Architecture Freeze Review](../architecture/architecture-freeze-review.md) — B8, B9, B10 in full
