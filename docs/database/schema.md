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
  to cascade, not orphan rows. Foreign keys to an entity a row merely
  *references* (a team/agent's `department_id`) use `ondelete="SET NULL"`
  instead — deleting a department detaches its teams/agents rather than
  deleting them.
- Tables that are both soft-deletable **and** uniquely named/keyed per
  company (`departments.name`, `teams.name`, `agents.user_id`,
  `customers.email`) enforce that uniqueness with a **partial** unique
  index (`WHERE deleted_at IS NULL`), not a plain `UniqueConstraint` —
  otherwise a soft-deleted row's name/email stays permanently reserved
  and can never be reused. See `docs/architecture/core-crm.md` decision
  #1 for the bug this fixes.

## Migration history

| Revision | Adds |
|----------|------|
| `1cff1a67f289` | `pgcrypto`, `citext` Postgres extensions (available for future use; no column currently depends on them) |
| `f2df1379a476` | `companies`, `users`, `permissions` (seeded from `domain.rbac.PERMISSIONS`), `roles`, `role_permissions`, `user_roles` |
| `37f197931b3f` | `departments`, `teams`, `team_memberships`, `agents`, `customers`, `tags`, `customer_tags` |
| `2748c9c76517` | `audit_logs` |
| `5a9957be8e5e` | `event_outbox` |
| `48fc9680074e` | `channel_configs` |
| `5463a5076e76` | seeds `channels.read`/`channels.manage` into `permissions` (a fixed, explicit snapshot — not imported from `domain.rbac.PERMISSIONS` like the original seed, so this migration stays a stable diff regardless of later catalog changes) |
| `855f7e80bccb` | `conversations`, `messages`, `message_attachments` |
| `9fe815db63b7` | `queues`, `agent_skills`, `agent_skill_assignments`, `queue_required_skills`, `routing_rules`; adds `queue_id`/`first_response_at`/`sla_first_response_breached_at`/`sla_resolution_breached_at` to `conversations` |
| `7c6ca45d6fac` | seeds `queues.read`/`queues.manage` into `permissions` (same fixed-snapshot pattern as `5463a5076e76`) |
| `a1b2c3d4e5f6` | `customer_channel_identities` (generic multi-channel identity resolution, see `docs/architecture/whatsapp-telegram.md`) |
| `b2c3d4e5f6a7` | `workflow_definitions`, `workflow_runs` |
| `c3d4e5f6a7b8` | seeds `workflows.read`/`workflows.manage` into `permissions` (same fixed-snapshot pattern as `5463a5076e76`/`7c6ca45d6fac`) |

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

### `departments`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| name | varchar(255) | unique per `(company_id, name)` among active rows |
| description | text, nullable | |
| is_active | boolean | |
| created_at / updated_at / deleted_at | timestamptz | |

### `teams`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| department_id | UUID, nullable | FK → `departments.id`, `SET NULL` on delete, indexed |
| name | varchar(255) | unique per `(company_id, name)` among active rows |
| description | text, nullable | |
| is_active | boolean | |
| created_at / updated_at / deleted_at | timestamptz | |

### `team_memberships` (join)

| Column | Type | Notes |
|--------|------|-------|
| team_id | UUID | FK → `teams.id`, cascade delete |
| agent_id | UUID | FK → `agents.id`, cascade delete |
| is_lead | boolean | |
| created_at / updated_at | timestamptz | |

Composite PK `(team_id, agent_id)`.

### `agents` (operational profile on top of a `user`)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| user_id | UUID | FK → `users.id`, cascade delete; unique among active rows |
| department_id | UUID, nullable | FK → `departments.id`, `SET NULL` on delete, indexed |
| title | varchar(255), nullable | |
| status | varchar(20) | `online` / `away` / `offline` (`AgentStatus`) |
| created_at / updated_at / deleted_at | timestamptz | |

### `customers`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| full_name | varchar(255) | |
| email | varchar(320), nullable | unique per `(company_id, email)` among active rows; multiple NULLs allowed |
| phone | varchar(32), nullable | indexed |
| notes | text, nullable | |
| custom_fields | JSON | schema-less bag; portable type (not `JSONB` — see core-crm.md decision #5) |
| created_at / updated_at / deleted_at | timestamptz | |

### `customer_channel_identities`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| customer_id | UUID | FK → `customers.id`, cascade delete, indexed |
| channel_type | varchar(50) | plain string, same reasoning as `channel_configs.channel_type` |
| external_id | varchar(255) | a WhatsApp `wa_id`, Telegram user id, etc. |
| created_at / updated_at | timestamptz | |

Unique on `(company_id, channel_type, external_id)`. Maps a provider's
external identifier to a `Customer` for every channel that has no
existing unambiguous `Customer` column to resolve onto (everything except
`web_chat`/`email` — see `docs/architecture/whatsapp-telegram.md`). No
`deleted_at` — these are pure mapping rows with no independent lifecycle
worth auditing, same reasoning as `customer_tags`.

### `tags` (company-scoped catalog)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| name | varchar(100) | unique per `(company_id, name)` — no soft-delete, so a plain `UniqueConstraint` |
| created_at / updated_at | timestamptz | |

Created on first use (`TagRepository.get_or_create`), not via a separate
"define a tag" step.

### `customer_tags` (join)

| Column | Type |
|--------|------|
| customer_id | UUID, FK → `customers.id`, cascade delete |
| tag_id | UUID, FK → `tags.id`, cascade delete |

Composite PK `(customer_id, tag_id)`.

### `audit_logs` (append-only)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| actor_user_id | UUID, nullable | FK → `users.id`, **`SET NULL`** on delete — the audit trail outlives the actor's row |
| action | varchar(100) | `<entity_type>.<verb>`, e.g. `department.created` |
| entity_type | varchar(100) | e.g. `department`, `customer`, `user` |
| entity_id | UUID, nullable | the affected row's id (null for events with no single entity) |
| details | JSON | small, action-specific context (e.g. `{"name": "Support"}`) |
| created_at | timestamptz | server-defaulted to `now()`, indexed |

No `updated_at`/`deleted_at` — rows are never modified or deleted (see
`docs/architecture/audit-logging.md`). Composite indexes on
`(company_id, created_at)` and `(company_id, entity_type, entity_id)`
support the two query patterns the API exposes: a recent-activity feed and
an entity's history.

As of M10, rows are written by the `audit-log` domain event consumer, not
by a direct per-service call — see `docs/architecture/event-bus.md`.

### `event_outbox` (append-only, transactional outbox)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| event_type | varchar(150) | `<aggregate_type>.<verb>`, e.g. `message.received` |
| company_id | UUID, nullable | some events are platform-level, not tenant-scoped |
| aggregate_type | varchar(100) | e.g. `customer`, `message`, `channel_config` |
| aggregate_id | UUID, nullable | |
| actor_user_id | UUID, nullable | |
| payload | JSON | event-specific context |
| occurred_at | timestamptz | business time the event describes |
| created_at | timestamptz | server-defaulted to `now()` — row insert time |
| dispatched_at | timestamptz, nullable | null = not yet relayed to RabbitMQ |
| attempts | integer | incremented on relay publish failure |

No soft-delete — rows are never deleted here (pruning old dispatched rows
is a separate operational job). Partial index on `created_at`
`WHERE dispatched_at IS NULL` keeps the relay's claim query cheap
regardless of how large the dispatched majority grows. See
`docs/architecture/event-bus.md` for the full pattern.

### `channel_configs`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| channel_type | varchar(50) | plain string, not a DB enum — validity is checked against `ChannelRegistry` at the application layer so new channel types need no migration |
| display_name | varchar(255) | |
| is_active | boolean | |
| credentials | bytea | AES-256-GCM encrypted at rest (`EncryptedJSON` type — see `docs/architecture/channels.md`); never returned by the API |
| webhook_secret | varchar(255), nullable | |
| created_at / updated_at / deleted_at | timestamptz | |

No uniqueness constraint on `(company_id, channel_type)` — a company may
run multiple instances of one channel type (e.g. two WhatsApp Business
numbers).

### `conversations`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| customer_id | UUID | FK → `customers.id`, cascade delete, indexed |
| channel_config_id | UUID | FK → `channel_configs.id`, cascade delete, indexed |
| external_thread_id | varchar(255), nullable | unique per `channel_config_id` among active rows |
| status | varchar(20) | `open` / `pending` / `resolved` / `closed` (`ConversationStatus`) |
| assigned_agent_id | UUID, nullable | FK → `agents.id`, `SET NULL` on delete, indexed |
| last_message_at | timestamptz, nullable | |
| queue_id | UUID, nullable | FK → `queues.id`, `SET NULL` on delete, indexed — added M14 |
| first_response_at | timestamptz, nullable | set on the first outbound message — added M14 |
| sla_first_response_breached_at | timestamptz, nullable | idempotency marker for the SLA sweep — added M14 |
| sla_resolution_breached_at | timestamptz, nullable | idempotency marker for the SLA sweep — added M14 |
| created_at / updated_at / deleted_at | timestamptz | |

### `messages`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id, channel_type | UUID, varchar(50) | denormalized — see `core-crm.md`/`channels.md`'s join-avoidance reasoning |
| channel_config_id | UUID | FK → `channel_configs.id`, cascade delete |
| conversation_id | UUID | FK → `conversations.id`, cascade delete, indexed |
| customer_id | UUID | FK → `customers.id`, cascade delete, indexed |
| external_message_id | varchar(255), nullable | unique per `channel_config_id` among rows that have one |
| direction | varchar(20) | `inbound` / `outbound` (`MessageDirection`) |
| message_type | varchar(20) | `text` / `media` / `system` (`MessageType`) |
| status | varchar(20) | `pending` / `sent` / `failed` — our processing state (`MessageStatus`) |
| delivery_status | varchar(20) | `pending` / `delivered` / `undelivered` / `not_applicable` — provider-confirmed (`DeliveryStatus`) |
| read_status | varchar(20) | `unread` / `read` (`ReadStatus`) |
| body | text, nullable | a media-only message has no text |
| reply_to_message_id | UUID, nullable | self-FK, `SET NULL` on delete |
| message_metadata | JSON | portable type, not `JSONB` — see `core-crm.md` decision #5 |
| sent_at / delivered_at / read_at | timestamptz, nullable | |
| created_at / updated_at / deleted_at | timestamptz | |

Composite indexes on `(conversation_id, created_at)` and
`(company_id, created_at)` support conversation-history pagination and
company-scoped recent-activity queries respectively.

### `message_attachments`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| conversation_id | UUID | FK → `conversations.id`, cascade delete, indexed |
| message_id | UUID, nullable | FK → `messages.id`, cascade delete, indexed — nullable because upload and compose-reply are separate requests, see `conversations.md` decision #1 |
| storage_key | varchar(500) | the `AttachmentStore`/MinIO object key |
| filename | varchar(255) | |
| content_type | varchar(100) | |
| size_bytes | bigint | |
| validation_status | varchar(20) | `pending` / `approved` / `rejected` (`AttachmentValidationStatus`) — only `approved` is written today; `pending` is reserved for a future virus-scan hook, see `conversations.md` decision #4 |
| created_at | timestamptz | no `updated_at`/`deleted_at` — an attachment row never changes after upload |

### `queues`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| name | varchar(255) | unique per company among active rows |
| description | varchar(1000), nullable | |
| department_id | UUID, nullable | FK → `departments.id`, `SET NULL` — an organizational label only, not an eligibility filter, see `queues-routing.md` decision #2 |
| assignment_strategy | varchar(20) | `round_robin` / `least_load` (`QueueAssignmentStrategy`) |
| first_response_target_minutes | integer, nullable | null = no first-response SLA on this queue |
| resolution_target_minutes | integer, nullable | null = no resolution SLA on this queue |
| is_active | boolean | |
| created_at / updated_at / deleted_at | timestamptz | |

### `agent_skills` (catalog, company-scoped) / `agent_skill_assignments` (join)

| Column | Type | Notes |
|--------|------|-------|
| id, company_id, name | UUID, UUID, varchar(100) | unique per company — created on first use, mirroring `tags` (M8) |

`agent_skill_assignments`: `agent_id` (FK → `agents.id`, cascade) +
`skill_id` (FK → `agent_skills.id`, cascade), composite PK.

### `queue_required_skills` (join)

| Column | Type |
|--------|------|
| queue_id | UUID, FK → `queues.id`, cascade delete |
| skill_id | UUID, FK → `agent_skills.id`, cascade delete |

Composite PK `(queue_id, skill_id)`. Zero rows for a queue means "no
restriction" — every active agent is eligible.

### `routing_rules`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| priority | integer | lower evaluates first |
| conditions | JSON | `{"channel_type": "..."}` and/or `{"body_contains": "..."}` — deliberately not a general rules DSL, see `queues-routing.md` |
| target_queue_id | UUID | FK → `queues.id`, cascade delete |
| is_active | boolean | |
| created_at / updated_at | timestamptz | |

### `workflow_definitions`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| name | varchar(255) | |
| description | text, nullable | |
| trigger_event_type | varchar(100) | plain string — new domain event types need zero migration, same reasoning as `channel_configs.channel_type` |
| conditions | JSON | `{"all": [...]}` / `{"any": [...]}` tree — see `domain/workflow_condition.py` |
| actions | JSON | ordered `[{"type": "...", "params": {...}}]` — see `application/workflow_actions/builtin.py` |
| is_active | boolean | |
| priority | integer | lower runs first among workflows sharing one `trigger_event_type` |
| created_at / updated_at / deleted_at | timestamptz | |

### `workflow_runs` (append-only)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| workflow_id | UUID | FK → `workflow_definitions.id`, cascade delete, indexed |
| triggering_event_type | varchar(100) | |
| triggering_event_payload | JSON | full snapshot of the event that triggered this run |
| status | varchar(20) | `succeeded` / `failed` / `skipped` (`WorkflowRunStatus`) |
| actions_executed | JSON | `[{"action_type": "...", "result"/"error": {...}}]` — execution stops at the first failing step |
| error_message | text, nullable | |
| started_at / finished_at | timestamptz | no `created_at`/`updated_at` — these two already fully describe the run's timing, same reasoning as `AuditLog` having no `updated_at` |

No `SoftDeleteMixin` on either — `workflow_runs` is a pure audit trail
(same reasoning as `audit_logs`/`event_outbox`); `workflow_definitions` is
soft-deletable like every other company-configured entity in this schema.

### `knowledge_categories`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| name | varchar(255) | |
| parent_id | UUID, nullable | FK → `knowledge_categories.id`, `SET NULL` — deleting a parent detaches children to top-level rather than cascading |
| created_at / updated_at / deleted_at | timestamptz | |

### `knowledge_articles`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| category_id | UUID, nullable | FK → `knowledge_categories.id`, `SET NULL` |
| title | varchar(255) | |
| body | text | |
| is_published | boolean | |
| created_at / updated_at / deleted_at | timestamptz | |

### `knowledge_article_tags` (join)

| Column | Type |
|--------|------|
| article_id | UUID, FK → `knowledge_articles.id`, cascade delete |
| tag_id | UUID, FK → `tags.id`, cascade delete |

Composite PK `(article_id, tag_id)` — reuses the existing company-scoped
`tags` catalog (M8) rather than a parallel Knowledge-Base-specific
tagging system.

### `quick_replies`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| shortcut | varchar(50) | unique per `(company_id, shortcut)` among active rows — same partial-unique-index pattern as `queues.name`/`customers.email` |
| title | varchar(255) | |
| body | text | |
| is_active | boolean | |
| created_at / updated_at / deleted_at | timestamptz | |

### `internal_notes`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete, indexed |
| conversation_id | UUID | FK → `conversations.id`, cascade delete, indexed |
| author_user_id | UUID, nullable | FK → `users.id`, `SET NULL` — a note outlives the user who wrote it, same reasoning as `audit_logs.actor_user_id` |
| body | text | |
| created_at / updated_at | timestamptz | |

No `SoftDeleteMixin` — hard-deletable, same reasoning as `routing_rules`
(low-stakes, no compliance requirement to retain a deleted note; the
audit-log-consumer already durably records the deletion event regardless
of the row's fate).
