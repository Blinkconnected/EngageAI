# Learning Platform

Stage 3 of the [Company Intelligence Engine](./company-intelligence-engine.md),
built to the [Learning Platform Charter](./learning-platform-charter.md).
The design it implements is
[intelligence-platform.md](./intelligence-platform.md); where the two
disagree the charter wins.

**This document describes phase 1 — which observes, and does nothing
else.** Clustering, pattern detection, trends, gaps, contradiction
detection, knowledge candidates, memory candidates, suggestions, human
review and every model call are phases 2–4 and are absent from the
codebase, not stubbed in it.

One sentence: **a finished conversation becomes a traceable, idempotent
row carrying structural and lexical features, and nothing else.**

---

## Why phase 1 exists at all

A pipeline that observes and proposes nothing looks like an incomplete
feature. It is the opposite: it is the phase that makes the expensive
phases *measurable* before they are switched on.

Three things become facts rather than estimates once this ships:

1. **What extraction actually costs** over the real corpus, before
   anything metered is enabled. Tiers 0 and 1 are free, so the whole
   history can be run through them.
2. **What the feedback ratio really is** — the share of observed content
   the platform itself wrote. That number decides whether phase 2 is safe
   at all, and no amount of design produces it.
3. **Whether the pipeline can be re-run.** Phase 1 is where
   `pipeline_version` gets its meaning, and a rollback story invented
   after clusters exist is a rollback story invented too late.

## What an observation is

One unit of finished work, as Learning saw it. Not a message, not a
conversation row, and deliberately not a channel.

| Column group | Holds |
|---|---|
| Source | `source_kind`, `source_id`, `channel`, `observed_at` |
| Subject | `customer_id` (nullable — anonymous web chat is normal) |
| Provenance | `human_authored_count`, `ai_generated_count`, `ai_assisted_count`, `human_authored_fraction` |
| Outcome | `resolved`, `resolved_by`, `outcome_attributable`, `reopened`, `escalated`, `first_contact_resolution`, `handling_seconds`, `csat_score`, `outcome_quality`, `settled`, `settle_due_at` |
| State | `state`, `exclusion_reason`, `pipeline_version` |

`source_kind` is named for the *kind of work*, not the transport. A
WhatsApp conversation and an email conversation are both `conversation`;
a phone call is a `call` because its structure genuinely differs.

### The extensibility seam, stated as a rule

> The first `if source.channel == ...` inside Learning is the change that
> breaks it. Channel belongs to the adapter, never to the pipeline.

`channel` is recorded for reporting and adapter debugging, and is handed
to the Policy Engine — which *is* allowed to care. Nothing else in
Learning reads it. A voice call becomes a transcript with segments, an
email thread becomes turns, an ERP ticket becomes a source kind, and all
of them produce the same envelope.

### Content refs are pointers, never copies

`learning_observation_refs` holds `(ref_kind, ref_id, ordinal)` and has
nowhere to put a message body — by construction, not by discipline. This
is the rule the Memory Platform already enforces for evidence, for the
same two reasons: a copy is a second store of customer content with its
own retention, and it turns erasure from a row deletion into a
text-editing problem.

Every observation carries at least one ref, or it is refused. A row
asserting that something happened with nothing to check it against is
the same defect Memory refuses when a fact arrives with no evidence.

**Excluded observations are exempt**, and that exemption is the point of
recording them at all — see below.

## Three states, and why exclusion is written down

| State | Meaning |
|---|---|
| `pending` | Assembled; its outcome may still change |
| `ready` | Settled and eligible for everything downstream |
| `excluded` | Policy refused, or there was nothing learnable |

`decide_state` evaluates in a fixed order, and the order is the design:

1. **Policy first.** A company that forbids learning gets an excluded row
   and nothing else is evaluated — no features read, no content examined.
2. **Human content next.** An entirely machine-written exchange is the
   platform's own output.
3. **Substance.** "ok", "thanks" — real, and worth nothing.
4. Only then does settlement decide `ready` versus `pending`.

A company that forbade learning must get `policy_denied` and not
`no_human_content`, even when both are true. The reason is not cosmetic:
*"we were not allowed to look"* is a materially different answer to a
regulator than *"we looked and found nothing"*.

And writing an excluded row rather than nothing is what makes **"the
platform saw this and chose not to learn from it"** an auditable fact
instead of an absence somebody has to take on trust.

## Features: tiers 0 and 1 only

The cost model is a ladder where each tier escalates only what it cannot
settle:

| Tier | What | Cost | Phase |
|---|---|---|---|
| 0 — structural | outcome, timings, counts | free | **1** |
| 1 — lexical | language, entities, topic tokens | negligible | **1** |
| 2 — embedding | placement against clusters | cheap | 2 |
| 3 — small model | intent, judgement | metered | 3 |
| 4 — strong model | per *candidate*, never per observation | expensive | 4 |

**Phase 1 stops at tier 1**, which is a narrowing of the charter's phase-1
row and is recorded as such in
[the phase 1 review](#deviations-from-the-charter). Tier 2 exists to place
an observation against *existing clusters* — there are none — and charter
§9 permits Learning to write only `CLUSTER_CENTROID` vectors into the
shared index, so an observation embedding has nowhere it is allowed to
live yet.

Everything in `domain/learning_features.py` is deterministic: same text,
same features, every run. That is what makes `pipeline_version` a
rollback boundary rather than a label on a moving target.

Two rules exist because production text broke the earlier ones (phase
1.5). **URLs are stripped before topic extraction** — they are already
kept as entities, and their path segments are identifiers. And **a token
mixing letters and digits is rejected** as an identifier fragment: a CSAT
link put UUID and JWT pieces (`9d1d`, `gl9pwqnk`) into the topic list of
every conversation that received one, consuming six of twenty topic slots
and displacing real signal. The rule is deliberately not a hex test —
`cafe`, `dead` and `decade` are hexadecimal and also words.

Language detection is script-based and honest about it — `ar`, `en`,
`mixed`, or nothing. `mixed` is a first-class answer rather than a
tie-break, because Arabic/English code-switching in one message is normal
traffic here, not an edge case.

## The anti-feedback-loop defence

Autopilot answers conversations using knowledge and memory that Learning
produced. Observing those as evidence is circular by construction:
confidence rises on no new information, and **every counter looks healthy
while it happens**.

Four mechanisms, at four different layers:

| Mechanism | Where | Effect |
|---|---|---|
| Provenance counts | `Provenance` on the envelope | An all-AI exchange is `is_evidence_bearing == False` → excluded |
| Extraction filter (**I-5**) | `LearningObservationService.assemble` | Machine-written turns are removed **before** extraction, not filtered from the results after |
| Template exclusion | `is_system_generated` on message metadata | A platform template — a CSAT invitation, an automated notice — is neither human nor AI, and is not evidence |
| Feedback ratio | `GET /intelligence/health` | The share of observed content the platform wrote, on the operator's screen |

The template rule was added in phase 1.5 after production data showed the
loop being closed by something the AI filter was never going to catch.
The CSAT invitation carried no provenance marker, so its wording —
"feedback", "moment", "share" — was being read as human-authored content
and entered the topics of every conversation that received one. Nobody
wrote it *to this customer*; it counts as neither human nor AI, because
adding it to either number would make that number lie.

The filter's placement matters more than it looks. Filtering afterwards
would still let a conversation Autopilot answered contribute the
platform's own vocabulary to the topics it later clusters on — the same
loop wearing a different hat, and invisible because the row would still
show a healthy human fraction.

`is_ai_assisted` content is **admitted**: a human read the draft and
pressed send, so it is real content. What it may never do is
*corroborate*, which is enforced by the Memory contract when phase 2
proposes facts, not by dropping it here.

## Outcomes are copied, never recomputed

`domain/conversation_outcome.derive` is the single definition of what
happened, shared with the SLA and reporting paths. Learning copies its
result into columns and re-derives nothing (**I-6**). Two definitions of
"resolved" is the A3 defect that once produced zero SLA clocks
platform-wide.

`outcome_attributable` is separate from `resolved` and does most of the
work. A conversation Autopilot closed is genuinely resolved; what it is
not is evidence that whatever preceded it *worked*. Only
`ResolvedBy.HUMAN` is attributable — a workflow or timeout close is a
rule firing, not a person judging a conversation finished, and a pipeline
that conflated the two would learn most enthusiastically from its own
behaviour.

Phase 1 cannot separate a workflow close from a human one on the
available data, so an unassigned close answers `unknown` rather than
guessing `human`. `unknown` is not attributable.

## Settlement: why nothing is `ready` immediately

An outcome is not final when a conversation ends. CSAT arrives minutes to
days later; a reopen invalidates the resolution outright. An observation
assembled at resolution therefore carries a *provisional* outcome, and
anything learning from it before the signals landed would record a
neutral quality for a conversation the customer rated badly — finding E2
of the [freeze review](./architecture-freeze-review.md).

Two paths close the window:

- **`learning-signals-consumer`** shortens it whenever the thing it was
  waiting for actually arrives (`csat.submitted`,
  `conversation.reopened`, `.transferred`, `.sla_breached`). A rated
  conversation settles immediately; waiting further would delay learning
  for no gain.

  `conversation.reopened` **had no publisher until 1.1.0** — the binding
  was written, its handler was tested against fabricated event dicts, and
  no code path in the platform ever produced the key, so a settled
  observation went on claiming a resolution the customer had contradicted
  by writing back. Both reopen paths now publish it (`ConversationService.
  update` on leaving a finished status, and the ingest consumer when a
  customer message reopens one), the consumer reads `reopened_at` and
  `ended_at` off the payload — the ingest path clears `closed_at`, so the
  publisher is the last thing that holds them — and `attach_outcome`
  returns a no-longer-settled observation to `pending` with no settle
  deadline. `tests/unit/test_bound_routing_keys_have_publishers.py` now
  fails the build for any binding with no publisher. See
  [the 1.1.0 release report](../releases/1.1.0.md).
- **`settle-learning-observations`** (Celery beat, every 15 min) promotes
  the ones where nothing ever arrives, which is most of them, after
  `LEARNING_SETTLE_HOURS` (default 72).

72 hours is deliberately far shorter than the 14-day CSAT token life.
Waiting for the last possible response would make every observation two
weeks stale, which is the same as not learning.

**Attaching a signal never un-excludes an observation.** A company that
forbade learning does not start learning because a survey came back.

The sweep **re-derives nothing**. Settlement is a fact about time: the
window elapsed, so the outcome recorded at assembly is now final.

## Idempotency and replay

`UNIQUE (source_id, pipeline_version)` is the whole idempotency story.
At-least-once delivery makes redelivery routine, a consumer restart
replays, and a deliberate re-run is a supported operation — so assembling
the same source twice finds the existing row rather than creating a
sibling. Two rows for one conversation would double every count derived
from them, and the counts are the input to clustering, so the error would
compound rather than show up as a number somebody could sanity-check.

Evidence pointers and the features row are equally idempotent: a
re-assembly updates the features in place and adds no duplicate refs.
`AssemblyResult` reports `created` and `features_written` so a caller
replaying a batch can see that its replay changed nothing.

Including `pipeline_version` in the key is what makes a bad extraction
**recoverable**: version 2 writes alongside version 1 instead of over it,
and the two can be compared before either is trusted.

`learning_runs` carries `UNIQUE (company_id, run_type, pipeline_version,
window_start)`, so two workers cannot both claim one window — a redeploy
overlapping a sweep is exactly the situation where somebody relies on
that answer being unambiguous.

## Ownership and the four tables

| Table | Holds |
|---|---|
| `learning_observations` | The envelope |
| `learning_observation_features` | Tier 0/1 output, one row per observation |
| `learning_observation_refs` | Pointers to observed content |
| `learning_runs` | Execution history per window |

All carry `company_id`. All are **derived and rebuildable** from source
events, which is the property that makes `pipeline_version` rollback real.

Learning reads conversations, messages, CSAT responses and channel
configs. It writes nothing outside the four tables above (**I-2**),
enforced by an AST guard
(`tests/unit/test_learning_writes_only_its_own_tables.py`) rather than by
review, because a behavioural test can only cover the paths somebody
thought to write.

That guard is also what makes replay safe. Re-running a pipeline that
also touched `conversations` would replay side effects onto live rows.

### The evidence graph stays acyclic (I-4)

Neither consumer binds a `memory.*`, `learning.*` or `intelligence.*`
routing key, asserted by a test that parses their `ROUTING_KEYS`. A
consumer bound to Memory's events would close the loop: memory writes an
event, Learning observes it, Learning's output eventually strengthens
that same memory, and confidence rises with no new human evidence
anywhere in the cycle.

Phase 1 also writes **no memory at all**, guarded by the same file. An
observation is evidence, not a fact — and a confidence that can be
written from two places is a confidence nobody can explain.

## Policy and permissions

`Policy.KNOWLEDGE_LEARNING` is the kill switch, evaluated through
`RecordingPolicyEngine` so *"why did Learning ignore this company?"* is
answerable from the decision log rather than from worker output nobody
keeps. It **fails closed**: a caller that did not populate capabilities is
not thereby granted permission to mine what somebody said.

It is nested under the `memory` settings section rather than given one of
its own. Learning is a use of retained observation, so a company that
switched memory off has already answered this question, and
`is_memory_enabled` is checked first — this flag only ever narrows. But it
can be refused *on its own*, which is the point: a company may accept the
platform keeping notes on its relationships while refusing to have those
notes mined for patterns. Collapsing the two would force an
all-or-nothing choice on exactly the regulated tenants who need the
distinction most.

| Permission | Role | May |
|---|---|---|
| `intelligence.read` | Owner, Admin | Read observations, runs, health |
| `intelligence.manage` | Owner | Reserved for phase 2 (dismiss a candidate, replay a window) |

Not on Agent. An observation is a customer conversation seen sideways —
provenance counts, outcome attribution, extracted entities — which is an
operator's view of the platform's own behaviour, not part of an agent's
working day.

## Erasure

Learning registers as an `ErasureParticipant`
(`LearningErasureParticipant`), closing **B5** from the freeze review.
Erasure previously reached Memory and nothing else, because Memory was
the only context holding subject data; an `ErasureReport` that omitted
Learning would assert complete deletion while four tables still held the
subject — and that report is the document somebody forwards to a
regulator.

Each context erases its own store. Same rule that keeps `MemoryManager`
the only writer of memory, applied to deletion: erasure fans out and
*asks*, rather than reaching across boundaries itself. A participant that
raises is recorded as **incomplete** rather than swallowed.

Only `customer` subjects have anything here. An agent appears in an
observation's participants but is not its subject, and erasing an agent
must not delete the company's record that work happened.

Children are deleted **explicitly**, not left to the foreign key's
`ON DELETE CASCADE`. PostgreSQL honours the cascade; SQLite enforces
foreign keys only with a pragma, and a bulk `DELETE` bypasses the ORM's
own cascade either way. The same trade `MemoryErasureService` already
makes, for the same reason: an erasure report must not depend on a
database setting to be true.

## Runtime shape

| Process | Binds / schedule | Does |
|---|---|---|
| `learning-observation-consumer` | `conversation.resolved`, `.closed` | Assembles one observation per finished conversation |
| `learning-signals-consumer` | `csat.submitted`, `conversation.reopened`, `.transferred`, `.sla_breached` | Attaches late outcome signals |
| `settle-learning-observations` | Celery beat, 900 s | Promotes observations whose window closed |

Two consumers rather than one because the work genuinely differs: the
first reads every message in a conversation once, the second attaches a
late rating to a row that already exists. Sharing a queue would put a
heavyweight assembly and a trivial update behind the same prefetch.

Neither binds `message.persisted`. An observation is about a *finished
unit*; assembling one per message would produce a row per turn that the
settle window then has to reconcile.

**Learning never blocks anything.** Both consumers are separate processes
that read other contexts and write only Learning's tables. If they are
down, every other context continues unaffected — charter §5, and the
reason this is not a hook in the conversation path.

`_MAX_TURNS = 500` bounds how much of one conversation is read. A thread
with thousands of turns is real, and loading all of them to extract a
handful of topic tokens is not worth the memory.

## API

All under `intelligence.read`. **Read-only** — phase 1 proposes nothing,
so there is no endpoint to approve, promote or dismiss a candidate,
because there are no candidates.

| Endpoint | Answers |
|---|---|
| `GET /intelligence/observations/{conversation_id}` | *What did Learning extract from this conversation, and from what?* — with content refs |
| `GET /intelligence/observations` | Paged, filterable by `state` |
| `GET /intelligence/runs` | Execution history |
| `GET /intelligence/health` | §15 health, the five operator counters, **and** §17's feedback ratio |

The traceability endpoint is the one that matters most: it is the whole
audit story in one call. Content refs are included there and omitted from
the list, because traceability is a question asked of one observation at a
time and loading refs for every row of a page would be a join nobody
reads.

Health and danger appear on one payload deliberately. `feedback_ratio` is
the number most likely to be quietly wrong, and an operator should not
have to know it lives somewhere else.

The five counters are `pending`, `settled`, `failed`, `replayed` and
`erased`. Two of them are not columns:

- **`failed`** is a fact about a *run*. An observation that failed to
  settle is still a correct pending observation, and a `FAILED` state
  would make a transient database blip look like corrupted data.
- **`erased`** is counted from the audit trail, because after an erasure
  there is nothing left in Learning's tables to count. The audit log
  outlives the rows it describes, which is what a deletion record is for.

`replayed` counts superseded generations — rows whose source has since
been observed under a newer pipeline version. It stays at zero through
ordinary redelivery, which is what makes it worth watching.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `LEARNING_SETTLE_HOURS` | 72 | How long an outcome may still change |
| `LEARNING_SETTLE_BATCH_SIZE` | 500 | Observations promoted per sweep |
| `LEARNING_SETTLE_INTERVAL_SECONDS` | 900 | How often the sweep runs **and** the width of the window a run claims — one setting because the two must agree |
| `memory.learning_enabled` (per company) | `true` | The kill switch |

Nothing here costs money in phase 1: no clustering, no detection, no
candidates, no model calls.

## What is verified

`tests/unit/test_learning_domain.py` (37) — the envelope and extraction in
isolation, including regressions for both defects production data found: policy-before-content ordering, an empty observation answering
`0.0` rather than `1.0` for its human fraction, deterministic topics,
bounded envelopes, Arabic tokenisation.

`tests/unit/test_learning_writes_only_its_own_tables.py` (7) — the AST
guards: no foreign model constructed, no foreign `insert`/`update`/
`delete`, no Learning row built outside Learning, no memory write, no
cyclic routing key. Includes a test that watches the guard fire, because
a guard nobody has watched fail is a guard nobody knows works.

`tests/integration/test_learning_platform.py` (35) — the platform end to
end: traceability, content-never-copied, redelivery not duplicating,
run-window claimed once, all-AI exclusion, machine-written turns not
reaching the extractor, the policy gate reading no content at all, settle
gating and the sweep, signals never un-excluding, outcome attribution,
tenant isolation in the repository *and* through the API, cross-tenant
source refusal, erasure of a customer and non-erasure of an agent, RBAC,
the five health counters, and `replayed` staying at zero through ordinary
redelivery.

And once, against the deployed stack over real conversations — see the
[Production Readiness Report](./learning-platform-production-readiness.md).
That run is what found the two extraction defects the 5 000-sample
benchmark scored 1.000 on.

## Deviations from the charter

Recorded here rather than silently absorbed. Both are narrowings; neither
adds capability.

1. **Tiers 0–1, not 0–2.** Charter §20 lists "tiers 0–2 features" for
   phase 1. Charter §9 permits Learning to write only `CLUSTER_CENTROID`
   into `embeddings`, and clusters are phase 2 — so an observation
   embedding has nowhere it is allowed to live. Tier 2 lands with
   clustering.
2. **A fourth table, `learning_observation_refs`.** Charter §8 names
   `observations` and `observation_features` but no traces table, while
   §10's traceability requirement needs one. It is Learning-owned,
   `company_id`-scoped and rebuildable like the rest; tables are prefixed
   `learning_` to keep the namespace obvious in a database with sixty of
   them.

Deferred within phase 1, deliberately: the operator-triggered **windowed
replay** endpoint (charter §20's "no backfill" note). Replay *safety* is
built — that is what `pipeline_version` and the unique key are — but the
trigger belongs with phase 2, when there is something to replay *into*.
In phase 1 a replay is a version bump and a re-consume, which is a
deploy-time act.

## See also

- [Learning Platform Charter](./learning-platform-charter.md) — the contract
- [Intelligence Platform](./intelligence-platform.md) — the Stage 3 design
- [Memory Platform](./memory-platform.md) — where candidates will go in phase 4
- [Company Intelligence Engine](./company-intelligence-engine.md) — Stage 1
- [Production Readiness Report](./learning-platform-production-readiness.md) — phase 1.5, what running it measured
- [Architecture Freeze Review 2](./architecture-freeze-review-2.md) — the approval this builds on
