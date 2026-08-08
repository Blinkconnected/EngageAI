# Error Message Catalogue

**Every user-facing error, in plain English.**

Each entry says three things, always in this order:

1. **What happened** — in the user's words, not the system's
2. **Why** — the cause, if we can know it
3. **How to fix it** — one clear next step

Errors are grouped by the platform's own error types, so every one that
can reach a user is covered.

- **Source of truth:** [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **IDs:** [help-ids.md](./help-ids.md)

---

## Writing rules

| Rule | Reason |
|---|---|
| **Never show a raw error code alone** | It tells the user nothing and makes them feel stupid |
| **Never blame the user** | "You entered an invalid value" → "That date is in the past" |
| **Say what to do next** | An error with no next step is a dead end |
| **Do not expose internals** | Table names, stack traces and class names help nobody outside engineering |
| **Distinguish "you cannot" from "not yet configured"** | Completely different fixes: one needs a role, one needs an administrator |
| **Keep the reference** | Show a short code in small text for support, not as the message |

> **The distinction that matters most:** *you do not have permission* and
> *your company does not have this feature* look identical to a user and
> need completely different actions. One is a role change, the other is a
> plan change. Always say which.

---

## Sign in and access

### `AuthenticationError` — 401

> **We could not sign you in**
>
> The email address or password did not match.
>
> Check the email address is right, then try again. If you still cannot
> get in, use **Forgot password?**.

**Also check:** you are on the right web address for your company. That
is the most common cause of this message.

### Session expired — 401

> **You have been signed out**
>
> Your session ended. This happens after a long period, or when an
> administrator changes security settings.
>
> Sign in again to continue. Anything you had typed but not sent will not
> be saved.

### `EmailNotVerifiedError` — 403

> **Please verify your email first**
>
> Your account exists, but the email address has not been confirmed.
>
> Open the verification email and select the link. If you cannot find it,
> check your spam folder or ask your administrator to send it again.

### `AuthorizationError` — 403

> **You do not have access to this**
>
> Your role does not include permission for this action.
>
> Ask your administrator to review your role. If a colleague can do it
> and you cannot, this is the reason.

### Feature not enabled — 403

> **This feature is not part of your plan**
>
> {Feature name} is not enabled for your company.
>
> Speak to your administrator about adding it. This is different from a
> permission — no one in your company can use it, not just you.

### `AgentMissingRequiredSkillError` — 403

> **This conversation needs a different skill**
>
> This queue requires a skill that is not on your profile.
>
> Ask a colleague with that skill to take it, or ask your administrator
> to add the skill to your profile.

---

## Conversations

### `ConversationAlreadyClaimedError` — 409

> **Someone else got there first**
>
> Another agent picked up this conversation a moment before you did.
>
> Refresh to see who has it. If you need to take over, ask them or use
> **Transfer**.

### `EntityNotFoundError` (conversation) — 404

> **This conversation no longer exists**
>
> It may have been merged, or the link may be out of date.
>
> Go back to the Inbox and search for the customer's name.

### Message send failed

> **Your reply was not sent**
>
> We could not deliver it to {channel}.
>
> Check **Channel status** — an expired connection is the usual cause.
> Your text has been kept, so you can send it again once the channel is
> working.

> **Note for whoever builds this:** never discard the agent's typed text
> on a send failure. Retyping a long reply is the difference between an
> annoyance and a complaint.

### Message rejected by the channel

> **{Channel} would not accept this message**
>
> {Channel} rejected it. Common reasons are a message that is too long,
> an unsupported file type, or a time limit on replying.
>
> Try shortening it, sending the file another way, or contacting the
> customer through a different channel.

### Attachment too large

> **That file is too big**
>
> The limit is {size}. This file is {actual}.
>
> Send a smaller version, or email it instead. Note that each channel has
> its own limit as well — WhatsApp accepts less than email.

### Attachment type not allowed

> **That file type is not allowed**
>
> {Extension} files cannot be sent for security reasons.
>
> Convert it to an allowed format, such as PDF or an image.

---

## Customers

### `EntityAlreadyExistsError` (customer) — 409

> **A customer with these details already exists**
>
> Another record already uses this email address or phone number.
>
> Search for the customer instead of creating a new one — you probably
> want the existing record.

### `EntityNotFoundError` (customer) — 404

> **We could not find that customer**
>
> The record may have been removed, or the link may be out of date.
>
> Search for them by name, email or phone.

---

## Channels

### Connection test failed

> **We could not connect to {channel}**
>
> {Provider's own message.}
>
> Check the credentials are copied exactly, with no extra spaces. They
> come from {provider}, not from Blink Engage.

> **Note:** show the provider's message verbatim. It usually names the
> exact problem, and rewording it loses the detail.

### Credentials expired

> **{Channel} needs reconnecting**
>
> The credentials have expired. {Provider} expires them periodically.
>
> Get new credentials from {provider} and enter them again. Use **Test
> connection** before saving.

### `EntityAlreadyExistsError` (channel) — 409

> **This channel is already connected**
>
> A channel with these details already exists in your workspace.
>
> Open the existing channel to update it instead of adding another.

---

## Queues, routing and SLA

### `QueueSlaOwnedByServiceError` — 409

> **This queue's targets come from its service**
>
> Response targets are now set on the service, so they cannot be set on
> the queue as well. This keeps one answer instead of two that disagree.
>
> Open the service this queue belongs to and set the targets there.

### Catch-all rule deletion

> **Are you sure? This is your safety net**
>
> The catch-all rule is what catches conversations no other rule matches.
> Without it, those conversations reach no queue at all and nobody sees
> them.
>
> Only remove it if another rule with no conditions exists.
>
> **[Cancel]** · [Delete anyway]

**Not an error — a confirmation.** It belongs here because it prevents
the most damaging configuration mistake in the product.

### Queue in use

> **This queue is still being used**
>
> Routing rules still point at it, or conversations are waiting in it.
>
> Move the conversations elsewhere and update the rules, then try again.

---

## AI

### `AiNotConfiguredError` — 503

> **AI is not set up yet**
>
> Your workspace has the AI feature, but no provider has been configured.
>
> Ask your administrator to choose a provider in **Settings → AI**.

### `EmbeddingNotConfiguredError` — 503

> **Knowledge search is not available**
>
> The part of the AI that searches your knowledge base has not been set
> up.
>
> Ask your administrator. Until then, search your knowledge manually.

### `EmbeddingDimensionMismatchError` — 500

> **Knowledge search needs attention from your administrator**
>
> A configuration change means stored knowledge and the current settings
> no longer match.
>
> This needs an administrator — it is not something you can fix or work
> around. Other AI features may still work.

> **Note:** this is a deployment problem, not a user mistake. Say so, and
> do not offer a retry that cannot succeed.

### AI request failed

> **The AI could not answer this time**
>
> The AI service did not respond.
>
> Try again in a moment. If it keeps happening, tell your administrator —
> your AI provider may be having problems.

### AI provider rate limited — 429

> **The AI is busy**
>
> Your AI provider is limiting requests because of high demand.
>
> Wait a minute and try again.

### `ThresholdOutOfBoundsError` — 422

> **That value is outside the safe range**
>
> {Setting} must be between {min} and {max}. Values outside this range
> have been measured to produce poor results.
>
> Choose a value inside the range.

---

## ERP

### `ErpNotConfiguredError` — 503

> **ERP is not connected**
>
> No ERP connection has been set up for your workspace.
>
> Ask your administrator to connect ERPNext in **Settings**.

### ERP sync failed

> **We could not reach your ERP system**
>
> {ERP's own message.}
>
> Check the ERP system is running and its credentials are still valid.
> Conversations are unaffected — only the ERP data is missing.

---

## Billing

### `InvoiceStateError` · `InvalidInvoiceTransitionError` — 409

> **This invoice cannot be changed now**
>
> An invoice can only be changed at certain stages, and this one has
> moved past that point.
>
> Open the invoice to see its current state. A credit note may be what
> you need instead.

### `InvoiceNotPayableError` — 409

> **This invoice cannot be paid**
>
> It has already been paid, cancelled, or is not yet issued.
>
> Open it to see its current state.

### `PaymentProcessingError` — 409

> **The payment did not go through**
>
> {Payment provider's message.}
>
> No money has been taken. Check the payment details and try again.

### `RefundNotPermittedError` — 409

> **This cannot be refunded**
>
> The payment is outside the refund window, or has already been
> refunded.
>
> Issue a credit note instead, or contact support.

### `PricingNotConfiguredError` — 503

> **Pricing has not been set up**
>
> Your workspace has no pricing configured, so charges cannot be
> calculated.
>
> Contact your provider.

### `AmbiguousPricingConfigurationError` · `PricingRangeOverlapError` — 409

> **The pricing setup is contradictory**
>
> Two pricing rules overlap, so we cannot tell which applies.
>
> This needs your provider to correct. Nothing has been charged
> incorrectly — we stop rather than guess.

### `PricingConcurrentEditError` — 409

> **Somebody else changed this first**
>
> Another person saved a change while you were editing.
>
> Reload the page and make your change again, so you are working from the
> current version.

### `MetricNotPriceableError` · `SystemProfileNotPriceableError` — 409

> **This cannot be priced**
>
> There is no price defined for this item.
>
> Contact your provider to have it added.

### `RateAlreadyEffectiveError` — 409

> **This rate is already in effect**
>
> A rate that has started cannot be changed, because invoices may already
> depend on it.
>
> Create a new rate with a future start date instead.

### `InvalidPricingTermsError` — 422

> **These pricing terms are not valid**
>
> {Specific problem.}
>
> Correct the highlighted values and save again.

### `LedgerError` — 409

> **This entry cannot be recorded**
>
> It would leave the accounts inconsistent.
>
> Check the amounts and dates. If they look right, contact your provider
> — financial records are deliberately strict about this.

### `UnknownCurrencyError` · `UnknownCountryError` — 422

> **That {currency/country} is not supported**
>
> Blink Engage cannot bill in {value}.
>
> Choose one from the list. If you need it added, contact your provider.

---

## General

### `EntityNotFoundError` — 404

> **We could not find that**
>
> It may have been deleted, or the link may be out of date.
>
> Go back and try again from the list.

### `EntityAlreadyExistsError` — 409

> **That already exists**
>
> Something with the same name or details is already here.
>
> Choose a different name, or open the existing one.

### Validation error — 422

> **Some details need correcting**
>
> {Field-by-field messages shown against each field.}
>
> Fix the highlighted fields and save again.

**Always show validation messages against the field**, not in a banner.
A banner saying "some fields are invalid" makes the user hunt.

### Rate limited — 429

> **Too many requests**
>
> You have done that too many times in a short period.
>
> Wait a minute and try again.

### Server error — 500

> **Something went wrong at our end**
>
> This is not your fault, and nothing you did caused it.
>
> Try again in a moment. If it keeps happening, tell your administrator
> and give them the time it happened and what you were doing.
>
> *Reference: {correlation id}*

> **Show the reference.** It is what lets an operator find exactly what
> happened in one lookup rather than an afternoon of searching. Make it
> selectable so the user can copy it.

### Service unavailable — 503

> **This part of the platform is temporarily unavailable**
>
> A service we depend on is not responding.
>
> Try again shortly. Conversations already open are not affected.

### Network error

> **You appear to be offline**
>
> We cannot reach Blink Engage.
>
> Check your internet connection. Anything you have typed is still on
> screen and will send once you reconnect.

### Version conflict — 409

> **Somebody else changed this while you were editing**
>
> Your version and theirs would overwrite each other.
>
> Reload to see their change, then make yours again.

---

## Coverage

| Group | Messages |
|---|---|
| Sign in and access | 6 |
| Conversations | 6 |
| Customers | 2 |
| Channels | 3 |
| Queues, routing, SLA | 3 |
| AI | 6 |
| ERP | 2 |
| Billing | 11 |
| General | 8 |
| **Total** | **47** |

Every domain error type the platform maps to an HTTP status is covered.

## Checklist for a new error message

- [ ] Says what happened, in the user's words
- [ ] Says why, if we can know
- [ ] Gives one clear next step
- [ ] Does not blame the user
- [ ] Distinguishes permission from plan
- [ ] Preserves anything the user typed
- [ ] Shows a reference on a server error
- [ ] Exposes no internals

---

## See also

- [Empty states](./empty-states.md)
- [Context help](./context-help.md)
- [Troubleshooting](../guides/blink-engage-user-guide.md#14-troubleshooting)
