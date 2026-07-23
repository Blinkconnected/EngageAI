# SMS Channel

M18 of the roadmap, closing out Phase 3 (Omnichannel Expansion). The
roadmap names this one differently from every other channel milestone:
"SMS channel (**provider-agnostic gateway abstraction**)" — unlike
WhatsApp/Telegram/Messenger/Instagram (each tied to exactly one vendor's
API), SMS has no shared protocol at all. Twilio, Vonage, MessageBird,
Plivo, and AWS SNS are all genuinely different APIs for the same medium.
Registering each one directly as a top-level `ChannelProvider` would mean
"twilio" and "vonage" show up as unrelated channel types instead of two
ways to run the same "sms" channel — wrong shape for what they actually
are.

## A second, inner plugin layer

`SmsProvider` (`ChannelRegistry`, channel type `"sms"`) is deliberately
thin: it validates/constructs, then delegates every capability to
whichever `SmsGateway` its config names (`credentials["gateway"]`, e.g.
`"twilio"`). `SmsGateway` (`domain/sms_gateway.py`) is an ABC + registry
(`SmsGatewayRegistry`) that mirrors `ChannelProvider`/`ChannelRegistry`
one level down — same shape, same reasoning (named lookup from a
database-stored string, not a Python reference already in scope), scoped
to gateway vendors instead of channel types. Adding Vonage later is one
new `SmsGateway` subclass + one registry line; `SmsProvider` itself never
changes — the exact same guarantee `ChannelRegistry` gives the outer
layer.

`SmsGateway`'s methods reuse `domain.channels` DTOs directly
(`InboundMessage`, `WebhookRequest`) rather than a parallel SMS-specific
DTO hierarchy — there was nothing SMS-specific to add that the existing
channel-agnostic contract didn't already cover.

## `TwilioGateway`: the first concrete gateway

Credentials: `account_sid`, `auth_token`, `from_number` (E.164).

- **Send**: `POST /2010-04-01/Accounts/{sid}/Messages.json` (Basic Auth),
  form-encoded `To`/`From`/`Body`.
- **Inbound**: Twilio POSTs `application/x-www-form-urlencoded` (not
  JSON, unlike every provider built so far) — `parse_inbound` decodes via
  `urllib.parse.parse_qsl`. `external_thread_id`/`external_customer_id`
  are both the sender's `From` number (mirrors WhatsApp's 1:1-thread
  design) and flow into the M16 phone-seeding allow-list
  (`_PHONE_LIKE_CHANNELS` already included `"sms"`, anticipated when that
  set was built). MMS media (`NumMediaN` > 0, `MediaUrlN`) is downloaded
  with Basic Auth and re-uploaded into our own `AttachmentStorage` —
  Twilio hosts inbound media, so this direction has no public-URL problem.
- **Signature**: Twilio's own scheme — HMAC-SHA1 (not SHA256) over the
  **full webhook URL** concatenated with sorted POST-param key+value
  pairs, base64-encoded (not hex), compared against `X-Twilio-Signature`.
  Different enough from every Meta-family provider's HMAC-SHA256-over-body
  scheme that it isn't shared code, and specifically why `WebhookRequest`
  needed a new `url` field (see below).

## `WebhookRequest` gained a `url` field

Every provider built through M17 signs over headers/body only. Twilio is
the first to sign the request URL itself, so `domain/channels.py`'s
`WebhookRequest` gained `url: str = ""` — additive, default empty, no
existing provider needed to change.

Populating it correctly matters: `str(request.url)` from the ASGI scope
would reflect whatever scheme/host uvicorn sees on its own connection,
which is `http://backend:8000/...` behind this stack's nginx, not the
public HTTPS URL Twilio actually POSTs to and signs against — a
real mismatch, not a hypothetical one. Trusting `X-Forwarded-Proto`/
`X-Forwarded-Host` would fix that, but this stack's `docker-compose.yml`
also publishes the backend's port directly to the host (`8000:8000`)
alongside nginx on `:80` — so forwarded headers would be spoofable by
anything that can reach the backend port directly, not just nginx.

Instead: a new `settings.public_base_url` (env `PUBLIC_BASE_URL`, default
`http://localhost`) names the externally-visible scheme+host explicitly,
and the webhook routes build `f"{settings.public_base_url}{request.url.path}"`
(plus query string if present) rather than trusting anything
request-derived for the scheme/host. This must be set to the real public
domain in production — same category of deployment-specific config as
`CORS_ALLOW_ORIGINS`.

## Scope boundary: text-only outbound

Outbound MMS is **not** built. Twilio's send API takes a `MediaUrl` it
fetches itself — it has no "upload bytes, get a reference" mechanism the
way Meta's Graph API does, so sending an attachment stored in our private
MinIO bucket would require exposing a public, provider-fetchable URL to
it (a presigned MinIO URL, or an authenticated-but-fetchable proxy
endpoint on our own API). That's a real cross-cutting concern of its own,
not something to bolt on inside the SMS milestone. `SmsProvider.send_message`
raises a clear `ValueError` if given attachments rather than silently
dropping them — an honest, documented gap beats a half-working feature.
Inbound MMS (customer-sent media) works fully, since Twilio hosts that
media and we merely fetch it (no public-URL problem in that direction).

## Method fidelity

SMS ends up the "simplest" provider from a capability-fidelity
perspective, and honestly so: `edit_message`/`delete_message`/
`mark_as_read`/`typing_indicator` are all no-ops — SMS is a decades-old
telecom protocol with no delivery-confirmed-as-read signal a business can
act on, no live-typing concept, and no edit/unsend capability at the
carrier level. This isn't a shortcut; it's what the medium actually
supports.

## Schema impact

None. `channel_type="sms"` is a new registry value; identity resolution
for SMS uses the exact same generic `customer_channel_identities` path
(M16) every provider-pushed channel without an existing `Customer` column
already uses.

## Verification performed

21 new tests added (278 → 299 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_twilio_gateway.py` (8 tests) — send via the REST API,
  inbound parsing (text-only, MMS media download), the Twilio HMAC-SHA1/
  base64 signature scheme (valid, invalid, missing-auth-token-fails-closed),
  health check — Twilio's HTTP calls mocked via `httpx.MockTransport`.
- `tests/unit/test_sms_provider.py` (10 tests) — the outer
  `SmsProvider`'s delegation to a fake in-process `SmsGateway` double
  (proving the registry/delegation wiring, not re-testing Twilio-specific
  behavior): unknown-gateway construction failure, send/receive
  delegation, the outbound-MMS `ValueError`, no-op methods, attachment
  round-trip, signature/webhook delegation, health-check reflection.
- `tests/integration/test_sms_webhook.py` (3 tests) — the real HTTP
  layer: a valid Twilio signature (computed against
  `settings.public_base_url` + the actual route path) publishing
  `message.received`, an invalid one rejected, and an unknown gateway
  name surfacing as a 400 at webhook-ingress time (not at
  `ChannelConfig` creation time, since `credentials` stays opaque JSON at
  that layer — consistent with every other provider's credentials).

A real send/receive round-trip against a live Twilio account and phone
number is a manual verification step, the same bar established for every
other provider in this codebase.
