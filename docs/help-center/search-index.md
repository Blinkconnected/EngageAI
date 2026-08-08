# Help Search Index

**Keywords and aliases for every feature, so help search finds things by
the words users actually type.**

- **Source of truth:** [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **IDs:** [help-ids.md](./help-ids.md)

---

## Why aliases matter

Users search with the word from their previous product, or from their
job, or from the mistake they are making. Somebody looking for the
knowledge base types "docs", "articles", "help", "FAQ" or "how do I add
an answer" — and one of those is the official name.

Each entry lists:

- **Primary** — the official name
- **Aliases** — other names for the same thing, including competitors'
  terms
- **Symptom searches** — what people type when something is wrong

> **Symptom searches are the most valuable column.** A user typing "SLA
> looks wrong" needs the business-hours article, which shares no words
> with their query. Getting these right prevents more support tickets
> than any other part of the Help Center.

---

## Inbox and conversations

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.inbox.list` | Inbox | conversations, messages, tickets, chats, queue, my work, cases, threads | where are my messages, cannot see conversations, empty inbox, conversations disappeared |
| `be.inbox.conversation` | Conversation | chat, thread, ticket, case, message history, dialogue | how do I reply, how to answer a customer |
| `be.feature.pick` | Pick | claim, take, assign to me, grab, accept | how do I take a conversation, two agents replied |
| `be.feature.transfer` | Transfer | reassign, hand over, escalate, move, forward, pass on | how do I give this to someone else, send to another team |
| `be.feature.internal_note` | Internal note | note, comment, private note, internal comment, memo | customer saw my note, how to write to my team only |
| `be.feature.attachment` | Attachment | file, upload, image, photo, document, pdf, media | cannot send file, file too big, attachment failed |
| `be.feature.priority` | Priority | urgency, importance, severity | how to mark urgent |
| `be.feature.status` | Status | state, stage, resolved, closed, open, pending | what does waiting on customer mean, difference between resolve and close |
| `be.feature.ownership_expiry` | Ownership expiry | unassigned automatically, released, timeout, returned to queue | conversation disappeared from mine, lost my conversation, why was it unassigned |
| `be.inbox.list.badge_unrouted` | Unrouted | no queue, lost, orphaned, nowhere | unrouted warning, conversation went nowhere, nobody sees it |

## Customers

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.customers.list` | Customers | contacts, people, clients, users, customer list, CRM, directory | find a customer, search by phone number |
| `be.customers.detail` | Customer profile | contact record, customer record, client details, profile | see customer history, past conversations |
| `be.feature.tags` | Tags | labels, categories, markers, groups, segments | how to tag, tag a conversation, group customers |
| `be.feature.custom_fields` | Custom fields | attributes, extra fields, properties, metadata, custom data | add account number, extra information |
| `be.customers.detail.timeline` | Timeline | history, past conversations, activity, previous contact | what did this customer say before |

## Channels

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.channels.list` | Channels | integrations, connections, sources, inboxes, messaging channels, platforms | connect whatsapp, add email, set up telegram |
| `be.channels.status` | Channel status | health, connection status, uptime, monitoring | channel not working, messages not arriving, whatsapp stopped |
| `be.channels.connect.test` | Test connection | verify, check credentials, validate, try connection | channel never received anything, saved but not working |
| — | WhatsApp | whatsapp business, wa, meta, waba | connect whatsapp, whatsapp not working, personal number |
| — | Email | mail, smtp, imap, inbox, email channel | receive email, email not arriving |
| — | Telegram | telegram bot, botfather | connect telegram, telegram token |
| — | Facebook Messenger | messenger, facebook, fb, meta, page messages | connect facebook page |
| — | Instagram | insta, ig, direct messages, dm | connect instagram |
| — | SMS | text message, texting, sms channel | send sms |
| — | Web Chat | chat widget, live chat, website chat, chatbox, embed | add chat to website, widget code |

## Routing, queues and SLA

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.routing.queues` | Queues | waiting lines, inboxes, buckets, groups, work queues, pools | create a queue, where do conversations wait |
| `be.routing.rules` | Routing rules | rules, distribution, triage, assignment rules, filters, conditions | send whatsapp to a team, route by keyword |
| `be.feature.catch_all` | Catch-all rule | default rule, fallback, safety net, last rule | conversations going nowhere, deleted the default rule, unrouted |
| `be.routing.services` | Services | offerings, service catalogue, products, lines of business | what is a service, service vs queue |
| `be.routing.sla` | SLA | service level, response time, targets, deadlines, promises, response goals | set response time, sla policy |
| `be.feature.sla_clocks` | SLA clocks | first response, resolution time, next response, idle, timers | what are the four clocks, how is response time measured |
| `be.feature.business_hours` | Business hours | working hours, opening hours, office hours, schedule, availability, holidays | **sla numbers wrong**, breaching overnight, weekend breaches, clock running at night |
| — | Escalation | escalate, raise, senior, supervisor, priority increase | how to escalate, escalation rules |

## AI

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.settings.company.ai` | AI settings | artificial intelligence, bot, assistant, automation, chatgpt, llm, copilot | set up ai, turn on ai, configure bot |
| `be.feature.ai_autopilot` | Autopilot | auto reply, automatic answers, bot replies, unattended, self-service | make ai answer customers, ai reply automatically |
| `be.feature.ai_confidence` | Confidence threshold | certainty, accuracy setting, sensitivity, threshold | ai answers too much, ai never answers, tune the ai |
| `be.feature.ai_handoff` | Handoff | escalate to human, transfer to agent, ai gave up, human takeover | ai stopped replying, handoff needed |
| `be.feature.ai_suggestions` | AI suggestions | drafts, recommendations, smart replies, suggested reply, autocomplete | ai help me write, draft a reply |
| — | Translation | translate, language, multilingual, arabic english | translate a message |
| — | Sentiment | mood, tone, emotion, happiness, customer feeling | is the customer angry |
| — | Summary | summarise, summarize, recap, tldr, condense | summarise this conversation |
| — | AI provider | openai, chatgpt, claude, anthropic, ollama, local ai, model | which ai does it use, run ai locally, keep data private |

## Knowledge

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.knowledge.articles` | Knowledge Base | knowledge, articles, docs, documentation, help centre, wiki, content, kb, guides | add an article, where do i write answers, **no knowledge menu** |
| `be.knowledge.faqs` | FAQs | frequently asked questions, questions and answers, q&a, common questions | add an faq, publish a question |
| `be.knowledge.quick_replies` | Quick replies | canned responses, saved replies, templates, macros, shortcuts, snippets | save a reply, reuse text |
| `be.knowledge.categories` | Categories | folders, sections, groups, topics, taxonomy | organise articles |
| — | Version history | versions, revisions, history, previous version, undo, restore | restore an article, what did this say before, **undo an edit** |

## Automation

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.automation.workflows` | Workflows | automation, rules, triggers, actions, if this then that, macros, bots, flows | automate something, when x happens do y, **no workflows menu** |
| — | Triggers | events, when, conditions, starts | what can start a workflow |
| — | Webhook | callback, http, external system, integration, api call | send data to another system |

## Workspace

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.workspace.agents` | Agents | users, team, staff, employees, members, people, operators, seats | add a user, invite someone, remove a user |
| `be.workspace.departments` | Departments | teams, groups, units, divisions, sections | organise the team |
| `be.workspace.roles` | Roles | permissions, access, security, privileges, groups, profiles | who can do what, restrict access |
| `be.feature.permission` | Permissions | access rights, privileges, capabilities, grants | **permission denied**, cannot access, access denied |
| `be.feature.feature_flag` | Plan features | subscription, plan, licence, entitlements, package, tier | feature not available, why is menu missing, not in your plan |
| — | Deactivate | disable, suspend, remove, offboard, leaver | someone left, stop access |

## Reports

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.insights.reports` | Reports | analytics, statistics, stats, metrics, dashboards, insights, kpi, bi | see performance, how are we doing |
| `be.insights.reports.executive` | Executive dashboard | overview, summary, management report, leadership | overall performance |
| `be.insights.reports.agent` | Agent dashboard | agent performance, individual stats, per-agent | how is each person doing |
| `be.insights.reports.live` | Live dashboard | real time, now, current, wallboard, monitor | what is happening now |
| `be.insights.reports.csat` | Satisfaction | csat, customer satisfaction, feedback, ratings, survey, nps | customer feedback, satisfaction score |
| `be.insights.reports.sla` | SLA report | service level report, target attainment, breaches | are we meeting targets, how many breaches |
| `be.insights.reports.export` | Export | download, excel, csv, pdf, extract, save report | download a report, export data, **no export button** |

## Intelligence

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.insights.intelligence` | Intelligence | learning, patterns, insights, discovery, trends, ai insights, analysis | what are customers asking, common questions |
| `be.feature.learning` | Learning | machine learning, ai learning, pattern detection, self-improvement | does the ai learn, will it improve by itself |
| `be.feature.memory` | Memory | customer memory, context, remembering, recall | does it remember customers |
| `be.insights.intelligence.cluster` | Cluster | group, theme, topic, pattern, similar conversations | what is a cluster |
| `be.insights.intelligence.trend` | Trend | pattern over time, increase, decrease, seasonality | **intelligence is empty**, no trends showing |

## Settings and account

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.settings.company` | Settings | configuration, preferences, options, admin, setup, company settings | where do i change settings |
| `be.settings.company.timezone` | Timezone | time zone, clock, utc, local time, region | **times are wrong**, hours off, wrong time in reports |
| `be.settings.company.branding` | Branding | logo, colours, appearance, white label, customisation | add our logo |
| `be.account.profile` | Profile | my account, preferences, personal settings, me | change my password, change language |
| `be.account.profile.availability` | Availability | status, online, away, presence, do not disturb | stop receiving conversations, going on holiday |
| `be.account.notifications` | Notifications | alerts, emails, push, reminders, messages | too many emails, not getting notified |
| `be.settings.api_keys` | API keys | api, token, integration key, credentials, developer access | **generate api key**, connect another system |

## Billing and integrations

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.billing.overview` | Billing | invoices, payments, subscription, charges, account, usage, costs | how much do we pay, see invoice |
| `be.integrations.erp` | ERPNext | erp, accounting, orders, invoicing system, back office | connect erp, sync customers |

## Sign in and access

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.auth.login` | Sign in | login, log in, sign on, access, authenticate | **cannot sign in**, forgot password, wrong password |
| `be.auth.register` | Create a company | register, sign up, new account, get started | create an account, start a workspace |
| `be.auth.verify_email` | Verify email | confirm email, activation, verification | did not get verification email |
| `be.auth.forbidden` | No access | 403, forbidden, denied, blocked, restricted | access denied, permission error |

## Mobile

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| — | Mobile | phone, app, ios, android, tablet, iphone, mobile app | **is there an app**, download the app, use on phone |

## Onboarding

| help_id | Primary | Aliases | Symptom searches |
|---|---|---|---|
| `be.onboarding.wizard` | Setup | onboarding, getting started, first steps, configuration, wizard | how do i start, what do i set up first |
| `be.onboarding.tour` | Product tour | tour, walkthrough, guide, introduction, demo | show me around, take the tour again |

---

## Searches that must return an answer

Highest-volume symptom searches, each mapped to the entry that actually
helps. If only these are tuned, most searches succeed.

| User types | Return |
|---|---|
| sla numbers wrong / breaching overnight | `be.feature.business_hours` |
| messages not arriving / channel stopped | `be.channels.status` |
| conversation disappeared | `be.feature.ownership_expiry` |
| customer saw my note | `be.feature.internal_note` |
| permission denied / access denied | `be.feature.permission` + `be.feature.feature_flag` |
| no knowledge menu / where do I add articles | `be.knowledge.articles` (no-UI explanation) |
| no workflows menu | `be.automation.workflows` (no-UI explanation) |
| generate api key | `be.settings.api_keys` (no-UI explanation) |
| is there a mobile app | Mobile (no app; responsive web) |
| intelligence is empty | `be.insights.intelligence` (needs volume) |
| undo an article edit | Version history (not available) |
| ai never answers | `be.feature.ai_confidence` |
| ai answers wrongly | `be.knowledge.articles` |
| conversations going nowhere / unrouted | `be.feature.catch_all` |
| times are wrong | `be.settings.company.timezone` |
| no export button | `be.insights.reports.export` (needs the feature) |

> **Six of these lead to "that does not exist yet".** Those are the
> searches most likely to end in a support ticket, and the ones where a
> clear answer saves the most time. Make sure they return the
> explanation, not zero results.

## Matching rules

| Rule | Reason |
|---|---|
| Match aliases as strongly as primary names | The alias is what the user knows |
| Ignore case, punctuation and plurals | "FAQs", "faq", "F.A.Q." are one thing |
| Match partial words | "notif" should find notifications |
| Support Arabic search terms | The interface is bilingual; help search should be too |
| Never return zero results in silence | Offer the closest matches and a way to contact support |

## Maintaining this

- Add a feature → add its row **in the same change**.
- Watch real searches that return nothing; each one is a missing alias.
- When a no-UI feature gains a screen, move its symptom searches from
  "does not exist" to the real page.

---

## See also

- [Help IDs](./help-ids.md)
- [Context help](./context-help.md)
- [User Guide](../guides/blink-engage-user-guide.md)
