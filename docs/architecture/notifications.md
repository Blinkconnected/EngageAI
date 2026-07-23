# Notifications & Real-Time Layer

M21 of the roadmap. Two halves: a durable per-user notification inbox
(with email dispatch via Celery), and an agent-facing WebSocket gateway
providing presence, live notification delivery, and — closing a real gap
left open since M11 — agent-side typing indicators actually reaching the
customer.

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

Three things happen over one connection:

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
3. **Typing** — the only inbound frame type
   (`{"type": "typing", "conversation_id", "is_typing"}`), forwarded to
   `ConversationService.send_typing_indicator`.

Tested the same way M12's Web Chat gateway is: calling the gateway
coroutine directly with a hand-built fake WebSocket, not through a real
ASGI WebSocket connection (Starlette's `TestClient.websocket_connect`
runs in its own background-thread event-loop portal, which corrupts the
shared in-memory-SQLite connection this suite's async fixtures use).

## The notification inbox

`Notification` (per-user, hard-deletable — a personal inbox is
functional, not a compliance record, unlike `AuditLog`). Created two ways:

- **Built-in** (`notification_consumer.py`): binds a *fixed*, code-defined
  set of routing keys — `conversation.assignment_changed`,
  `conversation.sla_breached` — unlike the Workflow Engine's `#`, since
  these are first-party lifecycle notifications every company gets, not
  something a company configures. The second consumer (after
  `audit-log-consumer`) with a narrower binding than `#`; more triggers
  are one more routing-key binding away.
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
channel config is.

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
