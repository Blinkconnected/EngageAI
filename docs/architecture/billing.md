# Billing

Blink Engage bills for **actual usage**. There are no subscription
plans, no seat licensing, and no per-agent, per-department or
per-channel limits — a company pays for what it consumes and nothing
else.

This document describes the billing architecture as it is being built.
It is deliberately staged, and each stage says plainly what exists today
and what does not.

## What changed, and why the history matters

An earlier release shipped a **subscription** model: `billing_plans`,
`subscriptions`, PayPal recurring billing, and a tenant-facing Billing
page. That model was retired before release (migration
`ac1c2974b1aa`) when the product moved to usage-based pricing. It is
recorded here because the tables and their code are in git history at
commit `a399f4d`, and a reader finding references to them elsewhere
should know they are gone on purpose rather than by accident.

**Feature entitlements survived that removal.** They used to resolve
partly from `billing_plans.features`; they now resolve from a platform
administrator's per-company overrides (`companies.feature_overrides`)
plus the catalog default in `domain/features.py`. The plan-granted layer
simply disappeared, and its absence means "grants everything" — the same
answer every company without a subscription already got, so no company's
entitlements changed. See the "Feature entitlements" section below.

## Currency

**v1 bills in a single currency: USD.** Multi-currency is not
implemented and is not partially implemented — nothing converts, and
there is no exchange-rate concept anywhere.

But single-currency and currency-hardcoded are different things, and
only the first is intended. Everything that touches an amount goes
through one module on each side:

| | Module | Holds |
|---|---|---|
| Backend | `domain/money.py` | `BILLING_CURRENCY`, precision, rounding, formatting |
| Frontend | `shared/money.ts` | `BILLING_CURRENCY`, `formatMoney`, `formatUnitPrice` |

Introducing a second currency later is a change to those two files and
the rows that reference them, not an archaeological dig for stray
`"USD"` literals and `$` signs. A unit test
(`tests/unit/test_money.py::test_nothing_outside_this_module_hardcodes_the_currency`)
fails the build if a currency literal appears anywhere else in the
backend source.

Currency is a **constant, not an environment variable**, on purpose. An
env var would imply that setting `BILLING_CURRENCY=EUR` produces a
working system. It would not — nothing converts — and a setting that
appears to work while silently mispricing is worse than a constant that
is honest about the build being single-currency.

## Precision and rounding

Money is `NUMERIC(18, 6)`. Never a float, and never `NUMERIC(_, 2)`.

**Six decimal places** because unit prices are genuinely sub-cent. A
conversation at $0.050 already needs three; a future metric priced per
1,000 AI tokens will need more. A two-place column rounds $0.0005 to
$0.00 and bills nothing at all.

**Eighteen digits** because the same type carries both a unit rate and
an aggregate total, leaving room for any realistic invoice while staying
narrow enough to index.

**Floats are excluded categorically.** 0.1 has no exact binary
representation, so float arithmetic on money produces totals that
disagree with their own line items — a defect a customer disputes and an
auditor rejects.

### Round once, at the end

This is the rule most of `domain/money.py` exists to enforce:

```python
line   = money.multiply(quantity, unit_price)   # full precision, no rounding
subtotal = money.total(lines)                   # full precision, no rounding
charge = money.to_billable_amount(subtotal)     # the ONE rounding step
```

Rounding earlier is the classic billing bug. Round each of 10,000
conversations at $0.0005 to cents and every one becomes $0.00, so the
invoice is zero instead of $5.00. `multiply()` and `total()` therefore
compute at a working precision *wider* than the storage scale, and
`to_billable_amount()` is the only function that rounds to what a
customer is actually charged.

Rounding is **`ROUND_HALF_UP`** (0.005 → 0.01), not Python's default
banker's rounding. Half-even is defensible statistically and required
for tax in some jurisdictions, but it surprises a customer reading an
invoice. Taxes are out of scope for this phase; if a jurisdiction later
demands half-even, `to_billable_amount()` is the single place to change.

`to_storage()` quantizes to the column scale when an amount is
persisted, so what is written is exactly what a later read returns
rather than relying on the database to truncate and silently disagreeing
with the value in memory.

### On the wire

Amounts cross the API as **strings**, not JSON numbers. A JSON number
becomes a JavaScript float in the browser, which reintroduces exactly
the drift `Decimal` exists to prevent. The frontend never does
arithmetic on money — it formats and displays; the server is the only
thing that computes.

`formatUnitPrice()` exists separately from `formatMoney()` because a
sub-cent rate must not be rounded away in an admin table: $0.05 and
$0.0005 are a hundredfold apart and both render as "$0.05" / "$0.00" at
display scale, making one look identical to the other, or free.

An unset amount renders as `$—`, never `$0.00` — "unknown price" and
"free" must not look the same.

## Billable metrics

**Metrics are code. Pricing is data.**

The catalog lives in `domain/billable_metrics.py`. A metric may only
exist if the platform actually knows how to measure it, so adding one
requires a release. Administrators configure prices, profiles and
per-company overrides — all data — but cannot invent a metric.

That is not gatekeeping for its own sake. A metric an operator could
type in would have no meter behind it, so it would either charge nothing
(a price that silently does nothing) or invite someone to assume usage
was being captured when it was not.

| Code | Unit | Measured today |
|---|---|---|
| `CONVERSATION` | conversation | yes |
| `AI_ASSISTED_REPLY` | reply | yes |
| `AI_AUTOPILOT` | reply | yes |
| `VOICE_MINUTE` | minute | **no** |
| `STORAGE_GB` | GB-month | **no** |

Each metric carries a code, display name, unit and description — the
metadata the pricing admin screens render.

### Why unit is explicit

"Price per unit" is meaningless until you know what a unit is, and the
answer differs in kind: a conversation is discrete and countable, a
minute is continuous and fractional, a GB-month is a rate over time that
must be *sampled* rather than counted. Carrying `MeasurementUnit` means
a screen renders "$0.05 / conversation" or "$0.002 / minute" from data
rather than every caller hardcoding a suffix.

### Declared but not priceable

`VOICE_MINUTE` and `STORAGE_GB` are real roadmap metrics with **no meter
in this codebase** — there is no voice channel, and nothing samples
attachment storage. They are declared anyway so the pricing schema is
designed against the full shape of the problem (a fractional unit and a
sampled-rate unit, neither of which a per-conversation count exercises).

They are marked `PLANNED`, and `is_priceable()` returns false for them,
so the pricing API refuses to attach a rate. Without that gate an
operator could configure voice pricing, see no charges, and reasonably
conclude billing was broken. A metric becomes priceable in the same
release that ships its meter.

Codes are **stable public identifiers**. They appear in pricing rows,
usage records and invoices, so renaming one silently reprices history.
Add metrics; never rename them. A test pins the current set for exactly
this reason.

## Feature entitlements

A platform administrator controls which product features each company
may use. This is *not* pricing: it answers "has this company been given
this capability?", not "what does it cost?".

Resolution is: an explicit per-company override, else the catalog
default in `domain/features.py`, which is `True` for every feature. So
an installation where nobody has touched entitlements has every feature
on for everyone — entitlement is opt-in restriction, never opt-in
permission.

Overrides live in `companies.feature_overrides`, a column only the
platform API writes — deliberately not inside the tenant-editable
`Company.settings` blob, since a company must never be able to grant
itself a capability it was not given.

Refusals answer **402 Payment Required**, not 403. "You have permission;
the workspace does not have this capability" is a different sentence,
and 403 would send an administrator to edit roles that were never the
problem.

Enforced at router registration in `api/v1/router.py` (whole routers for
`ai`, `erp`, `workflows`, `knowledge_base`, `sla`) and by
`deps.require_export_feature` for report downloads, which bites only
when an `?export=` parameter is present so a company without exports
still sees its dashboards on screen.

Endpoints: `GET /platform/features`,
`GET|PUT /platform/companies/{id}/features`. The PUT replaces the whole
override map, so omitting a key clears its override — with a merge there
would be no way to undo one.

## The pricing engine

Three levels, most specific first. The engine always resolves
automatically:

| Priority | Scope | Table |
|---|---|---|
| 1 | Company override | `pricing_rates` (`scope='COMPANY'`) |
| 2 | Pricing profile | `pricing_rates` (`scope='PROFILE'`) |
| 3 | Global default | `pricing_rates` (`scope='GLOBAL'`) |

Precedence is declared once, as data, in `domain/pricing_scope.py`.
Three places each re-deriving "which one wins" is three places that can
disagree, and a pricing engine that disagrees with itself bills the
wrong amount.

### The decision is a pure function

`domain/pricing.py::select_price` takes the candidate rows and an
instant and returns the winner. It touches no database and no event
loop, so the rule is unit-testable directly — and, more importantly, it
is the *only* implementation. The operator's console preview and the job
that eventually rates usage call the same function. A console showing
$0.040 while billing charges $0.050 is worse than either number alone.

The repository's job is only to load a superset of candidates.
`resolve_many` does that in **three queries regardless of batch size**
(which companies exist, their profile assignments over the window, every
candidate rate intersecting it), then decides per request **at that
request's own instant**. A run pricing a month of usage has a different
instant per row; forcing one instant on the batch would silently
re-rate.

### Effective dating

Every rate and every profile assignment carries
`[effective_from, effective_until)` — **half-open**. Inclusive lower,
exclusive upper. With an inclusive upper bound the instant one rate ends
and the next begins matches *both*, and the resolver has to guess.
`effective_until IS NULL` means "until further notice" — genuinely
open-ended, not a sentinel date, because a sentinel date is a date
somebody eventually reaches.

All instants are timezone-aware UTC, and a naive one is rejected with
422 rather than assumed. "Effective from 1 August" is a different moment
in Auckland and Los Angeles, and a conversation at 00:30Z would price
differently depending on which the server guessed.

> SQLite has no timezone type, so `DateTime(timezone=True)` returns
> *naive* values there while PostgreSQL returns aware ones — and
> comparing the two raises `TypeError`. The pricing tables therefore use
> `UtcDateTime`, a type decorator that guarantees aware values out of
> either backend. Effective dating decides what a customer is charged;
> it must behave identically on the production database and the one the
> tests run against.

### History is never rewritten

A rate row is **written once**. `unit_amount`, `scope`, `metric_code`
and `effective_from` are immutable; the only post-insert writes are
closing `effective_until` and voiding a not-yet-effective row.
`PricingRateRepository` exposes no `save`, no `update`, no `delete` —
the guarantee is enforced by giving the rest of the application no
method with which to break it.

"Editing a price" closes the current row at an instant and inserts a
successor, in one transaction. Re-resolving last month therefore always
yields last month's rate. **Old invoices are never recalculated with new
prices.**

Assignments are a *table*, not a `companies.pricing_profile_id` column,
for the same reason one level up: "which profile was this company on in
April?" must be answerable in June, or re-rating April silently walks
June's profile.

### Overlap is impossible, not merely rejected

Three layers, because an engine that silently picks one of two prices is
worse than one that stops:

1. PostgreSQL `EXCLUDE USING gist` constraints on both `pricing_rates`
   and `company_pricing_profile_assignments`. `COALESCE` to the nil UUID
   because `NULL = NULL` is not true — otherwise two GLOBAL rows for the
   same metric would never conflict, which is the single most important
   case. `tstzrange(..., '[)')` matches `covers()` exactly, so the
   constraint and the predicate agree by construction.
2. `PricingService` pre-checks overlap, so the operator gets a 409
   naming the conflict rather than a raw integrity error — and so the
   rule still holds on SQLite, where the constraint does not exist.
3. `select_price` raises `AmbiguousPricingError` if two equal-precedence
   rates ever do cover the same instant. There is deliberately **no
   tiebreak**: "newest wins" would return a plausible number and hide
   the misconfiguration.

Verified live against PostgreSQL — an overlapping insert is rejected, an
adjacent one is accepted.

### Audit

`pricing_audit_log` records every change with old value, new value,
changed by, changed at, effective date and reason. It is **append-only**
and never deleted.

A dedicated table rather than the existing `audit_logs`, for two
structural reasons:

- `audit_logs.company_id` is NOT NULL and its consumer skips events with
  no company. A **global** price change belongs to no tenant, so the
  most dangerous change in the system would produce zero audit rows.
- That trail is asynchronous (outbox → relay → broker → consumer).
  "Never deleted" cannot rest on a pipeline this codebase has already
  seen stall. The audit row is written on the same session as the price
  row: they commit together or neither exists.

Changes are *also* published as domain events, which is what carries a
tenant-visible change into that tenant's own audit log. The two
mechanisms are independent by design.

`changed_by_email` and `changed_by_name` are **denormalized at write
time**. The foreign key is `SET NULL` so the trail outlives the user
row — but a bare NULL turns every price an ex-operator ever set into an
anonymous change, and "changed by" is a required field of this
requirement.

Immutability is enforced three ways: no `TimestampMixin`/`SoftDeleteMixin`,
a repository exposing only `add` and reads (asserted by a test over its
public method names), and a PostgreSQL trigger that rejects UPDATE and
DELETE outright — verified live.

### Guardrails worth knowing about

- **A metric with no meter cannot be priced.** `VOICE_MINUTE` and
  `STORAGE_GB` return 409. Otherwise an operator configures a rate, sees
  no charges, and reasonably concludes billing is broken.
- **An unknown metric is 404, a known-but-unmeasured one is 409.** A typo
  and "we can't measure that yet" are different problems.
- **No price anywhere is a 503, never a zero.** A silent zero is a
  revenue leak that looks exactly like a working system.
  `GET /platform/pricing/health` lists any measured metric without one,
  so the gap is visible before metering ships.
- **Optimistic concurrency.** Every write carries either
  `expected_current_rate_id` or `expect_no_current_rate`; without one,
  two operators editing the same price both succeed and the second
  silently overwrites the first.
- **Backdating is possible but never accidental** — it needs
  `allow_backdating` *plus* a reason, and is recorded distinctly. Refuse
  it outright and an operator who genuinely needs it (a contract signed
  on the 10th, effective the 1st) does it in `psql`, unaudited.
- **"Apply now" has a one-minute grace window.** Without it "effective
  immediately" is unrepresentable: by the time validation runs, the
  instant the client called *now* is already past, and the write is
  refused as a backdate.
- **The Default profile carries no prices.** It is assignable and appears
  in every list because the requirement names it, but writing a rate
  against it returns 409 pointing at the global price — one concept, one
  place to edit.

### API

All under `/api/v1/platform/pricing`, gated at router registration by
`get_platform_auth`. Never `require_permission` (platform authority is
outside the tenant RBAC catalog) and deliberately never
`require_feature` — a company that lost the `ai` entitlement must still
be priceable.

| Endpoint | Purpose |
|---|---|
| `GET /metrics` | The catalog. Read-only: metrics are code |
| `GET /profiles` | The pricing tiers |
| `GET /effective` | Resolved price per metric, with what it shadowed |
| `PUT /global/metrics/{code}` | Update Global Pricing |
| `PUT /profiles/{id}/metrics/{code}` | Price a tier |
| `PUT /companies/{id}/metrics/{code}` | Update Company Pricing |
| `POST /companies/{id}/metrics/{code}/end` | Remove an override, effective-dated |
| `PUT /companies/{id}/profile` | Assign Pricing Profile |
| `POST /rates/{id}/void` | Retract a not-yet-effective rate |
| `POST /resolve` | **Resolve Usage Price** — the billing engine's entry point |
| `GET /history` | The audit trail |
| `GET /rates` | Full timeline for one target |
| `GET /health` | Metrics with no price |

`POST /resolve` takes a per-item `occurred_at` and returns **unrounded**
amounts: rounding happens once, when an invoice line is built.
`strict: false` quarantines unresolvable items instead of failing the
run, so a nightly job prices what it can — the unsafe mode is opted
into, never defaulted.

Removing an override is a POST, not a DELETE: it *writes* an
effective-dated boundary and an audit row, and a DELETE reads as "erase
this", which is the one thing it must never do.

## The usage engine

Migration `3cca1f08ef5d`. Three tables, and the split between them is
the design:

| Table | Holds | Mutability |
|---|---|---|
| `usage_records` | One row per billable occurrence | Append-only |
| `billing_periods` | One company's billing month | Created once, closed once |
| `usage_period_lines` | **The snapshot** | Written once, at close |

### Metering happens off the event bus

`usage_metering_consumer` listens to events the product already
publishes. Billing never sits in the path of the thing being measured —
a customer's message must be delivered whether or not billing is
available, and metering must never be able to slow or roll it back.

| Event | Metric | Idempotency key |
|---|---|---|
| `conversation.created` | `CONVERSATION` | `CONVERSATION:<conversation_id>` |
| `conversation.autopilot_replied` | `AI_AUTOPILOT` | `AI_AUTOPILOT:<message_id>` |

The key is derived from the occurrence's own identifiers — never a
timestamp, never a random value — and is unique in the database. The
relay delivers at-least-once and retries for days, so the consumer *will*
see the same conversation again; a redelivery finds the existing row and
does nothing.

`AI_ASSISTED_REPLY` is deliberately **not** metered yet. Its event fires
for every message, and billing off a high-volume event needs its own
look at cost and idempotency. It stays unpriced until its meter ships —
the same rule the metric catalog enforces for `VOICE_MINUTE`.

### Usage cannot move between months

A record's period comes from when the usage **happened**
(`event.occurred_at`), not from when the meter reported it. A redelivery
three days later still lands in the right month.

If that period has already closed, the record is **refused and counted**
(`billing_periods.late_record_count`), never redirected into the open
period. Silently folding it forward would move revenue between months
and make a closed set of books disagree with the records behind it. A
late meter is a visible problem, not a quiet distortion.

Exactly one period may be `OPEN` per company, enforced by a partial
unique index — two would split a month across two bills with nothing to
say which is right. Ranges are half-open `[start, end)`, so a
conversation at midnight on the 1st is billed once, not twice.

### Closing freezes everything

`close_period` resolves each metric's price **once**, computes the
subtotals, writes them as frozen lines, and marks the period closed —
all in one transaction.

Every number an invoice needs is on the line:

| Field | Why it is stored rather than derived |
|---|---|
| `quantity` | What was measured |
| `unit_amount` | What it cost **at the time** |
| `subtotal` | Recomputing at read time means a change to rounding silently alters a historical document |
| `rate_id` | The audit chain from a charge back to the decision that set it |
| `metric_version` | How the metric was defined when it was measured |

**An invoice line is a copy of a snapshot line.** Invoice generation
never re-aggregates `usage_records` and never re-resolves a price.
Effective-dated pricing already makes re-resolution *correct*, but
re-resolution still has to happen and every re-run is another chance to
differ; a snapshot makes re-derivation unnecessary, so it cannot be
wrong. A test asserts a closed period's lines are byte-identical after
the price is later multiplied by ten.

Closing is **idempotent**. The state transition is a guarded
`UPDATE ... WHERE status = 'OPEN'`, so exactly one caller wins even if
the job fires twice or two workers pick it up together; the loser
returns the existing snapshot rather than writing a second set of lines.
On PostgreSQL a trigger rejects `UPDATE` and `DELETE` on
`usage_period_lines` outright, so the snapshot survives a `psql` session
too.

Prices are resolved at the **period end**, not at "now": closing a month
late must not apply a rate that came into force afterwards. The Net-21
due date is computed from `period_end` for the same reason — a delayed
or retried job must not move a customer's payment deadline.

Usage with no configured price still gets a line, flagged `unpriced`
with the quantity intact. Dropping it would make the usage vanish from
the bill entirely, which looks exactly like it never happened.

### Metric versioning

`BillableMetric.version` is stamped onto every usage record at
measurement time and carried onto every snapshot line.

The code says *what* is billed; the version says *how it was measured*.
If `CONVERSATION` later starts counting a reopened conversation as a
second one, that is a different meaning for the same code — and anything
already measured still records the definition that produced it, so a
behaviour change cannot reach backwards into a bill. Aggregation groups
by code **and** version, so two halves of a period measured differently
are never silently added together.

Changing a metric's behaviour without bumping its version is the one way
to rewrite billing history.

### The close job

`blinkengage.billing.close_due_periods`, hourly. Not a once-a-month
cron: a monthly job that misses its window — a deploy, an outage, a
clock change — leaves every company's month unclosed until somebody
notices. An hourly sweep that finds nothing costs one indexed query and
self-heals, and each close being idempotent makes running it often free.

### API

Under `/api/v1/platform/usage`, gated by `get_platform_auth`:

| Endpoint | Purpose |
|---|---|
| `GET /companies/{id}/current` | The open period and what has accrued |
| `GET /companies/{id}/periods` | Period history |
| `GET /periods/{id}/snapshot` | The frozen lines |
| `POST /periods/{id}/close` | Freeze a period (idempotent) |
| `POST /records` | A manual correction, deduplicated by a caller-supplied key |

`current` deliberately returns **quantities only, no money**. An
estimate is a different thing from a charge, and a second
subtly-different number beside the frozen ones is how a correct bill
ends up disputed. Estimation belongs to whatever presents it, from the
same resolver.

## The invoice engine

Migration `21fac8ed2cd2`. Six tables: `invoices` / `invoice_lines`,
`credit_notes` / `credit_note_lines`, `payments` /
`payment_allocations`, plus `document_number_sequences`.

### An invoice is a copy

Generation reads a **closed** period's frozen snapshot and copies each
line. Nothing is re-aggregated from usage records; nothing is re-priced.
An open period cannot be invoiced at all — billing a month whose usage
is still accruing would bill a number that is still moving.

Generation is idempotent: a period that already has an invoice returns
it, backed by a unique constraint on `billing_period_id`. The failure
that guards against is charging a customer twice for one month.

Rounding happens exactly **once**, on the invoice total. Lines stay at
full precision, so the lines always sum to the total.

### Numbers

`INV-2026-000001`, year-scoped, from a counter table under a row lock.

A counter table rather than a database sequence, deliberately:
sequences are explicitly *not* transactional, so a rolled-back issue
would consume a value and leave a hole. An invoice series with holes is
something an auditor makes somebody explain.

The number is assigned **at issuance**, never at creation — a draft that
burned a number and was then discarded would leave the same hole. A
cancelled invoice keeps its number consumed forever; reusing it would
mean two documents shared a number, which is exactly what the series
exists to prevent.

Credit notes have their own series, `CN-2026-000001`.

### The state machine

```
DRAFT ──▶ ISSUED ──▶ PAID
  │         │  └───▶ OVERDUE ──▶ PAID
  └────────▶└──────▶ CANCELLED
```

`domain/invoicing.py` holds the transition table, and it is the only
authority — a state machine enforced only where somebody remembered to
check is not one. Every transition is *also* applied with the current
status in the WHERE clause, so two requests issuing the same draft, or
the overdue sweep racing a payment, cannot both succeed.

`OVERDUE` is a stored state rather than a date comparison at read time:
it is what people filter and report on, and deriving it means the answer
changes silently at midnight in whichever timezone the reader used.

An overdue invoice that gets paid goes straight to `PAID` — it does not
pass back through `ISSUED`, because "was late, then paid" is the true
history.

`PAID` and `CANCELLED` are terminal. An invoice with payments allocated
to it **cannot** be cancelled: that would leave the payment attached to
a withdrawn document. Use a credit note.

### Immutability

After issuance, an invoice's identity and money never change. Enforced
in three places:

1. **No endpoint exists** that edits an issued invoice or its lines. An
   API offering both an edit and a credit note would make the rule
   advisory.
2. **The repositories have no update or delete** for lines.
3. **PostgreSQL triggers** reject `UPDATE`/`DELETE` on `invoice_lines`
   and `credit_note_lines` outright, and reject any change to a
   non-draft invoice's number, amounts, customer, period or issue date.
   Status, payment progress and cancellation fields still move — those
   are the documented transitions.

### Corrections are credit notes

The only way to change what a customer owes after issuance. The invoice
keeps saying exactly what it said; the credit note is a separate
numbered document that says what was given back. Both exist for anybody
reconciling them later — which is precisely what editing the invoice
would destroy.

A reason is **required**: a credit note nobody can explain is unusable
to whoever finds it. Crediting more than the invoice total is refused,
and a full credit settles the invoice — otherwise a fully-credited
invoice would sit outstanding forever with nothing able to clear it.

Drafts cannot be credited; they are simply changed.

### Payments are independent

A `payment` records money arriving from a company. `payment_allocations`
say which invoices it settles.

That separation is the whole point: one bank transfer can clear three
invoices, an overpayment sits unallocated as a credit balance with no
special case, and a second payment provider plugs into `provider` /
`provider_reference` without touching the invoice tables. Those two
columns are unique together, so a redelivered gateway webhook cannot
record the same money twice.

Allocation refuses to exceed either the payment received or the invoice
outstanding — both would surface later as a balance nobody can explain.

### API

Under `/api/v1/platform/invoices`, gated by `get_platform_auth`:

| Endpoint | Purpose |
|---|---|
| `POST /generate/{period_id}` | Draft from a closed period (idempotent) |
| `GET /{id}`, `GET ?company_id=` | Read |
| `POST /{id}/issue` | Assign the number, freeze |
| `POST /{id}/cancel` | Withdraw (reason required) |
| `POST /{id}/credit-notes` | Correct an issued invoice |
| `POST /payments` | Record money received |
| `POST /payments/{id}/allocate` | Apply it to an invoice |

There is deliberately no update or delete for an invoice.

## The financial audit trail

Migration `c844f6c83199`. One append-only table,
`financial_audit_events`, and it is **the single source of truth for
financial investigations**.

Every creation, state transition, payment allocation, credit note,
cancellation and reversal writes a row:

| Field | Notes |
|---|---|
| `event_type` | Past-tense fact (`invoice.issued`), not a command |
| `entity_type`, `entity_id` | Which document |
| `previous_state`, `new_state` | **Both**, always |
| `actor_user_id`, `actor_email`, `actor_name` | Identity, by value |
| `actor_is_system` | A sweep acted — distinct from "unknown" |
| `occurred_at` | |
| `correlation_id` | Ties one action's events together |
| `reason` | Optional |
| `amount`, `currency`, `details` | What moved, and the specifics |

### Why both states

"It became PAID" does not say whether it was issued or overdue
beforehand, and that difference is exactly what a dispute turns on. The
prior state is captured **before** the UPDATE — reading it afterwards
returns the new one, which made early rows claim a document went from
cancelled to cancelled. A test pins it.

### Correlation

Allocating a payment writes an allocation event *and* an invoice
transition; issuing a credit note writes the note *and* settles the
invoice. Matching those by timestamp stops working the moment two
operators act in the same second, so they share a `correlation_id`.

It comes from a `ContextVar` set per request by `CorrelationIdMiddleware`,
honouring an inbound `X-Correlation-ID` (so a trace that began in a
gateway stays joined) and echoing it on the response so a caller can
quote it. Outside a request — a scheduled sweep, a consumer — one is
generated per operation.

Ambient rather than a parameter threaded through every signature: pass
it by hand and every new code path silently defaults to "no correlation"
the first time somebody forgets an argument.

`GET /platform/invoices/audit/correlation/{id}` answers "what else
changed when that happened", which is usually an investigator's second
question and the hardest to reconstruct without it.

### Why the actor is denormalized

A `SET NULL` foreign key turns every action an ex-employee took into an
anonymous one, and "who did this" is the second question every
investigation asks. Email and name are stored as *values*.
`actor_is_system` distinguishes "a scheduled job did this" from "we
don't know who" — two answers a bare NULL would conflate.

### Immutability

Written on the **same session** as the change it describes, so they
commit together or neither exists. An audit row written on a separate
connection, or published through a broker, can disagree with the thing
it records — and a trail that disagrees is worse than none, because it
will be believed.

The repository exposes `add` and reads only; there is no write endpoint;
and a PostgreSQL trigger rejects `UPDATE` and `DELETE`. A trail that can
be edited is not evidence.

> **Route ordering.** The `/audit*` routes are registered *before*
> `/{invoice_id}`. FastAPI matches in registration order, so with the
> parameterised route first, "audit" is parsed as an invoice UUID and
> every audit request 422s — the same class of bug the PayPal webhook
> route hit earlier.

### API

| Endpoint | Answers |
|---|---|
| `GET /audit/entity/{type}/{id}` | This document's history, oldest first |
| `GET /audit/correlation/{id}` | What else changed in that action |
| `GET /audit?company_id=&entity_type=&event_type=` | Search |

Pricing keeps its own dedicated trail (`pricing_audit_log`) — pricing is
configuration rather than a financial document, and the two are read by
different people asking different questions.

## Not built yet

Stated explicitly so nobody looks for them:

- **Billing states** — Active / Payment Due / Payment Overdue / Payment
  Suspended, as an axis separate from compliance suspension.
- **Payment gateway** — deliberately out of scope until the phases above
  land.
- **Contracts, taxes, discounts, tiered pricing** — later phases.

Company suspension today is the single compliance-style suspension
described in [`platform-admin.md`](platform-admin.md). Splitting it into
a billing axis and a compliance axis belongs to the billing-states phase
above and has not been done.
