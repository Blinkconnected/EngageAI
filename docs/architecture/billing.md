# Billing

Blink Engage bills for **actual usage**. There are no subscription
plans, no seat licensing, and no per-agent, per-department or
per-channel limits — a company pays for what it consumes and nothing
else.

This document describes the billing architecture as it is being built.
It is deliberately staged, and each stage says plainly what exists today
and what does not.

## Status: feature-complete, in maintenance

**The Billing domain is frozen.** The engine (metering, pricing,
invoicing, payments, the ledger and collections), the Billing Console, the
customer's own billing dashboard and Billing Operations are all complete,
and the two customer-facing documents that closed it out — the invoice PDF
and line-based credit notes — are in.

From here billing is maintained, not developed. Bug fixes, security work
and whatever a genuine new business requirement demands; nothing else.
Engineering effort moves to the AI Platform, the Inbox experience, the
Automation Builder, the mobile applications, and Reporting & Analytics.

The "Not built yet" section near the end of this document is the honest
list of what a future requirement would have to reopen this for. It is
short on purpose: everything on it was a deliberate decision to stop, not
something forgotten.

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

Each company is billed in **its own currency**, decided by the country
given at signup: **JOD** for Jordan, USD elsewhere. Adding a currency is
an entry in `CURRENCIES` plus prices to go with it.

This began as a single-currency build with one deliberate seam, and
widening it was a change to `domain/money.py` and the call sites that name
a currency — not an archaeology exercise hunting stray `"USD"` literals.
That was the entire point of routing every amount through one module:

| | Module | Holds |
|---|---|---|
| Backend | `domain/money.py` | `CURRENCIES`, `currency_for`, precision, rounding, formatting |
| Frontend | `features/billing/money.ts`, `features/billingops/format.ts` | how an amount is rendered at its own currency's resolution |

A unit test
(`tests/unit/test_money.py::test_nothing_outside_this_module_hardcodes_the_currency`)
fails the build if a currency literal appears anywhere else in the backend
source — which is what keeps the seam a seam.

There is no `BILLING_CURRENCY` environment variable and never was, on
purpose. An env var would imply that setting `BILLING_CURRENCY=EUR`
produces a working system; it would not, because nothing converts. A
currency is added by adding it to `CURRENCIES` **and giving it prices**,
and a setting that appears to work while silently mispricing is worse than
a constant.

### Decimal places are a property of the currency

USD settles in cents; **JOD settles in fils — three places**. A JOD total
rounded to two is wrong on every line, and 0.035 JOD rounded to 0.04 is a
14% error per conversation. `display_scale` therefore lives on the
`Currency`, and `to_billable_amount()` reads it. `PRICE_SCALE` (6) is
unchanged — that is storage and calculation precision, which is a
different question from how many places a *presented* amount has.

### Nothing converts

A JOD company is priced, invoiced and posted to the ledger entirely in
JOD. No exchange rate is stored, no amount is converted, and the trial
balance is **one set of books per currency** — summing dinars and dollars
produces a number that means nothing, and there is nothing available to
make it mean something.

Because of that, a company's currency is **fixed once it has been
billed**. An invoice states an amount in a currency; a document that
silently changes currency is not a correction, it is a different document
with the same number.

### A rate is priced in a currency

Pricing resolution only considers rates in the company's own currency.
Without that, a Jordanian company would resolve the dollar global default
and be invoiced 0.050 JOD for something priced at $0.050 — a silent
mispricing nothing downstream could detect.

A company with no rate in its currency is **unpriced**, which the usage
engine already reports rather than guessing. That is the correct, visible
failure: a new currency needs prices before anybody in it can be billed.
The JOD global default is seeded at 0.035, set deliberately rather than
converted — a price derived from an exchange rate drifts the moment the
rate moves, while the invoice it produced claims to be exact.

The overlap constraint on `pricing_rates` includes currency, because a
dollar price and a dinar price for the same metric over the same window
are not a conflict; they are how two currencies coexist. Both the
PostgreSQL `EXCLUDE` constraint and the application-level check were
widened together — the application refusing what the database allows is
the more confusing of the two failures, because it names a conflict that
is not one.

**Currency is part of the target, not a detail of the rate.** That sentence
was true of the overlap check from the start and false of everything else
until it was found live, so it is worth stating flatly: every query that asks
"the rate for this metric at this scope" must also say *which currency*, or it
is asking a question with more than one answer. Four places asked it wrong:

| Where | What went wrong |
|---|---|
| `open_rate_for` | Setting a dinar price was refused because a dollar one was open, so a second currency could not be written through the API at all — the seeded JOD rates existed only because a migration wrote them directly |
| `effective_pricing` | Two currencies read as an ambiguity and the whole pricing screen returned 409 |
| `coverage` | A metric priced only in dollars reported "covered" while a Jordanian company could not be billed at all |
| `end_company_rate` | Looked for an open override without saying which currency's |

All four now take a currency. `GET /platform/pricing/effective` gained a
`currency` parameter (defaulting to the installation default) and echoes
`available_currencies` so the console offers the choice without keeping its
own copy of the currency table; a `company_id` overrides it with the
company's own, since that is the only currency that can charge them.

`coverage` compares against the currencies **live companies actually bill
in**, not the whole `CURRENCIES` table — an installation with no Jordanian
customers needs no dinar rate, and a false alarm is how a health check gets
ignored.

### Countries

`domain/countries.py` is a curated list, not all of ISO 3166: signup must
not offer a country the billing engine has no prices for, because that
produces a customer nobody discovers is unbillable until the month
closes. A country also decides which **payment methods** are offered —
Jordan has domestic schemes most of the world does not, and offering
PayPal to somebody who cannot use it is worse than offering nothing.

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

### The scheduler monitor

`/platform/health/scheduler`, in the Platform Console under **Health**.

Every billing run writes a row: when it started, how long it took, what it
counted, and whether it failed. That exists because of the failure described
below — three sweeps failing on alternate runs for months, invisible because
every one of them is idempotent, evidenced only by stack traces nobody read.

**A monitor that records only successes goes quiet exactly when something is
wrong**, so a failed run is recorded and *then* re-raised: Celery still
retries, alerting still fires, and the counters the run managed before it died
are kept.

**The recording uses its own session.** The load-bearing decision: writing the
failure inside the transaction that just failed would roll the record back
along with the work, so the run most needing explanation would be the one
leaving no trace. It also never breaks the task — evidence about billing must
not be able to stop billing, the same tradeoff as the routing decision log.

The row is written when the run *starts*, so a worker killed mid-sweep leaves
a `RUNNING` row that ages visibly. Recording only on completion would leave
nothing, and "no row" is indistinguishable from "never scheduled".

Four states rather than up/down, because the interesting failure is not "it
errored" — every job here is safe to repeat — but "it has not succeeded
recently and nobody noticed":

| State | Means |
|---|---|
| `healthy` | Succeeded within the window its schedule promises |
| `degraded` | Succeeded, but some items in it could not be processed |
| `failing` | The last run failed, **or nothing has succeeded in three intervals** |
| `never_run` | Nothing recorded — expected on day one, an outage after a deploy |

The three-interval window is deliberate. One missed run is normal — a deploy,
a restart, a sweep that overran — and a monitor that cries after one is a
monitor people learn to ignore. Three consecutive misses is not noise, and it
is exactly what the real bug looked like.

An installation's health is the **worst** of its tasks, never an average: one
whose invoice run has not succeeded in a day is not "mostly healthy".

`next_run_at` is derived from the last run rather than read from Celery, which
keeps that state in its own beat file — inaccessible to the API and reset on
restart. Derived is approximate and honest; reading a number that resets would
be precise and wrong.

### Every sweep must dispose its connection pool

A hazard shared by all the billing tasks, worth stating once because it
cost months of silent unreliability.

A task module caches its engine at module level and runs its body inside
`asyncio.run()`. Each invocation therefore gets a **new event loop**
while reusing pooled asyncpg connections bound to the **previous** one.
The next run then fails with `Future attached to a different loop` the
moment `pool_pre_ping` touches a stale connection. The fix is one line —
`await _engine.dispose()` in a `finally` — which closes pooled
connections without discarding the engine, so the next call opens fresh
ones on its own loop.

`close_due_periods`, `collections_sweep` and `refresh_daily_summaries`
each shipped without it and failed on roughly every other sweep for
months. Nothing looked broken: every one of them is idempotent, so a
failed run simply left its work for the next successful one. Periods
still closed, dunning still went out — late, intermittently, and with
132 stack traces in 48 hours that nobody was reading.

The pattern cannot be caught by running a task once, which is what a
test does. It appears only on the *second* invocation inside one worker
process. So it is enforced structurally instead:
`tests/unit/test_task_engine_disposal.py` parses every task module that
caches an engine and asserts the dispose happens inside a `finally`.

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

### The invoice run

`blinkengage.billing.generate_pending_invoices`, hourly.

Closing a period and invoicing it are separate acts, and for a long time
only the first was scheduled. A month would close by itself at 00:0x on
the 1st and then sit there — correctly closed, never billed — until
somebody opened the Billing Console and pressed Generate for each
company in turn. That is not a finance module; that is a reminder to do
the finance by hand.

The sweep is driven off the **state of the document**
(`BillingPeriodRepository.closed_needing_invoice`) rather than off
"closed in the last hour", so it self-heals: a period missed during an
outage is picked up on the next run instead of staying uninvoiced until
somebody notices a month later. Once the invoice is *issued* the period
stops matching, which is what stops the sweep working on it forever.
Oldest first, so a backlog clears in the order the months actually
happened.

**It issues; it does not leave drafts.** A draft is an unfinished
invoice, not a finished one of a different kind: it carries no invoice
number, so the customer has nothing to quote and nothing to pay against,
and the payment clock never starts. Generating without issuing bills the
month halfway and leaves a console full of unnumbered documents nobody
is chasing.

Drafts therefore count as work still to do. A run that dies between
generating and issuing would otherwise strand a month as a draft
forever, which is precisely the state a self-healing sweep exists to
fix. Issuing is guarded on `DRAFT`, so a re-run never tries to issue
what it already issued.

**Every customer gets a document, including a zero one.** Periods are
opened lazily, on a company's first metered event — so a company that
used nothing all month has no period at all, and a run that only walks
periods would silently never bill the quietest customers. The run fills
that gap first (`companies_missing_period` → `add_closed_period`),
creating an empty closed period for the month that ended, so the invoice
exists and says zero. A customer who cannot find last month's invoice
has no way to tell *"you owed nothing"* from *"we forgot you"*.

The backfilled period is inserted **already closed** rather than opened
and then closed: one open period per company is a database constraint,
and a company whose first usage landed this month already has an open
one. A month with no usage has nothing to snapshot anyway.

Two exclusions, both deliberate: soft-deleted companies, and companies
created *after* the month ended — somebody who signed up in August is
not sent a bill for July, and receiving one would be alarming rather
than reassuring.

Each period is generated in its own transaction, so a company with a
broken snapshot fails alone and is logged with its company id; the rest
of the run still bills everybody else. "The invoice run failed" is not
actionable; "Acme's July invoice failed" is.

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

## The free monthly allowance

Every company gets the first **100 conversations each calendar month**
free, and pays its own rate for everything beyond. Unused allowance does
not carry over: an allowance that accumulates is a liability that grows
silently, and a customer who has not used the product for six months has
not earned six months of free usage.

### Where it is applied

At **close time**, in `build_snapshot_line`, not at invoice generation.
The snapshot is the immutable record of what a period cost, so applying
the allowance later would mean the same closed period produced different
invoices depending on when it was billed.

Every line — snapshot and invoice alike — carries three quantities:

| Column | Meaning |
| --- | --- |
| `quantity` | Everything that happened |
| `included_quantity` | What the allowance covered |
| `billable_quantity` | The remainder, which `subtotal` is computed from |

All three are **stored, not derived**. A line reading "50 conversations"
for a customer who had 150 is a document that invites a support ticket;
"150 conversations, 100 included, 50 billable" answers the question
before it is asked. And recomputing the split on read would let a change
to the allowance silently alter a historical invoice — the same reason
`subtotal` has always been stored.

### Why it is code, not data

Metrics are code and pricing is data; that split is settled. An
allowance sits between them, and it is code *today* because the product
decision is that it is the same for everyone — one number, no
per-company variation. Making it per-company is a data change and a
migration, and the shape is deliberately ready for it: because every
applied allowance is written onto the snapshot, the day it varies by
company, history still explains itself.

A metric absent from `FREE_MONTHLY_ALLOWANCE` has no allowance. That is
the correct default — granting one by accident is a revenue leak nobody
notices.

## The payment engine

Phase 4. Where the previous phases decided *what* a customer owes, this
one moves the money — and then chases it when it does not arrive.

### Providers

Four operations, expressed in provider-neutral terms
(`infrastructure/payments/base.py`): start a payment, read its state,
refund it, verify a webhook. Nothing in the contract knows about
invoices; a provider moves money, and deciding which invoice that money
settles stays the invoice engine's job. That seam is why a second
gateway is an adapter rather than a migration.

Two implementations ship:

- **PayPal**, on the **Orders v2** API. Deliberately not Subscriptions:
  this product bills in arrears from measured usage, so the amount is
  not known until the period closes and there is nothing for a
  fixed-price recurring plan to charge. An order is created for an
  invoice that already exists, for an amount already calculated.
- **Manual** — bank transfers, cheques, cash. A first-class provider,
  not a null object: enterprise and government customers pay by wire,
  and that payment deserves the same ledger row, allocation and audit
  trail as a card. One payment path instead of a gateway path plus an
  "and also, manually" path, because the second one is always the one
  that ends up under-tested.

`PaymentProviderRegistry` is built from settings, so a deployment
without PayPal credentials simply has no PayPal provider rather than one
that fails at the first charge. `GET /platform/payments/providers`
reports what is actually available, so a console never offers a button
that cannot work.

### Four payment flows, not one

The temptation is to model every provider as "a gateway": credentials in,
redirect out, webhook back. That describes PayPal and it is wrong for most
of what Jordan actually uses — in a way that produces a checkout button
leading somewhere the scheme does not have.

So `domain/payment_providers.py` starts from **flows**, because the flow
decides what the customer is shown, what the platform stores, and how money
is matched back to an invoice:

| Flow | What happens | Providers |
|---|---|---|
| `redirect` | Hosted checkout; the customer leaves and comes back | PayPal, MEPS, Network International |
| `bill_presentment` | The bill is pushed *to the scheme*; the customer pays it at any bank channel quoting a reference | eFAWATEERcom |
| `credit_transfer` | The customer pushes money to an alias on their own schedule; nothing is started on our side | CliQ |
| `operator_entry` | Finance records money that has arrived | Manual |

Two providers sharing a flow can share a screen. Two providers sharing only
the word "payment" cannot.

`bill_presentment` and `credit_transfer` have no intent to expire and no
redirect to fail: there is only a bill to publish, or a transfer to match.
Modelling either as a redirect would invent a checkout page neither scheme
has.

### Configuring a provider

`/platform/settings/payment-providers`, following the mail relay exactly:
one encrypted row (`platform_settings`, key `payment_providers`), stored
settings layered over the environment so an installation running on
`PAYPAL_*` variables keeps working untouched.

Each provider declares its own **credential fields** as data, so the API,
the console form and the validation read one list — a field the backend
requires and the form never renders is a provider that can never be saved.
Field names mirror each scheme's own vocabulary ("outlet reference", not a
normalised "merchant id"), because an operator is copying values out of a
bank's onboarding pack.

Providers are saved **one at a time**: these are separate contracts with
separate people, and a form that saved all of them together would make
editing one an opportunity to clear another.

**Secrets are write-only.** A stored credential is never sent back to the
console; the screen is told *that* a secret is set, not what it is. On a
write, an absent secret means "unchanged" and an empty string means
"cleared" — because the console cannot resend what it was never given, and
reading absence as "clear" would unconfigure every merchant account on the
installation the moment somebody opened the page and pressed Save.

That is why reads return a `ProviderView` rather than a redacted
`ProviderConfig`. The two facts the console needs — the non-secret values,
and which secrets exist — cannot both survive redaction: strip first and
"is the password set?" answers no for everything. One type, no ordering to
get wrong.

### Readiness is three states, not a boolean

- `active` — configured, and an adapter exists.
- `not_configured` — an adapter exists; credentials are missing or it is
  switched off.
- `awaiting_integration` — credentials can be stored, but **no adapter
  exists yet**.

The third is the honest state of eFAWATEERcom, CliQ, MEPS and Network
International today: the schemes are namable, configurable and country-
scoped, and nothing pushes a bill or opens a checkout. They are
deliberately **absent from `PaymentProviderRegistry`**, which is what the
checkout asks "can this be paid?" — answering yes for something that cannot
complete puts a dead button in front of a customer. The settings screen
says so in words instead, which is the right place to say it.

Completing them needs each scheme's integration specification. The wire
protocol is not something to infer: an adapter posting invented fields to
an invented endpoint is prototype code in the money path.

### Intents versus payments

A **payment intent** is money *requested*. A **payment** is money that
*arrived*. They are separate tables on purpose: a customer who opens a
checkout page and closes it must leave nothing in the ledger.

Capture is idempotent at three independent levels, because gateway
webhooks are delivered at least once and charging twice is the one
failure a payments integration cannot undo by itself:

1. the intent's guarded `UPDATE ... WHERE status = 'PENDING'`,
2. the payment's `(provider, provider_reference)` unique constraint,
3. PayPal's own `PayPal-Request-Id` idempotency header.

The reference stored on a payment is the **capture** id, not the
order id — a refund is issued against the capture, and storing the order
id would leave the refund path unable to find it. (The retired
subscription integration made exactly the mirror-image mistake, reading
a capture id as a subscription id and dropping every payment as
unknown.)

**A declined payment is not an error.** `capture()` records the failure
and returns `None` rather than raising. Raising would roll the request
back and take the recorded reason with it, leaving the intent stuck at
`PENDING` for ever and discarding the one thing the customer needs to
know — that their card was declined. The same reasoning applies to a
refund the provider refuses: the `payment_refunds` row *is* the record
of the attempt, so nothing raises once it exists. The exception is
`RefundNotPermittedError`, which is raised before the provider is
contacted, when there is nothing recorded to lose.

### Reconciliation

A webhook that is never delivered leaves a customer who has paid looking
unpaid — which ends in a suspension, and is the most damaging billing
failure there is. `reconcile_pending()` asks the provider directly about
intents that have sat pending for 20 minutes, and it runs **before** the
dunning pass in the hourly sweep so a delivery failure can never cause a
notice, let alone a suspension.

### Reversal

An allocation is never deleted; it is marked `reversed`, with the reason
and the timestamp. Needed when a payment was matched to the wrong
document, when a transfer bounces, or on a chargeback.

This is why `InvoiceStatus.PAID` is **no longer terminal**. An invoice
can stop being paid without being wrong, and an invoice frozen at `PAID`
would be a system insisting it has been paid when it has not. `PAID`
reopens to `ISSUED` — or to `OVERDUE` when the due date has already
passed, because a reversal does not make a late invoice punctual. It
never reopens to `DRAFT`, and the only caller is
`PaymentService.reverse_allocation`, which writes an audit event
carrying the reason.

The `(payment_id, invoice_id)` uniqueness is **partial**, covering live
allocations only. A total constraint made the commonest reason to
reverse — the amount was wrong — impossible to correct, because the
replacement allocation collided with the reversal it replaced.

### Refunds

A refund refuses to return money still allocated to an invoice. The
obstacle is the point: reverse the allocation first, stating why, and
the invoice correctly reopens as unpaid. The alternative is a refund
that silently leaves an invoice marked paid with no money behind it, and
nobody discovers that until a reconciliation months later.

Refunds are their own table rather than negative payments, because a
negative row breaks every sum written before refunds existed — and the
sums that break silently are the dangerous ones. Pending refunds count
against the refundable balance: a refund in flight will land, and
double-refunding is unrecoverable.

## Collections

### Billing status is not company status

`companies.billing_status` is a **separate column** from
`companies.status`, not another member of that enum. Non-payment and a
compliance breach are different facts with different remedies — the
first is lifted by paying, the second only by an operator — and a
company can be in both at once. Merging them would let the collections
sweep silently lift a compliance suspension the moment an invoice was
paid, and would make the commonest support question ("why can we not log
in?") unanswerable.

| Billing status | Meaning |
| --- | --- |
| `active` | Nothing outstanding, or nothing yet due |
| `payment_due` | An invoice is issued, not yet past its due date |
| `payment_overdue` | An invoice is past its due date |
| `payment_suspended` | The dunning sequence ran out |

The status is **computed from open invoices**, never set by hand — a
status somebody can type in is one that drifts from the ledger.

### The dunning sequence

A pure function of dates (`domain/collections.py`), so "the customer
says they got two final notices" is a unit test rather than an
investigation.

| Stage | Offset from due date |
| --- | --- |
| `upcoming` | −3 days |
| `due_today` | 0 |
| `first_notice` | +3 |
| `second_notice` | +7 |
| `final_notice` | +14 |
| `suspended` | +21 |

It ends 21 days past the due date, matching the Net 21 terms invoices
are issued on: a customer is never suspended before they have had the
full payment window *plus* the whole sequence of warnings.

Two properties worth stating:

- **Notices catch up rather than skip.** If the sweep is down for a
  week, the notices it missed still go out, in order. Skipping them
  would land the suspension with no warnings behind it — precisely the
  thing a customer would dispute, and would be right to.
- **A notice is sent once.** `(invoice_id, stage)` is unique, so a sweep
  that runs twice, or a worker that dies mid-pass, cannot send a second
  final notice. The constraint does the work, not a flag somebody has to
  remember to check.

### Suspension and access

Suspension is automatic at the end of the sequence, with two escapes.

**Billing administrators keep access.** Anyone holding `billing.read`
can still sign in to a workspace suspended for non-payment. Locking out
everybody who can pay leaves nobody able to pay, which turns a late
invoice into a permanently lost customer. The refusal message says so —
"contact your administrator" is useless advice to the administrator, who
is the person reading it.

**Companies can be exempted.** `billing_never_auto_suspend` covers
enterprise and government accounts on payment cycles longer than any
sane dunning sequence. Notices still go out and invoices still show as
overdue; only enforcement is withheld, and *that it was withheld* is
itself audited on every sweep — a silently skipped account is
indistinguishable from one the sweep failed to reach.

Reinstatement runs in the same pass as suspension, and recomputes the
resulting status rather than assuming `active`: a company with a second
unpaid invoice comes back as overdue, not as though nothing were owed.

### The sweep

`blinkengage.billing.collections_sweep`, hourly. Reconcile first, dun
second, for the reason given above. Every step is idempotent, so the
notices a customer receives depend on the dates, not on how often the
task runs.

## The financial ledger

The accounting substrate everything else sits on. Invoices, credit notes
and payments are **documents**: they describe commitments. The ledger
records what those documents did to the money, and a balance is a
question about the ledger rather than a column on a document.

### Every entry carries both sides

One positive amount, one debit account, one credit account. That makes
every entry balanced *by construction* — there is nowhere to put an
imbalance, so an unbalanced ledger cannot be written.

The classic alternative (N signed lines per transaction summing to zero)
is more general and would be needed the day one operation posts to three
accounts. Taxes and multi-leg settlement are out of scope, and a shape
that cannot represent an error is worth more here than one that can
represent anything.

Direction is carried by **which account is debited**, never by the sign.
A negative amount would let one movement be written two ways, and every
total would then depend on which way each writer happened to choose. A
check constraint refuses `amount <= 0`, and another refuses an entry
that debits and credits the same account.

### The chart of accounts

| Account | Kind | Holds |
| --- | --- | --- |
| `accounts_receivable` | Asset | What customers owe |
| `cash` | Asset | Money that has arrived |
| `customer_credit` | **Liability** | Money held on a customer's behalf, not yet applied |
| `revenue` | Income | What was billed |
| `revenue_adjustments` | Contra-income | What was credited back |
| `bad_debt` | Expense | Receivables abandoned |

`customer_credit` is why payments are independent of invoices. A payment
that has arrived but settled nothing is a **liability** — the money is
still the customer's — and allocation is what discharges it against the
receivable.

Debit and credit are not "plus" and "minus": whether a debit increases an
account depends on its kind, which is why `AccountKind` exists rather
than a signed amount. `balance_of()` returns a positive number when an
account holds what it normally holds, so callers get "how much" without
needing to know which way the account runs.

### Posting rules

| Operation | Debit | Credit |
| --- | --- | --- |
| Invoice issued | `accounts_receivable` | `revenue` |
| Credit note issued | `revenue_adjustments` | `accounts_receivable` |
| Payment received | `cash` | `customer_credit` |
| Payment allocated | `customer_credit` | `accounts_receivable` |
| Allocation reversed | `accounts_receivable` | `customer_credit` |
| Refund issued | `customer_credit` | `cash` |
| Chargeback | `customer_credit` | `cash` |
| Write-off | `bad_debt` | `accounts_receivable` |
| Manual adjustment | *operator names both* |  |

Read each row as "value leaves the credit account and arrives in the
debit account". A table rather than branching code, because this *is* the
accounting policy of the product and it should be readable in one screen
by somebody who knows accounting and not this codebase.

Three of those choices are worth stating:

- **A draft invoice posts nothing.** Issuance is the moment a receivable
  exists and revenue is recognised. Recognising it earlier would book
  money the customer has never been asked for.
- **Allocation moves neither cash nor revenue.** It only discharges the
  liability against the receivable — which is precisely why receiving and
  allocating are separate operations.
- **A write-off is an expense, not a discount.** It says we billed
  correctly and were not paid; a credit note says we billed too much.
  Collapsing them would make revenue wrong in one direction or bad debt
  invisible in the other. `write_off` deliberately leaves the invoice's
  status alone: there is no `WRITTEN_OFF` state, and the invoice really
  is still unpaid. The ledger is where the receivable stops being an
  asset.

A **chargeback** is kept distinct from a refund even though the cash
effect is similar, because the cause matters commercially — a refund is
something we chose to do — and a ledger where both look identical cannot
answer "how much are we losing to disputes".

### Nothing is ever amended

A mistake is corrected by posting the opposite entry. The repository
exposes no update and no delete, the API offers no endpoint that edits an
entry, and on PostgreSQL a trigger refuses `UPDATE` and `DELETE`
outright, so the rule survives a `psql` session.

`entry_number` comes from the same locked counter that hands out invoice
numbers, which makes it **gapless** and transactional — a rolled-back
write releases the number rather than burning it. A database sequence
would have been cheaper, but sequences are explicitly not transactional,
and a ledger with holes in its numbering is something an auditor makes
somebody explain. It also gives a deterministic order that `occurred_at`
cannot: entries written in one transaction share a timestamp to the
microsecond, so ordering by time alone can show a payment before the
invoice it settles.

### Derived, not duplicated

`GET /platform/ledger/{company_id}` answers what a company owes **from
the entries**. That is the authoritative figure.

The denormalized columns on documents (`invoices.amount_paid`,
`amount_credited`) remain, as a **projection**: "what is still owed" is
read on every list screen, and summing the ledger per row would be an
N+1. They are a cache of what the ledger says, not a second record of
it — and `GET /platform/ledger/reconciliation` proves the two agree,
per company. A cache nobody checks is just a second source of truth with
extra steps, so the check is exposed rather than buried in a log: the
only useful response to a divergence is a person looking at it.

`GET /platform/ledger/trial-balance` reports every account plus
`in_balance`. It cannot go false through normal use, which is exactly why
it is worth watching.

### Entries are written on the same session

Same reasoning as the audit trail: a ledger on a separate connection can
disagree with the thing it records, and one that disagrees is worse than
none because it will be believed. Either the invoice is issued and the
entry exists, or neither happened.

### Reconstructed entries

Documents predating the ledger are backfilled, because a source of truth
that disagrees with reality on its first day is not one. Every such row
is flagged `reconstructed = true`: it is an *inference* from a document
rather than a record of something observed, and a reader is entitled to
know which rows are which. Draft and cancelled invoices are skipped — a
draft was never billed, and a cancelled invoice's number is consumed but
nothing was ever owed.

The backfill is a single ordered INSERT so `entry_number` follows real
chronology across document types. It orders by the documents' own
timestamps and does not silently correct them, so a payment dated after
the allocation that drew on it will appear out of causal order —
surfacing a pre-existing data problem rather than hiding it.

## The Company Billing screen

`/platform/companies/{id}/billing`. What a company is charged, why, and
every change ever made to it.

### The console never calculates a price

Every figure on the screen comes from a resolver API — `/pricing/effective`
for the table, `/pricing/resolve` for the preview, `/pricing/history` for
the audit trail. The UI does not pick a winner between scopes, does not
multiply, and does not re-format an amount it computed.

That is not tidiness, it is the only way the screen can be trusted: a
second implementation of the precedence hierarchy in TypeScript would
drift from the one that actually bills, and the drift would show up as a
customer disputing an invoice that the console had told an operator was
right. The `scope` field on each row **is** the source; `shadowed` **is**
the list of rates that lost.

Amounts are printed as the server sent them rather than through
`Intl.NumberFormat` on a parsed float. JOD has three decimal places and
USD two, the API already returns each at its own scale, and re-formatting
a parsed number is how a displayed price stops matching the billed one.

### The preview asks, it does not model

"Preview the resolved pricing exactly as the resolver sees it" is
implemented literally: the screen POSTs to `/pricing/resolve` — the same
endpoint a closing period uses — for any instant an operator picks, and
renders the reply. It passes `strict: false`, because "no price is
configured for that at that moment" is a real answer somebody needs to
see rather than an error, and the resolver's own `reason` is shown
verbatim. A reason like "no price covers 2020-01-01" saves an operator
hunting through effective dates by hand.

### Writes carry optimistic concurrency

Every override sends either `expected_current_rate_id` (the rate being
replaced) or `expect_no_current_rate`. Without one of the two, two
operators editing the same price both succeed and the second silently
wins — and neither learns that anything was lost.

### Read-only operators

`users.platform_read_only` narrows a platform operator to reading.
Platform authority is otherwise all-or-nothing, deliberately, so that no
tenant role can be edited into it; this does not weaken that, because it
only ever *narrows* what an operator can do and a strictly less powerful
principal cannot be an escalation path.

It exists because auditing what a customer is charged is a normal job
that does not need the authority to change it, and the alternative is
sharing an account that can rewrite prices.

Reads stay open — including the resolver preview, which is a POST but
writes nothing, and which is the main reason to grant read access at all.
Writes are refused at the API with `require_platform_write`, not merely
disabled in the console: a disabled button is a courtesy, not a
permission.

## The billing dashboard

Every phase above is the operator's view of billing. This one is the
customer's, and it exists for one product goal: **nobody should be
surprised by their invoice.** Within about ten seconds a customer should
know what they spent today, what they have spent this period, what is
driving it, what they are likely to pay, and whether they need to act.

`GET /billing/dashboard` returns all of it in one response;
`GET /billing/estimate` returns only the figures that move, and is polled.
Both are scoped to the caller's own company from the auth context —
there is deliberately no `company_id` parameter anywhere under
`/billing/*`, because the surest way to prevent one tenant reading
another's spend is to give the caller no way to name a company.
`billing.read` gates them, which is what that permission was created for.

### Estimates are never invoices

The one confusion this feature cannot afford is a customer reading an
estimate as a bill. So the two are kept apart in the API (`estimated_*`
fields, an `estimate` object) and on screen (a divider, its own heading,
its own words). Draft invoices are not shown at all — a draft is the
operator's working copy, and putting its number in front of a customer
would present as a bill something nobody has yet stood behind. An issued
invoice remains the only legal statement of what is owed.

### Immutable daily aggregates

`billing_daily_summary` holds one row per company, per metric, per day. It
is the source for the daily cost chart, the daily usage chart, cost
analytics and any future forecasting.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade delete |
| billing_period_id | UUID | FK → `billing_periods.id`, **RESTRICT** — like invoices: this is the evidence of what a customer was shown, and deleting a period must not quietly destroy it |
| usage_date | date | The day the usage *happened*, UTC — not the day it was aggregated |
| metric_code / metric_version | varchar(60) / int | |
| metric_display_name | varchar(120), nullable | Snapshotted, like an invoice line's: a metric renamed later must not relabel a historical chart |
| quantity | numeric(18,6) | |
| unit_amount | numeric(18,6), nullable | What the Pricing Resolver returned **for that day**. Null where no price was configured — a gap, not a free metric |
| estimated_cost | numeric(18,6) | quantity × unit price, unrounded. An estimate; the invoice is the billing document |
| currency | char(3) | |
| projected_cost_snapshot | numeric(18,6), nullable | What the period was projected to total, as of this day |
| projection_strategy | varchar(30), nullable | Which method produced that snapshot |
| finalized_at | timestamptz, nullable | Null while the day is open. Once set, a trigger refuses UPDATE |
| created_at / updated_at | timestamptz | |

Unique on `(company_id, usage_date, metric_code)` — the upsert key, and
what stops a re-run doubling a chart. A partial index on open days serves
the refresh sweep; `(company_id, usage_date)` serves the chart query. Two
triggers enforce the rules the application also enforces:
`trg_billing_daily_summary_immutable` refuses an UPDATE to a finalized
row, and `trg_billing_daily_summary_no_delete` refuses DELETE.

Charts are **not** computed from `usage_records`. Charting thirty days
would scan every event a company generated, on every page load, for
numbers that cannot change.

**A closed day is immutable.** Today's row is recomputed as usage
arrives; once the day is over it is finalized and refused thereafter — by
the repository (`refresh_open_day` is a guarded UPDATE), by the service,
and by a PostgreSQL trigger so it also holds in a `psql` session. That
matters because these rows are what a customer *was shown* during the
month, and the promise is that the invoice matches what they saw. A
historical row that silently recalculates — because a price changed, or
an aggregation improved — breaks that promise in the least visible way
possible.

Each day is priced **at the price that applied on that day**, resolved at
the last second of it, so a rate change on the 15th leaves the 1st–14th
alone exactly as the invoice will. Nothing here prices anything itself:
the Pricing Resolver rates every day, in one batch call per refresh, and
a second pricing implementation behind a dashboard would eventually
disagree with the bill.

`projected_cost_snapshot` records what the period was projected to total
as of each day. Frozen with the row at finalization, it answers "what did
you tell me on the 12th?" — the first question after a surprising
invoice, and the only way to find out whether the projections are any
good.

There is deliberately **no backfill**. The table starts empty and fills
from the day it ships; `earliest_day` is surfaced so a chart can say
"data starts here" rather than drawing a flat line at zero and implying
no usage.

### The allowance is applied on read

The daily rows hold what a day's usage **cost**; the free monthly allowance is
netted off when the dashboard is read.

It has to work that way. The allowance is a *monthly* rule — the first 100
conversations of the month are free — and a single day's row cannot know how
much of it was left when that day began. Storing a netted figure per day would
also mean rewriting yesterday's row the moment a backdated record changed the
answer, and a closed day is immutable.

So `_net_of_allowance` walks the rows in date order, spends the allowance
against the earliest usage (which is what happens in reality), and reports
each day's billable cost. Every figure a customer compares against a bill —
today, month-to-date, each metric, the chart, the projection — is net.
Quantities stay gross, with the free portion shown beside them, because a
customer with a surprisingly small bill needs to see why and one whose
allowance has run out needs to see that too.

This reconciles with the invoice, which applies the same allowance to the
period aggregate at close (`build_snapshot_line`): at a steady price both come
to `allowance x price`.

The chart reads from the **first of the month** containing the window's start,
not from the start itself — otherwise narrowing the window to 7 days would
hand out a second allowance at its left edge.

**One known divergence.** The invoice prices a whole period at the rate in
force when it closes; the daily aggregates price each day at that day's rate.
The two differ only if a rate changes mid-period, and they differ because each
is right about a different thing: an immutable daily row must not be re-priced
by a later change, and an invoice must not be assembled from several rates
without saying so. In that case the estimate is the better description of what
happened and the invoice remains the document. Worth closing later by pricing
invoice lines per rate period; not worth silently reconciling by making
history mutable.

### The projection engine

`domain/projection.py` is framework-free arithmetic over daily totals,
with three named strategies:

- **`rolling_7_day`** — the mean of the last 7 complete days. The
  default: recent enough to follow a change in usage, long enough to
  absorb the weekly rhythm most businesses have. A three-day average
  taken on a Monday would project the month from its quietest days.
- **`daily_average`** — the mean of every complete day so far.
- **`linear_pace`** — spend so far divided by the fraction of the period
  elapsed, today included. The most responsive and the most volatile,
  which is why it is offered rather than defaulted to.

Three rules are non-negotiable.

**Today is excluded from the averages.** A day that is two hours old is
not a day; averaging it in makes the projection climb through every
afternoon and reset at midnight. Today is instead treated as an average
day when extrapolating.

**Every projection states its method**, and it is the method that
*actually ran*. Below 7 complete days `rolling_7_day` has nothing to roll
over, so it falls back to `daily_average` and reports
`effective_strategy` and `fell_back` — telling a customer "Rolling 7-Day
Average" when three days were available is a small lie that costs a great
deal of trust when noticed.

**Insufficient data is an answer, not a zero.** `NoProjection` carries an
explicit reason (no complete days, too early, no usage, period closed)
and the UI shows the sentence for it. Returning 0, or a wild number from
dividing by a fraction of a day, is worse than saying so.

Absent days count as zero-cost days, not as missing data: a quiet Sunday
happened and cost nothing, and averaging only the days that had usage
would project a month of busy days from a week containing a weekend.

A future phase lets a platform administrator choose the global default;
the strategy is already a stored, named value rather than a hardcoded
formula, so that is a setting rather than a migration.

### Live refresh without a global sweep

Estimated charges must update every 30–60 seconds while the page is open.
The obvious implementation — a sweep every 30 seconds — re-prices every
company on the installation whether or not anybody is looking.

Instead a dashboard read refreshes **that company's** aggregates when
they are more than `STALE_AFTER` (30s) old. However many people have the
page open and however fast they poll, today's row is recomputed at most
twice a minute, and the work happens only for companies being looked at.
The refresh is idempotent, so a concurrent one is harmless.

`blinkengage.billing.refresh_daily_summaries` still runs hourly, for what
reads cannot cover: closing yesterday and recording the projection
snapshot for the companies nobody visited. The period-close job refreshes
a period one last time *before* closing it and finalizes every day
*after*, so a month that has been invoiced has no open rows left.

### Payment methods are configuration

The country decides which methods are *offered*; the provider registry
decides which are *configured*; the API intersects the two. Nothing is
hardcoded — a method with no credentials behind it is reported
unavailable rather than rendered as a button that cannot work, and a
Jordanian customer is not offered PayPal merely because the code knows
the word. Methods that need an operator (`bill_reference`, `manual`) are
marked as such, so nobody waits for a receipt no automated process is
going to send.

## The billing model: billable messages

**One charge per customer-facing message, on any channel.** Not per
conversation, not per channel, not per AI feature.

The reasoning is that a message a customer can see is the unit of value the
product delivers. A conversation is an arbitrary container around it — two
companies with identical traffic can have wildly different conversation counts
depending on how their customers happen to open threads — and per-feature
surcharges charged twice for one delivered message.

### What counts

`domain/billable_events.py` owns the rule, as a pure predicate, so it can be
read in one place and tested without a database. The meter asks; it does not
decide.

*Included* — inbound customer messages, outbound agent replies, AI Autopilot
replies, automation replies, and every medium: text, image, audio, video, file.
**A photo is one message.** Not two, and not one per attachment.

*Excluded* — internal notes, system messages, assignment changes, tags, read
and delivery receipts, typing indicators, and anything else a customer never
sees. None of them deliver anything to a customer, and billing for them would
mean an agent tidying their own queue costs the customer money.

### Channel is a dimension, never a price

Every billable event records its channel, and **nothing that prices reads that
field.** A per-channel rate would make the same product cost different amounts
for reasons a customer cannot control, and would push the platform's own
carrier costs onto their bill line by line.

Analytics keeps the dimensions: the dashboard breaks a period's messages down
by channel, by origin (customer / agent / AI Autopilot / AI-assisted /
automation) and by direction. Those breakdowns are **counts, not money** — a
per-channel cost would be a number the invoice does not contain.

### One immutable event per message

| `billable_events` | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| company_id | UUID | FK → `companies.id`, cascade |
| billing_period_id | UUID | FK → `billing_periods.id`, **RESTRICT** — evidence behind a charge |
| message_id | UUID | **Unique.** No FK: a retention policy may delete the conversation, and an invoiced month's evidence must survive it |
| conversation_id | UUID | Reference, not a dependency, for the same reason |
| customer_id | UUID, nullable | Known for inbound; outbound replies do not carry it |
| direction | varchar(10) | `inbound` / `outbound` |
| origin | varchar(20) | `customer` / `agent` / `ai_autopilot` / `ai_assisted` / `automation` — analytics |
| channel_type | varchar(40) | Analytics. Snapshotted as a string; the channel config may be gone |
| message_type | varchar(20) | `text` / `media`, at the time |
| occurred_at | timestamptz | When the message happened, from the event — never "now" |
| usage_record_id | UUID, nullable | Null when the period had closed: evidence, deliberately not a charge |
| created_at | timestamptz | |

`trg_billable_events_immutable` refuses UPDATE and DELETE.

| `pricing_rate_tiers` | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| pricing_rate_id | UUID | FK → `pricing_rates.id`, cascade |
| up_to | numeric(18,6), nullable | **Inclusive** upper bound; NULL is the open-ended top step |
| unit_amount | numeric(18,6) | The rate this step charges |
| sort_order | int | 1-based; unique per rate, and the bounds must ascend with it |

`billable_events` is the evidence layer under the bill. A usage record says a
billable message happened; a billable event says *which* message, on which
channel, in which conversation, from whom.

`message_id` is unique, so the guarantee that a message is charged once belongs
to the database rather than to a consumer. That matters more than it looks:
an Autopilot reply publishes `message.sent` **and**
`conversation.autopilot_replied`, and the relay delivers at-least-once. Binding
only the two message events, and keying both on the message, makes double
counting structurally impossible rather than merely unlikely.

The table is append-only, enforced by trigger. A correction is a new
adjustment, never an edit.

**An event is written even when nothing is billed.** A message that arrives for
a period that has already closed is recorded as evidence with no usage record
attached: the arrival is a fact, the late count on the period surfaces it, and
silently billing it into the open period would move revenue between months.

### The meter

Two events, one metric:

| Event | What it is |
|---|---|
| `message.persisted` | an inbound customer message |
| `message.sent` | an outbound reply — agent, AI or automation |

Both produce one `BILLABLE_MESSAGE`, keyed `BILLABLE_MESSAGE:<message_id>`.
Both payloads carry `message_type` and `customer_visible` so the meter can
apply the rule from the event alone, without reading the message back.

The binding is complete **by construction**, not by inspection: each event has
exactly one publisher. `message.persisted` comes only from the ingest
consumer, and `message.sent` only from `ConversationService.send_reply` —
which every outbound path funnels through, including Autopilot, the workflow
engine, the AI service and CSAT dispatch. A new way to send a message
therefore bills automatically; there is no list of call sites to keep in step.

### Retired, not deleted

`CONVERSATION`, `AI_ASSISTED_REPLY` and `AI_AUTOPILOT` are `RETIRED`. No new
rate may be set for them and nothing meters them — but their existing rates
still resolve, their closed periods still price, and their invoices still
reprint. Their codes appear on issued documents, and a document that cannot be
reprinted is a document that cannot be defended.

The free allowance keeps its `CONVERSATION` entry for exactly the same reason:
re-rating a closed period must reproduce the total that was actually sent.

## Volume tiers

The rate is a function of the period's own volume. The shipped table:

| Billable messages in the month | First 100 | Rate for the rest |
|---|---|---|
| up to 200 | free | 0.002 |
| up to 500 | free | 0.0015 |
| above 500 | free | 0.001 |

(JOD at the same 0.7 ratio the existing rates use: 0.0014 / 0.00105 / 0.0007.)

### Volume, not graduated

The total selects **one** rate, and every chargeable unit is charged at it. 600
messages means all 500 chargeable ones at the 600-message rate — not the first
200 at one rate and the rest at others. It is the simpler thing to put on an
invoice: one quantity, one rate, one subtotal.

**It has a cliff, and that is understood.** A 500-message month costs
400 × 0.0015 = 0.60; a 501-message month costs 401 × 0.001 = 0.401. The bill
*falls* as usage crosses a boundary. That is inherent to volume pricing — it is
why graduated pricing exists — and it is worth stating rather than discovering:
nobody is ever charged more for using less, so the surprise is always in the
customer's favour. `tests/unit/test_tiers.py` asserts both the cliff and the
monotonicity within a tier, so anybody changing the table sees that the
behaviour is known.

### The allowance does not move anybody between tiers

The tier is chosen by what a company **used**, not by what it was billed for. A
company that sent 250 messages is in the second tier even though only 150 are
chargeable. Selecting on the billable quantity would push a company just over a
boundary back under it by way of its own free units, and quote a rate nobody
communicated.

### Where tiers are stored and applied

`pricing_rate_tiers` are child rows of a `pricing_rates` row — not JSON, so the
ordering and the bounds are constrained by the database and readable by the
audit trail. A rate with **no** tier rows is a flat price and behaves exactly
as it always has; `ResolvedPrice.tier_table()` returns a one-step table for it,
so there is one charging path rather than a tiered one and a flat one that
eventually disagree.

The parent rate's `unit_amount` stays meaningful: it holds the **top** tier's
rate, so anything reading a rate without its tiers still gets a real price.

Applied in two places, and they must agree:

- **The period close** charges the period aggregate through the table and
  freezes the selected rate *and* the tier bound (`usage_period_lines.
  tier_up_to`) onto the snapshot line. The invoice copies that verbatim, so it
  can state why the rate applied years later.
- **The dashboard** writes the same tier-selected rate onto each open day of
  `billing_daily_summary`, chosen by the period-to-date volume. That is what
  keeps the estimate and the invoice equal to the last decimal — a dashboard
  quoting the top-tier rate while the bill charges the first-tier one is
  exactly the surprise this feature exists to prevent.

A closed day keeps the rate it was finalized with, whatever the volume has
since become. The immutability rule wins: those rows are what the customer was
shown.

## Usage metrics and pricing models

Billing started with one metric priced one way. It now has to price many
dimensions, several ways, without another refactor — so *what is measured* and
*how it is charged* are separate, and both are explicit.

### What a metric is, and where each part lives

A metric definition spans two places on purpose, and the split is the whole
design: a metric's **identity** is code, its **price** is data.

| | Where | Why |
|---|---|---|
| Name, Code, Unit | `domain/billable_metrics.py` | Metrics are code so every priced thing provably has a meter. A metric an operator could type in would charge nobody. |
| Billing type (`MetricKind`) | same | Decides how a period aggregate is derived. Not a label — it changes the arithmetic. |
| Active (`MetricAvailability`) | same | `MEASURED` / `PLANNED` / `RETIRED`. Only a measured metric may be priced. |
| Currency | `pricing_rates.currency` | A metric is priced in every currency it is sold in; there is no single answer. |
| Pricing model | `pricing_rates.pricing_model` | The same metric can be flat for one plan and tiered for another. |
| Tier table | `pricing_rate_tiers` | Belongs to one rate, so history keeps the table it was charged under. |
| Included quantity | `pricing_rates.included_quantity` | Varies by plan and by negotiation. |
| Minimum charge | `pricing_rates.minimum_charge` | Same. |
| Effective date, End date | `pricing_rates.effective_from` / `effective_until` | Prices are effective-dated; a metric is not. |

Putting currency, tiers or dates on the *metric* would mean one price per
metric per installation, which is not a product anybody sells.

### The catalog

Twenty metrics are declared: one measured (`BILLABLE_MESSAGE`), three retired,
and sixteen planned — messages, AI tokens in and out, image generation, audio
transcription and synthesis, storage, file bandwidth, API requests, webhook
events, phone minutes, SMS, email, push notifications, active agents, active
bots and a custom dimension.

They are declared **before** their meters deliberately. The schema, the audit
trail and the console are then designed against the whole shape once, and a
planned metric is refused a price so nobody configures a rate that charges
nothing.

### Billing type decides the aggregation

`MetricKind` is written down while only one kind is metered, because the
mistake it prevents is a multiple rather than a rounding error:

- **counter** — discrete occurrences, summed. Messages, requests, tokens.
- **continuous** — fractional amounts, summed. Phone minutes, gigabytes moved.
- **sampled** — a level held over time, averaged. Gigabyte-months: summing
  daily samples would bill the same gigabyte thirty times.
- **seat** — active entities in the period. The value is the peak, never the
  sum of daily counts, or a month bills thirty times the seats.

Only `counter` has a meter today. The others' rules are stated so whoever
ships one implements the aggregation the metric already declares.

### Pricing models

`domain/pricing_models.py` owns one function — `charge(terms, quantity)` — and
every surface goes through it: the period close, the dashboard estimate, an
operator's preview. A second implementation is how a dashboard ends up
disagreeing with an invoice.

| Model | What it does | State |
|---|---|---|
| `flat` | One rate for every unit | **Enabled** |
| `volume_tier` | The total picks one rate for every chargeable unit | **Enabled** |
| `graduated_tier` | Each bracket at its own rate | Implemented, not offered |
| `fixed_fee` | A flat amount per period regardless of usage | Implemented, not offered |
| `package` | Sold in blocks, part-blocks rounded up | Declared |
| `committed` | A committed quantity, with a rate beyond it | Declared |
| `subscription` | A plan fee with entitlements across metrics | Declared |

Three states rather than two, because they answer different questions.
`IMPLEMENTED` means the arithmetic exists and is tested; `ENABLED` is the
product decision about what may be written today. Enabling graduated tiers is
a one-line change plus a console field — no new maths to get wrong.

`GET /platform/pricing/models` returns all seven with both flags, so a console
can show what is coming without offering it, and an editor written today needs
no change the day one is turned on.

**Package, committed and subscription are declared but not implemented, on
purpose.** Each needs a product decision before it needs code — does an unused
part of a package expire? does an unmet commitment roll over? — and
implementing maths for terms nobody has agreed would be inventing policy and
calling it architecture. Their parameters will live in `model_params`, a JSON
column, because the keys differ per model and a nullable column per future
model is five columns that are NULL forever.

### Included quantity and minimum charge are modifiers, not models

Both apply to **every** model:

- *Included usage* is `included_quantity`. Making it a separate model would
  mean a rate could not be both tiered *and* have a free allowance, which is
  precisely what the shipped message rate is.
- *Overage* is simply what the model charges beyond the included quantity.
  There is no overage model for the same reason — a committed rate adds a
  distinct overage *rate*, which is why `committed` is its own model.
- *Minimum charge* raises the subtotal to a floor, and the line records that
  it did, so an invoice can say why a quiet month costs what it does.

The allowance moved from `domain/allowances.py` to the rate. The code table
remains the **default** for a rate that sets none, so every rate written
before this keeps charging exactly as it did — and a rate that explicitly sets
zero means zero, which is a different thing from unset.

### What a frozen line records

`usage_period_lines` now carries `pricing_model` alongside `tier_up_to`. "Why
is this the amount?" is answered by the model as much as by the rate, and both
may have changed by the time somebody asks.

### The Usage Metric Pricing Editor

Reached from the **billing console** (`/platform/billing`), which is a separate
surface from the platform console — see `docs/architecture/platform-admin.md`.
Setting rates and suspending a company need the same authority but are not the
same job.

`frontend/src/features/platform/UsageMetricPricingEditor.tsx`. The metric is a
**parameter**, and every field on the screen comes from what the server says
the metric and the models are — nothing in the component knows that messages
exist, so the day a token or a phone-minute meter ships it prices there with
no change.

What the screen enforces by *shape* rather than by a message after the fact:

- The last tier step has no upper bound. Its cell is not an input; it reads
  "and above", and it has no delete button. A table whose top step ends
  somewhere leaves a customer past it with no price.
- Switching to a tiered model seeds a one-step table carrying the rate the
  metric already had, so changing the shape never silently changes the price.
- Models that are implemented but not enabled are shown **disabled** with a
  "coming" chip — an operator can see what is arriving without configuring a
  price that would never charge.
- Amounts are strings from input to API. Never parsed to a number: `0.0005`
  and `0.05` are a hundredfold apart, and a float round trip is how the two
  stop being distinguishable.

Bounds ascending is deliberately *not* enforced per keystroke — an operator
typing a table top-down passes through invalid states constantly. The
preview's refusal, in the server's own words, is the feedback that helps.

**Names are translated from codes, not from the server's prose.** The API
sends `display_name` and `description` as English, alongside a stable code
(`metric_code`, `model`). The console translates from the code and falls back
to the server's words, so an Arabic operator reads Arabic and a metric
declared before anyone translated it still reads as English rather than as a
missing-key placeholder. `metricName()` is its own module for the same reason:
the pricing table, the editor title, the company page and the coverage warning
must call a metric the same thing.

Still English in a non-English console: **domain validation messages** —
"Tier bounds must ascend: 500 follows 900" and its siblings. They interpolate
values into prose in the domain layer, which deliberately has no i18n
coupling, so translating them means converting the pricing error hierarchy to
codes and parameters. Worth doing, not done here.

**The preview is computed by the pricing engine, never in the browser.** It
debounces and calls `POST /platform/pricing/quote` (below). The preview is
exactly where an operator decides a price is right, so it must be the same
arithmetic the invoice will use.

## Metering and pricing are separate systems

**Metering records what happened. Pricing decides what it costs. Neither
knows about the other.**

This is the constraint everything above rests on, so it is worth stating as a
rule rather than leaving it implicit in the call graph.

| | Metering | Pricing |
|---|---|---|
| Answers | *What happened?* | *What does it cost?* |
| Owns | `usage_records`, `billable_events` | `pricing_rates`, `pricing_rate_tiers`, `pricing_profiles` |
| Writes | Append-only, at the moment of the event | Never writes usage; freezes lines at close |
| Knows | Company, metric, quantity, when, context | Rates, tiers, allowances, effective dates, currency |

### What a metering row is allowed to contain

Company, metric code, metric version, quantity, `occurred_at`, source,
idempotency key, and a context reference. **No amount, no currency, no rate
id, no "priced" flag.** A price frozen at measurement time is a pricing
decision that can never be revisited — and re-pricing a period is exactly what
this separation exists to allow.

The event row alongside it (`billable_events`) carries channel, origin and
direction. Those are **analytics dimensions**; the pricing engine reads none
of them, which is what makes billing channel-agnostic in fact rather than by
convention.

`test_metering_separation.py` asserts this against the model columns, so
adding a price column to either table fails with the reason.

### The meter does not construct the pricing engine

`UsageService` takes `pricing` as **optional**. The metering consumer's
`build_usage_service` passes none at all, and the module imports nothing from
the pricing package — delete `application/services/pricing_service.py` and the
meter still records usage. Asking a metering-only service to close a period
raises rather than quietly pricing nothing at zero.

The period-close job builds its own service *with* pricing, because closing is
the one place the two meet.

### Metering rows are immutable, and the database says so

| Table | Trigger |
|---|---|
| `billable_events` | `trg_billable_events_immutable` |
| `usage_records` | `trg_usage_records_immutable` (migration `b7d4e21a9c56`) |

Both refuse `UPDATE` and `DELETE` at the row level. The repositories expose
`add` and reads and no mutator, but a rule enforced only in the application is
a rule somebody eventually goes around with one statement in a psql session.

A correction is a **new record** — `UsageRecordSource.MANUAL`, with a note and
an operator — never an edit. `scripts/reset_company_billing.sql` disables both
triggers explicitly and re-enables them; that is a named development tool, and
its explicitness is the point.

### Pricing is reproducible from stored state

A close resolves rates at one instant, captured once:

```python
closing_at = datetime.now(UTC)
priced_at = min(period.period_end, closing_at)   # an early close prices at "now"
period.mark_closed(closed_at=closing_at)
```

One `now()` per close, not two. Both halves are on the period row, so the
instant a historical close priced at is `min(period_end, closed_at)` —
derivable from the row alone, with nothing to guess. Combined with rates that
are never rewritten (see *History is never rewritten*), any past period can be
re-priced and reach the same numbers.

### Simulation: `POST /platform/pricing/quote`

The other thing the separation buys. Terms come from the caller rather than
from a stored rate, and nothing is written:

```json
{ "metric_code": "BILLABLE_MESSAGE", "quantity": "150", "currency": "USD",
  "pricing_model": "volume_tier", "unit_amount": "0.001",
  "tiers": [{"up_to": "200", "unit_amount": "0.0005"}, {"up_to": null, "unit_amount": "0.001"}],
  "included_quantity": "100" }
```

It answers two questions with one call:

- *What will these terms charge?* — the pricing editor's preview, so the
  console never applies a tier table itself.
- *What would last month have cost under this table?* — given a closed
  period's own snapshot quantity.

Terms are normalised and validated through `PricingService.validated_terms`,
the **same method a write uses**. A tiered model with no table, a table whose
bounds do not ascend, or a model this release does not offer is refused here
exactly as on save, and amounts come back quantized to the column's scale. A
preview that validated differently would be worth less than none: an operator
would approve `250` and store `250.000000`.

## Billing Operations: the console a finance team works in

Everything above is the engine. This section is the **workspace** on top of
it — six screens under `/platform/billing`, all of them read paths over
figures the engine already computed, plus the small set of writes that
finance work actually consists of.

The console never calculates. Not the totals, not the balances, not the
ratios — every number on screen was produced server-side in `Decimal` and
crosses the wire as a string. A console that derives its own revenue is one
that will eventually disagree with the invoice, and the number people believe
is whichever they saw first.

### The rule that shapes every screen

**Nothing sums across currencies, and the response has nowhere to put a
figure that did.** Every collection the console reads is grouped by currency
with no field above the grouping:

| Endpoint | Grouped by currency | Cross-currency figures |
|---|---|---|
| `GET /platform/billing/revenue` | `currencies[]` | `companies_behind`, `companies_suspended` (counts) |
| `GET /platform/invoices/search` | `currencies[]` | `total` (a row count) |
| `GET /platform/payments/allocations` | `currencies[]` | `total` (a row count) |
| `GET /platform/payments/collections/aging` | `currencies[]` | none |
| `GET /platform/ledger/trial-balance` | one set of books per currency | none |
| `GET /platform/ledger/statement/{id}` | one currency per statement | none |

Counts are the only thing that legitimately spans currencies. This is
structural rather than a convention somebody has to remember: there is no
field a cross-currency amount could be written into, so it cannot be returned
by accident, and tests assert the exact key set of each response so it fails
the day somebody adds one.

The one flat cross-company list, `GET /platform/payments/collections/status`,
carries `currency` **on every row** for the same reason.

### `GET /platform/billing/revenue` — and why the headline figure is not MRR

Blink Engage bills for usage and sells no subscriptions, so there is no
contracted recurring revenue to report. The dashboard's monthly figure is a
**run rate**: revenue recognised in a window, scaled to thirty days. It
travels with its own `method`, always, because a derived number quoted
without its derivation is one nobody can check.

| `method` | Means |
|---|---|
| `trailing_30_day` | A thirty-day window. The rate and the window are the same length; nothing was scaled. |
| `scaled_from_window` | Some other window, scaled to thirty days. Steadier from ninety days, jumpier from ten — `days_observed` says which. |
| `insufficient_history` | Under seven days. Reported as unavailable rather than guessed, because a rate scaled up from four days says more about the window than about the business. |

Seven days matches the projection engine's own threshold deliberately: two
parts of the product disagreeing about how much history is enough would be
indefensible to a customer who noticed.

Two kinds of number sit side by side on that response and the distinction is
the whole design. **Period figures** — revenue, collected, bad debt — are what
moved through an account inside the window. **Positions** — outstanding,
customer credit — are what stands in it right now, whenever it was billed.
Conflating them is how a console reports all-time revenue as this month's.

`collection_ratio` is `null`, never zero, when nothing was billed: a ratio
with no denominator is undefined, and rendering it as 0% reads as a
collections failure in a month that simply had no invoices. It may also
exceed 1, and is deliberately not clamped — a quiet month that collects two
months of arrears really did collect more than it billed, and that is the
month a collections team most wants to see.

The endpoint walks every company to count who is behind. It is a page-load
figure, not something to poll.

### What "owed" means

One definition, `domain/invoicing.amount_owed`, applied everywhere:

```
owed = total − paid − credited,  but only if the document is a debt at all
```

A **draft** was never billed. A **cancelled** invoice was withdrawn. A
**written-off** one was abandoned. None of the three is money anybody is
chasing, and reporting them as receivables is how a console comes to disagree
with collections, with the aging report and with the ledger.

### Writes, and the reason each one demands

The console's write surface is small on purpose. There is no edit and no
delete: an issued invoice is a financial record, and every correction is an
additional document.

| Action | What it means | Refused when |
|---|---|---|
| Issue | The draft becomes a document. Revenue is recognised and a receivable exists. | Not a draft |
| Credit note | We billed too much. Posts to `revenue_adjustments`. | Still a draft — change the draft instead |
| Withdraw (cancel) | This document should never have existed. Reverses the receivable **and** un-recognises the revenue. | Money has been allocated to it |
| Write off | We billed correctly and will not be paid. Moves the receivable to `bad_debt` and stops collections chasing it. | Nothing outstanding |
| Record payment | Money that arrived outside the providers. Lands as customer credit. | — |
| Allocate | Applies credit to a document. | More than the document owes |
| Reverse allocation | Un-applies it. The original stays on the record. | Already reversed |
| Refund | Returns money. | More than remains refundable |
| Reinstate / exempt | Lifts a suspension, or marks a company the sweep must never suspend on its own. | — |

Every one of them writes an immutable financial audit event carrying the
operator's identity **as values**, so the action stays attributable after the
person who took it has left. Everything except issue and allocate requires a
typed reason, which is the only part a human writes and six months later the
only explanation anybody has.

### The CSV export

`GET /platform/invoices/search?export=csv` follows the **filter**, not the
page — a download that returned only the rows on screen is the subtlest way
to hand somebody an incomplete reconciliation. It is capped at
`EXPORT_ROW_CAP` (5,000) and announces truncation four ways: in the JSON
response before the download (`export_row_cap`), in `X-Export-*` headers, and
in the filename itself (`invoices-2026-07-31-TRUNCATED-5000-of-7321.csv`).
The headers are gone the moment the file lands on a disk; the filename is the
only signal still visible to whoever opens it next week.

Text cells are prefixed with an apostrophe when they begin with `=`, `+`,
`-`, `@`, tab or carriage return. Customer names are written by tenants and
read by our finance team in Excel, which is the one place a cell beginning
`=` stops being text and becomes a command. Amounts are never quoted —
that guard applies to text only, because quoting a negative amount would
corrupt the figures the export exists to carry.

There is no totals row: a column of amounts in two currencies has no honest
sum.

## The invoice document

`GET /platform/invoices/{id}/pdf` (any company, for an operator) and
`GET /billing/invoices/{id}/pdf` (their own, for a customer) render the
document a customer files and pays against.

**Assembled from frozen values only.** `InvoiceDocumentService` gathers the
header and totals from the `invoices` row, the lines from `invoice_lines`, the
tier that set each price from the `usage_period_lines` row the line links to,
the credits from `credit_notes`, the money received from `payment_allocations`,
and what is still owed from `domain.invoicing.amount_owed`. `domain/
invoice_document.py` performs **no arithmetic at all** and
`infrastructure/documents/invoice_pdf.py` performs none either — a renderer
that computed even one of its own figures would be a second billing
implementation, and the first time it disagreed nobody could say which document
was real. A test proves it: change the rate tenfold after issuance and the PDF
is byte-identical.

A **draft has no PDF** (409). It carries no number and has been sent to nobody;
a file that looks like an invoice but is not one is worse than an error.

A **cancelled or written-off** invoice says so on its face, above the amounts.
Its only other signal is a zero balance, which is exactly what a fully paid
invoice shows — and a customer who cannot tell those apart pays a withdrawn
bill.

### Typography, and why a font is vendored

DejaVu Sans ships beside the renderer and every invoice is set in it. Not a
preference: reportlab's base-14 fonts are Latin-1, and a Jordanian company's
legal name rendered in Helvetica comes out as one solid black rectangle per
character — on paper, a redaction. The face covers Latin, Arabic (including all
141 Arabic Presentation Forms), Cyrillic and Greek, and its licence permits
embedding in documents. `BILLING_DOCUMENT_FONT` overrides it.

`infrastructure/documents/arabic.py` shapes Arabic before it is drawn:
contextual forms chosen from what each letter joins to, required lam-alef
ligatures, then reversed into visual order with Latin and digit runs put back
the way round they were written. It is not a general bidi implementation and
does not pretend to be — it handles a company name or a description, which is
what an invoice contains. Text with no Arabic in it is returned untouched.

If a face somehow cannot render a name, the ASCII slug is printed instead and
the substitution is logged. **Never a black box.**

### What is on the page

Issuer mark; invoice number, issue date, due date, currency; customer name and
slug; billing period (stated half-open, because that is what the snapshot
holds); line items with quantity, included, billable, unit price, tier where
one applies, and amount; subtotal, total, credited, paid, amount outstanding;
credit notes issued against it; payments applied to it; a QR document
reference; and the registered legal entity in English and Arabic.

The **QR is a document reference, not a payment instruction** —
`BLINKENGAGE:INVOICE:1:<number>:<date>:<currency>:<total>` — and says so
beside itself. There is no customer-facing payment page to point at, and a QR
resolving to nothing is worse than none because somebody will scan it. The
version field and a single `qr_payload()` mean a future payment link is one
function body and a version bump.

`POST /platform/invoices/{id}/email` sends it to the company's billing
contacts — the same people a dunning notice reaches, defined once in
`billing_contacts`. Each address is attempted individually; what was sent and
what failed are both recorded on the audit event and both returned, because
"sent to two of three" is a different fact from "sent".

## Credit notes are made of invoice lines

An operator selects **lines and quantities, never amounts**. Every description,
unit and price on the resulting note is copied from the invoice line being
credited, so every figure traces back to something that was actually billed.
There is no free-amount path: one that existed for convenience would be the one
used, and a credit nobody can trace to a charge is a number an auditor makes
somebody explain.

| Endpoint | |
|---|---|
| `GET /platform/invoices/{id}/creditable` | each line's billable quantity, what is already credited, what is left, and the two ceilings |
| `POST /platform/invoices/{id}/credit-notes/preview` | what the note would say — run through the **write path's own** validation and arithmetic |
| `POST /platform/invoices/{id}/credit-notes` | issues it |

The preview and the save share one code path, so a total an operator approves
is the total the document carries and a selection accepted by the preview
cannot be refused a moment later. (`PricingService.validated_terms` exists
because this repository already made the opposite mistake once.)

`domain/credit_notes.py` holds the refusals as a closed set of codes —
`unknown_line`, `line_not_on_invoice`, `line_selected_twice`,
`quantity_exceeds_remainder`, `exceeds_invoice_remainder` and the rest — because
a console has to *act* on the answer, and it cannot act on prose.

**Two ceilings, not one.** A line's remainder is what it billed less what
earlier notes took off it. The invoice's remainder is its total less everything
credited — and it can be *smaller* than the line remainders add up to, when an
older whole-invoice credit note consumed credit without naming a line. Both are
returned, and the difference is reported as `unattributed_credited_amount`, so
a console can explain the gap rather than let somebody fill in a form that is
refused on submit.

### The lock, and what it is for

`issue_credit_note` takes `SELECT ... FOR UPDATE` on the invoice row **before**
reading the remainders. Issuing is a check-then-write: read what is creditable,
decide the selection fits, write the note and add to `amount_credited`. Without
the lock, two requests interleave between the read and the write and both are
told yes — eight concurrent notes against a $500 invoice each passed the check
and each was written, leaving $4,000 credited against a $500 document. There is
no database constraint on `amount_credited` to catch it, so the lock and the
tests around it are the whole guarantee.

### Not built yet

Stated explicitly so nobody looks for them:

- **Email and WhatsApp dunning delivery** — notices are in-app today.
  The notification type (`billing.dunning`) and the recipient set are in
  place; only the additional transports are missing.
- **A customer-facing payment page** — checkout is started through the
  platform API, so today an operator sends the approval link. The intent
  and return/cancel URLs are already modelled for a self-service page.
- **A credit note has no PDF of its own.** It is printed on the invoice it
  corrects, which is where somebody reconciling the two looks.
- **Contracts, taxes and discounts** — later phases.
- **Partial-payment plans.**
