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

## Not built yet

Stated explicitly so nobody looks for them:

- **Pricing engine** — the effective-dated, three-level price resolution
  (company override → pricing profile → global default). In progress;
  the metric catalog above is its first piece.
- **Usage engine** — usage records, aggregation, and the meters that
  emit them. The catalog names what *would* be measured; nothing
  measures it yet.
- **Invoices** — monthly billing periods, invoice generation, Net 21
  terms.
- **Billing states** — Active / Payment Due / Payment Overdue / Payment
  Suspended, as an axis separate from compliance suspension.
- **Payment gateway** — deliberately out of scope until the phases above
  land.
- **Contracts, taxes, discounts, tiered pricing** — later phases.

Company suspension today is the single compliance-style suspension
described in [`platform-admin.md`](platform-admin.md). Splitting it into
a billing axis and a compliance axis belongs to the billing-states phase
above and has not been done.
