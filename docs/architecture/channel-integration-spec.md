# Channel Integration Design Specification

**Status: awaiting approval. No channel connection flow may be
implemented or modified until this document is signed off — see
"Approval gate" at the end.**

This document exists to answer, for every supported channel, exactly
these eleven questions: connection method, required fields,
authentication flow, webhook registration flow, token refresh strategy,
connection verification, error handling, reconnection flow, user
experience (wizard steps), security considerations, and multi-tenant
behavior.

This is **not greenfield**. All 7 channels (WhatsApp, Facebook Messenger,
Instagram, Telegram, SMS, Email, Web Chat) already have a working backend
provider and a generic connect/edit/disconnect UI. Section 1 documents
that current state precisely, grounded in the actual source (file:line
references throughout, verified by direct code reading, not inferred from
docstrings). Section 2 is a gap analysis. Section 3 is the proposed target
design for closing those gaps, scoped and prioritized. Nothing in Section
3 is implemented — it is the thing being proposed for approval.

For deeper per-channel implementation detail beyond what's summarized
here, see the existing per-topic docs: `docs/architecture/channels.md`
(shared ABC/registry/factory/encryption), `docs/architecture/
whatsapp-telegram.md`, `docs/architecture/messenger-instagram.md`,
`docs/architecture/sms.md`, `docs/architecture/email-channel.md`. This
document's job is to organize the same ground truth around the eleven
questions above, consistently, across all seven channels at once — a cut
none of those existing docs takes individually.

---

## 1. Current state, per channel

### Shared architecture (applies to every channel below)

- **`ChannelProvider`** — an ABC (`domain/channel_provider.py:31-108`), not
  a `Protocol`, with 11 abstract methods: `send_message`,
  `receive_message`, `edit_message`, `delete_message`, `mark_as_read`,
  `typing_indicator`, `upload_attachment`, `download_attachment`,
  `webhook`, `verify_signature` (sync), `health_check`.
- **Registry + factory** — `ChannelRegistry` (`infrastructure/channels/
  registry.py`) maps `channel_type` string → provider class via explicit
  `@ChannelRegistry.register(...)` decorators. `ChannelProviderFactory.
  build(config)` looks up the class and constructs it with the config's
  (transparently decrypted) `credentials` and `webhook_secret`.
- **`ChannelConfig`** (`infrastructure/database/models/channel_config.py`)
  — company-scoped (`company_id` FK, cascade), `channel_type` (plain
  `varchar`, validated only against the registry at the application layer
  — adding a new channel type needs zero migration), `display_name`,
  `is_active`, `credentials` (`EncryptedJSON`, AES-256-GCM, see below),
  `webhook_secret` (plain-text column), standard timestamp/soft-delete
  mixins. **No uniqueness constraint on `(company_id, channel_type)`** —
  one company can run multiple instances of the same channel type.
- **Encryption at rest** — `infrastructure/security/crypto.py`, AES-256-GCM,
  key = SHA-256 of `settings.credentials_encryption_key` (enforced
  `min_length=32`), fresh random nonce per encryption (non-deterministic
  ciphertext). `credentials`/`webhook_secret` are **write-only** over the
  API — `ChannelConfigResponse` never echoes them back once saved.
- **CRUD API** (`api/v1/endpoints/channel_configs.py`) —
  `GET`/`POST`/`PATCH`/`DELETE /channel-configs`, gated by
  `channels.read`/`channels.manage`. `credentials` is an opaque
  `dict[str, Any]` at this layer for every channel type — **there is no
  per-channel-type server-side validation of required fields**; a
  malformed/incomplete credentials dict is accepted at create time and
  only fails later, the first time a provider tries to use a missing key.
  `PATCH` replaces `credentials` wholesale, not a merge.
- **Webhook ingress** — one generic route, `GET`/`POST /webhooks/
  {channel_config_id}` (`api/v1/endpoints/webhooks.py`), not split per
  channel family. `GET` handles the Meta `hub.challenge` handshake;
  `POST` is the real inbound path. Both resolve the config
  **cross-tenant** (external callers aren't authenticated as any
  company), verify the provider's signature scheme *before* parsing, call
  `provider.webhook()`, then publish one `message.received` domain event
  per inbound message onto the transactional outbox. **No rate limiting**
  on this route.
- **Frontend wizard** (`frontend/src/features/channels/`) —
  `ChannelCreateDialog.tsx`/`ChannelEditDialog.tsx`. **WhatsApp is the
  only channel with a guided, per-field form** (phone number ID, access
  token, verify token, each with contextual helper text). **Every other
  channel type gets one generic multiline "Credentials (JSON)" textarea**
  the operator must hand-author, with no per-channel hinting beyond a
  `'{}'` placeholder. A "Webhook secret" field is present for all
  channels, always operator-typed — **nothing is ever auto-generated
  server-side**. The post-create success screen shows a copyable webhook
  URL for every channel, plus a copyable verify token **only for
  WhatsApp**. Editing later (any channel) reverts to the generic JSON
  textarea even for WhatsApp — there's no guided re-entry form once a
  channel exists.
- **Error handling, honestly** — there is **no retry/backoff/circuit-
  breaker logic anywhere** in the channel infrastructure. Every provider's
  outbound HTTP call is a bare `raise_for_status()`. Send failures
  (`httpx.HTTPError` from an expired token, a rate limit, a provider
  outage) are **not** `DomainError` subclasses and are not caught
  anywhere — they propagate to a bare 500, and because the `Message` row
  is only persisted *after* a successful send, a failed send leaves **no
  record at all**: no "failed" status, nothing for the agent to retry or
  even see beyond a generic error toast.
- **Connection verification** — every provider implements `health_check()`,
  but **it is never called from any API endpoint**. There is no
  "Test connection" button anywhere in the product today; it is
  currently dead code from the API's perspective.
- **Token refresh** — **not implemented for any channel.** Every
  credential (Meta access tokens, Telegram bot tokens, Twilio auth token,
  SMTP/IMAP passwords) is treated as long-lived and manually rotated via
  `PATCH`.
- **Webhook registration with the provider** — **fully manual for every
  channel.** No code anywhere calls Meta's subscribe-app API, Telegram's
  `setWebhook`, or Twilio's number-configuration API. The operator copies
  the webhook URL (and verify token, for WhatsApp) from the success
  screen and pastes it into the provider's own dashboard/console
  themselves.

### Per-channel summary table

| Channel | Connection method | Required credential fields | Outbound auth | Webhook handshake | Token refresh | Guided frontend form? |
|---|---|---|---|---|---|---|
| WhatsApp | Long-lived API token | `phone_number_id`, `access_token`, `verify_token` | `Authorization: Bearer` | `GET hub.challenge` + HMAC-SHA256 body | None | **Yes** |
| Messenger | Long-lived API token | `access_token`, `page_id`, `verify_token` | token as query param | `GET hub.challenge` + HMAC-SHA256 body | None | No (generic JSON) |
| Instagram | Long-lived API token | `access_token`, `instagram_id`, `verify_token` | token as query param | `GET hub.challenge` + HMAC-SHA256 body | None | No (generic JSON) |
| Telegram | Bot token | `bot_token` | token embedded in URL path | secret-token header, exact match (no HMAC) | None | No (generic JSON) |
| SMS (Twilio) | API key/secret pair | `gateway`, `account_sid`, `auth_token`, `from_number` | HTTP Basic Auth | HMAC-SHA1 over URL+params, base64 | None | No (generic JSON) |
| Email | Username/password | `smtp_*` (host/port/user/pass/tls), optional `imap_*` | SMTP AUTH / IMAP LOGIN | generic HMAC-SHA256 over body, **or** 60s IMAP poll | N/A (no OAuth) | No (generic JSON) |
| Web Chat | None (first-party) | none used | N/A | N/A — never uses `/webhooks`, uses a WebSocket instead | N/A | No (generic JSON) |

Per-channel notes worth calling out explicitly:

- **SMS** is a two-level plugin system: the `sms` channel type delegates
  to whichever `SmsGateway` its `credentials["gateway"]` names. Only
  **Twilio** is implemented today; Vonage/MessageBird/Plivo/SNS are
  documented as future extension points, not built.
- **Email** is the only channel with two inbound paths (a webhook route
  *and* a 60-second Celery-beat IMAP poll) and the only one using plain
  username/password auth with no signature scheme tied to a provider's
  crypto (its webhook signature is this app's own generic HMAC, not an
  ESP-specific one).
- **Web Chat** is the reference first-party channel: no external
  credentials, session-token-gated WebSocket instead of a webhook,
  `verify_signature` always returns `True` because the real gate is the
  WebSocket handshake itself.
- **Messenger and Instagram** share one internal base class
  (`MetaMessagingProvider`) and are behaviorally identical except for the
  credential key name (`page_id` vs `instagram_id`) and registry string.

---

## 2. Gap analysis

Ranked by what actually blocks a real customer from safely and
confidently connecting a channel today, most impactful first:

1. **No error visibility on send failure.** An agent's reply can
   silently vanish (no persisted row, no "failed" indicator) if the
   channel token expired or the provider rate-limited the request. This
   is the highest-impact gap — it's a support-experience and trust
   problem, not just a rough edge.
2. **No "Test connection" button**, despite every provider already
   having a working `health_check()`. An operator connecting WhatsApp
   today has no way to confirm the token is valid before going live —
   they find out when a real customer message fails to get a reply.
3. **No guided form for 6 of 7 channels.** Requiring an operator to
   hand-author JSON for Telegram/Messenger/Instagram/SMS/Email/Web Chat
   is a real adoption barrier and a real support-ticket generator (a
   single typo'd key silently produces an empty-string default deep
   inside a provider, not a validation error).
4. **No server-side credential-shape validation.** A `POST
   /channel-configs` with a malformed `credentials` dict for any channel
   type succeeds today; the operator only discovers the mistake later,
   indirectly, when a message fails to send/receive.
5. **No webhook auto-registration.** Every channel requires the operator
   to leave this app and manually configure Meta's/Telegram's/Twilio's
   own dashboard. This is a real onboarding friction point, though it's
   also the lowest-risk gap to leave manual (see Section 3).
6. **No token refresh / expiry awareness.** Meta's long-lived Page/System
   User tokens *can* expire (60 days for user tokens, though System User
   tokens used correctly don't); there's no code path that would notice
   or alert on this before a send fails.
7. **No auto-generated webhook secrets/verify tokens.** Operators
   currently invent these themselves, which in practice invites weak,
   reused, or forgotten values.
8. **No real OAuth flow for any Meta channel.** Meta's own recommended
   integration path for WhatsApp/Messenger/Instagram is Facebook Login
   for Business (OAuth), not hand-pasted long-lived tokens — the latter
   works but is the less-supported, "System User" administrative path
   Meta itself increasingly discourages for multi-tenant SaaS.

---

## 3. Proposed target design (NOT implemented — pending approval)

Organized by effort/risk, since these gaps don't all belong in the same
milestone.

### 3a. Low-risk, high-value, no external dependencies (propose doing first)

**Structured send-failure handling.** Introduce a `ChannelSendError`
`DomainError` subclass. Every provider's `send_message` call site in
`ConversationService.send_reply` wraps the call, catches
`httpx.HTTPError` (and any raw `ValueError` the email/SMS providers
currently raise for missing fields), and re-raises as
`ChannelSendError(detail=..., retryable=bool)`. Persist the attempted
`Message` row regardless of outcome, with a `status="failed"` and the
error detail visible to the agent, rather than persisting nothing. Maps
to a real, informative HTTP error instead of a bare 500.

**"Test connection" endpoint.** `POST /channel-configs/{id}/test-connection`
(new, `channels.manage`-gated), builds the provider via the existing
factory, calls the existing `health_check()`, returns
`{healthy: bool, detail: str}`. Wire a "Test connection" button into
`ChannelEditDialog.tsx` next to the existing fields. Zero new external
integration — every provider already has this method; it's purely
plumbing it through to the API and UI.

**Server-side credential-shape validation.** One small Pydantic model per
channel type (`WhatsAppCredentials`, `TelegramCredentials`, etc.),
validated in `ChannelConfigService.create`/`update` against
`channel_type` before persisting — reject with a 422 and field-level
detail instead of silently accepting a malformed blob.

**Guided frontend forms for the remaining 6 channels**, following the
exact pattern WhatsApp's form already establishes (per-field inputs with
contextual helper text, password-masked secrets, a summary success
screen). Concretely: Telegram (`bot_token`), Messenger
(`access_token`/`page_id`), Instagram (`access_token`/`instagram_id`),
SMS (`gateway` selector defaulting to `twilio`, then
`account_sid`/`auth_token`/`from_number`), Email (`smtp_*` fields plus an
optional, collapsible `imap_*` section), Web Chat (no credential fields
at all — just a "Create" button and the embed/webhook info screen).

**Auto-generated webhook secret and verify token.** Generate both
server-side (`secrets.token_urlsafe(32)`-equivalent) at `POST
/channel-configs` time when the operator leaves them blank, and surface
them on the success screen exactly like WhatsApp's verify token is shown
today — removes the "operator invents a weak secret" failure mode by
default while still allowing an operator to supply their own if a
provider requires a specific format.

### 3b. Medium-risk, needs a small design decision but no external app registration

**Rate limiting on `/webhooks/{channel_config_id}`.** Add the same
`rate_limit_dependency` pattern already used on the Web Chat session
endpoint, scoped per `channel_config_id` rather than per-IP (external
providers call from their own infrastructure, not a stable client IP).

**Token-expiry awareness for Meta channels.** Meta's Graph API returns a
`GET /debug_token` introspection endpoint that reports `expires_at`, a
capability none of the Meta providers currently call.  Proposal: extend
`health_check()` for the three Meta-family providers to also report
`expires_at` (surfaced by the "Test connection" button above), and add a
Celery-beat sweep (mirroring the existing 60s email-poll pattern) that
flags channels within N days of expiry via the existing Notifications
system — a warning, not an automated refresh, since Meta's long-lived
token model has no refresh-token grant to call.

### 3c. Higher-risk / needs a business decision before any code

**Real OAuth (Facebook Login for Business) for WhatsApp/Messenger/
Instagram**, replacing (or offering as an alternative to) hand-pasted
long-lived tokens. This requires: a registered Meta App with the
relevant permissions (`whatsapp_business_management`,
`pages_messaging`, `instagram_manage_messages`, etc.), Meta App Review
(can take weeks and requires screencast/use-case justification per
permission), and a decision on whether Blink Engage operates one shared
Meta App across all tenants (simpler, but ties every customer's channel
health to one app's standing with Meta) or requires each customer to
register their own Meta App (more resilient, much worse onboarding).
**This is a product/business decision, not an engineering one** — flagged
here explicitly rather than assumed. Do not scope this into the same
milestone as 3a/3b.

**Webhook auto-registration** (calling Meta's subscribe-app API,
Telegram's `setWebhook`, Twilio's incoming-number webhook config) is
technically straightforward once OAuth exists (it needs a valid access
token with the right permission scope to call these endpoints on the
provider's behalf) but is low-value to build *before* OAuth, since the
manual copy-paste flow this replaces is a one-time, low-frequency
operator action, not a recurring pain point. Propose deferring until
3c's OAuth decision is made either way.

**Additional SMS gateways** (Vonage, MessageBird, Plivo, SNS) — pure
engineering effort, no OAuth complexity, but no customer demand signal
exists yet to prioritize over 3a/3b. Propose leaving as documented
future extension points until a real customer asks.

### Explicitly out of scope for this spec

- Adding new channel types beyond the existing 7 (plugin architecture
  already supports it; not requested).
- Changing the `ChannelProvider` ABC's method signatures — every
  proposal above fits within the existing contract.
- Multi-tenant behavior changes — the existing per-company-scoped,
  multiple-instances-per-type model is sound and not proposed to change.

---

## Phase 1 implementation notes: accepted gaps

Phase 1 ("Channel Experience" — guided setup wizard, connection
validation, Test Connection, health monitoring, error diagnostics,
reconnect flow, connection logs) is implemented for WhatsApp Cloud API,
Web Chat, Telegram and Email per the priority order above. An adversarial
review of that implementation surfaced two lower-severity gaps that were
deliberately **not** fixed as part of Phase 1, to keep that fix pass
proportionate to its own scope rather than opportunistically expanding it
into unrelated hardening work. Both are tracked here so they aren't lost:

**No SSRF host/IP restriction on credential fields.** Several credential
fields accept an arbitrary operator-supplied host (`smtp_host`,
`imap_host`, and any custom API base URL fields), and Test Connection
makes the server originate a real outbound connection to whatever host is
supplied — including internal/private IP ranges. This is rate-limited
(`enforce_channel_test_connection_rate_limit`) and audited (every
ephemeral test-connection call publishes a `channel_config.
test_connection_ephemeral` domain event), which bounds abuse, but does
not prevent a `channels.manage` principal from using Test Connection as an
internal network probe/oracle. This is a pre-existing risk category
broader than Test Connection alone — any future feature that lets an
operator supply a URL the server then fetches has the same exposure — so
it should be addressed as a general internal-network-egress policy (e.g. a
shared `assert_not_internal_host()` helper applied at every such
boundary), not as a one-off patch scoped to channel credentials. Tracked
as a follow-up; not scheduled against a specific milestone yet.

**Credential validation errors return `400` with a flat string detail,
not `422` with field-level detail.** `InvalidChannelCredentialsError` (and
the rest of this codebase's `DomainError` → HTTP mapping) intentionally
uses `400` + a single human-readable message for domain-level validation
failures, reserving FastAPI/Pydantic's built-in `422` +
field-level-errors shape for request *schema* validation only. This is
internally consistent with how every other domain validation error in
this codebase is already surfaced, so restructuring it just for channel
credentials would introduce an inconsistency rather than remove one.
Revisiting this would mean deciding the convention for the whole
`DomainError` hierarchy, not just channels — out of scope for a targeted
Phase 1 fix pass.

---

## Provider & Service Status page (added 2026-07-27): a view, not a new backend concept

The roadmap asked for a dedicated "Provider and service Status" page —
one place to see WhatsApp/Instagram/Telegram/Messenger/Email/SMS/Web
Chat's connectivity at a glance, extensible to future providers. Phase 1
above had already built everything this needs at the data layer:
`ChannelConfig.last_health_status`/`last_health_checked_at`/
`last_health_detail` (kept fresh by both the "Test Connection" action and
`infrastructure/tasks/channel_health_check_task.py`'s 5-minute Celery-beat
sweep), already returned in full by the existing, paginated
`GET /channel-configs`. The frontend already has `useAllChannelsQuery()`
(an unpaginated fetch, `frontend/src/features/channels/api.ts`, used
today by the Onboarding Wizard's Channels step) fetching exactly that.

So `frontend/src/features/status/StatusPage.tsx` is a **pure frontend
aggregation view** — zero backend changes. It groups the same
`GET /channel-configs` response by `channel_type` (using
`CHANNEL_TYPES`, `features/channels/types.ts` — already the single
source of truth for every channel-type label everywhere else in the
app, so "extensible to future providers" falls out for free: a new
provider only needs an entry there, not a new page-level query),
computing one aggregate status per type client-side:

- **Not configured** — no `ChannelConfig` row of that type at all
  (still gets its own card, so an operator sees what they haven't
  connected yet, not just what they have).
- **Inactive** — every config of that type has `is_active=false`.
- **Degraded** — any *active* config's `last_health_status` is
  `"unhealthy"`.
- **Not tested yet** — active configs exist, none have been checked.
- **Operational** — at least one active config is healthy and none are
  unhealthy.

Each channel type's card lists its individual configs with the same
`ChannelHealthBadge` the Channels management page already renders, and
reuses `TestConnectionButton`/`useTestConnectionMutation()` unchanged
for a per-channel "test now" action. A page-level "Check all now"
button (gated by `channels.manage`, same as every other write-adjacent
action here) fires `testConnectionMutation.mutateAsync()` for every
configured channel via `Promise.allSettled` — an on-demand alternative
to waiting for the next 5-minute beat tick, not a second scheduled job.

New route `/status` (`channels.read`-gated, same permission as
Channels), new sidebar entry — both siblings of the existing Channels
page, not a replacement for it.

5 new tests (`StatusPage.test.tsx`): aggregate status per type across
degraded/not-tested/inactive/operational/not-configured, an idle-type's
"no channel connected" message, individual + bulk "test now" actions
calling through to the real test-connection endpoint, both hidden
without `channels.manage`, and no accessibility violations. Verified
live against the real running `docker compose` stack: created a real
Web Chat channel, confirmed `GET /channel-configs` returns exactly the
fields the page consumes, and confirmed `POST
/channel-configs/{id}/test-connection` (the same call the page's
"Test now"/"Check all now" actions make) genuinely pings MinIO and
updates `last_health_status`/`last_health_checked_at`.

## "Whose fault is it?" fault classification (added 2026-07-28)

Every provider's `health_check()` already made a genuine live outbound
call to the actual upstream service (Meta's Graph API for
WhatsApp/Messenger/Instagram, Telegram's Bot API, a real SMTP/IMAP
connection for Email, Twilio's REST API for SMS — the one exception,
Web Chat, has no third-party upstream at all and checks BlinkEngage's
own MinIO instead). What the Status page couldn't say was *whose*
problem an unhealthy result was: a flat red "Unhealthy" chip looks
identical whether Meta's servers are down or an operator fat-fingered
their access token.

`domain.channels.HealthCheckOrigin` (`"provider"` | `"configuration"` |
`"network"` | `"internal"`) is a new field on `HealthStatus`, set one of
two ways:

- **Classified centrally** — `infrastructure.channels.error_sanitizer
  .classify_health_check_failure(exc)` reads an `httpx.HTTPStatusError`'s
  actual status code: 401/403/404 means the provider's own server
  responded and is rejecting *our* credentials (`"configuration"`);
  any other status (5xx, an unexpected 429) means the provider's own
  infrastructure is having a problem (`"provider"`). Any other
  `httpx.RequestError` (connection refused, DNS failure, timeout) means
  no response was ever received at all — indistinguishable from "their
  servers are unreachable" (`"network"`). `safe_health_check` applies
  this automatically to both the exception path and a provider's own
  caught-and-returned `HealthStatus`, so every current
  httpx-based provider (WhatsApp/Messenger/Instagram/Telegram/SMS)
  gets classification without individually re-implementing it — see
  each provider's `health_check()`, which calls
  `classify_health_check_failure` explicitly on its own caught
  exception, plus Telegram's `ok: false` special case (a 200 response
  that's still an auth rejection, classified as `"configuration"`
  directly).
- **Classified by the provider itself** — `EmailProvider` doesn't route
  through httpx at all: `aiosmtplib.SMTPAuthenticationError`/
  `SMTPHeloError` and `imaplib.IMAP4.error` (an auth rejection) map to
  `"configuration"`; any other exception (a real connection failure)
  maps to `"network"`. `WebChatProvider` always reports `"internal"` on
  failure, since its check is BlinkEngage's own MinIO, never a
  third-party provider.

Persisted as `ChannelConfig.last_health_origin` (migration
`9c1d2e3f4a5b`, nullable — null for a healthy check or a status recorded
before this column existed) alongside the existing
`last_health_status`/`last_health_detail`, written by both `test_connection`
(`ChannelConfigService`) and the periodic sweep
(`channel_health_check_task.py`), and returned on `ChannelConfigResponse`
and `TestConnectionResponse` alike.

`StatusPage.tsx` now renders an `Alert` under a degraded channel type's
header naming whose fault it is (`dominantUnhealthyOrigin` — when
multiple active configs of one type disagree, e.g. two WhatsApp numbers
sharing one revoked token, `"configuration"` wins as the most actionable
reading, mirroring `EmailProvider`'s own SMTP-vs-IMAP tie-break). A
`"provider"`/`"network"` origin reads as `severity="error"` ("not a
BlinkEngage issue"); `"configuration"`/`"internal"` read as
`severity="warning"` (ours to fix). `ChannelHealthBadge`'s tooltip gets
the same origin line, ahead of the raw detail text — the classification
says *whose* problem it is, the detail still says *what* happened.

## Approval gate

Per instruction, no channel connection flow implementation or
modification proceeds until this document is reviewed and approved.
Suggested approval unit: **Section 3a as one milestone** (self-contained,
no external dependencies, directly closes gaps 1-4 and 7 from Section 2)
— 3b and 3c are separable decisions that can be approved (or declined)
independently and later.
