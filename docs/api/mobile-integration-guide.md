# Mobile Integration Guide

**For engineers building a native client against Blink Engage.**

This covers the contracts a mobile app needs — authentication, real time,
paging, uploads, push, offline behaviour — and ends with an honest audit
of what is missing. Nothing here is aspirational: every endpoint named
was verified against the running API.

**Headline:** the platform is more ready for a mobile client than the
absence of one suggests. Device registration, FCM push, token refresh and
an agent WebSocket all exist today.

**Since v1.2.0**, four of the six gaps this guide originally recorded are
closed: delta sync, cursor pagination, idempotency keys on message send,
and this WebSocket contract being documented at all. Presence also no
longer treats a backgrounded phone as an absent agent. What remains is
§8.3 (no APNs sender) and §8.6 (no aggregate conversation endpoint) —
both amber, neither blocking.

---

## 1. Base URL and versioning

```
https://<host>/api/v1
```

Every route is under `/api/v1`. There is no `v2`; when one arrives it
will be a sibling path, not a breaking change to this one.

**`/docs`, `/redoc` and `/openapi.json` are disabled in production** —
an unauthenticated API map is reconnaissance. Generate the schema from a
staging deployment and check it into your mobile repo, so the client is
built against a pinned contract rather than a live one.

## 2. Authentication

Bearer JWT. Not cookies — deliberately, so there is no CSRF surface and
no cookie-jar behaviour to fight on mobile.

```
POST /api/v1/auth/login          → { access_token, refresh_token }
POST /api/v1/auth/refresh        → { access_token, refresh_token }
POST /api/v1/auth/logout         → revokes the refresh token
GET  /api/v1/auth/me             → the current user and permissions
```

Send on every request:

```
Authorization: Bearer <access_token>
X-Correlation-ID: <uuid you generate>
```

### Token lifetimes

| Token | Default | Setting |
|---|---|---|
| Access | 15 minutes | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Refresh | 30 days | `REFRESH_TOKEN_EXPIRE_DAYS` |

Refresh tokens live in Redis and are revocable, so `logout` genuinely
ends the session rather than relying on the client to forget.

### The refresh rule that matters on mobile

**Refresh proactively, and serialise it.**

A mobile client suspends and resumes constantly. On resume, an expired
access token will fail several in-flight requests at once, and a naive
"refresh on 401" retries all of them concurrently — several refresh calls
race, all but one of the resulting tokens is discarded, and on a rotating
refresh scheme the loser's token is already invalid. The user is logged
out for no reason.

```
on resume:
    if access_token expires within 60s:
        await refresh()          ← single-flight, all callers await the same promise
    proceed
```

Treat 401 as "refresh once, retry once, then log out" — never as a retry
loop.

### Permissions

`GET /api/v1/auth/me` returns the user's permission set. Use it to hide
UI the user cannot use, but **do not treat it as enforcement** — the
server checks every action independently. A mobile client that hides a
button has improved the experience, not the security.

## 3. Real time

Two WebSocket endpoints exist. **Neither appears in the OpenAPI schema**,
because FastAPI does not document WebSocket routes — so a developer
reading the generated schema would conclude the platform has no real-time
support. It does:

| Endpoint | For |
|---|---|
| `wss://<host>/api/v1/ws/agent` | Agent client — conversation and message updates |
| `wss://<host>/api/v1/web-chat/ws/{channel_config_id}` | Web chat widget (end customers) |

Mobile agent apps want `/ws/agent`.

**The full contract — every frame type, the presence model, reconnect
semantics — is in [`realtime.md`](../architecture/realtime.md).** Read it
before building the socket; what follows here is only the client-side
shape of it.

One property that catches people: the socket forwards `message_received`
for **every conversation in the company**, not only the one on screen, and
the client filters on the frame's own `conversation_id`. That is what
makes an Inbox list update live without subscribing per conversation, and
it means a busy company sends a mobile client frames it will discard.

### Connection lifecycle

```
connect  →  authenticate with the access token
         →  receive events while foregrounded
         →  disconnect on background
         →  on resume: reconnect AND reconcile (see below)
```

### Reconcile, do not trust the stream

A WebSocket is a latency optimisation, not a delivery guarantee. A phone
that lost signal in a lift missed whatever arrived meanwhile, and nothing
replays it.

**On every reconnect, re-fetch and reconcile** — with
`GET /conversations?updated_since=<newest updated_at you hold>`, which
exists for exactly this and costs one small request rather than a re-page
of the whole Inbox. Design the client so that a socket which never
connects at all still produces a correct, if less immediate, app. Polling
every 30 s as a fallback is a legitimate degraded mode; a client that
shows stale data confidently is not.

**Backgrounding no longer takes the agent offline.** Closing the socket
starts a grace period (90 s by default) rather than an immediate
transition, and reconnecting inside it cancels the transition entirely —
so an agent who pockets their phone stays in routing. A client does not
have to do anything to get this; it is worth knowing so the app does not
try to work around a problem that no longer exists. Full model in
[`realtime.md`](../architecture/realtime.md).

## 4. Pagination

Two conventions exist in the API, and you will meet both:

| Style | Endpoints | Parameters |
|---|---|---|
| Page-based | 26 | `page`, `page_size` |
| Limit/offset | 13 | `limit`, `offset` |

Both are offset-based, which has a known consequence: **on a list that is
actively changing, an item can be seen twice or missed** as rows shift
between page requests.

### Use the cursor on the two lists that move

The conversation and message lists — the two a client reads while they are
being written — also accept `?cursor=`:

```
GET /api/v1/conversations/{id}/messages?page_size=30
    → { "items": [...], "next_cursor": null }        ← offset request

GET /api/v1/conversations/{id}/messages?page_size=30&cursor=<token>
    → { "items": [...], "next_cursor": "eyJ2Ijox…" } ← keep going while set
```

Seed the first page without a cursor, then follow `next_cursor` until it
is `null`. The token is **opaque** — echo it back verbatim; parsing it
couples you to a sort key that may change. An invalid one is a 422 rather
than a silent first page, because a paging loop that never advances is far
harder to notice than an error.

Note that passing `cursor` on the conversation list also changes the
ordering to most-recently-active first; see §8.2 for why the SLA-health
ordering cannot be keyset-paged.

### On every other list, and as a general habit

- key list items by id and de-duplicate on merge,
- treat page 1 as authoritative on refresh rather than merging into an
  older cache,
- do not build "load more" on the assumption that offsets are stable.

## 5. Attachments

```
POST   /api/v1/conversations/{id}/attachments                     upload
GET    /api/v1/conversations/{id}/attachments/{aid}/download      full file
GET    /api/v1/conversations/{id}/attachments/{aid}/media         inline/streamed
```

- `media` supports **range requests**, so audio and video can stream and
  seek without downloading the whole object. Use it for playback;
  use `download` for save-to-device.
- Uploads are validated server-side against an allowlist of types. Do not
  rely on client-side filtering — check the error, and surface it.
- Media access is token-scoped; do not cache a media URL past the
  session, and never embed one in a push payload.

## 6. Push notifications

**This exists and works.**

```
GET    /api/v1/notifications/devices              list registered devices
POST   /api/v1/notifications/devices              register this device
DELETE /api/v1/notifications/devices/{device_id}  unregister
```

Register on login and after every token rotation; unregister on logout.
A device left registered after logout sends a customer's conversation
alerts to a phone that is no longer signed in.

### Delivery

Push is sent by the `dispatch-notification-pushes` sweep (every 10 s) via
**Firebase Cloud Messaging**.

**There is no APNs sender.** iOS is supported only by routing APNs
through Firebase, which is a normal and supported FCM configuration but
does mean an iOS build depends on a Firebase project. Recorded in §8.

If `FCM_SERVICE_ACCOUNT_JSON` is unconfigured, the platform sends nothing
and **does not mark notifications as pushed** — so configuring
credentials later starts delivering immediately, and "push is not set up"
never looks like "push is set up and failing."

### Payload discipline

Treat a push as a **signal, not a source of truth**: it says something
happened, and the app fetches the detail. Do not put customer message
content in a push payload — it lands on a lock screen, it is logged by
the platform vendor, and it is the wrong place for a healthcare or
financial customer's data.

## 7. Offline and retries

### Idempotency

Retrying a `POST` after a timeout is normal on mobile — the request may
have succeeded before the connection dropped.

**Message send accepts `Idempotency-Key`.** Generate one per composed
message (a UUID is fine), keep it for the lifetime of that send including
retries, and discard it once the message is confirmed:

```
POST /api/v1/conversations/{id}/messages
Idempotency-Key: 6f9d2c1e-…

201 Created                      ← first attempt
201 Created + Idempotent-Replay: true   ← your retry, same message
```

Rules that follow from the semantics (full detail in §8.4):

- **Never change the body while reusing a key** — that is a 422, by
  design. A new message needs a new key.
- A **409** means an earlier attempt is still in flight. Back off and
  retry the same key; do not send a fresh one.
- Keys are replayable for 24 hours, so a retry the next morning is still
  absorbed.
- On endpoints that do *not* yet accept the header: never auto-retry a
  `POST` that creates a customer-visible artefact without user
  confirmation. `GET`, `PUT` and `DELETE` remain safe to retry.

### Correlation

Send `X-Correlation-ID` on every request. It is echoed back, and it is
threaded through the outbox, the queues, every consumer's logs and any
background task the request spawns. When a customer reports "I sent a
message and nothing happened", that id is the difference between a
five-minute answer and an afternoon.

### Errors

| Status | Meaning | Client action |
|---|---|---|
| 401 | Access token expired or revoked | Refresh once, retry once, then log out |
| 403 | Permission or feature not enabled | Do not retry; explain |
| 409 | Conflict (e.g. already assigned) | Re-fetch and re-present |
| 422 | Validation | Show field errors; do not retry |
| 429 | Rate limited | Back off; honour `Retry-After` |
| 5xx | Server | Exponential backoff, cap attempts |

**403 has two distinct causes** — the user lacks a permission, or the
company does not have that feature. The message distinguishes them.
Do not collapse both into "access denied"; one is fixable by an
administrator granting a role, the other requires a plan change.

## 8. Gap audit

What a mobile client would want and not find. Each is scoped, none is
architectural.

### 8.1 No delta sync — ✅ **closed**

`GET /api/v1/conversations?updated_since=<iso8601>` now exists. The
comparison is strictly greater-than, so a client that stores the newest
`updated_at` it has received and sends it back is not handed that same row
on every poll. It composes with every other filter on the list.

**One correction to this entry as originally written**, because it was
wrong in a way that mattered: it recorded the fix as needing no migration
on the grounds that `conversations.updated_at` was already indexed. It was
not. The column exists (via `TimestampMixin`) but every index on the table
covered `last_message_at`, a lifecycle column, or the channel thread —
none of them answers "changed since". Shipping the filter alone would have
made the request a client is told to use *on resume, on a bad network* a
full scan of the company's conversations. Migration `c7d1e4b93a58` adds
`ix_conversations_company_updated_at`.

**Still missing: deletions.** A conversation deleted while the client was
away is simply absent from the delta rather than reported as removed.
There is no tombstone feed, so a client that must not show deleted
conversations has to reconcile against a full list periodically.

### 8.2 No cursor pagination — ✅ **closed**

Both lists that change while being read — conversations and messages —
accept `?cursor=` and return `next_cursor`. Offset paging is untouched:
`page`/`page_size` behave exactly as before and simply report
`next_cursor: null`.

Two things are worth knowing before building against it.

**Cursor mode changes the conversation ordering**, to most-recently-active
first rather than worst-SLA-health first. This is not a shortcut. Health is
computed from the SLA clocks *at query time*, so a conversation's rank
changes while a client pages through it; a keyset over that would point at
a position that no longer exists and would promise a stability it could not
deliver. `last_message_at` only ever moves forward, so in a descending
ordering a row can be seen twice — which a client keying by id can drop —
but never silently skipped, which is the guarantee actually worth having.
The health-ordered Inbox remains offset-paged.

**The cursor names a row, not a position.** It encodes only an id; the
sort value is looked up from that row when the page is built. The obvious
alternative — putting the timestamp in the cursor — makes the keyset
depend on a value surviving JSON, a timezone and a bind parameter with its
precision intact, and it does not always survive. Treat the token as
opaque and echo it back unchanged.

### 8.3 No APNs sender 🟡

FCM only. iOS works via Firebase, which is normal but couples an iOS
build to a Firebase project a customer may not want.

**Fix:** an `ApnsPushSender` alongside `FcmPushSender`. The `PushSender`
interface and factory already exist, so this is an addition rather than a
change — the architecture anticipated it.

### 8.4 No idempotency keys — ✅ **closed for message send**

`POST /conversations/{id}/messages` accepts `Idempotency-Key`. Present the
same key to retry safely after a timeout: the original response comes back
with `Idempotent-Replay: true` and no second message is sent.

- The key is scoped to the **sender and the conversation**, not just the
  company. Reusing one across conversations produces two messages —
  replaying the first conversation's reply into the second would be worse
  than the duplicate. Two different agents presenting the same key on the
  same conversation likewise each get their own message.
- Reusing a key with a *different* body is a **422**, not an absorbed
  duplicate. Returning the first response to a request that was never
  performed is the failure this feature exists to prevent, not a form of
  it.
- A key held by a request still in flight is a **409**. Retry shortly.
- Keys are replayable for 24 hours (`idempotency_result_ttl_hours`).

**Not yet covered:** other creating endpoints. The guard
(`api/idempotency.py`) is reusable and adding one is a few lines, but only
message send is wired up today — that is the one where a duplicate is
visible to a customer.

### 8.5 WebSocket contract is undocumented — ✅ **closed**

[`docs/architecture/realtime.md`](../architecture/realtime.md) now
documents the frame envelope, every event type, the presence model and
reconnect semantics.

Note one change it records: **a disconnect no longer marks an agent
offline.** The old behaviour dropped a phone user out of routing every
time their screen locked. Losing the last connection now schedules the
transition for `presence_offline_grace_seconds` (default 90) later, and
reconnecting cancels it.

### 8.6 No mobile-shaped aggregate endpoint 🟡

Rendering a conversation screen takes several round trips (conversation,
messages, customer, notes). Acceptable on a LAN, noticeable on 3G.

**Fix:** consider a single read-optimised endpoint for the conversation
view. Worth measuring before building — it is the kind of optimisation
that is easy to add and hard to remove.

### What is *not* a gap

- **Authentication** — refresh, revocation and permissions are complete.
- **Push infrastructure** — device registry and FCM delivery work.
- **Real time** — the agent socket exists.
- **Attachments** — range requests are supported, so media streams.
- **Tenant isolation** — enforced server-side; a mobile client cannot
  reach another company's data by manipulating a request.

## 9. Recommended build order

1. Auth + single-flight refresh (§2) — everything depends on it.
2. Conversation list and detail, **cursor-paged** (§4).
3. Send message with `Idempotency-Key` (§7).
4. Push registration (§6).
5. WebSocket, **as an enhancement over a working polling client** (§3),
   with `updated_since` reconciliation on every reconnect.
6. Attachments (§5).

Building step 5 before step 2 works is the common mistake: it produces an
app that feels fast when the socket is up and is broken when it is not.

---

## See also

- [API Reference](./README.md) — conventions, auth, errors
- [Known Limitations](../releases/v1.0-known-limitations.md)
- [Technical Debt Register](../releases/v1.0-technical-debt.md)
- [Real-time contract](../architecture/realtime.md) — frames, presence, reconnect
- `docs/architecture/notifications.md` — push delivery internals
