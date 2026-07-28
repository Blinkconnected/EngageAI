# Conversations, Messages, Attachments

M13 of the roadmap. This is where the "conversation engine" M11/M12
repeatedly promised would exist finally lands: it is, concretely, a
domain-event consumer that turns `message.received` events into
`Conversation`/`Message` rows, plus a read/write API for agents. It never
imports a `ChannelProvider` — the only place that happens is the
outbound-reply path, and even there it goes through
`ChannelProviderFactory`, never a concrete provider class.

## Data model

Built exactly to the schema `docs/architecture/channels.md` (M11) already
specified, with one refinement noted below.

```
conversations
-------------
id (PK)
company_id (FK -> companies, CASCADE)
customer_id (FK -> customers)
channel_config_id (FK -> channel_configs)
external_thread_id (nullable, unique per channel_config_id among active rows)
status            open | pending | resolved | closed
priority          low | normal | high | urgent (default normal — Beta 4, see below)
assigned_agent_id (FK -> agents, SET NULL, nullable)
department_id (FK -> departments, SET NULL, nullable — Sprint 2 Item 4, see below)
last_message_at (nullable)
created_at / updated_at / deleted_at

conversation_transfers
-----------------------
id (PK)
company_id (FK -> companies, CASCADE)
conversation_id (FK -> conversations, CASCADE)
target_type        agent | department | queue (future-ready, unused today)
from_agent_id (FK -> agents, SET NULL, nullable — the assignment before this transfer)
to_agent_id (FK -> agents, SET NULL, nullable)
to_department_id (FK -> departments, SET NULL, nullable)
to_queue_id (FK -> queues, SET NULL, nullable — unused today)
note (nullable)
transferred_by_user_id (FK -> users, SET NULL, nullable)
recipient_was_online (bool — see decision #6 below)
created_at              (append-only: no updated_at/deleted_at — a transfer is a fact, never edited)

messages
--------
id (PK)
company_id, channel_type      denormalized (see channels.md's reasoning)
channel_config_id (FK)
conversation_id (FK -> conversations, CASCADE)
customer_id (FK -> customers)
external_message_id (nullable, unique per channel_config_id among rows that have one)
direction         inbound | outbound
message_type      text | media | system
status            pending | sent | failed              (our processing state)
delivery_status   pending | delivered | undelivered | not_applicable  (provider-confirmed)
read_status       unread | read
body (nullable — a media-only message has no text)
reply_to_message_id (nullable self-FK, SET NULL)
metadata (JSON)
sent_at / delivered_at / read_at (nullable)
created_at / updated_at / deleted_at

message_attachments
-------------------
id (PK)
conversation_id (FK -> conversations, CASCADE)
message_id (FK -> messages, CASCADE, **nullable** — see decision #1)
storage_key        the AttachmentStore/MinIO object key
filename, content_type, size_bytes
validation_status  pending | approved | rejected
created_at
```

## Key architectural decisions

1. **`message_attachments.message_id` is nullable, refining M11's "child
   table, FK to messages" line.** Uploading and composing a reply are two
   separate requests (`POST .../attachments` then `POST .../messages`), so
   an attachment exists — validated, stored in MinIO — *before* the
   message that will reference it does. `conversation_id` is set
   immediately (so an orphaned upload is still scoped/ownable/cleanable);
   `message_id` is filled in when the reply is sent, in the same
   transaction as the `Message` insert.

2. **The conversation engine is a domain-event consumer
   (`infrastructure/events/consumers/conversation_ingest_consumer.py`),
   not a service called synchronously from the webhook route or the
   WebSocket gateway.** M11/M12 deliberately stopped at "publish
   `message.received`" precisely so this milestone could be *only* a
   subscriber — adding conversation persistence required zero changes to
   `WebhookIngestService`, the webhook route, or `webchat_gateway`. This is
   the M10 event bus doing exactly what it was built for.

3. **Customer identity resolution stays channel-specific and minimal —
   still deferred where M8 said it would be.** `message.received`'s
   `external_customer_id` means something different per channel: for
   `web_chat` it's literally our own `Customer.id` (the visitor session
   already resolved identity — see `web-chat.md`), because the customer
   record was created before the first message ever arrived. Every future
   provider-pushed channel (WhatsApp phone number, a Messenger PSID, ...)
   will need real matching/merge logic against existing customers, which
   is exactly the "multi-channel identity resolution" M8 explicitly
   deferred until channels existed to need it. That's still true — only
   `web_chat` exists, and its resolution is a direct UUID parse, not a
   general resolver. The consumer's customer-resolution step is
   structured as a per-`channel_type` branch specifically so adding real
   resolution for WhatsApp et al. later doesn't touch the web_chat branch.

4. **Attachment type validation now; virus scanning deliberately
   deferred, not faked.** `AttachmentValidationService` checks
   `content_type` against an allowlist and enforces a max size
   (`settings.attachment_allowed_content_types`/
   `attachment_max_size_bytes`) before anything reaches MinIO — a
   `MessageAttachment.validation_status` of `rejected` never gets
   persisted (the upload 400s) and `approved` is the only status this
   milestone ever writes. `pending` exists in the enum for a real
   antivirus hook (e.g. ClamAV) to land in later — that needs a new
   docker-compose service and a scanning client this milestone doesn't
   add, so `pending` is unused today rather than half-wired to a scanner
   that isn't there. Documenting the gap here rather than stubbing a
   scanner that always says "clean" is the honest choice.

5. **`Conversation.department_id` is a genuinely new, first-class
   routing field — not the same thing as `Queue.department_id`.** The
   latter is documented in `docs/architecture/queues-routing.md` as "an
   organizational label, not an eligibility filter." This one *is* the
   conversation's actual current routing target: a department transfer
   sets it and clears `assigned_agent_id`; an agent transfer sets
   `assigned_agent_id` and clears it. The two fields are mutually
   exclusive by construction (`ConversationService.transfer()`), never by
   a DB constraint, matching this codebase's general preference for
   service-layer invariants over check constraints for anything that
   needs a domain error message rather than a raw DB error.

6. **Transfers are append-only history, not a mutable "current assignment"
   annotation.** `ConversationTransfer` rows are never updated or
   soft-deleted — each one is an immutable fact ("at this time, this
   conversation moved from X to Y"), read back via
   `GET /conversations/{id}/transfers` for the conversation view's
   "Transfers" tab. `recipient_was_online` is computed once, at transfer
   time, from `AgentStatus` — it answers "was the receiving agent
   connected when this happened," not "is the transfer still pending
   acceptance." There is no acceptance workflow: reassignment happens
   immediately (`assigned_agent_id`/`department_id` update in the same
   transaction as the history row), matching this codebase's existing
   assignment model, which has never required an agent to confirm
   incoming work. An offline recipient still gets a durable `Notification`
   row via the existing outbox → notification-consumer pipeline — no new
   "return from offline" mechanism needed, since the badge/poll flow
   already surfaces unread notifications whenever that agent is next
   active. For a department-target transfer, `recipient_was_online`
   reflects whether *any* current member of that department was online at
   transfer time (false if the department has no agents at all).

7. **Reassignment is transfer-only.** `PATCH /conversations/{id}` no
   longer accepts `assigned_agent_id` (the field was removed from
   `ConversationUpdateRequest`) — every reassignment must go through
   `POST /conversations/{id}/transfer` so it always produces a history row,
   an audit-log entry, and a notification. The generic PATCH endpoint
   silently ignores an `assigned_agent_id` key in its payload rather than
   422ing, since the schema no longer declares the field and nothing in
   this codebase's request models sets `extra="forbid"`.

8. **Outbound replies go through the same `ChannelProviderFactory` the
   webhook route and WebSocket gateway already use — no new provider
   dispatch mechanism.** `ConversationService.send_reply` loads the
   conversation's `ChannelConfig`, builds the provider, calls
   `send_message()` with any linked attachments turned into
   `OutboundAttachment`s (re-downloaded from `AttachmentStore` — the
   provider needs bytes, not just a key) and `reply_to_external_message_id`
   set to the replied-to message's `external_message_id`, persists the
   `Message` row with the `SendResult`'s `external_message_id`, and
   publishes `message.sent`. For `web_chat`, `send_message` publishes to
   the visitor's Redis session channel, and the already-connected
   WebSocket gateway forwards it — the whole inbound→persist→reply→deliver
   loop closes end-to-end with the one channel that exists.

## API

`GET /conversations`, `GET /conversations/{id}`,
`PATCH /conversations/{id}` (status transitions only — assignment moved
to the transfer endpoint below, Sprint 2 Item 4) — all
`conversations.read`/`conversations.manage` (already seeded back in M6, no
new permissions needed). `GET /conversations/{id}/messages` (paginated),
`POST /conversations/{id}/messages` (send a reply — `conversations.manage`),
`POST /conversations/{id}/attachments` (upload — `conversations.manage`),
`GET /conversations/{id}/attachments/{attachment_id}/download`
(`conversations.read`). `DELETE /conversations/{id}` uses the existing
`conversations.delete` permission (soft-delete).

`POST /conversations/{id}/transfer` (Sprint 2 Item 4, `conversations.transfer`)
— body is `{target_type: "agent"|"department"|"queue", to_agent_id?,
to_department_id?, note?}`, validated so the target id matching
`target_type` is required. `queue` is future-ready architecture only per
the milestone's own requirement: the `TransferTargetType` enum and the
`ConversationTransfer.to_queue_id` column both already exist, but the
request schema has no `to_queue_id` input field and
`ConversationService.transfer()`'s queue branch only unassigns the
conversation (clears `assigned_agent_id`/`department_id`, never sets
`to_queue_id`) — a real queue-transfer implementation is future work, not
shipped here. Returns the created `ConversationTransfer`. `GET
/conversations/{id}/transfers` (`conversations.read`, paginated,
newest-first) backs the conversation view's "Transfers" tab and
`GET /conversations?assigned_agent_id=` (any read-scoped caller) backs
the Inbox's "My conversations only" toggle.

`MessageResponse.attachments` (Sprint 2 "Pilot Feedback & UX
Improvements", Item 3) — populated by both `GET .../messages` and
`POST .../messages` via `ConversationService.list_attachments_for_messages()`,
a batch query (not N+1) grouped by `message_id` at the endpoint layer.
Deliberately not an ORM relationship on `Message` itself — see this
file's own reasoning above on staying join-free at this table's scale.

Status transitions are validated (`open → pending → resolved → closed`,
plus reopening a `resolved`/`closed` conversation back to `open`) —
illegal transitions (e.g. `closed → pending` directly) raise a domain
error mapped to 400, not silently accepted.

## Priority, unread count, and SLA warning exposure (Beta 4)

9. **`Conversation.priority` is a pure triage/UX signal, deliberately
   decoupled from SLA policy.** `ConversationPriority` (`low` / `normal`
   / `high` / `urgent`, ordered low-to-high) never changes an
   `SlaPolicy`'s response/resolution targets — those stay entirely
   queue-driven, as before. Priority only drives the Inbox's default sort
   order (`_PRIORITY_RANK` in `ConversationRepository`, applied before the
   existing `last_message_at desc, created_at desc` ordering) and the
   redesigned Inbox's visual urgency badge. Settable via the existing
   generic `PATCH /conversations/{id}` (`priority` field on
   `ConversationUpdateRequest`) and filterable via `GET
   /conversations?priority=`, both under the existing
   `conversations.manage`/`conversations.read` permissions — no new
   permission needed. Stored via `Enum(native_enum=False)`, which persists
   a `StrEnum` member's uppercase **name** (`"NORMAL"`), not its lowercase
   `.value` (`"normal"`) — the same convention `ConversationStatus`
   already used; a hand-written SQL expression referencing the stored
   value (e.g. the sort-order `CASE`) must key off `.name`, not `.value`.

10. **`unread_count` is a computed, non-persisted aggregate, not an ORM
    column.** `MessageRepository.unread_counts_for_conversations()` runs
    one grouped query per page of conversations (never N+1), counting
    `direction=inbound, read_status=unread` messages, matching the
    existing `CustomerInternalRatingRepository.summary_for_customers()`
    batch-aggregate pattern. `ConversationService.list_messages()` — the
    sole consumer of `GET /conversations/{id}/messages` (only mounted by
    `MessageThread.tsx` for a genuinely open conversation, confirmed by
    grep) — marks every unread inbound message read as a side effect of
    that fetch, since viewing a conversation's messages *is* reading them;
    the repeated 15s poll this endpoint already receives is a cheap no-op
    `UPDATE` once nothing is left unread. Every endpoint that returns a
    `Conversation` (`list`, `get`, `update`, `pick`, `release`) threads
    this aggregate through a `_to_conversation_response()` helper (the
    same "aggregate value through a per-row helper" shape
    `customers.py`'s `_to_response()` already established) — a bare
    `ConversationResponse.model_validate(conversation)` would otherwise
    silently default `unread_count` to `0` on every one of them.

11. **SLA warning timestamps were already written, just never returned.**
    `sla_first_response_warned_at`/`sla_resolution_warned_at` (see
    `sla.md`) have existed on the `Conversation` model since the SLA
    engine's own milestone — Beta 4 only adds them to
    `ConversationResponse`, a schema-only change with no migration. They
    let the Inbox distinguish "approaching SLA" (a warning fired, not yet
    breached) from "breached" as two visually distinct states instead of
    one flat "at risk" signal.

**Beta 4 verification**: 8 new backend tests (priority defaults to
`normal`, PATCH updates it, an unknown value 422s, list filtering and
urgent-first ordering regardless of recency, unread count reflects
inbound messages and clears on view, an agent's own outbound replies
never count as unread, SLA warning fields are exposed and null before any
warning fires) — 965 backend tests total, `mypy`/`ruff` clean. Migration
applied and downgrade/upgrade-cycled twice against real Postgres;
`information_schema.columns` confirmed the live default is
`'NORMAL'::character varying`. `GET /api/v1/openapi.json` confirmed live
against the running stack: `ConversationResponse` includes all four new
fields, and `GET /conversations` accepts a real `priority` query
parameter. Frontend: `tsc`/`eslint` clean, 279 frontend tests passing.

## Verification performed

23 new tests. `handle_message_received` (the ingest consumer): creates a
conversation + message for a new thread, reuses the conversation for a
second message on the same `external_thread_id` (bumping
`last_message_at`), is idempotent on a duplicate `external_message_id`
(at-least-once delivery), skips platform-level events with no company,
and skips a channel type with no customer-resolution branch yet.
Conversation CRUD: list/get/update/delete, status filtering,
tenant-isolation, unauthenticated rejection, and status-transition
validation (a legal transition like `open → resolved` succeeds; an
illegal one like `closed → pending` 400s; reopening a `closed`
conversation back to `open` is explicitly allowed). Attachments: upload
accepts an allowed content type and rejects a disallowed one, download
round-trips the exact bytes uploaded (a `FakeAttachmentStore` in-memory
double stands in for MinIO — no real object-storage server runs in the
test suite, verified manually against `docker compose` instead, same bar
as the rest of this codebase's external-infra boundaries). And the full
loop: a visitor message ingested into a new conversation, an agent reply
sent through `ConversationService.send_reply`, the reply observed
arriving back over the visitor's `web_chat` session channel via a
subscribed `fakeredis` pubsub handle, a `message.sent` event landing in
the outbox, and an attachment correctly linked to (and rejected from
double-linking onto) an outbound message. 146 tests total passing across
the whole suite; `ruff check`/`mypy` clean.

**Sprint 2 "Pilot Feedback & UX Improvements", Item 3 (2026-07-25)**:
2 new/extended tests proving `attachments` is populated correctly on
both `send_message`'s immediate response and `list_messages` (including
a text-only message getting an empty list, not a missing field) — 568
backend tests total. Also fixed, on the frontend side: attachment
upload explicitly set `Content-Type: multipart/form-data` with no
`boundary`, which — verified directly against axios's installed source
and reproduced as a raw request against the live backend — the server
flatly rejects with `400 Missing boundary in multipart`. Upload from a
real browser could not have worked at all before this fix. See
`docs/ROADMAP.md`'s Item 3 entry for the full verification chain.

**Sprint 2 "Pilot Feedback & UX Improvements", Item 4 (2026-07-25)**:
Conversation Transfer — 15 new backend tests (transfer-to-agent and
transfer-to-department including cross-field clearing, note + full
history, RBAC denial for a plain Agent, audit-log creation, 422/404
validation, SLA-timer/message-history preservation, `recipient_was_online`
correctness, inbox filtering, and PATCH no longer reassigning) plus 2 new
notification-consumer tests (agent fanout, department fanout with a
control agent outside the department) — 583 backend tests total. 5 new
frontend tests — 83 total. Full chain verified live against the
production Docker stack with two real logged-in sessions (an Owner and
an Agent connected over the real `/ws/agent` WebSocket gateway): a
transfer to the connected agent delivered a `conversation.transferred`
notification frame over their live socket, correctly recording
`recipient_was_online: true`; a follow-up department transfer correctly
cleared the agent assignment and recorded `recipient_was_online: false`
(the target department had no members). Both transfers appeared in
`GET /audit-logs` with full detail. See `docs/ROADMAP.md`'s Item 4 entry
for the full verification chain, including the pre-existing
permission-backfill gap this milestone discovered and partially fixed.
