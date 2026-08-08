# Help ID Registry

**Permanent identifiers for every screen and feature.**

A `help_id` is a stable string that never changes. The interface passes
one to the help system; the help system returns the right content. When
a screen is renamed, redesigned or moved to a different URL, the
`help_id` stays the same — which is the whole point.

- **Source of truth for content:** [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **This registry is the index** every other Help Center document keys
  off.

---

## 1. Naming rules

```
be.<area>.<screen>[.<element>]
```

| Rule | Reason |
|---|---|
| Lowercase, dot-separated, ASCII | Safe in URLs, attributes, filenames and analytics |
| `be.` prefix on everything | Distinguishes ours from any third-party help widget |
| **Never reused** | A retired id is retired forever, or old links resolve to the wrong page |
| **Never renamed** | The id is the contract. The title can change freely |
| Element ids extend their screen id | `be.inbox.conversation.transfer` is obviously part of `be.inbox.conversation` |

> **Renaming a screen does not change its help_id.** If "Agents" becomes
> "Team", the id stays `be.workspace.agents`. Only the displayed title
> changes.

### Retiring an id

Mark it `retired` in this table with the date and what replaced it. Do
not delete the row — a bookmarked help link should explain that the
screen is gone, not return nothing.

## 2. Areas

| Area | Covers |
|---|---|
| `auth` | Sign in, register, verification |
| `home` | Dashboard |
| `inbox` | Conversations |
| `customers` | Customer records |
| `workspace` | Agents, departments, roles |
| `channels` | Channel connections and health |
| `routing` | Services, queues, routing rules, SLA |
| `knowledge` | Articles, FAQs, quick replies |
| `automation` | Workflows |
| `insights` | Reports, Intelligence |
| `billing` | Usage and invoices |
| `integrations` | ERP and other systems |
| `settings` | Company configuration |
| `account` | Profile, notifications |
| `onboarding` | Setup wizard and tour |
| `platform` | Provider administration (not customer-facing) |

## 3. Screen registry

**Status** tells the help system what to expect:
`live` — the screen exists · `no-ui` — the capability exists but has no
screen · `provider` — visible only to the platform provider.

### Authentication

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.auth.login` | Sign in | `/login` | live |
| `be.auth.register` | Create a company | `/register` | live |
| `be.auth.verify_email` | Verify your email | `/verify-email` | live |
| `be.auth.forbidden` | No access (403) | `/403` | live |
| `be.auth.feedback` | Satisfaction survey | `/feedback/:id` | live |

### Working screens

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.home.dashboard` | Dashboard | `/` | live |
| `be.inbox.list` | Inbox | `/conversations` | live |
| `be.inbox.conversation` | Conversation | `/conversations/:id` | live |
| `be.inbox.inspector` | Conversation inspector | (panel) | live |
| `be.customers.list` | Customers | `/customers` | live |
| `be.customers.detail` | Customer profile | `/customers/:id` | live |
| `be.search.global` | Search | (dialog) | live |

### Workspace

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.workspace.agents` | Agents | `/agents` | live |
| `be.workspace.departments` | Departments | `/departments` | live |
| `be.workspace.roles` | Roles and permissions | `/roles` | live |

### Channels

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.channels.list` | Channels | `/channels` | live |
| `be.channels.status` | Channel status | `/status` | live |
| `be.channels.connect` | Connect a channel | (dialog) | live |

### Routing and service levels

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.routing.services` | Services | `/services` | live |
| `be.routing.queues` | Queues | `/queues` | live |
| `be.routing.rules` | Routing rules | (within Queues) | live |
| `be.routing.sla` | SLA policies | `/sla` | live |

### Insights

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.insights.reports` | Reports | `/reports/:tab` | live |
| `be.insights.reports.executive` | Executive dashboard | `/reports/executive` | live |
| `be.insights.reports.agent` | Agent dashboard | `/reports/agent` | live |
| `be.insights.reports.live` | Live dashboard | `/reports/live` | live |
| `be.insights.reports.conversations` | Conversation report | `/reports/conversations` | live |
| `be.insights.reports.performance` | Performance report | `/reports/performance` | live |
| `be.insights.reports.queues` | Queue report | `/reports/queues` | live |
| `be.insights.reports.sla` | SLA report | `/reports/sla` | live |
| `be.insights.reports.csat` | Satisfaction report | `/reports/csat` | live |
| `be.insights.reports.ai` | AI report | `/reports/ai` | live |
| `be.insights.intelligence` | Intelligence | `/intelligence` | live |

### Commercial and integrations

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.billing.overview` | Billing | `/billing` | live |
| `be.integrations.erp` | ERPNext | `/erp-configs` | live |

### Settings and account

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.settings.company` | Company settings | `/settings/company/:tab` | live |
| `be.settings.company.general` | General | `/settings/company/general` | live |
| `be.settings.company.branding` | Branding | `/settings/company/branding` | live |
| `be.settings.company.business_hours` | Business hours | `/settings/company/business-hours` | live |
| `be.settings.company.ai` | AI settings | `/settings/company/ai` | live |
| `be.settings.company.erp` | ERP settings | `/settings/company/erp` | live |
| `be.account.profile` | Your profile | `/profile` | live |
| `be.account.notifications` | Notifications | `/notifications` | live |
| `be.account.changelog` | What's new | `/changelog` | live |

### Onboarding

| help_id | Screen | Route | Status |
|---|---|---|---|
| `be.onboarding.wizard` | Setup wizard | `/onboarding` | live |
| `be.onboarding.tour` | First-run tour | (overlay) | live |

### No interface in this release

The capability exists in the platform. There is no screen. The help
system should return the explanation, not a "page not found".

| help_id | Feature | Status |
|---|---|---|
| `be.knowledge.articles` | Knowledge articles | **no-ui** |
| `be.knowledge.faqs` | FAQs | **no-ui** |
| `be.knowledge.quick_replies` | Quick replies | **no-ui** |
| `be.knowledge.categories` | Knowledge categories | **no-ui** |
| `be.automation.workflows` | Workflows | **no-ui** |
| `be.settings.api_keys` | API keys | **no-ui** |

> **Why these are registered at all.** They appear in search results, in
> documentation, and in conversations with support. An id that resolves
> to "this exists but has no screen yet, here is who to ask" is far more
> useful than a dead link.

### Provider administration

Visible only to the platform provider, not to customers.

| help_id | Screen | Route |
|---|---|---|
| `be.platform.overview` | Platform home | `/platform` |
| `be.platform.companies` | Companies | `/platform/companies/:id` |
| `be.platform.company_users` | Company users | `/platform/companies/:id/users` |
| `be.platform.billing` | Platform billing | `/platform/billing` |
| `be.platform.invoices` | Invoices | `/invoices` |
| `be.platform.ledger` | Ledger | `/ledger` |
| `be.platform.payments` | Payments | `/payments` |
| `be.platform.collections` | Collections | `/collections` |
| `be.platform.pricing` | Pricing | `/pricing` |
| `be.platform.mail` | Mail | `/mail` |
| `be.platform.health` | Platform health | `/health` |

## 4. Feature-level IDs

Used by tooltips and search when the subject is a concept rather than a
screen.

| help_id | Feature |
|---|---|
| `be.feature.conversation` | What a conversation is |
| `be.feature.pick` | Picking up a conversation |
| `be.feature.transfer` | Transferring |
| `be.feature.internal_note` | Internal notes |
| `be.feature.attachment` | Attachments |
| `be.feature.priority` | Priority |
| `be.feature.status` | Conversation statuses |
| `be.feature.ownership_expiry` | Why a conversation left "mine" |
| `be.feature.sla_clocks` | The four SLA clocks |
| `be.feature.business_hours` | Business hours |
| `be.feature.routing_rule` | Routing rules |
| `be.feature.catch_all` | The catch-all rule |
| `be.feature.queue` | Queues |
| `be.feature.service` | Services |
| `be.feature.ai_autopilot` | Autopilot |
| `be.feature.ai_confidence` | Confidence threshold |
| `be.feature.ai_handoff` | AI handoff |
| `be.feature.ai_suggestions` | AI suggestions |
| `be.feature.knowledge` | Knowledge |
| `be.feature.memory` | Memory |
| `be.feature.learning` | Learning |
| `be.feature.tags` | Customer tags |
| `be.feature.custom_fields` | Custom fields |
| `be.feature.role` | Roles |
| `be.feature.permission` | Permissions |
| `be.feature.feature_flag` | Plan features |
| `be.feature.audit_log` | Audit trail |
| `be.feature.csat` | Satisfaction surveys |

## 5. How the interface should use these

1. Every screen declares its `help_id`.
2. The help button sends that id to the help system.
3. The help system returns the context help entry
   ([context-help.md](./context-help.md)).
4. Field tooltips use element ids
   ([tooltips.md](./tooltips.md)).
5. Errors carry their own codes
   ([error-messages.md](./error-messages.md)).
6. Search maps keywords to ids
   ([search-index.md](./search-index.md)).

> **The rule that keeps this working:** an id is assigned once, in this
> file, before the screen ships. An id invented in the interface and
> never registered here is an id nothing can resolve.

## 6. Coverage

| Category | Count |
|---|---|
| Live screens | 44 |
| No-UI features | 6 |
| Provider screens | 11 |
| Feature concepts | 28 |
| **Total registered ids** | **89** |

---

## See also

- [Context-sensitive help](./context-help.md)
- [Tooltip library](./tooltips.md)
- [Empty states](./empty-states.md)
- [Error catalogue](./error-messages.md)
- [Product tour](./product-tour.md)
- [Search index](./search-index.md)
