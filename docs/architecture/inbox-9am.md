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

The three questions are answered in order down the left, and the answer to
"which one" opens beside them rather than instead of them.

```
┌─ Conversations ─────────────┬─ The open conversation ───────────────────┐
│ Inbox        41 active 4 br.│ Mona Haddad  💬          [Pick up] [⋯] (i)│
│ 🚨 Needs attention (7) 📥…  │ Waiting for pickup · 🔴 Breached          │
│ Waiting on us, running out. │ Owner    Waiting  Last msg  Opened  Queue │
├─────────────────────────────│ Nobody   42m      3m ago    2h ago  Supp. │
│▎Mona Haddad         [Pick]  ├───────────────────────────────────────────┤
│ Waiting for pickup 🔴 42m   │ Messages | Internal notes | Transfers     │
│ AI stood down                │                                          │
├─────────────────────────────┤   … the thread …                          │
│ Karim Nasser        [Pick]  │                                           │
│ Waiting for pickup  8m      ├───────────────────────────────────────────┤
│ Routed to "Support"         │ 📎 ⚡ ✨ [ Write a reply, or / … ]      ➤ │
└─────────────────────────────┴───────────────────────────────────────────┘
```

The summary is read once a morning. The queues are chosen a few times a day.
The rows are read constantly. Prominence follows *how much a thing changes a
decision*, not how often it is looked at — which is why the summary is now one
line rather than a band of seven figures. Those figures were not wrong, they
were *duplicated*: every one of them also appears inside its own queue chip
immediately below. Two of them answer something the chips do not — how much
there is in total, and how much has already failed — so those two stayed.

## Why the conversation is a pane and not a page

Opening a conversation used to replace this screen entirely. An agent working
a queue therefore did list → conversation → Back → list → conversation,
losing their place in the list on every single one and paying a page load for
each. The queue they had chosen — the desk they sat at — did not survive the
round trip either.

Both are on screen at once now. The list keeps its scroll position and marks
the row being read; the URL still carries the open conversation, so a link to
one still opens it, and the list simply comes with it.

Below `md` there is no room for both without making each unusable, so it
degrades to one at a time with a back arrow. That is the only place the old
navigation survives, and it is the only place it was ever right.

## The strip above the thread

An agent needs five things before typing a word: who this is, what it is
waiting on, whether it is late, who owns it, and *how long it has been like
that*. Every one of them used to be behind a `⋮` menu that opened a drawer —
along with **Pick up**, the single most common action on the screen.

They are a permanent strip now. The durations tick (`useNow`), because a
duration rendered once and left alone is not stale, it is wrong: "Waiting 4m"
still reading 4m twenty minutes later is a figure somebody makes a decision
on.

The split between the strip and the drawer is *replying versus re-filing*.
Ownership — Pick up, Ask AI, Take over, Transfer, Release — is replying, and
lives in the strip. Status and queue are re-filing, and stay one click away.
Neither set appears in both places: the same button in two locations is how a
screen stops being trustworthy.

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
| Pick up, on a row | **Added** — an agent working a pickup queue claims several in a row, and routing each through the conversation is the slow path |
| Saved replies | **Added to the composer** — approved wording existed in the database with no way to reach it from the one screen that uses it |

## The test of success

An agent who has to scan rows to learn their workload has been failed by the
screen, not by their own attention. If that is still true after this, the
answer is to remove more, not to arrange it better.
