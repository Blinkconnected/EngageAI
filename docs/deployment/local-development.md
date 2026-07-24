# Local Development

## Prerequisites

- Docker Engine + the Compose plugin (`docker compose version`)
- Node.js 22+ and Python 3.13 (only needed for running backend/frontend
  tooling outside containers — not required to run the stack itself)

## First-time setup

```bash
cp .env.example .env
# Edit .env: at minimum set real values for JWT_SECRET_KEY,
# POSTGRES_PASSWORD, RABBITMQ_DEFAULT_PASS, MINIO_ROOT_PASSWORD /
# S3_SECRET_KEY, and GF_SECURITY_ADMIN_PASSWORD. These are required
# (the compose file fails fast with a clear error if left unset).

docker compose up -d --build
```

## What you get

| URL                          | Service                                   |
|-------------------------------|--------------------------------------------|
| http://localhost/             | App, via NGINX (proxies to the Vite dev server) |
| http://localhost/api/       | Backend REST API, via NGINX (`/api/v1/...`) |
| http://localhost:8000/docs    | Swagger UI — **backend port directly**, not through NGINX: the dev NGINX config's catch-all `location /` proxies every unmatched path (including bare `/docs`) to the frontend's Vite dev server, not the backend, so `/docs` is only reachable by bypassing NGINX |
| http://localhost:8000/redoc   | ReDoc, same direct-backend-port caveat as above |
| http://localhost:8000         | Backend directly (bypasses NGINX)          |
| http://localhost:5173         | Vite dev server directly (bypasses NGINX)  |
| http://localhost:9090         | Prometheus                                  |
| http://localhost:3000         | Grafana (login: `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` from `.env`) |
| MinIO console (see below)     | Object storage browser                      |

The backend and frontend containers bind-mount the repo, so code edits are
picked up live (`uvicorn --reload`, Vite HMR).

## Common commands

```bash
docker compose logs -f backend           # tail one service's logs
docker compose exec backend bash         # shell into the backend container
docker compose exec backend alembic revision -m "add x"   # new migration
docker compose down                      # stop everything, keep volumes
docker compose down -v                    # stop everything, DELETE volumes (data loss)
```

Backend tooling (tests/lint/types) can also be run directly against the
local virtualenv without Docker — see `backend/README.md`-equivalent
commands in the root `Makefile` (`make backend-test`, `make backend-lint`,
`make backend-typecheck`).

## Verifying the stack is healthy

```bash
curl http://localhost/api/v1/health         # liveness
curl http://localhost/api/v1/health/ready   # readiness (checks the DB)
docker compose ps                           # all core services should show "healthy"
```

## Troubleshooting

- **A required env var error on startup** (`POSTGRES_PASSWORD must be set
  in .env`, etc.): these are intentionally hard requirements — the compose
  file refuses to start with placeholder-free but unset secrets. Fill them
  in in `.env`.
- **`backend` restarts in a loop**: check `docker compose logs backend` —
  the entrypoint waits up to ~60s for Postgres before giving up; if
  Postgres itself isn't healthy yet the backend's dependency condition
  (`service_healthy`) should already gate this, so a loop usually means an
  application-level startup error (check the traceback in the logs).
