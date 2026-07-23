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
4. If a specific message is poison (repeatedly failing and blocking the
   queue), the outbox-relay/consumer pattern used throughout this
   codebase (see `docs/architecture/event-bus.md`) acks on success only
   — a permanently-failing handler will retry forever. Identify the
   `EventOutbox`/task row (by id, from logs) and either fix the
   underlying data issue or mark it dispatched manually as a last resort:
   ```sql
   -- only after understanding *why* it's failing
   UPDATE event_outbox SET dispatched_at = now() WHERE id = '<uuid>';
   ```

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
