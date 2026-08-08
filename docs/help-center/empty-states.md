# Empty-State Messages

**What every screen says when it has nothing to show.**

An empty screen is the moment a new user decides whether the product is
working. "No data" tells them nothing. A good empty state explains why it
is empty, and offers the one action that fills it.

- **Source of truth:** [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **IDs:** [help-ids.md](./help-ids.md)

---

## Writing rules

| Rule | Reason |
|---|---|
| **Say why it is empty** | "No conversations" and "No conversations *yet, because no channel is connected*" lead to different actions |
| **Never blame the user** | "You have not created any queues" reads as an accusation. "You do not have any queues yet" does not |
| **One primary action** | Two equally weighted buttons is a decision the user cannot make yet |
| **Secondary action is an escape** | Learn more, clear filters, or go somewhere useful |
| **Distinguish empty from filtered** | These are completely different problems and need different messages |

> **The most important distinction in this document:** *nothing exists
> yet* versus *your filter matched nothing*. Showing the first message
> when the second is true sends a user off to create something they
> already have.

---

## Inbox

### `be.inbox.list` — no conversations at all

> **No conversations yet**
>
> When a customer messages you, their conversation appears here.
> Conversations arrive from every channel you have connected.
>
> **[Connect a channel]** · [How the Inbox works]

**When shown:** no conversations exist in the workspace.

> **Note for whoever builds this** — if no channel is connected, this is
> the most important empty state in the product. It is the moment a new
> workspace discovers it cannot receive anything.

### `be.inbox.list` — channel connected, no messages yet

> **Nothing has arrived yet**
>
> Your channels are connected and working. As soon as a customer
> messages you, the conversation appears here.
>
> **[Send yourself a test message]** · [Check channel status]

**When shown:** at least one healthy channel, no conversations.

### `be.inbox.list` — filter matched nothing

> **No conversations match these filters**
>
> Try widening them — or clear them to see everything.
>
> **[Clear filters]** · [Show all conversations]

**When shown:** conversations exist, the current filter excludes them
all.

### `be.inbox.list` — nothing assigned to you

> **Nothing assigned to you**
>
> Conversations waiting for someone are in the unassigned view. Pick one
> up to start working on it.
>
> **[Show unassigned]** · [Show everything]

### `be.inbox.conversation` — no messages

> **No messages in this conversation**
>
> This is unusual — a conversation normally starts with a customer
> message. If it stays empty, tell your administrator.
>
> **[Back to Inbox]** · [Get help]

---

## Customers

### `be.customers.list` — no customers

> **No customers yet**
>
> A customer record is created automatically the first time somebody
> contacts you. Connect a channel and they will appear here.
>
> **[Connect a channel]** · [How customers work]

### `be.customers.list` — search found nothing

> **No customers match "{query}"**
>
> Try a phone number or email address — those match most reliably.
>
> **[Clear search]** · [Show all customers]

### `be.customers.detail` — no conversation history

> **No conversations with this customer yet**
>
> Their conversations will appear here as they contact you.
>
> **[Back to Customers]**

---

## Workspace

### `be.workspace.agents` — only the owner

> **You are the only person here**
>
> Invite your team so conversations can be shared. A one-person
> workspace works perfectly well too — invite people when you need them.
>
> **[Invite someone]** · [About roles]

### `be.workspace.departments` — none

> **No departments yet**
>
> Departments group people — Support, Sales, Billing — and conversations
> can be routed to them. They are optional; create one when you can name
> the work it owns.
>
> **[New department]** · [Do I need departments?]

### `be.workspace.roles` — only defaults

> **Using the default roles**
>
> Owner, administrator, supervisor and agent cover most teams. Create a
> custom role when somebody needs a different set of permissions.
>
> **[New role]** · [About permissions]

---

## Channels

### `be.channels.list` — none connected

> **No channels connected**
>
> A channel is how customers reach you — WhatsApp, email, web chat and
> others. **Until you connect one, nobody can contact you.**
>
> **[Add a channel]** · [Which channel should I start with?]

**When shown:** no channels configured. This is the highest-priority
empty state in the product.

> **Tip in the panel:** Telegram is usually the quickest to connect if
> you want to try the platform today.

### `be.channels.status` — none to check

> **Nothing to monitor yet**
>
> Once you connect a channel, its health appears here and is checked
> every five minutes.
>
> **[Add a channel]**

---

## Routing

### `be.routing.queues` — only the default

> **You have one queue: General**
>
> Everything arrives here, which is fine for most teams. Add another
> queue when a distinct group of people handles a distinct kind of work.
>
> **[New queue]** · [How routing works]

### `be.routing.rules` — only the catch-all

> **One routing rule: the catch-all**
>
> This rule sends everything to your General queue, so nothing is ever
> lost. Add rules above it to send particular conversations elsewhere.
>
> **[New rule]** · [How rules are evaluated]

> **Warning shown alongside:** Do not delete the catch-all rule.
> Without it, a conversation matching no rule reaches no queue at all.

### `be.routing.rules` — catch-all missing

> **⚠ There is no catch-all rule**
>
> Conversations that match none of your rules will reach no queue, and
> nobody will see them. Add a rule with no conditions at the lowest
> priority.
>
> **[Create a catch-all rule]** · [Why this matters]

**When shown:** no rule exists with empty conditions. This is a warning
state, not a neutral one.

### `be.routing.services` — only the default

> **You have one service: General**
>
> Services carry your response targets and AI settings. Add another when
> a different kind of work needs a different policy.
>
> **[New service]** · [What is a service?]

### `be.routing.sla` — no policy

> **No response targets set**
>
> Without a policy, conversations are not measured against any promise.
> Set targets so you can see whether you are meeting them.
>
> **[Create an SLA policy]** · [About the four clocks]

> **Tip in the panel:** Set business hours first. Without them, evening
> and weekend hours count against your targets.

---

## Reports and Intelligence

### `be.insights.reports` — no data in range

> **No data for this period**
>
> There were no conversations between {from} and {to}. Try a wider date
> range.
>
> **[Last 30 days]** · [Clear filters]

### `be.insights.reports` — no data at all

> **No reporting data yet**
>
> Reports fill up as conversations happen. Once your team has been
> working for a few days, there will be something to see.
>
> **[Go to Inbox]** · [About reports]

### `be.insights.intelligence` — nothing observed

> **Nothing noticed yet**
>
> Intelligence looks for patterns across finished conversations. It needs
> a good number of them before patterns appear — and several weeks before
> trends mean anything.
>
> This screen filling up is a sign of a busy workspace, not a setting you
> need to change.
>
> **[About Intelligence]** · [Go to Reports]

**When shown:** fewer observations than the minimum. **Do not show a
generic "no data" here** — a new workspace will assume something is
broken.

### `be.insights.intelligence` — clusters but no trends

> **No trends yet**
>
> Trends compare several weeks of history against each other. Your
> clusters are forming; trends will follow once there is enough history
> to compare.
>
> **[View clusters]**

---

## Billing

### `be.billing.overview` — no invoices

> **No invoices yet**
>
> Usage is recorded as your team works, and your first invoice appears
> at the end of the billing period.
>
> **[View current usage]** · [How billing works]

---

## Search

### `be.search.global` — nothing found

> **Nothing found for "{query}"**
>
> Try fewer words, or a phone number or email address.
>
> **[Clear search]**

> **Note** — search only ever returns your own workspace's data.

### `be.search.global` — knowledge result found

> Knowledge results appear here but cannot be opened in this release —
> there is no knowledge screen yet.

**When shown:** the result set contains knowledge articles or categories.
This prevents the user clicking a result that goes nowhere.

---

## Notifications

### `be.account.notifications` — none

> **No notifications**
>
> You are told when a conversation is assigned to you, transferred to
> you, or misses its response target.
>
> **[Notification settings]**

---

## No-UI features

Shown when a user reaches one of these through search or a link.

### `be.knowledge.articles`

> **Knowledge is not editable here yet**
>
> Your knowledge base is real and working — it is what the AI answers
> from, and it appears in search results. There is just no editor in the
> interface in this release.
>
> To add or change an article or FAQ, ask your provider or IT team.
>
> **[How knowledge works]** · [Contact support]

### `be.automation.workflows`

> **Workflows are set up by your provider**
>
> The workflow engine exists, but there is no builder in the interface in
> this release. Describe what you want in the form *when… if… then…* and
> your provider can configure it.
>
> **[How workflows work]** · [Contact support]

### `be.settings.api_keys`

> **API keys are not available here**
>
> There is no API key screen in this release. If you need another system
> connected to Blink Engage, speak to your provider.
>
> **[Contact support]**

---

## Onboarding

### `be.onboarding.wizard` — nothing configured

> **Let's get you set up**
>
> A few steps and your workspace is ready. The important one is
> connecting a channel — without it, customers have no way to reach you.
>
> **[Start setup]** · [Skip for now]

---

## Coverage

| Screen group | Empty states |
|---|---|
| Inbox | 5 |
| Customers | 3 |
| Workspace | 3 |
| Channels | 2 |
| Routing | 5 |
| Reports and Intelligence | 4 |
| Billing | 1 |
| Search | 2 |
| Notifications | 1 |
| No-UI features | 3 |
| Onboarding | 1 |
| **Total** | **30** |

## The three that matter most

1. **`be.channels.list` — no channels.** The moment a workspace discovers
   it cannot receive anything.
2. **`be.routing.rules` — catch-all missing.** A warning, not an empty
   state. Conversations are being lost right now.
3. **`be.insights.intelligence` — nothing observed.** Without an
   explanation, every new customer reports this as a bug.

---

## See also

- [Context help](./context-help.md)
- [Error messages](./error-messages.md)
- [Product tour](./product-tour.md)
