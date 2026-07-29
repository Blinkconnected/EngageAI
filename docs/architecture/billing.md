# Billing, Subscriptions and Feature Entitlements

How the platform charges companies for their workspace, and how a
platform operator controls what each company may use. The operator tier
that owns all of this is described in
[`platform-admin.md`](platform-admin.md).

Two rules shape almost every decision here:

- **Never bill twice.** PayPal delivers webhooks at-least-once and
  retries every non-2xx for up to three days.
- **Never lock out a paying customer.** A transient card decline must
  not cost a company their helpdesk.

## Where the credentials live

PayPal is configured with **environment variables**, never database
rows:

```
PAYPAL_ENVIRONMENT=sandbox      # or: live
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_WEBHOOK_ID=...
```

This is the opposite direction from `ChannelConfig.credentials`, which
holds a *tenant's* own provider account and is therefore per-company and
encrypted at rest. PayPal here is the **platform operator's own merchant
account** — there is exactly one per installation, and it follows the
same shape as `SMTP_PASSWORD` and `OPENAI_API_KEY`. Keeping it out of the
database means no API response, backup, or platform-admin session can
ever expose it.

An installation with no PayPal credentials still starts and still serves
every billing endpoint: `GET /billing` answers `is_configured: false` and
the page explains itself rather than offering a Subscribe button that can
only fail. Actions that genuinely need PayPal raise
`BillingNotConfiguredError` → **503**.

`PAYPAL_WEBHOOK_ID` is separately required to *verify* inbound webhooks.
Without it the webhook handler **fails closed** and processes nothing —
acting on an unverified request would let anyone who can reach the URL
activate a paid subscription for free.

## The schema

Migration `583624ea9a99`, four tables:

| Table | Holds | Notable |
|---|---|---|
| `billing_plans` | The platform-wide price list | No `company_id` — one catalog for everyone |
| `subscriptions` | One company's subscription to one plan | Not soft-deletable; `company_id` not unique |
| `billing_payments` | Individual charges | `paypal_capture_id` **unique** |
| `billing_webhook_events` | Every PayPal event already processed | `paypal_event_id` **unique** |

Money is `NUMERIC(12, 2)` throughout, never a float: a binary float
cannot represent `0.10` exactly, and an invoice total that drifts by a
cent is a defect a customer disputes.

`subscriptions.company_id` is deliberately **not** unique. A company that
cancels and later re-subscribes keeps both rows for its revenue history;
the *current* subscription is the newest one not in `CANCELLED`/
`EXPIRED`.

`SubscriptionStatus` mirrors PayPal's own vocabulary rather than
inventing a parallel one, so a support engineer comparing this table
against the PayPal dashboard is comparing like with like.

## The subscribe flow

1. `POST /billing/subscribe {plan_id}` creates the subscription at PayPal
   and stores it as `APPROVAL_PENDING`, carrying PayPal's `approval_url`.
2. The customer approves it in PayPal's checkout.
3. PayPal sends `BILLING.SUBSCRIPTION.ACTIVATED`, and *that* is what
   marks it `ACTIVE`.

Step 3 is the load-bearing one. Marking a subscription active on our own
say-so at step 1 would grant a paid workspace to anyone who started a
checkout and walked away.

`approval_url` is stored rather than discarded so the billing page can
re-offer the link if the customer closed PayPal's window mid-checkout,
instead of stranding a pending subscription with no way to finish it.

**Cancelling does not suspend the company.** They have paid through the
end of the current period; taking their workspace away the moment they
click cancel would be taking the balance of a term they already bought.
PayPal reports `EXPIRED` when the paid period actually runs out, and that
is what ends access.

## Webhooks

`POST /api/v1/webhooks/paypal` — public, unauthenticated in the HTTP
sense (PayPal has no bearer token to present) but never *unverified*.
Every delivery is checked with PayPal's own
`/v1/notifications/verify-webhook-signature` API.

> **Route order matters.** `paypal_webhooks.router` is registered
> *before* `webhooks.router`, whose `/webhooks/{channel_config_id}` path
> parameter would otherwise swallow `/webhooks/paypal` and answer 422
> ("paypal is not a valid UUID"). This was a real bug caught by the
> integration tests.

The API-based signature check is deliberate rather than verifying the
certificate chain locally: PayPal rotates its signing certificates, and
an offline verifier that pins or caches them fails closed at rotation
time — silently rejecting real payment events, the worst possible failure
mode for billing.

**The route always answers 204, even when it rejects the request.** That
is the opposite of the usual advice and it is intentional: PayPal retries
any non-2xx for three days, so returning an error for an event already
durably recorded — or one that will never be handled — buys nothing but a
retry storm against a payment path.

### Idempotency, twice over

1. `billing_webhook_events.paypal_event_id` is unique and checked before
   anything is applied.
2. `billing_payments.paypal_capture_id` is unique and checked again
   inside payment handling, because PayPal can report the same capture
   under more than one event id.

A **rejected** (unverified) delivery is deliberately *not* recorded.
Storing it would let a forger burn a real event id so the genuine
delivery is later skipped as a duplicate.

### Events handled

| PayPal event | Effect |
|---|---|
| `BILLING.SUBSCRIPTION.ACTIVATED` / `RE-ACTIVATED` / `UPDATED` | Mirror status; activate the company |
| `BILLING.SUBSCRIPTION.SUSPENDED` / `EXPIRED` | **Suspend the company** |
| `BILLING.SUBSCRIPTION.CANCELLED` | Mirror status; access continues |
| `BILLING.SUBSCRIPTION.PAYMENT.FAILED` | Count it; suspend only at the threshold |
| `PAYMENT.SALE.COMPLETED` | Record the payment; restore access |
| `PAYMENT.SALE.DENIED` / `REFUNDED` | Record it, not completed |

Anything else is recorded and ignored. PayPal sends far more event types
than this product subscribes to, and erroring on them would turn every
unrelated account event into a retry storm.

> A PayPal **Sale** resource's `id` is the *capture* id;
> `billing_agreement_id` is the subscription. `_load` therefore checks
> `billing_agreement_id` first. Reading `id` first looked every payment
> up by its capture id, found nothing, and dropped the charge as
> "unknown subscription" — a real bug, caught by the tests.

## Suspension, and getting back

Suspension for non-payment reuses the machinery `platform-admin.md`
describes: `Company.status = SUSPENDED`, enforced at sign-in, at refresh,
and on every permission-gated request.

**A single failed payment does not suspend anybody.** PayPal runs its own
dunning retries and only reports `SUSPENDED` once it gives up; that is
the primary mechanism. `BILLING_FAILED_PAYMENTS_BEFORE_SUSPEND`
(default 3) is a backstop behind it, not a replacement.

Recovery is deliberately **asymmetric**. A successful payment lifts a
suspension *only* if billing imposed it, which
`Subscription.company_suspended_at` records. A company an operator shut
off for abuse stays off, whatever PayPal later reports — otherwise anyone
could buy their way back in.

A billing suspension publishes `platform.company_status_changed` with
`source: "billing"` and **no actor**: nobody decided it, a rule did, and
attributing it to a user would make the audit trail claim a person did
it.

**A suspended company keeps receiving customer messages.** Webhook and
web-chat ingress are untouched, so a billing dispute never makes a tenant
silently drop their own customers.

### Known limitation

A company suspended for non-payment **cannot sign in to pay**, because
suspension blocks sign-in entirely (the deliberate choice recorded in
`platform-admin.md`). In practice PayPal's own retries and the
`PAYMENT.SALE.COMPLETED` webhook restore access without anyone signing
in, and the sign-in refusal names suspension rather than blaming the
password. A billing-only login for suspended tenants is the obvious next
step and is not built.

## Feature entitlements

Migration `7125cf36c6a0`. A platform administrator controls which product
features each company may use — see
[`domain/features.py`](../../backend/src/blinkengage/domain/features.py)
for the catalog.

**Resolution order**, most specific first:

1. **A per-company override** (`companies.feature_overrides`), absolute
   in both directions. An operator can grant a feature to a company on a
   cheaper plan (a pilot, a negotiated contract) or revoke one from a
   company abusing it, without inventing a bespoke plan for one customer.
2. **The plan's feature set** (`billing_plans.features`), if the company
   has a live subscription and that plan declares one.
3. **The catalog default**, which is `True` for every feature.

`billing_plans.features = NULL` means **"grants everything"**,
deliberately distinct from `[]` (grants nothing). An operator who has not
thought about entitlements yet must not silently strip features from
their paying customers.

Point 3 is what makes this safe to deploy: an existing installation has
no plans and no overrides, so every company resolves to "everything
enabled" — exactly what they had before. **Entitlement is opt-in
restriction, never opt-in permission.**

`feature_overrides` is its own column rather than a key inside
`Company.settings` precisely because `settings` is tenant-editable via
`company.manage`. A company must never be able to grant itself a feature
it has not bought.

### Features vs permissions

They answer different questions and are stacked, never substituted:

| | Question | Catalog | Failure |
|---|---|---|---|
| Permission | May this **user** do it? | `domain/rbac.py` | 403 |
| Feature | Has this **company** bought it? | `domain/features.py` | **402** |

402 Payment Required, not 403: telling an administrator they lack
permission for something their own role grants would send them to edit
roles that were never the problem.

### Where it is enforced

Applied at router registration in `api/v1/router.py`, not per endpoint —
one place to read, and a new endpoint added to a gated router inherits
the gate instead of quietly shipping ungated.

| Feature | Gated |
|---|---|
| `ai` | the whole `/ai` router |
| `erp` | `/erp-configs` |
| `workflows` | `/workflows` |
| `knowledge_base` | `/knowledge` |
| `sla` | `/sla-policies`, holidays, escalation |
| `reports_export` | `require_export_feature` — only when `?export=` is present |

`reports_export` is separate on purpose: a plan without exports still
gets its dashboards on screen. Gating the whole reports router would be
the difference between a tiered product and a broken one.

Customer satisfaction surveys and the web-chat widget are deliberately
**not** in the catalog even though both are sellable: they are public,
customer-facing routes with no authenticated company to resolve an
entitlement from, so a toggle for them would render in the console and
change nothing. A switch that does not switch anything is worse than no
switch.

The frontend reads the resolved list from `/auth/me` (`features`) and
hides what a company does not have, so nobody is shown a page that 402s
the moment they open it. It is carried on the profile because the
navigation needs it before the first screen renders.

## API surface

Tenant, under `/api/v1/billing` — every route scoped to the caller's own
company like the rest of the tenant API:

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /billing` | `billing.read` | Subscription, plans on offer, payment history |
| `GET /billing/plans` | `billing.read` | Purchasable plans |
| `POST /billing/subscribe` | `billing.manage` | Start a subscription; returns the approval link |
| `POST /billing/cancel` | `billing.manage` | Cancel; access continues to period end |

`billing.manage` is **Owner-only by default** — the one permission in the
catalog that moves real money. `billing.read` also goes to Admin.

Platform, under `/api/v1/platform` (gated by `get_platform_auth`):

| Endpoint | Purpose |
|---|---|
| `GET /plans` | Every plan, including withdrawn ones |
| `POST /plans` | Publish a plan to PayPal and the catalog |
| `PATCH /plans/{id}/status` | Withdraw from sale, or restore |
| `GET /companies/{id}/subscription` | One company's billing state |
| `GET /features` | The feature catalog |
| `GET /companies/{id}/features` | Resolved per company, **with its source** |
| `PUT /companies/{id}/features` | Replace that company's overrides |

The features endpoint is a **PUT, not a PATCH**: the body replaces the
whole override map, so omitting a key clears its override and returns
that feature to following the plan. With a merge there would be no way to
undo one, and a company would be pinned to an operator's one-off decision
forever.

`GET /companies/{id}/features` returns each feature's `source`
(`override` / `plan` / `default`) because an operator fixes a
plan-disabled feature differently from an override-disabled one.

Withdrawing a plan deliberately **does not touch existing subscribers**:
a company already paying for a retired plan keeps that price until they
change plan themselves. Silently re-pricing an existing customer because
an operator archived a plan would be a surprise charge.

Price and interval are fixed once a plan is created, because PayPal
treats them that way. Repricing means publishing a new plan.

## Setting it up

1. Create a PayPal app (sandbox or live) and copy its client id/secret.
2. Register a webhook in PayPal pointing at
   `https://<your-host>/api/v1/webhooks/paypal`, subscribing to the
   events in the table above, and copy its **webhook id**.
3. Put all four values in `.env` and restart the backend.
4. Sign in as a platform administrator, open **Plans**, and create one.
5. Companies see it on **Billing** and can subscribe.

## Deliberately not built

- **Proration and mid-term plan changes.** A company cancels and
  re-subscribes. Getting proration wrong means charging people the wrong
  amount, and PayPal's own revision API has enough edge cases to deserve
  its own milestone.
- **Usage-based billing** (per agent, per conversation). Every plan here
  is a flat recurring price.
- **Tax and invoicing documents.** PayPal issues its own receipts;
  producing VAT-compliant invoices is a jurisdiction-specific problem,
  not a schema one.
- **Any payment provider other than PayPal.** `PayPalClient` is
  deliberately concrete rather than an abstract `PaymentProvider` with
  one implementation — an interface designed against a single provider
  usually fits only that provider.
