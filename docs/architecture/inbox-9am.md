# The 9:00 AM exercise

An experienced agent opens Blink Engage. Their first question is never *which
conversation should I open* — it is **what does my day look like**. This
document walks that moment, and every layout decision in the Inbox answers
back to it.

## The three seconds

**Second one — what is happening today?**

They read one line of numbers and stop. *Four breached. Eleven waiting for
pickup. Six mine. AI has nine.* They now know the shape of the day without
having opened anything, and — more importantly — they know whether today is
normal. A morning with four breached is a different morning from one with
none, and that difference has to arrive before any conversation does.

**Second two — what requires me now?**

Their eye moves to the work queues. Not to choose a filter: to choose *what
kind of work they are doing for the next twenty minutes*. Clearing breaches is
a different activity from picking up a queue, and an agent who has decided
which one they are doing reads the list differently.

**Second three — which one?**

Only now do rows matter. And by this point the agent is not scanning for work
— they have already decided what work they are doing, and are choosing the
next item within it.

The old Inbox collapsed all three into one: a table, and the instruction
*figure it out*.

## What this means for the page

Three layers, in this order, and the order is not negotiable because it is the
order of the questions.

```
┌─ Operational summary ──────────────────────────────────────┐
│  Active 41 · Needs attention 7 · Waiting pickup 11         │
│  AI working 9 · Waiting customer 8 · At risk 3 · Breached 4│
└────────────────────────────────────────────────────────────┘
┌─ Work queues ──────────────────────────────────────────────┐
│  🚨 Needs attention  📥 Waiting pickup  👤 Mine  🤖 AI ...  │
└────────────────────────────────────────────────────────────┘
┌─ Conversations ────────────────────────────────────────────┐
│  Mona Haddad                                                │
│  Waiting for pickup · 🔴 Breached · Support queue · 42m     │
│  AI stood down — an agent took it                           │
│  "I still haven't had a refund"              💬             │
└────────────────────────────────────────────────────────────┘
```

The summary is read once a morning. The queues are chosen a few times a day.
The rows are read constantly. Prominence follows *how much a thing changes a
decision*, not how often it is looked at.

## The row, in the order it communicates

1. **Customer** — who
2. **Operational state** — why this is here
3. **SLA health** — how urgent
4. **Owner** — who is answerable
5. **Duration** — how long it has been like this
6. **Last meaningful event** — what most recently changed
7. **Last message** — what the customer said
8. **Channel** — a mark, nothing more

The last message is seventh of eight. That is the whole reframing: an agent
should understand *why a conversation is in front of them* before reading a
word of its content. A row that opens with message text is a row that makes
them read to decide.

Channel is last because it almost never changes what somebody does first.

## Why queues, not filters

A filter asks *how do you want the data narrowed*. That requires knowing the
data model before you can ask a question, and it puts the burden of framing on
the person least able to carry it at 9am.

A queue asks *what work are you doing*. Switching from **Waiting pickup** to
**Breached** should feel like moving from one desk to another — different
work, different mindset — not like editing a query.

Practically: queues are the primary navigation, they carry their counts, and
the count is part of the label. `Breached (4)` answers a question before it is
clicked; `Breached` invites a click to find out.

A queue with nothing in it is shown, greyed, with its zero. *Breached (0)* is
one of the most valuable things the screen can say, and hiding empty queues
would remove exactly the reassurance a morning needs.

## What earns its place

Every element must reduce decision time. Applying that honestly removes
things that look reasonable:

| Element | Verdict |
|---|---|
| Operational state | **Stays** — the answer to "why is this here" |
| SLA health | **Stays** — the only thing that says "running out of time" |
| Owner | **Stays** — "is this mine to move" |
| Duration | **Stays** — turns a state into a judgement |
| Customer name | **Stays** — how a person refers to the work |
| Last meaningful event | **Stays** — what changed since they last looked |
| Last message | **Demoted** — context, once the decision is made |
| Channel | **Demoted to a mark** — rarely changes what to do first |
| Priority | **Only when not normal** — a badge on every row is a badge on none |
| Status chip | **Removed** — the operational state says it better |
| Avatar colours | **Removed** — decorative; nine colours that mean nothing |
| Pagination | **Demoted** — the list is ordered worst-first; page two is where conversations go to be forgotten |

## The test of success

An agent who has to scan rows to learn their workload has been failed by the
screen, not by their own attention. If that is still true after this, the
answer is to remove more, not to arrange it better.
