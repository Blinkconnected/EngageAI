# Database Schema

Migrations: `backend/alembic/versions/`. Applied automatically on
container start via `docker/backend/entrypoint.sh` →
`blinkengage.core.migrate` (Postgres-advisory-lock-serialized
`alembic upgrade head`).

## Conventions

- Every entity table has a UUID primary key (`id`), generated client-side
  by SQLAlchemy (`uuid.uuid4()`), not a database sequence or
  server-generated UUID — see `infrastructure/database/base.py`'s `GUID`
  type decorator (native `UUID` on Postgres, `CHAR(36)` on SQLite).
- Every entity table has `created_at`/`updated_at` (server-defaulted to
  `now()`, timezone-aware). Tables representing something that can be
  "removed" without losing the audit trail also have a nullable
  `deleted_at` (soft delete — see `SoftDeleteMixin`); pure association/
  join tables (`role_permissions`, `user_roles`) and the `permissions`
  catalog do not, since they have no independent lifecycle worth
  auditing.
- Foreign keys cascade on delete (`ondelete="CASCADE"`) for
  strictly-owned child rows (a company's users/roles, a role's
  permission/user assignments) — deleting a company or role is expected
  to cascade, not orphan rows.

## Migration history

| Revision | Adds |
|----------|------|
| `1cff1a67f289` | `pgcrypto`, `citext` Postgres extensions (available for future use; no column currently depends on them) |
| `f2df1379a476` | `companies`, `users`, `permissions` (seeded from `domain.rbac.PERMISSIONS`), `roles`, `role_permissions`, `user_roles` |

## Tables

### `companies` (tenant)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| name | varchar(255) | |
| slug | varchar(255) | unique, indexed; lowercase-normalized in the application layer |
| status | varchar(20) | `trial` / `active` / `suspended` (`CompanyStatus`) |
| created_at / updated_at / deleted_at | timestamptz | |

### `users` (login identity)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| email | varchar(320) | **globally** unique, indexed — see auth-rbac.md decision #1 |
| hashed_password | varchar(255) | bcrypt |
| full_name | varchar(255) | |
| is_active | boolean | |
| is_company_owner | boolean | set once at registration, not currently reassignable via API |
| last_login_at | timestamptz, nullable | |
| created_at / updated_at / deleted_at | timestamptz | |

### `permissions` (seeded catalog)

| Column | Type | Notes |
|--------|------|-------|
| code | varchar(100) | PK, e.g. `customers.manage` |
| description | text | |

Seeded by migration `f2df1379a476` from `domain.rbac.PERMISSIONS` — the
single source of truth for what permissions exist. Adding a new permission
means adding it there and writing a new migration to insert the row; the
catalog is never written to by application code at runtime.

### `roles`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| name | varchar(100) | unique per `(company_id, name)` |
| description | text, nullable | |
| is_system | boolean | true for the seeded Owner/Admin/Agent roles; prevents deletion |
| created_at / updated_at | timestamptz | |

### `role_permissions` (join)

| Column | Type |
|--------|------|
| role_id | UUID, FK → `roles.id`, cascade delete |
| permission_code | varchar(100), FK → `permissions.code`, cascade delete |

Composite PK `(role_id, permission_code)`.

### `user_roles` (join)

| Column | Type |
|--------|------|
| user_id | UUID, FK → `users.id`, cascade delete |
| role_id | UUID, FK → `roles.id`, cascade delete |

Composite PK `(user_id, role_id)` — a user can hold multiple roles.
