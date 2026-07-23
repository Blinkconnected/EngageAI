# Audit Logging Foundation

M9 of the roadmap, closing out Phase 1 (Identity & Core Directory). Adds a
company-scoped, append-only activity trail and hooks it into every
state-changing operation added so far.

## Data model

```
audit_logs
----------
id (PK)
company_id (FK -> companies, CASCADE)
actor_user_id (FK -> users, SET NULL, nullable)
action            "<entity_type>.<verb>", e.g. "department.created"
entity_type       "department" | "team" | "agent" | "customer" | "user" | "company"
entity_id (nullable)
details           small JSON bag of action-specific context
created_at        server-defaulted, indexed
```

No `updated_at`/`deleted_at` — see decision #1 below. Full column reference:
`docs/database/schema.md`.

## Key architectural decisions

1. **No `TimestampMixin`/`SoftDeleteMixin` on `AuditLog`.** Every other
   entity in this codebase gets both mixins (see `schema.md`'s
   conventions), but an audit row is written exactly once and never
   updated or deleted — giving it an `updated_at` would imply it can
   change, and soft-delete would let someone hide their own audited
   actions, defeating the feature. `AuditLog` only has `created_at`.

2. **The publish call runs synchronously, on the same `AsyncSession` as the
   business change it's describing — not via Celery/RabbitMQ or any queue.**
   `api/deps.py`'s `get_db_session` commits once per request; an
   `AuditLogPublisher.publish()` call inside a service method just adds a
   row to that same session. This means an audit entry and the change it
   records commit or roll back together atomically: there is no window
   where a committed business change is missing its audit entry, and no
   window where an audit entry exists for a change that got rolled back.
   A queued/async design (which would make sense for something like
   webhook delivery) would reintroduce exactly that inconsistency window,
   for no benefit here.

3. **`AuditPublisher` is a `Protocol` (`domain/audit.py`), not an inherited
   base class.** Consistent with how `domain/repositories/base.py`'s
   `Repository` Protocol is (structurally, not nominally) satisfied by the
   concrete repositories — `AuditLogPublisher` in
   `infrastructure/audit/publisher.py` doesn't subclass anything, it just
   implements `async def publish(event) -> None`.

4. **Hooked directly into each service's methods, not through a general
   in-process event bus.** `DepartmentService`, `TeamService`,
   `AgentService`, `CustomerService`, and `AuthService` each take an
   `audit: AuditPublisher` constructor dependency and call
   `self._audit.publish(AuditEvent(...))` inline after every
   create/update/delete (and, for `TeamService`, membership add/remove).
   A publish/subscribe bus would be justified once there's a second
   consumer of these events (e.g. the Phase 4 Workflow Engine reacting to
   entity changes) — with exactly one consumer today, that indirection
   would be speculative. Revisit this decision when Workflow Engine (M18)
   lands.

5. **`actor_user_id` threads through as a plain method parameter, not
   ambient/thread-local state.** Every mutating service method gained an
   `actor_user_id: UUID | None = None` parameter, and every endpoint passes
   `auth.user_id` (already available from `require_permission`'s
   `AuthContext`) through to it. `AuthService.authenticate`/`logout`
   already resolve the acting `User` internally, so those two don't need
   the extra parameter. This keeps services testable as pure functions of
   their inputs — no hidden global to fake in tests.

## Audited actions

| Action | Emitted from |
|--------|-------------|
| `company.registered` | `AuthService.register_company` |
| `user.login` | `AuthService.authenticate` |
| `user.logout` | `AuthService.logout` |
| `department.created` / `.updated` / `.deleted` | `DepartmentService` |
| `team.created` / `.updated` / `.deleted` | `TeamService` |
| `team_membership.added` / `.removed` | `TeamService.add_member` / `.remove_member` |
| `agent.created` / `.updated` / `.deleted` | `AgentService` |
| `customer.created` / `.updated` / `.deleted` | `CustomerService` |

## API

`GET /audit-logs` (`audit_logs.read` permission — already seeded onto the
Owner/Admin roles in `domain/rbac.py` since M6) is the only route; nothing
writes an audit log via the API. Supports the shared `Page`/`PageParams`
pagination plus filters: `entity_type`, `action`, `actor_user_id`,
`entity_id`, `since`, `until`.

## Verification performed

6 new integration tests (SQLite-backed): registration + login produce
`company.registered`/`user.login` entries with the correct actor; a full
department create/update/delete lifecycle is captured with matching
`entity_id`/`actor_user_id`; team-membership add/remove produce
`team_membership.*` entries with the agent id in `details`; filtering and
pagination; unauthenticated access rejected; and cross-tenant isolation (a
department created in one company produces zero visible audit rows to
another company's `GET /audit-logs?action=department.created`). 86 tests
total passing across the whole suite; `ruff check`/`mypy` clean.
