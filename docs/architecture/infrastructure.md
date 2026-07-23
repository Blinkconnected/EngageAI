# Infrastructure Architecture

## Overview

Blink Engage runs as a set of Docker Compose–orchestrated services behind a
single NGINX ingress. Two Compose files describe the stack:

- `docker-compose.yml` — the default (dev) stack: hot-reloading backend and
  Vite dev server, NGINX proxying to both.
- `docker-compose.prod.yml` — an overlay applied on top with
  `-f docker-compose.yml -f docker-compose.prod.yml`: lean production
  images, no bind mounts, resource limits, and a single NGINX image that
  serves the compiled SPA directly instead of proxying to a dev server.

```
                        ┌────────────────────────┐
   client ───────────▶  │  nginx (port 80)       │
                        │  / api /metrics /ws     │
                        └───────────┬────────────┘
                     dev: proxy     │      prod: proxy
              ┌──────────────────┐  │  ┌───────────────────────┐
              │ frontend (vite)  │  │  │ static SPA (baked in) │
              └──────────────────┘  │  └───────────────────────┘
                                     ▼
                        ┌────────────────────────┐
                        │  backend (FastAPI)      │──────▶ postgres
                        │  /api/v1  /metrics      │──────▶ redis
                        └───────────┬────────────┘──────▶ rabbitmq
                                     │                └──▶ minio
                        ┌────────────┴────────────┐
                        │ celery-worker/-beat      │
                        └──────────────────────────┘

  observability: prometheus ◀─ backend, postgres-exporter, redis-exporter, rabbitmq
                 grafana ◀─ prometheus, loki
                 loki ◀─ promtail ◀─ docker container logs (all services)
```

## Services

| Service             | Image                                   | Role |
|---------------------|------------------------------------------|------|
| `postgres`           | `postgres:17-alpine`                     | Primary datastore |
| `redis`              | `redis:7-alpine`                         | Cache, Celery result backend, session/rate-limit store |
| `rabbitmq`           | `rabbitmq:3.13-management-alpine`        | Celery broker (prometheus plugin enabled) |
| `minio` / `minio-init` | `minio/minio`, `minio/mc`               | S3-compatible attachment storage; `minio-init` creates the bucket on first boot |
| `backend`            | `docker/backend/Dockerfile` (`dev`/`runtime`) | FastAPI API |
| `celery-worker`      | same image, `celery worker` command      | Async task execution |
| `celery-beat`        | same image, `celery beat` command        | Scheduled task dispatch |
| `frontend`           | `docker/frontend/Dockerfile` (`dev` only) | Vite dev server (dev stack only) |
| `nginx`              | `nginx:1.27-alpine` (dev) / `docker/nginx/Dockerfile` (prod) | Ingress: reverse proxy (dev) or static SPA + reverse proxy (prod) |
| `postgres-exporter`, `redis-exporter` | prometheuscommunity / oliver006 | Metrics exporters |
| `prometheus`, `grafana`, `loki`, `promtail` | official images | Metrics + log aggregation and visualization |

## Key architectural decisions

1. **Single NGINX origin, relative frontend API paths.** The frontend calls
   `VITE_API_BASE_URL=/api/v1` and `VITE_WS_BASE_URL=/ws` — relative paths,
   not absolute URLs. NGINX is the one origin for the browser in both dev
   and prod, which sidesteps CORS entirely for same-origin deployments and
   means the same build artifact works regardless of the domain it's
   deployed behind.
   *Tradeoff*: deployments that must serve the API and SPA from genuinely
   different origins (e.g. a separate API subdomain) need to override
   these at build time via the `VITE_API_BASE_URL`/`VITE_WS_BASE_URL`
   build args in `docker/nginx/Dockerfile` and reintroduce CORS
   configuration (already present and env-driven in the backend via
   `CORS_ALLOW_ORIGINS`).

2. **Two build targets per backend image (`dev` / `runtime`), one
   Dockerfile.** `dev` bind-mounts source for hot reload and installs the
   full `[dev]` extra (pytest, ruff, mypy, etc.); `runtime` is a
   multi-stage build that compiles dependencies in a `builder-runtime`
   stage and copies only the resulting venv into a slim final image — no
   compiler toolchain, no dev dependencies, non-root user. Both share the
   same `entrypoint.sh` (waits for Postgres, runs `alembic upgrade head`,
   then execs the given command), so migrations always run before the app
   or a worker starts, in every environment.

3. **Compose merge semantics required explicit `!override`.** Compose's
   default merge behavior *appends/unions* list and map fields (`volumes`,
   `depends_on`, ...) across `-f` files rather than replacing them. An
   overlay that sets `volumes: []` to "clear" a dev bind mount is a no-op
   under default merge — the base list wins unchanged. `docker-compose.prod.yml`
   uses the `!override` YAML tag on `volumes` and `depends_on` wherever the
   base value must be fully replaced rather than merged. This was caught by
   actually rendering `docker compose config` for both stacks and diffing
   the result — validate merged overlays this way, not by inspection alone.

4. **The dev `frontend` service is profile-gated (`profiles: ["dev-only"]`)
   in the prod overlay**, rather than removed — Compose has no "delete a
   service" primitive across `-f` files. Since that profile is never
   activated in the prod command line, the service is parsed but never
   started.

5. **NGINX upstream resolution uses Docker's embedded DNS resolver
   (`127.0.0.11`) with variable-based `proxy_pass`, not a static hostname.**
   A literal `proxy_pass http://backend:8000/api/;` resolves the `backend`
   hostname *once*, at NGINX startup — if that name isn't resolvable yet
   (start-up ordering) or changes (container recreation), NGINX fails to
   start or crash-loops entirely, taking down routes that don't even
   depend on the affected upstream. Using `set $backend_upstream
   http://backend:8000; proxy_pass $backend_upstream;` forces re-resolution
   per request. This was caught by testing the built production NGINX
   image standalone (`docker run` + `nginx -t`) without a live `backend`
   container present — exactly the condition a naive image would hit
   during a cold start or rolling deploy.
   *Follow-on correctness note*: once `proxy_pass` uses a variable, NGINX
   stops doing prefix substitution on the location match and instead
   forwards the original request URI unchanged. The proxy targets here
   have no trailing path (`proxy_pass $backend_upstream;`, not
   `.../api/`) — correct in this case because the path is identical on
   both sides, but worth remembering if a future proxied path needs to
   differ from the upstream's.

6. **First Alembic migration enables `pgcrypto` and `citext`** rather than
   creating any domain tables — those land with the entities that need
   them (Milestone 3, Auth/RBAC). This still proves the full migration
   pipeline (`entrypoint.sh` → `alembic upgrade head` → real Postgres)
   end-to-end before any domain logic depends on it.

7. **Prometheus instrumentation added to the backend now (M2), not
   deferred to the observability-hardening milestone (M26).** Wiring
   `prometheus-fastapi-instrumentator` at `/metrics` during infrastructure
   setup means Prometheus/Grafana have something real to scrape
   immediately, and the dashboard provisioned in
   `docker/grafana/dashboards/backend-api.json` is exercised by actual
   traffic rather than sitting inert until M26.

## Risks & tradeoffs

- **RabbitMQ management image size.** `rabbitmq:3.13-management-alpine`
  bundles the management UI/plugin for convenience; a leaner
  `rabbitmq:3.13-alpine` would reduce image size for environments that
  don't need the UI. Kept the management image for now since the
  Prometheus plugin and UI are useful during active development.
- **Promtail mounts the Docker socket and `/var/lib/docker/containers`
  read-only** to discover and tail container logs. This is the standard
  Loki/Promtail pattern but does give the promtail container visibility
  into all container metadata on the host; in a hardened/regulated
  deployment (this platform explicitly targets healthcare/financial
  customers) this should be revisited in the M25 security-hardening phase
  — options include a restricted Docker socket proxy or switching to the
  `json-file` log driver with an explicit path allowlist.
  See [[security-hardening-todo]] once that milestone begins.
- **No TLS termination yet.** NGINX listens on plain HTTP:80 in both dev
  and prod compose files. TLS (via a cert volume + NGINX `listen 443 ssl`
  block, or a managed proxy in front) is explicitly deferred to the M25
  security hardening phase and is a hard requirement before any real
  deployment — tracked in `docs/ROADMAP.md`.
- **Resource limits in `docker-compose.prod.yml` are conservative
  starting points** (e.g. backend 2 CPU / 1 GiB), not load-tested values.
  They exist so a single misbehaving container can't starve the host, but
  should be revisited against real traffic in the M27 performance-testing
  phase.
- **Loki retention is time-based only (168h / 7 days)**, filesystem-backed,
  single-node (`replication_factor: 1`, in-memory ring). Adequate for a
  single-host deployment; a multi-node or object-storage-backed Loki
  config is a scaling concern for later, not a correctness concern now.
- **This host's actual OS is Ubuntu 26.04**, not the Ubuntu 24.04 named in
  `CLAUDE.md`. Since every service runs in a container, the host OS version
  has no bearing on application behavior; noted here only for the record.

## Verification performed

- `docker compose config` rendered and manually diffed for both the plain
  dev stack and the `-f docker-compose.yml -f docker-compose.prod.yml`
  merge, confirming: `backend`/`celery-worker`/`celery-beat` build target
  switches to `runtime` with no bind mounts in prod; `frontend` is absent
  from the prod service list; `nginx` rebuilds from
  `docker/nginx/Dockerfile` with only the `backend` dependency (not
  `frontend`) in prod.
- Full dev stack brought up service-by-service (`postgres`/`redis`/
  `rabbitmq`/`minio` → `backend`/`celery-*` → `frontend`/`nginx` →
  `prometheus`/`grafana`/`loki`/`promtail`/exporters), with health checks
  and logs inspected at each stage.
- `alembic upgrade head` confirmed running against a real Postgres
  container via the entrypoint script.
- A Celery task (`blinkengage.ping`) dispatched from inside the `backend`
  container round-tripped through RabbitMQ → `celery-worker` → Redis
  result backend successfully.
- NGINX confirmed proxying `/`, `/api/v1/health`, and `/metrics` correctly
  through the single origin on port 80.
- Prometheus confirmed scraping all 5 configured targets (`up`).
- Grafana confirmed provisioning both datasources (Prometheus, Loki) and
  the `Blink Engage — Backend API` dashboard automatically.
- Loki confirmed receiving and serving log queries for all 15 running
  services via Promtail's Docker service-discovery.
- Production images (`backend` runtime target, `celery-worker` runtime
  target, `nginx` prod image with the frontend baked in) all built
  successfully; the prod `nginx` image was smoke-tested standalone
  (config test + serving the compiled SPA) independent of the rest of the
  stack.
