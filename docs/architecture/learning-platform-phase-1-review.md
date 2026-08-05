# Learning Platform — Phase 1 Verification & Review

**Scope reviewed:** Stage 3, phase 1 (Observe) as built, against the
[Learning Platform Charter](./learning-platform-charter.md).
**Verdict:** see [§6](#6-verdict).

This document is written to be disagreed with. Where phase 1 narrowed the
charter it says so with the reason; where a charter clause is not yet
enforced by anything it says that too, rather than counting design intent
as delivery.

---

## 1. Scope compliance

The instruction was phase 1 only, with an explicit exclusion list. Held.

| Excluded from phase 1 | Present in the codebase? |
|---|---|
| Clustering | No — no table, no service, no reference |
| Pattern detection | No |
| Trend detection | No |
| Knowledge candidates | No |
| Memory candidates | No — and a guard asserts Learning calls no memory write |
| Gap detection | No |
| Contradiction detection | No |
| Suggestions | No |
| Human review | No — the API is read-only |
| Any LLM reasoning beyond feature extraction | No model call exists in any Learning module; extraction is tiers 0–1, pure Python |

Nothing is stubbed either. There is no `# TODO: clustering` waiting to be
filled in, because a stub is a claim about a design that has not been
reviewed.

## 2. Charter invariants — what is enforced, and by what

| # | Invariant | Status | Enforced by |
|---|---|---|---|
| **I-1** | No observation or query spans tenants | **Enforced** | `TenantMismatchError` on assembly; every repository method company-scoped except the idempotency lookup (documented, verified by the caller); `TestTenantIsolation` covers repository and API |
| **I-2** | Learning writes only its own tables | **Enforced** | AST guard: no foreign model constructed, no foreign `insert`/`update`/`delete`, no Learning row built outside Learning |
| **I-3** | Nothing reaches Knowledge without a human | **Vacuous in phase 1** | No code path from Learning to Knowledge exists. Becomes a real assertion in phase 3 |
| **I-4** | The evidence graph is acyclic | **Enforced** | `ROUTING_KEYS` of both consumers parsed and asserted free of `memory.*`, `learning.*`, `intelligence.*` |
| **I-5** | `is_ai_generated` never evidence; `is_ai_assisted` never corroborates | **First half enforced.** Second half is Memory's, in phase 4 | Filtering happens *before* extraction; integration test proves an AI turn's vocabulary does not reach the topics |
| **I-6** | Outcome from `conversation_outcome.derive`, never recomputed | **Enforced** | Learning is the only caller of `OutcomeInputs`; the settle path re-derives nothing; attribution tested for AI, human and unknown resolvers |
| **I-7** | Only settled observations are eligible | **Enforced structurally** | `settled` is a column, `state` is derived from it; nothing yet consumes eligibility because nothing downstream exists |
| **I-8** | Candidates transient, suppression separate | **Not applicable** | Phase 2 |
| **I-9** | Floors before scores | **Not applicable** | Phase 2 |
| **I-10** | Multiple-testing correction, ≥2 windows | **Not applicable** | Phase 2 |

I-3, I-8, I-9 and I-10 are honestly "not yet real" rather than "passing".
A test that asserts the absence of code that was never written proves
nothing about the code that will be.

## 3. Deviations from the charter

Two, both narrowings. Neither adds capability, and neither was silent.

### 3.1 Tiers 0–1, not tiers 0–2

Charter §20 lists "tiers 0–2 features" as phase 1's delivery. Phase 1
ships tiers 0 and 1.

The charter contradicts itself here, and §9 is the stronger clause:
Learning may register and write only `CLUSTER_CENTROID` in the shared
embeddings table. Tier 2 exists to place an observation against existing
clusters; there are no clusters, and an observation embedding has no
owner type it is permitted to use. Implementing tier 2 in phase 1 would
have required either a second embedding owner type the charter does not
grant, or writing vectors that nothing may read.

**Consequence:** phase 2 gains tier-2 extraction along with clustering,
which is where the two are useful together anyway. **Cost:** the
extraction-cost measurement that gates phase 1 → 2 covers tiers 0–1 only,
so the embedding cost of the corpus is still an estimate rather than a
measurement. That is a real gap in the gate and is stated as such.

The `CLUSTER_CENTROID` registration in `domain/embedding_owners.py` that
§9 permits is deferred with it. That file's convention is to pre-declare
an owner type before anything writes it — `MEMORY_FACT` is there
unwritten — but a declaration names the *one module* allowed to write it,
and phase 2 has not chosen that module. Naming one now would be inventing
a filename and calling it a boundary.

**Requires your decision:** accept the narrowing, or require tier 2 in
phase 1 with an additional embedding owner type (`OBSERVATION`) added to
`domain/embedding_owners.py` and to charter §9.

### 3.2 A fourth table

Charter §8 names `observations` and `observation_features`. Phase 1 also
creates `learning_observation_refs`, because §10's traceability
requirement — every observation fully traceable to evidence — needs
somewhere to put the pointers, and the charter's table list omitted it.

It is Learning-owned, `company_id`-scoped, derived and rebuildable like
the rest. Table names are prefixed `learning_` for namespace clarity in a
database with sixty tables.

**Requires your acknowledgement**, not a decision — there was no way to
satisfy §10 without it.

### 3.3 Deferred within phase 1: the replay endpoint

Charter §20 promises "a windowed replay is available through the API for
a company that asks", under `intelligence.manage`.

Replay **safety** is built: `UNIQUE (source_id, pipeline_version)` makes
re-assembly idempotent, and including the version in the key makes a bad
extractor recoverable rather than permanent. The **trigger** is not, and
belongs with phase 2: in phase 1 a replay is a version bump plus a
re-consume, which is a deploy-time act, and there is nothing to replay
*into* until clustering exists. Building the endpoint now would mean
building a replay worker — new machinery outside "observation ingestion".

## 4. What the verification actually showed

### 4.1 Suites

Run against the **committed change in isolation** — a worktree built from
the staged tree alone — and compared line for line against a worktree of
pristine `HEAD`. That comparison is the point: the repository also
contains an unrelated in-flight refactor, and a suite run on the working
tree cannot tell you which change caused what.

| Suite | Result |
|---|---|
| `tests/unit/test_learning_domain.py` | 28 passed |
| `tests/unit/test_learning_writes_only_its_own_tables.py` | 7 passed |
| `tests/integration/test_learning_platform.py` | 32 passed |
| `tests/unit` (whole) | 1686 passed, 6 failed |
| `tests/unit` at pristine `HEAD` | 1650 passed, **the same 6 failed** |
| `tests/integration` (whole) | 1496 passed, 1 failed |
| `tests/integration` at pristine `HEAD` | 1464 passed, **the same 1 failed** |
| Whole backend suite on the working tree | 3215 passed, 1 failed |
| Frontend (`vitest`, 53 files) | 470 passed; lint and `tsc` clean |
| `ruff check` | clean |
| `ruff format --check` | one file — `api/deps.py`, already unformatted at `HEAD` |
| `mypy` (524 files) | 8 errors, **the same 8 as at `HEAD`** |

Every pre-existing failure was checked to fail *for the same reason* on
both trees, not merely to share a name:

- `test_routing_decisions::test_every_reason_code_has_a_decision_and_a_sentence`
  — four AI-autopilot `RoutingDecisionReason` codes have no rendering. A
  different enum from `PolicyReason`, which is the one Learning extends.
- `test_ai_queue_worker::test_a_company_with_no_services_asks_no_policy`
  — identical assertion, identical line, on both trees.
- Five in `test_sla_target_resolution` — the in-flight SLA refactor's
  territory; they pass on the working tree, which is why the working-tree
  run shows one failure and the pristine-`HEAD` run shows six.

Phase 1 introduces **zero** new failures of any kind. They are reported
rather than rounded off, because "the suite is green" would not be true
and a review that said so would be worth nothing.

Phase 1 touches no frontend code. The read API has no UI yet, which is
correct for a phase whose audience is an operator with a terminal and a
decision to make about phase 2.

### 4.1.1 One shared prerequisite, included deliberately

`ExecutionContext.service` is widened from `ServiceContext` to
`ServiceContext | None` in this commit, with the two policy rules that
read it given an explicit answer for `None`.

Learning's gate is **company-scoped** — `Policy.KNOWLEDGE_LEARNING` reads
capabilities and nothing else — but a conversation bound to no service
could not previously be given an `ExecutionContext` at all. The
alternative was the pattern the rest of the platform uses at `HEAD`
(`if service is None: return "no_service"`), which would have silently
disabled Learning for every company on this installation, since none has
adopted the service directory yet. Shipping that knowingly was not an
option.

The change is **behaviour-preserving at `HEAD`**: all three existing
`ExecutionContext` construction sites already guard on
`service is not None`, so the new branches are unreachable until a caller
chooses to reach them. It overlaps an in-flight service-directory
refactor, and the wording was taken from that work rather than invented
in parallel, so the two cannot diverge.

### 4.2 Migration

`e5b2c83f19d7` verified **up → down → up** against real PostgreSQL 16 on
a scratch database, not SQLite. Down removes all four tables; up recreates
them with the partial index (`WHERE state = 'pending'`), the unique
constraints and the cascading foreign keys intact.

`alembic check` reports drift, and every Learning entry in that report is
the `created_at`/`updated_at` `modify_nullable` noise the shared
`TimestampMixin` already produces for `memory_facts`, `embeddings`,
`knowledge_chunks`, `services` and a dozen others. Learning introduces no
new class of drift. (That the baseline is noisy at all is a pre-existing
defect worth its own cleanup; it is not this phase's.)

### 4.3 Three defects found and fixed during the build

Reported because "the tests pass" is not by itself evidence that they
were ever capable of failing.

1. **`Conversation.channel_type` does not exist.** The consumer read a
   field that is on `ChannelConfig`, not on the conversation. Every
   observation would have crashed at the policy gate — caught by the
   first integration test that ran the consumer end to end, not by any
   unit test, which is the argument for the integration layer.

2. **Naive/aware datetime arithmetic in `conversation_outcome`.** The
   single outcome resolver subtracted `ended_at` from `now` without
   normalising. PostgreSQL `timestamptz` yields aware datetimes and
   SQLite yields naive ones, so this would have worked in production and
   failed in the suite — or, with a different call site, the reverse.
   Fixed at the *entrance* to the resolver (`OutcomeInputs.__post_init__`)
   rather than at the four arithmetic sites, so a branch added later
   cannot forget it.

3. **Erasure relied on a cascade the test backend does not apply.** The
   participant deleted observations and let `ON DELETE CASCADE` remove
   features and refs. PostgreSQL honours that; SQLite enforces foreign
   keys only with a pragma, and a bulk `DELETE` bypasses the ORM cascade
   on both. Children are now deleted explicitly and counted — the same
   trade `MemoryErasureService` already documented, for the reason that
   an erasure report is a document somebody forwards to a regulator.

The third is the one that mattered. It would not have been caught by
review, and the erasure report would have claimed completeness while two
tables still held the subject.

## 5. What phase 1 cannot yet tell you

The gate from phase 1 to phase 2 is *"extraction cost measured; lag within
§14"*. Neither number exists yet, because neither can be produced by a
build — only by running.

| Needed before phase 2 | How to get it |
|---|---|
| Extraction cost over the real corpus | Run the consumers against production traffic and read `GET /intelligence/health` and `learning_runs` |
| Observation lag (≤ 5 min after settle) | Consumer lag per topic, already emitted; needs a dashboard panel |
| **The actual feedback ratio** | `GET /intelligence/health` — this is the number that decides whether phase 2 is safe at all |

The feedback ratio deserves emphasis. Phase 2 clusters observations; if a
meaningful share of observed content is the platform's own output, phase 2
clusters the platform's vocabulary and every subsequent phase inherits it.
The exclusion rules make that *unlikely*; the number makes it *known*.

Also absent, and deliberately: a Grafana panel. §17's danger dashboard is
required "before phase 4", and the metrics it needs are emitted now, but
the panel itself is not phase 1 work.

## 6. Verdict

**Phase 1 is complete as specified**, with the two narrowings in §3
requiring your decision before they are treated as settled — §3.1
substantively (tier 2), §3.2 as an acknowledgement (the fourth table).

**Phase 2 should not begin on this document alone.** The charter's own
gate is a measurement, not a review, and the platform has not yet run
long enough to produce it. The honest sequence is: deploy phase 1, let it
observe real traffic, read the feedback ratio and the extraction cost,
and *then* decide about clustering — which is exactly what phase 1 was
built to make possible.

## See also

- [Learning Platform](./learning-platform.md) — what was built
- [Learning Platform Charter](./learning-platform-charter.md) — the contract
- [Architecture Freeze Review 2](./architecture-freeze-review-2.md) — the approval this builds on
