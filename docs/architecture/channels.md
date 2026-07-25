# Channel Provider Plugin Architecture

M11 of the roadmap (was M10 before the M10/event-bus insertion — see
`docs/ROADMAP.md`). Builds the channel abstraction, registry, adapter
contract, and per-company configuration model the roadmap calls for —
deliberately with **zero real providers**: WhatsApp/Telegram/Messenger/
Instagram/SMS/Email are later, separate milestones (M15-M18), and Web Chat
(the reference implementation) is M12. This milestone proves the
architecture works using only a test-double provider.

## Goal

Adding channel provider #50, ten years from now, must be one new class plus
one registry line — **zero changes to the conversation engine, the webhook
ingress route, or any other provider.** Every design decision below exists
to make that true.

## Channel-agnostic contract

`domain/channels.py` — plain dataclasses, no framework/ORM dependency, so
providers and the conversation engine can both be unit-tested without a
database or an HTTP server:

- `OutboundMessage` — what the conversation engine hands a provider to send.
- `InboundMessage` — what a provider hands back after parsing a webhook:
  `external_message_id`, `external_customer_id`, `body`, `attachments`,
  `reply_to_external_message_id`, `sent_at`, `raw_metadata`.
- `OutboundAttachment` / `AttachmentRef` — a to-be-uploaded attachment vs. a
  provider-side handle to an already-uploaded one.
- `SendResult`, `HealthStatus` — return shapes for `send_message`/
  `health_check`.
- `WebhookRequest` — raw `headers`/`body: bytes`/`query params`, **not** a
  FastAPI `Request` — keeps providers framework-agnostic and testable
  without spinning up ASGI.

`domain/channel_provider.py` — `ChannelProvider`, an **ABC**, not a
`Protocol`. This is a deliberate divergence from `Repository`
(`domain/repositories/base.py`) and `DomainEventPublisher`
(`domain/events.py`), which are Protocols satisfied structurally with no
central registry. Channel providers need the opposite: **named,
discoverable registration** (a route needs to look up "the WhatsApp
provider" by a string from the database, not by having a Python reference
to a class already in scope) plus shared base behavior across every
provider (retry/backoff helpers, common construction from a `ChannelConfig`).
Inheritance + a registry fits that; structural typing with no registry
doesn't. Every method the roadmap named is an abstract method:

| Method | Purpose |
|---|---|
| `send_message` | push an `OutboundMessage` to the provider |
| `receive_message` | **pure parsing**: one provider-specific payload → `list[InboundMessage]`, independently unit-testable without an HTTP request |
| `edit_message` / `delete_message` | provider-side message mutation, where supported |
| `mark_as_read` | read-receipt push to the provider |
| `typing_indicator` | ephemeral — providers that support it call through to `RealtimePublisher` (see `event-bus.md`) themselves; there's no durability expectation |
| `upload_attachment` / `download_attachment` | move attachment bytes to/from the provider's storage |
| `webhook` | **orchestration entry**: given a verified `WebhookRequest`, parses the full inbound payload (via `receive_message`) and returns whatever ack body the provider's handshake protocol requires |
| `verify_signature` | sync, pure, called by the route **before** `webhook()` as an explicit security gate — not folded into `webhook()` itself, so signature checking is testable and auditable independently of parsing logic |
| `health_check` | provider-side liveness/credential check |

## Registry and factory

`infrastructure/channels/registry.py`:

- `ChannelRegistry` — a process-wide `dict[str, type[ChannelProvider]]`,
  populated via `@ChannelRegistry.register("channel_type")` on each
  concrete provider class. Discovery is one explicit import list (a new
  `infrastructure/channels/providers/__init__.py` importing every concrete
  provider module), mirroring `core/celery_app.py`'s existing `include=[...]`
  task-discovery pattern — explicit over magic, matching this codebase's
  established style.
- `ChannelProviderFactory.build(config: ChannelConfig) -> ChannelProvider`
  — looks up the class by `config.channel_type`, decrypts
  `config.credentials`, constructs the instance.

**Registration is triggered from `factory.py`, not from each entrypoint.**
`@ChannelRegistry.register(...)` only runs once the `providers` package is
actually imported somewhere — for the first several milestones the only
thing that imported it was `api/v1/router.py`, which only the FastAPI web
process loads. Phase 1's `channel_health_check_task` (a Celery-beat task
running in the standalone `celery-worker`/`celery-beat` processes, which
never import `api/v1/router`) exposed this in production: every channel
type resolved to "Unknown channel type" there from day one, silently,
because nothing in that process had ever triggered registration.
`email_imap_poll_task` and `workflow_engine_consumer`'s `ConversationService.
send_reply` path had the identical latent gap. Fixed at the structural
level rather than by adding an import to each affected entrypoint (which
just repeats the same mistake for the next one): `factory.py` — the one
class whose entire job is "look up a registered provider" — imports
`infrastructure.channels.providers` itself at module level. Any code that
imports `ChannelProviderFactory` now gets registration as a side effect,
regardless of which process it runs in.

## Per-company configuration: `ChannelConfig`

`infrastructure/database/models/channel_config.py` — company-scoped,
soft-deletable, standard mixins (`company_id` FK cascade + indexed, like
every other tenant-scoped table):

- `channel_type` is a **plain `varchar`, not a DB enum and not a foreign
  key to a "channel types" table**. `AgentStatus` already uses
  `Enum(..., native_enum=False, length=20)` (a SQLAlchemy-level enum stored
  as a plain string, not a native Postgres `ENUM` type) so that adding a
  new status doesn't require an `ALTER TYPE`; `channel_type` goes one step
  further and isn't validated at the database level *at all* — validity is
  enforced in the application layer against `ChannelRegistry`'s registered
  keys. Adding WhatsApp in M16 means zero migrations touch this column.
- `display_name`, `is_active`.
- `credentials` — JSON, **encrypted at rest**. A new
  `infrastructure/security/crypto.py` provides AES-256-GCM
  encrypt/decrypt, keyed by a new `settings.credentials_encryption_key`
  (same "secret from settings" pattern already used for
  `jwt_secret_key`). `EncryptedJSON` (a SQLAlchemy `TypeDecorator`, the
  same abstraction technique `GUID` already establishes in
  `infrastructure/database/base.py`) makes this transparent to callers —
  application code reads/writes a plain `dict`, encryption happens at the
  bind/result boundary. Swapping the key source for a real secrets
  manager (Vault/KMS) later is a one-function change
  (`get_encryption_key()`), not a schema or call-site change.
- `webhook_secret` — used by a concrete provider's `verify_signature`.
- **No uniqueness constraint on `(company_id, channel_type)`** — a company
  may run multiple instances of one channel type (e.g. two WhatsApp
  Business numbers routed to different departments).

CRUD API (`channels.read`/`channels.manage` permissions, added to
`domain/rbac.py`'s catalog and the Admin/Owner default role sets) follows
the exact repository → service → endpoint → schema shape already
established by `departments.py`/`DepartmentService`/`DepartmentRepository`.

## Webhook ingress: the seam that keeps the conversation engine channel-agnostic

One generic route: `POST /webhooks/{channel_config_id}`.

1. Load the `ChannelConfig` (404 if missing/inactive).
2. `ChannelProviderFactory.build(config)`.
3. `provider.verify_signature(request)` — 401 if false. This runs *before*
   any parsing, so an unverified payload never reaches provider-specific
   parsing code.
4. `provider.webhook(request)` → `list[InboundMessage]` + an ack body.
5. Publish one `message.received` `DomainEvent` per `InboundMessage` onto
   the outbox (see `event-bus.md`) — **this route does not create any
   Conversation/Message row itself.** Those tables don't exist until M13
   (Conversations, Messages, Attachments); when they land, the
   conversation engine will be built as a *consumer* of `message.received`,
   never as a caller of any provider. That's what "the conversation engine
   is completely channel-agnostic" means concretely: it depends on the
   `ChannelProvider` ABC/DTOs and the factory, never on a concrete provider
   package, and it learns about inbound messages exclusively through the
   event bus.

Outbound is the mirror image: a future "send reply" use case (M13) builds
an `OutboundMessage`, resolves the conversation's `ChannelConfig`, gets the
provider via the same factory, calls `send_message()`, persists the
`external_message_id` from the `SendResult`, and publishes `message.sent`.

Provider-specific webhook handshakes (e.g. Meta's `hub.challenge`
GET-verification flow for WhatsApp/Messenger) are a known concern,
deliberately not designed for here — they'll be solved concretely when
that specific provider is built (M16/M17), not speculatively now.

## Message/attachment schema (specified now, built in M13)

Not created as tables in this milestone — Conversations/Messages is its
own roadmap item — but fully specified here so M13 implements this design
rather than inventing one under time pressure:

**`messages`**: `id` (UUID PK) · `external_message_id` (nullable, unique
per `(channel_config_id, external_message_id)` — provider message IDs are
only unique within one provider account, never globally) · `channel_type`
and `company_id` **denormalized directly onto the row** (every existing
table already carries `company_id` directly rather than requiring a join
for tenant-scoped queries; at 100M rows that join-avoidance matters for
both webhook ingestion latency and analytics) · `channel_config_id` (FK) ·
`conversation_id` (FK, cascade, indexed) · `customer_id` (FK, indexed) ·
`direction` (`Enum(..., native_enum=False)`: inbound/outbound — a small,
our-own-code-controlled set, unlike `channel_type`) · `status` (our
internal processing state: pending/sent/failed) · `delivery_status`
(provider-confirmed: pending/delivered/undelivered/not_applicable) ·
`read_status` + `read_at` (unread/read) — three separate columns because
the roadmap calls out status/delivery status/read status as three
distinct concerns, not one combined enum · `reply_to_message_id` (nullable
self-FK, `SET NULL`) · `metadata` (portable `JSON`, not `JSONB` — same
SQLite-test-compatibility reasoning as `Customer.custom_fields`, documented
in `core-crm.md` decision #5) absorbing whatever provider-specific fields
don't warrant a column — the other half of "support future providers
without schema changes," alongside `channel_type` being a plain string ·
`sent_at`/`delivered_at`/`read_at` as separate nullable timestamps
alongside `created_at`/`updated_at`, since provider-reported times lag
ingestion time.

**`message_attachments`**: a real child table (FK to `messages`, cascade),
not a JSON array — attachments need their own lifecycle (MinIO storage
key, content type, size, virus/type validation status, per the roadmap's
M13 line) that a JSON blob can't index or validate against.

**Scaling note for M13**: at ~50-100M rows, native Postgres range
partitioning of `messages` by `created_at` (monthly) is the right move.
Every hot query pattern here (conversation history, company-scoped recent
activity) already includes a natural partition-friendly predicate, so
nothing about this schema blocks adding partitioning later — not done now,
premature at row zero.

## Verification performed

12 new tests (SQLite-backed) in `tests/integration/test_channels.py`,
built around a `FakeChannelProvider` test double registered under a
test-only channel type (`test_fake`): rejecting an unregistered
`channel_type` (400), full `ChannelConfig` CRUD, pagination, soft-delete,
tenant isolation, and unauthenticated-access rejection (same shape as the
`departments` tests); a direct DB-row inspection proving `credentials` are
never stored in plaintext; and four webhook-ingress tests exercising the
complete inbound seam end-to-end — registry lookup → factory construction
→ `verify_signature` → `webhook` → a `message.received` `DomainEvent`
landing in the outbox with the correct `channel_type`/company/payload
fields, plus invalid-signature (401), unknown-config (404), and
inactive-channel (404) rejections. Plus a standalone crypto round-trip
test (`tests/unit/test_crypto.py`, including a non-determinism check —
the same plaintext must encrypt differently each call). 107 tests total
passing across the whole suite; `ruff check`/`mypy` clean. This proves the
full architecture end-to-end with zero real providers implemented, per
the explicit requirement that provider implementations wait until the
architecture itself is signed off.

**Phase 1: Channel Experience (2026-07-25)** — see `docs/ROADMAP.md`'s
Phase 1 entry for the full feature list and the review-driven fixes
(credential redaction, the registration-triggering fix above, etc.).
`tests/unit/test_channel_error_sanitizer.py` specifically covers the
credential-leak fix: both the case a provider's `health_check()` raises
an exception embedding a credential, and the case (every current
provider) where it catches that exception itself and returns the
credential-embedding detail as a normal, non-exception `HealthStatus` —
redacting only the `except` path would have left the second, more common
case wide open. 557 backend / 65 frontend tests passing; verified live
against the production Docker Compose stack including a manual
`check_channel_health` invocation against the rebuilt `celery-worker`
container to confirm the registration fix (was: "Unknown channel type"
for all 18 active channels; now: 17/18 transitioned correctly on first
sweep).
