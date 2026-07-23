# Production Deployment

> Status: infrastructure-level deployment mechanics only. TLS termination,
> secrets management (beyond `.env`), backup automation, and the full
> security hardening pass are tracked separately in `docs/ROADMAP.md`
> (Phase 6) and must be completed before handling real customer data.

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

## What's intentionally NOT here yet

- TLS/HTTPS — deploy behind a TLS-terminating load balancer, or add a
  `listen 443 ssl` server block + certificate volume to
  `docker/nginx/nginx.prod.conf` before any real-world exposure.
- Automated backups (`backups/` — Phase 6).
- Secrets manager integration (currently a plain `.env` file — Phase 6).
- Horizontal scaling / multi-node orchestration (this is a single-host
  Compose deployment by design at this stage; Kubernetes manifests are out
  of scope unless requested).
