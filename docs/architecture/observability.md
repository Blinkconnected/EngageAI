# Observability & DevOps

M27 of the roadmap, continuing Phase 6 (Hardening & Launch). Extends the
Prometheus/Grafana/Loki/Promtail stack that's existed since early in this
build with Celery metrics, real dashboards, alerting, a genuine
dependency-aware readiness probe, automated backups with a verified
restore drill, and GitHub Actions CI/CD — plus a serious concurrency bug
this milestone's own verification work surfaced and fixed.

## A real bug found while verifying the stack, not by design

While checking that the new Celery metrics pipeline actually reported
data, the live `celery-worker` logs showed a recurring
`RuntimeError: ... attached to a different loop` on **every** periodic
task (`relay-event-outbox`, `check-sla-breaches`, `poll-email-imap`,
`dispatch-notification-emails`) — 50+ occurrences in three minutes. This
was a real, systemic bug, not a scan artifact: every one of these four
Celery-beat tasks caches its `AsyncEngine`/`async_sessionmaker` at module
level (created once per worker process, intentionally — avoiding
reconnecting to Postgres on every 5-second relay tick), but each task
invocation calls `asyncio.run(...)`, which creates a **brand-new event
loop every time**. An asyncpg connection is bound to the event loop that
opened it; when SQLAlchemy's `pool_pre_ping` tried to reuse a connection
pooled during a *previous* invocation's (now-closed) loop from inside a
*new* invocation's loop, it crashed instead of gracefully reconnecting —
pre_ping recovers from "the connection died," not "the connection
belongs to a different event loop entirely."

Fixed identically in all four task modules
(`infrastructure/events/relay.py`, `infrastructure/tasks/sla_sweep_task.py`,
`infrastructure/tasks/email_imap_poll_task.py`,
`infrastructure/tasks/notification_email_dispatch_task.py`): each task's
async body now disposes its cached engine's connection pool in a
`finally` block before returning. `engine.dispose()` closes pooled
connections but not the lightweight `AsyncEngine`/`async_sessionmaker`
Python objects themselves, so the *next* invocation's `_get_session_
factory()` call still takes the "already cached, reuse it" branch (no
extra reconnect overhead on the hot path) — it just opens fresh
connections against the *current* loop instead of trying to resurrect
one from a dead loop. Verified against the real running stack: zero
occurrences of the error across a 130-second window covering all four
task types, versus 50+ in three minutes beforehand. The consumers
(`audit_log_consumer.py`, `conversation_ingest_consumer.py`, etc.) were
never affected — each calls `asyncio.run(main())` exactly once for the
entire process lifetime (one long-lived loop, not one per message), so
there's no cross-loop reuse to go wrong.

## Prometheus: Celery metrics closing the last exporter gap

Postgres/Redis/RabbitMQ were already scraped (`postgres-exporter`,
`redis-exporter`, RabbitMQ's built-in Prometheus plugin). Celery itself
had no exporter. Added `celery-exporter` (danihodovic/celery-exporter),
which listens to the Celery event stream on the same broker every
worker/beat already uses — zero code changes needed in any task, only
two new Celery config flags (`worker_send_task_events`,
`task_send_sent_event`) so the broker actually carries those events in
the first place; without them, Celery never publishes task lifecycle
events at all and the exporter's `/metrics` stays permanently empty.
Verified end-to-end: `celery events --dump` inside the worker container
confirmed events flow, and `celery_task_succeeded_total`/`celery_task_
runtime_bucket`/etc. are queryable in Prometheus.

## Grafana: from one dashboard to five, plus real alerting

Provisioning (datasources, dashboard auto-loading) already existed and
was solid; only one dashboard (Backend API) existed. Added four more —
PostgreSQL, Redis, RabbitMQ & Celery, and Logs (a Loki-backed log-volume-
by-level panel plus a live error/critical tail) — using each exporter's
own standard, documented metric names (`pg_up`, `redis_connected_
clients`, `rabbitmq_queue_messages_ready`, `celery_task_failed_total`,
...), all verified against the real running Prometheus (`/api/v1/query`
confirmed every metric name resolves to real series before it went into
a dashboard).

Alerting used **Grafana's built-in unified alerting** (provisioned via
`docker/grafana/provisioning/alerting/`), not a separate Alertmanager
container — simpler for a single-Grafana-instance deployment, and this
platform doesn't run multiple Grafana replicas needing Alertmanager's
clustering. Six rules: high 5xx rate (>5%), high p95 latency (>2s),
Postgres down, Redis down, RabbitMQ queue backlog (>1000 ready messages
for 10+ minutes), and Celery task failure rate. All six were confirmed
actually loaded via Grafana's provisioning API
(`/api/v1/provisioning/alert-rules`) after a real restart, not just
"the YAML looks right." The contact point is a **deliberate,
obviously-fake placeholder webhook** (`ops-placeholder`,
`https://ops-placeholder.invalid/...`) — which Slack channel, PagerDuty
key, or email address should receive these is a business/operational
decision this codebase can't make on its own; rules and routing are
fully wired, so plugging in a real destination later is a one-line
change, not a re-architecture.

## Loki/Promtail: log-level labels, safely

`core/logging.py` emits JSON in production/staging, plain colored text
in development. Added `pipeline_stages` to `promtail-config.yml`
extracting only `level` as an indexed Loki label (5 possible values:
debug/info/warning/error/critical) — deliberately **not** promoting
`logger` (roughly 90 distinct module names) to a label, since Loki's own
guidance is that label cardinality directly drives its storage/query
cost; `logger`/`event`/everything else stays queryable via LogQL's
`| json` at query time without being indexed. The JSON parse stage fails
silently (a documented, safe Promtail behavior) on development's
non-JSON lines, so this is safe to ship unconditionally rather than
needing environment-specific promtail configs.

## Readiness probe: now actually reflects dependency health

`GET /api/v1/health` (liveness) is unchanged — "the process is up,"
nothing more. `GET /api/v1/health/ready` previously checked only
Postgres; now checks Postgres, Redis, and RabbitMQ, returning 503 with a
per-dependency breakdown (`{"status": "degraded", "database": "ok",
"redis": "ok", "rabbitmq": "unreachable"}`) the moment any one of them
is unreachable, each bounded by a 3-second timeout so a hung dependency
can't hang the health check itself. The `backend` service's Docker
healthcheck now points at `/health/ready` instead of the old plain
liveness check — meaningful for a load-balanced pool (see below), since
an orchestrator/load balancer should stop routing traffic to a replica
whose database connection is down even if the process itself is still
technically alive.

## nginx: load distribution, and closing a public metrics leak

Both `nginx.dev.conf` and `nginx.prod.conf` already used a `resolver` +
variable `proxy_pass` (`http://backend:8000`), forcing re-resolution
against Docker's embedded DNS every 10 seconds rather than resolving
once at startup and caching forever. This is a real, if coarse-grained,
load-distribution mechanism for `docker compose up --scale backend=N`:
Docker's embedded DNS round-robins the order of returned addresses on
each query specifically to support this kind of naive load balancing, so
new upstream connections opened after each re-resolution window can land
on a different replica. It is **not** per-request load balancing the way
an `upstream {}` block with multiple `server` entries gives on a static
topology — a real limitation of open-source nginx (no Plus) combined
with Docker Compose's dynamic replica IPs, worth naming honestly rather
than overclaiming. For stronger guarantees at real scale, the documented
next step is a real orchestrator (Kubernetes Service/Ingress) or nginx
Plus's dynamic upstream module — out of scope here.

Found and fixed one real gap while reviewing this: `nginx.prod.conf`'s
`/metrics` location proxied straight through with **no access
restriction at all**, publicly exposing per-endpoint request-rate/
latency data to the internet. Prometheus itself never needed this route
(it scrapes `backend:8000/metrics` directly over the internal Docker
network) — it only existed for manual operator convenience. Restricted
to private IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
loopback) with `deny all` otherwise. Left open in `nginx.dev.conf`,
where it's a local-only concern.

## Request latency: two timings in the access log, and per-query stats

Both nginx configs previously logged with the stock `main` format, which
records that a request happened but not how long it took. Combined with
`pg_stat_statements` not being loaded, that left no server-side evidence
for a latency complaint — the access log could not distinguish a slow
endpoint from a fast one, and the database could not name its slowest
query. Diagnosing "the app feels slow" meant reasoning from request
counts alone.

`docker/nginx/logging.conf` now defines a `timed` format, used by every
server block in both configs, appending two fields:

- `rt=$request_time` — wall-clock time nginx spent on the request, from
  the first client byte read to the last byte written. This is what the
  user actually waited.
- `urt=$upstream_response_time` — time the backend alone took, excluding
  nginx overhead and transfer over the client's link.

Logging both is the point: a large `rt` beside a small `urt` means the
application is fine and the client link (or a slow upload) is the cost,
while the two rising together means the backend is genuinely slow. One
number cannot separate those cases, and picking only `$request_time`
would have made every mobile-network user look like a backend problem.

The filename prefix is load-bearing. The stock `nginx.conf` pulls in
`conf.d/*.conf` as a sorted glob, so the file is mounted (dev) and
`COPY`d (prod) as `00-logging.conf` — it must be parsed before
`default.conf`, or the server blocks reference an undefined `log_format`
and nginx refuses to start. The prod overlay clears the nginx service's
volumes (`!override []`), which is why the prod path uses a `COPY` in
`docker/nginx/Dockerfile` rather than relying on the compose mount.

On the database side, `shared_preload_libraries=pg_stat_statements` is
set on the `postgres` service with `track=all` (so statements inside
PL/pgSQL functions are counted too, not just top-level ones) and
`max=5000`. This cannot be enabled at runtime — `shared_preload_libraries`
is read only at server start — so it lives in the compose command rather
than a migration, and **enabling it requires a PostgreSQL restart**, which
drops every open connection. The extension itself is then created once
with `CREATE EXTENSION IF NOT EXISTS pg_stat_statements`.

Both changes are measurement only: no request is served differently, and
the cost is a few MB of shared memory plus per-statement bookkeeping.

## Automated backups + a real restore drill

`scripts/backup_postgres.sh` — `pg_dump` (plain SQL, gzip-compressed,
timestamped) via `docker compose exec`, with configurable retention
pruning (`BACKUP_RETENTION_DAYS`, default 14). `scripts/restore_
postgres.sh` — restores a given backup, requiring a typed confirmation
of the target database name unless `--force`, and supports `--target-db`
for restoring into a database other than the real one.
`scripts/verify_backup_restore.sh` is the actual "restore drill" the
roadmap names: restores the most recent backup into a throwaway scratch
database, runs sanity checks (`companies` row count, a non-empty
`alembic_version`), then drops the scratch database — proving a backup
is genuinely restorable without ever touching real data. All three were
run against the real live stack as part of this milestone's own
verification, not just written and assumed to work: a real backup was
taken, a real restore drill passed, and the restore script itself was
exercised (into a disposable `--target-db`, never the real database).

## GitHub Actions CI/CD

`.github/workflows/ci.yml` (the directory existed but was completely
empty before this milestone) — seven jobs: backend lint (ruff + mypy),
backend test (pytest — no service containers needed, since the entire
suite runs against in-memory SQLite/fakeredis per `tests/conftest.py`;
real-broker/real-Postgres behavior is this codebase's own
manually-verified-against-docker-compose bar, established since M10),
frontend lint (eslint/prettier/tsc), frontend test (vitest), a Docker
build job for both the backend and nginx+SPA images, a Trivy image
vulnerability scan (advisory, non-blocking — matching `pip-audit`'s own
non-blocking treatment in `docs/security/hardening.md`), and a
**documented placeholder** deploy job gated on version tags. The deploy
job intentionally does not deploy anywhere: a real target (cloud
provider, host, registry credentials) is an infrastructure/business
decision, not something to fabricate. Every step a real deploy would
take is named in comments, pointing at `docs/deployment/production.md`.

## Verification performed

No new test files this milestone — the existing readiness test in
`tests/integration/test_health_api.py` was updated in place to cover the
richer, dependency-aware response shape (still 513 passing overall).
The Celery-task concurrency fix, the Prometheus/Grafana/Loki/alerting
wiring, the backup/restore scripts, and the CI workflow are all
infra-layer changes verified directly against the real running stack
rather than through new pytest coverage — no automated test can exercise
real asyncpg connection-pool/event-loop interaction the way the
concurrency bug actually manifested, and Grafana/Prometheus provisioning
correctness is only meaningfully verified against a real instance.
`ruff check`/`ruff format --check`/`mypy src` all green:

- `tests/integration/test_health_api.py` — the readiness endpoint now
  covers the genuine "degraded" path (no real RabbitMQ broker runs in
  the test process, so this doubles as verifying the 503 status code
  and per-dependency breakdown organically, not via a mock).

Manually verified against the real docker-compose stack: all Prometheus
scrape targets up (including the new `celery` job), all 6 Grafana alert
rules and the contact point/notification policy loaded via Grafana's
provisioning API, all 5 dashboards present, Celery task metrics flowing
end-to-end (`celery events --dump` confirmed events on the broker,
Prometheus confirmed non-zero series), both nginx configs pass `nginx
-t`, a real backup taken and a real restore drill passed, and the
restore script itself exercised against a disposable scratch database.
`docker-compose.yml` gained the new `celery-exporter` service — like
every other exporter/observability service (`postgres-exporter`,
`redis-exporter`, `prometheus`, `grafana`, `loki`, `promtail`), it needs
no `docker-compose.prod.yml` override at all, since none of those are
dev-only either; the base file's definition already applies in both
environments unchanged.
