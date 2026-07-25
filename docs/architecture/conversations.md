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
assigned_agent_id (FK -> agents, SET NULL, nullable)
last_message_at (nullable)
created_at / updated_at / deleted_at

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

5. **Outbound replies go through the same `ChannelProviderFactory` the
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
`PATCH /conversations/{id}` (status transitions, assignment) — all
`conversations.read`/`conversations.manage` (already seeded back in M6, no
new permissions needed). `GET /conversations/{id}/messages` (paginated),
`POST /conversations/{id}/messages` (send a reply — `conversations.manage`),
`POST /conversations/{id}/attachments` (upload — `conversations.manage`),
`GET /conversations/{id}/attachments/{attachment_id}/download`
(`conversations.read`). `DELETE /conversations/{id}` uses the existing
`conversations.delete` permission (soft-delete).

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
