# WhatsApp Business + Telegram Channels

M16 of the roadmap. Two providers built together because they exercise
the same new architectural piece from opposite directions: WhatsApp needs
a webhook *handshake* the plugin architecture hadn't solved yet; Telegram
needs *customer identity resolution* with no natural `Customer` column to
land on. Both are answered by generalizing, not special-casing.

## Generic customer identity resolution (`CustomerChannelIdentity`)

`Customer`'s own docstring predicted this since M8: "multi-channel identity
resolution... deferred to Phase 4, once the Channels/Conversations feature
actually creates per-channel contact records for a customer to resolve
against." Email (M15) resolved onto the existing `Customer.email` column
because an email address already *is* one. WhatsApp's `wa_id` and
Telegram's numeric user id have no equivalent — a wa_id isn't always the
same number as a CRM-entered `Customer.phone`, and there is no
`Customer.telegram_id` column and never should be one (that doesn't scale
to the next twenty channels).

So M16 builds the generic mechanism instead of a third special case:
`customer_channel_identities` (`company_id`, `customer_id`, `channel_type`,
`external_id`, unique on the first/third/fourth) — a many-rows-per-customer
mapping table. `conversation_ingest_consumer._resolve_customer_id` gets one
new fallback branch, used by *every* channel type that isn't `web_chat` or
`email`: look up `(company_id, channel_type, external_id)`; if found,
return the linked customer; if not, create a `Customer` and link it. This
branch is channel-agnostic — it doesn't know or care whether `channel_type`
is `"whatsapp"`, `"telegram"`, or something that doesn't exist yet.
Messenger/Instagram/SMS (M17/M18) need zero new resolution code, only a
new registered `ChannelProvider`.

WhatsApp and SMS external ids happen to be phone numbers, so on
first-contact customer creation this branch also seeds `Customer.phone`
(a `_PHONE_LIKE_CHANNELS` allow-list) — a convenience for search/display,
never a resolution mechanism. Resolution always goes through
`CustomerChannelIdentity`, never back through `Customer.phone`, so a
customer having a different landline in their CRM record than their
WhatsApp number is not a conflict.

Email and Web Chat keep their existing M13/M15 branches rather than being
migrated onto this table — both already shipped, tested behavior against a
real, purpose-built `Customer` column before this table existed, and
retrofitting them for symmetry alone isn't worth the churn.

## Solving the M11 "known concern": provider GET handshakes

M11 flagged Meta's `hub.challenge` verification flow as a concern to solve
"when that provider is actually built" rather than design for
prematurely. WhatsApp is that provider. Meta requires a **GET** request to
the webhook URL (`hub.mode=subscribe&hub.verify_token=...&hub.challenge=...`)
to succeed, with the literal challenge value echoed back, before it will
ever POST a real message.

Solved without a 12th `ChannelProvider` method (the interface is a hard
11-method contract) by reusing the two hooks every provider already has:

- `POST /webhooks/{channel_config_id}` (M11) is joined by a new
  `GET /webhooks/{channel_config_id}` in the same route module. It builds
  a `WebhookRequest` with an empty body and the real query params, and
  calls the *exact same* `WebhookIngestService.ingest()` — no new service
  method.
- `WhatsAppProvider.verify_signature` special-cases
  `query_params["hub.mode"] == "subscribe"`: checks `hub.verify_token`
  against `credentials["verify_token"]` instead of computing an HMAC (a
  GET handshake has no body to sign).
- `WhatsAppProvider.webhook` special-cases the same condition: returns
  `([], WebhookAck(status_code=200, body=hub.challenge))` — using
  `WebhookAck.body`, a field that already existed since M11 specifically
  documented for "echoing a verification challenge token."

Providers with no such handshake (Telegram, email, Web Chat) simply never
see a GET with `hub.mode` set, so nothing about them changes.

## WhatsApp: Meta Cloud (Graph) API

Credentials: `access_token`, `phone_number_id`, `verify_token` (GET
handshake only — the POST signature check uses the existing
`ChannelConfig.webhook_secret` column, consistent with every other
provider, not a separate credentials key).

- **Outbound**: `POST /{phone_number_id}/messages`. Attachments are a
  two-step Graph API dance — upload to `/{phone_number_id}/media` first to
  get a `media_id`, then reference it in the message body (`caption` set
  from `OutboundMessage.body` on the first attachment only, matching how
  one WhatsApp message carries at most one media item).
- **Inbound**: one webhook payload can carry either real messages
  (`value.messages[]`) or delivery-status updates (`value.statuses[]`) on
  the *same* endpoint — `receive_message` skips status-only entries
  instead of erroring, since those aren't `InboundMessage`s. Media
  attachments require a second round trip (`GET /{media_id}` for a
  short-lived URL, then `GET` that URL) before landing in our own
  `AttachmentStorage` — same "download from the provider, re-upload to our
  store" shape every provider's inbound attachment handling already uses.
- **`mark_as_read`** is real (`POST /messages` with
  `{"status": "read", "message_id": ...}`) — WhatsApp is the first channel
  where this method does something. **`typing_indicator`** stays a no-op:
  the Cloud API only exposes typing as a side effect of marking one
  specific message read, which needs a message id, not the thread id this
  method's signature provides. **`edit_message`/`delete_message`** are
  no-ops — the platform has neither capability for business-sent messages.

## Telegram: Bot API

Credentials: `bot_token`. Signature verification uses
`X-Telegram-Bot-Api-Secret-Token` (an exact-match header Telegram sends
when a webhook is registered with a `secret_token`, compared via
`hmac.compare_digest` against `ChannelConfig.webhook_secret`) — not HMAC
over the body, since Telegram doesn't sign payloads that way.

- **Composite message ids**: `editMessageText`/`deleteMessage` need both a
  `chat_id` and a `message_id`, but `ChannelProvider.edit_message`/
  `delete_message` take one opaque string. Telegram's
  `external_message_id` is `f"{chat_id}:{message_id}"` for both inbound
  and outbound messages uniformly, so replies and edits can always
  recover both values by splitting on `:` — a self-contained provider
  choice (the id is otherwise meaningless outside this class), not an ABC
  change.
- **Outbound attachments**: unlike WhatsApp's two-step media upload,
  Telegram's `sendPhoto`/`sendDocument` accept a direct multipart file
  upload in the same call that sends the message — no separate upload
  step needed.
- **`typing_indicator`** is real for `is_typing=True` (`sendChatAction`
  with `action="typing"`); `is_typing=False` is a no-op, since Telegram's
  indicator auto-expires (~5s) and the Bot API has no explicit "stop"
  call. **`mark_as_read`** stays a no-op — the Bot API exposes no
  read-receipt concept for a bot to surface. **`edit_message`/
  `delete_message`** are real (`editMessageText`/`deleteMessage`), unlike
  WhatsApp — Telegram actually supports both.

## Schema impact

One new table (`customer_channel_identities`), covered above — a
one-time generalization, not a per-channel migration. `channel_configs`
and `messages` needed no changes; `channel_type="whatsapp"` /
`"telegram"` are just new registry values, per M11's original design.

## Verification performed

52 new tests added (198 → 250 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_whatsapp_provider.py` (21 tests) — send (text, reply
  context, attachment upload + caption), receive (text, status-only
  skip, reply threading, media download), signature verification (HMAC,
  GET handshake valid/invalid, missing-secret-fails-closed), webhook
  (challenge echo, POST delegation), `mark_as_read`, no-op methods,
  attachment round-trip, health check — all against `httpx.MockTransport`
  (no new dependency; `httpx` was already in use).
- `tests/unit/test_telegram_provider.py` (22 tests) — send (text, reply,
  photo, document), receive (text, username fallback, reply threading,
  non-message updates skipped, document download), real edit/delete,
  typing indicator (on and the True/False asymmetry), signature
  verification, webhook delegation, attachment round-trip, health check.
- `tests/integration/test_whatsapp_telegram_webhooks.py` (6 tests) — the
  real HTTP layer: WhatsApp's GET handshake (valid/invalid token), both
  providers' POST ingestion publishing `message.received` with valid
  signatures, and rejection with invalid ones.
- `tests/integration/test_conversation_ingest_consumer.py` (4 tests added,
  1 removed — net +3) — the now-obsolete "whatsapp is unresolvable" test
  is replaced by coverage of the generic `CustomerChannelIdentity` path:
  first-contact creation and reuse on a second message for a channel type
  that doesn't even exist yet (`some_future_channel`, proving the
  mechanism is genuinely channel-agnostic), phone-seeding for WhatsApp
  specifically, and blank-external-id skip.

A real Graph API/Bot API round-trip against a live WhatsApp Business
number and Telegram bot is a manual verification step, the same bar
established for SMTP/IMAP (M15) and MinIO/RabbitMQ elsewhere in this
codebase. The `a1b2c3d4e5f6` migration was additionally verified against
a real running Postgres instance (upgrade, downgrade, re-upgrade), not
only SQLite.
