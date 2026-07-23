# Core CRM: Departments, Teams, Agents, Customers

Phase 3 of the roadmap. Covers the operational directory layer built on
top of the Phase 2 auth/RBAC/multi-tenant foundation.

## Data model

```
departments              teams                    agents
-----------              -----                    ------
id (PK)                  id (PK)                  id (PK)
company_id (FK)          company_id (FK)          company_id (FK)
name                     department_id (FK, null) user_id (FK, unique*)
description              name                     department_id (FK, null)
is_active                description              title
soft-delete              is_active                status (online/away/offline)
                         soft-delete              soft-delete

                         team_memberships
                         ----------------
                         team_id (FK) + agent_id (FK)  [composite PK]
                         is_lead

customers                tags                     customer_tags
---------                ----                     -------------
id (PK)                  id (PK)                  customer_id (FK)
company_id (FK)          company_id (FK)          tag_id (FK)      [composite PK]
full_name                name (unique per company)
email (unique per company*)
phone
notes
custom_fields (JSON)
soft-delete
```

`*` — see decision #1 below: these uniqueness constraints are scoped to
*active* (non-soft-deleted) rows only.

- `Agent` is a distinct table from `User` (Phase 2's login identity) — see
  `docs/architecture/backend.md`'s note on this split. Creating an agent
  via `POST /agents` creates both a `User` and an `Agent` row, and assigns
  the company's seeded "Agent" role, in one transaction.
- `Tag` is a company-scoped catalog (like `Permission`, but company-owned
  rather than platform-owned) — tags are created on first use
  (`get_or_create`) rather than requiring a separate "define a tag" step.

## Key architectural decisions

1. **Soft-delete + uniqueness required partial unique indexes, not plain
   unique constraints — a real bug caught by testing, not foreseen by
   design.** `Department.name`, `Team.name`, `Agent.user_id`, and
   `Customer.email` are all unique per company **and** all live on
   soft-deletable tables. A plain `UniqueConstraint` blocks reusing a name
   after "deleting" the row that held it, because the row still physically
   exists with `deleted_at` set. Fixed by scoping each constraint to
   `WHERE deleted_at IS NULL` (`sqlalchemy.Index(..., unique=True,
   postgresql_where=..., sqlite_where=...)` — SQLAlchemy translates this to
   a native partial index on both Postgres and SQLite). This is a pattern
   every future soft-deletable + uniquely-named entity needs to follow;
   it's easy to reintroduce this bug by reaching for `UniqueConstraint`
   out of habit.

2. **Directly mutate ORM relationship collections instead of
   inserting/deleting join-table rows independently through the
   session — a second real bug, also caught by testing.** Customer
   tagging originally added/removed `CustomerTag` rows via
   `session.add()`/`session.delete()` directly, bypassing the
   `Customer.customer_tags` relationship collection. Within one request,
   `customer` is already in the session's identity map; a subsequent fetch
   after that out-of-band mutation returned the *same, now-stale* cached
   object instead of re-querying, so the response reflected the old tag
   set. Fixed by appending/removing through `customer.customer_tags`
   directly (relying on the `cascade="all, delete-orphan"` relationship
   config), which keeps the in-memory object consistent with what gets
   flushed — no reload needed. See `CustomerService._set_tags`'s docstring
   for the full explanation.

3. **A third, related bug**: even after fixing #2, constructing
   `CustomerTag(tag_id=tag.id)` (the foreign key value) instead of
   `CustomerTag(tag=tag)` (the related object) still crashed — the outer
   `customer.customer_tags` list was correctly populated, but each
   `CustomerTag.tag` relationship was not, so reading `.tag.name` in the
   API response still triggered an unsafe lazy load once the object
   became persistent. The fix is to always assign the *object*, not just
   its id, when you need the relationship readable without a DB round
   trip in the same request.

4. **Agent role assignment is automatic and fixed, not configurable.**
   `POST /agents` always grants the seeded "Agent" role — there's no way
   yet to create an agent with a different/custom role. Acceptable for
   this phase (RBAC's default roles cover the common case); revisit once
   custom roles have an API surface (noted as deferred in
   `docs/architecture/auth-rbac.md`).

5. **Customer `custom_fields` uses SQLAlchemy's portable `JSON` type, not
   Postgres's `JSONB`.** `JSONB` doesn't compile on SQLite, which the test
   suite runs against — using it broke every test that touched the
   `customers` table's schema. Plain `JSON` works identically (Postgres
   stores it as `json`, not `jsonb`) at the cost of no GIN-indexable
   querying into the JSON structure. Revisit if `custom_fields` needs to
   be searched/filtered efficiently at scale — that would call for a
   dedicated migration to `JSONB` plus a GIN index, done deliberately
   rather than reached for by default.

6. **Multi-channel identity resolution and merge/dedupe for customers are
   deferred to Phase 4.** The original roadmap line for Customers named
   these; they only make sense once the Channels/Conversations feature
   actually creates per-channel contact records for a customer to resolve
   against. Building them now would be speculative.

## Pagination

All list endpoints (`GET /departments`, `/teams`, `/agents`, `/customers`)
share `api/schemas/pagination.py`'s `PageParams` (page/page_size query
params, 1-100 page size) and `Page[T]` response envelope
(`items`/`total`/`page`/`page_size`). `Customer` additionally accepts a
`search` query param (case-insensitive substring match against name,
email, phone).

## Verification performed

- 30 new unit/integration tests (SQLite-backed) covering CRUD, pagination,
  search, tagging, team membership management, RBAC enforcement (an
  Agent-role user can read but not manage other agents), and multi-tenant
  isolation (a customer created in one company is invisible — 404, not
  403 — to another company). 80 tests total passing across the whole
  suite.
- End-to-end verification against real Postgres: applied the new
  migration on top of the already-running Phase 2 schema (a real
  incremental-migration scenario, not just a from-scratch `create_all`),
  then exercised the full flow live — created a department, an agent
  (with its underlying user + role), a team with that agent as lead, and
  a tagged customer — before confirming the partial-unique-index fix by
  soft-deleting a department and successfully recreating one with the
  same name.
