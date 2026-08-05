# Operational Readiness Review

**Scope:** the whole platform, reviewed as if it goes live tomorrow.
**Method:** audit of the running stack, the compose files, the CI
pipeline and the code — not of the documentation describing them.
**Verdict:** [§8](#8-verdict).

Every finding below carries the evidence it came from. Where something
was measured, the measurement is quoted; where a capability is absent,
the absence was confirmed by looking, not inferred.

---

## 1. Deployment

### What is in place

| Area | State | Evidence |
|---|---|---|
| Images | Multi-stage, non-root (`USER blinkengage`), `HEALTHCHECK` in the image | `docker/backend/Dockerfile` |
| Compose | 30 services, `restart: unless-stopped` throughout | `docker-compose.yml` |
| Prod overlay | `restart: always`, CPU/memory limits per service | `docker-compose.prod.yml` |
| Health checks | Infra services all have them; `/health` and `/health/ready` on the API | `api/v1/endpoints/health.py` |
| TLS | Terminated at nginx, Let's Encrypt, ACME challenge path served | `docker/nginx/nginx.dev.conf` |
| Migrations | Alembic, single head, verified up → down → up on real PostgreSQL | phases 1–2 |
| CI | ruff, `mypy --strict`, pytest with coverage, tsc, vitest, image build | `.github/workflows/ci.yml` |

### D1 — Three services are missing from the production overlay 🔴

`docker-compose.prod.yml` covers 17 services. The base file has 30. The
gap includes **`learning-observation-consumer`, `learning-signals-consumer`
and `usage-metering-consumer`**.

Compose merges rather than replaces, so those containers still start —
but with `restart: unless-stopped` instead of `always`, and **with no
memory or CPU limit at all**. A leak in a learning consumer takes the
host down rather than being OOM-killed and restarted.

`usage-metering-consumer` is the one that should worry somebody most: it
is on the billing path.

**Fix:** add the three to the prod overlay with the same 0.5 CPU / 256 MB
shape as their peers. Ten minutes.

### D2 — Backups are scripted but never run 🔴

`scripts/backup_postgres.sh` is correct — pg_dump, gzip, timestamped,
prunes past `BACKUP_RETENTION_DAYS`. `scripts/restore_postgres.sh` and
`scripts/verify_backup_restore.sh` exist beside it.

**Nothing invokes any of them.** No cron, no systemd timer, no compose
service, no CI job. The only reference in the repo is a line in the CI
deploy notes telling a human to run it before deploying.

A backup procedure that depends on somebody remembering is not a backup
procedure.

**Also missing:** MinIO (attachments) has no backup at all. RabbitMQ is
durable-queue-only. There is no off-host copy of anything — `backups/` is
a directory on the same machine as the database.

**Fix:** a scheduled job, an off-host destination, and a restore rehearsal
whose result is recorded. Until then the RPO is *"since the last time
somebody remembered"* and the RTO is unknown.

### D3 — Secrets are environment variables with placeholder defaults 🟠

`.env.example` ships `JWT_SECRET_KEY=change-me-to-a-random-64-char-secret-…`
and `CREDENTIALS_ENCRYPTION_KEY=change-me-…`. There is no secret manager,
no rotation path, and nothing that refuses to start on a placeholder.

The naming is at least honest, and `CREDENTIALS_ENCRYPTION_KEY` is
correctly separate from the JWT secret. But a deployment that copies
`.env.example` and edits only the database URL boots with a known signing
key.

**Fix (cheap):** refuse to start in production when either key matches its
placeholder or is under 32 bytes. **Fix (proper):** a secret manager, and
a documented rotation procedure for the credentials key — which is the
harder one, because rotating it requires re-encrypting stored channel
credentials.

### D4 — Rollback is documented per-component, not as a procedure 🟡

Alembic down-migrations are verified for the Learning tables, and the
pilot deployment guide has a rollback section. There is no
platform-level runbook: no "we deployed at 14:00 and it is wrong" script,
no image pinning strategy in compose (`build:` rather than a tagged
image), no documented order for reverting API and workers together.

## 2. Operations

### What is in place

Prometheus scraping six jobs (backend, postgres, redis, rabbitmq, celery,
itself), Grafana with five provisioned dashboards
(backend-api, postgres, redis, rabbitmq-celery, logs), Loki + promtail
for logs, `celery-exporter` fed by `worker_send_task_events`.

Structured JSON logging throughout. A `SchedulerRun` record per sweep
plus, for Learning, its own `learning_runs` history.

### O1 — Six alert rules, and none of them page anybody 🔴

`docker/grafana/provisioning/alerting/rules.yml` defines exactly six:
5xx rate, p95 latency, PostgreSQL down, Redis down, RabbitMQ backlog,
Celery failure rate.

The contact point is named **`ops-placeholder`** and is a webhook. Nothing
is wired to a human.

Six rules is also thin for 30 services. Nothing alerts on: MinIO down,
disk filling, certificate expiry, a consumer that has stopped consuming
(as opposed to the queue backing up), the outbox relay stalling, a
scheduled sweep that stopped running, or replication lag.

**The gap that matters most for Learning:** a sweep that stops firing
produces *no* signal — no queue grows, no error is logged, and the
dashboard shows numbers that look like "no traffic" rather than "the
scheduler forgot". This was found in phase 1.5 on a stack where beat had
been up 41 hours. It is exactly the failure an alert should catch and no
alert covers.

### O2 — No request tracing 🟠

`core/correlation.py` exists and is good — a `ContextVar` carrying a
correlation ID so that everything caused by one action shares an
identifier. It is used by the billing and ledger services.

It is **not propagated into event consumers or Celery tasks**, and there
is no OpenTelemetry, no trace/span export, and no `X-Request-ID` header
on the API.

Consequence: a customer message arrives on a webhook, is persisted, is
routed, triggers an SLA clock, an AI reply and a usage record — across
five processes. There is no identifier tying those together. Debugging is
timestamp correlation across Loki, which stops working the moment two
things happen in the same second.

### O3 — Queue monitoring is depth-only 🟠

RabbitMQ is scraped and there is a backlog alert. What is not monitored:
**consumer count per queue** (a queue with zero consumers and zero
messages looks identical to a healthy idle queue), per-queue age of the
oldest message, and redelivery counts.

## 3. Performance

### What is measured

From phases 1.5 and 2.5, against real PostgreSQL:

| Metric | Value |
|---|---|
| Observation extraction | p50 0.040 ms, p99 0.108 ms |
| Observation assembly (with I/O) | p50 13.2 ms, p99 48.8 ms |
| Observation throughput | ~66/s single worker (~238 k/hour) |
| Clustering throughput | 444/s (~1.6 M/hour) |
| Storage per observation | 2.79 KB → 2.6 GiB per million conversations |
| Learning consumers at rest | 72 MB and 63 MB |
| Celery worker | 647 MB |

Learning is not a performance risk at any volume this platform can
currently produce. Clustering runs ~7× faster than the pipeline feeding
it.

### P1 — 81% of the database is dead space in one table 🟠

```
embeddings   164 MB   0 live tuples
(total database: 201 MB)
```

Zero live rows, zero dead tuples, last autovacuum 2026-08-04. The space
was allocated by pgvector verification work and **autovacuum cannot
return it** — only `VACUUM FULL` or `pg_repack` reclaims to the
filesystem.

Harmless at 201 MB. It becomes a capacity-planning problem the moment
somebody sizes a disk from `pg_database_size`, and an index-bloat problem
when embeddings are genuinely used.

### P2 — Three tables grow without any retention policy 🟠

| Table | Rows | Retention |
|---|---|---|
| `scheduler_runs` | 22 651 | **None** |
| `event_outbox` | 3 535 | **None** — the repository has no delete at all |
| `audit_logs` | 1 565 | None (correct — audit is meant to be kept) |

`scheduler_runs` grows at roughly one row per sweep per schedule. With
the current beat schedule that is on the order of a million rows a year,
for telemetry whose value is entirely in its recent tail.

`event_outbox` retaining dispatched rows forever is the more serious of
the two: it is on the write path of every domain event, and its
`ix_event_outbox_undispatched` partial index stays small but the heap
does not.

Memory's confidence history *does* have a retention window
(`memory_confidence_history_days`), so the pattern exists in the codebase
— it simply was not applied here.

### P3 — Connection pool is sized for one API process 🟡

`database_pool_size: 10`, `max_overflow: 20` — 30 connections per
process. With one API container, thirteen consumers and a Celery worker
each holding their own engine, a default PostgreSQL `max_connections` of
100 is reachable under load. No PgBouncer.

## 4. Reliability

### R1 — A poison message loops forever 🔴

```python
async with message.process(requeue=True):
    await handler(message)
```
— `infrastructure/events/rabbitmq.py`

Every consumer on the platform uses this. A handler that raises requeues
the message, which is redelivered, which raises again. **There is no
dead-letter exchange** (`grep x-dead-letter` returns nothing), no
redelivery cap, and no poison-message quarantine.

One malformed event — a schema change, a null nobody expected, a row
deleted between publish and consume — puts a consumer into a hot loop
that burns CPU, floods logs, and blocks every message behind it. The
queue does not grow (the message is being consumed), so the **backlog
alert never fires**.

The asymmetry is stark and worth stating plainly: the *outbound* path is
protected — `relay.py` counts attempts and dead-letters past
`max_attempts`, with the event left visible and its error recorded. The
*inbound* path has none of that.

**Fix:** declare queues with `x-dead-letter-exchange`, cap redeliveries,
and alert on the DLQ. This is the single highest-value reliability change
available.

### What is genuinely strong

- **Idempotency.** Observations are unique on
  `(source_id, pipeline_version)`; cluster membership on
  `(cluster_id, observation_id)`; clusters on
  `(company_id, algorithm_version, signature)`. Measured: replaying 5 000
  observations created 0 rows and wrote 0 bytes.
- **Replay.** `pipeline_version` produces parallel generations rather
  than overwriting, so a bad extractor is recoverable. Exercised for real
  on the v1 → v2 bump.
- **Transactional outbox.** Events are written in the same transaction as
  the state change, so a crash between them is impossible.
- **Crash recovery.** Every sweep claims work by elapsed time rather than
  by a flag, so a worker killed mid-batch leaves nothing stuck. Sweeps
  are idempotent and re-run cleanly.
- **Derived data.** All eight Learning tables are rebuildable from
  conversations, which makes their rollback genuinely safe.

### R2 — No disaster recovery plan 🔴

There is no documented RTO or RPO, no tested restore, no off-host backup,
and no runbook for "the database is gone". `verify_backup_restore.sh`
exists but has no recorded execution.

This is the same finding as D2 seen from the other side, and it is listed
twice deliberately: one is a missing job, the other is a missing plan.

## 5. Security

### What is in place — and it is the strongest area

- **RBAC** with a closed permission set, defaults per system role, and a
  test asserting every permission is known.
- **Tenant isolation enforced structurally.** Learning's repositories
  take `company_id` on every method — there is no method that can be
  called without one. Cluster signatures are company-scoped, so two
  tenants converging on identical vocabulary cannot collide.
- **AST guards** that fail the build: only `MemoryManager` writes memory,
  only Learning writes `learning_*`, Learning publishes no findings,
  Learning imports no other context's writer, Learning imports no model
  provider.
- **Audit trail** fed by the event bus (`#` binding), now including
  threshold changes with old and new values.
- **Rate limits** on login, register, AI endpoints, search and channel
  tests.
- **Credentials encrypted at rest** with a key separate from the JWT
  secret.
- **Docs disabled in production** (`docs_url=None` when
  `is_production`).
- **Non-root containers.**

### S1 — `/metrics` is publicly reachable 🔴

```nginx
location /metrics {
    proxy_pass $backend_upstream;
}
```

No `allow`/`deny`, no auth, no network restriction. Prometheus metrics
from a multi-tenant platform disclose endpoint inventory, request volumes,
error rates and latency distributions — and with per-tenant label
cardinality, they can disclose which tenants are active and how busy.

**Fix:** `allow` the monitoring network and `deny all`. One line.

### S2 — Placeholder secrets can boot 🟠

See D3. Listed under security as well because the consequence is
different here: a known JWT signing key means forgeable sessions for
every tenant.

### S3 — No cross-tenant isolation test for the API surface as a whole 🟡

Learning has one (two companies, identical vocabulary, separate
clusters). Memory has one. There is no *platform-wide* test that walks
every authenticated endpoint with a second tenant's identifiers and
asserts 404/403 — so isolation rests on every endpoint having remembered
to scope, verified per-endpoint rather than exhaustively.

## 6. Production checklist

Ordered so that anything marked 🔴 blocks go-live.

### Blocking

- [ ] 🔴 **D1** Add `learning-observation-consumer`,
      `learning-signals-consumer`, `usage-metering-consumer` to the prod
      overlay with restart policy and resource limits
- [ ] 🔴 **D2** Schedule `backup_postgres.sh`; add an off-host
      destination; back up MinIO
- [ ] 🔴 **R2** Run `verify_backup_restore.sh` against a real dump and
      record the result; publish an RTO and RPO
- [ ] 🔴 **R1** Declare dead-letter exchanges; cap redeliveries; alert on
      DLQ depth
- [ ] 🔴 **S1** Restrict `/metrics` to the monitoring network
- [ ] 🔴 **O1** Replace `ops-placeholder` with a real contact point and
      confirm one alert reaches a human

### Before the pilot is judged

- [ ] 🟠 **D3/S2** Refuse to boot in production on placeholder or short
      secrets
- [ ] 🟠 **O1** Add alerts: consumer count zero per queue, sweep not run
      within N intervals, outbox undispatched age, disk usage,
      certificate expiry
- [ ] 🟠 **P2** Retention for `scheduler_runs` and dispatched
      `event_outbox` rows
- [ ] 🟠 **O3** Export consumer count and oldest-message age per queue
- [ ] 🟠 **P1** `VACUUM FULL` or `pg_repack` the `embeddings` table

### Worth doing, not blocking

- [ ] 🟡 **O2** Propagate the correlation ID into consumers and Celery;
      add `X-Request-ID`
- [ ] 🟡 **P3** Size the pool per process count, or add PgBouncer
- [ ] 🟡 **D4** A platform rollback runbook with pinned image tags
- [ ] 🟡 **S3** An exhaustive cross-tenant isolation test

## 7. Risk register

Probability is over an eight-week pilot at pilot volumes.

| # | Risk | Severity | Probability | Exposure | Mitigation |
|---|---|---|---|---|---|
| R1 | Poison message loops a consumer; backlog alert stays silent | **High** | **Medium** | 🔴 | DLQ + redelivery cap + DLQ alert |
| D2/R2 | Data loss with no tested restore | **Critical** | Low | 🔴 | Scheduled off-host backups; rehearsed restore |
| O1 | An incident happens and nobody is paged | **High** | **High** | 🔴 | Real contact point; the six rules already exist |
| S1 | Metrics disclose tenant activity | Medium | **High** | 🔴 | nginx allow/deny |
| D1 | Unlimited consumer takes the host down | **High** | Low | 🔴 | Prod overlay entries |
| S2 | Deployment boots with a placeholder signing key | **Critical** | Low | 🟠 | Startup refusal |
| O1b | A learning sweep silently stops; dashboard reads as "no traffic" | Medium | **Medium** | 🟠 | Alert on `learning_runs` staleness |
| P2 | `event_outbox`/`scheduler_runs` growth degrades write latency | Medium | Medium | 🟠 | Retention sweep |
| P3 | Connection exhaustion under load | Medium | Low | 🟡 | Pool sizing / PgBouncer |
| O2 | Multi-process incident takes hours to diagnose | Medium | **High** | 🟡 | Correlation propagation |
| P1 | Disk sized from a misleading `pg_database_size` | Low | Medium | 🟡 | Reclaim, then re-measure |

**The three that would most change the risk profile**, in order: a real
contact point (O1) because it converts every other failure from silent to
noticed; dead-lettering (R1) because it is the one failure mode that
actively hides itself; and a tested restore (D2/R2) because it is the only
one that is unrecoverable.

## 8. Verdict

# NOT READY

Not because the platform is unsound — the application-layer engineering
is strong, and the parts that are hardest to retrofit (tenant isolation,
idempotency, replay safety, the audit trail, the structural guards) are
the parts that are done well.

It is not ready because **six operational capabilities that a live system
cannot run without are absent**, and four of them are absent in ways that
would be discovered during the incident rather than before it:

1. **Nobody gets paged.** Six alert rules fire into a placeholder webhook.
2. **Backups have never run and a restore has never been tested.** The
   scripts are correct; nothing invokes them; there is no off-host copy.
3. **A poison message loops forever, silently.** No dead-lettering
   anywhere on the inbound path, and the failure produces no alert
   because the queue does not grow.
4. **`/metrics` is public.**
5. **Three services, one of them on the billing path, run in production
   with no resource limit.**
6. **No tested disaster recovery, and no stated RTO or RPO.**

None of these is a large piece of work. Items 1, 4 and 5 are
configuration changes measured in minutes. Item 3 is a queue declaration
and a handler change. Items 2 and 6 are a scheduled job plus one rehearsal
whose result gets written down.

**What that adds up to:** roughly two to three days of operational work,
none of it in the application, followed by one rehearsal. That is the
distance between here and GO LIVE READY.

**Recommendation:** clear the six blocking items, then run the eight-week
pilot in [the pilot plan](./production-pilot-plan.md). The Learning
Platform itself is the *least* risky thing being deployed — it is
read-only, it emits nothing, and its resource profile is measured and
flat. The risk is the platform underneath it.

## See also

- [Eight-week pilot plan](./production-pilot-plan.md)
- [Learning pilot deployment guide](./learning-platform-pilot.md)
- [Pilot readiness checklist](../architecture/learning-platform-pilot-checklist.md)
- [Observability](../architecture/observability.md)
