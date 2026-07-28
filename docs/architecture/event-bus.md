# Domain Event Bus

M10 of the roadmap. Foundational cross-cutting infrastructure that Phase 2
(Channels/Conversations) and every later phase (AI, Workflow Engine,
Notifications, ERPNext, Reporting/Analytics) build on, so it lands *before*
the channel plugin architecture (M11) even though it isn't itself a
channel feature.

## Why this exists

M9 (audit logging) introduced `domain/audit.py`'s `AuditEvent`/
`AuditPublisher`: each mutating service called an `AuditPublisher` directly,
synchronously, in its own request transaction. That module's own docstring
admitted the design was deliberately single-consumer: "not a general-purpose
event bus... adding indirection for a single consumer would be
speculative." Phase 2 onward invalidates that premise — the roadmap needs
message received/sent, customer created, assignment changed, AI completed,
ERP updated, and workflow executed to all reach AI, Workflow Engine,
Notifications, ERPNext, Reporting, Analytics, and Audit Logging *without*
each of those modules being wired into the services and each other directly
(requirement: adding a consumer must require zero changes to whatever
publishes the event, or to any other consumer). That's a real event bus,
not five more direct-call hooks.

## Two tiers, not one

Not every signal needs the same guarantee, so there are two independent
mechanisms rather than one bus wearing two hats:

| | Durable domain events | Ephemeral realtime signals |
|---|---|---|
| Examples | `message.received`, `customer.created`, `workflow.executed` | typing indicator, presence, live delivery ticks |
| Guarantee | must never be silently lost | fine to drop if nobody's listening right now |
| Transport | Postgres outbox → RabbitMQ topic exchange | Redis pub/sub |
| Latency cost | one extra DB row + async relay | near-zero |

Forcing typing indicators through a durable, at-least-once pipeline would
add latency for no benefit; forcing `message.received` through fire-and-
forget pub/sub would silently drop messages under broker hiccups. Two
mechanisms, matched to two different guarantees.

## Durable events: the transactional outbox

A naive "commit to Postgres, then publish to RabbitMQ" has a gap: if the
process crashes between those two steps, the business change is committed
but its event is gone forever — and the reverse (publish succeeds, then the
DB transaction rolls back) fabricates an event for a change that never
happened. Fixed with the standard **transactional outbox** pattern:

1. `domain/events.py` defines `DomainEvent` (generalizes M9's `AuditEvent`):
   `event_type` (`"<aggregate_type>.<verb>"`, e.g. `"customer.created"`,
   `"message.received"` — the same convention M9 established),
   `company_id: UUID | None` (nullable — some events are platform-level),
   `aggregate_type`, `aggregate_id: UUID | None`,
   `actor_user_id: UUID | None`, `payload: dict[str, Any]`, `occurred_at`.
   `DomainEventPublisher` is a `Protocol` with one method —
   `async def publish(event) -> None` — same shape as `AuditPublisher`.
2. `EventOutbox` (`infrastructure/database/models/event_outbox.py`) is an
   append-only table, same philosophy as `AuditLog` (no Timestamp/
   SoftDelete mixins): `id`, `event_type`, `company_id`, `aggregate_type`,
   `aggregate_id`, `payload` (JSON), `occurred_at`, `created_at`,
   `dispatched_at` (nullable — null means "not yet relayed"), `attempts`.
   A partial index on `WHERE dispatched_at IS NULL` keeps relay claiming
   cheap forever, regardless of how large the dispatched majority grows.
3. `OutboxEventPublisher` (`infrastructure/events/outbox_publisher.py`)
   implements `DomainEventPublisher` by adding one `EventOutbox` row per
   `publish()` call, on whatever `AsyncSession` it was built with — the
   same request-scoped session the triggering business change is using.
   **No broker round-trip on the request path.** The event and the change
   it describes commit or roll back together, atomically, by construction.
4. A separate **relay** asynchronously drains the outbox to RabbitMQ. It
   runs as a Celery-beat-scheduled task (`infrastructure/events/relay.py`,
   registered in `core/celery_app.py`'s `beat_schedule` and `include` list
   exactly like the existing `ping` task), so it inherits Celery's
   existing horizontal scaling for free — more `celery-worker` replicas
   means more relay throughput, no new deployment concept needed.
5. **Claiming is safe under concurrent relays.** The claim query uses
   `SELECT ... FOR UPDATE SKIP LOCKED` on Postgres, so if two relay
   invocations overlap (multiple worker replicas, or beat firing before
   the previous run finished), each claims a disjoint batch — no row is
   published twice. SQLite (test-only) doesn't support `SKIP LOCKED`, so
   the claim query branches on `session.bind.dialect.name`, exactly like
   `GUID`'s existing `if dialect.name == "postgresql"` branch in
   `infrastructure/database/base.py`; the simpler non-locking SQLite path
   is fine because tests never run concurrent relays.
6. Each claimed row is published to a durable RabbitMQ **topic exchange**
   (`blinkengage.events`, routing key = `event_type`) via `aio_pika`
   (already a declared dependency, unused until now) as a persistent
   message, then marked `dispatched_at`. Publish failures leave
   `dispatched_at` null and increment `attempts`, so the next relay run
   retries it — at-least-once delivery.

## Consumers: independent durable queues, not more Celery tasks

Celery's task model is RPC-style — dispatch one task, one worker executes
it once. What every future module needs instead is **topic-exchange fan-
out**: one published event, delivered to *every* independently-bound
durable queue, each queue consumed by its own module at its own pace. That
isn't naturally expressed as a Celery task, so consumers are small,
standalone `aio_pika` consumer processes instead:

- `infrastructure/events/consumer.py`: `run_consumer(queue_name, routing_keys,
  handler)` — declares the shared exchange, declares (or reuses) a durable
  queue named `queue_name`, binds each of `routing_keys` (a topic pattern
  like `#` for "everything" or `message.*` for a namespace), and consumes
  forever with manual ack — only acking a message once `handler` returns
  successfully, so a crashed handler leaves the message for redelivery.
  This is the one piece of shared plumbing every consumer reuses; nothing
  here knows what any specific consumer does with an event.
- Each consumer module supplies its own `queue_name`, `routing_keys`, and a
  pure, independently unit-testable `handler(event, session) -> None`, and
  is its own process/docker-compose service (mirrors how `celery-worker`
  and `celery-beat` are already separate services from `backend`) —
  **adding consumer #6 is a new module + one new compose service, zero
  changes to the outbox, the relay, or any existing consumer.**

### The audit-log consumer: M9's hook, generalized

`infrastructure/events/consumers/audit_log_consumer.py` is the first
consumer, and it replaces M9's direct-call hook entirely:

- **Before (M9):** `DepartmentService`/`TeamService`/`AgentService`/
  `CustomerService`/`AuthService` each took an `audit: AuditPublisher`
  constructor argument and called `audit.publish(AuditEvent(...))` inline.
  Which actions got audited was an explicit per-service opt-in list.
- **After:** those same five services take a `events: DomainEventPublisher`
  argument instead and publish a generic `DomainEvent` — the exact same
  call site, same information, just a more general type. The `audit-log`
  consumer binds `queue_name="audit-log"`, `routing_keys=["#"]` (literally
  everything published to the bus) and its `handle_audit_event(event,
  session)` writes one `AuditLog` row per event
  (`action=event.event_type`, `entity_type=event.aggregate_type`,
  `entity_id=event.aggregate_id`, `details=event.payload`, ...).
  "What gets audited" becomes "everything," which is both simpler and
  safer for compliance than an opt-in list a future developer could forget
  to extend. `AuditLog`, `AuditLogRepository`, `AuditLogService`, and
  `GET /audit-logs` are all unchanged — only *how a row gets written*
  moved from a direct call to a bus subscription.

This means the audit trail is now itself proof the bus works: as soon as
channels/conversations (M12+) start publishing `message.received`, those
rows show up in `GET /audit-logs` with zero code changes to the audit
module — exactly the decoupling this milestone exists to deliver.

**Redacted, not verbatim, for a handful of fields (P6.20's final
review).** "Everything is audited" was, until this fix, being read too
literally: `message.received`/`message.persisted`/`message.sent`'s
`body` and `conversation.transferred`'s `note` were copied into
`AuditLog.details` character-for-character.
`_REDACTED_PAYLOAD_FIELDS` in `audit_log_consumer.py` now replaces those
specific free-text fields with the literal string `"[redacted]"` before
the row is written — the row itself (who, when, what event type) is
still recorded, just not a second verbatim copy of what a customer said.
This matters because `AuditLog` has different retention semantics than
`Conversation`: it's never touched by `Conversation.deleted_at` (soft
delete) or the agent-removal flow above, and it's reachable through
`audit_logs.read` alone — a permission entirely separate from
`conversations.read` — so a customer's message content was effectively
being duplicated into a second, longer-retained, differently-permissioned
store. Structural fields (ids, `channel_type`, `to_agent_id`, etc.) are
untouched; only the free-text ones are redacted, and only for the four
event types listed in `_REDACTED_PAYLOAD_FIELDS`.

## Ephemeral signals: Redis pub/sub

`infrastructure/events/realtime_publisher.py`: `RealtimePublisher.publish(
channel: str, payload: dict)` — a thin wrapper over the existing shared
`redis.asyncio.Redis` singleton's `PUBLISH` command (the client is already
a `providers.Singleton` in `core/container.py`; its docstring already
anticipated "caching/pub-sub" as a future use). Channel naming:
`company:{company_id}:conversation:{conversation_id}:typing`, etc. This
milestone only builds the publish side — `ChannelProvider.typing_indicator()`
(M11) has somewhere real to send to. Nothing subscribes yet; that starts
with the Web Chat channel/WebSocket gateway (M12) and the Notifications
module (M22, renumbered).

Why Redis and not the same outbox+RabbitMQ pipeline: durability is exactly
the property these signals don't need, and paying for it would only add
latency to something inherently latency-sensitive (a typing indicator that
arrives after the user stopped typing is useless).

## Scaling posture

- **Relay**: horizontally safe via `SKIP LOCKED` — add `celery-worker`
  replicas, relay throughput scales with them, no coordination needed.
- **Consumers**: each is its own process/queue — scale a hot consumer
  (e.g. AI processing under load) independently of a cold one (e.g. ERP
  sync) by running more instances of just that consumer's compose service;
  RabbitMQ's competing-consumers-per-queue semantics handle load balancing
  within a consumer type automatically.
- **Outbox table growth**: at 100M-message scale, event volume tracks
  message volume. Dispatched rows should be pruned/archived by a scheduled
  job once they're old enough that no retry could plausibly still need
  them (operational task, not built in this milestone — the partial index
  already excludes dispatched rows from the hot path regardless of table
  size).

## Incident: silent relay starvation (found during Phase 7/M33)

While building the frontend's Conversation View, a real end-to-end check
(send a message over the web-chat WebSocket, confirm it becomes a real
conversation via `GET /conversations`) never showed the conversation.
Investigation traced it to two compounding, previously-undiscovered bugs:

1. **Root cause**: `GUID.process_result_value`
   (`infrastructure/database/base.py`) used `isinstance(value, uuid.UUID)`
   to decide whether a loaded value already needs no conversion. asyncpg
   returns its own `asyncpg.pgproto.pgproto.UUID` for UUID columns — a
   *subclass* of `uuid.UUID`, so `isinstance` is `True` for it, and the
   raw asyncpg object passed through unconverted. That object behaves
   identically to a real `uuid.UUID` everywhere the app already
   exercised it (`str()`, equality, Pydantic response serialization) —
   except `orjson.dumps()`, which only recognizes the *exact* `uuid.UUID`
   type, not subclasses. The relay's `_serialize()` calls `orjson.dumps()`
   directly on `event.company_id`/`aggregate_id`/`actor_user_id`, so
   **every single outbox row with a non-null UUID field failed to
   publish**, unconditionally, every time. Fixed by checking
   `type(value) is uuid.UUID` instead of `isinstance`.
2. **Compounding severity multiplier**: `claim_batch` claims the oldest
   undispatched rows with no bound on `attempts`, and `mark_failed` had no
   cap. Once bug #1 started failing every publish, the *same* oldest
   ~100 rows (`events_relay_batch_size`) were reclaimed and re-failed on
   every 5-second relay tick, forever — permanently starving every
   healthy event created afterward from ever being claimed, since they
   were always newer (further back in the FIFO) than the permanently-
   failing rows in front of them. Confirmed live: one row had reached
   **14,586 attempts** (~20 hours of continuous failure) with `attempts=0`
   sitting on brand-new events that had never been claimed even once.

Both were live for the entire event-bus-dependent surface of the
application — audit logging, reporting rollups, conversation ingestion,
notifications, workflow triggers, ERP sync — since bug #1 has existed
since the `GUID` type was introduced (M2) and only manifests when
something calls `orjson.dumps()` on a loaded UUID field directly, which
only the relay does (every API response's UUID serialization goes through
Pydantic, which tolerates the subclass fine). It was never caught by any
existing test because the established test pattern for exercising
consumers (`drain_outbox`-style fixtures, `_ingest_inbound_message`
helpers) calls consumer handlers directly against fabricated event dicts,
bypassing the relay's `orjson.dumps()` call entirely — this is the first
verification this build ever did of the *actual* outbox → relay →
RabbitMQ → consumer path against a real Postgres/asyncpg connection with
real, non-null UUID columns.

**Fixes shipped together**:
- `GUID.process_result_value`: `type(value) is uuid.UUID` instead of
  `isinstance`.
- A dead-letter guard: `claim_batch` now takes a required `max_attempts`
  and excludes rows at or past it (`events_relay_max_attempts`, default
  10) from future claims — a circuit breaker, not a silent drop; excluded
  rows stay in the table (`dispatched_at` still null) for an operator to
  find via `attempts >= max_attempts`. This doesn't fix bug #1, but it
  means a *future*, unrelated poison event can't again take down the
  entire relay indefinitely — one bad row now costs at most
  `max_attempts` wasted relay ticks, not an unbounded one.

**Verified live**, not just via tests: before the fix, 0 of ~1,400 outbox
rows had `dispatched_at` set. After restarting the affected containers
with the fix, 1,317 rows drained within seconds and exactly the 100
rows that had already exceeded the new `max_attempts` cap were correctly
excluded and left pending (confirmed via direct SQL) — everything else,
including the golden-path conversation created via the web-chat WebSocket
during this investigation, flowed through end-to-end:
`GET /conversations` showed the real conversation, `GET .../messages`
showed the real inbound message, and a reply/status-change/internal-note
against it all worked exactly as the frontend expects. Regression tests
added: `tests/unit/test_guid_type.py` (asserts the exact-type behavior
directly, without needing a real asyncpg connection) and
`test_event_bus.py::test_a_permanently_failing_event_is_dead_lettered_after_max_attempts`
(simulates a permanently-failing row and asserts both that it stops being
reclaimed and that a healthy event behind it still gets relayed).

## Verification performed

9 new tests (SQLite/fakeredis-backed): outbox publish-then-claim
round-trip, claim-batch ordering/limit/exclusion-of-dispatched-rows
behavior, the relay's success path (marks dispatched, calls the injected
publish function with the right routing key) and failure path (increments
`attempts`, leaves the row claimable for retry) via a fake publish
function, the audit consumer's `handle_audit_event` pure-function mapping
(event in → correct `AuditLog` row out, including the "skip platform-level
events with no company" branch), and the realtime publisher's Redis
pub/sub round-trip. The existing M9 audit-log integration tests (6 tests)
were adapted to a `drain_outbox` fixture that runs the same claim →
`handle_audit_event` path a real consumer would, since audit rows are no
longer written synchronously in-request. 107 tests total passing across
the whole suite; `ruff check`/`mypy` clean. The actual RabbitMQ round-trip
(publish → topic exchange → bound queue → consumer delivery) is verified
manually against a real broker, the same bar M2/M3 used for the original
Celery/RabbitMQ wiring, since that integration isn't meaningfully
testable against SQLite/fakeredis.
