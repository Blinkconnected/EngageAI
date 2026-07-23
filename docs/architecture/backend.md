# Backend Architecture

## Layering (Clean Architecture)

```
backend/src/blinkengage/
  domain/            Entities, value objects, repository interfaces, domain
                      exceptions. No framework or I/O dependencies.
  application/        Use cases / application services that orchestrate
                      domain objects through repository interfaces.
  infrastructure/     Concrete implementations: SQLAlchemy models & session
                      management, repository implementations, external
                      service clients (object storage, AI providers, ERP).
  api/                FastAPI routers, request/response schemas, dependency
                      wiring. Translates HTTP <-> application layer calls.
  core/               Cross-cutting concerns: settings, logging, security
                      (JWT/hashing), the DI container, exception-to-HTTP
                      translation.
```

Dependency rule: `api` depends on `application` and `core`; `application`
depends on `domain`; `infrastructure` implements `domain` interfaces and is
wired in via `core/container.py`. `domain` depends on nothing else in this
codebase.

**Pragmatic adaptation, stated explicitly**: SQLAlchemy ORM models
(`infrastructure/database/models/`) serve as the primary domain
representation returned by repositories — there is no separate, hand-written
"domain entity" dataclass per table that repositories map to/from. A strict
reading of Clean Architecture would keep those separate so the domain layer
has zero persistence-framework awareness. For a platform with this many
entities (dozens of tables across the full roadmap), that duplication tax
(every field defined twice, every change touching two classes plus a
mapper) was judged not worth it relative to the payoff, which mainly
matters if the ORM were ever swapped out — unlikely for this project's
lifetime. `domain/` is reserved for logic that genuinely needs to be
framework-free and independently testable (e.g. `domain/rbac.py`'s
permission catalog, password-policy-shaped validation) rather than for
1:1 entity mirrors. The `Repository` protocol in `domain/repositories/base.py`
still exists and is still the abstraction application code depends on —
this decision only concerns what a repository returns, not whether one
exists.

## Dependency injection

`core/container.py` defines a `dependency_injector.DeclarativeContainer`
holding singletons for settings, the async SQLAlchemy engine, and the
session factory. It is instantiated once in `main.create_app()` and stored
on `app.state.container`. Route handlers obtain dependencies through
`api/deps.py`, which reads from `request.app.state.container` — application
code never imports the container directly, keeping FastAPI route modules
easy to unit test with a plain ASGI transport.

## Database

- SQLAlchemy 2 async ORM (`infrastructure/database/base.py`) with a shared
  `Base`, plus `UUIDPrimaryKeyMixin`, `TimestampMixin`, and
  `SoftDeleteMixin` used by every domain entity table (soft-delete only —
  rows are never physically removed, preserving the audit trail required by
  `CLAUDE.md`).
- A custom `GUID` type decorator stores UUIDs natively in PostgreSQL and as
  `CHAR(36)` in the SQLite backend used for fast unit/integration tests.
- Migrations are managed with Alembic (`backend/alembic/`), configured for
  async engines via `run_sync`.
- The Repository pattern (`domain/repositories/base.py`) and a
  `SqlAlchemyUnitOfWork` (`infrastructure/database/unit_of_work.py`) keep
  persistence concerns out of application/domain code.

## Security

- Passwords are hashed with bcrypt via `passlib` (`core/security.py`).
- Authentication uses short-lived JWT access tokens plus longer-lived,
  individually-revocable refresh tokens (`TokenType.ACCESS` /
  `TokenType.REFRESH`), signed with `JWT_SECRET_KEY` (HS256 by default,
  configurable).
- Domain-level `AuthenticationError` / `AuthorizationError` are translated
  to HTTP 401/403 at the API boundary by `core/exceptions.py`, keeping HTTP
  concerns out of the domain layer.
- RBAC, multi-tenancy, refresh-token revocation, and login/register rate
  limiting are documented in full in
  [`docs/architecture/auth-rbac.md`](auth-rbac.md) — including the
  reasoning behind embedding permissions in the access token rather than
  checking them against the database per-request, and a real concurrency
  bug (racing `alembic upgrade head` calls across services) caught during
  end-to-end verification and fixed with a Postgres advisory lock
  (`core/migrate.py`).

## Configuration

All configuration is environment-variable driven via `pydantic-settings`
(`core/config.py`) — see `.env.example` at the repository root. There are
no hard-coded secrets or environment-specific values in source code.

## Health checks

- `GET /api/v1/health` — liveness only, no dependency checks.
- `GET /api/v1/health/ready` — readiness, verifies the database connection
  with `SELECT 1`. Used by Docker/orchestrator health checks and load
  balancers.

## Testing

- `pytest` + `pytest-asyncio` (auto mode) with an in-memory SQLite database
  for unit and integration tests — no external services required to run
  the suite.
- Integration tests exercise the FastAPI app through `httpx.AsyncClient`
  over an `ASGITransport`, so no network socket is bound during tests.
- Static analysis gates: `ruff` (lint), `black` (format), `mypy --strict`
  (types). All three must pass before a milestone is committed.
