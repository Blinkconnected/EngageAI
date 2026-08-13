# Company AI Brain

Every company on Blink Engage has a private Brain: what it knows, what it has
observed, how it speaks, and what it is allowed to do. This document is the
audit that preceded the build, the architecture that came out of it, and the
list of things it deliberately does not do.

Status: **Phase 1 built — vocabulary, boundaries and guards. Phases 2+ design.**

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

## Future phases

| Phase | Contents | Depends on |
|---|---|---|
| **2** | Wire structured records into Autopilot grounding via the Brain | Phase 1 |
| **3** | `ChannelConfig.purpose`; ingestion branch before customer resolution | Phase 1 |
| **4** | Durable email identity; replace `\Seen`-as-cursor | Phase 3 |
| **5** | Document parsing, classification, extraction → DRAFT records | Phase 4 |
| **6** | Admin assistant as a real conversation over the tool registry | Phase 1 |
| **7** | Voice profile + constraints; verifier enforcement | M2G |
| **8** | Customer communication signals as memory fact types | M2H |
| **9** | Tool planning over the existing executor, read-only first | Phase 2 |

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
