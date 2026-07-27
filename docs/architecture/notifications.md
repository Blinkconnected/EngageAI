# Notifications & Real-Time Layer

M21 of the roadmap. Two halves: a durable per-user notification inbox
(with email dispatch via Celery), and an agent-facing WebSocket gateway
providing presence, live notification delivery, and — closing a real gap
left open since M11 — agent-side typing indicators actually reaching the
customer.

**Sprint 2 Item 5 (2026-07-25)** generalized this from "a few
conversation-specific triggers" into a genuine platform capability:
any module can add its own notification trigger by registering one
class (see "Generic extensibility" below), duplicate notifications are
now actively prevented rather than merely undocumented, users get
per-type/per-channel delivery preferences (email/browser/sound), every
open tab/device stays in sync on read-state changes, and the frontend
gained a full Notification Center (history + preferences) alongside the
existing header dropdown. See that section's dated entries throughout
this document, and `docs/ROADMAP.md`'s own entry, for what changed and
why.

## Closing a dormant gap: `ChannelProvider.typing_indicator`

Every channel provider built since M11/M12 has implemented
`typing_indicator()` — `WebChatProvider` publishes an ephemeral signal,
`TelegramProvider`/`MessengerProvider`/`InstagramProvider` call real
sender-action APIs. Nothing had ever *called* it: there was no code path
from "an agent is typing a reply" to any provider. This milestone's
roadmap line ("WebSocket... typing") is exactly that path.
`ConversationService.send_typing_indicator` resolves a conversation's
`ChannelConfig`/provider (the same resolution `send_reply` already does)
and calls `provider.typing_indicator()` — best-effort, swallowing any
provider error, since a live-typing signal is never worth failing a
WebSocket connection over. The agent WebSocket gateway is the only
caller today, but the method was always meant to be called from
wherever "an agent started typing" is known.

## The agent WebSocket gateway (`/ws/agent`)

Distinct from the Web Chat WebSocket (M12, customer-facing, keyed by an
anonymous session token): this one authenticates with the same JWT
access token every REST call uses, passed as `?token=` (browsers can't
set arbitrary headers during a WebSocket handshake) — validated with the
same `decode_token`/`TokenType.ACCESS` every HTTP request already uses,
not a new auth mechanism.

Four things happen over one connection:

1. **Presence** — connecting flips `Agent.status` from `OFFLINE` to
   `ONLINE`, but never overrides an explicit `AWAY` (an agent's deliberate
   choice). Disconnecting always sets `OFFLINE` — the gateway can't tell
   "closed the tab" from "went to lunch," and a disconnected agent
   genuinely can't receive live work either way.
2. **Notifications** — the connection subscribes to the recipient's
   personal realtime channel (`user:{id}:notifications`) and forwards
   whatever `NotificationService.create` publishes there, live. This is
   the ephemeral-signal tier (`RealtimeSignalPublisher`, Redis pub/sub, no
   durability) — the durable in-app `Notification` row is the source of
   truth regardless of whether anyone's connected to see it live.
3. **Live conversation updates** — see the dedicated section below.
4. **Typing** — the only inbound frame type
   (`{"type": "typing", "conversation_id", "is_typing"}`), forwarded to
   `ConversationService.send_typing_indicator`.

Tested the same way M12's Web Chat gateway is: calling the gateway
coroutine directly with a hand-built fake WebSocket, not through a real
ASGI WebSocket connection (Starlette's `TestClient.websocket_connect`
runs in its own background-thread event-loop portal, which corrupts the
shared in-memory-SQLite connection this suite's async fixtures use).

## Live conversation updates (added 2026-07-27)

**The bug this closes**: before this, a customer's new message on an
already-open conversation never appeared until the agent refreshed the
page or sent their own reply (which happened to trigger a cache
invalidation as a side effect). `message.persisted` (the durable event)
only ever reached `MessagePersistedRule` → a bell notification on the
*assigned* agent's personal channel — nothing refreshed the conversation
transcript itself, and nothing reached anyone without that one specific
notification type enabled, or anyone who wasn't the assigned agent (a
supervisor or teammate with the same conversation open).

**The fix, deliberately not a per-conversation subscription protocol**:
every agent's `/ws/agent` connection now *also* subscribes to a single
company-wide channel — `realtime_channels.company_realtime_channel_name
(company_id)` — alongside their existing personal one. A dynamic
subscribe/unsubscribe-per-open-conversation protocol (the more
"textbook" design) was considered and rejected: it would need the
gateway to track a mutable set of subscribed channels per connection and
the frontend to announce "I'm now viewing conversation X," for a benefit
(narrower fan-out) that doesn't matter at this codebase's scale — a
client simply filters incoming frames by their own `conversation_id`
instead. Two publishers:

- `conversation_ingest_consumer.handle_message_received` — publishes
  `{"type": "message_received", "conversation_id", "message_id",
  "direction": "inbound", "body"}` right after persisting an inbound
  customer message (alongside the existing durable `message.persisted`
  event — this is the ephemeral, no-durability-guarantee sibling, not a
  replacement).
- `ConversationService.send_reply` — publishes the same shape with
  `"direction": "outbound"` after a successful send, so a second agent
  (or a second tab) watching the same conversation sees an agent's own
  reply live too, not just the sender's own optimistic UI update.

**Frontend**: `RealtimeProvider.tsx` invalidates
`['conversations', conversationId, 'messages']` and the Inbox's list
query on a `message_received` frame whose `conversation_id` is present —
no explicit "which conversations am I watching" bookkeeping needed,
since an invalidated-but-unmounted query is simply a no-op. The existing
15-second poll on the messages query and 10/30-second poll on the Inbox
list remain as a fallback (same "poll is the durable floor, push is the
convenience" relationship the notification bell already has with
`GET /notifications`), not removed.

**Customer typing (web_chat only)**: the widget's inbound frame
(`WidgetMessageIn` — see `docs/architecture/web-chat.md`'s chat widget
contract) gained a `type: "typing"` variant alongside the existing
message-send. `webchat_gateway` resolves the frame to a conversation
(via the same `channel_config_id`+`external_thread_id` lookup ingestion
uses) and publishes `{"type": "customer_typing", "conversation_id",
"is_typing"}` to the same company-wide channel — silently skipped if no
conversation exists yet (a visitor typing before ever sending their
first message has nothing to associate it with). `RealtimeProvider`
exposes this as `isCustomerTyping(conversationId)`, consumed by
`MessageThread` to render a live "Customer is typing…" line, with an
8-second self-clearing safety net in case a "stopped typing" frame never
arrives (a dropped connection, a closed tab). This mirrors the existing
agent→customer typing feature's own scope exactly (only web_chat
supports a live typing signal — see that feature's own doc section
above for why the other five channels' provider APIs have no equivalent
inbound event to receive), and, like that feature, ships as fully
working, tested *infrastructure* with no bundled customer-facing widget
UI — this codebase has never shipped one (the "chat widget contract" is
a protocol spec any embeddable widget implements against, not a widget
shipped here).

## The notification inbox

`Notification` (per-user, hard-deletable — a personal inbox is
functional, not a compliance record, unlike `AuditLog`). Created two ways:

- **Built-in** (`notification_consumer.py`): binds whatever event types
  are registered in `NotificationRuleRegistry` — unlike the Workflow
  Engine's `#`, since these are first-party lifecycle notifications
  every company gets, not something a company configures. The second
  consumer (after `audit-log-consumer`) with a narrower binding than `#`.
- **Custom** (`create_notification` workflow action): the M19
  `publish_event` escape hatch made concrete for this specific case — a
  company can configure *any* workflow to notify *any* user about
  anything, with zero new backend code. `WorkflowExecutionContext` gained
  a `notifications: NotificationService` field alongside
  `conversation_service` for this.

No new RBAC permission — `GET/POST/DELETE /notifications/*` are gated by
authentication alone (`get_current_auth`, no `require_permission`),
scoped to `auth.user_id`: a user always manages only their own inbox,
which isn't a role-based access question the way managing a queue or a
channel config is. The same is true of the new
`GET/PUT /notifications/preferences` below.

## Generic extensibility: the `NotificationRuleRegistry`

**Sprint 2 Item 5.** Before this, `notification_consumer.py`'s
`handle_event()` was a hardcoded if/elif chain over three event types,
and its `ROUTING_KEYS` list had to be kept in sync with that chain by
hand — exactly the kind of drift-prone duplication this same session
already eliminated once for RBAC (`infrastructure.database.
permission_sync` replacing per-permission backfill migrations). The same
fix, applied here:

- `application/notification_rules/base.py` — `NotificationRule` (an ABC,
  one `resolve(context) -> list[NotificationDraft]` method) and
  `NotificationRuleContext` (event_type, company_id, payload, session).
  Mirrors `WorkflowAction`/`ChannelProvider`: internal orchestration that
  needs a live session, not a pure-domain contract.
- `infrastructure/notifications/rule_registry.py` — `NotificationRuleRegistry`,
  the fourth application of this codebase's "named lookup from a
  database/message-carried string" idiom (after `ChannelRegistry`,
  `WorkflowActionRegistry`, `SmsGatewayRegistry`). `@NotificationRuleRegistry.
  register("some.event_type")` on a class is the entire integration
  surface for a new built-in trigger.
- `application/notification_rules/builtin.py` — the four built-in rules
  today: `ConversationAssignmentChangedRule`, `ConversationTransferredRule`,
  `ConversationSlaBreachedRule`, and the new `MessagePersistedRule` (see
  below). Each loads its conversation via `ConversationRepository.
  get_by_id(company_id=..., conversation_id=...)` — company-scoped, not a
  raw `session.get()` — because nothing upstream actually guarantees a
  domain event's `company_id` and `payload["conversation_id"]` agree (a
  company's own `publish_event` workflow action sets `payload` freely); a
  live adversarial review of this exact change caught that an earlier
  draft used the unscoped lookup, which could leak another company's
  conversation id into a notification's `payload` even though the
  recipient agent lookup was correctly scoped. Fixed before this shipped.
- `notification_consumer.py`'s `ROUTING_KEYS` is now
  `NotificationRuleRegistry.registered_event_types()`, computed at import
  time (after importing `notification_rules.builtin`, which registers the
  four rules as a decorator side effect) — never hand-maintained.
  `handle_event()` is now a thin dispatcher: look up the rule for
  `event_type`, call `resolve()`, hand each returned draft to
  `NotificationService.create()`.

**New built-in trigger: `message.persisted` → "New message received".**
Fires for the conversation's *assigned* agent only (an unassigned
conversation has no per-agent notification target — same convention as
the SLA rule; the Inbox's own filtering is how unassigned work is
surfaced, not a notification), with the message body truncated to 120
characters in the notification's `body` text.

One conversation-related event type is explicitly *not* wired up here,
by design, not oversight: a `@mention` in an internal note/message (no
mention-detection feature exists anywhere in this codebase to produce
the triggering event) — structurally one new `NotificationRule` + one
new `domain.notification_types` catalog entry away whenever that feature
lands.

~~An SLA *warning* before breach — only post-breach detection exists
today.~~ **Added 2026-07-27 by the SLA Builder** — `conversation
.sla_warning` now exists (see `docs/architecture/sla.md`), but it isn't
wired into this generic `NotificationRule` catalog: it's consumed
directly by an `SlaPolicy`'s own `escalation_rules` (an explicit list of
user ids to notify per policy), not broadcast to every agent/supervisor
generically the way `ConversationAssignmentChangedRule` etc. are. A
generic "notify me on any SLA warning" preference is still one new
`NotificationRule` away if ever wanted.

## Duplicate prevention under at-least-once delivery

**Sprint 2 Item 5.** RabbitMQ's competing-consumers model guarantees
at-least-once delivery, not exactly-once — a consumer crash between
creating a `Notification` row and acking the message causes the same
event to be redelivered and reprocessed. `Notification.source_event_id`
(the triggering `EventOutbox` row's id, threaded through every event dict
as `"id"`) plus a `UNIQUE(source_event_id, user_id, notification_type)`
constraint is the idempotency key —
`notification_type` is part of it (not just `source_event_id`+`user_id`)
so a built-in rule and a company's own `create_notification` workflow
action never collide just because both target the same user for the
same event. One narrower case this still doesn't cover, an accepted
limit rather than something this key was designed to solve: two
`create_notification` steps in the same workflow run, both hardcoded to
`notification_type="workflow.notification"`, targeting the same user
from the same event.

**A stateless pre-check SELECT is a fast path only, not the actual
guarantee** — two sessions can both pass it before either commits (a
genuine concurrent-transaction race, not just sequential redelivery: two
consumer processes handling redelivered copies of the same event, or a
built-in rule and a workflow action racing to notify the same user).
`NotificationRepository.add_or_get_existing()` is what makes that race
safe: it attempts the insert inside a `SAVEPOINT` (`session.begin_nested()`),
and on the unique-violation this constraint is specifically there to
raise, falls back to fetching the row that won instead of letting the
`IntegrityError` propagate uncaught. That distinction matters a lot: an
adversarial review of the first version of this change confirmed that
an *uncaught* `IntegrityError` here would crash the whole consumer
process (`session_scope`'s `except: rollback; raise` re-raises;
`aio_pika`'s `message.process()` nacks-with-requeue on exception but
never suppresses it) — reintroducing, in a new place, the exact
crash-loop bug `audit_log_consumer.py` already hit live once (see its
own `except IntegrityError` block) and was supposed to have taught this
codebase to avoid. The `SAVEPOINT` also matters for the fan-out case
(a department transfer notifying several agents in one `handle_event`
call): a lost race for one recipient must only roll back that one
insert, never discard notifications already flushed for the others in
the same transaction.

Verified live, not just in the test suite: the exact redelivery scenario
(the same event processed twice, in two independent sessions/
transactions, not one shared open transaction) against the real
production Docker stack produced exactly one notification and zero
consumer crashes or restarts.

## Per-user delivery preferences

**Sprint 2 Item 5.** `domain/notification_types.py` — a small,
fixed catalog (`NOTIFICATION_TYPES`, `NotificationChannel`) covering only
the built-in rules' notification types (not the open-ended
`workflow.notification` type a company can trigger arbitrarily — there's
no fixed list to render a toggle for those). Three channels:
`email`, `browser`, `sound` — the in-app notification itself (the badge,
the history list) is always delivered and isn't a toggleable channel,
since disabling it would mean the notification never existed at all.

`NotificationPreference` (`infrastructure/database/models/
notification_preference.py`): one row per explicit override
(`user_id`, `notification_type`, `channel`, `enabled`), unique on the
first three. Opt-out, not opt-in — the *absence* of a row means enabled,
matching the same "additive defaults, explicit rows only for deviations"
philosophy the RBAC permission sync established for `role_permissions`.
`NotificationPreferenceService.get_matrix()` always materializes the
*full* type×channel matrix from the domain catalog, defaulting anything
uncustomized to `enabled: true`.

`GET/PUT /notifications/preferences` — `GET` returns the full matrix;
`PUT` upserts one `(notification_type, channel, enabled)` entry at a
time, matching a toggle-based settings UI's natural one-request-per-click
shape. Both auth-only, same reasoning as the rest of this feature.

**Email honors it**: `notification_email_dispatch_task.py`'s sweep now
checks the `email` channel preference before actually sending — if
disabled, the row is still marked `email_dispatched_at` (so it isn't
re-checked forever), just without a real SMTP send.

**Browser/sound honor it too, client-side**: see the frontend section
below for how `RealtimeProvider` reads this same matrix to gate the
live delivery effects.

## Cross-tab/cross-device consistency

**Sprint 2 Item 5.** `NotificationService.mark_read`/`mark_all_read`/
`delete` now also publish a realtime signal — `{"type":
"notifications_changed"}`, deliberately a different `type` than a
brand-new notification's `{"type": "notification", ...}` frame, so a
client can tell "something new arrived" apart from "read state changed
elsewhere" (the latter should refresh the badge/list but never trigger a
sound or browser popup for something that isn't new). Every open
tab/device for a user shares the exact same
`notification_channel_name(user_id)` Redis channel the agent WebSocket
gateway already subscribes to, so marking something read in one tab is
reflected in every other tab/device within the same live-push path a
brand-new notification uses — not left to each tab's independent 30s
poll to eventually converge. Verified live: marking a notification read
via one authenticated session pushed the signal to that same user's
*other*, separately-connected WebSocket session immediately.

## The frontend: Notification Center, browser notifications, and sound

**Sprint 2 Item 5.** `features/notifications/NotificationsPage.tsx`
(routed at `/notifications`, linked from the header bell's "View all
notifications") — two tabs: **History** (`NotificationHistoryPanel`,
full paginated list via the same growing-`page_size` "load more" pattern
`MessageThread.tsx` established, an "Unread only" filter, mark-read on
click, delete, and — new — clicking a notification whose `payload.
conversation_id` is set navigates to that conversation) and
**Preferences** (`NotificationPreferencesPanel`, the type×channel toggle
matrix). `NotificationBell.tsx`'s existing dropdown is unchanged apart
from the same click-to-navigate behavior and a new "View all
notifications" link at the bottom.

**Browser notifications and sound** (`features/notifications/
deliveryEffects.ts`) are new capabilities this app never had before:
- `playNotificationSound()` synthesizes a short two-tone chime via the
  Web Audio API rather than shipping a bundled audio asset — nothing to
  source or license, consistent with this app being fully self-contained.
- `showBrowserNotification(title, body)` wraps the native `Notification`
  API, only firing when permission is already `"granted"`.
- `requestBrowserNotificationPermission()` must be called from a user
  gesture (a Preferences-panel toggle click) — `NotificationPreferencesPanel`
  requests permission the moment a user tries to turn the `browser`
  channel *on* (never on a toggle-off, which needs no permission), and
  refuses to persist `enabled: true` if the browser denies it.

Both effects are deliberately small, individually-mockable functions
(not inlined into the WebSocket handler) so they can be spied on in
tests without a real `AudioContext`/`Notification` in jsdom.
`RealtimeProvider.tsx` calls them on a live `"notification"` frame,
each gated by that notification_type's cached preference — and, for that
gating to actually work in *every* tab (not just one that happened to
visit Settings → Notifications → Preferences), `RealtimeProvider`
now fetches the preferences matrix itself on mount via
`useNotificationPreferencesQuery()`, keeping it warm in the React Query
cache for the whole authenticated session. An adversarial review of the
first version of this change caught that without this, `isChannelEnabled()`'s
`queryClient.getQueryData(...)` read would silently return `undefined`
(fail open to "enabled") in any tab that never opened that settings
panel — defeating an explicit opt-out for the common case, not the edge
case. Fixed before this shipped.

This session also established this codebase's first WebSocket-mocking
pattern for frontend tests (`RealtimeProvider.test.tsx`) — no prior
precedent existed. A minimal hand-built `FakeWebSocket` class stood in
for jsdom's real one via `vi.stubGlobal('WebSocket', FakeWebSocket)`,
matching this codebase's existing preference for small hand-built fakes
over a mocking library wherever one suffices (the backend's own
`_FakeWebSocket` for the agent gateway tests is the same idea).

## Platform email vs. channel email — two SMTP configs, deliberately

`EmailProvider` (M15) sends *customer-facing* mail using a company's own
per-`ChannelConfig` SMTP credentials. Notification emails are a
*platform-level* concern: "you were assigned a conversation" must reach
an agent even for a company that has configured zero email channels.
Conflating the two would mean notifications silently stop working for
any company without a support inbox configured. New `settings.smtp_*`
(host/port/username/password/tls/from-address/from-name) exist
specifically for this — separate from any `ChannelConfig`, read from the
same environment-variable configuration pattern every other setting uses.

## Why a Celery-beat sweep, not a fire-and-forget task enqueue

`notification_email_dispatch_task.py` polls
`Notification WHERE email_dispatched_at IS NULL`, exactly like the M10
outbox relay and the M15 IMAP poll — "claim undispatched rows, mark them,
no separate cursor table." A direct `.delay()`/`apply_async()` enqueue
from `NotificationService.create()` was considered and rejected: no
service anywhere in this codebase enqueues a Celery task directly today —
every asynchronous dispatch so far is either the outbox+relay+consumer
event-bus pattern or a Celery-beat periodic sweep. Introducing a third
dispatch mechanism for one feature would be inconsistent with an
already-established, working pattern for no real benefit. The task's core
logic (`dispatch_pending`) takes an external session — same
`poll_channel_config`-style split as `email_imap_poll_task.py` — so it's
directly unit-testable against the test database, unlike the Celery-task
wrapper itself (which builds its own engine, verified manually against
the real stack like every other Celery-beat task).

## Schema impact

One new table (`notifications`) — `user_id` is `ON DELETE CASCADE` (not
`SET NULL` like `AuditLog.actor_user_id`): a notification inbox is
personal and functional, not a record that must outlive its owner.
`email_dispatched_at` follows the same "null = pending, partial index on
the null case" shape as `EventOutbox.dispatched_at`. No new permissions
(see above).

**Sprint 2 Item 5** added `notifications.source_event_id` (nullable
UUID) + `UNIQUE(source_event_id, user_id, notification_type)`, and a new
`notification_preferences` table (`user_id`, `notification_type`,
`channel`, `enabled`, unique on the first three). One migration-safety
lesson worth documenting in full, since it's this codebase's first time
adding a `UNIQUE` constraint to an already-populated, actively-written
table (every earlier one was defined inline at `CREATE TABLE` time on a
brand-new table):

A plain `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE` takes an
`ACCESS EXCLUSIVE` lock for the full underlying index build — blocking
every read/write against `notifications` for that duration, directly
undermining this codebase's documented zero-downtime rolling-deploy
goal. The fix, caught by adversarial review before this shipped: build
the index with `CREATE UNIQUE INDEX CONCURRENTLY` (via Alembic's
`autocommit_block()`, since `CONCURRENTLY` can't run inside a
transaction) and attach it afterward with
`ALTER TABLE ... ADD CONSTRAINT ... UNIQUE USING INDEX` — the standard
two-step that avoids the exclusive lock.

That fix then **caused** a second, more severe bug, only found by
actually running it against the real multi-container Docker stack
(not caught by any test, since the test suite builds schema via
`Base.metadata.create_all()` and never runs Alembic migrations at all):
`core/migrate.py`'s cross-container startup lock used a *blocking*
`SELECT pg_advisory_lock(...)`, which holds the waiting connection's
implicit single-statement transaction open for its *entire* wait.
`CREATE INDEX CONCURRENTLY` must wait for every other transaction in the
database (not just ones touching its own table) to finish before it can
complete — so with `backend`+`celery-worker`+`celery-beat`+6 consumers
all racing for the same lock at startup (the exact scenario this lock
exists for), the index build could never finish (waiting on the
blocked-forever waiters) while the waiters could never finish waiting
(blocked on the lock the index-building session held) — a genuine
deadlock, reproduced live and confirmed via `pg_stat_activity`
(`wait_event: virtualxid` on the `CREATE INDEX CONCURRENTLY` session).
Fixed by polling `pg_try_advisory_lock` (non-blocking) instead, so a
waiting connection is genuinely idle — no open transaction — between
attempts (`core.migrate.acquire_advisory_lock`/`release_advisory_lock`,
also reused by `core/sync_permissions.py`). Because a container can now
be killed mid-migration and leave `autocommit_block()`'s several
separately-committed phases partially applied (confirmed live: a
container killed between the index build and the version-stamp update
left the column and index in place but not yet the constraint or the
`notification_preferences` table), the migration's `upgrade()` also
checks what already exists at each step (`IF NOT EXISTS` / inspector
existence checks) so re-running it from any partial state converges
correctly — the same property a single-transaction migration gets for
free, but this one deliberately isn't one.

## Verification performed

20 new tests added (355 → 375 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/integration/test_agent_realtime_gateway.py` (4 tests) —
  presence flips online on connect / offline on disconnect, an explicit
  `AWAY` is never overridden by connecting, a typing frame reaches
  `WebChatProvider.typing_indicator` (verified via the exact Redis
  channel the provider publishes to), and a concurrently-created
  notification is forwarded live over the socket.
- `tests/integration/test_notifications_api.py` (8 tests) — list,
  unread-count, mark-read, mark-all-read, delete, authentication,
  per-user scoping, and a 404 for another user's notification.
- `tests/integration/test_notification_consumer.py` (4 tests) —
  assignment-changed and SLA-breach notify the right agent, an SLA
  breach with no assigned agent creates nothing, an unrelated event type
  is a no-op.
- `tests/integration/test_notification_email_dispatch_task.py` (3
  tests) — send-and-mark-dispatched, idempotency across two sweeps
  (second sweep sends nothing), and a failed send leaves the row
  undispatched for retry.
- `tests/integration/test_workflow_engine.py` (+1 test) —
  `create_notification` action notifies the configured target user.

A real WebSocket connection from a browser and a real SMTP round-trip
against a live mailbox are manual verification steps, the same bar
established for every other realtime/email path in this codebase.

**Sprint 2 Item 5 (2026-07-25)**: 23 new backend tests (593 → 616
passing) — `test_notification_rule_registry.py` (4, new: register/get,
conflict-on-double-register, registered types include the builtins),
`test_notification_types.py` (3, new: catalog uniqueness/validity),
`test_notification_consumer.py` (+6: the new `message.persisted` rule
notifying/not-notifying, a genuine cross-transaction redelivery race
recovered by `add_or_get_existing` — distinct from the pre-existing
same-session redelivery test, which an adversarial review correctly
flagged as only proving the application-level pre-check, not the DB
constraint — a cross-tenant mismatched-company/conversation test, and a
same-event-different-notification_type non-collision test),
`test_notifications_api.py` (+2: mark-read/mark-all-read each publish
the `notifications_changed` realtime signal, verified via a real
Redis-pubsub subscribe), `test_notification_email_dispatch_task.py`
(+1: a disabled email preference marks dispatched without sending),
`test_notification_preferences_api.py` (7, new: defaults-all-enabled,
update-and-reflect, re-enable-after-disable, unknown type/channel
rejected with 400, auth required, per-user scoping). Also 27 new
frontend tests (83 → 110 passing): `deliveryEffects.test.ts` (11),
`RealtimeProvider.test.tsx` (6, including this codebase's first
WebSocket-mocking pattern), `NotificationsPage.test.tsx` (8),
`NotificationBell.test.tsx` (+1, click-to-navigate). `ruff`/`mypy`/
`tsc`/`eslint` all clean; the production frontend build succeeds.

An adversarial multi-dimension code review (27 sub-agent calls across
correctness/concurrency, multi-tenant/RBAC, migration safety, frontend
correctness/security, and test-quality lenses, each finding
independently re-verified by two further agents trying to refute it)
ran before this shipped and found 11 real, previously-unnoticed issues —
including the critical unhandled-`IntegrityError` dedup race described
above, the cross-tenant `_load_conversation` scoping gap, the frontend
fail-open-on-empty-preferences-cache bug, and several genuine
test-coverage gaps — all fixed (one, a redundant single-column index
already covered by a composite unique constraint, was deliberately left
as-is: low severity, no correctness impact, and consistent with an
existing repo-wide model convention, so fixing it in isolation would
have been an inconsistent nitpick rather than a real improvement).

Live verification against the real production Docker stack (not just
the test suite) covered, with two real logged-in sessions (an Owner and
an Agent, the latter over a live `/ws/agent` WebSocket connection): the
full real pipeline for a new message — published through the actual
`EventOutbox` → relay → `conversation-ingest-consumer` →
`notification-consumer`, not a direct function call — delivering a live
`message.persisted` notification to the connected agent's socket within
seconds; the `notifications_changed` cross-tab signal, confirmed by
marking a notification read via one session and observing the push on
that same user's independently-connected socket; preference GET/PUT
persisting correctly; the dedup fix, confirmed by replaying the exact
same event through two genuinely separate sessions/transactions and
getting exactly one notification with zero consumer crashes or
restarts; and the migration/lock deadlock described above, discovered,
diagnosed via `pg_stat_activity`, and fixed entirely during this live
verification pass — the full multi-container startup (9 containers
racing for the same lock at once) then re-verified deadlock-free, and
the migration re-verified to converge correctly both from an empty
database and from the exact partial-failure state the deadlock had left
behind.

**Live conversation updates + customer typing (2026-07-27)**: 9 new
backend tests (2 in `test_agent_realtime_gateway.py` — an inbound
customer message and an agent's own reply each forwarded live over the
socket; 2 in `test_web_chat.py` — a typing frame broadcast for an
existing conversation, silently skipped with none yet) — 837 backend
tests total (was 828). 5 new frontend tests (3 in
`RealtimeProvider.test.tsx`, 2 in the new `MessageThread.test.tsx`) —
215 frontend tests total (was 210). `ruff`/`mypy`/`tsc`/`eslint` all
clean; the production build succeeds. Live-verified against the real
Docker stack (`backend`, `conversation-ingest-consumer`,
`workflow-engine-consumer`, `celery-worker`, `celery-beat` all rebuilt
and recreated) with two real raw WebSocket connections (Python's
`websockets` library, not mocks) — one as the agent gateway, one as the
web-chat widget — over the actual running RabbitMQ/Redis/Postgres:
sent an inbound customer message and confirmed the agent socket received
`message_received` with `direction: "inbound"`; sent a `typing` frame
once the conversation existed and confirmed `customer_typing` arrived
(and confirmed it does *not* arrive when sent before any conversation
exists yet); posted an agent reply via the REST API and confirmed the
same agent socket received a second `message_received` frame with
`direction: "outbound"` — proving a second agent/tab watching the same
conversation would see it live too.
