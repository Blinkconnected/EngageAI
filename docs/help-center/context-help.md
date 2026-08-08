# Context-Sensitive Help

**What the help panel shows on each screen.**

When a user selects the help button, the interface passes the screen's
`help_id` and the panel shows the matching entry below.

- **Source of truth:** [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **IDs:** [help-ids.md](./help-ids.md)

Every entry has the same five parts, in the same order, so users learn
the shape once:

1. **What is this page?** — one or two sentences
2. **What can I do here?** — the actions available
3. **Common tasks** — numbered, the things people actually do
4. **Tips** — including the mistake this screen invites
5. **Related pages** — where to go next

> **Writing rule:** keep it short enough to read standing up. Anything
> longer belongs in the user guide, linked at the end.

---

## `be.home.dashboard` — Dashboard

**What is this page?**
Your summary of what is happening right now: how many conversations are
open, which have nobody looking after them, and which are running out of
time.

**What can I do here?**
See the state of the operation, and jump straight to the conversations
that need attention. You do not answer customers here — that is the
Inbox.

**Common tasks**
1. Check **at risk** first — those are closest to missing a promise.
2. Check **unassigned** — nobody is responsible for those yet.
3. Open **My conversations** and work through them.

**Tips**
- Work in that order, not in arrival order. A new message that waits five
  minutes is fine; one about to breach is not.
- The Dashboard is a summary. Do not try to run your whole day from it.

**Related pages**
Inbox · Reports · Intelligence

---

## `be.inbox.list` — Inbox

**What is this page?**
Every conversation from every channel, in one list. This is where agents
spend the day.

**What can I do here?**
Filter conversations, open one to read and reply, pick one up, and see at
a glance which are unassigned, unread or running out of time.

**Common tasks**
1. Filter to **unassigned + at risk** — the work nobody owns that is
   running out of time.
2. Open a conversation and select **Pick** to take it.
3. Switch to **Mine** to see your own workload.

**Tips**
- If conversations seem to have vanished, a filter is almost certainly
  still applied from earlier. Clear filters.
- **Unrouted** is the one badge to escalate. It means the conversation
  reached no queue at all, so nobody is watching it.

**Related pages**
Conversation · Queues · Customers · Dashboard

---

## `be.inbox.conversation` — Conversation

**What is this page?**
One discussion with one customer: every message either side has sent,
plus internal notes your team added.

**What can I do here?**
Reply, add an internal note, attach a file, use the AI assistant, change
priority, transfer it to somebody else, and resolve it when you are done.

**Common tasks**
1. Select **Pick** to take responsibility for it.
2. Type your reply and select **Send**.
3. Select **Note** to leave a comment only your team sees.
4. Select **Transfer** to hand it over — and write why.
5. Select **Resolve** when the customer's problem is dealt with.

**Tips**
- **Check whether you are in Reply or Note mode before typing.** The two
  boxes look similar, and a note sent to a customer cannot be recalled.
- Pick before you reply, or two agents can answer the same person.
- Read the whole history on a reopened conversation. The customer
  remembers what they told you last month.

**Related pages**
Inbox · Customer profile · Knowledge

---

## `be.customers.list` — Customers

**What is this page?**
Everyone who has ever contacted you, across every channel.

**What can I do here?**
Search for a customer, filter by tag, and open a record to see their
history.

**Common tasks**
1. Search by name, email or phone number.
2. Open a record to read their conversation history.
3. Filter by tag to find a group, such as everyone tagged `vip`.

**Tips**
- Searching a phone number is the fastest way to find someone who has
  called rather than messaged.
- If one person appears twice, they contacted you with different details.
  Update the records so they match.

**Related pages**
Customer profile · Inbox

---

## `be.customers.detail` — Customer profile

**What is this page?**
Everything you know about one person: contact details, tags, custom
fields, internal notes and rating, and every conversation they have had
with you.

**What can I do here?**
Update their details, add tags and notes, and open any past conversation.

**Common tasks**
1. Read the timeline before replying to a complaint.
2. Add a tag such as `vip` or `wholesale`.
3. Add an internal note about how this customer prefers to be handled.

**Tips**
- Notes and ratings are internal, but permanent and auditable. Write them
  professionally.
- Put conversation-specific detail in the conversation, not here. This is
  for things true across every conversation.

**Related pages**
Customers · Conversation

---

## `be.workspace.agents` — Agents

**What is this page?**
The people in your workspace, their roles and their availability.

**What can I do here?**
Invite new people, change roles, and deactivate people who have left.

**Common tasks**
1. Select **Invite** and enter a name, email and role.
2. Open someone's record to change their role or department.
3. Select **Deactivate** when somebody leaves.

**Tips**
- **Deactivate, do not delete.** Deactivating keeps their conversation
  history and audit trail and stops them signing in.
- You cannot set somebody's password. You trigger a reset; they choose
  it.

**Related pages**
Roles · Departments

---

## `be.workspace.departments` — Departments

**What is this page?**
Organisational groups such as Support, Sales or Billing. Conversations
can be routed to them.

**What can I do here?**
Create departments and assign people to them.

**Common tasks**
1. Select **New department** and name it.
2. Assign agents from the Agents screen.

**Tips**
- Departments are optional. Create one when you can name the work it owns
  — an empty hierarchy is overhead somebody maintains forever.

**Related pages**
Agents · Queues

---

## `be.workspace.roles` — Roles and permissions

**What is this page?**
What each kind of user is allowed to do.

**What can I do here?**
Create roles, choose their permissions, and assign them to people.

**Common tasks**
1. Select **New role** and name it after a job — "Billing Agent", not
   "Level 2".
2. Tick only the permissions that job needs.
3. Assign it from the Agents screen.

**Tips**
- Grant the narrowest role that works. Widening later takes a minute;
  discovering somebody had delete rights for a year does not.
- Permissions are checked on the server for every action. Hiding a button
  protects nothing.

**Related pages**
Agents · Settings

---

## `be.channels.list` — Channels

**What is this page?**
How customers reach you: WhatsApp, Messenger, Instagram, Telegram, email,
SMS and web chat.

**What can I do here?**
Connect a new channel, update credentials, and remove a channel.

**Common tasks**
1. Select **Add channel** and choose the type.
2. Enter the credentials from the provider.
3. Select **Test connection** — then save.

**Tips**
- **Always test before saving.** Saved is not verified. One mistyped
  character in a token looks perfectly saved and silently receives
  nothing.
- A personal WhatsApp number cannot be connected. You need WhatsApp
  Business API access, and Meta approval is not instant.

**Related pages**
Channel status · Queues · Settings

---

## `be.channels.status` — Channel status

**What is this page?**
Whether each connected channel is working right now. Checked every five
minutes.

**What can I do here?**
See which channels are healthy and which need attention.

**Common tasks**
1. Scan for anything not showing healthy.
2. Open the channel and reconnect with fresh credentials.
3. Test the connection before saving.

**Tips**
- Check this on Monday mornings. Tokens expire quietly, usually over a
  weekend.
- If customers say messages are not arriving, look here first.

**Related pages**
Channels

---

## `be.routing.queues` — Queues

**What is this page?**
The waiting lines conversations sit in before an agent picks them up, and
the rules deciding which queue each conversation goes to.

**What can I do here?**
Create queues, and create and reorder routing rules.

**Common tasks**
1. Select **New queue** and name it after the work, not the team.
2. Open **Routing rules** and add a rule with a priority and conditions.
3. Check the catch-all rule is still there at the lowest priority.

**Tips**
- Rules are checked highest priority first, and **the first match wins**.
- **Never delete the catch-all rule.** Without it, a conversation
  matching nothing reaches no queue and waits where nobody is looking.
- Leave gaps between priorities — 100, 200, 300 — so you can insert one
  later without renumbering everything.

**Related pages**
Services · SLA · Channels

---

## `be.routing.services` — Services

**What is this page?**
What your company offers — "Technical Support", "Billing". Services carry
policy: response-time targets and AI settings attach to them.

**What can I do here?**
Create and edit services and the policy attached to each.

**Common tasks**
1. Review the **General** service your workspace started with.
2. Add a service when a distinct kind of work needs a distinct policy.

**Tips**
- Add services when policies differ, not to mirror your org chart.

**Related pages**
Queues · SLA

---

## `be.routing.sla` — SLA policies

**What is this page?**
Your promises about how quickly you respond and resolve, and how the
platform measures them.

**What can I do here?**
Create policies, set targets for the four clocks, and choose what they
apply to.

**Common tasks**
1. Select **New policy** and set a first-response target.
2. Set the warning threshold early enough to act on.
3. Confirm **business hours** is enabled.

**Tips**
- **If your SLA numbers look wrong, check business hours first.** With
  them unset, every hour counts as a working hour and an evening message
  breaches before anyone is back.
- Set targets you can actually meet. An SLA nobody achieves gets ignored,
  and then real breaches look normal.

**Related pages**
Business hours · Services · SLA report

---

## `be.insights.reports` — Reports

**What is this page?**
How the operation is performing: volume, speed, satisfaction and AI use.

**What can I do here?**
Choose a report, set a date range and filters, read the numbers, and
export them.

**Common tasks**
1. Choose a report tab.
2. Set the date range.
3. Filter by channel, queue or agent.
4. Select **Export** to download.

**Tips**
- Averages hide problems. An average of 20 minutes can contain ten
  six-hour waits. Look at the worst cases too.
- Compare like periods. A week with a public holiday tells you about the
  holiday.

**Related pages**
Dashboard · Intelligence · SLA

---

## `be.insights.intelligence` — Intelligence

**What is this page?**
Patterns the platform has noticed across your finished conversations:
groups of similar questions, trends over time, and unusual spikes.

**What can I do here?**
Read what has been noticed. **Intelligence only observes** — it does not
change how conversations are handled or what the AI says.

**Common tasks**
1. Look at the largest clusters — those are what customers ask most.
2. Ask whether each is covered by your knowledge base.
3. If not, get an article or FAQ written.

**Tips**
- An empty screen is expected on a new or quiet workspace. It needs many
  conversations before patterns appear, and several weeks before trends
  mean anything.
- This is the loop that makes the AI better: Intelligence shows you what
  customers keep asking, and somebody writes the answer down.

**Related pages**
Reports · Knowledge

---

## `be.billing.overview` — Billing

**What is this page?**
What your workspace has used and what it has been invoiced.

**What can I do here?**
Review usage, invoices, payments and credit notes.

**Common tasks**
1. Check current-period usage.
2. Open an invoice to see what it covers.

**Tips**
- Usage is metered as conversations and messages happen, so the current
  period moves during the month.

**Related pages**
Reports · Settings

---

## `be.settings.company` — Company settings

**What is this page?**
Workspace-wide configuration: your company details, business hours, AI
and integrations.

**What can I do here?**
Change your company name, timezone, logo, business hours, AI settings and
ERP connection.

**Common tasks**
1. Set the **timezone** — do this before anything else.
2. Set **business hours**.
3. Configure **AI**, if your plan includes it.

**Tips**
- The timezone is the basis for every time calculation in the product.
  Changing it later does not correct reports already produced.

**Related pages**
Business hours · AI settings · Channels · Roles

---

## `be.settings.company.business_hours` — Business hours

**What is this page?**
The days and times your team works, plus holidays.

**What can I do here?**
Set working days and hours, and add holidays.

**Common tasks**
1. Select your working days.
2. Set opening and closing times.
3. Add holidays separately.

**Tips**
- **This is the most consequential screen in Settings.** SLA clocks pause
  outside these hours, and AI availability can depend on them. Leaving it
  unset makes every hour count as a working hour, which is the single
  most common cause of "our SLA numbers look wrong".

**Related pages**
SLA · AI settings · Company settings

---

## `be.settings.company.ai` — AI settings

**What is this page?**
How the AI assistant behaves for your workspace.

**What can I do here?**
Choose a provider, turn autopilot on or off, and set the confidence
threshold and delays.

**Common tasks**
1. Choose a provider — OpenAI, Claude or Ollama.
2. Set the confidence threshold **high** to begin with.
3. Decide whether the AI may reply on its own.

**Tips**
- Start cautious and lower the threshold slowly while watching the AI
  report. It is easier to explain "the AI was careful" than "the AI told
  a customer something untrue".
- The AI answers from your knowledge base. If that is thin or out of
  date, autopilot will be confidently wrong.

**Related pages**
AI report · Knowledge · Business hours

---

## `be.account.profile` — Your profile

**What is this page?**
Your own account: password, language, theme, availability and
notifications.

**What can I do here?**
Change your password, switch between English and Arabic, choose light or
dark, and set yourself available or away.

**Common tasks**
1. Set your language — Arabic switches the whole layout right-to-left.
2. Set yourself **Away** when you stop working.
3. Choose which events notify you.

**Tips**
- Setting yourself Away does **not** hand over conversations you already
  have. Transfer them first.
- Notify on assignment, transfer and SLA breach. Turn the rest off, or
  you will mute all of it.

**Related pages**
Notifications · Dashboard

---

## `be.onboarding.wizard` — Setup wizard

**What is this page?**
A guided walk through the main setup steps for a new workspace.

**What can I do here?**
Set your company details, invite your team, connect a channel, and
connect ERP.

**Common tasks**
1. Confirm your company name and timezone.
2. Invite the people who will answer customers.
3. **Connect a channel and test it.**

**Tips**
- **Connecting a channel is the only genuinely blocking step.** Without
  one, no customer can reach you at all. The wizard does not currently
  stop you finishing without it, so check before you consider setup done.
- Your workspace already has a queue, a service and a catch-all routing
  rule. You do not need to build routing to start.

**Related pages**
Channels · Business hours · Agents

---

## `be.auth.login` — Sign in

**What is this page?**
Where you sign in to your company's workspace.

**What can I do here?**
Sign in, or start a password reset.

**Common tasks**
1. Enter your email and password.
2. Use **Forgot password?** if you cannot get in.

**Tips**
- **Do not use Register if your company already uses Blink Engage.** It
  creates a brand-new empty workspace, and you will not see your
  colleagues' conversations. Ask for an invitation instead.
- Check the web address first. Most "I cannot sign in" reports are the
  wrong address.

**Related pages**
Verify email · Profile

---

## `be.auth.forbidden` — No access

**What is this page?**
You tried to open something your account cannot reach.

**What can I do here?**
Go back, or ask an administrator for access.

**Common tasks**
1. Check whether a colleague can see the same screen.
2. If they can, ask an administrator about your role.
3. If nobody can, your plan does not include that feature.

**Tips**
- Two different things produce this screen: your **role** lacks a
  permission, or your **company's plan** lacks a feature. Only the second
  needs a plan change.

**Related pages**
Roles · Dashboard

---

## No-UI features

The help system should return these rather than a missing page.

### `be.knowledge.articles` · `be.knowledge.faqs` · `be.knowledge.quick_replies`

**What is this?**
Your knowledge base: the reference material the AI answers from, the FAQs
written to be shown to customers, and the saved replies agents reuse.

**What can I do here?**
**There is no Knowledge screen in this release.** Knowledge is real and
working — it powers the AI's answers and appears in global search results
— but there is no editor in the interface.

**Common tasks**
1. To add or change knowledge, ask your provider or IT team.
2. Give them the exact wording you want, especially for policies.
3. Tell them whether it should be an **article** (reference material the
   AI paraphrases) or an **FAQ** (a question and its exact answer, shown
   as written).

**Tips**
- Anything you have worded carefully should be an FAQ, not an article.
  Articles may be paraphrased; FAQs are quoted.
- There is no version history, so editing replaces content permanently.
  Keep significant rewrites in a document outside Blink Engage.

**Related pages**
Intelligence · AI settings

### `be.automation.workflows`

**What is this?**
Automatic actions: when something happens, if conditions are met, do
something — move a conversation, notify somebody, raise its priority.

**What can I do here?**
**There is no workflow builder in this release.** The engine exists and
is configured through the API by your provider.

**Common tasks**
1. Write down what you want in the form *when… if… then…*.
2. Send that to your provider.
3. Ask them to test both a case that should match and one that should
   not.

**Tips**
- Be specific about conditions. A workflow with a broad trigger and no
  conditions runs on everything.

**Related pages**
SLA · Queues

### `be.settings.api_keys`

**What is this?**
Credentials that let another system talk to Blink Engage.

**What can I do here?**
**Not available in this release.** There is no API key screen. If you
need another system connected, speak to your provider — a workflow can
also call an external system when something happens.

**Related pages**
Workflows · ERP

---

## Coverage

| Group | Entries |
|---|---|
| Working screens | 17 |
| Authentication | 2 |
| No-UI features | 3 |
| **Total** | **22** |

Screens not listed individually — report sub-tabs, dialogs, provider
administration — inherit their parent's entry.

---

## See also

- [Help IDs](./help-ids.md)
- [Tooltips](./tooltips.md)
- [Empty states](./empty-states.md)
- [User Guide](../guides/blink-engage-user-guide.md)
