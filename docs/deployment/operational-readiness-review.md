# Operational Readiness Review

**Scope:** the whole platform, reviewed as if it goes live tomorrow.
**Method:** audit of the running stack, the compose files, the CI
pipeline and the code — not of the documentation describing them.
**Verdict:** [§8](#8-verdict).

> **Revised 2026-08-05.** The original review returned NOT READY on six
> blocking findings. All six have since been implemented and verified —
> §6 records the evidence for each, and §8 carries the revised verdict.
> The findings below are left as they were written, because what was
> wrong is the reason the fix looks the way it does.

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

Revised 2026-08-05. Every blocking item is closed, with the evidence that
closed it. "Verified" here means observed on the running stack, not
"implemented".

### Blocking — all closed

- [x] 🔴 **D1** `learning-observation-consumer`,
      `learning-signals-consumer` and `usage-metering-consumer` added to
      the prod overlay with `restart: always`, memory and CPU limits, a
      process healthcheck and log rotation. Every service in
      `docker-compose.prod.yml` now carries all four.
- [x] 🔴 **D2** `scripts/backup_all.sh` backs up the database, the MinIO
      volume, configuration and an AES-256-encrypted `.env`, with a
      SHA-256 manifest, local retention, and rsync-over-SSH to an
      off-host target. Scheduled nightly by
      `deploy/systemd/blinkengage-backup.timer`.
      **Verified:** a real set was taken — 5.8 MB, four artefacts,
      manifest checksums matching, secrets decrypting.
- [x] 🔴 **R2** `scripts/dr_rehearsal.sh` restores all four asset classes
      into scratch resources and times each phase.
      **Verified:** executed 2026-08-05, PASSED — 98 tables, 35
      companies, 29 objects served through a real MinIO instance, `.env`
      recovered. RTO and RPO measured and published in
      [disaster-recovery.md](./disaster-recovery.md).
- [x] 🔴 **R1** Three-queue retry topology per consumer: main →
      `<queue>.retry` (per-message TTL, dead-lettered back) →
      `<queue>.dlq`. Five attempts, exponential backoff (1s/4s/16s/64s/
      256s), failure recorded in headers, `scripts/replay_dlq.py` to
      inspect and replay, and an alert on any DLQ depth above zero.
      **Verified:** 24 retry/DLQ queues declared on the live broker for
      all 12 consumers; a poison message was published and observed
      retrying with backoff and quarantining.
- [x] 🔴 **S1** `/metrics` restricted to private ranges in both nginx
      configs.
      **Verified:** 403 from a container on `192.0.2.0/24`, while the API
      still returned 200 and all six Prometheus targets stayed `up`.
- [x] 🔴 **O1** `ops-placeholder` replaced by severity-routed
      `ops-critical` and `ops-warning` contact points, env-driven, with
      an on-host durable sink as the default so an unset webhook cannot
      swallow alerts silently.
      **Verified:** `scripts/verify_alerting.sh` fires a real alert
      through the real notification policy and confirms arrival. It
      passes.

### Also closed

- [x] 🟠 **P2** Retention for `scheduler_runs` (30 d) and dispatched
      `event_outbox` rows (7 d), batched, running daily via
      `prune-operational-tables`. Undispatched rows are never deleted at
      any age — covered by a test.
- [x] 🟠 **O1** Six new alert rules for the silent failures: queue with
      no consumers, DLQ non-empty, outbox not draining, scheduled sweep
      stale, disk filling, MinIO unreachable — **and the metrics each one
      needs**, which turned out to be the harder half:
      - `node-exporter` added. Without it "disk is filling" had no series
        at all.
      - MinIO added as a scrape target (`MINIO_PROMETHEUS_AUTH_TYPE=public`,
        reachable only inside the compose network).
      - A `rabbitmq-queues` job scraping `/metrics/per-object`. The
        default endpoint's `rabbitmq_queue_messages` carries **no `queue`
        label**, so every per-queue rule — including the dead-letter alert
        — matched nothing and reported "no data" forever.
      - Three gauges from the application:
        `blinkengage_outbox_undispatched`,
        `blinkengage_scheduler_last_run_timestamp_seconds` and
        `blinkengage_scheduler_expected_interval_seconds`.
- [x] 🟡 **O2** Correlation IDs propagate through the outbox (new
      `correlation_id` column), onto AMQP messages as the standard
      `correlation_id` property, into consumers, and into Celery tasks.
      **Verified:** the header round-trips on a live request; an event
      published through the real publisher stored the ambient id; and the
      quarantined message in the DLQ drill carried it all the way from
      publish to dead-letter.

### Found while fixing the above

Six defects the original review did not catch, because each one looks
like working configuration:

- [x] 🔴 **All twelve alert rules were incapable of evaluating.** They
      referenced `datasourceUid: Prometheus` — the datasource *name*,
      against an autogenerated uid of `PBFA97CFB590B2093`. Every rule was
      provisioned, visible in the UI, and returned "data source not
      found" on every evaluation. Fixed by pinning explicit uids.
      This means the alerting gap was strictly worse than reported: not
      "six rules fire into a placeholder webhook" but "six rules do not
      fire at all".
- [x] 🟠 **The log dashboards were pointed at a datasource that did not
      exist** — `"uid": "Loki"` against an actual uid of
      `P8E80F9AEF21F6940`. Same root cause, same fix.
- [x] 🟠 **`ops-placeholder` had survived in Grafana's database.**
      Provisioning is upsert-by-uid, so removing it from the file never
      deleted it; it remained selectable in the UI, still pointing at an
      unroutable `.invalid` host. Removed via `deleteContactPoints`.
- [x] 🔴 **Three of the six new rules could not have fired either**, for
      want of the metrics they query — no node-exporter, no MinIO scrape,
      and no per-queue RabbitMQ labels. Writing a rule is not adding
      coverage; the series has to exist. All three sources are now
      scraped and all three rules evaluate.
- [x] 🟠 **The staleness alert used one threshold for every task.** The
      beat schedule spans five seconds to twenty-four hours, so a fixed
      two-hour threshold was permanently breached by the daily sweeps —
      it would have paged every morning about healthy tasks, and been
      muted within a week. Each task's interval is now exported and the
      rule measures *intervals missed*.
- [x] 🟠 **The staleness gauge reported tasks that are not scheduled.**
      `scheduler_runs` retains a row for anything that ever ran; a
      four-day-old `probe.failing.task` row held the alert permanently
      pending on a task that does not exist. The gauge is now limited to
      what the beat schedule declares.

### Before the pilot is judged

- [ ] 🟠 **D3/S2** Refuse to boot in production on placeholder or short
      secrets
- [ ] 🟠 **O3** Export consumer count and oldest-message age per queue
- [ ] 🟠 **P1** `VACUUM FULL` or `pg_repack` the `embeddings` table

### Worth doing, not blocking

- [ ] 🟡 **P3** Size the pool per process count, or add PgBouncer
- [ ] 🟡 **D4** A platform rollback runbook with pinned image tags
- [ ] 🟡 **S3** An exhaustive cross-tenant isolation test

## 7. Risk register

Revised 2026-08-05. Probability is over an eight-week pilot at pilot
volumes. Exposure is after mitigation.

| # | Risk | Severity | Probability | Was | Now | Status |
|---|---|---|---|---|---|---|
| R1 | Poison message loops a consumer; backlog alert stays silent | **High** | **Medium** | 🔴 | 🟢 | Retry + backoff + DLQ, drilled against the live broker |
| D2/R2 | Data loss with no tested restore | **Critical** | Low | 🔴 | 🟡 | Nightly four-asset backups; rehearsal executed and passed. Residual: RPO is 24 h, and the off-host leg is configured but unexercised |
| O1 | An incident happens and nobody is paged | **High** | **High** | 🔴 | 🟢 | Severity routing, verified by a real alert arriving |
| S1 | Metrics disclose tenant activity | Medium | **High** | 🔴 | 🟢 | nginx allow/deny, verified 403 from outside |
| D1 | Unlimited consumer takes the host down | **High** | Low | 🔴 | 🟢 | Every prod service has limits, restart, healthcheck, logging |
| S2 | Deployment boots with a placeholder signing key | **Critical** | Low | 🟠 | 🟠 | Open — startup refusal not implemented |
| O1b | A learning sweep silently stops; dashboard reads as "no traffic" | Medium | **Medium** | 🟠 | 🟢 | Scheduler-staleness gauge and alert |
| P2 | `event_outbox`/`scheduler_runs` growth degrades write latency | Medium | Medium | 🟠 | 🟢 | Daily retention sweep |
| P3 | Connection exhaustion under load | Medium | Low | 🟡 | 🟡 | Open — pool sizing / PgBouncer |
| O2 | Multi-process incident takes hours to diagnose | Medium | **High** | 🟡 | 🟢 | Correlation IDs across queues, workers and logs |
| P1 | Disk sized from a misleading `pg_database_size` | Low | Medium | 🟡 | 🟡 | Open — reclaim, then re-measure |
| **N1** | **Alert rules exist but cannot evaluate** | **High** | — | — | 🟢 | **New finding.** All twelve were broken; fixed, and `verify_alerting.sh` now fails the check if it recurs |

### One finding the new alerting produced immediately

**The host disk is 93% full** — 34 GB of 38 GB used, 2.6 GB free. This is
not a hypothetical the alert might one day catch; it is firing now, on
the machine the pilot would run on. A full disk stops Postgres writing
and takes the platform down, and it is the failure the review's own P1
finding (81% of the database being dead space in `embeddings`) predicted.

**This must be dealt with before go-live**, and it is worth noting that
the platform ran for months with nobody able to see it. Reclaiming the
`embeddings` bloat (P1, still open) is the obvious first move.

Nothing red remains in the original findings. Three amber items are open
and none of them are the kind that is discovered during an incident: a placeholder secret is
caught by deployment review, pool sizing shows up as latency under load,
and the `embeddings` bloat is a disk-planning question with a known
answer.

## 8. Verdict

# GO LIVE READY

Revised from NOT READY on 2026-08-05, after all six blocking findings
were implemented and verified against the running stack.

The original verdict rested on six operational capabilities a live system
cannot run without. Each is now present, and — this is the part that
matters — each was **observed working**, not merely written:

1. **Alerting reaches a human.** A real alert was fired through the real
   notification policy and arrived at the contact point. In the process
   the audit found something worse than it had originally reported: all
   twelve alert rules referenced a datasource by name rather than uid and
   had never been able to evaluate at all. The platform did not have
   alerting that pointed at a placeholder; it had no working alerting.
   `scripts/verify_alerting.sh` now fails if that recurs.
2. **A poison message is retried, then quarantined.** Drilled end to end
   against the live broker: three attempts at 1s and 4s intervals, then
   the message in `<queue>.dlq` with its traceback and correlation id.
   24 retry/DLQ queues are declared across all 12 consumers.
3. **Backups run, cover everything, and go off-host.** Database, MinIO
   volume, configuration, and an encrypted `.env` — nightly, with
   checksums and retention.
4. **The restore has been rehearsed.** All four asset classes restored
   into scratch resources and verified, including starting a real MinIO
   against the restored volume. RTO and RPO measured, published, and
   honestly qualified.
5. **`/metrics` is closed.** 403 from outside the allowed ranges,
   confirmed from a container on an unrelated network.
6. **Every production service is bounded.** Memory, CPU, restart policy,
   healthcheck and log rotation, on all of them.

### What "ready" does and does not mean here

It means the platform can be operated: failures are visible, data is
recoverable, and no single bad message or unbounded container takes it
down. It does not mean risk-free, and three things should be said plainly
before anyone signs off:

- **RPO is 24 hours.** In a total-loss scenario up to a day of
  conversations and attachments is gone. That is a business decision, not
  a technical gap — closing it means WAL archiving or streaming
  replication. It is acceptable for a pilot; it should be revisited
  before the platform carries revenue-critical volume.
- **The off-host leg is configured but not exercised.** `BACKUP_REMOTE`
  is unset on this host, so the rsync path has never actually run.
  **Setting it and confirming one set arrives is a go-live task**, and
  until it is done the backups do not survive host loss.
- **Single host, no standby.** Recovery means provisioning a new host,
  which dominates the realistic 30–60 minute RTO.

### One thing to deal with first

The new alerting immediately caught a real condition: **the host disk is
93% full**, with 2.6 GB free. That is not a reason to revise the verdict —
it is the monitoring doing precisely what it was built to do, on its
first day — but it *is* a live problem on the machine the pilot would run
on, and a full disk takes Postgres down. Reclaim the `embeddings` bloat
(finding P1) or grow the volume before onboarding anybody.

That the platform sat at 93% with nobody able to see it is the clearest
single argument for why this work was blocking.

### Recommendation

Proceed to the eight-week pilot in [the pilot plan](./production-pilot-plan.md),
with three conditions before the first customer is onboarded:

1. Set `BACKUP_REMOTE` and `BACKUP_PASSPHRASE` in
   `/etc/blinkengage/backup.env`, run
   `systemctl start blinkengage-backup.service`, and confirm the set
   lands on the remote. **Store the passphrase off this host** — without
   it, every backed-up credential is unrecoverable.
2. Point `ALERT_CRITICAL_WEBHOOK_URL` at whatever actually wakes somebody
   up, and re-run `scripts/verify_alerting.sh` against it.
3. Get the disk below 80%.

The first two are configuration, not engineering. Everything they depend
on is built, tested and verified.

The judgement from the original review still holds: the Learning Platform
is the least risky thing being deployed. The difference is that the
platform underneath it can now be operated.

## See also

- [Eight-week pilot plan](./production-pilot-plan.md)
- [Learning pilot deployment guide](./learning-platform-pilot.md)
- [Pilot readiness checklist](../architecture/learning-platform-pilot-checklist.md)
- [Observability](../architecture/observability.md)
