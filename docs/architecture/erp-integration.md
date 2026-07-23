# ERPNext Integration

M24 of the roadmap. Outbound customer sync, inbound webhook ingestion,
and on-demand pull for the six record types the CLAUDE.md ERP section
names: Customers, Invoices, Sales Orders, Quotations, Support Tickets,
Payments, Contacts.

## One named integration, not a plugin architecture

Unlike channels, AI providers, or SMS gateways — each explicitly a
plugin architecture in the CLAUDE.md spec, with several interchangeable
implementations behind one registry — the ERP section names exactly one
system: ERPNext. Building a registry/plugin architecture here would be
pure ceremony with nothing to register a second entry against. So
`domain/erp_client.py`'s `ErpClient` is a `Protocol` (like
`DomainEventPublisher`), not an `ABC` with a registry (like
`ChannelProvider`/`AiProvider`) — there's exactly one concrete
implementation (`infrastructure/erp/client.py`'s `ErpNextClient`),
constructed directly from a company's `ErpConfig` row via
`infrastructure/erp/factory.py::build_erp_client`, the same "factory
decrypts credentials and builds the client" shape
`ChannelProviderFactory` already established.

`ErpConfig` itself mirrors `ChannelConfig` exactly — per-company,
soft-deletable, `credentials` encrypted via the same `EncryptedJSON`
type, `credentials`/`webhook_secret` write-only over the API (never
echoed back). One active `ErpConfig` per company is all this integration
supports (`ErpConfigRepository.get_active_for_company`) — a company
either has one ERPNext connection or none.

## Outbound: push a new customer, automatically and silently

`erp_sync_consumer.py` binds `customer.created` (the only new routing
key this milestone adds) and calls `ErpSyncService.sync_customer`. For
the large majority of companies with no `ErpConfig` at all, this is a
silent, cheap no-op (`get_active_for_company` returns `None`) — it must
never error or log-spam for the common case, since it runs on every
single new customer across every company on the platform. Any failure
during the actual ERPNext API call (network blip, bad credentials,
ERPNext down) is caught and logged, never re-raised — a customer's
ERPNext sync failing must never block or retry-loop the customer's own
creation.

Sync is idempotent: `ErpCustomerLink` has a unique constraint on
`customer_id`, and `sync_customer` checks for an existing link before
calling ERPNext at all. The explicit, agent-triggered counterpart
(`POST /customers/{id}/erp-sync`, `erp.manage`) reuses the exact same
method but wraps it in `sync_customer_or_raise`, which surfaces a new
`ErpNotConfiguredError` (503, same pattern as M22's
`AiNotConfiguredError`) when there's no active connection — a
*deliberate* manual action against an unconfigured integration should be
an error, unlike the automatic consumer's silent no-op.

## Inbound: a generic webhook, not six near-duplicate tables

ERPNext's own Webhook doctype lets an administrator configure one
webhook per document event, POSTing the raw document JSON to a URL of
their choosing — there's no standardized request-signature scheme the
way WhatsApp/Messenger/Twilio have, so this integration's own shared
secret is verified via a custom request header (`X-Webhook-Secret`) the
ERPNext admin configures alongside the URL, checked with
`hmac.compare_digest` against `ErpConfig.webhook_secret`.

`POST /webhooks/erpnext/{erp_config_id}/{doctype}` is deliberately
doctype-agnostic in its URL, not hardcoded to a fixed enum of the six
named record types — an ERPNext admin creates one Webhook record per
doctype they want synced, each pointing at this same URL pattern with a
different `{doctype}` segment. This also sidesteps a real-world
ambiguity: "Support Tickets" is the Frappe Helpdesk app's `HD Ticket`
doctype on some ERPNext installs and the core `Issue` doctype on others
— accepting any doctype string means this integration works with either
without a hardcoded assumption.

Every inbound document (regardless of doctype) lands in one generic
`erp_synced_records` table (`company_id`, `customer_id` nullable,
`doctype`, `external_name`, `data` JSON, `external_modified_at`), not six
near-duplicate tables — invoices/orders/quotations/tickets/payments/
contacts are heterogeneous, read-only, per-company-customized document
shapes only ever displayed, never queried/filtered relationally beyond
"this customer's records of doctype X." A customer reference is resolved
by looking up the payload's `"customer"` field against
`ErpCustomerLink.erp_customer_name`; if no link is found (or the
document simply doesn't carry a customer reference), the row is still
cached with `customer_id = NULL` rather than dropped.

## Manual pull as a backfill/retry path, sharing the same cache

`POST /customers/{id}/erp-pull/{doctype}` (`erp.manage`) calls
`ErpNextClient.list_records` live and upserts every result into the same
`erp_synced_records` table the webhook writes to — useful for an initial
backfill (a customer created before ERP was configured) or recovering
from a missed webhook delivery, without a second storage path to keep in
sync. `list_records` filters on ERPNext's own `"customer"` field, which
`Sales Invoice`/`Sales Order`/`Payment Entry` use natively out of the
box; some doctypes (a customized `Quotation`, a support-ticket doctype
using `raised_by`) may use a different field name — a known, documented
limitation rather than an attempt to special-case every possible ERPNext
customization. `GET /customers/{id}/erp-records?doctype=...` reads the
cache directly (no live ERPNext call), reusing `customers.read` — no new
permission needed for *viewing* data about a customer the agent can
already see, the same reasoning Internal Notes (M20) established for
reusing `conversations.*`.

## RBAC

One new permission, `erp.manage` — configuring the ERPNext connection and
triggering manual sync/pull is an admin action, seeded into the default
`Admin` role only (not `Agent`), the same density as `channels.manage`.
Viewing synced records reuses `customers.read`.

## Schema impact

Three new tables (`erp_configs`, `erp_customer_links`,
`erp_synced_records`) plus a seed for `erp.manage` — two migrations
(schema, then permission-seed), matching the established two-migration
shape whenever a milestone adds both (see `docs/database/schema.md`).

## Verification performed

34 new tests added (458 → 492 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_erpnext_client.py` (6 tests) — `create_customer`'s
  request shape and optional-field omission, `list_records`'s filter
  construction and empty-response handling, health-check true/false.
- `tests/integration/test_erp_configs_api.py` (6 tests) — CRUD,
  credentials/webhook-secret excluded from every response, soft delete,
  and `erp.manage` permission gating against the Agent role.
- `tests/integration/test_erp_sync_service.py` (11 tests) — no-op
  without an active config, customer creation + link on the happy path,
  idempotency across two calls, `sync_customer_or_raise`'s 503-equivalent
  error, `pull_records`'s unconfigured/not-yet-linked error paths and its
  happy path caching two records, and webhook ingestion's secret
  rejection, unknown-config rejection, customer resolution via the link
  table, and a missing `"name"` field's `ValueError`.
- `tests/integration/test_erp_webhooks_and_customer_api.py` (8 tests) —
  the webhook route's valid/invalid/missing-secret/unknown-config paths
  over real HTTP, and the customer-scoped sync/pull/list endpoints
  including the 503 unconfigured path and `customers.read`-only access
  to the read endpoint.
- `tests/integration/test_erp_sync_consumer.py` (3 tests) — silent no-op
  without ERP configured, a successful auto-sync, and an ERPNext-side
  failure that doesn't propagate.

Both migrations (`c9d0e1f2a3b4`, `d0e1f2a3b4c5`) were verified against
the real running Postgres via `docker compose exec backend alembic
upgrade head`, then a two-step downgrade and re-upgrade cycle. A new
`erp-sync-consumer` service was added to both `docker-compose.yml` and
`docker-compose.prod.yml`.
