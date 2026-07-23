# Blink Engage

Enterprise AI-powered omnichannel customer engagement platform — built for
SMBs, enterprises, government, healthcare and financial institutions.

Blink Engage unifies conversations across WhatsApp, Facebook Messenger,
Instagram, Telegram, Email, SMS and Web Chat into a single agent workspace,
with AI-assisted replies, workflow automation, routing/assignment,
knowledge base, analytics, and ERPNext integration.

## Status

Actively under initial development. See [`docs/ROADMAP.md`](docs/ROADMAP.md)
for the full milestone plan and current progress, and
[`CLAUDE.md`](CLAUDE.md) for the permanent product/engineering specification
governing this repository.

## Architecture

- **Backend**: Python 3.13, FastAPI, SQLAlchemy 2 (async), Alembic,
  PostgreSQL, Redis, RabbitMQ, Celery, WebSockets — Clean Architecture with
  a Repository pattern and dependency injection.
- **Frontend**: React, TypeScript, Vite, Material UI, Redux Toolkit,
  React Query.
- **Infrastructure**: Docker / Docker Compose, NGINX, MinIO, Prometheus,
  Grafana, Loki, GitHub Actions.

## Repository layout

```
backend/     FastAPI application (domain / application / infrastructure / api)
frontend/    React + TypeScript SPA
docker/      Dockerfiles and per-service container configuration
docs/        Architecture, API, database, security, deployment documentation
scripts/     Operational and developer scripts
tests/       Cross-cutting / end-to-end tests
monitoring/  Prometheus, Grafana, Loki configuration
backups/     Backup artifacts (gitignored) and restore scripts
```

## Local development

Prerequisites: Docker Engine + Compose plugin, Node.js 22+, Python 3.13.

```bash
cp .env.example .env
docker compose up -d --build
```

Backend API: http://localhost:8000/docs
Frontend: http://localhost:5173

See [`docs/deployment/`](docs/deployment/) for full setup and production
deployment instructions.

## Contributing

All changes follow the milestone workflow defined in `CLAUDE.md`: build,
test, fix, document, commit. No milestone is merged with failing tests.
