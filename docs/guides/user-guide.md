# User Guide

**How to use Blink Engage, feature by feature.**

Written for the people who use the platform daily — agents, supervisors
and the administrators who set it up. It is task-oriented: each section
answers *how do I do this*, not *how is this implemented*.

- For what a feature **is** and how it works internally, see [SYSTEM.md](../SYSTEM.md).
- For **configuration**, see the [Administrator Guide](./administrator-guide.md).
- For quick answers, see the [FAQ](./faq.md).

---

## Contents

1. [Signing in](#1-signing-in)
2. [Finding your way around](#2-finding-your-way-around)
3. [The Inbox](#3-the-inbox)
4. [Handling a conversation](#4-handling-a-conversation)
5. [Using AI](#5-using-ai)
6. [Knowledge, FAQs and quick replies](#6-knowledge-faqs-and-quick-replies)
7. [Customers](#7-customers)
8. [Queues and assignment](#8-queues-and-assignment)
9. [SLA](#9-sla)
10. [Reports](#10-reports)
11. [Intelligence](#11-intelligence)
12. [Notifications](#12-notifications)
13. [Your profile](#13-your-profile)

---

## 1. Signing in

Go to your company's Blink Engage address and sign in with your email and
password.

**First time?** You will have received a verification email. Verify
before signing in — an unverified account can authenticate but is
restricted.

**Forgot your password?** Use the link on the sign-in page. If your
company's email is not configured yet, an administrator resets it for you
from **Agents**.

**Signed out unexpectedly?** Sessions last 30 days, but an administrator
rotating the signing key ends every session immediately. Sign in again.

## 2. Finding your way around

The left menu shows only what you have permission to see, and only what
your company has enabled — so your menu may be shorter than a colleague's.
That is not a fault.

| Menu item | What it is for |
|---|---|
| **Dashboard** | Today at a glance |
| **Inbox** | Your conversations — where you spend the day |
| **Customers** | Who you have talked to, and their history |
| **Agents** | The people in your workspace |
| **Departments** | Organisational grouping |
| **Channels** | WhatsApp, email, web chat and the rest |
| **Status** | Whether each channel is currently healthy |
| **Services** | What your company offers, and the policy attached |
| **Queues** | Where conversations wait to be picked up |
| **Roles** | Who may do what |
| **SLA** | Response and resolution targets |
| **Intelligence** | What the platform has noticed across conversations |
| **Reports** | Performance, volume, satisfaction |
| **Billing** | Usage and invoices |
| **ERPNext** | ERP synchronisation, if enabled |
| **Settings** | Company-wide configuration |

> The menu is currently a flat list of up to seventeen items. A grouped
> layout is specified in
> [navigation-information-architecture.md](../architecture/navigation-information-architecture.md)
> but not yet implemented.

## 3. The Inbox

The Inbox is the working screen. Conversations arrive from every channel
and appear in one list.

### Views

Filter by state — unassigned, mine, all open, resolved, closed — and by
queue, channel or customer. Views persist as you move around.

### What the badges mean

| Badge | Meaning |
|---|---|
| **Unassigned** | Nobody has picked it up |
| **SLA warning** | Approaching the response or resolution target |
| **SLA breached** | The target was missed |
| **AI handled** | The AI replied without an agent |
| **Handoff needed** | The AI stopped and wants a human |
| **Unrouted** ⚠️ | It reached no queue — tell an administrator |

**Unrouted is the one to escalate.** Everything else is a normal working
state; unrouted means routing configuration is wrong and the conversation
is somewhere nobody is looking.

### Picking up work

Click a conversation to open it. **Pick** assigns it to you.

Ownership expires if you leave a conversation untouched — it returns to
the queue so it is not stranded on somebody who went home. Reply, or pick
it up again, to keep it.

## 4. Handling a conversation

### Replying

Type and send. The reply goes back over the channel the customer used —
you do not choose WhatsApp or email; the conversation already knows.

Formatting support varies by channel. What a channel cannot represent is
degraded, not dropped.

### Internal notes

Switch to **Note** to write something only colleagues see. Notes are
never delivered to the customer.

> Use notes for anything you would not want read aloud to the customer.
> They are internal, but they are permanent and auditable.

### Attachments

Attach with the paperclip. Type and size limits are enforced; a rejected
file tells you why. Images preview inline; audio and video stream without
downloading in full.

### Transferring

**Transfer** moves a conversation to another agent, queue or department.
Add a note explaining why — the next person inherits the conversation,
not your reasoning.

### Resolving and closing

**Resolve** marks it dealt with. This may trigger a satisfaction survey.

**Close** ends it. A customer replying to a resolved conversation
**reopens** it rather than starting a new one, so context is not lost.

## 5. Using AI

Available if your company has the AI feature enabled and configured.

### Autopilot

The AI can answer on its own when your company has allowed it, the
conversation qualifies, and confidence is high enough. You will see
**AI handled** on those conversations.

When the AI is unsure, it stops and marks **handoff needed** rather than
guessing. It also stops automatically when a conversation is in SLA
trouble — the assumption being that a struggling conversation needs a
person.

### Assisting you

In an open conversation, the AI can:

| Action | What it does |
|---|---|
| **Suggest reply** | Drafts a response from context and your knowledge base |
| **Summarise** | Condenses a long thread |
| **Translate** | Between supported languages |
| **Improve grammar** | Corrects without changing meaning |
| **Rewrite professionally** | Adjusts tone |
| **Next best action** | Suggests what to do next |
| **Search knowledge** | Finds relevant articles and FAQs |

**Everything is a suggestion.** Nothing is sent without you sending it.
Read before you send — the AI is drawing on your knowledge base, and if
that is wrong or out of date, so is the suggestion.

## 6. Knowledge, FAQs and quick replies

Three different things, often confused:

| | Audience | Used by | Purpose |
|---|---|---|---|
| **Knowledge article** | Internal by default | AI and agents | Reference material, in your own words |
| **FAQ** | Written to be shown to customers | AI, search | A question and its answer |
| **Quick reply** | Internal shortcut | Agents | Canned text you send often |

### Knowledge articles

Longer reference documents. The AI uses them as raw material and puts
answers in its own words.

### FAQs

A question and its answer, in the order you want customers to read them.
**A new FAQ starts unpublished** — publishing is a decision, because
unlike an article this is written to be shown to customers. Unpublishing
removes it from search too, so nothing can quote something you took down.

### Quick replies

Type the shortcut, get the text, edit before sending. For the sentences
you write twenty times a day.

### Search

Search understands meaning, not just wording — a customer using different
words to describe the same thing still finds the right answer.

## 7. Customers

**Customers** lists everyone who has contacted you, merged across
channels where the platform can tell it is the same person.

A customer record shows contact details, conversation history across all
channels, internal ratings, activity, and ERP data if ERP is enabled.

**Internal ratings** are your team's private note on a customer. They are
never shown to the customer, and they are auditable.

## 8. Queues and assignment

A **queue** is where conversations wait. Routing rules decide which queue
a conversation lands in, based on channel, keywords, language or
customer attributes.

Your workspace starts with a **General** queue and a catch-all rule, so
nothing can arrive with nowhere to go. Administrators add more specific
rules above it as needed.

Conversations are assigned from a queue to an agent by the assignment
engine, respecting availability, capacity and skills.

**Set yourself available or away** from your profile. Away removes you
from automatic assignment; conversations already yours stay yours.

## 9. SLA

An SLA sets targets for how quickly conversations are answered and
resolved. Four clocks:

| Clock | Measures |
|---|---|
| **First response** | Customer's first message → your first reply |
| **Next response** | Each subsequent customer message → your reply |
| **Resolution** | Conversation opened → resolved |
| **Idle** | Time since anyone said anything |

Clocks respect **business hours** — a message at 22:00 does not burn
overnight against your target, provided business hours are configured.
This is the most common source of "SLA looks wrong": if business hours
were never set, everything counts as working time.

You will see a **warning** before a breach and a **breach** badge after.
Both are visible in the Inbox and in Reports.

## 10. Reports

| Report | Answers |
|---|---|
| **Executive** | How is the operation doing overall |
| **Agent** | How is each agent performing |
| **Live** | What is happening right now |
| **Conversations** | Volume, channel mix, resolution |
| **Performance** | Response and resolution times |
| **Queues** | Where work waits and for how long |
| **SLA** | Attainment and breaches |
| **Satisfaction** | CSAT results |
| **AI** | How much the AI handled, and how well |

Export to PDF or Excel if your plan includes Report Export.

## 11. Intelligence

The intelligence layer reads resolved conversations and reports patterns:
clusters of similar conversations, trends over time, and anomalies.

**It only observes.** In this release it writes nothing back — it does not
create knowledge articles, modify memory, or change how conversations are
handled. Treat it as a report on what your customers keep asking about.

## 12. Notifications

You are notified when a conversation is assigned to you, transferred to
you, breaches SLA, or the AI hands one off.

Email and push are delivered if your administrator has configured them.
Push requires registering your device, which happens automatically on
sign-in where supported.

## 13. Your profile

From your avatar: change your password, set your language (English or
Arabic, including right-to-left layout), choose light or dark theme, set
availability, and manage notification preferences.

---

## Getting help

1. Check the [FAQ](./faq.md).
2. Ask your administrator — most issues are configuration.
3. If something looks broken rather than misconfigured, give your
   administrator the **time** and the **conversation id**. Every request
   carries a correlation id, and those two facts let an operator find
   exactly what happened.

## See also

- [Administrator Guide](./administrator-guide.md) — configuring all of the above
- [FAQ](./faq.md)
- [SYSTEM.md](../SYSTEM.md) — what each feature is and how it works
