# Company Knowledge and Adaptive Voice (M2)

The M2 milestone: an isolated Company Knowledge Base that answers *what is
true*, and an adaptive communication layer that decides *how it is said*.

Companion to the [Company Intelligence Engine](./company-intelligence-engine.md),
which remains the canonical programme document. This one exists because M2 adds
two things that document does not cover — **deterministic structured
knowledge** and **document ingestion** — and extends two it designs but does
not build. It does not restate the engine; it says what M2 adds, what it
reuses, and what it declines.

Status: **architecture approved. M2A in build; M2B–M2J design.**

---

## What the audit found before anything was designed

Most of what M2 asks for already exists or is already designed. Designing it
again would produce a second vocabulary for the same concepts — the failure
this architecture has avoided so far.

| Capability | State | Where |
|---|---|---|
| Provenance on every learned item | **Shipped** — `created_from`, `confidence_state`, `human_state`, `lifecycle_state`, `steward_user_id`, `expires_at`, `archived_at` | `memory_facts`, `domain/memory.py` |
| USER_PROVIDED / AI_INFERRED / USER_CONFIRMED distinction | **Shipped** as `CreatedFrom` × `ConfidenceState` × `HumanState` | `domain/memory.py` |
| "Never silently convert an inference into a fact" | **Shipped** as the Memory Manager invariant | [KMI](./knowledge-memory-intelligence.md) |
| Hybrid retrieval, lexical + semantic, RRF | **Shipped** | `knowledge_retrieval_service.py`, `domain/retrieval.py` |
| Tenant-isolated vector search | **Shipped, empirically verified** — 0 cross-tenant rows, recall@10 = 1.000 | `scripts/verify_pgvector.py` |
| AI tools: schema → AuthContext → tenant → permission → confirmation → audit | **Shipped** | `application/ai_tools/` |
| Inbound email, MIME attachment extraction to object storage | **Shipped** | `email_imap_poll_task.py`, `connectors/email.py` |
| Brand voice, split into constraints and characteristics | **Designed, unbuilt** — Company DNA | [KMI § Company DNA](./knowledge-memory-intelligence.md#company-dna) |
| Voice per (channel, segment, situation, language) | **Designed, unbuilt** | ibid. |
| Arabic register: MSA vs dialect ≠ English formality | **Designed** | ibid. |
| Article versioning, classes, access levels | **Designed, unbuilt** (engine stage 2) | [Engine](./company-intelligence-engine.md) |
| Deterministic structured knowledge | **Not designed** | — |
| Document ingestion pipeline | **Not designed** | — |

So M2 is **three new things** plus **build-out of existing design**:

1. **NEW** — Structured Knowledge (§3), the one real gap.
2. **NEW** — Ingestion (§6), attaching to shipped email infrastructure.
3. **NEW** — Customer Communication Profile (§9), as inference.
4. **BUILD-OUT** — Company DNA / Voice (§8), already designed.

---

## 1. Two positions

### 1.1 One milestone, two bounded contexts

Knowledge and Communication ship together because neither is useful alone:
knowledge without voice answers correctly in the wrong register; voice without
knowledge is fluent invention.

They do not become one component. What to say and how to say it are separate,
and a single service owning both would put the thing that must never be wrong
(a price) behind the same interface, permission and failure mode as the thing
allowed to be imperfect (warmth).

**One milestone. Two contexts. Two permission families. Enforced structurally.**

### 1.2 For authoritative facts, grounding is a gate, not a preference

"Prefer company knowledge" is a prompt directive, and a prompt directive has an
unmeasured failure rate. For a price quoted to a financial institution the gap
between *usually* and *always* is the product.

So for `PRICE`, `SLA_TERM` and any `RESTRICTED` class, an answer containing a
value not traceable to a retrieved structured record is **blocked by the
verifier** and handed to a human. This reuses the existing mechanism for
uncited restricted claims rather than inventing one.

Until the verifier ships (engine stage 3, deferred per
[freeze review B8](./architecture-freeze-review-2.md)), this authority is
**advisory**, and this document says so rather than claiming a guarantee that
has no enforcement point. M2A ships the deterministic *store* and its
resolution semantics; the gate lands with the generation pipeline.

---

## 2. Domain model

```
COMPANY AI INTELLIGENCE LAYER
│
├── KNOWLEDGE — what is true            authority: human approval
│   ├── Official Knowledge      EXISTING (articles) + versioning DESIGNED
│   ├── Structured Knowledge    NEW  ← M2A
│   ├── Voice Constraints       DESIGNED (KnowledgeClass)
│   └── Documents + Ingestion   NEW
│
├── MEMORY — what we observed           authority: evidence
│   ├── Organizational / Customer / Conversation / Experience   EXISTING
│   └── Customer communication signals  NEW (fact types, not a table)
│
└── COMMUNICATION — how we say it       authority: company configuration
    ├── Voice Profile           DESIGNED (versioned config)
    └── Voice Constraints       → stored in Knowledge, applied by verifier
```

### Entity decisions

Nine entities were proposed. Evaluated against what exists:

| Proposed | Verdict | Rationale |
|---|---|---|
| `KnowledgeSource` | **NEW** | Nothing models a trusted origin |
| `KnowledgeDocument` | **NEW** | The ingested artefact, distinct from the article |
| `KnowledgeDocumentVersion` | **NEW** | Immutable; the citation target |
| `KnowledgeItem` | **REJECTED** | Ambiguous between article, fact and chunk |
| `KnowledgeFact` | **REJECTED as new** | `memory_facts` already holds this contract; structured knowledge needs different *semantics* (§3.2), not this name |
| `KnowledgeChunk` | **EXISTING** | `knowledge_chunks`, shipped |
| `KnowledgeIngestionJob` | **NEW** | Needs idempotency, retry, stage audit |
| `CommunicationProfile` | **NEW, not a table** | Versioned config in `Company.settings.voice` + `service_versions.extras` |
| `CustomerCommunicationProfile` | **NEW, not a table** | Projection over `memory_facts` (§9) |

Two rejected outright, two deliberately not tables.

---

## 3. Structured Knowledge

**NEW. M2A.**

A price is not a passage. "What is the price of DIA 500 Mbps?" answered by
cosine similarity is a lookup answered by resemblance, and resemblance returns
the 200 Mbps row with a respectable score.

### 3.1 The record

`KnowledgeRecord` — a typed, deterministically queryable row with an effective
period.

| Column | Purpose |
|---|---|
| `company_id` | tenant scope |
| `record_type` | `PRICE`, `PRODUCT`, `SERVICE`, `SLA_TERM`, `POLICY_PARAM` |
| `subject_key` | canonical normalised identity (§4) |
| `subject_label` | display form as authored |
| `attributes` | JSON, schema-versioned per `record_type` |
| `effective_from` / `effective_until` | the period this was true |
| `version`, `supersedes_id`, `superseded_by_id` | the chain |
| `lifecycle_state` | `draft` / `active` / `superseded` / `archived` |
| `access_level` | `PUBLIC_TO_AI` / `INTERNAL` / `RESTRICTED` |
| `created_from` | provenance, reusing `CreatedFrom` |
| `source_document_version_id` | → the immutable artefact (M2D) |
| `source_reference` | free-form origin when no document exists |
| `approved_by_user_id`, `approved_at` | who made it official |

A `PRICE`'s attributes: `{amount, currency, unit, billing_period, tax_treatment}`.

**Currency is a field, never a formatted string.** `"180 JOD"` cannot be
compared, converted or totalled; the invoicing domain already learned this.

### 3.2 Why not `memory_facts`

`memory_facts` is evidential — confidence computed from a support stream,
lifecycle driven by decay and contradiction. A price has no confidence. It is
180 JOD because a human approved a document saying so. Storing an approved
price in a table whose semantics are *this decays unless re-observed* would
make the platform's most auditable statement its least stable one.

`knowledge_articles` is wrong for the opposite reason: an article is prose for
a human, retrieved by resemblance. This is a value for a machine, retrieved by
identity.

The two remain connected: a `KnowledgeRecord` may cite a document version, and
Memory may observe that a record is frequently asked about. Neither writes the
other.

### 3.3 Resolution

Resolve by `(company_id, subject_key, record_type)` filtered to
`lifecycle_state = 'active'` and `effective_from <= at < effective_until`.

Three outcomes, all explicit:

| Outcome | Behaviour |
|---|---|
| Exactly one | Authoritative. Cite it |
| None | Absence signal. **Never** fall back to semantic retrieval |
| More than one | Contradiction. Never pick. Escalate |

The last matters most. Two overlapping active prices is a data problem the
platform must surface; a retrieval layer that silently returns the
higher-scoring one converts a data problem into a quotation.

Overlap is prevented at write time (§5) and still checked at read time, because
a constraint that only exists in application code is one a backfill can violate.

---

## 4. `subject_key` — deterministic canonicalisation

**DECISION 1 — resolved.**

The canonical key is computed by a **pure, deterministic function**. No model
is involved: an LLM-generated key is not reproducible, and a key that changes
between runs silently forks a product's history into two chains.

### 4.1 The algorithm

Ordered, and each step exists for a reason:

1. **Unicode NFKC normalisation** — collapses compatibility forms. Arabic-Indic
   digits `٥٠٠` → `500`; full-width Latin → ASCII.
2. **Arabic orthographic folding** — strip diacritics (harakat) and tatweel;
   unify alef forms (`أإآٱ` → `ا`), `ى` → `ي`, `ة` → `ه`. Without this,
   `الخدمة` and `الخدمه` are different products, and both spellings occur in
   real traffic.
3. **Case folding** — `str.casefold()`, not `lower()`; correct for non-ASCII.
4. **Punctuation to separator** — `/`, `_`, `.`, `,`, `(`, `)`, `–`, `—` and
   friends become a single `-`. Retained inside alphanumeric runs so `500mbps`
   and `v2.1` survive as tokens.
5. **Whitespace collapse** — any run of whitespace → single `-`.
6. **Trim** separators from both ends; collapse runs of `-`.
7. **Length bound** — 200 chars, truncated on a separator boundary.

`DIA 500 Mbps` → `dia-500-mbps`. `  DIA/500  Mbps ` → `dia-500-mbps`.
`دي آي إيه ٥٠٠` → `دي-اي-ايه-500`.

**Version-independent by construction:** the function reads only the label. It
never consults the database, the current version, or anything that changes over
time, so the same label yields the same key in 2026 and 2029.

### 4.2 Collision handling

Two labels normalising to one key is **expected and correct** — that is the
point. `DIA 500 Mbps`, `DIA/500 Mbps` and `dia 500 mbps` *are* the same
product.

The harmful case is two genuinely different products colliding. Handled by
scope and by evidence, not by hoping:

- **Uniqueness is `(company_id, record_type, subject_key, version)`.** Two
  different `record_type`s may share a key without interacting — a `PRODUCT`
  named `support` and a `POLICY_PARAM` named `support` are different rows.
- **Within one `(company_id, record_type, subject_key)`, collision is
  identity.** A second record is a new *version* of the same subject, not a
  separate subject. This is the behaviour that makes "update the price of the
  500 Mbps service" work.
- **A genuine collision is a naming problem, surfaced not resolved.** If two
  distinct products normalise together, the platform reports the conflict with
  both labels and requires a distinguishing label. It does not silently
  disambiguate with a numeric suffix — `dia-500-mbps-2` is a key nobody can
  look up and nobody chose.
- **`subject_label` preserves the authored form.** The key is for lookup; the
  label is what a human sees. A record found by `dia-500-mbps` still displays
  as `DIA 500 Mbps`.

Aliases (a per-company table mapping alternative labels to a canonical key) are
**deferred to M2C**, where retrieval needs them. M2A stores the key and the
label; nothing yet needs a synonym.

---

## 5. Lifecycle, versioning and validation

**M2A.**

### 5.1 States

```
draft ──publish──> active ──supersede──> superseded
  │                   │
  └──archive──────────┴──archive──────> archived
```

- **`draft`** — created but not authoritative. Never retrieved for answering.
- **`active`** — the current truth for its subject and period.
- **`superseded`** — replaced by a newer version. Retained, auditable, still
  the correct answer to "what did we quote in July".
- **`archived`** — withdrawn. Not authoritative, not deleted.

**There is no delete.** Not in the service, not in the API, not as a tool. A
price that was quoted must be reproducible in an audit two years later, which
is the founding argument of the engine document.

### 5.2 Supersession

Superseding record *v(n)* with *v(n+1)*:

1. Validate the new record.
2. Set `v(n).superseded_by_id`, `lifecycle_state = 'superseded'`.
3. Close `v(n).effective_until` to the new record's `effective_from` **if it
   was open or overlapping** — the old price stops being true exactly when the
   new one starts.
4. Insert *v(n+1)* with `version = n+1`, `supersedes_id = v(n).id`, `active`.

All in one transaction. A half-superseded chain has two active prices, which is
§3.3's contradiction — the state the whole design exists to prevent.

### 5.3 Validation rules

Enforced in the domain, so they hold regardless of caller:

- `effective_from` required; `effective_until` optional (open-ended).
- `effective_until > effective_from` when present.
- **No two `active` records may overlap in time** for one
  `(company_id, record_type, subject_key)`. Checked in-transaction against
  committed state.
- `attributes` validated against the schema for `record_type`; unknown keys
  rejected rather than stored.
- `PRICE` requires `amount` (non-negative decimal) and `currency` (ISO-4217).
- A record may not be published without `created_from` and either a source
  document version or a `source_reference` — **provenance is not optional**.

### 5.4 Reading at a point in time

Every read takes an `at` timestamp defaulting to now. `as_of` is how "what did
we quote in July" is answered, and it is the same code path as the live
lookup — not a separate reporting query that can drift from it.

---

## 6. Ingestion

**NEW. M2E–M2F. DECISION 3 — resolved.**

### 6.1 The mailbox reuses existing infrastructure

`email_imap_poll_task.py` already polls IMAP; `connectors/email.py` already
extracts MIME attachments into MinIO via `AttachmentStore`. **M2 does not build
an email receiver.** It adds a second consumer of an existing inbound stream.

A knowledge mailbox is a **company-scoped ingestion capability** carried by a
`channel_config` whose purpose is ingestion rather than conversation. That
choice buys, at no cost: the existing poll, encrypted credential storage,
connector health checks, retry and the existing idempotency key.

The routing decision is one branch at the point an inbound message would become
a conversation: ingestion-purpose configs go to the ingestion pipeline instead.

### 6.2 Company resolution precedes everything

Mail resolves to **exactly one company before any parsing**, by the
`channel_config` it arrived through. A message that cannot be resolved to
exactly one company is rejected and audited — never parsed, never indexed,
never guessed. Company resolution is the tenant boundary, and it happens before
any content is read.

### 6.3 Pipeline

```
inbound email                        EXISTING
  → company resolution               EXISTING (one company, or reject)
  → sender/domain trust evaluation   NEW
  → security validation              EXISTING allowlist + NEW (§7)
  → attachment extraction            EXISTING
  → document parsing                 NEW  (§6.5)
  → classification                   NEW
  → structured extraction            NEW  → draft KnowledgeRecords
  → validation + duplicate detection NEW  (content hash)
  → versioning / supersession        M2A
  → approval routing                 NEW  (§6.4)
  → publish                          M2A
  → indexing                         EXISTING (sweep marks PENDING)
```

Every stage transition writes to `KnowledgeIngestionJob`. A failure is a row
with a stage and a reason, not a lost email.

Idempotency: `(company_id, message_id, attachment_hash)`. Redelivery is
identity, not a new document — the same discipline as the outbox relay.

### 6.4 Trust does not mean auto-publish

| Trust | Source | Effect |
|---|---|---|
| `TRUSTED` | Approved mailbox, verified sender, approved domain | May auto-publish **low-risk types only** |
| `REVIEW_REQUIRED` | Everything else | Always queued |

**Pricing, SLA, billing, legal/policy, security and contractual knowledge
always require human review before publication, regardless of trust level or
extraction confidence.** A trusted sender is a statement about a mailbox;
mailboxes are compromised. This is not configurable downward.

### 6.5 Parsing scope

**DECISION 4 — resolved.**

**In scope:** PDF (text layer), DOCX, XLSX, CSV, plain-text and HTML email
bodies, standard attachments.

**Out of scope: OCR.** A scanned PDF with no text layer is **rejected with an
explicit reason**, never silently half-read. Half-reading a price list is worse
than refusing it, because the failure is invisible.

The extension point is a `DocumentParser` protocol resolved by content type and
capability. An OCR parser registers against it later without changing the
pipeline. Naming the seam now is what stops OCR expanding this milestone.

---

## 7. Security

**EXISTING principle, NEW surface.**

M2 widens the attack surface materially: the platform ingests documents from
email, the most hostile input a business system takes.

### 7.1 Documents are data, never instructions

Retrieved content is never placed where it can be read as instruction. Chunks
and records enter the prompt inside a delimited, labelled region, and the
system prompt states that region is reference material from untrusted sources.

Prompt wording is not the control. The structural defences are:

- **Tool authorization derives from `AuthContext` only.** No text in any
  document can grant a permission, because permissions are not read from text.
  Already true of the executor; M2 does not weaken it.
- **The tool registry is a fixed allowlist.** An unregistered tool fails at
  schema validation.
- **Tenant scope is applied in the repository layer**, below anything a model
  influences.
- **Classification never grants permission** (§10). It is routing only.

### 7.2 Never retrievable

Passwords, API keys, tokens, refresh tokens, channel credentials, encryption
keys. These are not *filtered from responses* — they are never in a table
retrieval reads. Ingestion rejects documents matching credential patterns
rather than indexing them. Filtering fails open; absence does not.

### 7.3 Access levels enforced at retrieval

`PUBLIC_TO_AI` / `INTERNAL` / `RESTRICTED`, enforced **at retrieval time by
audience**, not at generation.

A customer-facing generation retrieves only `PUBLIC_TO_AI`. An `INTERNAL`
policy that should influence a reply without being quoted is supplied as a
constraint, not as citable content — the same mechanism as Voice Constraints,
which are *applied, never cited*.

Enforcing at generation would mean the restricted text was in context, one
prompt away from disclosure. Enforcing at retrieval means it was never fetched.

---

## 8. Voice

**DESIGNED in [Company DNA](./knowledge-memory-intelligence.md#company-dna). M2G builds it.**

The split holds without modification:

- **Voice Constraints** — prohibited phrases, mandatory disclaimers, required
  escalation language. Knowledge: versioned, approved, restricted, enforced by
  the **verifier**. A prohibited phrase that appears anyway blocks the send.
- **Voice Profile** — tone, formality, verbosity, emoji policy, greeting and
  closing style. Versioned configuration, applied as a **generation directive**.

Keeping them apart is what makes "no emojis" a preference and "include the
regulatory notice" a guarantee. Merging gives both the weaker enforcement.

Resolved per **(channel, segment, situation, language)** with a company default
and sparse overrides, through `setting(namespace, key, default)`. A conversation
bound to an older service version keeps the voice it started with.

**Arabic is not a formality setting.** MSA vs dialect is a register choice that
does not map onto English formality. A company with a friendly, informal
English voice has not thereby chosen Jordanian Arabic. `dialect_preference` is
resolved per language, never derived from a global tone flag.

---

## 9. Customer communication signals

**NEW. M2H. DECISION 5 — resolved.**

An inference, never a conclusion from one message, with confidence growing as
history grows, never shown to the customer. That contract is `memory_facts`
exactly.

So these are **new fact types on the shipped contract**, not a new table:
`PREFERRED_LANGUAGE`, `DIALECT_SIGNAL`, `FORMALITY_SIGNAL`,
`VERBOSITY_SIGNAL`, `SCRIPT_SIGNAL` (Arabizi vs Arabic script).

`subject_type = CUSTOMER`, so the existing erasure participant removes them
with the customer — the data-protection question is already answered.

### 9.1 The feature flag

`dialect_adaptation` defaults **OFF**.

| Flag | Behaviour |
|---|---|
| **OFF** | Language matching **on**. Company voice **on**. Formality/tone matching **on**. Dialect: natural neutral language |
| **ON** | Dialect applied only above confidence threshold; below it, neutral |

Language matching (Arabic vs English) needs far less evidence than dialect
matching (Jordanian vs Egyptian), so they are separate fact types with separate
thresholds — not one style score.

Below threshold the platform uses neutral language rather than guessing. A
badly-produced dialect reads as mockery, which is worse than neutral MSA.

### 9.2 Mirror language, not toxicity

Register and language are mirrored. Hostility, abuse and threats are not. A
reply to an angry message matches its language and directness while remaining
non-hostile.

This is a **Voice Constraint**, enforced — not a style suggestion. Mirroring
abuse is a brand incident.

### 9.3 Never leaked

Never rendered, cited or named. "I detected that you speak Jordanian Arabic" is
a defect. The profile is a generation directive and is `INTERNAL` by
construction.

### 9.4 Dialect quality is not verifiable by automated tests

Four **safety** properties are assertable and will ship verified: language
matching, dialect-only-above-threshold, toxicity-never-mirrored,
classification-never-leaked.

Dialect **quality** is not. It requires a held-out corpus graded by qualified
native speakers of each target dialect — Jordanian, Egyptian, Gulf — not a
model judging its own Arabic. Until that exists, `dialect_adaptation` stays
OFF, and no automated result may be reported as verifying dialect quality.

The future process: a held-out corpus per dialect, never used for tuning;
blind grading by at least two native speakers per dialect on naturalness,
register appropriateness and absence of mockery; a scored suite reported as a
distribution, not a pass/fail gate.

---

## 10. Retrieval routing

**NEW. M2C. DECISION 2 — resolved.**

**Rules first, model fallback.**

Deterministic rules classify high-risk and authoritative intents wherever
practical: pricing, SLA, billing, policy, escalation, authentication/security,
account configuration. A rule that matches a known `subject_key` or a
type-specific pattern is cheap, deterministic and testable.

The model is consulted **only** when rules cannot confidently classify.

| Intent | Mechanism | Fallback |
|---|---|---|
| Price, SLA term, product attribute | Structured lookup **only** | None — absence signal |
| Policy, procedure | Full-text + semantic | Semantic |
| FAQ | Hybrid | Semantic |
| Product description | Structured + semantic | Semantic |

**Structured lookup never falls back to semantic.** No active price record
means "I don't have current pricing for that", not the nearest-looking passage.
A fallback here is exactly how an expired 2025 price gets quoted in 2026.

**Classification never grants permission.** It selects a retrieval strategy and
nothing else. Permissions come from `AuthContext`; a misclassified query
retrieves the wrong way, it does not gain authority.

### Absence signal

On no-result or multi-result the generator receives an explicit absence signal,
not an empty context. An empty context invites the model to fill it from
parametric knowledge — the precise failure this design prevents. The signal
carries what was searched and why it failed; the verifier blocks any reply
containing a price while it is set.

---

## 11. Extraction confidence

**DECISION 6 — resolved.**

Tiers, not one arbitrary number.

| Tier | Low-risk types | Sensitive types |
|---|---|---|
| `HIGH` | Eligible for auto-publish | **Review required** |
| `MEDIUM` | Review required | **Review required** |
| `LOW` | Do not publish; clarify or review | **Review required** |

**Sensitive types** — pricing, SLA, billing, legal/policy,
security/authentication, contractual — **always require review before
publication.** High confidence does not bypass this, and neither does a
`TRUSTED` sender. The two gates are independent and both must pass.

Policy is configurable per knowledge type; the platform ships safe defaults,
and the sensitive-type rule is a floor rather than a default — configuration
may make a low-risk type stricter, never a sensitive type looser.

---

## 12. Tool registry

**EXISTING mechanism, NEW tools.** Registered on `application/ai_tools/`.

| Tool | Permission | Confirmation | Mutating |
|---|---|---|---|
| `search_knowledge` | `knowledge.read` | — | no |
| `get_knowledge_item` | `knowledge.read` | — | no |
| `list_knowledge_sources` | `knowledge.read` | — | no |
| `ingest_document` | `knowledge.ingest` | NONE | yes (draft) |
| `propose_knowledge_update` | `knowledge.propose` | NONE | yes (draft) |
| `confirm_knowledge_update` | `knowledge.approve` | REQUIRED | yes |
| `publish_knowledge` | `knowledge.publish` | REQUIRED | yes |
| `archive_knowledge_version` | `knowledge.publish` | REQUIRED | yes |
| `get_communication_profile` | `company.settings.read` | — | no |
| `update_communication_profile` | `company.settings.manage` | REQUIRED | yes |

Restricted classes need `knowledge.approve_restricted`.

**No delete tool.** Archive, deprecate, supersede.

The asymmetry that keeps this usable: **proposing is cheap, publishing is
confirmed.** The admin's conversation stays fluid; the moment anything becomes
official, a human says yes.

---

## 13. Audit, events, tenancy

Audit and events use existing mechanisms. Knowledge mutations write
`audit_logs` with `entity_type` `knowledge_record`. Ingestion jobs are
themselves the audit — every transition, including rejections and why.

Events on the existing outbox → relay → consumer path:
`knowledge.record.published`, `knowledge.record.superseded`,
`knowledge.ingestion.failed`, `knowledge.ingestion.review_required`.

Every new table carries `company_id` with an FK to `companies`, scoped in the
repository layer. Nothing learns across tenants. One company's prices, voice
and customer signals are invisible to every other company, including in
aggregate.

---

## 14. API contract

```
GET    /knowledge/records                    filter: type, subject_key, at
GET    /knowledge/records/{id}
GET    /knowledge/records/{id}/versions
POST   /knowledge/records                    create draft
POST   /knowledge/records/{id}/publish
POST   /knowledge/records/{id}/supersede
POST   /knowledge/records/{id}/archive
GET    /knowledge/records/resolve            deterministic lookup

GET    /knowledge/documents                  M2D
POST   /knowledge/documents                  M2D
GET    /knowledge/sources                    M2D
GET    /knowledge/ingestion-jobs             M2E
POST   /knowledge/ingestion-jobs/{id}/approve
POST   /knowledge/ingestion-jobs/{id}/reject

GET    /company/communication-profile        M2G
PUT    /company/communication-profile        M2G
POST   /company/communication-profile/preview
```

Cursor pagination and idempotency keys per the mobile-readiness work. The
preview endpoint is what makes voice configurable in practice — a setting whose
effect you cannot see before customers do is one nobody will touch.

---

## 15. Test strategy

### Knowledge — deterministic

| Case | Assertion |
|---|---|
| Tenant isolation | Company A's records never in B's results, at every layer |
| Provenance | No publish without `created_from` and a source |
| Versioning | Supersession preserves the old record; the chain is walkable |
| Conflicting records | Two overlapping active → error, never a pick |
| Expired pricing | `effective_until` past → absent, never returned |
| Duplicate documents | Same content hash → idempotent |
| Structured lookup | Returns the record, never a similar passage |
| Missing knowledge | Absence signal; no silent semantic fallback |
| Malicious document | Injection ingested as data; no permission change |
| Restricted knowledge | Never retrieved for customer-facing generation |
| Authorization | Every mutation requires its permission |
| `subject_key` | Deterministic, idempotent, Unicode- and Arabic-correct |

### Communication — mixed

Safety properties assertable (§9.4). Dialect quality is human-graded and stays
flagged off until it is.

---

## 16. Phases

| Phase | Contents | Depends on |
|---|---|---|
| **M2A** | Structured Knowledge: domain, `subject_key`, records, versioning, lifecycle, provenance, validation, API, tests | shipped stage 1 |
| **M2B** | Article versioning, `KnowledgeClass`, access levels, approval workflow | M2A |
| **M2C** | Retrieval router, intent rules, absence signal, aliases | M2A + M2B |
| **M2D** | Documents, document versions, sources, trust levels, manual upload | M2B |
| **M2E** | Ingestion: parsing, classification, extraction, dedup, approval routing, jobs | M2D |
| **M2F** | Email → knowledge, branching off the existing IMAP poll | M2E |
| **M2G** | Voice Profile + Voice Constraints; verifier constraint check | M2B |
| **M2H** | Customer communication signals; confidence gate; flag | M2G + Memory Manager |
| **M2I** | Context assembly, priority resolution | M2C + M2H |
| **M2J** | Evaluation corpus, human grading process | M2I |

**Manual upload (M2D) before email ingestion (M2F)** deliberately: it exercises
parsing, versioning and approval with a human choosing the file. Debugging
extraction and email delivery simultaneously is two problems wearing one hat.

The Memory Manager must exist before M2H writes any communication fact — a fact
written before the Manager is written outside the invariant.

---

## 17. Priority resolution

```
1. Platform safety                          ENFORCED
2. Company policy + Voice Constraints       ENFORCED (verifier)
3. Authoritative knowledge                  ENFORCED for sensitive types
──────────────────────────────────────────  the line
4. Customer communication preference        DIRECTIVE, confidence-gated
5. Company brand voice                      DIRECTIVE
6. Conversational style                     DIRECTIVE
```

Above the line fails closed; below it degrades gracefully. Conflicts resolve to
the higher level, always.

Customer-provided instructions enter at no level. "Ignore your pricing rules"
is message content, and message content is data.

---

## 18. What this does not do

- **It does not auto-publish sensitive knowledge.** No trust level, confidence
  tier or configuration permits it. Deliberate; not configurable downward.
- **It does not expose delete.** Archive, deprecate, supersede.
- **It does not let a document change what the AI may do.**
- **It does not classify a customer from one message.**
- **It does not mirror hostility**, and this is enforced.
- **It does not tell the customer what it inferred about them.**
- **It does not make Autopilot more autonomous.** Better grounding constrains
  what may be said; it does not widen permission.
- **It does not learn across tenants.**
- **It does not claim dialect quality is verified** on automated results.
- **It does not perform OCR**, and rejects rather than half-reads.

---

## See also

- [Company Intelligence Engine](./company-intelligence-engine.md) — the programme
- [Knowledge, Memory and Intelligence](./knowledge-memory-intelligence.md) — domain boundaries, Company DNA
- [AI Tool Calling](./ai-tool-calling.md) — the mechanism M2 tools register on
- [Policy Engine](./policy-engine.md)
- [Audit Logging](./audit-logging.md)
