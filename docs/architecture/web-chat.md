# Web Chat Channel (Reference Implementation)

M12 of the roadmap. The first real `ChannelProvider` (M11 built the
architecture with a test-only double; this is where it gets exercised by
a genuine, fully first-party channel). Deliberately chosen as the
reference implementation because it has no external provider API,
webhook handshake, or rate limit to work around — it isolates "does our
own architecture hold together" from "does a third party's API behave."

## Why Web Chat doesn't use the generic webhook route

M11's `POST /webhooks/{channel_config_id}` ingress exists because most
channels (WhatsApp, Telegram, Messenger, Email, SMS) are **provider-push**:
a third party POSTs to us. Web Chat is **bidirectional over one
connection** — a visitor's browser holds a WebSocket open to us — so
there is no inbound HTTP payload to verify a signature on.
`WebChatProvider.verify_signature` always returns `True` and its
`webhook`/`receive_message` methods exist only to satisfy the
`ChannelProvider` contract; the real inbound path is the WebSocket
gateway calling `receive_message` directly on each inbound WS frame, then
publishing `message.received` itself — same event, same bus, different
entry point than an HTTP webhook.

## Session handling: an opaque Redis token, not a JWT

A chat visitor session is not the same thing as an agent's login session
(M6's JWT access/refresh pair): no permissions to embed, no company-wide
RBAC to check, and revocation should be immediate (Redis key delete) not
"wait for a short-lived access token to expire." Reusing the JWT module
would conflate two different trust domains for a shallow reason (both are
"a token"). Instead:

- `infrastructure/cache/chat_session_store.py`'s `ChatSessionStore` mints
  an opaque `secrets.token_urlsafe(32)` and stores
  `{customer_id, channel_config_id, company_id}` as a Redis key with a
  sliding TTL — the exact pattern `infrastructure/cache/refresh_tokens.py`
  (M6) already established for a different kind of revocable token.
  Redis lookup succeeding **is** the verification; there's no signature to
  decode.
- `POST /web-chat/{channel_config_id}/sessions` (public, rate-limited via
  the existing `rate_limit_dependency`) creates a `Customer` row on first
  visit (matching Intercom/Zendesk's "anonymous visitors are lightweight
  customer records that get identified later" behavior — no separate
  "Visitor" model; M8's `Customer.email` is already nullable and
  `custom_fields` already absorbs anything channel-specific) and returns a
  session token; a client presenting an existing valid token gets the same
  session back rather than a new `Customer`.

## The chat widget contract

The WebSocket gateway (`WS /ws/webchat/{channel_config_id}?token=...`)
speaks a small JSON frame protocol (`api/schemas/web_chat.py`):

- Inbound (`WidgetMessageIn`): `{"body": str, "reply_to_external_message_id": str | None}`.
- Outbound (`WidgetMessageOut`): `{"type": "message" | "typing", "body": ..., "is_typing": ...}`.

The gateway validates the token against `ChatSessionStore` before
accepting the connection (closes with code 4401 if missing/invalid/
mismatched `channel_config_id`), then loops: each inbound frame goes
through `WebChatProvider.receive_message` → a `message.received`
`DomainEvent` on the M10 bus, same as every other channel.

## Horizontal scaling: Redis pub/sub fanout, not a connection registry

A visitor's WebSocket is a long-lived connection pinned to whichever app
server instance accepted it. When something needs to reach that visitor
(an agent's reply, once M13/M14 build that path), the app server that
happens to handle the reply is very likely a *different* process. Rather
than building a distributed connection registry (which server holds which
socket), the gateway subscribes to a **Redis pub/sub channel keyed by the
session token** on connect, and forwards anything published there straight
to the local socket; `WebChatProvider.send_message`/`typing_indicator`
just publish to that same channel via `RealtimeSignalPublisher` (M10's
ephemeral tier — a typing indicator or a chat message push is exactly the
non-durable, low-latency signal that tier exists for). Any server can
publish; only the server that actually holds the matching subscription
delivers it. Adding more `backend` replicas requires zero changes here —
Redis pub/sub already fans out to every subscriber.

`infrastructure/events/realtime_publisher.py` gained a `subscribe()`
async-context-manager companion to the M10 `RealtimePublisher.publish()`,
for exactly this purpose.

## Attachments: a shared MinIO client, built here, reused by M13

`ChannelProvider.upload_attachment`/`download_attachment` need a working
object store now, even though `messages`/`message_attachments` tables
don't exist until M13. `infrastructure/storage/s3_client.py` (a thin
`minio.Minio` factory from the already-declared `s3_*` settings) and
`infrastructure/storage/attachment_store.py` (`AttachmentStore` — an
async wrapper via `anyio.to_thread.run_sync`, since the `minio` package is
synchronous) are built as shared infra here; M13 reuses `AttachmentStore`
directly rather than inventing a second object-storage abstraction.

## `WebChatProvider` — the 11 methods

| Method | Behavior |
|---|---|
| `send_message` | publish to the session's Redis channel; the gateway forwards it down the socket |
| `receive_message` | parse one `WidgetMessageIn` JSON frame → `InboundMessage` |
| `edit_message` / `delete_message` | publish an edit/delete signal to the session channel |
| `mark_as_read` | publish a read-receipt signal |
| `typing_indicator` | publish via `RealtimeSignalPublisher` — no durability needed |
| `upload_attachment` / `download_attachment` | delegate to `AttachmentStore` |
| `webhook` / `verify_signature` | present only to satisfy the ABC — see above; the gateway never calls `webhook()` |
| `health_check` | pings the MinIO bucket |

Registered as `ChannelRegistry.register("web_chat")`.

## Verification performed

16 new tests: `WebChatProvider` unit tests (send/receive/typing/upload+
download round-trip/verify_signature/health_check, using fakes for both
`RealtimeSignalPublisher` and `AttachmentStorage` — a real MinIO round-trip
isn't meaningfully unit-testable and is verified manually against the
running `docker compose` stack, the same bar established for RabbitMQ),
`ChatSessionStore` round-trip and TTL-extension tests (fakeredis), the
session-creation endpoint (new visitor creates a `Customer`; a returning
token reuses one; rejects a non-`web_chat` config; 404s on an unknown
config), and the WebSocket gateway's business logic exercised by calling
`webchat_gateway` directly with a hand-built fake `WebSocket` — publishing
`message.received` for a valid session, and closing with 4401/4404 for a
missing token and an inactive channel respectively. That direct-call
approach (rather than a real ASGI WebSocket connection via
`TestClient.websocket_connect`) is deliberate: Starlette's WebSocket test
client runs the app in its own background-thread event-loop portal, and
that portal touching the same in-memory-SQLite connection this suite's
async fixtures use corrupts it — calling the plain coroutine directly
keeps everything on one event loop while still exercising the exact same
logic. 123 tests total passing across the whole suite; `ruff check`/
`mypy` clean.
