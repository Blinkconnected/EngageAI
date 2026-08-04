# Service-centric migration — proposal

*Moving every company from Queue-centric to Service-centric configuration
without changing what any of them experiences on the day it happens.*

**Status: proposed. No code written.** Traced against the implementation, not
the intent; every claim below was checked against the source or the live
database.

---

## 1. What the dual mode actually is today

It is not two clean modes. It is **nine independent fallbacks**, and they do not
agree with each other. That is the real finding, and it changes the shape of
the plan.

| Fact | Service path | Fallback when no service | Uniform? |
|---|---|---|---|
| Service resolution | `default_stages()` pipeline | `NOT_CONFIGURED`, continue | — |
| ROUTING policy | `Policy.ROUTING` evaluated + recorded | **skipped entirely** | ❌ |
| Queue selection | `service.queue.logical_queue_id` | Routing rules | ✅ documented fallback |
| SLA targets | `service.sla` | Queue policy → platform default | ✅ one resolver |
| AI engagement | `Policy.AI_ENGAGEMENT` evaluated + recorded | 5 inline conditions, **no decision written** | ❌ |
| AI pickup delay | `service.ai.pickup_delay_seconds` (default 30) | **hard-coded `0`** | ❌ |
| AI confidence threshold | `service.ai.confidence_threshold` | Company setting | ✅ one resolver |
| Business hours | `service.business_hours_id` | — | ❌ **field is read by nothing** |
| Ownership policy | — | `OwnershipRules()` | ❌ **never configured anywhere** |

Three of these are genuine, well-built fallback chains with a single resolver.
Three are ad-hoc branches that silently change behaviour. And two are fields
that exist in the model and are read by nothing at all.

**So Stage 1 is not "add hybrid support".** Hybrid support already exists — it
is simply inconsistent. Stage 1 is *making it uniform*, and doing that closes
G1 and G4 from the AI validation report as a side effect.

### Two fields that are not what they appear

- **`ServiceContext.business_hours_id`** is read by no code path. Business
  hours live in `Company.settings["business_hours"]` — one calendar per
  company — and the per-queue `SlaPolicy.business_hours_aware` boolean only
  decides whether the SLA respects it. A migration cannot "preserve per-service
  business hours" because no company has any.
- **Ownership policy** is never configured. Nothing anywhere passes `rules=` to
  `OwnershipService.transfer`, so every conversation runs on `OwnershipRules()`
  defaults. There is nothing to preserve here either — but there is something
  to *not silently invent*.

Both belong in the target architecture. Neither can be described as "migrated",
and a plan that claimed to preserve them would be preserving nothing.

---

## 2. The risk that determines the whole design

> **The moment a company has one active Service, every conversation resolves to
> a Service.**

`FallbackStage` resolves to the company's default service, or failing that
*"the first service in the directory"*. It only answers `NOT_CONFIGURED` when a
company has **no active services at all**.

So creating a General Service for an existing company is not additive. On the
very next inbound message it flips that company from every fallback in the
table above onto the service path simultaneously. With stock defaults, that
means:

| | Before migration | After a naive migration | Effect |
|---|---|---|---|
| `AiPolicy.enabled` | company settings say on | **`False`** (the model default) | **AI silently switches off** |
| `pickup_delay_seconds` | `0` (hard-coded fallback) | `30` | AI stops answering immediately |
| SLA targets | queue policy: 3 / 15 min | `SlaTargets()` — all `None` | **clocks stop being measured** |
| Queue selection | routing rules | `service.queue`, unset → falls back | unchanged, by luck |
| AI policy decisions | none written | written | improvement |

Two of those are outages dressed as a migration. A company using AI would stop
using AI; a company measuring an SLA would stop measuring it. Neither would
raise an error, and both would be discovered by a customer.

**Therefore the governing rule of this migration:**

> A migrated Service must be seeded with the values that company **resolves to
> today**, never with model defaults. The migration copies the *effective*
> configuration, not the *declared* one.

Everything in Stage 2 follows from that sentence.

---

## 3. Target architecture

```
Company
  └── Service                 ← business configuration. Versioned, immutable,
       │                        frozen onto each conversation by value.
       │                        "What we promise, for this line of business."
       └── Logical Queue       ← runtime execution. Where work waits and who
            │                    may take it.
            └── Runtime lanes  ← capacity. standard / priority / overflow.
```

**Service answers *what we promise*.** SLA targets, AI policy, business hours,
required skills, supervisors, forms, and — through `extras` — every module not
yet built, including Company Intelligence.

**Queue answers *where work waits*.** Assignment strategy, agent eligibility,
autopilot opt-in, depth.

The split already exists in the model and is already correct. `ServiceContext`
is a frozen value object carried onto each conversation, with `extras` as an
explicit growth seam and `setting()` returning the caller's default for modules
a stored version predates. **That is exactly the property Company Intelligence
needs**, and it is the strongest argument for doing this before building it: a
module added later needs no migration and cannot change how already-bound
conversations behave.

### What moves, and what does not

| Configuration | Today | Target |
|---|---|---|
| SLA targets | Queue → `SlaPolicy`, or legacy queue minutes | **Service** |
| AI enabled / threshold / delays | Company settings + queue `autopilot_enabled` | **Service** (company stays the kill switch) |
| Business hours calendar | `Company.settings` | **Company** (unchanged — one calendar) |
| Business-hours awareness | `SlaPolicy.business_hours_aware` | **Service** |
| Ownership policy | nowhere | **Service** (new capability, not a migration) |
| Required skills | `queue_required_skills` | **Service** |
| Assignment strategy | Queue | **Queue** (runtime) |
| Autopilot opt-in | Queue | **Queue** (runtime gate stays; Service decides policy) |
| Capacity / overflow | Runtime lanes | **Queue** (runtime) |
| Routing rules | Company | **Company** (they select a Service, not a Queue) |

**The company-wide AI kill switch stays company-wide.** A compliance officer
switching AI off must not have to visit every service. Service policy is
narrower than the kill switch and never overrides it.

---

## 4. The migration

### Stage 1 — Uniform resolution *(no company changes behaviour)*

Make every fact in §1 resolve through one chain, expressed once:

```
Service → Queue → Company → Platform default
```

For each of the six inconsistent facts, this means:

- **AI pickup delay** — fall back to the domain default (`30`), not `0`. *This
  changes behaviour for every company* and is the G1 decision from the AI
  validation report. It belongs here rather than in Stage 2, so it lands as
  one deliberate, announced change rather than as a side effect of a data
  migration.
- **AI engagement policy** — evaluate `Policy.AI_ENGAGEMENT` for every
  conversation, service or not, building an `ExecutionContext` from resolved
  values. Closes G4; every company gains "why did AI answer this".
- **ROUTING policy** — likewise.
- **Business hours awareness** — resolve service → queue policy → company.
- **Ownership policy** — introduce a resolver returning `OwnershipRules()`
  today, so the seam exists before anything configures it.
- **AI hand-off decision** — write the `AI_RELEASED` decision the Inspector
  already renders (G2).

**Exit criteria.** Every subsystem reads through a named resolver. No
`if service is not None` branch decides *behaviour* anywhere — only *provenance*
(which tier answered), which is recorded.

**Invariant introduced.** *No configuration fact has more than one resolver,
and every resolver reports which tier answered.* Enforceable by an AST guard in
the shape of the ownership guard: the set of modules reading
`service.ai.*` / `queue.sla_policy_id` / `Company.settings["ai"]` directly is an
allow-list of resolvers.

### Stage 2 — Automatic migration *(data, still no behaviour change)*

For every company with no active service, create **one Service per live logical
queue**, seeded from what that company resolves to *today*:

| Service field | Seeded from |
|---|---|
| `name` | the queue's name |
| `queue.logical_queue_id` | that queue |
| `sla` | `resolve_sla_targets(service=None, queue=<that queue>)` — the effective targets |
| `ai.enabled` | the company's *effective* AI state for that queue: `is_ai_enabled(settings) AND queue.autopilot_enabled` |
| `ai.pickup_delay_seconds` | whatever Stage 1 made effective |
| `ai.confidence_threshold` | `None` — so the company setting keeps deciding |
| `business_hours_aware` | the queue's `SlaPolicy.business_hours_aware` |
| `required_skill_ids` | `queue_required_skills` for that queue |

Then set the company's **default service** to the one built from the queue its
catch-all rule targets, so `FallbackStage` resolves the same way routing
already does.

**Ordering matters.** Stage 2 must run *after* Stage 1, because Stage 1 is what
makes "the effective value" a thing you can read from one place. Running Stage 2
first means seeding from six different ad-hoc branches.

**In-flight conversations are not re-bound.** A conversation already running
keeps its binding — or its absence — and finishes the way it started. Only
conversations created after the migration bind to the new services. This is the
existing `is_stale` guarantee applied to the migration itself: an administrator
changing configuration never reaches into conversations already in progress.

**Idempotent, and skips companies that already chose.** A company with any
active service is left alone entirely: they have made decisions this migration
must not overwrite.

### Stage 3 — Compatibility mode *(one writer, two readers)*

- Service becomes the **only** place new configuration can be written. Queue-level
  SLA fields and `SlaPolicy` attachment become read-only in the API and are
  labelled *legacy* in the UI, with a link to the service that now owns them.
- Registration creates the full chain: **Company → General Service → General
  Queue → catch-all rule**, with the Service as the company default.
- A **drift check** runs as a scheduled job: for every company, compare
  service-resolved values against queue-resolved values and report divergence.
  Nothing auto-corrects. Divergence means somebody edited legacy config through
  a path that should no longer exist, and that is a bug to find rather than a
  value to overwrite.
- Onboarding gains a Service step. This is also what closes B4 (the go-live
  checklist) properly: "you have a service, a queue, a rule and a channel" is a
  readiness statement a company can be shown.

**Exit criteria.** Zero companies without a service. Drift check clean for one
full billing period.

### Stage 4 — Legacy removal

- Drop `queues.first_response_target_minutes`, `queues.resolution_target_minutes`,
  `queues.sla_policy_id`.
- Remove the queue tier from `resolve_sla_targets`; the chain becomes
  Service → Platform.
- Remove the inline five-condition AI branch.
- `SlaPolicy` either becomes a Service-level template or is removed.
- Queue keeps only runtime concerns: assignment strategy, skills eligibility,
  autopilot opt-in, lanes, depth.

**Not before** Stage 3's drift check has been clean for a full period, and not
in the same release as anything else.

---

## 5. Invariants

Each is meant to be enforced by something that fails, in the shape of the
existing wiring and ownership guards.

1. **Every active company has at least one active Service.** *(from Stage 3)*
2. **Every conversation resolves to exactly one Service**, and the resolution
   is recorded with the strategy that produced it.
3. **One resolver per configuration fact.** No subsystem reads a raw
   configuration column; it asks a resolver, and the resolver reports the tier.
4. **A Service version is immutable, and a conversation runs on the version it
   bound to.** Already true; the migration must not weaken it.
5. **The company kill switch is never overridden by a Service.**
6. **Migration is value-preserving.** For every migrated company, the effective
   configuration after Stage 2 equals the effective configuration before it.
   This is the invariant the verification in §7 exists to prove.
7. **`extras` is the only place a new module stores service configuration**, so
   Company Intelligence needs no schema change and no re-migration.

---

## 6. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **Creating a Service silently disables AI** (`ai.enabled` defaults `False`) | **critical** | Seed from effective state, never defaults. Verification §7 asserts AI reachability per company before and after. |
| R2 | **Creating a Service silently stops SLA measurement** (`SlaTargets()` is all-`None`) | **critical** | Same. Assert clock counts per company before and after. |
| R3 | Stage 1's pickup-delay change makes AI wait 30s where it answered instantly | high | It is a deliberate, announced behaviour change — the G1 decision — not a side effect. Ship alone, with the option to seed `0` per company. |
| R4 | A company with many queues gets many Services and an unusable directory | medium | One Service per **live** queue only; most companies have one. Report the count before running. |
| R5 | `FallbackStage` picks "the first service in display order" — arbitrary for multi-queue companies | medium | Always set an explicit company default in Stage 2. Never rely on display order. |
| R6 | In-flight conversations behave inconsistently with new ones during Stage 2 | low | Deliberate and already the model's guarantee (`is_stale`). Documented, visible in the Inspector. |
| R7 | Queue deleted after a Service binds to it | low | Already handled: `SET NULL`, and the Policy Engine reports `NO_QUEUE_CONFIGURED` rather than crashing. |
| R8 | Stage 4 drops columns still read by a report or export | medium | Grep-and-guard before dropping; keep the columns one release after the code stops reading them. |
| R9 | Two sources of truth persist because Stage 3 stalls | medium | Stage 3 has an explicit exit criterion. A compatibility mode with no end date is the failure this whole plan exists to avoid. |

---

## 7. Verification

**Before/after equivalence is the whole test.** For every company, capture a
configuration fingerprint before Stage 2 and assert it is unchanged after:

```
per company, per live queue:
  effective SLA targets          (first response, resolution, queue, next)
  effective AI enabled           (company switch AND queue opt-in)
  effective AI confidence threshold
  effective pickup delay
  business-hours awareness
  catch-all queue destination
```

- **Dry-run mode.** The migration reports the fingerprint diff for every
  company and writes nothing. No installation is migrated before its diff is
  empty.
- **Replay verification.** For a sample of recently closed conversations,
  re-resolve configuration under the new path and assert the same SLA targets
  and the same AI decision would have been produced.
- **Live smoke test**, in the shape of the one run this milestone: one real
  conversation per migrated company through the full chain, asserting routing,
  SLA source, ownership, AI engagement and metering all still agree.
- **Drift job** as a standing check through Stage 3.

---

## 8. Rollback

| Stage | Reversible? | How |
|---|---|---|
| 1 | Yes | Code-only. Revert the release; resolvers fall back to prior branches. No data written. |
| 2 | **Yes, and this is the point** | The migration only *adds* services. Rollback = deactivate the services it created (`is_active = false`), which returns every company to `NOT_CONFIGURED` and the legacy path, because `FallbackStage` only skips when no **active** service exists. Reversible with one UPDATE, no data loss, no history rewritten. |
| 3 | Partially | API/UI restrictions revert with the release. Services created by administrators during Stage 3 are real configuration and stay. |
| 4 | **No** | Dropped columns are gone. This is why Stage 4 waits for a clean drift period and ships alone. |

Stage 2's rollback property is worth designing *for*: it is the reason the
migration must **add** services rather than transform queues. A migration that
rewrote queue rows would not have this.

---

## 9. Recommendation

**Do Stage 1 before Company Intelligence. Do not do Stage 2 yet.**

Stage 1 is where the architectural value is. It collapses nine fallbacks into
one chain, closes G1, G2 and G4 from the AI validation report, and gives every
future module — Company Intelligence first — a single place to ask what a
company has configured. It writes no data and is fully reversible.

Stage 2 is a data migration whose two critical risks (R1, R2) are both
"silently turns off something a customer is relying on". It should run only
after Stage 1 has made "the effective value" readable from one place, and only
behind the dry-run in §7.

Building Company Intelligence on the current dual mode would mean writing the
tenth fallback. Building it after Stage 1 means writing none: it reads the
resolver, stores its settings in `extras`, and inherits the version-freezing
guarantee for free.

**Freeze recommendation: adopt §3 as the target architecture and §5 as
invariants now.** They constrain Company Intelligence correctly whether or not
Stage 2 has run.
