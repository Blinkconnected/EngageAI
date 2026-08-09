# Redacting a message

Removing what a message said, keeping that it was said.

## Why not deletion

Deletion was the obvious request and the wrong answer.

A message sent over WhatsApp, SMS or email **cannot be unsent**. The
customer keeps their copy whatever we do to ours. Deleting the row
destroys our half of a record the other half of which still exists — we
lose the ability to answer *"what did we tell them?"*, and the customer
can still produce it. In a dispute that is the worst possible position.

Redaction keeps the shape of the conversation and removes the content.
The message stays in the thread, in order, attributed, timestamped, and
marked redacted. What it said is gone. Who removed it and why is
permanently on the record.

## The permission

| Permission | Owner | Admin | Agent |
|---|---|---|---|
| `messages.redact` | ✅ | ✅ | ❌ |

Administrators, because they are the compliance contact in most
companies and an Owner-only control would go unused. **Not agents**: a
redaction cannot be undone by the person who notices the mistake a
minute later, so it is not routine work.

**It does not weaken the deletion boundary.** `conversations.delete` —
which destroys a whole conversation with no reason recorded, and which
also gates bulk destruction through `POST /agents/{id}/removal` — remains
Owner-only. Asserted in `test_destructive_permission_boundaries.py` and
again in the redaction tests, because the natural way to break it is to
add a new destructive permission and grant it more widely than the old
one.

There is no bulk endpoint. Redaction is one message at a time, on
purpose: it is the difference between a correction and a purge.

## What it removes, and where from

The hard part is not blanking a column. Message content does not stay in
the message. Each of these is a place a body-only redaction would leave
it, reporting success:

| Where | What happens |
|---|---|
| `messages.body` | Overwritten with `NULL`, in place |
| `messages.message_metadata` | Filtered to an **allow-list** — providers echo the body back |
| Attachments | Objects deleted from storage, then the rows |
| `memory_evidence` | Citations of this message deleted |
| `learning_observation_refs` | Citations deleted; an observation left with none is discarded |
| Future Learning sweeps | The message is filtered out at the source query |

All in one transaction. Attachments go **first**: if object storage
refuses, everything rolls back and the message keeps its content —
better than a message reading "redacted" beside a downloadable file of
what it said.

### The metadata allow-list

`METADATA_KEYS_KEPT` is an allow-list, not a deny-list, and that
distinction is the whole of it. Providers add fields, workflows write
their own, and a deny-list silently leaks every key nobody thought of —
which here means leaking exactly the content redaction was meant to
remove.

Kept: `is_ai_generated`, `error`, `provider`, `channel_type`,
`delivery_attempts`. Provenance and delivery facts, none of them
customer content, and the conversation stops making sense without them.

### Memory and Learning

Both store **pointers, never copies** — a pre-existing design decision
(`MemoryEvidence`'s own docstring: *"Storing a conversation excerpt here
would put customer content into a second store with different
retention"*). So redaction is not deleting content twice; it removes the
**citation**. A fact whose evidence is a redacted message is a fact
nobody can check, and a redacted message must never be the reason the
platform believes something.

Learning observes *conversations* and cites individual messages through
`LearningObservationRef`. Only the citation is removed: discarding the
whole observation would throw away what was learned from the rest of a
conversation because one message in it was redacted. An observation left
with no citations at all goes to `discarded`.

**The forward half.** Removing existing citations is not enough — the
next sweep reads the conversation again. `_turns_for` filters
`redacted_at IS NULL`, so a redacted message is not picked back up. Not
even as an empty turn: that would shift every ordinal after it and let
the conversation be observed as if the customer had said nothing at that
point, which is a worse distortion than the turn being absent.

### Paths that were already sealed

Verified rather than assumed, and covered by tests so they stay that
way:

- **Global search** never indexed message bodies (conversations match
  through their customer — see `global-search.md`). A future full-text
  message search would reintroduce every redacted string, so there is a
  test.
- **AI transcripts** are built with `if message.body:`, so a redacted
  message contributes nothing.
- **The Conversation Inspector** reads `Message` rows, whose bodies are
  now `NULL`.
- **Reports and exports** aggregate from summary tables and never read
  message bodies.

## The record

`message_redactions` is append-only. Nothing in the application updates
or deletes a row after insert, and no endpoint exposes either. That is
the point: a redaction is irreversible, so the account of it must be the
one thing that cannot be quietly revised afterwards.

Every foreign key is `ON DELETE SET NULL`, never `CASCADE` — purging the
conversation later must not take the paperwork with it. `company_id`,
`customer_name` and `redacted_by_name` are denormalised onto the row so
it stays attributable and readable after everything it points at is
gone.

It records: actor (id **and** name), timestamp, reason, `message_id`,
`conversation_id`, `company_id`, scope, and counts of what was purged.
Counts rather than descriptions — *"3 attachments purged"* can be checked
against object storage years later; *"attachments removed"* cannot.

**The record never carries the content.** There is no field on
`MessageRedactionResponse` through which a redacted body could travel,
not even for an administrator. A "just this once, show me what it said"
affordance would make every other guarantee on this page untrue.

## API

| Endpoint | Permission |
|---|---|
| `POST /conversations/{id}/messages/{message_id}/redact` | `messages.redact` |
| `GET /message-redactions` | `messages.redact` |

The reason is mandatory, minimum 10 characters, whitespace collapsed
before measuring.

| Condition | Status |
|---|---|
| Not found, or another tenant's | 404 — a cross-tenant id must not be confirmed to exist |
| Already redacted | 409 — retry-safe; a duplicate delivery cannot append a second account |
| Reason too short/long | 400 (422 when Pydantic catches it first) |
| Without the permission | 403 |

Scoped by **conversation as well as company**. Company-only scoping would
let a caller redact any message in their tenant through any conversation
id they can see, turning a per-conversation check into a company-wide
one.

## What redaction is not

- **Not reversible.** No backup restore path is offered, and the
  migration's own downgrade says so: dropping the columns does not
  return the content, because it was overwritten in place.
- **Not erasure of the customer's copy.** Their phone still has the
  message.
- **Not a substitute for conversation deletion.** For "remove this
  entire conversation", see `conversation-deletion.md`.

## Verification performed

- `tests/unit/test_message_redaction_rules.py` (11) — the reason floor
  including whitespace-only, refusing a second redaction, and the
  metadata allow-list: provider echoes stripped, provenance kept, fifty
  unknown keys all removed, and a guard that nothing content-shaped is
  ever added to the allow-list itself.
- `tests/integration/test_message_redaction.py` (23) — Owner and Admin
  may redact and an Agent may not, in either direction; the boundary
  test that `conversations.delete` did not spread; content gone from the
  API, from provider metadata in the database, from AI transcripts, from
  search and from the Inspector; the row surviving so the thread still
  reads; memory citations removed; learning citations cut while the rest
  of the observation survives; a redacted message never re-entering
  `_turns_for`; the full audit record; the log never carrying content
  and being company-scoped; cross-tenant and cross-conversation both
  404; redacting twice a 409 with only one record; and attachments
  purged from object storage.
