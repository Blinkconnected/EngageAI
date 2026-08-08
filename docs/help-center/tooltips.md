# Tooltip Library

**Short help for individual fields and controls.**

A tooltip answers one question — *what is this?* — in one line. Anything
that needs a paragraph belongs in context help; anything that needs a
page belongs in the user guide, reached through **Learn more**.

- **Source of truth:** [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **IDs:** [help-ids.md](./help-ids.md)

---

## Writing rules

| Rule | Reason |
|---|---|
| **One line.** Under 120 characters | A tooltip that wraps three times is a paragraph in a small box |
| **Say what it does, not what it is called** | "Pauses the clock outside working hours" beats "Business hours setting" |
| **No jargon** | The reader is stuck; this is the wrong moment for vocabulary |
| **Add "Learn more" only when there is more** | A link that repeats the tooltip trains people to stop clicking |
| **Warn where the field is dangerous** | Better here than in a support ticket |

**Title** is the field's visible label. Keep it identical to the
interface, or the tooltip looks like it belongs to something else.

---

## Conversation

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.inbox.conversation.pick` | Pick | Takes this conversation and tells everyone else you are handling it. | §4.3 Assigning |
| `be.inbox.conversation.reply` | Reply | Goes to the customer, on the channel they used. | — |
| `be.inbox.conversation.note` | Internal note | Only your team sees this. The customer never does. | §4.4 Notes |
| `be.inbox.conversation.attach` | Attach file | Adds a file. Size and type limits apply, and each channel has its own. | §4.8 Attachments |
| `be.inbox.conversation.quick_reply` | Quick reply | Inserts saved text you can edit before sending. | — |
| `be.inbox.conversation.transfer` | Transfer | Moves this to another agent, queue or department. | §4.3 Assigning |
| `be.inbox.conversation.transfer_reason` | Reason | Why you are handing it over. The next person inherits the conversation, not your reasoning. | — |
| `be.inbox.conversation.resolve` | Resolve | Marks it dealt with. May trigger a satisfaction survey. | — |
| `be.inbox.conversation.close` | Close | Ends the conversation. Prefer Resolve, which can ask for feedback. | — |
| `be.inbox.conversation.priority` | Priority | How urgent this is. If everything is urgent, nothing is. | — |
| `be.inbox.conversation.autopilot` | Autopilot | Whether the AI may reply to this conversation without you. | §5.2 Autopilot |
| `be.inbox.conversation.status` | Status | Where this conversation has got to. | §4.2 Conversations |
| `be.inbox.conversation.queue` | Queue | Which waiting line this conversation belongs to. | — |

## Inbox list and filters

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.inbox.list.filter_assignment` | Assignment | Show everything, only yours, or only conversations nobody has taken. | — |
| `be.inbox.list.filter_status` | Status | Narrow to conversations at a particular stage. | — |
| `be.inbox.list.filter_queue` | Queue | Show only one waiting line. | — |
| `be.inbox.list.filter_channel` | Channel | Show only WhatsApp, only email, and so on. | — |
| `be.inbox.list.filter_sla` | SLA health | Find conversations close to missing their target. | §8.2 SLA |
| `be.inbox.list.badge_unassigned` | Unassigned | Nobody has taken this one yet. | — |
| `be.inbox.list.badge_at_risk` | At risk | Close to missing its response target. | §8.2 SLA |
| `be.inbox.list.badge_breached` | Breached | The target was missed. Answer immediately. | §8.2 SLA |
| `be.inbox.list.badge_handoff` | Handoff needed | The AI stopped because it was unsure. A person is needed. | §5.2 Autopilot |
| `be.inbox.list.badge_unrouted` | Unrouted | This reached no queue, so nobody is watching it. Tell an administrator. | §8.1 Routing |

## Customer

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.customers.detail.tags` | Tags | Labels for grouping and filtering customers. Customers never see them. | §4.5 Tags |
| `be.customers.detail.custom_fields` | Custom fields | Extra information your company tracks, such as an account number. | §9.3 Attributes |
| `be.customers.detail.rating` | Internal rating | Your team's private assessment. Never shown to the customer. | §9.4 Notes and ratings |
| `be.customers.detail.notes` | Customer notes | Things true across every conversation, such as "prefers phone calls". | §9.4 Notes and ratings |
| `be.customers.detail.timeline` | Timeline | Every conversation with this person, on every channel. | §9.2 Timeline |

## Agents and roles

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.workspace.agents.invite` | Invite | Sends an email so they can set their own password. You never set it for them. | §3.2 Users |
| `be.workspace.agents.role` | Role | What this person is allowed to do. | §3.4 Roles |
| `be.workspace.agents.department` | Department | Which organisational group they belong to. | — |
| `be.workspace.agents.availability` | Availability | Whether new conversations are assigned to them automatically. | §2.4 Profile |
| `be.workspace.agents.deactivate` | Deactivate | Stops them signing in but keeps their history. Use this instead of deleting. | §3.2 Users |
| `be.workspace.roles.permission` | Permission | One action a role allows. Checked on the server every time. | §3.5 Permissions |

## Channels

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.channels.connect.type` | Channel type | Which service this connects to — WhatsApp, email, Telegram and so on. | §11.3 Integrations |
| `be.channels.connect.credentials` | Credentials | Provided by the channel's own service, not by Blink Engage. | §11.3 Integrations |
| `be.channels.connect.test` | Test connection | Proves the credentials actually work. **Always do this before saving.** | §4.1 Channels |
| `be.channels.status.health` | Health | Whether this channel is reachable right now. Checked every five minutes. | §4.1 Channels |

## Queues and routing

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.routing.queues.name` | Queue name | Name it after the work, not the team — teams change more often. | §8.1 Routing |
| `be.routing.rules.priority` | Priority | Higher numbers are checked first, and the first match wins. | §8.1 Routing |
| `be.routing.rules.conditions` | Conditions | What must be true for this rule to apply. Leave empty to match everything. | §8.1 Routing |
| `be.routing.rules.target` | Target queue | Where matching conversations are sent. | — |
| `be.routing.rules.catch_all` | Catch-all rule | The safety net that catches anything no other rule claimed. **Do not delete it.** | §8.1 Routing |
| `be.routing.services.name` | Service | Something your company offers. Response targets and AI settings attach to it. | §1.2 Core concepts |

## SLA

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.routing.sla.first_response` | First response target | How long a customer may wait for your first reply. | §8.2 SLA |
| `be.routing.sla.next_response` | Next response target | How long they may wait for each later reply. | §8.2 SLA |
| `be.routing.sla.resolution` | Resolution target | How long until the whole thing is sorted out. | §8.2 SLA |
| `be.routing.sla.idle` | Idle target | How long a conversation may sit with nobody saying anything. | §8.2 SLA |
| `be.routing.sla.warning` | Warning threshold | How early to warn you. Late enough and the warning arrives too late to act on. | §8.2 SLA |
| `be.routing.sla.business_hours` | Use business hours | Pauses the clock outside working hours. Leave this on unless you run 24/7. | §8.2 SLA |
| `be.routing.sla.scope` | Applies to | Which service or queue these targets cover. | — |

## Settings

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.settings.company.name` | Company name | Shown to customers in surveys and emails. | §3.1 Companies |
| `be.settings.company.timezone` | Timezone | The basis for every time in the product. Set it before anything else. | §3.1 Companies |
| `be.settings.company.logo` | Logo | Appears on surveys and emails sent to customers. | — |
| `be.settings.company.language` | Default language | Used when a customer's own language cannot be detected. | — |
| `be.settings.business_hours.days` | Working days | The days your team works. SLA clocks pause on the others. | §8.4 Scheduling |
| `be.settings.business_hours.times` | Opening hours | Start and end of your working day. | §8.4 Scheduling |
| `be.settings.business_hours.holidays` | Holidays | Dates your team does not work, on top of the weekly pattern. | §8.4 Scheduling |

## AI

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.settings.ai.enabled` | AI enabled | The master switch for every AI feature in your workspace. | §5 AI Assistant |
| `be.settings.ai.provider` | AI provider | Which service generates the answers. Ollama runs locally, so nothing leaves your systems. | §11.3 Integrations |
| `be.settings.ai.autopilot` | Autopilot | Lets the AI reply to customers without an agent. | §5.2 Autopilot |
| `be.settings.ai.confidence` | Confidence threshold | How sure the AI must be before it answers. Higher is more cautious. | §5.2 Autopilot |
| `be.settings.ai.pickup_delay` | Pickup delay | How long to wait for a human before the AI steps in. | §5.2 Autopilot |
| `be.settings.ai.resume_delay` | Resume delay | How long after an agent goes quiet before the AI resumes. | §5.2 Autopilot |
| `be.settings.ai.business_hours_only` | Business hours only | Restricts the AI to your working hours. | §5.2 Autopilot |

## AI actions in a conversation

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.feature.ai_suggestions.reply` | Suggest reply | Drafts an answer from this conversation and your knowledge base. You still send it. | §5.1 AI actions |
| `be.feature.ai_suggestions.summary` | Summarise | Condenses a long conversation into a few lines. | — |
| `be.feature.ai_suggestions.translate` | Translate | Translates a message between supported languages. | — |
| `be.feature.ai_suggestions.sentiment` | Sentiment | Judges whether the customer sounds happy or unhappy. | — |
| `be.feature.ai_suggestions.grammar` | Improve grammar | Fixes mistakes without changing what you meant. | — |
| `be.feature.ai_suggestions.rewrite` | Rewrite professionally | Adjusts the tone of what you wrote. | — |
| `be.feature.ai_suggestions.next_action` | Next best action | Suggests what to do next in this conversation. | — |
| `be.feature.ai_suggestions.tags` | Suggest tags | Proposes tags from the conversation, to apply to the customer. | §4.5 Tags |

## Reports

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.insights.reports.date_range` | Date range | The period this report covers. Compare like with like. | §10.3 Using a report |
| `be.insights.reports.export` | Export | Downloads the data. Needs the Report Export feature in your plan. | §10.4 Exports |
| `be.insights.reports.kpi_frt` | First response time | How long customers wait for a first reply. The number they notice most. | §10.2 Key numbers |
| `be.insights.reports.kpi_resolution` | Resolution time | From the conversation opening to being resolved. | §10.2 Key numbers |
| `be.insights.reports.kpi_sla` | SLA attainment | The share of conversations that met their target. | §10.2 Key numbers |
| `be.insights.reports.kpi_csat` | CSAT | Average satisfaction score. Watch the trend, not one bad week. | §10.2 Key numbers |
| `be.insights.reports.kpi_ai_handled` | AI handled | Answered without a human. Good only if satisfaction holds up. | §10.2 Key numbers |
| `be.insights.reports.kpi_handoff` | Handoff rate | How often the AI stopped and asked for help. | §5.2 Autopilot |

## Intelligence

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.insights.intelligence.cluster` | Cluster | A group of similar conversations — usually a question customers keep asking. | §12.2 Intelligence |
| `be.insights.intelligence.trend` | Trend | Something increasing or decreasing over time. Needs several weeks of data. | §12.2 Intelligence |
| `be.insights.intelligence.anomaly` | Anomaly | An unusual spike worth a look. | §12.2 Intelligence |

## Profile

| help_id | Title | Description | Learn more |
|---|---|---|---|
| `be.account.profile.language` | Language | English or Arabic. Arabic switches the whole layout right-to-left. | §2.4 Profile |
| `be.account.profile.theme` | Theme | Light or dark. | — |
| `be.account.profile.availability` | Availability | Away stops new conversations being assigned to you — but keeps the ones you already have. | §2.4 Profile |
| `be.account.profile.notifications` | Notification preferences | Which events tell you, and how. Turn on too many and you will mute them all. | §2.5 Notifications |

---

## Coverage

| Group | Tooltips |
|---|---|
| Conversation | 13 |
| Inbox list and filters | 10 |
| Customer | 5 |
| Agents and roles | 6 |
| Channels | 4 |
| Queues and routing | 6 |
| SLA | 7 |
| Settings | 7 |
| AI configuration | 7 |
| AI actions | 8 |
| Reports | 8 |
| Intelligence | 3 |
| Profile | 4 |
| **Total** | **88** |

## The five that prevent the most support tickets

If only a handful are implemented, these are the ones:

1. `be.channels.connect.test` — saved is not verified
2. `be.routing.sla.business_hours` — the SLA-looks-wrong cause
3. `be.inbox.conversation.note` — the note-sent-to-customer mistake
4. `be.routing.rules.catch_all` — deleting it strands conversations
5. `be.settings.company.timezone` — wrong once, wrong everywhere

---

## See also

- [Help IDs](./help-ids.md)
- [Context help](./context-help.md)
- [User Guide](../guides/blink-engage-user-guide.md)
