# Help Surfaces

**The same content, delivered in three places, to three different
audiences.**

Help appears on three surfaces:

| Surface | Who sees it | Signed in? |
|---|---|---|
| **Public** | Anyone — prospects, customers before they log in, search engines | No |
| **Tenant** | People working inside a customer workspace | Yes |
| **Admin** | The platform provider running Blink Engage | Yes, provider role |

**One source, three renderings.** The content is written once, in the
Help Center documents, and each surface renders the subset it is allowed
to show. Nothing is written twice — a forked copy drifts, and the copy
that drifts is always the one the customer reads.

- **IDs:** [help-ids.md](./help-ids.md)
- **Content:** [context-help.md](./context-help.md) ·
  [context-help-admin.md](./context-help-admin.md) ·
  [tooltips.md](./tooltips.md) ·
  [empty-states.md](./empty-states.md) ·
  [error-messages.md](./error-messages.md) ·
  [product-tour.md](./product-tour.md) ·
  [search-index.md](./search-index.md)

---

## 1. The surface field

Every help entry gains one field. It is the only thing that decides where
an entry appears.

```
surface: public | tenant | admin
```

Surfaces are **cumulative upward**:

```
   public  ──►  everyone sees it
      │
   tenant  ──►  signed-in workspace users and the provider
      │
   admin   ──►  the provider only
```

An entry marked `public` appears on all three. An entry marked `admin`
appears only on the admin surface. There is no way to mark something
"tenant but not admin" — the provider supports tenants and needs to see
what they see.

> **Default to `tenant` when unsure.** Promoting an entry to public later
> is a decision anyone can make. Discovering that something private was
> published is not reversible — it has been indexed.

## 2. What goes where

| Content | Public | Tenant | Admin |
|---|---|---|---|
| Product concepts and terminology | ✅ | ✅ | ✅ |
| How to use each screen | ✅ | ✅ | ✅ |
| Field tooltips | ⬜ | ✅ | ✅ |
| Empty-state messages | ⬜ | ✅ | ✅ |
| User-facing error text | ✅ | ✅ | ✅ |
| Internal error names and status codes | ❌ | ❌ | ✅ |
| Product tour | ⬜ | ✅ | ✅ |
| FAQ and troubleshooting | ✅ | ✅ | ✅ |
| What does not exist yet | ✅ | ✅ | ✅ |
| Provider screens (`be.platform.*`) | ❌ | ❌ | ✅ |
| Operational runbooks, backups, alerting | ❌ | ❌ | ✅ |
| Pricing internals, ledger, collections | ❌ | ❌ | ✅ |
| Anything about a specific customer | ❌ | ❌ | ❌ |

✅ published · ⬜ not useful there · ❌ **must not appear**

### The three hard exclusions

**1. Provider content never reaches a tenant.** Every `be.platform.*` id
is `admin`. A tenant administrator is not a platform administrator, and
help that describes screens for managing *other companies* is both
confusing and a disclosure.

**2. Internal names never reach the public.** The error catalogue is
organised by the platform's own error types — `AuthorizationError`,
`PricingConcurrentEditError`. Those are headings for engineers. The
public and tenant surfaces publish **only the user-facing message**; the
internal name and status code stay on the admin surface.

**3. No customer data on any surface.** Help is written content. It never
contains a real company name, a real conversation, or a real invoice —
including in screenshots.

### On publishing what does not exist

The Help Center is candid that six things people look for are not built:
no Knowledge screen, no Workflows screen, no API keys, no version
history, no conversation tags, no mobile app.

**Publish all of it.** A prospect who finds out after buying is a refund
and a bad reference; one who finds out beforehand is either fine with it
or was never going to be a good fit. The commercial instinct to hide gaps
costs more than it saves, and support answers these questions anyway.

## 3. Public surface

**Purpose:** answer a question without logging in — for a prospect
evaluating the product, a customer on their phone, or a support agent
sending a link.

**Address:** `help.blinkengage.com`, or `/help` on the marketing site.

### What is different about it

| Constraint | Consequence |
|---|---|
| **No permissions to filter by** | Cannot hide what a reader lacks. Say "if your plan includes X" instead of hiding |
| **No workspace context** | Cannot say "your business hours are not set". Speak generally |
| **Indexed by search engines** | Titles must read as questions people search for |
| **Linkable** | Every entry needs a stable URL |

### URL scheme

```
https://help.blinkengage.com/<area>/<topic>
```

Derived from the `help_id` with `be.` dropped and dots turned into
slashes:

| help_id | Public URL |
|---|---|
| `be.inbox.conversation` | `/inbox/conversation` |
| `be.feature.business_hours` | `/feature/business-hours` |
| `be.knowledge.articles` | `/knowledge/articles` |

**URLs follow help ids, and help ids never change** — so a link shared in
an email in 2026 still resolves in 2030. When a screen is renamed, the
title changes and the URL does not.

### Structure

```
  Getting started        what it is, first login, core concepts
  Using the Inbox        conversations, replies, notes, transfers
  Channels               connecting each channel type
  Routing and SLA        queues, rules, response targets
  AI assistant           what it does, autopilot, limitations
  Customers              records, tags, history
  Reports                what each report answers
  Administration         settings, roles, business hours
  Troubleshooting        by symptom
  FAQ                    135 questions
  What's not built yet   the six, stated plainly
```

Mirrors the user guide, because that is the source of truth.

### Not published

Tooltips (meaningless without the field beside them), empty states
(meaningless without the screen), the product tour, internal error names,
and everything provider-only.

## 4. Tenant surface

**Purpose:** answer a question without leaving the screen you are on.

**Where:** the help panel, field tooltips, empty states, error messages
and the first-run tour.

### Filtering

This is the surface that knows who is asking, and the only one that can
filter. Two filters, applied in this order:

```
   entry
     │
     ├── requires a permission the user lacks?     → hide
     ├── requires a feature the company lacks?     → show, explain the plan
     └── otherwise                                 → show
```

The asymmetry is deliberate:

- **Permission missing → hide.** Explaining a screen somebody will never
  reach is noise.
- **Feature missing → show, with an explanation.** "AI is not part of
  your plan" is useful; silence looks like a missing feature.

> This mirrors the product itself, where a 403 has two causes and the
> message says which. Help behaves the same way, so the two never
> disagree.

### Deep links to public

Every **Learn more** in a tooltip opens the public page for that
`help_id`. One article, two entry points — the panel gives the short
answer in context, the public page gives the whole thing and can be
shared with a colleague who is not signed in.

### Provider users inside a tenant workspace

A provider supporting a customer sees the **tenant** surface while in
that workspace, plus a marker that they are viewing as provider. They
must see what the customer sees, or they will explain a screen the
customer does not have.

## 5. Admin surface

**Purpose:** running the platform, not using it.

**Where:** the provider's own administration area, plus its own public-
facing entry at `/help/admin` behind the provider role.

### What it adds

Everything the tenant surface has, plus:

| Content | Where it comes from |
|---|---|
| Provider screen help | [context-help-admin.md](./context-help-admin.md) |
| Internal error names and status codes | [error-messages.md](./error-messages.md) |
| Operations | [runbooks.md](../deployment/runbooks.md) |
| Recovery | [disaster-recovery.md](../deployment/disaster-recovery.md) |
| Deployment | [production-deployment-guide.md](../deployment/production-deployment-guide.md) |
| What is known to be wrong | [technical-debt.md](../releases/v1.0-technical-debt.md) · [known-limitations.md](../releases/v1.0-known-limitations.md) |

### Why the debt register belongs here

A provider answering "why is Intelligence empty?" or "why did
`PAYPAL_ENVIRONMENT` not work?" needs the honest answer, not the customer
one. The customer-facing text says what to do; the admin surface says
what is actually happening and whether it is known.

> **This is the surface where candour is cheapest and most valuable.**
> The provider is the one who can act on it.

## 6. Search per surface

| Surface | Searches | Zero results shows |
|---|---|---|
| Public | Public entries only | Nearest matches, then "contact us" |
| Tenant | Public + tenant, filtered by permission | Nearest matches, then "ask your administrator" |
| Admin | Everything, including operations | Nearest matches, then the runbook index |

The [search index](./search-index.md) is shared. Aliases and symptom
searches work identically on all three — somebody typing "sla numbers
wrong" gets the business-hours answer whether or not they are signed in.

## 7. Language

Both the interface and the tenant help surface support English and
Arabic, including right-to-left layout.

**Public help is English only today** — matching the state of product
documentation. When Arabic public help is added, the URL scheme gains a
language prefix (`/ar/inbox/conversation`) rather than a separate site,
so the two cannot drift apart.

## 8. Publishing

```
   Help Center documents  (this directory, reviewed in pull requests)
             │
             ▼
      surface field per entry
             │
      ┌──────┼──────┐
      ▼      ▼      ▼
   public  tenant  admin
```

| Rule | Reason |
|---|---|
| Content changes go through review, like code | Help is part of the product |
| An entry's surface is set when it is written | Deciding later means somebody guesses |
| Publishing is automatic from the source | A manual copy step is a drift step |
| A retired entry keeps its URL | Explain that the screen is gone; do not 404 a shared link |

### Before publishing anything publicly

- [ ] No customer names, data or screenshots
- [ ] No internal error names, table names or endpoint paths
- [ ] No provider-only screens or procedures
- [ ] Reads correctly to somebody who has never signed in
- [ ] Says "if your plan includes…" rather than assuming
- [ ] Verified against the running product, not against another document

> The last one is not routine. Two sections of the user guide described
> screens that do not exist, and it went unnoticed until somebody checked
> the interface rather than the documentation.

## 9. Coverage by surface

| | Public | Tenant | Admin |
|---|---|---|---|
| Screen help entries | 22 | 22 | 33 |
| Tooltips | — | 88 | 88 |
| Empty states | — | 30 | 30 |
| Error messages | 47 (text only) | 47 (text only) | 47 (with internals) |
| Tour steps | — | 13 | 13 |
| FAQ | 135 | 135 | 135 |
| Operational documents | — | — | 12 |

---

## See also

- [Help Center index](./README.md)
- [Help IDs](./help-ids.md)
- [Admin context help](./context-help-admin.md)
- [User Guide](../guides/blink-engage-user-guide.md)
