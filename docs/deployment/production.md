# Production Deployment

> Status: security hardening (M26), automated backups, and monitoring/
> alerting (M27) are done — see `docs/security/hardening.md` and
> `docs/architecture/observability.md`. TLS termination, secrets manager
> integration, and a real CI/CD deploy target remain open — see "What's
> intentionally NOT here yet" below.

## Bring-up

```bash
cp .env.example .env
# Fill in real, unique secrets for every required variable — see
# docs/security/ (added in the security-hardening phase) for rotation
# policy once that phase lands.

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

This overlay, relative to the default (dev) stack:

- Builds `backend`, `celery-worker`, `celery-beat` from the `runtime`
  Docker target (no bind mounts, no dev dependencies, non-root user).
- Does **not** start the Vite dev server (`frontend` is profile-gated off).
- Builds `nginx` from `docker/nginx/Dockerfile`, which compiles the React
  SPA and serves the static output directly, reverse-proxying `/api`,
  `/metrics`, and `/ws` to the `backend` service.
- Applies conservative CPU/memory limits to `backend`, `celery-worker`,
  `celery-beat`, `nginx`, and `postgres`.
- Sets `restart: always` on the core services.

## Frontend build-time configuration

The compiled SPA calls the API via **relative paths**
(`VITE_API_BASE_URL=/api/v1`, `VITE_WS_BASE_URL=/ws` by default) — see
`docs/architecture/infrastructure.md` for why. If the API is ever served
from a different origin than the SPA, override these as build args:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml build \
  --build-arg VITE_API_BASE_URL=https://api.example.com/api/v1 \
  --build-arg VITE_WS_BASE_URL=wss://api.example.com/ws \
  nginx
```

and set `CORS_ALLOW_ORIGINS` in `.env` to the SPA's origin.

## Database migrations

Migrations run automatically on every `backend`/`celery-*` container start
(via `docker/backend/entrypoint.sh`, before the process execs). For a
zero-downtime rolling deploy where you want migrations applied exactly
once ahead of a multi-replica rollout, run them explicitly first:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

## Backups & restore (M27)

```bash
./scripts/backup_postgres.sh            # pg_dump, gzip, timestamped, into backups/
./scripts/verify_backup_restore.sh      # restore drill against a scratch database
./scripts/restore_postgres.sh <file> [--force] [--target-db NAME]
```

Run `backup_postgres.sh` on a schedule (host cron, or a scheduled CI job)
and `verify_backup_restore.sh` right after it — a backup nobody has ever
restored is not a verified backup. See
`docs/architecture/observability.md` for the full design rationale.
`BACKUP_RETENTION_DAYS` (default 14) controls pruning.

## Monitoring & alerting (M27)

Grafana at `:3000` (datasources/dashboards/alert rules all provisioned
automatically, see `docs/architecture/observability.md`), Prometheus at
`:9090`. Alert rules are wired but point at a deliberate placeholder
contact point (`docker/grafana/provisioning/alerting/contact-points.yml`)
— replace the webhook URL there with a real Slack/PagerDuty/email
destination before relying on alerting in production.

## CI/CD

`.github/workflows/ci.yml` runs lint/test/build/scan on every push and PR
to `main`. The `deploy` job is a documented placeholder gated on version
tags — it does not deploy anywhere until a real target (host, registry,
credentials) is configured; see the comments in that file.

## What's intentionally NOT here yet

- TLS/HTTPS — deploy behind a TLS-terminating load balancer, or add a
  `listen 443 ssl` server block + certificate volume to
  `docker/nginx/nginx.prod.conf` before any real-world exposure.
- A real CI/CD deploy target — see "CI/CD" above.
- Secrets manager integration (currently a plain `.env` file — tracked as
  a follow-up, not blocking for a single-host deployment).
- True per-request load balancing across multiple `backend` replicas —
  nginx's dynamic-DNS re-resolution (`docker/nginx/nginx.*.conf`) gives
  coarse-grained rotation across `docker compose up --scale backend=N`
  replicas, not per-request spreading; a real orchestrator (Kubernetes
  Service/Ingress) or nginx Plus is the documented next step at higher
  scale. See `docs/architecture/observability.md`.
