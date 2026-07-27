# SLA Builder

Added 2026-07-27 (Priority 1, Item 1 of the "Enterprise Readiness & UX"
roadmap — the Product & UX Review's "SLA is a scoreboard, not a
safeguard" finding). Lets each company define its own SLA policies —
business-hours-aware response/resolution targets, warning thresholds,
and automatic escalation — instead of the flat, wall-clock-only,
detection-only pair of minute fields every queue had before.

Builds additively on Phase 2/M14's existing infrastructure (queue-level
SLA targets, the Celery-beat breach sweep, the SLA report) rather than
replacing it — see "What already existed" below.

## Data model

```
sla_policies                          holidays
-------------                         --------
id (PK)                               id (PK)
company_id (FK, cascade)              company_id (FK, cascade)
name (unique per company)             name
description                           date (unique per company)
first_response_target_minutes         recurs_annually
resolution_target_minutes
warning_threshold_percent (1-100)     queues.sla_policy_id (FK, SET NULL)
business_hours_aware (bool)           -----------------------------------
escalation_rules (JSON list)          Nullable — a queue with no assigned
is_active (bool)                      policy keeps using its own legacy
                                       first_response_target_minutes/
                                       resolution_target_minutes fields
                                       unchanged (plain wall-clock, no
                                       warning, no escalation). An
                                       assigned policy takes over
                                       entirely; the legacy fields are
                                       simply ignored while it's set.

conversations.sla_first_response_warned_at (nullable) — new
conversations.sla_resolution_warned_at (nullable)     — new
```

`escalation_rules` is a JSON list of `{trigger: "warning"|"breach",
action: "reassign_queue"|"reassign_agent"|"notify", ...action-specific
params}` — see `api.schemas.sla.EscalationRule` for the exact validated
shape (which extra field each action requires) and "Escalation" below
for why this isn't Workflow-Engine-backed.

## What already existed (Phase 2/M14), reused unchanged

- `Queue.first_response_target_minutes`/`resolution_target_minutes` —
  now the *fallback* for a queue with no `sla_policy_id` assigned.
- The Celery-beat sweep (`infrastructure.tasks.sla_sweep_task
  .check_sla_breaches`, every minute) and its idempotency columns
  (`sla_first_response_breached_at`/`sla_resolution_breached_at`).
- The `conversation.sla_breached` domain event.
- `GET /reports/sla` and its dashboard panel — purely retrospective
  reporting, untouched by this milestone.
- `Company.settings.business_hours` (enabled flag + per-weekday
  open/close/closed schedule) and `Company.settings.timezone` — both
  existed, fully validated, with their own settings-tab UI
  (`BusinessHoursSettingsPanel.tsx`), but **nothing read them**. Its own
  on-page copy literally said "reserved for future SLA/routing use."
  This milestone is that future use.

## Business-hours-aware deadline calculation

`domain/business_hours.py` — pure Python, no persistence or framework
dependency (same reasoning as `domain/rbac.py`). Two entry points:

- `resolve_schedule(settings, holiday_dates=[...], recurring_holidays=[(month, day), ...])`
  → a normalized `BusinessHoursSchedule`, built once per company per
  sweep run (cached — see "Performance" below) rather than re-parsed
  per conversation.
- `add_business_minutes(start, minutes, schedule)` — the deadline
  calculator. Skips closed weekdays, holidays, and outside-hours gaps
  entirely: a conversation created 11pm Friday with a 60-minute target
  and 9-5 weekday hours deadlines 10am Monday, not midnight Friday. A
  `start` that itself falls outside business hours is clipped forward to
  that day's own open time before spending any of `minutes`. Equivalent
  to plain `start + timedelta(minutes=minutes)` when business hours
  aren't enabled — "not enforced" means every moment counts as open.

Holidays combine two shapes: a fixed calendar date (`Holiday.date`,
`recurs_annually=False`) or a (month, day) pair matched every year
regardless of year (`recurs_annually=True`, e.g. "New Year's Day") — so
an Owner doesn't have to re-enter fixed holidays annually.

13 unit tests (`tests/unit/test_business_hours.py`) cover: disabled
business hours, open/closed weekday boundaries (close is exclusive),
fixed and recurring holidays, same-day completion, clipping a start
before opening time, skipping a weekend, skipping a holiday,
timezone-awareness (a UTC evening timestamp landing on the *next* local
business day in a UTC+11 zone), and the all-days-closed safety-cap error.

## Warning thresholds

Each policy has a `warning_threshold_percent` (default 80). Once that
percentage of a target has elapsed with no response/resolution yet,
`SlaMonitorService` publishes `conversation.sla_warning` exactly once
per breach type — mirroring the existing breach idempotency pattern via
two new columns (`sla_first_response_warned_at`/
`sla_resolution_warned_at`). A queue with no assigned policy (using the
legacy flat fields) has no warning concept at all, preserving its exact
pre-existing breach-only behavior.

`conversation.sla_breached`'s payload gained a `conversation_id` field
it was missing before this milestone (a real gap: every other
conversation-touching event already carried it, and no consumer could
have worked without it) — `conversation.sla_warning`'s payload matches
the same shape, plus `warning_threshold_percent`.

## Escalation

Each policy's `escalation_rules` executes **directly** against
`ConversationService`/`NotificationService` — the exact same functions a
Workflow Engine action calls — rather than generating `WorkflowDefinition`
rows for the existing Workflow Engine (M19) to pick up. Considered and
rejected: `WorkflowActionRegistry` actions are directly callable without
a `WorkflowDefinition` row already, so the engine/consumer add no
capability here; the audit-trail win (`WorkflowRun` history) wasn't
worth managing hidden, policy-synchronized `WorkflowDefinition` rows for
a milestone already covering eight other sub-features, and — critically
— **no Workflow authoring UI exists anywhere in this codebase** (only
its raw JSON API), so building an Escalation Rules UI was required
either way; reusing the engine wouldn't have saved any frontend work.

Three actions today: `reassign_queue`, `reassign_agent` (both call
`ConversationService.update()`, the same lighter-weight path the
existing `assign_to_queue`/`assign_to_agent` workflow actions already
use — not `.transfer()`, so no `ConversationTransfer` audit row is
written, matching those actions' existing behavior rather than
introducing a new discrepancy), and `notify` (calls
`NotificationService.create()` per recipient, `notification_type=
"sla_escalation"`). A rule's failure (e.g. a since-deleted target agent)
is caught and logged per-rule, never aborting the sweep for any other
conversation.

## Queue assignment

`Queue.sla_policy_id` (nullable FK, `ondelete="SET NULL"`) — set via the
existing `POST/PATCH /queues` endpoints (a new optional field, not a new
endpoint). `QueueService` validates the policy belongs to the same
company before assigning it (`EntityNotFoundError` otherwise) — the
existing `department_id` field on this same schema has no equivalent
cross-tenant check, but a queue silently running another company's SLA
policy (wrong targets, wrong escalation recipients) is a correctness bug
worth the extra query, unlike an organizational label.

**Known limitation, matching `department_id`'s existing identical
gap**: `PATCH /queues/{id}` has no way to *clear* an assigned policy
back to unset — like every other optional field on this request, `null`
means "leave unchanged," not "clear." Reassign to a different policy, or
delete the queue and recreate it, in the meantime.

A policy can't be deleted while any queue is still assigned to it
(`SlaPolicyHasAssignedQueuesError`) — same reasoning as blocking role
deletion while members still hold it: the FK's `SET NULL` wouldn't break
anything at the database level, but would silently strip every assigned
queue's SLA config with no warning.

## Preview

`POST /sla-policies/preview` (`sla_policies.read` — a read-only
calculation, no state changes) takes a policy id and a hypothetical
`starts_at`, returning the four computed timestamps (first-response/
resolution × warning/deadline) using the exact same
`resolve_schedule`/`add_business_minutes` calculation the real sweep
uses — so what an admin previews is exactly what would happen in
production, not a separate approximation.

## RBAC

New permission pair `sla_policies.read`/`sla_policies.manage` (not folded
into `queues.manage`, even though a policy is assigned to queues — SLA
policies/holidays/escalation rules are a richer, separate configuration
surface a company may want a narrower set of people editing). Wired into
`DEFAULT_ROLE_PERMISSIONS`: Owner (both, via the full-catalog set), Admin
(both, matching its access to `queues.manage`), Agent (`.read` only,
matching its existing `queues.read`-but-not-`.manage` pattern) — picked
up automatically for every existing company via the permission-sync
mechanism (`docs/architecture/auth-rbac.md`), no migration/backfill
needed for the grants themselves.

## Frontend

A new "SLA Builder" page (`features/sla/`, nav + route gated on
`sla_policies.read`; create/edit/delete additionally gated on
`sla_policies.manage`, checked client-side same as Queues/Roles) with
three tabs:

- **Policies** — table + create/edit dialogs (targets, warning
  threshold, business-hours-aware switch, and an inline escalation-rule
  editor: add/remove rows, each with a trigger/action pair and the
  action's own target field — queue picker, agent picker, or a
  multi-select notify-recipient picker).
- **Holidays** — table + create dialog (name, date, "repeats every
  year"). Deliberately create/delete only for this first version, no
  edit — deleting and re-adding is an acceptable v1 workflow for a
  low-frequency admin action, matching this codebase's own precedent of
  documenting a deliberately narrower v1 (e.g. Queues & Routing's
  Required Skills deferral) rather than silently leaving a gap.
- **Preview** — policy picker + a datetime input, calling the preview
  endpoint and rendering all four computed timestamps.

The existing Queue create/edit dialogs gained an "SLA policy" picker
(`None (use targets below)` + every company policy), with the two flat
target fields' helper text updated to say they're ignored while a policy
is assigned — no new dialog needed, this is one more field on the
existing form.

## Verification performed

37 new backend tests: 13 for `domain/business_hours.py` in isolation
(SQLite-free, no DB), 9 for the updated `SlaMonitorService` (business-
hours-aware vs. legacy-fallback deadlines, warning-then-breach ordering,
both escalation actions, a holiday delaying a deadline, the
`conversation_id` payload regression), 15 for the full `sla-policies`/
`holidays` API surface (CRUD, name/date uniqueness conflicts, escalation
rule parameter validation, delete-blocked-while-assigned, cross-tenant
scoping, permission gating, the preview endpoint with and without
business hours). Frontend: 8 new tests for the SLA Builder page
(axe-checked) plus 1 more for the Queue dialog's policy picker — 210
frontend tests total.

Live-verified against the real Docker stack: rebuilt and recreated
`backend`, `celery-worker`, and `celery-beat`, confirmed the new
migration applied cleanly against real Postgres. Via curl: enabled real
Mon-Fri 9-5 UTC business hours, created a business-hours-aware policy,
confirmed the preview endpoint correctly rolled a Saturday-noon start
forward to Monday 10am (not Saturday 1pm); assigned the policy to a
queue and confirmed deleting it while assigned is blocked (400); created
a recurring holiday. Manually invoked the actual Celery task function
(`sla_sweep_task._check_sla_breaches_async`) inside the running
container against real Postgres/Redis/MinIO to confirm its expanded
`ConversationService`/`NotificationService` wiring constructs and runs
without error, not just the `SlaMonitorService` logic in isolation.
Also confirmed visually via Playwright screenshots: the Policies,
Holidays, and Preview tabs, with the Preview tab's screenshot showing
the exact same Monday-10am/9:30am result the curl check produced,
end-to-end through the real UI.

## Known limitations / deferred

- No way to clear `Queue.sla_policy_id` back to unset via the API (see
  "Queue assignment" above) — matches `department_id`'s pre-existing
  identical limitation on the same schema.
- Escalation's `notify` action targets explicit user ids only — there is
  no "notify this queue's supervisor" primitive anywhere in this
  codebase yet (no `Queue.supervisor_id`/`Department.manager_id` column
  exists), so an admin must pick specific people.
- No in-context SLA countdown badge on the Inbox/conversation view yet —
  the breach/warning timestamps exist on `Conversation` and are fully
  computed, but nothing renders them outside the SLA Builder's own
  preview tool and the existing retrospective SLA report.
- Holidays have no edit, only create/delete (see "Frontend" above).
