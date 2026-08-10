# Real-time: the agent WebSocket contract

**Status:** current. Companion to
[`notifications.md`](./notifications.md), which covers how notifications
are created and delivered; this document covers the socket itself — its
frames, its presence semantics, and what a client must do on reconnect.

It exists because FastAPI does not document WebSocket routes. Anyone
reading `openapi.json` would conclude the platform has no real-time
support at all, and that conclusion has been drawn before — it is
[gap 8.5](../api/mobile-integration-guide.md) in the mobile audit.

---

## 1. Endpoints

| Endpoint | Audience | Auth |
|---|---|---|
| `wss://<host>/api/v1/ws/agent` | Agents (the console, and any native client) | Access JWT as `?token=` |
| `wss://<host>/api/v1/web-chat/ws/{channel_config_id}` | End customers (the widget) | Anonymous session token |

This document is about the first. The Web Chat socket is a different
trust domain and is documented in [`web-chat.md`](./web-chat.md).

### Why the token is in the query string

Browsers cannot set arbitrary headers on a WebSocket handshake, so
`Authorization: Bearer` is not available. The access token goes in
`?token=`, which has a consequence worth stating plainly: **URLs are
logged in more places than headers are.** The mitigations are that the
access token is short-lived (15 minutes by default) and that NGINX is
configured not to log query strings for this path. Treat a leaked socket
URL as a leaked access token.

Failure to authenticate closes the socket with **4401** before accepting
it. A malformed inbound frame does *not* close the socket; an unrecoverable
domain error closes it with **4400**.

---

## 2. Frames

Every frame is a JSON object with a `type` discriminator. A client must
ignore types it does not recognise — new ones are added without a version
bump, and a client that throws on an unknown `type` breaks on deploy.

### Server → client

**`notification`** — something happened that this user should be told about.

```json
{
  "type": "notification",
  "id": "9f1c…",
  "notification_type": "conversation.assignment_changed",
  "title": "You've been assigned a conversation",
  "body": "Take a look.",
  "payload": {}
}
```

**`message_received`** — a message was stored on a conversation in this
company. Despite the name it covers **both directions**: `direction` is
`inbound` for a customer's message and `outbound` for an agent's reply,
so a second tab or a colleague watching the same conversation sees a reply
the moment it is sent.

```json
{
  "type": "message_received",
  "conversation_id": "3b7a…",
  "message_id": "c410…",
  "direction": "inbound",
  "body": "Are you still there?"
}
```

**`customer_typing`** — a Web Chat visitor is typing.

```json
{ "type": "customer_typing", "conversation_id": "3b7a…", "is_typing": true }
```

### Client → server

**`typing`** — the only inbound frame the gateway accepts.

```json
{ "type": "typing", "conversation_id": "3b7a…", "is_typing": true }
```

Suppressed entirely when the company has turned the typing indicator off
(Company Settings → Messaging). The setting is read **once per
connection**, so a change takes effect on the client's next reconnect
rather than instantly — the same staleness tradeoff the platform already
accepts for permissions embedded in an access token.

An unparseable frame is ignored and the connection stays open. Dropping
the socket over one bad frame would turn a client-side bug into an outage.

### Filtering is the client's job

The connection subscribes to two Redis channels: the user's personal
notification channel and the company-wide realtime channel. It forwards
what arrives verbatim. That means **a client receives `message_received`
for every conversation in its company, not only the one on screen**, and
filters on the frame's own `conversation_id`.

This was a deliberate choice over a dynamic subscribe/unsubscribe
protocol: the broadcast is what makes an Inbox list update live without
the client having to subscribe to forty conversations, and a per-
conversation protocol would have to stay correct across every reconnect.
Its cost is real and worth knowing — a company with heavy traffic sends
every agent every message, and a mobile client on a metered connection
pays for frames it discards. Revisit if that cost is ever measured to
matter.

---

## 3. Presence

Connecting flips `Agent.status` from `OFFLINE` to `ONLINE`. It never
overrides an explicit `AWAY` or `BUSY` — those are choices the agent made,
and a socket opening is not an argument against them.

**Disconnecting does not set `OFFLINE`.** This is the part that changed,
and the reason is that the original behaviour was correct only for a
desktop browser tab:

- **A phone disconnects constantly.** Backgrounding the app closes the
  socket. Marking that agent offline dropped them out of routing several
  times an hour, and put them back only when they next happened to open
  the app.
- **A second tab used to end the first one's presence.** Closing one of
  two connections marked the agent offline while they sat in front of the
  other.

### How it works now

Presence is derived from *how many connections an agent has*, not from the
most recent one to close. Two facts live in Redis
(`infrastructure/cache/presence.py`), because both are shared by every API
worker and by the sweep that acts on them — the worker that sees a
disconnect is usually not the one that sees the reconnect:

| Key | Shape | Meaning |
|---|---|---|
| `presence:live:{company}:{agent}` | Set of connection ids | One member per open socket |
| `presence:pending_offline` | Sorted set, scored by deadline | Agents due to be marked offline |

```
connect     →  SADD live, ZREM pending, status ONLINE if OFFLINE
disconnect  →  SREM live; if the set is now empty, ZADD pending at
               now + presence_offline_grace_seconds
sweep       →  every 30s: claim each due agent with ZREM, re-check the
               live set, then write OFFLINE
```

The sweep is `blinkengage.agents.sweep_presence_offline`. Going offline is
the one presence transition nobody performs — staying disconnected is the
*absence* of an event — so something has to notice, the same shape of
problem as an SLA clock running out.

**The claim and the re-check** handle the two things that can happen
between a deadline being written and the sweep running. The `ZREM` settles
overlapping sweeps: only the caller that actually removed the member
proceeds. The live-set check settles a reconnect, and is performed *again*
after the status is written, because a reconnect landing in between would
otherwise leave a connected agent marked offline with nothing scheduled to
correct it.

### Settings

| Setting | Default | Notes |
|---|---|---|
| `presence_offline_grace_seconds` | 90 | Longer than a backgrounded app's reconnect, far shorter than a break |
| `presence_connection_ttl_hours` | 12 | Leak backstop only — reached solely by a worker that died without running its disconnect path |

The sweep runs at 30s against a 90s grace, so the effective wait is 90–120
seconds. A sweep coarser than the grace it enforces would make the wait up
to twice what an operator configured.

---

## 4. Reconnect: what a client must do

**A WebSocket is a latency optimisation, not a delivery guarantee.**
Nothing replays frames missed while a phone was in a lift. Design the
client so that a socket which never connects at all still produces a
correct — if less immediate — application.

On every reconnect:

1. **Re-fetch and reconcile.** Use
   `GET /conversations?updated_since=<newest updated_at you hold>` — the
   delta sync exists for exactly this, so resuming costs one small request
   rather than re-paging the Inbox.
2. **Do not trust the stream to have been continuous.** Reconcile by id
   and let the fetched state win.
3. **Poll as a degraded mode.** Every 30s while the socket is down is
   legitimate. A client that shows stale data confidently is not.

One caveat on the delta: a conversation **deleted** while the client was
away is absent from the response rather than reported as removed. There is
no tombstone feed. A client that must not show deleted conversations has
to reconcile against a full list periodically.

---

## 5. Testing

The suite calls the gateway coroutine directly with a fake WebSocket
(`tests/integration/test_agent_realtime_gateway.py`) rather than using
Starlette's ASGI WebSocket test client, which corrupts the shared
in-memory-SQLite connection the async fixtures use. The sweep is tested
through `_settle_one` in `tests/integration/test_presence_offline_sweep.py`.

---

## See also

- [`notifications.md`](./notifications.md) — how notifications are created, and push delivery
- [`web-chat.md`](./web-chat.md) — the customer-facing socket
- [Mobile Integration Guide](../api/mobile-integration-guide.md) — the client-side contract in full
