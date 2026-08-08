# Context Help — Admin Surface

**Help for the provider's own administration screens.**

These describe running Blink Engage as a platform, not using it as a
customer. Every entry here is `surface: admin` and **must never reach a
tenant** — they describe managing other companies.

- **Surfaces:** [surfaces.md](./surfaces.md)
- **IDs:** [help-ids.md](./help-ids.md)
- **Tenant screens:** [context-help.md](./context-help.md)

Same five-part shape as the tenant entries, plus a sixth where it earns
its place: **Careful** — the consequence of getting it wrong. Provider
actions affect somebody else's business, so the warnings are stronger.

---

## `be.platform.overview` — Platform home

**What is this page?**
Every company on this deployment, and how the platform is doing overall.

**What can I do here?**
See the list of companies, open one to manage it, and reach billing,
health and pricing.

**Common tasks**
1. Open a company to change its plan, owner or status.
2. Check platform health before investigating a customer report.
3. Review revenue for the current period.

**Tips**
- When a customer reports a problem, check **Platform health** first. A
  scheduler that has stopped affects every company at once, and you will
  otherwise debug one customer's symptom.

**Careful**
Everything here spans companies. A change made on the wrong company
affects a real business that did not ask for it.

**Related pages**
Companies · Platform health · Revenue

---

## `be.platform.companies` — Companies

**What is this page?**
Every customer workspace: its status, plan, owner and usage.

**What can I do here?**
Create a company, change which features its plan includes, transfer
ownership, and suspend or reactivate it.

**Common tasks**
1. Open a company to see its state.
2. Change **features** to match what they have bought.
3. Transfer **ownership** when their owner leaves.
4. Change **status** to suspend or restore access.

**Tips**
- Feature changes take effect immediately. A customer watching their
  screen will see menu items appear or vanish.
- Turning a feature **off** hides it entirely rather than blocking it, so
  a customer will report the menu item as "missing", not "denied".

**Careful**
**Suspending a company stops its customers being answered.** Conversations
keep arriving on connected channels and nobody can reply. Confirm the
commercial decision before changing status, and tell them first.

**Related pages**
Company users · Company billing · Pricing

---

## `be.platform.company_users` — Company users

**What is this page?**
The people inside one customer's workspace.

**What can I do here?**
Change a user's role, activate or deactivate them, and resend or force
email verification.

**Common tasks**
1. Resend verification when a customer says an invitation never arrived.
2. Restore access for somebody locked out.
3. Change a role when the customer's owner cannot.

**Tips**
- Prefer talking the customer through doing it themselves. Acting on
  their behalf leaves an audit entry attributed to you, and they lose the
  record of who decided it.
- Verification problems are usually email delivery, not the account.
  Check the mail screen before changing anything.

**Careful**
Changing somebody's role changes what they can see in a live workspace.
Deactivating the wrong user removes a working agent mid-conversation.

**Related pages**
Companies · Mail

---

## `be.platform.billing` — Revenue

**What is this page?**
What the platform has earned, across all companies.

**What can I do here?**
Review revenue for a period, and open any company's contribution.

**Common tasks**
1. Review the current period.
2. Compare against the previous one.
3. Open a company whose usage moved unexpectedly.

**Tips**
- A sharp change for one company is usually a real change in their
  business, but check for a stuck consumer before assuming — a lagging
  usage consumer under-reports rather than erroring.

**Related pages**
Invoices · Ledger · Pricing

---

## `be.platform.invoices` — Invoices

**What is this page?**
Invoices across every company, and the audit trail behind them.

**What can I do here?**
Generate invoices for a closed period, review them, and trace how any
figure was produced.

**Common tasks**
1. Generate invoices once a billing period has closed.
2. Open an invoice to see what it covers.
3. Use the audit view to trace a disputed figure back to the usage that
   produced it.

**Tips**
- Every invoice figure can be traced to the usage records behind it. When
  a customer disputes an amount, start there rather than recalculating.
- A `usage.late_record_rejected` event means usage arrived after its
  period closed. Occasional is normal; frequent points at a lagging
  consumer.

**Careful**
**An issued invoice cannot be edited.** Correct it with a credit note.
This is deliberate — an editable invoice is not an accounting record.

**Related pages**
Ledger · Collections · Revenue

---

## `be.platform.ledger` — Ledger

**What is this page?**
The financial record: what was charged, paid, credited and owed.

**What can I do here?**
Review entries and trace balances.

**Tips**
- The ledger refuses entries that would leave the accounts inconsistent.
  If an entry is rejected, the amounts or dates are wrong — the
  restriction is protecting the record.

**Careful**
Ledger entries are the financial truth of the platform. Treat a rejection
as information, not an obstacle to work around.

**Related pages**
Invoices · Payments

---

## `be.platform.payments` — Payments

**What is this page?**
Payments received, attempted and refunded, and the providers configured.

**What can I do here?**
Review payments, investigate failures, and check provider configuration.

**Common tasks**
1. Investigate a failed payment — the provider's own message says why.
2. Confirm a payment was recorded against the right invoice.
3. Check provider credentials after a run of failures.

**Tips**
- A failed payment takes no money. Tell the customer that first; it is
  the thing they are worried about.
- **`PAYPAL_ENVIRONMENT` does nothing.** The setting that controls live
  versus sandbox is `PAYPAL_SANDBOX`. A deployment believing it is live
  because of the first variable is silently taking no real money — see
  [TD-1](../releases/v1.0-technical-debt.md#td-1).

**Careful**
Refunds are restricted by window and by state. When a refund is refused,
issue a credit note instead rather than looking for a way around it.

**Related pages**
Invoices · Ledger · Collections

---

## `be.platform.collections` — Collections

**What is this page?**
Companies with money outstanding, and where each is in the dunning
process.

**What can I do here?**
Review overdue accounts and what has been chased.

**Tips**
- Check whether the customer is actually using the platform before
  escalating. An unused workspace with an unpaid invoice is a churn
  conversation, not a collections one.

**Careful**
Suspension is a commercial decision with an immediate operational effect:
their customers stop being answered. It is not a collections lever to
pull automatically.

**Related pages**
Companies · Invoices

---

## `be.platform.pricing` — Pricing

**What is this page?**
What the platform charges, in general and per company.

**What can I do here?**
Define rates, set effective dates, and apply company-specific pricing.

**Common tasks**
1. Review current rates.
2. Add a new rate with a future effective date.
3. Set a specific price for one company.

**Tips**
- **A rate that has taken effect cannot be changed.** Create a new one
  with a future date. Invoices may already depend on the old rate, and
  changing it would rewrite history.
- Overlapping ranges are rejected rather than resolved. The platform
  stops instead of guessing which price applies — a guess here is a
  wrong invoice.

**Careful**
Pricing changes affect real invoices. Set effective dates deliberately,
and check for an overlap before saving.

**Related pages**
Companies · Invoices · Revenue

---

## `be.platform.mail` — Mail

**What is this page?**
Email the platform has sent — invitations, verifications, notifications,
invoices.

**What can I do here?**
Confirm whether a specific message was sent, and investigate delivery
failures.

**Common tasks**
1. A customer says an invitation never arrived — check here first.
2. Confirm a verification email was sent before resetting anything.
3. Look for a pattern in failures pointing at configuration.

**Tips**
- "Sent" and "delivered" are different. If it was sent and the customer
  does not have it, the next place to look is their spam folder, then
  their mail provider.
- Most "cannot sign in" reports resolve here.

**Related pages**
Company users · Platform health

---

## `be.platform.health` — Platform health

**What is this page?**
Whether the platform's background work is running: scheduled sweeps,
queues, and the services everything depends on.

**What can I do here?**
See which scheduled tasks have run recently and whether anything has
stopped.

**Common tasks**
1. Check this before investigating any customer report — a platform-wide
   problem looks like many unrelated customer problems.
2. Confirm scheduled sweeps are running.
3. Check queue depth if messages are arriving late.

**Tips**
- **A stopped sweep produces no error.** It simply stops happening, which
  is why staleness is measured per task against its own schedule rather
  than against one global threshold.
- If several customers report different symptoms at once, the cause is
  usually one thing here.

**Careful**
This screen shows the platform, not one customer. A green screen does not
mean a specific customer's channel is working — check their channel
status too.

**Related pages**
Operator runbook · Companies

---

## Operational documents on this surface

Not screens. Reached from the admin help index.

| Topic | Document |
|---|---|
| Day-to-day operations | [runbooks.md](../deployment/runbooks.md) |
| Backups and recovery | [disaster-recovery.md](../deployment/disaster-recovery.md) |
| Deploying and upgrading | [production-deployment-guide.md](../deployment/production-deployment-guide.md) |
| Draining a dead-letter queue | [runbooks.md](../deployment/runbooks.md#drain-a-dead-letter-queue) |
| Checking alerts reach a human | [runbooks.md](../deployment/runbooks.md#verify-alerts-still-reach-a-human) |
| Tracing one request end to end | [runbooks.md](../deployment/runbooks.md#trace-one-request-across-the-whole-platform) |
| What is known to be wrong | [technical-debt.md](../releases/v1.0-technical-debt.md) |
| What is deliberately not built | [known-limitations.md](../releases/v1.0-known-limitations.md) |
| Event catalogue | [event-catalogue.md](../architecture/event-catalogue.md) |
| Architecture | [architecture index](../architecture/README.md) |
| The baseline | [v1.0-baseline.md](../releases/v1.0-baseline.md) |
| What comes next | [post-launch-roadmap.md](../releases/post-launch-roadmap.md) |

---

## Answering a customer question

The three checks that resolve most reports, in order:

1. **Platform health** — is this everyone, or just them?
2. **Mail** — did the email they are waiting for actually go?
3. **Their channel status** — is the way their customers reach them
   working?

Then ask for the **correlation id** if there is an error on screen, or
the time and conversation reference if there is not. Either one turns an
afternoon of searching into a single lookup.

## The six answers most often needed

| Customer says | Actual answer |
|---|---|
| "Our SLA numbers are wrong" | Business hours are not configured |
| "Messages are not arriving" | Channel credentials saved but never tested, or expired |
| "Where do I add knowledge articles?" | No screen exists; the provider maintains it via the API |
| "Intelligence is empty" | Not enough conversations yet — expected, not broken |
| "I cannot generate an API key" | No API key screen exists in this release |
| "The menu item is missing" | Their plan lacks the feature, or their role lacks the permission |

Four of these are "working as designed but nobody could have known".
Answer them plainly rather than treating them as faults.

---

## Coverage

| Group | Entries |
|---|---|
| Provider screens | 11 |
| Operational documents | 12 |

---

## See also

- [Surfaces](./surfaces.md)
- [Tenant context help](./context-help.md)
- [Error messages](./error-messages.md)
- [Operator runbook](../deployment/runbooks.md)
