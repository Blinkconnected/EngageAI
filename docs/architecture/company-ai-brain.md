# Company AI Brain

Every company on Blink Engage has a private Brain: what it knows, what it has
observed, how it speaks, and what it is allowed to do. This document is the
audit that preceded the build, the architecture that came out of it, and the
list of things it deliberately does not do.

Status: **Phases 1–3 and 4A/4B/4C/4F built. 4D, 4E, 4G design.** Phase 1 is
the vocabulary, boundaries and guards; Phase 2 is the first thing to occupy the
orchestration seam — structured knowledge reaching a customer answer; Phase 3
makes that grounding enforced rather than requested; Phase 4 is the source
side — a company mailbox whose mail is attributed, stored once, and read for
its text.

---

## The first finding: most of this is already designed, and some is built

The brief for the Brain reads as a new subsystem. It is not. Nearly every
capability it asks for is already specified in
[Company Knowledge and Adaptive Voice (M2)](./company-knowledge-and-voice.md)
and the [Company Intelligence Engine](./company-intelligence-engine.md), and a
material part of it is in the code today.

Building a "Brain" package that re-modelled knowledge, provenance, lifecycle or
retrieval would produce a second vocabulary for concepts that already have one —
the exact failure both of those documents were written to avoid. So the Brain is
**not a new knowledge stack**. It is the orchestration layer those documents
name and neither builds: the thing that decides, for one message, what to
retrieve, what policy applies, whether the platform actually knows the answer,
and how the reply should sound.

The honest one-line summary: **M2 built the organs; the Brain is the nervous
system that was always missing.**

---

## What already exists

Verified by reading the code at `363c7f3`, not by trusting the documents.

| Capability | State | Where |
|---|---|---|
| Structured knowledge records, typed + schema-validated attributes | **Shipped** | `domain/knowledge_records.py`, `infrastructure/database/models/knowledge_record.py`, migration `e2b9d47f1a83` |
| Lifecycle `DRAFT`/`ACTIVE`/`SUPERSEDED`/`ARCHIVED`, no `DELETE` | **Shipped** | `KnowledgeLifecycleState` |
| Access levels `PUBLIC_TO_AI`/`INTERNAL`/`RESTRICTED` | **Shipped** | `KnowledgeAccessLevel` |
| Sensitive types that always need review | **Shipped as a declaration**, nothing consults it | `SENSITIVE_RECORD_TYPES` |
| Deterministic Arabic-aware `subject_key` | **Shipped** | `canonical_subject_key()` |
| Effective periods, versioning, supersession chain, overlap prevention | **Shipped** | `knowledge_record_service.py` |
| Deterministic resolution with three explicit outcomes | **Shipped** | `KnowledgeRecordService.resolve()` |
| Provenance (`created_from`, source ref, approver, timestamps) | **Shipped** | `KnowledgeRecord` |
| Hybrid lexical+semantic retrieval, RRF | **Shipped** | `knowledge_retrieval_service.py`, `domain/retrieval.py` |
| Tenant-isolated vector search, empirically verified | **Shipped** | `scripts/verify_pgvector.py` — 0 cross-tenant rows, recall@10 1.000 |
| Evidence-based memory, confidence/lifecycle/identity | **Shipped** | `domain/memory.py`, `memory_manager.py` |
| Single-writer invariant, statically enforced | **Shipped** | `tests/unit/test_memory_manager_is_the_only_writer.py` |
| 9-provider AI abstraction | **Shipped** | `infrastructure/ai/providers/` |
| Tool execution: schema → auth → tenant → permission → confirmation → audit | **Shipped** | `application/ai_tools/` |
| Autopilot with autonomous send + handoff | **Shipped** | `autopilot_service.py` |
| Inbound email, IMAP poll, MIME attachments to MinIO | **Shipped** | `email_imap_poll_task.py`, `connectors/email.py` |
| Knowledge RBAC split three ways | **Shipped** | `knowledge_records.read` / `.propose` / `.publish` |
| Outbox → relay → consumer events; `audit_logs` | **Shipped** | event bus, audit logging |

**Nothing in the brief requires a new vector database, a new retrieval
algorithm, a new memory store, a new provider abstraction, or a second
autonomous send path.** All four already exist and are better than a rewrite.

---

## What is missing

Five real gaps. Everything else in the brief is build-out of the above.

**1. No orchestration.** `ToolExecutor` is production-ready and its only caller
is `api/v1/endpoints/ai_actions.py` — the endpoint a *human* uses to confirm or
reject a parked action. Nothing plans a turn, chooses tools, or assembles
context. This is the Brain's core responsibility.

**2. Autopilot does not consume structured knowledge.**
`AutopilotService._grounding_for()` retrieves FAQs and article passages. It does
not touch `KnowledgeRecord`. So the platform's one authoritative, auditable,
deterministically-resolvable store — the reason M2A exists — has no path to a
customer answer. A price change published through the API today changes nothing
about what Autopilot says.

**3. `ChannelConfig` has no purpose.** The model carries `channel_type`,
credentials and health, and nothing else. Every inbound message goes to
`conversation_ingest_consumer`, which resolves or creates a `Customer`. Pointing
`ai@company.com` at the platform today would manufacture a customer record for
the company's own finance team and open support conversations about price
lists.

**4. Email ingestion is not durable.** `_fetch_unseen_sync()` sets `\Seen`
inside the fetch loop, on the IMAP thread, before the message has been persisted
anywhere:

```python
raw_messages.append(fetch_data[0][1])
connection.store(uid, "+FLAGS", "\\Seen")   # ← before any persistence
```

Its docstring calls this "the idempotency mechanism … no separate cursor table
needed". For conversation ingestion the cost of losing a message is bounded — a
customer resends. For knowledge ingestion it is a price list that silently never
arrived. A crash between this line and the database loses the email
permanently, and nothing anywhere records that it existed.

**5. No conflict detection between a *candidate* and existing knowledge.**
Read-time contradiction is handled: two overlapping ACTIVE records raise
`OverlappingRecordError` and resolution never picks. But there is no function
that takes "the email says 18 JOD" and the current 15 JOD record and reports a
conflict *before* anything is written. That is what makes an admin review
meaningful rather than a diff after the fact.

---

## Architecture

```
                        ┌──────────────────────────────┐
  customer message ───▶ │      Brain Orchestrator      │
  (existing pipeline)   │   one turn, one company      │
                        └───────────────┬──────────────┘
                                        │  BrainRequest (company_id mandatory)
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                   ▼           ▼            ▼                  ▼
   Knowledge          Memory        Policy      Communication      Conflict
   (M2A records +     (memory_      (ai_policy,  signals           detection
    articles/FAQ)      facts)        eligibility) (language/tone)   (pure)
        │                   │           │            │                  │
        └───────────────────┴─────┬─────┴────────────┴──────────────────┘
                                  ▼
                        ResponseStrategy  ← tone / de-escalation policy
                                  ▼
                        AI provider (existing abstraction)
                                  ▼
                        grounding + safety validation
                                  ▼
                   ┌──────────────────────────────┐
                   │  AutopilotService (existing) │  ← the ONLY autonomous send
                   └──────────────────────────────┘
```

The Brain **advises**. It does not send. `AutopilotService` keeps sole ownership
of the decision to reply without a human, and keeps its existing eligibility,
threshold and handoff logic unchanged. Better grounding constrains what may be
said; it does not widen permission — the rule M2 §18 already states.

### Tenant isolation

`company_id` is a **required constructor argument** on every Brain request
object, not a filter applied later and not a keyword with a default. There is no
Brain call that can be made without naming a company, so there is no
cross-tenant retrieval to forget to exclude. Below the Brain, isolation is
already enforced in the repository layer and verified empirically for the vector
path.

The guard test asserts this structurally: constructing a Brain request without a
company is a `TypeError`, and the retrieval boundary rejects any resolved record
whose `company_id` differs from the request's.

### Retrieval

Reuses the existing hybrid RRF stack unchanged. The Brain adds an **audience**
concept over it:

| Audience | May see |
|---|---|
| `CUSTOMER` | `PUBLIC_TO_AI` only, resolvable states only |
| `INTERNAL_AGENT` | `PUBLIC_TO_AI` + `INTERNAL` |
| `COMPANY_ADMIN` | all levels the caller's permissions allow, including `DRAFT` |

Enforced at retrieval, never at generation — restricted text that reaches the
prompt is one instruction away from disclosure, and text never fetched is not.

### Answering

The Brain answers the nine questions the brief lists, but the important one is
the eighth: *is the platform allowed to answer at all?* On absence or
contradiction the strategy is not "generate something careful" — it is an
explicit absence signal, and the response strategy selects clarification,
confirmation or escalation. An empty context invites the model to fill it from
parametric knowledge, which is how a 2025 price gets quoted in 2026.

### Tone and de-escalation

A pure policy function, not prompt text. It maps
`(emotional_state, escalation_risk, language, formality)` onto a strategy:
acknowledge, brevity, escalation offer, and a hard prohibition on mirroring
hostility. Being pure makes it testable, which is the whole reason it is not a
paragraph in a system prompt — a prompt directive has an unmeasured failure
rate, and "do not mirror abuse" is a brand guarantee rather than a preference.

Language and register are mirrored. Hostility, threats and abuse are not, and
that asymmetry is enforced in the policy rather than requested of the model.

### Admin assistant

A proposal pipeline over the existing tool registry, not a new write path.
Proposing is cheap; publishing is confirmed. The assistant may produce a
`KnowledgeProposal`; only `publication_gate()` lets one become authoritative,
and only with an approver identity and a permission the caller actually holds.

**No `knowledge_proposals` table.** `DRAFT` already carries exactly these
semantics, and the brief says so.

### Email ingestion

Design only in Phase 1 — the boundary and the identity rule, not the pipeline.

A knowledge mailbox is a `ChannelConfig` whose **purpose** is ingestion. The
branch happens before an inbound message becomes a conversation, so knowledge
mail never reaches customer resolution. Company resolution precedes all parsing:
mail that cannot resolve to exactly one company is rejected and audited, never
guessed at.

Durable identity is `(company_id, message_id, content_hash)` — persisted
*before* the message is acknowledged, so `\Seen` stops being the system of
record. Redelivery is identity, not a new document.

---

## Conflict handling

A pure function comparing a candidate against the currently-resolvable record
for the same `(company_id, record_type, subject_key)`. It classifies rather than
decides:

| Verdict | Meaning |
|---|---|
| `NO_CONFLICT` | Nothing authoritative covers this subject and period |
| `IDENTICAL` | Same value — idempotent restatement, not a change |
| `VALUE_CONFLICT` | Same subject and overlapping period, different value |
| `PERIOD_CONFLICT` | Overlapping effective periods |
| `SUPERSEDES` | Strictly later period; a clean scheduled change |

The Brain never resolves a `VALUE_CONFLICT` itself. It surfaces existing value,
candidate value, both provenances, both periods and the extraction confidence,
and a human decides. Silently choosing is how the platform's most auditable
statement becomes its least trustworthy.

---

## Approval and publication

`publication_gate()` is a pure function and the single chokepoint. It refuses
publication unless **all** hold:

1. The record carries provenance.
2. An approver identity is present.
3. The caller holds the required permission — `knowledge_records.publish`, plus
   `approve_restricted` for `RESTRICTED`.
4. A sensitive type (`PRICE`, `SLA_TERM`, `POLICY_PARAM`) has explicit human
   approval, **whatever** the source's trust level or the extraction's
   confidence.
5. No unresolved `VALUE_CONFLICT`.

Rule 4 is not configurable downward. A trusted sender is a statement about a
mailbox, and mailboxes are compromised.

---

## Security

- Tenant scope is mandatory and structural, not a filter.
- Retrieved documents are data, never instructions; permissions derive from
  `AuthContext` only, and no text can grant one.
- The tool registry stays a fixed allowlist; unregistered tools fail at schema
  validation.
- Customer-facing retrieval never sees `DRAFT`, `INTERNAL`, `RESTRICTED`, or
  another tenant's rows.
- Every knowledge mutation is audited through the existing `audit_logs` path.
- Credentials are never in a table retrieval reads. Absence, not filtering.

---

## Future tool orchestration

Phase 1 introduces **no autonomous actions**. The Brain may reason about which
read-only tools would help, and the existing executor remains the only thing
that runs one — with its permission check, tenant scope, confirmation policy and
audit intact. Any mutating tool keeps its existing confirmation requirement.
Nothing about the Brain widens what the executor allows.

---

## One deliberate deviation from the brief

The brief asks for a guard test that **SUPERSEDED knowledge cannot resolve for
customers**. Implementing that literally would break a deliberate shipped
behaviour and reintroduce a bug the existing design documents at length.

`RESOLVABLE_STATES` is `{ACTIVE, SUPERSEDED}` in both
`domain/knowledge_records.py` and the repository query. The reason is scheduling:
publishing a price change effective next month supersedes today's record
*immediately*, while the replacement does not yet cover today. Resolving only
`ACTIVE` would leave the subject **unpriced for a month** because somebody
scheduled a change correctly.

The safety property the brief is actually reaching for is *stale knowledge must
never answer as current*. That is guaranteed by the period arithmetic, not the
state: periods among resolvable states are disjoint by construction, because
supersession closes the outgoing period exactly where the incoming one opens.

So the guard test pins the real invariant: **a record never answers for a moment
its effective period does not cover, regardless of state**, and `DRAFT` and
`ARCHIVED` never answer at all. `DRAFT` was never true; `ARCHIVED` was withdrawn
and its period is deliberately left intact for audit, so it *can* overlap a
later active record and must stay excluded.

Note also that `company-knowledge-and-voice.md` §3.3 still says resolution
filters to `lifecycle_state = 'active'`. The code has been correct and the
sentence stale since M2A shipped.

---

## Phase 1, as built

Contracts and guards only. No pipeline, no UI, no migration.

| Item | Where |
|---|---|
| Brain vocabulary | `domain/brain/vocabulary.py` |
| Request/response boundary, mandatory tenant | `domain/brain/context.py` |
| `publication_gate()` | `domain/brain/publication.py` |
| Conflict detection, pure | `domain/brain/conflicts.py` |
| Retrieval boundary + audience filter | `domain/brain/retrieval_policy.py` |
| Ingestion boundary + durable identity | `domain/brain/ingestion.py` |
| Admin assistant proposal contract | `domain/brain/assistant.py` |
| Response strategy | `domain/brain/response_strategy.py` |
| Tone / de-escalation policy | `domain/brain/tone.py` |
| Orchestrator boundary (protocol) | `application/brain/orchestrator.py` |
| Guard tests | `tests/unit/test_company_ai_brain_guards.py` |

Pure domain functions with no I/O, so they are testable without a database and
cannot acquire one by accident.

---

## Phase 2, as built

The gap was gap 2 above: `knowledge_records` shipped complete and nothing on
the path to a customer had ever read it, so publishing a price change altered
nothing about what Autopilot said.

| Item | Where |
|---|---|
| Deterministic subject matching | `domain/brain/subject_matching.py` |
| `CompanyBrain`, first `BrainOrchestrator` | `application/brain/service.py` |
| Grounding hook | `AutopilotService._grounding_for()` |
| Wiring | `infrastructure/autopilot_factory.py` |

**Matched by identity, not resemblance.** A subject matches when its key's
tokens appear contiguously in the question, canonicalised through the same
`canonical_subject_key` the record was written with — so `خدمة ٥٠٠` finds
`خدمه-500`, and "is DIA available at 500 sites, in mbps terms" does not match
`dia-500-mbps`. Contiguity is what stops it guessing.

**Three outcomes, three behaviours.** Exactly one record becomes an
authoritative section labelled *quote exactly, never paraphrase a number*.
None becomes an explicit absence signal — the model is told the company has
nothing on record and must not recall a value from anywhere else. Two becomes
an escalation that states no value at all.

**Autopilot's authority is unchanged.** The Brain supplies grounding only. It
does not decide whether Autopilot may reply, and the confidence threshold,
eligibility gates and hand-off logic are untouched. A Brain failure degrades to
ungrounded rather than costing a reply — with one exception:
`CrossTenantAccessError` is re-raised rather than swallowed, because the broad
handler that makes a dead database survivable would otherwise turn a tenant
leak into a quiet "no grounding today".

Still advisory, and this is worth being plain about: nothing yet *blocks* a
reply that states a price while the absence signal is set. That is the
verifier's job (engine stage 3, deferred), which M2 §1.2 already flags.

## Phase 3, as built — the Grounding Verifier

Phase 2 handed the model the approved records and asked it to quote them.
Asking has an unmeasured failure rate. Handed an absence signal, a model
usually says "I don't have that on record" and occasionally says "I believe
it's around 120 JOD" — fluently, at high confidence, in the customer's own
dialect. Nothing downstream could tell those two apart, because both are
well-formed replies. Phase 3 is the gate that can.

### The final-send boundary

Found, not assumed. There is exactly one autonomous path to a customer:

```
AutopilotService.run()
  └── conversation_service.send_reply(...)      ← the only autonomous send
```

`send_reply` is shared with humans — agents send through it too — so the
verifier does **not** live inside it. A human's sentence is not the platform's
to verify. It sits in `run()`, on the generated reply, immediately before the
commit-and-send:

```
eligibility → ownership → dedupe → mode gate → AI provider
  → Brain grounding (Phase 2)
  → generation
  → needs_handoff / confidence < threshold        ← existing gate, untouched
  → GROUNDING VERIFIER                            ← Phase 3, here
  → conversation.autopilot_active = True
  → send_reply(...)
```

**After** the confidence gate on purpose. Running before it would let the
verifier's ALLOW be mistaken downstream for permission; running after means it
can only ever subtract from what was already permitted. A reply that failed the
threshold never reaches this line.

### What it decides

| Outcome | Reason | When |
|---|---|---|
| ALLOW | `NO_COMPANY_CLAIM` | No priced subject was asked about, or the reply states no figure |
| ALLOW | `AUTHORITY_CONFIRMED` | Every figure traces to an approved record |
| BLOCK | `AUTHORITY_ABSENT` | Checked; the company has no approved record |
| BLOCK | `UNSUPPORTED_VALUE` | A record exists and the reply quotes a different figure |
| ESCALATE | `AUTHORITY_CONFLICT` | The company's own records disagree |
| ESCALATE | `GROUNDING_UNAVAILABLE` | Could not check |

BLOCK and ESCALATE both terminate in the **existing** `_hand_off()`, with
distinct reasons on the conversation's timeline
(`unverified_company_fact`, `knowledge_not_decidable`). No second send path, no
new escalation mechanism, no new handoff infrastructure.

### What counts as a company fact

Deterministic, and deliberately narrow: **value claims** — figures — about
subjects whose record type requires approval (`PRICE`, `SLA_TERM`,
`POLICY_PARAM`). No keyword list, no second LLM.

Supported figures come from the resolved records' attributes *and* their
subject labels, because a correct answer quotes both ("our **500** Mbps DIA
costs **180** JOD"). They are **never** seeded from the customer's message —
otherwise "is it 120 JOD?" → "yes, 120 JOD" authorises itself, which is the
cheapest possible way to make the platform quote a price it never approved.

Digits are folded through `unicodedata.digit`, so Arabic-Indic `١٨٠` is the
same figure as `180`; `180`, `180.0` and `180,00` are one figure, because a
verifier that withholds a correct answer over decimal notation is one somebody
switches off.

### Subject detection uses unapproved records too

The security-relevant subtlety, and it looks backwards. Whether a question is
about a priced subject is a property of *the question*, not of whether an
approved answer happens to exist. Filtering candidates by visibility before
matching meant a company whose only price record was still a `DRAFT` looked
like a company that sells nothing priced — so the verifier never engaged and an
invented figure passed. An unapproved row must be able to say "this is a priced
subject" while remaining wholly unable to answer.

Authority is granted in exactly one place: a record that resolves *and* passes
the audience visibility check. `DRAFT`, `ARCHIVED`, out-of-period `SUPERSEDED`,
`RESTRICTED` and another tenant's rows all fail it.

### Failure semantics

`AUTHORITY_ABSENT` and `GROUNDING_UNAVAILABLE` are never collapsed. "We do not
have that on record" and "our knowledge store is down" are different sentences
to a customer and different problems to an operator. A Brain outage produces
`requires_authority=True, unavailable=True` — the conservative reading, because
the alternative claims no priced subject was named on the strength of a query
that errored.

### Tenant isolation

`CrossTenantAccessError` propagates. It is not converted to BLOCK, ESCALATE, a
fallback, or "no grounding today" — the broad handler that makes a dead
database survivable explicitly re-raises it first.

### Non-goals

- Not a hallucination detector. Generic conversation is untouched.
- Does not verify prose. "Our team is famously helpful" is unverifiable without
  a model reading it, and Phase 3 adds no model.
- Does not widen Autopilot's authority. It can only withhold.

## Phase 4A/4B/4F, as built — the ingestion boundary

The source side of the arrow. Mail arrives, is attributed, and is stored once.
Nothing interprets it: 4C (attachments), 4D (jobs), 4E (extraction) and 4G
(admin assistant) are not built, and structural tests fail the build if this
path acquires a parser, a model call or a knowledge write.

**Routing (4A).** `channel_configs.purpose`, read through
`parse_channel_purpose`, which fails closed. The branch is in the IMAP poll
*before* `receive_message()` — earlier than necessary, because that parser
uploads attachments and drops the `Authentication-Results` headers. A second
guard sits at `publish_inbound_message_events`, the last shared point before a
customer exists, and raises for any non-support purpose.

**Identity (4B).** `knowledge_source_messages`, unique on
`(company_id, channel_config_id, message_id, content_hash)`. The row is
committed before `\Seen` is set, which demotes the flag to an optimisation.
Same id with different content is deliberately a *new* source: some senders
reuse Message-IDs, and a price list is not a duplicate because a header
collided.

**Authorization (4F).** Allowlist (empty by default, per address, never per
domain) **and** authentication results from a verifier the company named via
`knowledge_authserv_id` on the channel's credentials. Untrusted or absent
Authentication-Results ⇒ `AUTHENTICATION_UNAVAILABLE` ⇒ reject. No DNS lookups.

**Known limitation, stated rather than papered over:** this depends on the
company's own MTA stamping Authentication-Results and on the company telling
Blink that server's `authserv-id`. Until both are true the mailbox accepts
nothing. That is the intended failure direction, and it is the price of not
faking verification.

Rejection reasons: `TENANT_UNRESOLVED`, `INVALID_CHANNEL_PURPOSE`,
`UNAUTHORIZED_SENDER`, `AUTHENTICATION_FAILED`, `AUTHENTICATION_UNAVAILABLE`,
`CREDENTIAL_MATERIAL`, `MALFORMED_MESSAGE` — recorded, never returned to the
sender, who would otherwise learn which condition to satisfy next.

Events on the existing outbox: `knowledge.source.received`,
`knowledge.source.duplicate`, `knowledge.source.rejected`.

## Phase 4C, as built — attachment extraction

Attachments arriving at a knowledge mailbox are read for their **text** and
nothing else. No model sees them, and no knowledge record is written.

| Kind | Reader | Notes |
|---|---|---|
| PDF | `pypdf` | text layer only; encrypted → refused; no text layer → refused as a scan |
| DOCX | `python-docx` | paragraphs **and table cells** — real price lists live in tables |
| XLSX | `openpyxl` | `data_only=True`, `read_only=True`; formulas never evaluated |
| CSV | stdlib `csv` | cells are strings; a leading `=` is text, never a formula |
| TXT | stdlib | UTF-8, latin-1 fallback |

**Sniffed from content, never the extension.** `pricing.pdf` containing a ZIP
is read as the ZIP. The filename decides exactly one thing — CSV versus TXT,
which are the same bytes — and can never *promote* a file.

**Limits before parsing:** 10 MiB per document; 300 PDF pages; 50 sheets;
20,000 spreadsheet rows; 50,000 CSV rows; 1 M extracted characters. ZIP bombs
are refused from the archive's own directory listing, never unpacked.

Rejections, all terminal: `UNSUPPORTED_TYPE`, `TOO_LARGE`, `ENCRYPTED`,
`NO_TEXT_LAYER`, `CORRUPT`, `ARCHIVE_BOMB`, `EMPTY`. A rejected document is
still a row — "your Q3 price list arrived and is a scan we cannot read" is
answerable; silence is not.

**No OCR.** A scan is refused with a stated reason. `DocumentParser` is
resolved by kind, so an OCR reader registers for that case later without the
pipeline changing.

Storage: `knowledge/{company_id}/{sha256}` in the existing bucket. Dedupe is
`UNIQUE(company_id, content_hash)` — the same PDF forwarded three times is one
document. Oversized files are refused *before* storage; everything else is
kept, including refusals, because the unreadable file is the one an operator
will want to open by hand.

Attachments are only read for an **accepted** message. An unauthorised sender's
files are never opened — authorization is the gate, and reading first would
make it advisory.

## Phase 4D, as built — durable ingestion jobs

`knowledge_ingestion_jobs`, one row per unit of work, company-scoped.

```
RECEIVED ──▶ EXTRACTING ──▶ EXTRACTED ──▶ PROPOSED ──▶ APPROVED
    │            │                                 └──▶ REJECTED
    │            ├──▶ FAILED_RETRYABLE ──▶ EXTRACTING
    └────────────┴──▶ FAILED_TERMINAL
```

`PROPOSED`/`APPROVED`/`REJECTED` are declared and **unreached** — 4E and
publication are not authorized. A state machine missing its exits invites
somebody to add them ad hoc.

**Idempotency:** `UNIQUE(company_id, job_key)` where `job_key` is
`{source_message}:{document}`. A deterministic string rather than a nullable
composite key, because SQL treats NULLs as distinct and would admit duplicates.

**Concurrency:** every transition is a compare-and-set — `WHERE id AND
company_id AND state = expected`. Zero rows matched raises `JobClaimLost`.

**Crash safety:** a dead worker leaves `EXTRACTING` with its attempt counted.
Nothing silently reclaims it; recovery goes through `FAILED_RETRYABLE`.

**Retries:** bounded at 5 attempts, counted on claim. Retryable exhaustion
becomes terminal — a job that is retryable forever is one nobody looks at.
Parser refusals are terminal immediately.

**No state grants authority.** `grants_authority()` returns false for every
state, and the guard test asserts it.

## Phase 4E, as built — AI fact extraction

Document text → candidate facts → DRAFT records. Company provider first,
platform default as fallback; no provider means the job stays **resumable**,
never settled with a fabricated empty result.

Every fact carries a **verbatim `source_passage`** — mandatory, discarded
without it — plus a confidence tier (HIGH/MEDIUM/LOW, ordering only, never
authority) and `extractor_version` + model identifier recorded on the DRAFT's
`source_reference`.

`detect_conflict()` runs per fact against the current ACTIVE record, matched by
identity. Blocking verdicts are counted and **not** drafted over. DRAFT creation
is idempotent per `(company, type, subject_key)`.

**Authority boundary:** only `create_draft`; no `complete_with_tools`; no
ACTIVE/SUPERSEDED/ARCHIVED; `subject_key` derived; authority-bearing attributes
stripped. No migration, no proposal table.

**Wired by `ExtractionBridge`:** a job at `EXTRACTED` runs extraction, drafts
what survives, then advances to `PROPOSED`. Drafts first — a crash between the
two costs a repeat, not a lost job. No provider ⇒ deferred, job untouched.
`CrossTenantAccessError` propagates and is never a failure state.

Building it added one transition to 4D: `EXTRACTED → FAILED_RETRYABLE`, absent
because fact extraction runs after the document is read and a provider timeout
there is still transient.

## Future phases

| Phase | Contents | Depends on |
|---|---|---|
| **4G** | Knowledge tools + admin assistant surface | 4E |
| **5** | Voice constraints enforced by the verifier — prohibited phrases, mandatory disclaimers | Phase 3 |
| **6** | Customer communication signals as memory fact types | M2H |
| **7** | Tool planning over the existing executor, read-only first | Phase 2 |

This intentionally matches M2's own phase letters where they correspond, rather
than inventing a parallel numbering for the same work.

---

## Risks

- **Two documents could drift.** This one owns orchestration; M2 owns knowledge
  and voice. If they disagree, M2 wins on knowledge semantics.
- **The absence signal is advisory until the verifier ships.** M2 §1.2 already
  says so. Phase 1 does not change it, and no claim here should be read as a
  guarantee that a model cannot state an ungrounded price.
- **Dialect quality is not testable by machine.** Four safety properties are;
  naturalness is not. `dialect_adaptation` stays OFF.
- **`SENSITIVE_RECORD_TYPES` now has its first consumer.** It was a declaration
  with no reader; `publication_gate()` reads it. Adding a type without
  classifying it now has a consequence.

## Open questions

1. **Does the admin assistant get its own conversation surface, or does it live
   inside the existing agent inbox?** Affects Phase 6 and the frontend.
2. **What is the trust model for a knowledge mailbox sender?** Approved domain,
   verified sender, or explicit allowlist per company.
3. **Should `INTERNAL` knowledge influence a customer reply as an uncited
   constraint in Phase 2, or wait for the verifier?** Influencing without citing
   is exactly what the verifier is meant to police.
4. **Emotional state: inferred per message, or accumulated on the
   conversation?** Per message is cheaper and stateless; accumulated is more
   accurate and needs a home.

---

## See also

- [Company Knowledge and Adaptive Voice (M2)](./company-knowledge-and-voice.md) — knowledge and voice semantics
- [Company Intelligence Engine](./company-intelligence-engine.md) — the programme
- [AI Tool Calling](./ai-tool-calling.md) — the executor the Brain plans over
- [Knowledge, Memory and Intelligence](./knowledge-memory-intelligence.md) — domain boundaries
