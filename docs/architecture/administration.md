# Administration

M25 of the roadmap, closing Phase 5 (Reporting & Ecosystem). Company
profile/settings management, plugin registry introspection, and an
export capability for the audit log viewer that's existed since M9.

## Scope: backend only, deliberately

Every milestone from M15 through M24 this build cycle shipped backend
only — no frontend UI, since the frontend has been out of scope for this
entire arc of work. "Administration console" reads as a UI concept, but
building a full admin frontend here would be wildly disproportionate to
every other milestone's scope and is properly a dedicated frontend phase
of its own, not a sub-task squeezed into one backend milestone. M25
delivers exactly the APIs a console UI would need — company
configuration, plugin visibility, audit log export — with no client for
them yet, consistent with M15-M24.

## Company profile and settings

`Company` gains a `settings: dict[str, Any]` JSON column — a portable
blob (like `Customer.custom_fields`) rather than named columns for
timezone/business-hours/branding/etc., since the exact set of admin
console settings is expected to grow and none of it needs to be
queried/filtered on at the database level. `GET /company` is gated by
authentication alone (no `company.manage` needed) — a company's name and
settings are shared, company-wide information every member already has
implicit visibility into (not a personal record the way a `Notification`
is), so viewing it is a baseline capability of any authenticated user in
the company. Editing (`PATCH /company`) requires `company.manage` — a
permission that has existed in the catalog since M2 but was never wired
into an actual endpoint or the `Admin` role's default permission set
until now; both gaps are closed by this milestone (added to
`DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]`, a Python-side default
applied only to newly created companies going forward — existing
companies' `Admin` roles are the customizable defaults the RBAC design
already treats as such, not something a migration retroactively grants).

## Company logo upload

Added later (Enterprise Readiness & UX milestone, Priority 2 item 10):
`branding.logo_url` — a plain string the operator had to paste a link
into — is replaced by a real upload. `POST /company/logo` (multipart,
`company.manage`) validates the file against its own tighter limits
(`logo_max_size_bytes`/`logo_allowed_content_types` in `core/config.py` —
2 MiB, PNG/JPEG/WebP only, deliberately smaller/narrower than the generic
attachment upload's 25 MiB/document-inclusive allow-list, since a logo is
always a small raster image), stores it in the same MinIO bucket
attachments use (`AttachmentStore`, a `logos/` key prefix) via
`CompanyService.upload_logo`, and persists only the storage key and
content type into `settings.branding` — never a client-supplied URL.
`GET /company/logo` streams the bytes back (any authenticated member, not
`company.manage` — a logo is display-only branding, not sensitive data);
`DELETE /company/logo` removes it. The bucket isn't public-read, so the
frontend fetches this authenticated and renders it via a blob URL
(`useCompanyLogoUrl`), the same pattern already used for message
attachments — not a direct `<img src>` to a raw storage URL. Re-uploading
best-effort deletes the previous object rather than accumulating orphans.

## Plugin registry introspection

`GET /admin/plugins` (`company.manage`) reports what's actually
registered across every one of this platform's four
registry-keyed-by-string plugin systems — `ChannelRegistry`,
`SmsGatewayRegistry`, `AiProviderRegistry`, `WorkflowActionRegistry` —
plus which AI provider is currently active
(`settings.ai_provider`). This is read-only introspection of process
state that already exists; no new registry, no new plugin kind.

One real gap this surfaced: `WorkflowActionRegistry` was only ever
populated in the `workflow-engine-consumer` process (via
`import blinkengage.application.workflow_actions` in that module), never
in the main API process — nothing before this endpoint needed to read
that registry from the API side. `api/v1/endpoints/admin.py` adds the
same blanket import locally, scoped to exactly the one endpoint that
needs it, rather than adding it to `router.py` for every route.

## Audit log export

`GET /audit-logs` gained an `export=pdf|xlsx` query parameter, reusing
the exact same generic `render_pdf_table`/`render_excel_table` renderers
M23 built for Reports & Analytics export — no new rendering code, just a
new caller. Capped at 10,000 rows
(`_EXPORT_ROW_LIMIT`): an export is a human opening a downloaded file,
not a paginated API response, so an unbounded query here would risk
loading an unreasonable number of rows into memory for one request in a
way normal pagination already prevents.

## Schema impact

One column added to an existing table (`companies.settings`) — no new
tables, no new permission migration (`company.manage` already existed in
the catalog since M2's `f2df1379a476`).

## Verification performed

10 new tests added (492 → 502 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/integration/test_company_api.py` (5 tests) — authentication
  required, the Owner viewing the profile, an Agent able to view but not
  edit (403 on `PATCH`), a full update of name + settings, and a partial
  update leaving previously-set settings untouched.
- `tests/integration/test_admin_plugins_api.py` (3 tests) —
  authentication required, `company.manage` gating against the Agent
  role, and the registry snapshot actually listing real registered
  channel types/SMS gateways/AI providers/workflow actions.
- `tests/integration/test_audit_logs_api.py` (+2 tests) — the existing
  file's PDF and Excel export paths, verified by magic-byte signature and
  content-type (same verification style M23's report exports use).

The migration (`e1f2a3b4c5d6`) was verified against the real running
Postgres via `docker compose exec backend alembic upgrade head`, then a
downgrade and re-upgrade cycle. No docker-compose changes were needed —
no new consumer process, no new runtime dependency.
