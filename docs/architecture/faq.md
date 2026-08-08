# FAQ

A published question and its answer, searchable the same way knowledge
is, and quotable by AI as an **approved answer** rather than as raw
material.

Status: **built.** Source: [`domain/faq.py`](../../backend/src/blinkengage/domain/faq.py),
[`application/services/faq_service.py`](../../backend/src/blinkengage/application/services/faq_service.py),
[`application/services/faq_retrieval_service.py`](../../backend/src/blinkengage/application/services/faq_retrieval_service.py).

---

## Why this exists, and why it did not before

The AI Engine has answered *"Knowledge Search"* and *"FAQ Search"* with a
single capability since it shipped, and said so plainly in its own source:

> *"Covers both Knowledge Search and FAQ Search — the same capability
> (answer a question by grounding in a set of help-center articles), not
> two separate systems; this project's Knowledge Base never named a
> distinct FAQ entity for a parallel search to be built against."*

That was the honest answer at the time. It is no longer the answer,
because the entity now exists.

The gap it closes is not "search, again". It is that a company had
nowhere to put **a short, curated, customer-facing answer**. Everything
went into a knowledge article: internal by default, written as prose, and
retrieved as a passage the model then had to summarise into its own
words. A company that spent a week wording its refund policy would watch
the platform paraphrase it.

---

## Why an entity, not a flag on `KnowledgeArticle`

The cheap option was `KnowledgeArticle.kind = 'faq'`. Four differences
made a table the right call, and only the first is about search.

| | Knowledge article | FAQ |
|---|---|---|
| **Retrieval target** | Prose inside a long body | **A question** |
| **Embedding unit** | Chunked; N vectors, incrementally hashed | **One vector, no chunking** |
| **Order** | None — a list of documents | **Curated `display_order`** |
| **Audience** | Internal by default; agents read it | **The customer reads it** |
| **`is_published` default** | `true` | **`false`** |

**The retrieval key is different.** An article is found by matching prose;
an FAQ is found by matching a question against a canonical question. That
is why an FAQ answers a customer's phrasing better than any article will.

**An FAQ needs no chunking.** A question plus a short answer is one
embeddable unit. Routing it through `knowledge_chunks` would create a
chunk row per FAQ with `ordinal=0` and a null heading path forever, plus
per-chunk incremental-hash machinery that can never have more than one
chunk to be incremental about.

**The publication default is the clearest expression of the split.** An
unfinished *article* is visible to agents, who can tell a draft from a
policy. An unfinished *FAQ* is visible to customers, who cannot. So an
FAQ is created unpublished and publishing is something somebody chose —
not something that happened because they saved a row.

**What it does not get its own copy of.** Categories and tags are reused
(`knowledge_categories`, the company `Tag` catalog), because a company's
"Billing" category should hold both the article and the FAQ about
billing, and two taxonomies to keep in step are two that drift.

---

## What it owns

| | |
|---|---|
| **Owns** | `faqs`, `faq_tags`, the FAQ half of hybrid retrieval, FAQ index state |
| **Never owns** | Categories (Knowledge), tags (CRM's `Tag` catalog), the embedding model or vector storage (Stage 1), whether AI may answer (Policy Engine) |
| **Depended on by** | The AI Engine's `answer_from_knowledge_base`, the agent-facing FAQ search, the knowledge index sweep |
| **Events emitted** | `faq.created`, `faq.updated`, `faq.deleted` |
| **Events consumed** | None — FAQ writes are synchronous, indexed by a sweep |
| **Tables** | `faqs`, `faq_tags` (migration `a4d81f6b25c9`) |
| **Permissions** | `knowledge_base.read` / `knowledge_base.manage` — **no new pair** |
| **Feature gate** | `knowledge_base`, the same entitlement as articles |

### Why no new permission

A new `faqs.*` pair would be **denied by default to every company that
has customised its roles**, silently locking existing administrators out
of a page they can see in the navigation. An FAQ is knowledge-base
content by any reading, and the `knowledge_base` feature is already
described as *"Internal knowledge articles and FAQ search"*. The same
reasoning kept Internal Notes on `conversations.*`.

---

## The contract

`domain/faq.validate_content` runs before anything reaches the session,
so "every FAQ has a question and an answer" is a property of the store
rather than a habit of its callers — the posture
`memory.validate_fact_shape` takes.

| Rule | Why |
|---|---|
| Question required, answer ≥ 2 chars | An FAQ with half of itself is not one |
| Question ≤ 500, answer ≤ 8,000 chars | **The bound is what stops the FAQ table becoming a second, worse knowledge base.** Anything longer is an article, and the platform has those |
| `locale ∈ {ar, en}` or null | Refused rather than stored: a silently accepted `fr` produces an FAQ no language filter ever returns, which looks exactly like the FAQ having been lost |
| `null` locale is a real answer | A price or a phone number applies whatever the customer speaks, and belongs in **every** language's list rather than none |

Errors are `DomainError` subclasses, so the API boundary renders them as
a 400 naming what is wrong rather than a 500 claiming the platform broke.

---

## Indexing: one vector, and the unpublish path

FAQs ride the **same sweep** as articles
(`blinkengage.knowledge.reindex_pending`, every 60 s) rather than getting
a schedule of their own — both call the same metered provider for the same
company, and two schedules would mean two independent bursts against one
rate limit.

The write path does the cheap half in its own transaction
(`index_state = PENDING`); the sweep does the metered call. Same division
of labour as the outbox and its relay.

```
FAQ saved ──► index_state = PENDING        (same transaction)
                     │
              sweep (60s) claims a bounded batch
                     │
       published? ───┴─── no ──► vector REMOVED, state = SKIPPED
              │
             yes
              │
       hash unchanged? ── yes ──► nothing paid for
              │
             no
              │
     embed(question + answer) ──► one row in `embeddings`
                                  owner_type = 'FAQ', owner_id = faq.id
```

**Both fields are embedded, not the question alone.** Embedding only the
question makes an FAQ unfindable by a term appearing solely in its answer
— a product name, a fee, a branch — which is a large share of what
customers actually type.

**Unpublishing removes the vector.** This is the property that decides
whether publication can be trusted at all: a retrievable unpublished FAQ
is one the AI quotes at a customer after somebody took it down. Deleting
marks the row `PENDING` **in the same transaction as the delete**,
because taking the vector out is what makes the deletion real.

**Retagging costs nothing.** A vector encodes neither a tag nor a
category, so only a change to the embeddable text — or to visibility —
re-queues the row.

**No new column on `embeddings`.** That table's `owner_type`/`owner_id`
pair was built polymorphic exactly so new owners arrive without a
migration. `OWNER_FAQ` is the second kind to use it, after
`OWNER_KNOWLEDGE_CHUNK`.

---

## Retrieval

The same two halves and the *same* `reciprocal_rank_fusion` function as
article search — not a copy. Two fusion implementations would be two
rankings that drift, and the one somebody found first would be the one
they debugged.

```
query
  ├─ LEXICAL   trigram (PostgreSQL) / substring (SQLite)
  │            question scored separately from answer, question weighted
  │            higher — an FAQ whose question *is* the customer's question
  │            should outrank one whose long answer happens to mention
  │            the same words
  │
  └─ SEMANTIC  VectorIndex.search(company_id=…, owner_type='FAQ')
               company_id is a required kwarg — a cross-tenant search is
               inexpressible

           ▼
  RRF: score = Σ 1/(60 + rank)
           ▼
  hydrate through FaqRepository — company predicate applied a SECOND time
           ▼
  drop anything unpublished — catches an FAQ taken down since the last sweep
```

**Degradation is graceful and explicit.** With no embedding provider,
retrieval runs lexical-only and says so in `sources` / `degraded` /
`reason`. A vendor outage must make a company's published answers
findable by keyword, not unfindable.

**No chunk collapse.** Article retrieval fuses at the article level after
collapsing chunks; an FAQ *is* the unit. That simplification is what made
a separate entity worth having.

---

## How AI uses it

`POST /ai/knowledge-search` now retrieves **both**, and the ordering is
the point rather than a detail:

```
APPROVED ANSWERS (prefer these; reuse their wording where it fits)
  Q: How long do refunds take?
  A: Refunds are returned to the original card within five working days.

REFERENCE MATERIAL (background; summarise only what is needed)
  Article: Refund policy
  …the matching chunk…
```

**FAQs are labelled as approved answers and come first.** An FAQ is a
complete answer somebody wrote and published for exactly this question;
an article passage is raw material the model has to summarise. Handing
the model both without saying which is which invites it to paraphrase a
curated answer into an uncurated one — which is how a company that
carefully worded its refund policy finds the platform explaining refunds
in its own words instead.

Three FAQs, deliberately, against five article passages: an FAQ is
already a complete answer, so three is grounding while ten is a wall of
text that pushes the article passages out of the prompt.

---

## API

All under `knowledge_base.read` / `knowledge_base.manage`.

| Endpoint | Does |
|---|---|
| `GET /faqs` | Paged list; filter by `search`, `category_id`, `locale`, `published_only` |
| `POST /faqs` | Create — **unpublished unless asked otherwise** |
| `GET /faqs/search` | Hybrid retrieval, returning `sources`/`ranks`/`degraded` per hit |
| `POST /faqs/reorder` | Partial reorder |
| `GET /faqs/{id}` | One FAQ |
| `PATCH /faqs/{id}` | Edit, publish, unpublish, retag |
| `DELETE /faqs/{id}` | Soft delete, and queue the vector's removal |

`GET /faqs/search` is declared **above** `/{faq_id}` because FastAPI
matches routes in declaration order, and a literal path registered after
a permissive path parameter is unreachable.

`index_state` is on the response for the reason `GET /knowledge/index-status`
exists: every failure mode of a background indexer is invisible from
outside — search simply returns less — and an author needs to see that
the answer they just wrote is not findable yet.

### Reordering is partial by design

`POST /faqs/reorder` takes the ids to move. Ids left out keep their
relative order **after** the ones named. An administrator reordering the
five FAQs on one filtered screen must not silently reshuffle the forty
that screen never loaded, which is what a "this list *is* the order"
contract would do. An unknown id — a stale browser tab holding a deleted
FAQ — is ignored rather than failing the whole reorder.

---

## What is verified

| | |
|---|---|
| Pure contract | 11 unit tests — validation, bounds, locale folding, embeddable text stability, ordering, partial reorder |
| Platform behaviour | 23 integration tests — authoring, publication, indexing, retrieval, isolation, audit |
| Migration | Applied from empty, downgraded and re-applied on **real PostgreSQL**; partial indexes and FK actions inspected |

The tests that matter most are the publication ones:

- **an unpublished FAQ is never embedded**
- **unpublishing takes the vector out of the index**
- **deleting queues the vector's removal in the same transaction**
- **an unpublished FAQ is not returned by search**

Plus the two that justify the design: a term appearing **only in the
answer** still finds the FAQ, and retagging does **not** cost a
re-embedding.

---

## Deliberately not built

Recorded rather than silently omitted, per this codebase's habit.

- **Helpful / not-helpful voting.** A genuine FAQ feature and a cheap
  pair of counters — but it needs a public, unauthenticated write
  endpoint with its own abuse and rate-limiting story. That is a separate
  decision, not a detail of this one.
- **A public help-centre endpoint.** Everything here is agent-facing and
  authenticated. Serving FAQs to an anonymous visitor is a public read
  surface with its own caching and abuse profile, and the web-chat widget
  is the natural first consumer when somebody wants it.
- **Linked translations.** `locale` filters; it does not link an Arabic
  FAQ to its English twin. A translation group is a real feature and a
  bigger one — it needs a canonical side, a staleness rule for when the
  source changes, and a fallback policy.
- **Versioning.** FAQs have the same reproducibility gap as articles
  (**B9**), and they should gain versions in the same change rather than
  inventing a second mechanism first.
- **A frontend.** Backend only, matching the knowledge base's own state.
- **Unicode/whitespace normalisation for trigram matching.** A real idea
  — a question typed with a non-breaking space or full-width punctuation
  is a different string to `pg_trgm` than the one an administrator saved.
  Doing it properly means normalising the *stored* text too, which is a
  write-path change and a backfill. A helper that normalised only the
  query was written, found to be half a mechanism, and removed rather
  than left looking finished.

## See also

- [Company Intelligence Engine](./company-intelligence-engine.md) — Stage 1, the retrieval machinery this reuses
- [Knowledge Base, Quick Replies, Internal Notes](./knowledge-quick-replies-notes.md)
- [AI Engine](./ai-engine.md)
- [Platform Handbook](./platform-handbook.md)
