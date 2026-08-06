# Operational Runbooks

Step-by-step procedures for common operational tasks. Every command
assumes you're in the repository root with the stack already up
(`docker compose ps` shows services running). See
`docs/deployment/production.md` for first-time bring-up and
`docs/deployment/disaster-recovery.md` for incident response.

## Restart a single service

```bash
docker compose restart <service>
```

Config files mounted read-only (nginx confs, Prometheus/Grafana/Promtail
configs) are **not** picked up by a plain container restart if they were
edited on the host after the container last started for services that
read them only at process startup — this is true for all of them here.
A `restart` is sufficient; a rebuild (`up -d --build <service>`) is only
needed when the service's own *code* (not just a mounted config file)
changed.

## Rebuild after a code or dependency change

```bash
docker compose up -d --build <service> [<service> ...]
```

Rebuilding `backend` does **not** automatically rebuild `celery-worker`/
`celery-beat`/the event-bus consumers even though they share the same
Dockerfile — each is built independently by Compose. After any
`backend/pyproject.toml` dependency change or shared-module code change,
rebuild every backend-derived service:

```bash
docker compose up -d --build backend celery-worker celery-beat \
  audit-log-consumer conversation-ingest-consumer workflow-engine-consumer \
  notification-consumer reporting-consumer erp-sync-consumer
```

## Apply a new migration manually

Migrations run automatically on every `backend`/`celery-*`/consumer
container start (`docker/backend/entrypoint.sh`, Postgres-advisory-lock
serialized — safe even if multiple containers race to start
simultaneously). To apply one without restarting anything:

```bash
docker compose exec backend alembic upgrade head
```

To check the currently-applied revision vs. what's on disk:

```bash
docker compose exec backend alembic current
docker compose exec backend alembic heads
```

## Roll back a migration

```bash
docker compose exec backend alembic downgrade -1   # one step
docker compose exec backend alembic downgrade <revision>
```

Every migration in this codebase has a working `downgrade()` — verified
at the time it was written (see each migration's own commit/PR) — but
always take a backup first for anything beyond a same-day rollback:

```bash
./scripts/backup_postgres.sh
```

## Scale backend replicas

```bash
docker compose up -d --scale backend=3
```

nginx's dynamic-DNS re-resolution (`docker/nginx/nginx.*.conf`) picks up
new replicas within `resolver ... valid=10s` — no nginx restart needed.
See `docs/architecture/observability.md` for the honest characterization
of what this load-balancing does and doesn't guarantee.

## Investigate a stuck/backed-up queue

1. Check the RabbitMQ management UI (`http://localhost:15672` in dev —
   not exposed in the prod overlay by default) or query Prometheus:
   `rabbitmq_queue_messages_ready{queue="<name>"}`.
2. Check the Grafana "RabbitMQ & Celery" dashboard for queue depth and
   Celery task failure rate together — a backlog with a high failure
   rate usually means the consumer is crash-looping on a poison message;
   a backlog with a low failure rate usually means under-provisioned
   consumers.
3. Check the relevant consumer's logs:
   ```bash
   docker compose logs <consumer-service> --tail 200
   ```
4. A poison message no longer blocks its queue. Consumers retry with
   exponential backoff (1s, 4s, 16s, 64s, 256s) and quarantine into
   `<queue>.dlq` after 5 attempts, so a backlog is a throughput problem
   and a *failing* message shows up in a dead-letter queue instead. See
   "Drain a dead-letter queue" below.

## Rotate the JWT signing secret

Rotating `JWT_SECRET_KEY` invalidates **every** currently-issued access
and refresh token immediately — every logged-in user is forced to log
in again. There is no dual-key grace period built in today (a real gap
for a zero-downtime rotation; flagged for a future milestone if
needed). Procedure:

1. Update `JWT_SECRET_KEY` in `.env`.
2. `docker compose up -d --build backend celery-worker celery-beat` (and
   every consumer, per "Rebuild after a code or dependency change"
   above — any process that calls `decode_token`/`create_token` needs
   the new value).
3. Communicate the forced re-login to users ahead of time if possible.

## Rotate the credentials encryption key

`CREDENTIALS_ENCRYPTION_KEY` encrypts `ChannelConfig`/`ErpConfig`
credentials at rest (`infrastructure/security/crypto.py`). Rotating it
requires re-encrypting every existing row — a plain key swap makes
every stored credential permanently undecryptable. Procedure:

1. Take a backup (`./scripts/backup_postgres.sh`) — this is a
   data-migrating operation, not a config change.
2. Write a one-off script that, using the **old** key, decrypts every
   `ChannelConfig.credentials`/`ErpConfig.credentials` row, then
   re-encrypts with the **new** key and writes it back — inside a single
   transaction per row.
3. Only after every row is confirmed re-encrypted, update
   `CREDENTIALS_ENCRYPTION_KEY` in `.env` and restart `backend` (and any
   consumer that decrypts credentials — currently `erp-sync-consumer`
   via `build_erp_client`, and `conversation-ingest-consumer`/`backend`
   via `ChannelProviderFactory`).
4. Run `./scripts/verify_backup_restore.sh` afterward as a sanity check
   that the database is in a consistent, restorable state.

This isn't scripted today (no real key-rotation need has arisen yet) —
write the actual script when this is first needed, following the shape
above, and consider committing it to `scripts/` at that point.

## Check overall system health at a glance

```bash
curl -s http://localhost:8000/api/v1/health/ready | python3 -m json.tool
```

Or the Grafana "Backend API" dashboard for request rate/latency/error
rate, plus the Postgres/Redis/RabbitMQ & Celery dashboards for
dependency health — see `docs/architecture/observability.md`.

---

## Drain a dead-letter queue

Every consumer has one. A message that fails five times, spread over
about five minutes of backoff, is quarantined into `<queue>.dlq` with the
failure in its headers rather than retried forever. The
"Messages in a dead-letter queue" alert fires on any depth above zero,
because a quarantined message is always something a human decided
nothing about yet.

**1. See what is quarantined, and where.**

The broker's AMQP port is deliberately not published, so this runs
inside the Docker network rather than on the host:

```bash
docker compose run --rm --no-deps --entrypoint python \
  -v "$PWD/scripts:/ops:ro" backend /ops/replay_dlq.py list
```

**2. Find out why.** Non-destructive — messages are read and put back.

```bash
docker compose run --rm --no-deps --entrypoint python \
  -v "$PWD/scripts:/ops:ro" backend /ops/replay_dlq.py inspect conversation-ingest
```

Each message shows its attempt count, the exception, the tail of the
traceback, and the correlation id. **Use that correlation id** to pull
the originating request out of Loki:

```
{job="blinkengage"} |= "<correlation-id>"
```

That gives the whole story — the API request, the outbox write, the
relay, and the consumer failure — as one thread.

**3. Fix the cause.** Genuinely fix it. Replaying into a dependency that
is still broken just refills the queue, slowly.

**4. Replay.**

```bash
docker compose run --rm --no-deps --entrypoint python \
  -v "$PWD/scripts:/ops:ro" backend /ops/replay_dlq.py replay conversation-ingest
```

Replayed messages get a fresh retry budget, so anything still broken
re-quarantines rather than spinning. Past 25 messages the tool requires
`--yes`.

**If a message should never be processed** — a malformed event from a
since-fixed bug — purge that queue in the RabbitMQ management UI rather
than replaying. Note what was discarded and why, in the incident record.

## Take a backup by hand

Nightly at 02:30 UTC via `blinkengage-backup.timer`. To take one now —
before a risky migration, say:

```bash
sudo systemctl start blinkengage-backup.service
journalctl -u blinkengage-backup.service -n 40 --no-pager
```

Or directly, which is also how to take one on a host where the timers are
not installed:

```bash
BACKUP_PASSPHRASE=<passphrase> ./scripts/backup_all.sh
```

Each set contains the database, the MinIO volume, configuration, and an
encrypted `.env`, plus a `MANIFEST` of SHA-256 checksums, the git commit
and the Alembic head.

**Check it went off-host.** Without `BACKUP_REMOTE` set, the run says so
loudly and the set exists only on this host — which does not survive the
failure backups are for:

```bash
grep -E '^BACKUP_REMOTE=' /etc/blinkengage/backup.env
```

## Check backups are actually running

The failure mode is silence: a timer that stopped firing produces no
error and no alert of its own.

```bash
systemctl list-timers 'blinkengage-*' --no-pager
systemctl is-failed blinkengage-backup.service
ls -lt backups/ | head
```

The most recent set should be less than 24 hours old. If it is not, read
`journalctl -u blinkengage-backup.service` before assuming the data is
safe.

## Verify alerts still reach a human

Run before go-live, after any change to the alerting provisioning or the
webhook secrets, and after any recovery.

```bash
./scripts/verify_alerting.sh
```

It fires a real alert through the real notification policy and confirms
it arrives — not a config check. It also fails on a rule that cannot
evaluate, which is the quiet failure worth catching: a rule that is
provisioned and visible but references a datasource that does not resolve
looks exactly like working coverage.

Alerts route by severity: `critical` → `ops-critical` (repeating hourly
until acted on), everything else → `ops-warning`. Both default to the
on-host `alert-sink` container, which logs each one where Promtail picks
it up for Loki. Point them at Slack or PagerDuty by setting
`ALERT_CRITICAL_WEBHOOK_URL` and `ALERT_WARNING_WEBHOOK_URL` in `.env`.

To read what was delivered:

```bash
docker compose logs alert-sink --tail 20
```

Or in Loki, alongside everything else:

```
{container="blinkengage-alert-sink-1"} |= "critical"
```

## Trace one request across the whole platform

Every request carries a correlation id (`X-Correlation-ID`, generated if
absent). It propagates into the outbox row, onto the AMQP message as its
standard `correlation_id` property, into the consumer that handles it,
and into the Celery task id for scheduled work.

```
{job="blinkengage"} |= "<correlation-id>"
```

A quarantined message carries the same id in its DLQ headers, which is
what connects "this event failed" back to "this customer did this thing".

## Restore a backup

See [disaster-recovery.md](disaster-recovery.md) — full procedure,
measured RTO/RPO, and the rehearsal script.

Quick check that the latest backup is restorable, without touching
production:

```bash
./scripts/verify_backup_restore.sh
```

Full rehearsal of all four asset classes:

```bash
BACKUP_PASSPHRASE=<passphrase> ./scripts/dr_rehearsal.sh
```
