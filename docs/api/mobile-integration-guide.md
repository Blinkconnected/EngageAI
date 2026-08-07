# Mobile Integration Guide

**For engineers building a native client against Blink Engage.**

This covers the contracts a mobile app needs — authentication, real time,
paging, uploads, push, offline behaviour — and ends with an honest audit
of what is missing. Nothing here is aspirational: every endpoint named
was verified against the running API.

**Headline:** the platform is more ready for a mobile client than the
absence of one suggests. Device registration, FCM push, token refresh and
an agent WebSocket all exist today. Three real gaps remain, listed in §8.

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
| `wss://<host>/api/v1/ws/{channel_config_id}` | Web chat widget (end customers) |

Mobile agent apps want `/ws/agent`.

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

**On every reconnect, re-fetch the conversation list** and reconcile
against local state. Design the client so that a socket which never
connects at all still produces a correct, if less immediate, app. Polling
every 30 s as a fallback is a legitimate degraded mode; a client that
shows stale data confidently is not.

## 4. Pagination

Two conventions exist in the API, and you will meet both:

| Style | Endpoints | Parameters |
|---|---|---|
| Page-based | 26 | `page`, `page_size` |
| Limit/offset | 13 | `limit`, `offset` |

Both are offset-based, which has a known consequence: **on a list that is
actively changing, an item can be seen twice or missed** as rows shift
between page requests. Conversation lists are exactly such a list.

Mitigate on the client:

- key list items by id and de-duplicate on merge,
- treat page 1 as authoritative on refresh rather than merging into an
  older cache,
- do not build "load more" on the assumption that offsets are stable.

Cursor pagination would fix this properly and does not exist — recorded
in §8.

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
have succeeded before the connection dropped. **The API does not
currently accept an idempotency key** (§8), so:

- Generate a client-side message id, send it, and de-duplicate on read.
- Never auto-retry a `POST` that creates a customer-visible artefact
  (a message, an invoice) without user confirmation.
- `GET`, `PUT` and `DELETE` are safe to retry.

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

### 8.1 No delta sync 🟠

There is no `?since=<timestamp>` or change-feed endpoint. A client
returning after hours offline must re-page the conversation list to
discover what changed.

**Cost:** more requests and more battery on resume; worse on poor
networks, which is when it matters most.

**Fix:** `GET /api/v1/conversations?updated_since=<iso8601>` on the
existing list endpoint. The data is already there —
`conversations.updated_at` is indexed. Small.

### 8.2 No cursor pagination 🟠

Offset paging over a live list can duplicate or skip rows (§4).

**Fix:** cursor pagination on the conversation and message lists — the
two that change while being read. The rest can stay page-based.

### 8.3 No APNs sender 🟡

FCM only. iOS works via Firebase, which is normal but couples an iOS
build to a Firebase project a customer may not want.

**Fix:** an `ApnsPushSender` alongside `FcmPushSender`. The `PushSender`
interface and factory already exist, so this is an addition rather than a
change — the architecture anticipated it.

### 8.4 No idempotency keys 🟡

Safe `POST` retries are not expressible (§7).

**Fix:** accept `Idempotency-Key` on message send and other creating
endpoints, store the key with the result, return the original response on
replay. Standard, and worth doing before a mobile client ships.

### 8.5 WebSocket contract is undocumented 🟡

Real time exists and is invisible to anyone reading the OpenAPI schema.

**Fix:** document the message envelope, event types and reconnect
semantics in `docs/architecture/realtime.md` and link it from the API
reference. Documentation, not code — and the cheapest item here.

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
2. Conversation list and detail, offset paging with de-duplication (§4).
3. Send message, with client-generated ids (§7).
4. Push registration (§6).
5. WebSocket, **as an enhancement over a working polling client** (§3).
6. Attachments (§5).

Building step 5 before step 2 works is the common mistake: it produces an
app that feels fast when the socket is up and is broken when it is not.

---

## See also

- [API Reference](./README.md) — conventions, auth, errors
- [Known Limitations](../releases/v1.0-known-limitations.md)
- [Technical Debt Register](../releases/v1.0-technical-debt.md)
- `docs/architecture/notifications.md` — push delivery internals
