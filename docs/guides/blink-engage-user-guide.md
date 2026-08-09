# Blink Engage — User Guide

**The official product manual.**

Version 1.0 · For Blink Engage `v1.2.0`

Everything in this guide describes the product as it exists today. Where
something does not exist yet, this guide says so plainly rather than
leaving you looking for a button that is not there.

---

## How to use this guide

| If you are… | Start at |
|---|---|
| An agent answering customers | [§4 Inbox](#4-inbox) |
| A supervisor watching a team | [§10 Reports](#10-reports) |
| An administrator setting up | [§2 Getting Started](#2-getting-started) then [§11 Administration](#11-administration) |
| Stuck right now | [§14 Troubleshooting](#14-troubleshooting) |
| Looking for a quick answer | [§15 FAQ](#15-faq) |

**Callouts used throughout:**

> **Tip** — a shortcut or a faster way.

> **Note** — something to be aware of.

> **Warning** — something that can cause a problem.

> **Best Practice** — what experienced teams do.

---

## Contents

1. [Introduction](#1-introduction)
2. [Getting Started](#2-getting-started)
3. [Workspace](#3-workspace)
4. [Inbox](#4-inbox)
5. [AI Assistant](#5-ai-assistant)
6. [Knowledge Base](#6-knowledge-base)
7. [Workflows](#7-workflows)
8. [Automation](#8-automation)
9. [Customers](#9-customers)
10. [Reports](#10-reports)
11. [Administration](#11-administration)
12. [AI & Learning](#12-ai--learning)
13. [Mobile](#13-mobile)
14. [Troubleshooting](#14-troubleshooting)
15. [FAQ](#15-faq)

---

# 1. Introduction

## 1.1 What is Blink Engage?

Blink Engage is a customer engagement platform. It brings every message
your customers send you — WhatsApp, Facebook Messenger, Instagram,
Telegram, email, SMS and web chat — into **one shared inbox**, so your
team answers from one place instead of seven.

Around that inbox it adds the things a real support operation needs:
routing so the right person gets the right conversation, response-time
targets so nothing is forgotten, an AI assistant that can draft or even
send replies, a knowledge base the AI answers from, and reporting so you
can see how the operation is doing.

### What problem it solves

Without a platform like this, a growing business ends up with a WhatsApp
account on somebody's phone, a shared email inbox nobody owns, and a
Facebook page checked twice a day. Messages get missed. Two people reply
to the same customer. Nobody knows how long customers wait.

Blink Engage replaces all of that with one screen, one queue, and one
record of what happened.

### Who it is for

Teams of 1 to 500 people who talk to customers. It is used by retailers,
service businesses, government departments, clinics and banks.

## 1.2 Core concepts

Nine ideas. Understand these and the rest of the product follows.

### Conversation

A **conversation** is one continuous discussion with one customer. It
contains every message either side has sent, plus internal notes your
team adds.

A conversation stays open until someone resolves it. If the customer
replies afterwards, it **reopens** — the discussion continues in the same
place rather than starting a new one.

> **Note** — A conversation belongs to one channel. If the same customer
> emails you *and* messages your WhatsApp, those are two conversations,
> but both are linked to the same customer record.

### Channel

A **channel** is a way customers reach you: your WhatsApp number, your
support email address, the chat widget on your website.

You connect a channel once. After that, messages arriving there
automatically become conversations.

### Queue

A **queue** is a waiting line for conversations. Conversations arrive in
a queue and wait for an agent to pick them up.

Most companies start with one queue and add more when different teams
handle different work — for example a *Sales* queue and a *Support*
queue.

### Routing rule

A **routing rule** decides which queue a conversation goes to. For
example: "if the message arrives on WhatsApp and mentions *invoice*, put
it in the Billing queue."

> **Note** — Your workspace is created with a **catch-all rule** already
> in place. Any conversation that matches no other rule lands in your
> General queue, so nothing is ever lost. Every rule you write later
> takes priority over it.

### Agent

An **agent** is a person who answers conversations. Agents have an
availability status and a workload.

### Service

A **service** is something your company offers — "Technical Support",
"Billing", "New Sales". Services carry policy: response-time targets and
AI settings attach to a service.

Your workspace starts with a **General** service.

### SLA

An **SLA** (Service Level Agreement) is a promise about speed. For
example, "we answer within one hour." Blink Engage measures four
different clocks against your targets and warns you before you miss one.

See [§8.2 SLA](#82-sla).

### Knowledge

Your **knowledge base** is the reference material the AI answers from,
plus FAQs written to be shown to customers.

### Customer

A **customer** is the person on the other end. Their record holds their
contact details and every conversation they have ever had with you,
across all channels.

## 1.3 Terminology

| Term | Plain meaning |
|---|---|
| **Agent** | A team member who answers customers |
| **Assign** | Give a conversation to a specific agent |
| **Attachment** | A file sent in a conversation |
| **Autopilot** | The AI replying to a customer without a human |
| **Breach** | A response-time target that was missed |
| **Business hours** | The days and times your team works |
| **Channel** | A way customers reach you |
| **Conversation** | One discussion with one customer |
| **CSAT** | Customer satisfaction — the score customers give you |
| **Department** | An organisational group, e.g. Support |
| **Handoff** | The AI stopping and asking for a human |
| **Internal note** | A comment only your team sees |
| **Pick** | Take a conversation for yourself |
| **Queue** | A waiting line for conversations |
| **Quick reply** | Saved text you send often |
| **Resolve** | Mark a conversation as dealt with |
| **Role** | A set of permissions given to a user |
| **Routing** | Deciding which queue a conversation goes to |
| **Service** | Something your company offers, carrying its own policy |
| **SLA** | A response-time promise |
| **Transfer** | Move a conversation to someone else |
| **Unassigned** | Nobody has taken this conversation yet |
| **Workspace** | Your company's private area in Blink Engage |

> **Note on "workspace" and "company"** — they mean the same thing. Your
> data is completely separate from every other company using Blink
> Engage. No one outside your workspace can see any of it.

---

# 2. Getting Started

## 2.1 First login

**Purpose:** get into your workspace for the first time.

**When to use it:** on day one, or whenever you are signed out.

**Permissions required:** none — but your account must be verified.

### Before you start

You need an invitation email. If you have not received one, ask your
administrator to invite you from the **Agents** screen. You cannot create
your own account inside somebody else's workspace.

### Step by step

1. **Open the verification email** and click the link inside. This proves
   the email address is yours.
2. **Set your password.** Choose something you do not use elsewhere.
3. **Go to your company's Blink Engage address.** It usually looks like
   `https://engage.yourcompany.com`. Your administrator will tell you.
   You land on the public site describing the product — select **Sign
   in** in the top right.
4. **Enter your email and password**, then select **Sign in**.
5. You land on the **Dashboard**.

`[Screenshot placeholder: Sign-in screen showing email field, password field, "Sign in" button, and "Forgot password?" link]`

### Screen explained — the sign-in page

| Element | What it does |
|---|---|
| **Email** field | The address your invitation was sent to |
| **Password** field | Your password. Select the eye icon to check what you typed |
| **Sign in** button | Signs you in |
| **Forgot password?** link | Sends a reset link to your email |
| **Register** link | Creates a **new company**, not a new user in an existing one |

> **Warning** — Do not use **Register** if your company already uses
> Blink Engage. It creates a brand-new, empty workspace, and you will
> not be able to see your colleagues' conversations. If you did this by
> mistake, ask your administrator to invite you properly and abandon the
> workspace you created.

### Example

Layla joins the support team at Amman Home Supplies. Her manager invites
her from the Agents screen. Layla receives an email titled "You have been
invited to Blink Engage", clicks the link, sets a password, signs in, and
sees the Dashboard with the company's conversations.

### Common mistakes

| Mistake | What happens | Fix |
|---|---|---|
| Using **Register** instead of the invitation | You get an empty workspace of your own | Ask for an invitation; abandon the new workspace |
| Not verifying the email | You can sign in but are restricted | Find the verification email, or ask for it to be resent |
| Signing in at the wrong address | "Invalid credentials" | Confirm the exact address with your administrator |

> **Tip** — Bookmark your company's Blink Engage address on the first
> day. Most "I cannot sign in" reports turn out to be the wrong address.

### Troubleshooting

- **"Invalid email or password"** — check the address you are signing in
  at first. Then use **Forgot password?**.
- **No verification email** — check your spam folder. Ask your
  administrator to resend it.
- **Reset email never arrives** — your company may not have email set up
  yet. Ask your administrator to reset your password directly.

## 2.2 Dashboard

**Purpose:** a summary of what is happening right now.

**When to use it:** first thing each morning, and whenever you want an
overview rather than a specific conversation.

**Permissions required:** any signed-in user. What you see depends on
your role.

### Screen explained

`[Screenshot placeholder: Dashboard with summary cards across the top and lists below]`

| Area | What it shows |
|---|---|
| **Summary cards** | Open conversations, unassigned conversations, conversations assigned to you, conversations at risk of missing their target |
| **My conversations** | The conversations currently assigned to you |
| **Needs attention** | Unassigned or at-risk conversations |
| **Activity** | Recent events in the workspace |

### Step by step — starting your day

1. Open the **Dashboard**.
2. Look at **at risk** first. Those are closest to missing a promise.
3. Then look at **unassigned**. Those have nobody working on them.
4. Then open **My conversations** and work through them.

> **Best Practice** — Deal with at-risk conversations before new ones. A
> new message that waits five minutes is fine; one about to breach its
> target is not.

### Common mistakes

- **Working only from the Dashboard.** It is a summary. The Inbox is
  where you actually work.
- **Ignoring "unassigned".** An unassigned conversation has nobody
  responsible for it. If everyone assumes somebody else will take it,
  nobody does.

## 2.3 Navigation

**Purpose:** move around the product.

**Permissions required:** each menu item appears only if your role allows
it *and* your company's plan includes it.

### Screen explained — the left menu

`[Screenshot placeholder: Left sidebar showing the full menu]`

| Menu item | What it is for | You need |
|---|---|---|
| **Dashboard** | Today at a glance | — |
| **Inbox** | Conversations — where agents work | `conversations.read` |
| **Customers** | People who have contacted you | `customers.read` |
| **Agents** | Your team members | `agents.read` |
| **Departments** | Organisational groups | `departments.read` |
| **Channels** | WhatsApp, email, chat and the rest | `channels.read` |
| **Status** | Whether each channel is working | `channels.read` |
| **Services** | What your company offers | `queues.read` |
| **Queues** | Waiting lines for conversations | `queues.read` |
| **Roles** | Who may do what | `roles.manage` |
| **SLA** | Response-time targets | `sla_policies.read` + SLA feature |
| **Intelligence** | Patterns the platform has noticed | `intelligence.read` |
| **Reports** | Performance and volume | `reports.read` |
| **Billing** | Usage and invoices | `billing.read` |
| **ERPNext** | ERP synchronisation | `erp.manage` + ERP feature |
| **Settings** | Company configuration | `company.manage` |

> **Note** — **Your menu may be shorter than a colleague's.** Two filters
> are applied invisibly: your permissions, and what your company's plan
> includes. This is normal, not a fault. If you need an item you cannot
> see, ask your administrator which of the two is missing.

> **Note** — The menu is currently one long list. A grouped version is
> planned; see [§15](#15-faq) under *Navigation*.

## 2.4 User profile

**Purpose:** control your own account and how the product behaves for you.

**When to use it:** first day, and whenever you go on holiday or change
your working preferences.

**Permissions required:** none. Everyone can change their own profile.

### Step by step — opening your profile

1. Select your **avatar** (top right).
2. Select **Profile**.

`[Screenshot placeholder: Profile screen with sections for details, password, language, theme, availability and notifications]`

### Fields explained

| Field | What it does |
|---|---|
| **Name** | How your name appears to colleagues |
| **Email** | Your sign-in address |
| **Password** | Change it here; you need your current one |
| **Language** | English or Arabic. Arabic switches the whole layout right-to-left |
| **Theme** | Light or dark |
| **Availability** | Whether new conversations are assigned to you |
| **Notification preferences** | Which events notify you, and how |

### Availability explained

| Status | Effect |
|---|---|
| **Available** | You receive automatically assigned conversations |
| **Away** | You receive none |

> **Warning** — Setting yourself **Away** does **not** hand over the
> conversations you already have. They stay yours. Transfer them before
> you finish for the day, or they wait for you.

### Example

Omar finishes at 5pm and has three open conversations. He transfers two
to the Support queue for the evening shift and sets himself **Away**. The
third he leaves assigned to himself because the customer is waiting for a
call back tomorrow morning.

### Best practices

> **Best Practice** — Set yourself **Away** the moment you stop working,
> not when you remember. Conversations assigned to somebody who has gone
> home are the most common cause of a missed target.

> **Tip** — If you work in Arabic, switch the language before doing
> anything else. The whole layout mirrors, and it is easier to learn the
> product once in the language you will use.

### Troubleshooting

- **Password change rejected** — your current password is wrong, or the
  new one is too short. The screen tells you which.
- **Language did not change** — refresh the page.

## 2.5 Notifications

**Purpose:** tell you when something needs you.

**Permissions required:** none.

### What you are notified about

| Event | Meaning |
|---|---|
| Conversation assigned to you | Somebody, or the system, gave you a conversation |
| Conversation transferred to you | A colleague passed one over |
| SLA warning | A conversation is approaching its target |
| SLA breach | A target was missed |
| AI handoff | The AI stopped and wants a human |

### How they reach you

| Method | Requires |
|---|---|
| **In-app** | Nothing. Always on |
| **Email** | Your administrator has set up email |
| **Push** (browser/phone) | Your administrator has set up push, and you allowed notifications |

### Step by step — turning notifications on

1. Open **Profile → Notifications**.
2. Choose which events notify you and by which method.
3. Select **Save**.
4. For push, your browser will ask permission. Select **Allow**.

> **Warning** — If you block browser notifications, Blink Engage cannot
> ask again. You must re-enable them in your browser's site settings.

### Common mistakes

- **Turning everything on.** You will mute all of it within a week, and
  then miss the one that mattered.
- **Assuming push is on.** It only works if your administrator has
  configured it. Check with them rather than assuming.

> **Best Practice** — Notify on **assignment**, **transfer** and **SLA
> breach**. Leave the rest off unless you have a reason.

---

# 3. Workspace

## 3.1 Companies

**Purpose:** your company's private area. Everything you do happens
inside it.

**When to use it:** you do not "use" a workspace — you work inside one.
Administrators configure it.

**Permissions required:** `company.manage` to change company settings.

### What a workspace contains

Your users, agents, departments, channels, queues, conversations,
customers, knowledge, reports and settings. All of it is invisible to
every other company using Blink Engage.

### Step by step — changing company details

1. Open **Settings → Company**.
2. Update the fields you need.
3. Select **Save**.

`[Screenshot placeholder: Company settings with tabs across the top]`

### Fields explained

| Field | What it affects | If wrong |
|---|---|---|
| **Company name** | Shown to customers in surveys and emails | Customers see the wrong name |
| **Timezone** | Every time calculation in the product | All your times and reports are shifted |
| **Logo** | Branding on surveys and emails | Cosmetic only |
| **Default language** | Fallback when a customer's language is unknown | Auto-replies in the wrong language |

> **Warning** — **Set the timezone before you do anything else.** It is
> the basis for business hours, SLA clocks, reports and schedules.
> Changing it later does not correct reports that were already produced.

### Example

Amman Home Supplies sets its timezone to *Asia/Amman*. Their business
hours of 09:00–17:00 now mean 9am to 5pm in Amman, and an SLA clock does
not run overnight.

## 3.2 Users

**Purpose:** the people who can sign in.

**When to use it:** when someone joins, leaves or changes job.

**Permissions required:** `agents.read` to view, and role-management
permission to invite or change roles.

### Users and agents — the difference

| | |
|---|---|
| **User** | Anyone who can sign in |
| **Agent** | A user who handles conversations, with availability and workload |

Every agent is a user. Not every user is an agent — a manager who only
reads reports is a user, not an agent.

### Step by step — inviting someone

1. Open **Agents**.
2. Select **Invite**.
3. Enter their **name** and **email**.
4. Choose their **role**.
5. Optionally choose a **department** and **team**.
6. Select **Send invitation**.

They receive an email, set their own password, and appear as active once
they have verified.

`[Screenshot placeholder: Agents list with an "Invite" button top right]`

> **Note** — You cannot set somebody's password for them. You can trigger
> a reset. Nobody should be able to sign in as another person.

### Step by step — someone leaves

1. Open **Agents**.
2. Find the person and open their record.
3. Select **Deactivate**.

> **Warning** — **Deactivate, do not delete.** Deactivating keeps their
> conversation history and audit trail intact and stops them signing in.
> Deleting a person who answered a thousand conversations damages your
> records.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Deleting instead of deactivating | Conversation history loses its author |
| Giving everyone an administrator role | Anyone can change routing or delete data |
| Not deactivating leavers | A former employee can still sign in |

> **Best Practice** — Review your user list once a quarter. Deactivate
> anyone who has left.

## 3.3 Teams and departments

**Purpose:** group people so work can be routed and reported by group.

**When to use it:** when different groups of people handle different
kinds of work. **Not before.**

**Permissions required:** `departments.read` to view.

### The difference

| | Purpose |
|---|---|
| **Department** | A permanent organisational unit — Support, Sales, Billing. Can be a routing target |
| **Team** | A working group inside or across departments, used for assignment and reporting |

### Step by step — creating a department

1. Open **Departments**.
2. Select **New department**.
3. Enter a **name** and optional **description**.
4. Select **Save**.
5. Assign agents to it from the **Agents** screen.

> **Note** — Neither is required. A ten-person company can run
> perfectly well with no departments at all.

> **Best Practice** — Create a department when you can name the work it
> owns. "Billing handles invoice and payment questions" is a reason.
> "We should probably have departments" is not — an empty hierarchy is
> overhead somebody has to maintain forever.

### Common mistakes

- **Mirroring your whole org chart.** Blink Engage is not an HR system.
  Create only the groups that route or report differently.
- **Creating departments with one person in each.** That is a list of
  people, which you already have.

## 3.4 Roles

**Purpose:** decide what each person may do.

**When to use it:** when inviting someone, and when someone's job changes.

**Permissions required:** `roles.manage`.

### Screen explained

`[Screenshot placeholder: Roles screen listing roles with a permission matrix]`

| Element | What it does |
|---|---|
| **Role list** | Every role in your workspace |
| **Permission matrix** | What each role may do, by resource and action |
| **New role** button | Creates a custom role |
| **Assign** | Attaches a role to a user |

### Default roles

| Role | Typically can |
|---|---|
| **Owner** | Everything, including billing and company settings |
| **Administrator** | Configure the workspace; not billing |
| **Supervisor** | See all conversations and reports; manage the team |
| **Agent** | Handle conversations assigned to their queues |

### Step by step — creating a custom role

1. Open **Roles**.
2. Select **New role**.
3. Name it something describing the job — "Billing Agent", not "Role 2".
4. Tick the permissions it needs.
5. Select **Save**.
6. Assign it to people from **Agents**.

### Example

Amman Home Supplies creates a **Weekend Supervisor** role: it can read
all conversations, transfer them, and read reports, but cannot change
routing rules or invite people.

### Best practices

> **Best Practice** — Grant the narrowest role that lets someone do their
> job. Widening a role later takes a minute. Discovering that a
> temporary contractor had delete permission for a year does not.

> **Tip** — Name roles after jobs, not after permission levels. "Billing
> Agent" tells you who should have it; "Level 2" does not.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Giving everyone Administrator | Anyone can delete a queue or a routing rule |
| Copying a role and forgetting to narrow it | Quiet over-permission |
| Using roles to hide screens for tidiness | Roles are security, not decoration |

## 3.5 Permissions

**Purpose:** the individual actions a role can allow.

**Permissions required:** `roles.manage` to view or change.

### How permissions work

Each permission is a **resource** plus an **action** — for example
`conversations.read` or `roles.manage`. A role is a collection of these.
A user gets permissions from their role.

Permissions are checked on the server for **every action**. Hiding a
button does not protect anything; the permission does.

### Permissions and features are different questions

| | Asks |
|---|---|
| **Permission** | May *this person* do it? |
| **Feature** | Did *this company* buy it? |

Both can produce "you cannot do that". The message tells you which.

> **Note** — If a colleague can see a screen and you cannot, it is a
> permission. If **nobody** in your company can see it, it is a feature
> your plan does not include. Only the second one needs a plan change.

### Troubleshooting

- **"You do not have permission"** — ask your administrator to check your
  role.
- **A whole menu section is missing for everyone** — your plan does not
  include that feature.
- **You could do something yesterday and cannot today** — your role was
  changed. Role changes are recorded in the audit trail.

---

# 4. Inbox

The Inbox is where agents spend the day. This is the longest section of
the guide because it is the one you will use most.

## 4.1 Channels

**Purpose:** the ways customers reach you.

**When to use it:** administrators connect channels; agents just see the
conversations that arrive.

**Permissions required:** `channels.read` to view; administrator rights to
connect.

### Supported channels

| Channel | Customers reach you via |
|---|---|
| **WhatsApp** | Your WhatsApp Business number |
| **Facebook Messenger** | Your Facebook page |
| **Instagram** | Direct messages to your account |
| **Telegram** | Your Telegram bot |
| **Email** | A support email address |
| **SMS** | A phone number |
| **Web Chat** | A chat widget on your website |

More channel types can be added through a plugin system.

### Step by step — connecting a channel

1. Open **Channels**.
2. Select **Add channel**.
3. Choose the channel type.
4. Enter the credentials the form asks for. These come from the provider
   — for example, from Meta for WhatsApp.
5. Select **Test connection**.
6. Only when the test passes, select **Save**.

`[Screenshot placeholder: Add channel screen with type selector, credential fields, "Test connection" and "Save" buttons]`

> **Warning** — **Always use Test connection before saving.** Saved
> credentials are not verified credentials. A single mistyped character
> in a token looks perfectly saved, reports no error, and silently
> receives nothing. Teams have gone live believing they were reachable
> and discovered otherwise from an angry customer.

### Screen explained — Status

**Status** shows whether each connected channel is currently working.
Blink Engage checks every five minutes.

| Indicator | Meaning | Action |
|---|---|---|
| **Healthy** | Working | None |
| **Unhealthy** | Cannot reach the provider | Usually an expired token — reconnect |
| **Not configured** | Credentials incomplete | Finish the setup |

`[Screenshot placeholder: Status screen listing channels with health indicators]`

### Example

A clinic connects WhatsApp and email. A patient messages WhatsApp asking
about opening hours; the message appears in the Inbox within seconds as a
new conversation. The reply the agent types goes back to WhatsApp
automatically.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Saving without testing | The channel silently receives nothing |
| Ignoring an unhealthy status | Customers message you and nobody sees it |
| Reusing a personal WhatsApp number | You cannot connect it; you need WhatsApp Business |

> **Tip** — Check **Status** on Monday mornings. Tokens expire quietly,
> usually over a weekend.

### Troubleshooting

- **Channel shows unhealthy** — the token has almost certainly expired.
  Get a new one from the provider and reconnect.
- **Test connection fails** — read the error; it comes from the provider
  and usually names the problem exactly.
- **Messages arrive late** — check Status, then ask your administrator to
  check the platform's queues.

## 4.2 Conversations

**Purpose:** read and answer customer messages.

**When to use it:** all day.

**Permissions required:** `conversations.read` to see them; write
permission to reply.

### Screen explained — the Inbox

`[Screenshot placeholder: Inbox with the conversation list on the left and the open conversation on the right]`

The Inbox is two panes side by side. Opening a conversation does **not**
take you off the list — it opens beside it, so you keep your place and
can move straight on to the next one.

| Pane | Contains |
|---|---|
| **Left — the list** | The queue you have chosen, and every conversation in it |
| **Right — the conversation** | Who it is with, what state it is in, the messages, and the reply box |

On a phone or a narrow window there is not room for both, so you see one
at a time and a back arrow returns you to the list.

### Choosing what to work on

At the top of the list are the **work queues** — *Needs attention*,
*Waiting pickup*, *Assigned to me*, *AI working*, *Waiting customer*,
*At risk*, *Breached*, *Resolved today*. Each one carries its own count,
so you can see how much is in it before you open it. Choosing one is
like sitting at a different desk: the list below shows only that work.

> **Tip** — Empty queues stay on screen showing a zero. "Breached (0)"
> is worth seeing.

### The conversation list

Each row is written to be read in the order you decide in: **who** it is
with, **why** it is in front of you, **how urgent** it is, **who owns
it** and **for how long**, and finally what most recently changed. The
message text is deliberately not the first thing — you should know why a
conversation needs you before you read a word of it.

Rows nobody has claimed carry a **Pick up** button, so you can take one
without opening it first.

### What you see at the top of an open conversation

`[Screenshot placeholder: Conversation header showing customer, channel, state, SLA and the timings strip]`

This strip is always on screen while you read. You should never have to
open anything to know where a conversation stands.

| Shown | What it tells you |
|---|---|
| **Customer name** | Who you are talking to. Select it to open their profile |
| **Channel icon** | Which line the conversation arrived on |
| **Star rating** | How this customer has been rated internally, if at all |
| **State** | What the conversation is waiting on right now |
| **SLA badge** | Attention, At risk or Breached. Nothing shown means healthy |
| **Priority** | Only when it is not Normal |
| **Unread** | How many customer messages you have not read |
| **Owner** | Who is answerable — an agent, a queue, or nobody |
| **Waiting** | How long it has been in that state. This keeps counting while you watch |
| **Last message** | How long since anybody said anything |
| **Opened** | How old the whole conversation is |
| **First reply** | How long ago the customer first got an answer. Absent until they get one |
| **Queue** | Which queue it belongs to |

> **Tip** — **Waiting** is the number to read first. "Waiting 4m" and
> "Waiting 4h" call for completely different behaviour.

### Badges explained

| Badge | Meaning | What to do |
|---|---|---|
| **Unassigned** | Nobody has taken it | Pick it up, or leave it for the right person |
| **Attention** | The response clock is ticking on | Prioritise it |
| **At risk** | Close to missing the target | Answer now |
| **Breached** | The target was missed | Answer immediately; it is already late |
| **Autopilot** | The AI is handling it | Watch; take over if needed |
| **Handoff needed** | The AI stopped and wants a human | Take over |
| **Unread** | New messages you have not seen | Read them |

### Conversation statuses

| Status | Meaning |
|---|---|
| **New** | Just arrived, not yet touched |
| **Waiting** | In a queue, waiting for an agent |
| **In progress** | An agent is working on it |
| **Waiting on customer** | You replied; the customer has not |
| **Waiting on agent** | The customer replied; you have not |
| **Resolved** | Dealt with. May trigger a satisfaction survey |
| **Customer feedback** | Awaiting or receiving a survey response |
| **Closed** | Finished |

> **Note** — **Waiting on customer** is the status that most affects your
> numbers. A conversation sitting in it is not counted against your
> response time, because you are not the one holding it up.

### Priority

| Priority | Use for |
|---|---|
| **Low** | Non-urgent questions |
| **Normal** | The default |
| **High** | Unhappy customer, or time-sensitive |
| **Urgent** | Serious problems — an outage, a safety issue |

### Step by step — answering a conversation

1. Open **Inbox**.
2. Choose a work queue, if you are not already in the right one.
3. Select a conversation from the list. It opens beside the list.
4. Read the strip at the top: who, what state, how long.
5. Select **Pick up** to take it, if nobody has.
6. Type in the reply box — or press **/** for a saved reply.
7. Select **Send**.

`[Screenshot placeholder: Open conversation with the timings strip, message history and the reply box]`

### Buttons explained

| Button | Where | What it does |
|---|---|---|
| **Pick up** | Header, and on unclaimed rows in the list | Assigns the conversation to you |
| **Ask AI to reply** | Header | Hands answering to the AI |
| **Take over** | Header, while AI holds it | Takes it back from the AI |
| **Transfer** | Header | Moves it to another agent, queue or department |
| **Release** | Header | Gives it up so somebody else can take it |
| **Ask to delete** (bin) | Header | Asks an administrator to delete the conversation |
| **Redact** | On a message | Removes what that one message said. Administrators only |
| **Details** (i) | Header | Opens status, queue, customer and the AI summary |
| **Send** | Reply box | Sends your reply over the customer's own channel |
| **Attach** (paperclip) | Reply box | Adds a file |
| **Saved replies** (lightning) | Reply box | Inserts wording your company has approved |
| **AI** (sparkle) | Reply box | Drafts a reply for you to edit |
| **Internal notes** | Tab | Switches to notes nobody outside your company sees |

> **Note** — Status, priority and queue are changed from **Details**.
> They are re-filing rather than replying, which is why they are one
> click away instead of on screen all day.

### Redacting a message

**Purpose:** remove what a single message said — a customer who pasted
their card number into the chat, a colleague who sent something that
should not be in the record.

**Permissions required:** `messages.redact`. Administrators and the
account Owner. Agents cannot redact.

**Redaction removes the words, not the message.** The message stays in
the conversation — in the right place, with the right time, marked as
redacted. That is deliberate. A message sent over WhatsApp or email
cannot be unsent: the customer still has their copy. Deleting ours would
destroy our half of a record they can still produce, which is the worst
of both.

#### Step by step

1. Open the conversation and find the message.
2. Select **Redact** on the message.
3. Write **why**. At least a sentence — this is what an auditor will
   read, possibly years later.
4. Confirm.

`[Screenshot placeholder: The redact dialog on a single message, with the reason field]`

> **Warning** — This cannot be undone. There is no "show me what it said"
> anywhere in the product afterwards, for anybody, including the Owner.

#### What gets removed

| | |
|---|---|
| The message text | Gone |
| Anything the channel provider stored with it | Gone |
| Files attached to that message | Deleted from storage |
| Anything the AI had learned or remembered from it | Removed |
| The fact that a message was sent, by whom, and when | **Kept** |
| Who redacted it and why | **Kept, permanently** |

> **Note** — A redacted message can never be used again: it is excluded
> from AI answers, from what the platform learns, and from search.

#### Common mistakes

- **Using redaction for a whole conversation.** Redaction is one message
  at a time. To remove an entire conversation, ask for it to be deleted
  — see below.
- **Expecting the customer's copy to disappear.** It will not. Redaction
  removes our record, not theirs.
- **Writing "PII" as the reason.** It will be refused. Say what happened.

### Deleting a conversation

**Purpose:** remove a conversation that should not be kept — a customer
exercising their right to be forgotten, a duplicate, something posted to
the wrong account.

**Permissions required:** `conversations.delete_request` to ask (every
agent has it). `conversations.delete_approve` to decide (administrators). Deleting a
conversation outright, without a request, stays with the Owner alone.

**Deleting takes two people.** A conversation is the record of what your
company said to a customer: evidence in a dispute, an input to every
report, and in some industries something you are obliged to keep. So
nobody removes one on their own.

#### Step by step — asking

1. Open the conversation.
2. Select the **bin icon** at the end of the row of buttons at the top.
3. Write **why** it should be deleted. At least a sentence — an
   administrator will read it, possibly days later, and it is all they
   will have.
4. Select **Send request**.

`[Screenshot placeholder: The "Ask to delete this conversation" dialog with the reason field]`

> **Note** — Nothing is deleted at this point. The conversation stays
> exactly where it is until an administrator agrees.

Once you have asked, everybody who opens that conversation sees a banner
naming you and quoting your reason, and the bin icon disappears. That is
deliberate: a colleague about to write a long reply should know it may be
on its way out, and nobody should ask twice.

#### Step by step — deciding

**Permissions required:** `conversations.delete_approve`.

1. Open **Deletion requests** in the left menu, under **Work**.
2. Read the reason. It is the whole basis of the decision.
3. Either:
   - **Approve and delete** — the conversation is deleted immediately. A
     note is optional.
   - **Reject** — the conversation is kept. A note is **required**; the
     person who asked only sees what you write.

`[Screenshot placeholder: Deletion requests queue with a pending request and its reason]`

> **Warning** — Approving deletes the conversation and cannot be undone.

> **Note** — You cannot decide your own request. If you asked, somebody
> else has to agree. An administrator who does not want a second opinion
> can delete a conversation directly instead, and the record will show
> that is what they did.

> **Note** — Whoever asked is told the outcome either way, and
> administrators are told as soon as a request arrives. Nobody has to go
> looking.

#### What is kept afterwards

The request survives the conversation. Long after the messages are gone,
the record still shows the customer's name, the reason given, who asked,
who agreed and when. That is the point — a deletion nobody can account
for later is indistinguishable from a mistake.

#### Common mistakes

- **Writing "spam" as the reason.** It will be refused, and rightly: it
  tells the administrator nothing.
- **Asking twice.** One request can be open per conversation at a time.
  If the button has gone, somebody has already asked.
- **Expecting it to disappear immediately.** It does not. Watch for the
  banner, and the notification when a decision is made.

### Saved replies

**Purpose:** send the wording your company agreed on, without retyping
it.

**Permissions required:** `quick_replies.read`.

Saved replies are the phrases you use over and over — the refund policy,
opening hours, the apology your legal team approved. Typing them out
each time is slower, and the wording drifts a little every time somebody
does.

#### Step by step

1. Put your cursor in the reply box.
2. Press **/**, or select the lightning icon.
3. Start typing — the shortcut (`/refund`), the title (*Refund policy*),
   or any words from the reply itself.
4. Use the arrow keys and **Enter**, or select one with the mouse.
5. The wording appears in the reply box. Edit it if you need to — add a
   name, a date — then **Send**.

> **Tip** — **/** only opens the picker when it is the very first thing
> in an empty box. You can still type "12/05" or "and/or" normally.

> **Note** — A saved reply replaces whatever is in the box. That is
> deliberate: a saved reply is a whole answer, not a fragment.

> **Warning** — Saved replies are not sent automatically. Nothing goes to
> the customer until you select **Send**.

Administrators add and edit saved replies; agents use them. A reply
turned off by an administrator stops being offered immediately, so
withdrawn wording cannot go back out.
| **Autopilot** | Turns AI handling on or off for this conversation |

> **Note** — You do not choose which channel your reply goes to. It goes
> back the way the customer came in. A WhatsApp message gets a WhatsApp
> reply.

### Example

A customer messages on Instagram: *"Is the blue chair still available?"*

1. The conversation appears as **Unassigned** in the Sales queue.
2. Hana selects it and chooses **Pick**.
3. She checks stock, types "Yes, we have three left — would you like me
   to reserve one?", and selects **Send**.
4. The status becomes **Waiting on customer**.
5. The customer replies "Yes please." The status becomes **Waiting on
   agent**.
6. Hana reserves it, replies, and selects **Resolve**.

### Best practices

> **Best Practice** — **Pick before you reply.** Picking tells everyone
> else you are handling it. Replying without picking means two agents can
> answer the same customer.

> **Best Practice** — Answer the **at risk** and **breached**
> conversations before the new ones, even though new ones feel more
> urgent.

> **Tip** — Read the whole history before replying, especially on a
> reopened conversation. The customer remembers what they told you last
> week even if you do not.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Replying without picking | Two agents answer the same customer |
| Resolving to clear the list | The customer replies, it reopens, and your numbers look worse |
| Using **Close** instead of **Resolve** | Skips the satisfaction survey |
| Writing an internal note in the reply box | The customer sees it |

> **Warning** — **Check whether you are in Reply or Note mode before you
> type.** The box looks similar in both. Sending an internal note to a
> customer cannot be undone — messages already delivered to WhatsApp or
> email cannot be recalled.

### Troubleshooting

- **The reply will not send** — check the channel's Status. An expired
  token blocks sending.
- **The conversation disappeared from "mine"** — ownership expires if a
  conversation is untouched for a while, and it returns to the queue.
  Pick it up again.
- **The customer says they did not receive it** — check Status, then give
  your administrator the time and conversation reference.

## 4.3 Assigning

**Purpose:** decide who is responsible for a conversation.

**When to use it:** every conversation should have exactly one owner.

**Permissions required:** conversation write permission. Assigning to
*other* people usually needs a supervisor role.

### The three ways a conversation gets an owner

| Method | How |
|---|---|
| **Automatic** | The assignment engine picks an available agent, based on workload, capacity and skills |
| **Pick** | You take it yourself |
| **Assign** | A supervisor gives it to a specific person |

### Step by step — taking a conversation

1. Open it.
2. Select **Pick**.

### Step by step — giving it to someone else

1. Open the conversation.
2. Select **Transfer**.
3. Choose a **person**, a **queue**, or a **department**.
4. **Write a note explaining why.**
5. Select **Transfer**.

`[Screenshot placeholder: Transfer dialog with target selector and reason box]`

> **Best Practice** — Always write the reason. The next person inherits
> the conversation but not your reasoning. "Transferring to Billing —
> customer disputes invoice 4471, I have confirmed the delivery date" is
> useful. An empty transfer is a puzzle.

### Ownership expiry

If you take a conversation and then do nothing with it, ownership expires
and it returns to the queue.

This exists so a conversation is not stranded on somebody who went home.
It is not a punishment.

> **Tip** — If you are waiting on something slow — a supplier, a
> colleague — leave an internal note saying so. Then it is obvious to
> everyone that the conversation is being handled, not forgotten.

### Common mistakes

- **Transferring without a reason.** The next agent starts from zero.
- **Assigning to a person who is Away.** It will sit until they return.
  Transfer to a queue instead.
- **Hoarding conversations.** Ten open conversations assigned to you that
  you are not working on hides them from everybody else.

## 4.4 Notes and internal comments

**Purpose:** talk to your colleagues inside a conversation without the
customer seeing.

**When to use it:** context, warnings, what you have already tried, what
you are waiting for.

**Permissions required:** conversation write permission.

### Step by step

1. Open the conversation.
2. Select **Note** above the message box.
3. Type your note. The box changes colour to show it is internal.
4. Select **Add note**.

`[Screenshot placeholder: Conversation with the note box highlighted in a different colour and an internal note in the timeline]`

### What notes are for

| Good note | Why |
|---|---|
| "Called the supplier — back in stock Thursday" | Saves the next agent a phone call |
| "Customer has complained twice about the same fault" | Warns whoever picks it up |
| "Refund approved by Sara, ref 4471" | Records a decision |

> **Warning** — Notes are **permanent** and **auditable**. They are
> internal, not private. Write them as though a colleague, a manager or a
> regulator might read them later — because one might.

### Common mistakes

- **Writing the note in the reply box.** The customer receives it.
- **Using notes for personal opinions about a customer.** They last
  forever and are visible to your whole team.
- **Not writing notes at all.** The next agent repeats work you already
  did.

> **Best Practice** — Leave a note before transferring, before going
> home, and after any decision the customer was not told about.

## 4.5 Tags

**Purpose:** label things so you can find and group them later.

> **Note — where tags exist today.** Tags are on **customer** records,
> not on conversations. You can tag a customer *VIP* or *Wholesale* and
> filter your customer list by that tag. There is **no conversation
> tagging** in this release.
>
> The AI can **suggest tags** from a conversation's content, which you
> then apply to the customer record.

### Step by step — tagging a customer

1. Open **Customers**.
2. Open the customer's record.
3. In the **Tags** field, type a tag and press Enter.
4. Select **Save**.

### Examples

| Tag | Used for |
|---|---|
| `vip` | Customers who get priority handling |
| `wholesale` | Business rather than retail buyers |
| `arabic` | Customers who prefer Arabic |

### Best practices

> **Best Practice** — Agree your tag list as a team and write it down.
> Tags multiply: `VIP`, `vip` and `V.I.P.` become three different tags
> that each match a third of the customers you meant.

> **Tip** — Use lowercase, single words. It removes most of the
> duplication problem on its own.

## 4.6 Search

**Purpose:** find anything in your account — a conversation, a customer,
or a setting — without knowing which page it lives on.

**Permissions required:** you only ever see results you are allowed to
see. Search never shows you a type of thing you could not already open
yourself, and it tells you which types it looked in.

### Step by step

1. Select the **search box** at the top of the screen, or press
   **Ctrl + K** (**Cmd + K** on a Mac) from anywhere.
2. Type what you are looking for — a customer name, a phone number, a
   department, an FAQ.
3. Results appear grouped by type.
4. Select a result to open it.

`[Screenshot placeholder: Global search with results grouped under Conversations, Customers and Departments]`

### What you can search

| Type | Search by |
|---|---|
| **Conversations** | The customer's name or email |
| **Customers** | Name, email, phone |
| **Agents** | Name, email |
| **Knowledge articles** | Title, content |
| **Knowledge categories** | Name |
| **FAQs** | The question **and** the answer |
| **Quick replies** | Shortcut, title, text |
| **Teams** | Name, description |
| **Queues** | Name, description |
| **Workflows** | Name, description |
| **Services** | Name, code, description |
| **Departments** | Name, description |
| **Channels** | The name you gave it **and** its type, such as `whatsapp` |
| **SLA policies** | Name, description |
| **Roles** | Name, description — administrators only |

> **Note** — Search does not look inside the text of messages. It finds
> the **conversation** by the person it is with, which is how the Inbox
> identifies conversations anyway. To find words inside a conversation,
> open it and use your browser's own find.

> **Tip** — Searching a phone number is the fastest way to find a
> customer when they call you rather than message.

> **Tip** — You do not need to remember which settings page something is
> on. Type the name of the department, channel, service or SLA policy
> and go straight there.

> **Note** — Roles are the one exception: only people who can manage
> roles can find them in search. A list of your role names describes how
> you delegate authority, so it is not shown to everybody.

> **Note** — Some results appear greyed out and say *No page for this
> yet*. The record is real and the match is real; that part of the
> product has no screen of its own yet, so there is nowhere to send you.

### Common mistakes

- **Typing one character.** Search needs at least two. One letter
  matches almost everything, which is the same as matching nothing.
- **Expecting every match.** Search shows the best five of each type. If
  what you want is not there, open that type's own page and filter it —
  that list is complete and paginated.

> **Note** — Knowledge search understands **meaning**, not just exact
> words. Searching "cannot log in" finds an article titled "Password
> reset". Conversation search is more literal, so use words the customer
> actually typed.

### Common mistakes

- **Searching for a whole sentence.** Two or three distinctive words work
  better.
- **Expecting to find another company's data.** Search never crosses
  workspaces.

## 4.7 Filters

**Purpose:** narrow the Inbox to the conversations you care about.

### Filters available

| Filter | Options |
|---|---|
| **Assignment** | Mine, unassigned, everyone |
| **Status** | New, waiting, in progress, resolved, closed |
| **Queue** | Any queue you can access |
| **Channel** | WhatsApp, email, and so on |
| **Priority** | Low to urgent |
| **SLA health** | Healthy, attention, at risk, breached |

### Step by step

1. Open **Inbox**.
2. Choose filters in the left-hand panel.
3. The list updates immediately.
4. Filters stay applied as you move around.

> **Tip** — The most useful daily view is **unassigned + at risk**. It is
> everything that is nobody's responsibility and running out of time.

### Common mistakes

- **Forgetting a filter is on.** "My conversations have disappeared" is
  almost always a filter left from yesterday. Clear filters to check.

## 4.8 Attachments

**Purpose:** send and receive files.

**Permissions required:** conversation write permission.

### Step by step — sending a file

1. Open the conversation.
2. Select the **paperclip**.
3. Choose the file.
4. Add a message if you want.
5. Select **Send**.

### Step by step — receiving

Files the customer sends appear in the conversation. Images preview
inline. Audio and video can be played without downloading. Other files
show a download link.

### Limits

| | |
|---|---|
| **File types** | Restricted to an approved list |
| **Size** | Limited; the screen tells you the limit |
| **Channel limits** | Each channel has its own — WhatsApp and email differ |

> **Warning** — Blink Engage's limit is not the only one. A file that
> uploads fine can still be rejected by WhatsApp for being too large.
> If a file will not go through, ask the customer for a smaller version
> or email it instead.

### Common mistakes

- **Sending a huge file on WhatsApp.** Use email for large documents.
- **Assuming an upload was delivered.** Check the message shows as sent.

> **Tip** — For anything over a few megabytes, email is more reliable
> than any messaging channel.

---

# 5. AI Assistant

## 5.1 What the AI can do

**Purpose:** help agents answer faster, and answer simple questions
without an agent at all.

**When to use it:** whenever you want a draft, a translation, a summary,
or an answer from your knowledge base.

**Permissions required:** your company's plan must include the **AI**
feature, and an administrator must have configured a provider.

### The ten AI actions

| Action | What it does |
|---|---|
| **Reply suggestion** | Drafts a reply using the conversation and your knowledge base |
| **Summary** | Condenses a long conversation into a few lines |
| **Translate** | Translates a message |
| **Detect language** | Identifies what language a customer is writing in |
| **Sentiment** | Judges whether the customer sounds happy or unhappy |
| **Suggest tags** | Proposes tags from the conversation content |
| **Improve grammar** | Corrects your text without changing its meaning |
| **Rewrite professionally** | Adjusts tone |
| **Next best action** | Suggests what to do next |
| **Knowledge search** | Finds relevant articles and FAQs |

### Step by step — using a suggestion

1. Open a conversation.
2. Select **AI**.
3. Choose **Suggest reply**.
4. Read the draft.
5. Edit it — the draft is a starting point, not a finished answer.
6. Select **Send**.

`[Screenshot placeholder: AI panel showing a suggested reply with Use, Edit and Discard options]`

> **Warning** — **Nothing the AI drafts is sent until you send it.** Read
> every suggestion before sending. The AI answers from your knowledge
> base, so if an article is out of date, the suggestion will be
> confidently wrong.

## 5.2 Autopilot — the AI replying on its own

**Purpose:** answer straightforward questions without an agent.

**When to use it:** high volumes of repetitive questions — opening hours,
delivery times, return policy.

**Permissions required:** administrator, to enable it.

### How it decides

The AI replies on its own only when **all** of these are true:

1. Your administrator has enabled autopilot.
2. The conversation qualifies under your rules — for example, inside
   business hours.
3. The AI's **confidence** is above the threshold you set.
4. The conversation is not in SLA trouble.

If any is false, it does not reply.

### What happens when it is unsure

It stops and marks the conversation **Handoff needed**. It does not
guess.

> **Note** — Autopilot also **stops automatically** when a conversation
> is at risk of missing its target. The reasoning is that a conversation
> already in difficulty needs a person, not another automated reply.

### Step by step — taking over from the AI

1. Find the conversation marked **Handoff needed** or **Autopilot**.
2. Open it and read what the AI has already said.
3. Select **Pick**.
4. Reply as normal. Autopilot stops for that conversation.

### Example

A furniture shop enables autopilot with a high confidence threshold. A
customer asks "What time do you close?" — the AI finds the answer in the
knowledge base, is confident, and replies instantly at 9pm. Another asks
"Can I return a sofa I assembled myself?" — the AI is not confident,
stops, and marks it for a human. An agent answers the next morning.

### Best practices

> **Best Practice** — Start with a **high** confidence threshold and
> lower it slowly while watching the AI report. It is much easier to
> explain "the AI was cautious" than "the AI told a customer something
> untrue".

> **Best Practice** — Before enabling autopilot, make sure your knowledge
> base is current. Autopilot without good knowledge is an automated way
> of being wrong.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Enabling autopilot with an empty knowledge base | The AI cannot answer anything useful |
| Setting the threshold too low | The AI answers questions it should not |
| Setting it too high | The AI hands off everything, adding delay for no benefit |
| Never reviewing what the AI said | Nobody notices a wrong answer being repeated |

> **Tip** — Read the **AI report** weekly for the first month. It shows
> how much the AI handled and how often it handed off.

## 5.3 Knowledge answers

The AI answers from your knowledge base and FAQs. It does not invent
policy.

If the answer is not in your knowledge base, the AI cannot give it, and
will hand off rather than making something up.

> **Best Practice** — When you answer a question that is not in the
> knowledge base and will be asked again, add it. That is how the AI gets
> better — not by learning from conversations, but by you writing
> the answer down once.

## 5.4 Memory usage

Blink Engage remembers useful facts about a customer across conversations
— what they told you before, what they prefer.

**What you can expect:** an agent opening a conversation sees relevant
context from earlier conversations without searching for it.

**What you cannot expect in this release:** the platform does not
automatically create new memories from patterns across many
conversations. See [§12 AI & Learning](#12-ai--learning).

## 5.5 AI limitations

Stated plainly, because knowing these prevents most disappointment.

| Limitation | What it means for you |
|---|---|
| **It answers from your knowledge base** | Out-of-date articles produce confidently wrong answers |
| **It cannot see other companies' data** | It knows only what is in your workspace |
| **It cannot act** | It replies and suggests. It does not issue refunds, change orders or update records |
| **It stops when unsure** | You will get handoffs. That is the design working |
| **It stops on SLA trouble** | Difficult conversations always reach a human |
| **It does not learn from your conversations by itself** | Improving it means improving your knowledge base |
| **Suggestions are never auto-sent** | An agent always presses Send |

> **Warning** — The AI can be confidently wrong. It is a fast assistant,
> not an authority. For anything involving money, health, legal
> obligations or a promise to a customer, read carefully before sending.

### Troubleshooting

- **AI options are missing** — your plan may not include the AI feature,
  or no provider is configured. Ask your administrator.
- **The AI never replies on its own** — autopilot may be off, or the
  threshold too high.
- **The AI gives wrong answers** — check the knowledge article it drew
  from. The article is usually the problem, not the AI.
- **The AI replies in the wrong language** — check the company default
  language and whether language detection is being used.

---

# 6. Knowledge Base

> **Note — there is no Knowledge screen in this release.**
>
> Knowledge is **real and working**: articles, FAQs and quick replies are
> stored, they are what the AI answers from, and knowledge results appear
> in global search. What does not exist yet is a **screen for managing
> them**. There is no Knowledge item in the menu, no article editor and
> no FAQ editor.
>
> Knowledge results found by search also cannot be opened — they show as
> a result, but there is no page to open.
>
> **How knowledge is maintained today:** through the platform API, which
> means your provider or IT team loads and updates it for you. If you
> need an article changed, that is who to ask.
>
> **This section describes what knowledge *is* and how it behaves**, so
> you understand what the AI is drawing on and can brief whoever
> maintains it. The step-by-step instructions in §6.2 to §6.5 describe
> the API-backed capability, not screens you can open today.

## 6.1 What the knowledge base is for

**Purpose:** the reference material your team and your AI answer from.

**When to use it:** whenever you answer a question you will be asked
again.

**Permissions required:** your plan must include the **Knowledge Base**
feature. Reading needs knowledge read permission; writing needs write
permission.

### Three kinds of content — do not confuse them

| | Who sees it | Used by | Purpose |
|---|---|---|---|
| **Knowledge article** | Your team (internal by default) | AI and agents | Reference material, in your own words |
| **FAQ** | Written to be shown to customers | AI and search | A question and its answer |
| **Quick reply** | Your team only | Agents | Canned text you send often |

The most common confusion is between an **article** and an **FAQ**.

- An **article** is a document. The AI reads it as raw material and puts
  the answer in its own words.
- An **FAQ** is a question and its exact answer. It is written to be
  shown, so the wording you choose is the wording customers get.

> **Best Practice** — If you have spent time getting the wording exactly
> right — a refund policy, a legal disclaimer — make it an **FAQ**, not
> an article. An article may be paraphrased. An FAQ is quoted.

## 6.2 Articles

### Screen explained — the Knowledge screen

`[Screenshot placeholder: Knowledge screen with a category list on the left, article list in the middle, and New article button top right]`

| Area | Contains |
|---|---|
| **Left — categories** | Your categories; select one to filter |
| **Middle — list** | Articles, with title, category and last edited date |
| **Top — search** | Finds articles by meaning, not just exact words |
| **Tabs** | Switch between Articles, FAQs and Quick replies |

### Buttons explained

| Button | What it does |
|---|---|
| **New article** | Opens the empty editor |
| **Save** | Stores your changes immediately |
| **Delete** | Removes the article permanently — there is no version history to restore from |
| **Categories** | Opens category management |

### Step by step — writing an article

1. Open **Knowledge**.
2. Select **New article**.
3. Enter a **title** that describes the question, not the topic.
4. Write the **body**.
5. Choose a **category**.
6. Select **Save**.

`[Screenshot placeholder: Article editor with title, body, category selector and Save button]`

### Fields explained

| Field | What it does |
|---|---|
| **Title** | How it appears in search. Write it as the question a customer would ask |
| **Body** | The content. The AI reads this |
| **Category** | Groups related articles |
| **Language** | Which language the content is in |

### Examples

| Weak title | Better title |
|---|---|
| "Returns" | "How do I return an item?" |
| "Delivery info" | "How long does delivery take?" |
| "Policy v2 final" | "What is our refund policy?" |

> **Tip** — Write titles as questions. Customers search in questions, and
> so does the AI.

### Best practices

> **Best Practice** — One article, one question. A single article
> covering returns, refunds and exchanges will be found for all three and
> answer none of them well.

> **Best Practice** — Put a date or an owner in articles that go stale —
> prices, opening hours, promotions. It makes review possible.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Writing articles nobody maintains | The AI confidently repeats last year's price |
| Copying a long PDF into one article | Search finds it for everything and helps with nothing |
| Vague titles | Neither agents nor the AI can find it |

## 6.3 Categories

**Purpose:** group articles so they can be browsed.

### Step by step

1. Open **Knowledge → Categories**.
2. Select **New category**.
3. Name it.
4. Select **Save**.

> **Tip** — Keep categories few and obvious: Orders, Delivery, Returns,
> Account, Technical. Twenty categories with one article each is a
> filing system nobody uses.

## 6.4 FAQs

### Step by step — creating an FAQ

1. Open **Knowledge → FAQs**.
2. Select **New FAQ**.
3. Enter the **question** exactly as a customer would ask it.
4. Enter the **answer** exactly as you want it shown.
5. Choose a **category** and **language**.
6. Select **Save**.
7. When you are happy with it, select **Publish**.

`[Screenshot placeholder: FAQ editor showing question, answer, category, language and a Publish toggle]`

### Publishing explained

> **Note** — **A new FAQ starts unpublished.** This is deliberate. Unlike
> an article, which only your team sees, an FAQ is written to be shown to
> customers. Publishing is a decision, so it is a separate action.

**Unpublishing** does more than hide it: it also removes the FAQ from
search, so nothing can quote an answer you have taken down.

### Order

FAQs appear in the order you set. Put the most-asked first.

### Examples

| Question | Answer |
|---|---|
| "Do you deliver to Irbid?" | "Yes. Delivery to Irbid takes 2–3 working days and costs 3 JOD." |
| "Can I pay on delivery?" | "Yes, cash on delivery is available for orders under 200 JOD." |

### Common mistakes

- **Writing the FAQ and forgetting to publish.** It exists but nobody
  sees it. Check the publish state after saving.
- **Publishing a draft.** The wording is shown to customers exactly as
  written.
- **Answering two questions in one FAQ.** Split them.

## 6.5 Quick replies

**Purpose:** text you send many times a day, saved once.

### Step by step

1. Open **Quick replies**.
2. Select **New quick reply**.
3. Enter a **shortcut** and the **text**.
4. Select **Save**.

To use one: in a conversation, select **Quick reply** and choose it. The
text is inserted into the reply box, where you can edit it before
sending.

### Examples

| Shortcut | Text |
|---|---|
| `greeting` | "Hello, thank you for contacting us. How can I help today?" |
| `hours` | "We are open Sunday to Thursday, 9am to 5pm." |
| `wait` | "Thank you for your patience — I am checking this now." |

> **Tip** — Always edit a quick reply before sending. Customers can tell
> when they have received a template, and adding one specific detail
> makes it read as a person.

## 6.6 Search

Knowledge search understands **meaning**. Searching "cannot log in" finds
"How do I reset my password?" even though no words match.

### Step by step

1. Use the global search box, or search inside **Knowledge**.
2. Type the customer's question.
3. Open the best result.

> **Tip** — Search using the customer's own words rather than your
> internal terminology. That is how the AI searches too, and it will show
> you whether the article is findable.

## 6.7 Drafts and version history

> **Note — what exists today.**
>
> **Drafts:** an article or FAQ that you save but do not publish acts as
> a draft. FAQs have an explicit published/unpublished state.
>
> **Version history: not available in this release.** Blink Engage does
> not keep previous versions of an article, and you cannot see what an
> article said last month or restore an earlier version. Editing an
> article replaces it.

> **Warning** — Because there is no version history, **be careful when
> editing a long-standing article**. If several people maintain your
> knowledge base, agree who edits what, and paste significant rewrites
> into a document outside Blink Engage first.

Version history is a planned improvement.

---

# 7. Workflows

> **Note — there is no Workflows screen in this release.**
>
> The workflow engine exists in the platform and can be configured
> through the API, but there is **no workflow builder in the interface**.
> You cannot create, edit, test or activate a workflow yourself.
>
> **How workflows are set up today:** ask your provider or IT team. They
> can configure triggers, conditions and actions for you.
>
> **This section explains how workflows think**, so you can describe what
> you want precisely. The screens and buttons described in §7.2 to §7.6
> describe the capability, not something you can open today.

## 7.1 What workflows are

**Purpose:** make the platform do something automatically when something
happens.

**When to use it:** for repetitive actions your team does by hand every
day.

**Permissions required:** your plan must include the **Workflow Engine**
feature, plus workflow management permission.

### How a workflow is built

Three parts:

```
   WHEN something happens        →   IF conditions are met   →   DO this
   (trigger)                         (conditions)                (actions)
```

### Example in plain language

> **When** a conversation is created,
> **if** it arrived on WhatsApp and the message contains "invoice",
> **then** move it to the Billing queue and set priority to High.

## 7.2 Creating a workflow

### Step by step

1. Open **Workflows**.
2. Select **New workflow**.
3. Give it a **name** describing what it does.
4. Choose a **trigger**.
5. Add **conditions**.
6. Add **actions**.
7. Save it as **inactive** first.
8. Test it.
9. Activate it.

`[Screenshot placeholder: Workflow editor showing trigger at the top, conditions in the middle, actions at the bottom]`

### Fields explained

| Field | What it does |
|---|---|
| **Name** | How you recognise it later |
| **Description** | Why it exists — write this, your future self will need it |
| **Trigger** | The event that starts it |
| **Conditions** | Extra tests that must pass |
| **Actions** | What happens |
| **Active** | Whether it runs |

### Screen explained — the Workflows screen

`[Screenshot placeholder: Workflow list showing name, trigger, active toggle and last run]`

| Column | Shows |
|---|---|
| **Name** | What you called it |
| **Trigger** | The event that starts it |
| **Active** | Whether it is running |
| **Last run** | When it last fired |

### Buttons explained

| Button | What it does |
|---|---|
| **New workflow** | Opens the editor |
| **Active** toggle | Turns the workflow on or off. Off is safe |
| **Runs** | Shows recent executions and what each one did |
| **Duplicate** | Copies a workflow as a starting point |
| **Delete** | Removes it permanently |

> **Tip** — Use the **Active** toggle rather than deleting a workflow you
> are unsure about. A workflow turned off can be turned back on; a
> deleted one has to be rebuilt from memory.

## 7.3 Triggers

A trigger is an event in the platform. Workflows can trigger on a wide
range of them, including:

| Trigger | Fires when |
|---|---|
| Conversation created | A new conversation starts |
| Conversation updated | Something about it changes |
| Message received | A customer sends a message |
| Conversation assigned | Ownership changes |
| Conversation transferred | It moves to someone else |
| Conversation resolved | An agent resolves it |
| SLA warning | A target is approaching |
| SLA breached | A target is missed |
| Customer created | A new customer record appears |
| Satisfaction submitted | A customer returns a survey |

> **Note** — Many more events exist than are listed here. The trigger
> picker in the product shows the current list.

## 7.4 Conditions

Conditions narrow when the workflow acts.

| Condition on | Examples |
|---|---|
| **Channel** | is WhatsApp |
| **Queue** | is Billing |
| **Priority** | is High or Urgent |
| **Message content** | contains "refund" |
| **Customer** | has tag `vip` |
| **Time** | outside business hours |

> **Warning** — **A workflow with a broad trigger and no conditions runs
> on everything.** "When a message is received, notify the manager" will
> notify the manager for every message from every customer all day. Add
> conditions before activating.

## 7.5 Actions

| Action | Effect |
|---|---|
| **Move to queue** | Sends the conversation to a different queue |
| **Assign** | Gives it to a specific agent |
| **Set priority** | Changes urgency |
| **Notify** | Alerts a person or group |
| **Add note** | Writes an internal note |
| **Send webhook** | Calls another system |

> **Note** — A **webhook** lets Blink Engage tell another system that
> something happened. Your IT team or supplier will tell you what address
> to use.

## 7.6 Testing

**Purpose:** confirm the workflow does what you meant before it affects
real customers.

### Step by step

1. Save the workflow as **inactive**.
2. Re-read the conditions and ask: *what else would match this?*
3. Activate it.
4. Create a test conversation that should match — send yourself a message
   on the channel.
5. Open **Workflows → Runs** to see whether it ran and what it did.
6. Also test something that should **not** match, and confirm it did not
   run.

`[Screenshot placeholder: Workflow runs list showing recent executions with timestamps and outcomes]`

> **Best Practice** — Testing the negative case matters more than the
> positive one. Most workflow problems are not "it did not run" but "it
> ran on things I did not expect".

### Best practices

> **Best Practice** — One workflow, one purpose. A single workflow doing
> five unrelated things is impossible to debug when one of them
> misbehaves.

> **Best Practice** — Start narrow. Add a condition limiting it to one
> queue or one channel, watch it for a week, then widen.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Broad trigger, no conditions | It fires constantly |
| Two workflows acting on the same event | They fight; the result depends on order |
| Never checking **Runs** | You do not find out it stopped working |
| No description | Nobody dares change it later |

### Troubleshooting

- **The workflow did not run** — check it is Active, then check the
  conditions actually match your test.
- **It ran but did nothing visible** — check **Runs** for the outcome;
  the action may have failed.
- **It runs too often** — your conditions are too broad.

---

# 8. Automation

Workflows are automation you build. This section covers the automation
that is built in.

## 8.1 Routing rules

**Purpose:** decide which queue a conversation goes to.

**When to use it:** as soon as you have more than one queue.

**Permissions required:** queue management permission.

### How rules are evaluated

Rules are checked in **priority order, highest first**. The **first rule
that matches wins**; the rest are not considered.

```
   Priority 100   if channel = WhatsApp and text contains "invoice"  →  Billing
   Priority  50   if channel = Email                                 →  Support
   Priority   0   (catch-all, no conditions)                         →  General
```

### The catch-all rule

Your workspace is created with a **catch-all rule** at the lowest
possible priority and no conditions. Anything that matches no other rule
lands in your General queue.

> **Warning** — **Do not delete the catch-all rule.** Without it, a
> conversation matching no rule reaches no queue at all and waits where
> nobody is looking. If you have deleted it, recreate a rule with no
> conditions at the lowest priority.

### Step by step — creating a rule

1. Open **Queues → Routing rules**.
2. Select **New rule**.
3. Set a **priority** — higher numbers are checked first.
4. Add **conditions**.
5. Choose the **target queue**.
6. Select **Save**.

`[Screenshot placeholder: Routing rules list ordered by priority, with the catch-all at the bottom]`

### Example

A clinic wants urgent medical questions handled first:

| Priority | Condition | Queue |
|---|---|---|
| 100 | Message contains "emergency", "urgent" or "pain" | Triage |
| 50 | Channel is email | Admin |
| 0 | (catch-all) | General |

### Common mistakes

| Mistake | Consequence |
|---|---|
| Deleting the catch-all | Conversations reach no queue |
| Two rules at the same priority | Which one wins is unpredictable |
| Very broad keyword conditions | Everything goes to one queue |
| Forgetting rules are first-match | Later rules never run |

> **Tip** — Leave gaps between priorities — 100, 200, 300. Then you can
> insert a rule between two existing ones without renumbering everything.

## 8.2 SLA

**Purpose:** set and measure promises about how fast you respond.

**When to use it:** as soon as you care about response times.

**Permissions required:** your plan must include the **SLA** feature.

### The four clocks

| Clock | Measures | Example target |
|---|---|---|
| **First response** | Customer's first message → your first reply | 1 hour |
| **Next response** | Each later customer message → your reply | 2 hours |
| **Resolution** | Conversation opened → resolved | 24 hours |
| **Idle** | Time since anyone said anything | 48 hours |

### Business hours

Clocks **pause outside business hours**. A message at 10pm does not burn
your one-hour target overnight.

> **Warning** — **This is the single most common configuration mistake in
> the product.** If business hours have never been set, every hour counts
> as a working hour. A message arriving at 6pm Thursday breaches its
> four-hour target before anyone is back at work on Sunday, and your SLA
> report looks catastrophic for no real reason.
>
> If your SLA numbers look wrong, check business hours first.

### SLA health

| Health | Meaning |
|---|---|
| **Healthy** | Comfortably inside the target |
| **Attention** | The clock is running |
| **At risk** | Approaching the target |
| **Breached** | The target was missed |

### Step by step — creating an SLA policy

1. Open **SLA**.
2. Select **New policy**.
3. Name it.
4. Set targets for the clocks you care about.
5. Set the **warning threshold** — how early you want to be told.
6. Confirm **business hours** is enabled.
7. Choose what it applies to — a service or a queue.
8. Select **Save**.

`[Screenshot placeholder: SLA policy editor with the four clocks, warning threshold, and business-hours toggle]`

### Example

A retailer promises: reply within 1 hour during business hours, resolve
within 1 working day. They set first response 60 minutes, resolution 8
working hours, warning at 75%. Agents see **at risk** at 45 minutes,
which is enough time to act.

### Best practices

> **Best Practice** — Set targets you can actually meet. An SLA nobody
> achieves is ignored within a fortnight, and then genuine breaches look
> the same as normal.

> **Best Practice** — Set the warning early enough to be useful. A
> warning at 95% of the target tells you about a problem you can no
> longer prevent.

### Common mistakes

- **Leaving business hours off.** Overnight and weekends destroy your
  numbers.
- **Targets copied from a competitor's marketing.** Measure what you
  currently do first, then improve on it.
- **Only measuring first response.** Customers care more about
  resolution.

## 8.3 Escalations

> **Note — how escalation works today.** There is no separate
> "escalation" screen. Escalation is built from the pieces above:
>
> - **SLA warnings and breaches** raise notifications and are visible in
>   the Inbox.
> - **Workflows** can act on an SLA warning or breach — notify a manager,
>   raise the priority, move it to a senior queue.
> - **Transfer** moves a conversation to a person or team who can help.

### Step by step — building an escalation

1. Create a queue called **Escalations**.
2. Create a workflow:
   - **Trigger:** SLA breached
   - **Conditions:** priority is High or Urgent
   - **Actions:** move to Escalations queue, notify the supervisor
3. Test it.
4. Activate it.

> **Best Practice** — Escalate on **breach plus importance**, not on
> breach alone. Escalating every breach floods the escalation queue and
> the supervisor stops reading it.

## 8.4 Scheduling

Blink Engage runs scheduled work in the background — checking SLA clocks,
sending notifications, checking channel health, polling email. You do not
configure or start any of it.

**What you can schedule:**

| Thing | Where |
|---|---|
| **Business hours** | Settings → Business hours |
| **Holidays** | Settings → Holidays |
| **AI availability** | AI settings — restrict AI to business hours |

### Step by step — setting business hours

1. Open **Settings → Business hours**.
2. Select your working days.
3. Set opening and closing times for each.
4. Select **Save**.
5. Add **holidays** separately — they apply on top of the weekly pattern.

`[Screenshot placeholder: Business hours grid with days down the side and open/close times]`

> **Best Practice** — Set business hours on day one, before anything
> else that depends on time. It affects SLA, AI and notifications
> together.

---

# 9. Customers

## 9.1 The customer record

**Purpose:** everything you know about one person, in one place.

**When to use it:** before replying to anyone you have spoken to before.

**Permissions required:** `customers.read`.

### Screen explained

`[Screenshot placeholder: Customer profile with details on the left and a conversation timeline on the right]`

| Area | Contains |
|---|---|
| **Details** | Name, email, phone |
| **Tags** | Labels you have applied |
| **Custom fields** | Extra information your company tracks |
| **Rating** | Your team's internal rating |
| **Notes** | Internal notes about the customer |
| **Timeline** | Every conversation, across all channels |
| **ERP data** | Orders and invoices, if ERP is connected |

### Step by step — opening a customer

1. Open **Customers**, or
2. From a conversation, select the customer's name.

## 9.2 Timeline and history

The timeline shows every conversation with this person, on every channel,
oldest to newest.

> **Tip** — Check the timeline before replying to a complaint. "I see you
> contacted us about this in March" changes the conversation completely,
> and the customer already knows they did.

### Merged across channels

If the same person contacts you by WhatsApp and email, and Blink Engage
can tell it is the same person, both appear on one timeline under one
customer.

> **Note** — Matching relies on shared details such as a phone number or
> email address. Someone using a different phone and a different email
> may appear as two customers. You can update the records so they match.

## 9.3 Attributes and custom fields

**Custom fields** hold information specific to your business — account
number, membership level, preferred branch.

### Step by step

1. Open the customer.
2. Edit the **custom fields**.
3. Select **Save**.

> **Best Practice** — Agree what each field means and write it down.
> A field called "Status" that one person fills with "Active" and another
> with "Paid" is worse than no field.

## 9.4 Notes and ratings

**Notes** are internal comments about the customer, separate from notes
inside a conversation. Use them for things that are true across every
conversation: "prefers phone calls", "account managed by Sara".

**Ratings** are your team's private assessment. Customers never see them.

> **Warning** — Notes and ratings are internal but permanent and
> auditable. Write nothing you would not be willing to defend.

### Common mistakes

- **Putting conversation-specific detail in a customer note.** It belongs
  in the conversation.
- **Using ratings to record frustration.** They are a business signal,
  not a place to vent.

## 9.5 Data requests

If a customer asks what you hold about them or asks you to delete it,
customer records can be erased. Speak to your administrator — this is a
decision with legal consequences, not a routine action.

> **Note** — Conversation history is retained by default. Whether it
> should be deleted alongside a customer record depends on your
> jurisdiction and your own policy.

---

# 10. Reports

## 10.1 What reports are for

**Purpose:** see how the operation is performing.

**When to use it:** weekly for a team, daily for a busy one, monthly for
a board.

**Permissions required:** `reports.read`. Exporting needs the **Report
Export** feature.

### The ten reports

| Report | Answers |
|---|---|
| **Executive dashboard** | How is the operation doing overall? |
| **Agent dashboard** | How is each agent performing? |
| **Live dashboard** | What is happening right now? |
| **Conversations** | How many, on which channels, over what period? |
| **Performance** | How fast do we respond and resolve? |
| **Queues** | Where does work wait, and how long? |
| **SLA** | Are we meeting our promises? |
| **CSAT** | How satisfied are customers? |
| **AI** | How much did the AI handle, and how well? |
| **AI usage** | What has the AI cost us? |

`[Screenshot placeholder: Executive dashboard with KPI cards across the top and trend charts below]`

### Screen explained — the Reports screen

| Area | Contains |
|---|---|
| **Tabs** | One per report |
| **Filter bar** | Date range, channel, queue, agent |
| **KPI cards** | The headline numbers for the period |
| **Charts** | The same numbers over time |
| **Table** | The detail behind the charts |

### Buttons explained

| Button | What it does |
|---|---|
| **Date range** | Sets the period. Everything on screen respects it |
| **Apply** | Runs the report with your filters |
| **Reset** | Clears filters back to the default |
| **Export** | Downloads the data. Needs the Report Export feature |

## 10.2 Reading the key numbers

| KPI | Means | Watch for |
|---|---|---|
| **Open conversations** | Not yet resolved | Rising steadily means you are falling behind |
| **First response time** | How long a customer waits for a first reply | The number customers notice most |
| **Resolution time** | Start to resolved | Rising while responses stay fast means things get stuck mid-way |
| **SLA attainment** | Percentage meeting targets | Below 90% means the target or the staffing is wrong |
| **CSAT** | Average satisfaction | Watch the trend, not one bad week |
| **Volume by channel** | Where customers come from | Tells you where to invest |
| **AI handled** | Answered without a human | Rising is good only if CSAT holds |
| **Handoff rate** | AI stopped and asked for help | High means confidence threshold or knowledge needs work |

> **Note** — **Averages hide problems.** An average first response of 20
> minutes can contain a hundred replies in 2 minutes and ten that took
> six hours. Look at the worst cases, not only the average.

## 10.3 Using a report

### Step by step

1. Open **Reports**.
2. Choose a report from the tabs.
3. Set the **date range**.
4. Apply filters — channel, queue, agent.
5. Read the numbers.
6. Export if you need to share them.

### Fields explained

| Control | What it does |
|---|---|
| **Date from / Date to** | The period covered |
| **Channel** | Limits to one channel |
| **Queue** | Limits to one queue |
| **Agent** | Limits to one person |
| **Export** | Downloads the data |

## 10.4 Exports

### Step by step

1. Open the report.
2. Set your date range and filters.
3. Select **Export**.
4. Choose the format.
5. The file downloads.

> **Note** — Export requires the **Report Export** feature in your plan.
> If you do not see the button, that is why.

> **Warning** — Exported reports contain customer information. Treat the
> file as you would any confidential document: do not email it outside
> the company, and delete it when you are done.

## 10.5 Best practices

> **Best Practice** — Look at the same three numbers every week rather
> than all forty occasionally. Consistency is what makes a trend visible.

> **Best Practice** — When a number moves, open the conversations behind
> it before drawing a conclusion. A spike in resolution time is sometimes
> one difficult case, not a trend.

> **Tip** — Compare like periods. Comparing a week containing a public
> holiday with a normal week produces a conclusion about the holiday.

### Common mistakes

| Mistake | Consequence |
|---|---|
| Judging an agent on volume alone | Rewards fast, shallow answers |
| Using averages only | Hides your worst customer experiences |
| Reading reports after a bad month | Reports are for noticing, not for post-mortems |
| Comparing agents on different queues | Different work, not different performance |

### Troubleshooting

- **Numbers look too low** — check the date range and filters.
- **A report is empty** — you may have filtered to a queue with no
  activity in that period.
- **Numbers differ from what you expect** — check the timezone in company
  settings.
- **SLA numbers look terrible** — check business hours before anything
  else.

---

# 11. Administration

## 11.1 Settings

**Purpose:** configure how the workspace behaves.

**Permissions required:** `company.manage`.

### Where to find things

| Setting | Location |
|---|---|
| Company name, timezone, logo | Settings → Company |
| Business hours and holidays | Settings → Business hours |
| AI configuration | Settings → AI |
| Notification rules | Settings → Notifications |
| Channels | Channels |
| Queues and routing | Queues |
| SLA policies | SLA |
| Roles | Roles |

## 11.2 Setting up a new workspace

### The recommended order

| Step | Task | Why in this position |
|---|---|---|
| 1 | Company name and **timezone** | Everything time-based depends on it |
| 2 | **Business hours** | SLA and AI both use it |
| 3 | **Connect a channel** | The only genuinely blocking step |
| 4 | Invite agents | Optional — a one-person workspace is valid |
| 5 | Review routing | The catch-all already works |
| 6 | SLA policy | Defaults apply until you set one |
| 7 | AI | Off until configured |

> **Note — what you already have.** Your workspace is created with
> default roles, a **General queue**, a **catch-all routing rule** and a
> **General service**. Routing works before you configure anything. You
> do not need to build it.

> **Warning** — The setup wizard does not currently stop you finishing
> with no channel connected. A workspace with no channel cannot receive
> anything from anyone. **Connect and test a channel before you consider
> setup complete.**

## 11.3 Integrations

### Email

**Purpose:** receive customer email as conversations, and send
notifications.

Two separate things use email:

| Use | Configured in |
|---|---|
| **Customer email as a channel** | Channels → Email |
| **Notifications to your team** | Platform email settings (administrator) |

> **Note** — If password reset emails do not arrive, notification email
> is not configured. That is a platform-level setting, not a channel.

### WhatsApp

1. You need a **WhatsApp Business** account and API access through Meta.
2. Open **Channels → Add channel → WhatsApp**.
3. Enter the credentials from Meta.
4. Select **Test connection**.
5. Save.

> **Warning** — A personal WhatsApp number cannot be connected. You need
> WhatsApp Business API access, which Meta must approve. Start this early
> — approval is not instant.

### Telegram

1. Create a bot with Telegram's BotFather and copy the token.
2. **Channels → Add channel → Telegram**.
3. Paste the token, test, save.

Telegram is usually the quickest channel to connect and a good one to
test the platform with.

### Facebook Messenger and Instagram

1. You need a Facebook Page, and for Instagram a linked professional
   account.
2. **Channels → Add channel**, choose the type.
3. Authorise through Meta.
4. Test and save.

### SMS

Requires an SMS provider account. Enter the credentials, test, save.

### Web Chat

1. **Channels → Add channel → Web Chat**.
2. Configure appearance and greeting.
3. Copy the code snippet.
4. Ask whoever maintains your website to paste it before `</body>`.

> **Tip** — Test the widget on your live site from a phone as well as a
> desktop. Chat widgets are the most common thing to look wrong on
> mobile.

### ERPNext

If your plan includes **ERP Integration**, Blink Engage can synchronise
customers, invoices, orders, quotations, tickets, payments and contacts
with ERPNext.

**Channels → ERPNext**, enter the URL and API credentials, test, save.

## 11.4 API keys

> **Note — not available in this release.** Blink Engage does not have a
> customer-facing API key management screen. There is no way for an
> administrator to generate an API key for a third-party tool from the
> product.
>
> The platform does have a full API, and a **workflow** can call an
> external system via a **webhook**. If you need a system to push data
> *into* Blink Engage, speak to your provider — it is an arrangement made
> outside the product today.

## 11.5 Security

**Purpose:** the controls protecting your data.

### What is in place

| Control | What it means |
|---|---|
| **Separate workspaces** | No company can see another's data. Enforced on every request |
| **Roles and permissions** | Every action is checked on the server |
| **Encrypted credentials** | Channel and ERP credentials are encrypted where they are stored |
| **Audit trail** | Every significant action is recorded permanently |
| **Rate limiting** | Protects against abuse |
| **Encrypted transport** | Traffic between browsers and the platform is encrypted |

### Your responsibilities

> **Best Practice** — Use a unique password and do not share accounts.
> A shared login makes the audit trail useless: every action is recorded
> against a person, and if two people are that person, nothing can be
> attributed.

> **Best Practice** — Deactivate leavers the day they leave.

> **Best Practice** — Review roles quarterly. Permissions accumulate.

### Audit logs

Every significant action is recorded — who, what, when. Audit logs are
permanent and are never deleted.

Use them to answer "who changed this?" and for anything that must be
defensible afterwards.

### Troubleshooting

- **"You do not have permission"** — your role lacks it. Ask an
  administrator.
- **A colleague sees a screen you cannot** — a permission difference.
- **Nobody in the company sees it** — a plan/feature difference.

---

# 12. AI & Learning

This section explains the three things people confuse most.

## 12.1 Knowledge, Memory and Learning

| | What it is | Who creates it | Used for |
|---|---|---|---|
| **Knowledge** | What your company officially says | **You write it** | Answering questions |
| **Memory** | What the platform remembers about a customer | Built from conversations | Context for agents and AI |
| **Learning** | Patterns the platform notices across many conversations | Detected automatically | Telling you what is happening |

### Knowledge — what you have decided

Your articles and FAQs. Deliberate, written by a person, and the
authority. The AI answers from this.

**If it is wrong, the AI is wrong.** Knowledge is the one of the three
you fully control, and the one most worth your time.

### Memory — what the platform remembers

Useful facts about a customer, so an agent does not have to read three
old conversations to learn that this customer prefers phone calls.

**What you can expect:** relevant context appearing when you open a
conversation.

### Learning — what the platform notices

Learning reads **finished** conversations and looks for patterns: groups
of similar conversations, trends over time, unusual spikes.

**What you can expect today:** a report. Learning tells you what it has
noticed.

> **Note — what Learning does *not* do in this release.**
>
> Learning **only observes**. It does not:
> - write anything into Memory,
> - create or edit knowledge articles,
> - change how conversations are handled,
> - change what the AI says,
> - act on anything it notices.
>
> This is deliberate. The platform is designed to prove its observations
> are sound before it is allowed to act on them.

## 12.2 The Intelligence screen

**Purpose:** see what the platform has noticed.

**Permissions required:** `intelligence.read`.

| Section | Shows |
|---|---|
| **Clusters** | Groups of similar conversations |
| **Trends** | Things increasing or decreasing over time |
| **Anomalies** | Unusual spikes worth a look |
| **Metrics** | How much has been observed |

`[Screenshot placeholder: Intelligence screen showing clusters with sizes and example conversations]`

### How to use it

1. Open **Intelligence**.
2. Look at the largest clusters — those are what customers ask most.
3. For each, ask: *is this in our knowledge base?*
4. If not, write an article or FAQ.

> **Best Practice** — This is the loop that makes the AI better. Learning
> shows you what customers keep asking; **you** write the answer; the AI
> starts answering it. The platform does not close that loop by itself,
> and in this release it is not supposed to.

## 12.3 Current limitations

| Limitation | What it means |
|---|---|
| **Learning only observes** | It reports; it does not act |
| **It needs volume** | Patterns need many conversations. A new workspace shows little |
| **Trends need history** | Several weeks of data before trends mean anything |
| **It never crosses companies** | It learns only from your own conversations |
| **No automatic knowledge creation** | You write the articles |

> **Note** — If **Intelligence** looks empty, that is expected on a new
> or low-volume workspace. It is not broken; it has not seen enough yet.

## 12.4 What to expect over time

| Time | What you will see |
|---|---|
| **Week 1** | Little or nothing |
| **Month 1** | Clusters begin to form around common questions |
| **Month 3** | Trends become meaningful |

---

# 13. Mobile

## 13.1 What is available

> **Note — there is no Blink Engage mobile app.** There is nothing to
> install from the App Store or Google Play.
>
> Blink Engage works in your phone's **web browser**. The interface adapts
> to small screens.

### Using it on a phone

1. Open your phone's browser.
2. Go to your company's Blink Engage address.
3. Sign in as usual.
4. Add it to your home screen for quick access:
   - **iPhone (Safari):** Share → Add to Home Screen
   - **Android (Chrome):** menu → Add to Home screen

`[Screenshot placeholder: Blink Engage Inbox on a phone screen]`

### What works well on a phone

- Reading and replying to conversations
- Picking up and transferring
- Internal notes
- Viewing customers
- Notifications

### What is harder on a phone

- Reports and dashboards — better on a larger screen
- Building workflows and routing rules
- Writing long knowledge articles
- Bulk work

> **Best Practice** — Use a phone for **responding** — answering a
> customer while away from your desk. Use a computer for **configuring**.

### Notifications on a phone

Browser push works if your administrator has configured push and you
allow notifications when your browser asks.

> **Warning** — Phone browsers are more aggressive than desktop about
> stopping background activity. Do not rely on a phone as your only way
> of being told about an urgent conversation.

### Troubleshooting

- **Layout looks wrong** — rotate to portrait, or refresh.
- **Notifications do not arrive** — check the browser allowed them, and
  that your administrator has configured push.
- **Signed out constantly** — private browsing mode clears the session.
  Use a normal window.

---

# 14. Troubleshooting

The problems teams actually hit, in the order they hit them.

## 14.1 Signing in

| Problem | Likely cause | Fix |
|---|---|---|
| "Invalid email or password" | Wrong address, wrong password | Confirm the exact Blink Engage address with your administrator, then use **Forgot password?** |
| No verification email | Spam folder, or email not configured | Check spam; ask your administrator to resend |
| Reset email never arrives | Notification email not set up | Ask your administrator to reset it directly |
| Signed out repeatedly | Private browsing, or the signing key was rotated | Use a normal window; sign in again |
| Can sign in but almost everything is missing | Account not verified, or a very narrow role | Verify the email; ask about your role |

## 14.2 Messages not arriving

**The single most common cause is a channel whose credentials were saved
but never tested.**

1. Open **Status**.
2. Find the channel.
3. If it is **unhealthy**, the token has almost certainly expired.
4. Reconnect with fresh credentials from the provider.
5. **Test connection** before saving.
6. Send yourself a test message.

| Problem | Likely cause |
|---|---|
| Nothing has ever arrived on this channel | Credentials wrong from the start; never tested |
| It worked and stopped | Token expired |
| Some arrive, some do not | Provider-side filtering, or unsupported message types |
| Arriving but delayed | Platform backlog — tell your administrator |

## 14.3 Replies not reaching customers

| Problem | Likely cause | Fix |
|---|---|---|
| Reply will not send | Channel unhealthy | Check **Status** |
| Sent but customer says nothing arrived | Provider rejected it | Check the conversation for an error; some channels restrict messaging outside a time window |
| Attachment rejected | Too large, or wrong type | Send a smaller file, or email it |
| Customer got an internal note | It was typed in the reply box | It cannot be recalled. Apologise and clarify |

> **Warning** — Messages delivered to WhatsApp, email or SMS **cannot be
> recalled**. The platform does not control the customer's device. Send a
> correction.

## 14.4 Conversations behaving unexpectedly

| Problem | Cause |
|---|---|
| Disappeared from "mine" | Ownership expired after inactivity; it returned to the queue |
| A resolved one came back | The customer replied, which reopens it |
| Cannot find one you saw earlier | A filter is still applied. Clear filters |
| Marked **Unrouted** | It reached no queue — routing configuration problem. Tell your administrator |
| Two agents replied | Neither picked it first |

## 14.5 SLA numbers look wrong

**Check business hours first. It is the cause the overwhelming majority
of the time.**

| Problem | Cause |
|---|---|
| Everything breaches overnight | Business hours never configured, so every hour counts |
| Times shifted by hours | Company timezone wrong |
| Targets missed constantly | Targets unrealistic for your staffing |
| A conversation shows no SLA | No policy applies to that service or queue |

## 14.6 AI problems

| Problem | Cause | Fix |
|---|---|---|
| No AI options anywhere | Plan lacks AI, or no provider configured | Ask your administrator |
| AI never replies on its own | Autopilot off, or confidence threshold too high | Check AI settings |
| AI answers wrongly | Knowledge base out of date | Fix the article |
| AI hands off constantly | Threshold too high, or knowledge too thin | Add knowledge first, then lower the threshold |
| AI replies in the wrong language | Company default language, or detection | Check AI and company settings |
| AI stopped mid-conversation | It was unsure, or the conversation hit SLA trouble | Take over — that is the design |

## 14.7 Notifications

| Problem | Cause |
|---|---|
| No emails | Notification email not configured |
| No push | Push not configured, or browser permission denied |
| Too many | Notification preferences too broad |
| Colleagues get them, you do not | Your own preferences, or your availability |

## 14.8 Performance

| Problem | Cause |
|---|---|
| Screens slow to load | Network, or a very large date range on a report |
| Search slow | Very broad search terms |
| Attachments slow to upload | File size, or connection |

If the whole platform is slow for everyone, tell your administrator —
they can see whether it is the platform or the network.

## 14.9 What to give whoever helps you

Three things turn an afternoon of guessing into a single lookup:

1. **When** it happened, as precisely as you can.
2. **Which conversation or customer** — a name or reference.
3. **What you expected** versus what happened.

> **Tip** — A screenshot showing the time is worth more than a paragraph
> of description.

---

# 15. FAQ

## Getting started

**1. What is Blink Engage in one sentence?**
One shared inbox for every channel your customers use, with routing,
response-time targets, reporting and an AI assistant around it.

**2. Do I need to install anything?**
No. It runs in a web browser.

**3. Which browsers work?**
Any current version of Chrome, Edge, Firefox or Safari.

**4. How do I get an account?**
An administrator invites you. You cannot create your own inside an
existing workspace.

**5. I clicked Register and got an empty workspace. What happened?**
You created a new company. Ask your administrator for a proper
invitation, and abandon the one you made.

**6. Why does my menu look different from my colleague's?**
Two invisible filters: your permissions, and what your company's plan
includes.

**7. How do I change my password?**
Profile → change password. You need your current one.

**8. I forgot my password.**
Use **Forgot password?** on the sign-in page. If no email arrives, ask
your administrator.

**9. Can I use Blink Engage in Arabic?**
Yes, including full right-to-left layout. Set it in your profile.

**10. Is there a dark mode?**
Yes, in your profile.

**11. How long do I stay signed in?**
Up to 30 days, unless you sign out or an administrator rotates the
signing key.

**12. Why was I signed out suddenly?**
Usually a key rotation by an administrator, which signs everyone out at
once.

## Conversations

**13. What is a conversation?**
One continuous discussion with one customer on one channel.

**14. What does "Pick" mean?**
It assigns the conversation to you and tells everyone you are handling
it.

**15. Do I have to pick before replying?**
You should. Without it, two agents can answer the same customer.

**16. A conversation vanished from "mine". Why?**
Ownership expires if untouched, so conversations are not stranded on
somebody who left for the day. Pick it up again.

**17. What is the difference between Resolve and Close?**
**Resolve** means dealt with, and may trigger a satisfaction survey.
**Close** ends it. Prefer Resolve.

**18. A resolved conversation reopened.**
The customer replied. That is intended — history stays in one place.

**19. Can I delete a conversation?**
No. Conversations are part of your record.

**20. Can I edit a message I sent?**
No. Messages delivered to a channel cannot be recalled. Send a
correction.

**21. What does "Unrouted" mean?**
The conversation reached no queue at all, so nobody is watching it. Tell
your administrator — routing is misconfigured.

**22. What are the conversation statuses?**
New, Waiting, In progress, Waiting on customer, Waiting on agent,
Resolved, Customer feedback, Closed.

**23. What does "Waiting on customer" affect?**
Time in that status is not held against your response time, because the
customer is the one who has not replied.

**24. What are the priorities?**
Low, Normal, High, Urgent.

**25. Should I set everything to Urgent?**
No. If everything is urgent, nothing is.

**26. How do I move a conversation to a colleague?**
**Transfer**, choosing a person, queue or department. Always write the
reason.

**27. Should I transfer to a person or a queue?**
A queue, unless you know the person is working. A conversation assigned
to someone on holiday waits for them.

**28. What is the difference between a reply and an internal note?**
A reply goes to the customer. A note is only seen by your team.

**29. Can a customer ever see internal notes?**
No — but they are permanent and auditable, so write them professionally.

**30. I typed a note in the reply box and sent it.**
It cannot be recalled. Apologise, clarify, and move on.

**31. Can I reply on a different channel from the one they used?**
No. Replies go back the way the customer came in.

**32. Why can I not find a conversation I saw this morning?**
A filter is almost certainly still applied. Clear filters.

**33. How do I search inside conversations?**
Use the search box at the top. Use words the customer actually typed.

**34. Can I search other companies' conversations?**
No. Search never crosses workspaces.

## Channels

**35. Which channels are supported?**
WhatsApp, Facebook Messenger, Instagram, Telegram, Email, SMS, Web Chat,
plus a plugin system for others.

**36. Can I connect my personal WhatsApp?**
No. You need WhatsApp Business API access via Meta.

**37. How long does WhatsApp approval take?**
It varies and is controlled by Meta, not by Blink Engage. Start early.

**38. Which channel is quickest to set up?**
Telegram, usually — a bot token and you are connected.

**39. A channel stopped working.**
Check **Status**. Almost always an expired token. Reconnect and test.

**40. Why did my channel never receive anything?**
Credentials were probably saved without testing. Reconnect and use
**Test connection**.

**41. How often is channel health checked?**
Every five minutes.

**42. Can one customer reach us on two channels?**
Yes. Those are two conversations linked to one customer record.

**43. Can I add a channel type that is not listed?**
There is a plugin system. Speak to your provider.

**44. Do I need a separate number for each channel?**
Each channel has its own requirements — WhatsApp and SMS need numbers,
web chat does not.

## Queues and routing

**45. What is a queue?**
A waiting line for conversations.

**46. How many queues should we have?**
Start with one. Add one when a distinct group of people handles a
distinct kind of work.

**47. What is a routing rule?**
A rule deciding which queue a conversation goes to.

**48. How are rules evaluated?**
By priority, highest first. The first match wins.

**49. What is the catch-all rule?**
A rule with no conditions at the lowest priority, created with your
workspace. It catches anything nothing else claimed.

**50. Can I delete the catch-all rule?**
You can, and you should not. Without it, unmatched conversations reach no
queue.

**51. Two rules have the same priority. Which wins?**
It is unpredictable. Give every rule a distinct priority.

**52. My rule never fires.**
A higher-priority rule is matching first, or your conditions are too
narrow.

**53. Everything goes to one queue.**
A rule's conditions are too broad, or only the catch-all matches.

**54. What is a Service, and how is it different from a queue?**
A queue is where conversations wait. A service is what you offer, and it
carries policy — SLA targets and AI settings attach to it.

## SLA

**55. What is an SLA?**
A promise about how quickly you respond and resolve.

**56. What are the four clocks?**
First response, next response, resolution, and idle.

**57. Do clocks run overnight?**
Not if business hours are configured. If they are not, yes — and that is
the most common configuration mistake in the product.

**58. Our SLA numbers look terrible. Where do I look first?**
Business hours. Then the company timezone.

**59. What is the difference between a warning and a breach?**
A warning is early notice. A breach means the target was missed.

**60. How early should the warning be?**
Early enough to act. A warning at 95% of the target tells you about a
problem you can no longer prevent.

**61. Can different queues have different targets?**
Yes. Policies apply to a service or a queue.

**62. What happens when a conversation breaches?**
It is badged in the Inbox, notifications fire, and AI autopilot stops.

**63. Does AI keep replying after a breach?**
No. Autopilot stops when a conversation is in SLA trouble.

## AI

**64. What can the AI do?**
Suggest replies, summarise, translate, detect language, judge sentiment,
suggest tags, improve grammar, rewrite professionally, propose a next
action, and search knowledge.

**65. Will the AI answer customers on its own?**
Only if autopilot is enabled and confidence clears your threshold.

**66. Does the AI send anything without me?**
Suggestions never. Autopilot replies do, when enabled and confident.

**67. What happens when the AI is unsure?**
It stops and marks **Handoff needed**. It does not guess.

**68. Where does the AI get its answers?**
Your knowledge base and FAQs.

**69. The AI gave a wrong answer.**
Check the article it drew from. The article is usually the problem.

**70. Does the AI learn from our conversations automatically?**
No. Improving it means improving your knowledge base.

**71. Can we run AI without sending data to OpenAI or Anthropic?**
Yes — Ollama runs locally. Ask your administrator.

**72. What is the confidence threshold?**
How sure the AI must be before answering. Higher is more cautious.

**73. Where should we set it initially?**
High. Lower it slowly while watching the AI report.

**74. The AI hands off everything.**
Threshold too high, or knowledge too thin. Add knowledge first.

**75. Can the AI see another company's data?**
No.

**76. Can the AI act — refunds, orders, records?**
No. It replies and suggests only.

**77. How much does AI cost?**
Provider charges are yours. Usage is metered per company and shown in
Billing.

**78. Can I turn AI off for one conversation?**
Yes — the autopilot control in the conversation.

## Knowledge base

**79. What is the difference between an article and an FAQ?**
An article is reference material the AI paraphrases. An FAQ is a question
and its exact answer, written to be shown.

**80. Which should I use for a carefully worded policy?**
An FAQ. Articles may be paraphrased; FAQs are quoted.

**81. Why is my new FAQ not appearing?**
Either it is still unpublished — new FAQs start that way deliberately —
or it was never created, because there is no FAQ screen in this release.
Ask whoever maintains your knowledge base.

**82. What happens when I unpublish an FAQ?**
It is hidden and removed from search, so nothing can quote it.

**83. Can I see previous versions of an article?**
No. Version history does not exist in this release. Editing replaces the
content.

**84. Can I restore an article I overwrote?**
No. Keep significant rewrites in a document outside Blink Engage first.

**85. What is a quick reply?**
Saved text an agent inserts and edits before sending. There is no screen
for managing the list in this release — ask your provider to add one.

**86. How does knowledge search work?**
It understands meaning, so "cannot log in" finds "reset your password".

**87. How should I title articles?**
As the question a customer would ask. Pass this to whoever maintains your
knowledge base — there is no editor in the interface yet.

**88. How often should we review knowledge?**
Anything with a price, date or policy — quarterly at least.

## Customers

**89. What is on a customer record?**
Contact details, tags, custom fields, internal rating, notes, full
conversation timeline, and ERP data if connected.

**90. Are conversations from different channels merged?**
Onto one customer record, yes, when the platform can tell it is the same
person.

**91. Two records exist for one person.**
They used different details. Update the records so they match.

**92. Can I tag a conversation?**
No. Tags are on customers in this release.

**93. Can customers see their tags, ratings or notes?**
No. All are internal — and all are permanent and auditable.

**94. Can we delete a customer's data on request?**
Customer records can be erased. Speak to your administrator — it has
legal consequences.

## Workflows and automation

**95. What is a workflow?**
When something happens, if conditions are met, do something. There is no
workflow builder in the interface in this release — your provider
configures them for you.

**96. Can a workflow send a message to a customer?**
It can notify and act on the conversation. Design carefully — automated
messages reach real people.

**97. My workflow did not run.**
Check it is Active, then check the conditions match your test.

**98. My workflow runs too often.**
Its conditions are too broad.

**99. How do I test a workflow safely?**
Ask whoever configured it to leave it inactive first, then send a test
message that should match — and one that should not. There is no
workflow screen for you to do this yourself in this release.

**100. Can two workflows conflict?**
Yes. Two workflows acting on the same event can fight. Keep them
narrow and distinct.

**101. Is there an escalation feature?**
Not a separate screen. Build escalation from an SLA breach trigger plus a
workflow that notifies and moves the conversation.

## Reports

**102. Which reports exist?**
Executive, Agent, Live, Conversations, Performance, Queues, SLA, CSAT,
AI, and AI usage.

**103. Can I export?**
Yes, if your plan includes Report Export.

**104. Are reports real-time?**
The Live dashboard is near-real-time. Others are built from aggregates
refreshed hourly.

**105. My report is empty.**
Check the date range and filters.

**106. Numbers look wrong by a few hours.**
Check the company timezone.

**107. Should I judge agents on conversation volume?**
No. It rewards fast, shallow answers. Look at satisfaction and
resolution too.

## Administration

**108. What is the minimum setup to go live?**
Connect one channel. Everything else has a working default.

**109. What do we get automatically?**
Default roles, a General queue, a catch-all routing rule and a General
service.

**110. Do we need departments and teams?**
No. Create them when you can name the work they own.

**111. Should I delete or deactivate someone who leaves?**
Deactivate. It preserves history and stops sign-in.

**112. Can I set a user's password?**
No. You trigger a reset; they choose it.

**113. Can we import existing customers?**
Not through a bulk import screen. ERP sync brings them in if you use
ERPNext.

**114. Can I generate an API key?**
Not in this release. There is no API key screen.

**114a. Which screens do not exist yet?**
Knowledge, FAQs, quick replies, workflows and API keys have no interface
in this release. The capabilities exist in the platform and are
configured by your provider.

**115. Can Blink Engage push data to another system?**
Yes, through a workflow webhook action.

**116. Where do I set business hours?**
Settings → Business hours. Holidays are separate.

**117. Can I change the timezone later?**
Yes, but it does not correct reports already produced.

## Security and data

**118. Can another company see our data?**
No. Separation is enforced on every request.

**119. Where are channel credentials stored?**
Encrypted where they are stored.

**120. Is there an audit trail?**
Yes — every significant action, permanently, never deleted.

**121. Is Blink Engage GDPR or HIPAA compliant?**
The platform provides the technical controls — separation, encryption,
audit trail, erasure, access control. Compliance is a property of your
whole operation, and no certification is claimed.

**122. How long is data kept?**
Business data indefinitely by default. Audit logs are never deleted.

**123. Are backups taken?**
Yes, by your administrator, on a schedule, including your files and
configuration.

## Mobile

**124. Is there a mobile app?**
No. Blink Engage runs in your phone's browser.

**125. Can I add it to my home screen?**
Yes — Share → Add to Home Screen on iPhone, or the browser menu on
Android.

**126. Do notifications work on a phone?**
Browser push works if configured and permitted. Do not rely on it as the
only way of being told about something urgent.

**127. What is harder on a phone?**
Reports, workflow building, and writing long articles.

## Intelligence and Learning

**128. What does the Intelligence screen show?**
Clusters of similar conversations, trends, anomalies and metrics.

**129. Does Learning change what the AI says?**
No. It only observes in this release.

**130. Will it write knowledge articles for us?**
No. It shows you what customers keep asking; you write the answer.

**131. Our Intelligence screen is empty.**
Expected on a new or low-volume workspace. It needs many conversations.

**132. How long before trends mean anything?**
Several weeks of consistent traffic.

**133. Does Learning use other companies' data?**
No, never.

## Still stuck

**134. Something is broken — what do I send?**
When it happened, which conversation or customer, and what you expected
versus what happened.

**135. Where do I start troubleshooting?**
[§14 Troubleshooting](#14-troubleshooting) — problems are grouped by
symptom.

---

## Document information

| | |
|---|---|
| **Guide version** | 1.0 |
| **Applies to** | Blink Engage `v1.2.0` |
| **Audience** | Agents, supervisors, administrators |

### Related documents

- [Administrator Guide](./administrator-guide.md) — configuration reference
- [User Guide (short)](./user-guide.md) — condensed version of this manual
- [Quick FAQ](./faq.md) — technical and operational questions

### Features referenced as unavailable

For clarity, these are named in this guide as **not available in this
release**, so nobody spends time looking for them:

| Feature | Section |
|---|---|
| Conversation tags | [§4.5](#45-tags) |
| **A Knowledge screen** (articles, FAQs, quick replies) | [§6](#6-knowledge-base) |
| Knowledge version history | [§6.7](#67-drafts-and-version-history) |
| **A Workflows screen** (builder, testing, activation) | [§7](#7-workflows) |
| API key management | [§11.4](#114-api-keys) |
| A dedicated escalation screen | [§8.3](#83-escalations) |
| A native mobile application | [§13](#13-mobile) |
| Learning acting on what it observes | [§12.3](#123-current-limitations) |
