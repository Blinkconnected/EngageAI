# Facebook Messenger + Instagram Channels

M17 of the roadmap. Two providers built together for the same reason M16
built WhatsApp and Telegram together: they share almost everything.
Messenger and Instagram messaging are the same underlying Meta
"Messenger Platform" product — one webhook envelope
(`entry[].messaging[]`), one Send API shape, scoped to a Facebook Page
versus an Instagram Business Account. Building two nearly-identical
providers side by side in the same milestone is the textbook case *for*
extracting a shared base, not against it (see below) — this is a
different judgment from avoiding speculative abstraction, because the
duplication is concrete and immediate, not hypothetical.

## Shared bases (two of them, for two different kinds of sharing)

- **`_meta_webhook.py`** — free functions (`verify_meta_signature`,
  `meta_hub_challenge_ack`), not a class. WhatsApp (M16, Cloud API),
  Messenger, and Instagram (both Messenger Platform) all use the
  identical `hub.challenge` GET flow and `X-Hub-Signature-256` HMAC
  scheme, despite having otherwise-unrelated send/receive shapes — so
  only *this* piece is shared across all three, as functions each
  provider's `verify_signature`/`webhook` calls into. `WhatsAppProvider`
  was refactored to use these (mechanical, behavior-preserving — its
  existing 21 unit tests were re-run unchanged and still pass) rather
  than leaving a third near-duplicate implementation once Messenger and
  Instagram needed the same logic too.
- **`_meta_messaging.py`** (`MetaMessagingProvider`) — an unregistered
  base class holding everything Messenger and Instagram share: Send API
  calls, `entry[].messaging[]` parsing, attachment upload/download,
  typing indicator, health check. `MessengerProvider`/`InstagramProvider`
  are five-line subclasses that set `_recipient_credential_key`
  (`"page_id"` / `"instagram_id"`) and register themselves —
  `ChannelRegistry.register` sets `channel_type` on each concrete class
  independently, so despite sharing a base, `messenger`/`instagram` never
  collide in the registry.

## Send API and webhook shape

Credentials: `access_token` (a Page access token — Instagram's is the
access token of the Page connected to the IG account), plus the node id
(`page_id` or `instagram_id`) and `verify_token` for the GET handshake.
Unlike WhatsApp's Cloud API (Bearer header), the Messenger Platform's
older Send API passes `access_token` as a **query parameter** — kept
accurate to the real API rather than normalized to match WhatsApp.

- **Outbound**: `POST /{node_id}/messages`. Attachments are a two-step
  upload (`POST /{node_id}/message_attachments`, multipart, `is_reusable`
  requested so the same upload could be resent later) then referenced by
  `attachment_id` in the send call — conceptually the same "upload for an
  id, then reference the id" shape WhatsApp's media upload uses, though
  the two Graph endpoints differ enough that the code isn't shared
  between `_meta_messaging.py` and `whatsapp.py`. Since the Send API has
  no combined text+attachment message, a caption is sent as its own
  preceding text message first.
- **Inbound**: one endpoint carries either real messages
  (`messaging[].message`) or delivery/read/postback events on the *same*
  array — `receive_message` skips entries with no `message` key, mirroring
  how WhatsApp's `receive_message` skips status-only webhook entries.
  Attachments arrive as a direct, pre-authenticated CDN `url` (no
  media-id-then-fetch indirection WhatsApp needs) — one `GET`, then
  re-uploaded into our own `AttachmentStorage`.
- **Sender display name costs an extra call**: unlike WhatsApp's webhook
  (which inlines a `contacts[].profile.name`), Messenger/Instagram
  webhooks carry no name at all — only a sender id. `_fetch_sender_name`
  resolves it with a Graph User Profile call
  (`GET /{sender_id}?fields=first_name,last_name`), landing exactly where
  this document originally predicted the enrichment would go: inside
  `_parse_messaging_item` alone, with zero architecture change. It
  addresses the *sender's* node rather than the channel's own, which is
  why `_graph_root` (versioned base, no node id) was split out of
  `_api_base`.

  Two properties matter more than the call itself:

  - **Every failure degrades to `None`, never to an error.** The lookup
    legitimately fails — for a sender whose profile the app can't read,
    and for essentially every sender while the app is still in
    development mode. A name is an enrichment, not something the
    conversation needs in order to exist, so a failed lookup must not
    fail the webhook: doing so would make Meta retry a delivery that
    could never succeed, and lose a real customer message over a missing
    nicety. The generic `CustomerChannelIdentity` path (M16) then falls
    back to the external id as `Customer.full_name`, exactly as it did
    before this lookup existed. A blank or whitespace-only profile is
    treated as no name for the same reason — a blank customer record is
    worse than the id.
  - **Memoised per webhook batch, not per instance.** One batch routinely
    carries several messages from the same sender, and each lookup is its
    own round-trip. The cache is a local passed down from
    `receive_message`, not instance state: a provider is built per
    request, and a longer-lived cache would need invalidation rules for a
    value that is only ever read when a customer is first created.
- **No reply-context field**: the Send API has no parameter to make a
  business-sent message quote/reference a specific prior customer
  message the way WhatsApp's `context.message_id` does — sending still
  accepts `OutboundMessage.reply_to_external_message_id` uniformly (it's
  part of the channel-agnostic DTO), it's simply not attached to
  anything on this channel, an honest platform limitation rather than an
  invented feature.

## Method fidelity

`mark_as_read` is a no-op — the real `mark_seen` sender action addresses
a *recipient* id, but this ABC method's signature only provides a
*message* id, so there's nothing to call (the same shape of limitation
WhatsApp's `typing_indicator` already had to document). `typing_indicator`
**is** real (`sender_action: "typing_on"/"typing_off"`) since that
method's signature does provide the thread/recipient id. `edit_message`/
`delete_message` are no-ops — the Send API has neither capability for
business-sent messages, matching WhatsApp's platform limitation exactly.

## Schema impact

None — `channel_type="messenger"`/`"instagram"` are new registry values
only, and the M16 `customer_channel_identities` table already generically
covers identity resolution for any channel type without dedicated
`Customer` columns. Zero new tables, zero new migrations.

## Verification performed

28 new tests added (250 → 278 passing — the WhatsApp refactor changed no
test count, its 21 tests were re-run unchanged), all green under
`pytest -q`, `ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_messenger_provider.py` (17 tests) — exercises the full
  shared `MetaMessagingProvider` base via `MessengerProvider`: send (text,
  attachment + leading caption), receive (text, delivery/read events
  skipped, reply threading, URL-based attachment download), GET
  handshake + webhook challenge echo, no-op edit/delete/mark-as-read, real
  typing indicator (both directions), attachment round-trip, health
  check.
- `tests/unit/test_instagram_provider.py` (4 tests) — deliberately light:
  proves the parameterization (registry channel type, credential key,
  request URL, webhook envelope) differs correctly for Instagram, without
  re-testing the shared base logic `test_messenger_provider.py` already
  covers.
- `tests/integration/test_messenger_instagram_webhooks.py` (7 tests) —
  the real HTTP layer for both: GET handshake valid/invalid, POST
  ingestion publishing `message.received` with valid signatures, and
  rejection with invalid ones.

A real Graph API round-trip against a live Facebook Page and connected
Instagram Business Account is a manual verification step, the same bar
established for every other provider in this codebase.
