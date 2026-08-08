# First-Run Product Tour

**The guided introduction a new user sees the first time they sign in.**

- **Source of truth:** [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **IDs:** [help-ids.md](./help-ids.md)

---

## Principles

| Principle | Why |
|---|---|
| **Two tours, not one** | An administrator setting up and an agent answering customers need completely different things |
| **Short** | Six steps for agents, seven for administrators. Anything longer is skipped |
| **Skippable at every step** | A tour that traps someone is worse than no tour |
| **Point at real screens** | Never a video or an illustration of a screen that is not in front of them |
| **Resumable** | Closing it does not mean losing it |
| **Never block work** | If a real conversation arrives mid-tour, the conversation wins |

> **The one thing the tour must achieve:** the user knows what to do next
> when it ends. Everything else is secondary.

## Which tour to show

```
first sign-in
     │
     ├── can manage the company?  ──►  Administrator tour  (7 steps)
     │
     └── otherwise                ──►  Agent tour          (6 steps)
```

Decide from permissions, not from the role name — custom roles will not
be called "Administrator".

---

# Agent tour

For people who answer customers. Six steps, about 90 seconds.

### Step 1 — Welcome

**Anchor:** centre of the screen
**help_id:** `be.onboarding.tour`

> **Welcome to Blink Engage**
>
> This is where you will answer your customers. Ninety seconds and you
> will know your way around.
>
> **[Show me]** · [Skip]

### Step 2 — The Inbox

**Anchor:** Inbox in the left menu · **help_id:** `be.inbox.list`

> **Everything arrives here**
>
> WhatsApp, email, web chat — every channel lands in this one list. You
> will spend most of your day on this screen.
>
> **[Next]** · [Skip]

### Step 3 — Picking up work

**Anchor:** the Pick button · **help_id:** `be.feature.pick`

> **Take a conversation before replying**
>
> **Pick** puts your name on it, so two people do not answer the same
> customer.
>
> **[Next]** · [Skip]

### Step 4 — Reply or note

**Anchor:** the message box · **help_id:** `be.feature.internal_note`

> **Two kinds of message**
>
> **Reply** goes to the customer. **Note** is only seen by your team.
>
> Check which one you are in before typing — a note sent to a customer
> cannot be taken back.
>
> **[Next]** · [Skip]

### Step 5 — Response targets

**Anchor:** an SLA badge · **help_id:** `be.feature.sla_clocks`

> **These badges tell you what is urgent**
>
> **At risk** means a conversation is close to missing its response
> target. Deal with those before new arrivals.
>
> **[Next]** · [Skip]

### Step 6 — Finish

**Anchor:** the help button

> **That is everything you need to start**
>
> The help button is here whenever you want it, and it always explains
> the screen you are on.
>
> **[Go to my Inbox]**

**On completion:** land on the Inbox filtered to unassigned, so there is
something to do.

---

# Administrator tour

For whoever is setting up the workspace. Seven steps, about two minutes.

### Step 1 — Welcome

> **Let's get your workspace ready**
>
> A few things to set up, and one that genuinely matters more than the
> rest. Two minutes.
>
> **[Show me]** · [Skip]

### Step 2 — What you already have

**help_id:** `be.feature.catch_all`

> **Some of this is already done**
>
> Your workspace was created with a **General queue**, a **General
> service**, and a **catch-all routing rule** — so no message can ever
> arrive with nowhere to go.
>
> You do not need to build routing to get started.
>
> **[Next]** · [Skip]

> **Why this step exists:** without it, new administrators build routing
> they already have, or worry they are missing something. It is the
> cheapest support ticket to prevent.

### Step 3 — Set your timezone

**Anchor:** Settings → Company · **help_id:** `be.settings.company.timezone`

> **Set your timezone first**
>
> Every time in the product depends on it — response targets, reports,
> schedules.
>
> Changing it later does not correct reports already produced, so it is
> worth doing now.
>
> **[Open settings]** · [Next] · [Skip]

### Step 4 — Business hours

**Anchor:** Settings → Business hours · **help_id:** `be.feature.business_hours`

> **Tell us when you work**
>
> Response-time clocks pause outside your working hours, so an evening
> message does not count against you overnight.
>
> **Teams that skip this step report that their SLA numbers look wrong.**
> It is the most common configuration mistake in the product.
>
> **[Set business hours]** · [Next] · [Skip]

### Step 5 — Connect a channel

**Anchor:** Channels · **help_id:** `be.channels.list`

> **This is the one that matters**
>
> A channel is how customers reach you. **Until you connect one, nobody
> can contact you at all.**
>
> Telegram is the quickest if you want to try it today. WhatsApp needs
> approval from Meta, so start that early.
>
> **[Connect a channel]** · [Next] · [Skip]

> **This step should be visually distinct** — it is the only genuinely
> blocking one.

### Step 6 — Test before you trust it

**Anchor:** the Test connection button · **help_id:** `be.channels.connect.test`

> **Always test the connection**
>
> Saved is not the same as working. One mistyped character in a token
> looks perfectly saved and silently receives nothing.
>
> Test takes two seconds and prevents the most expensive setup mistake
> there is.
>
> **[Next]** · [Skip]

### Step 7 — Invite your team

**Anchor:** Agents · **help_id:** `be.workspace.agents`

> **Bring your team in**
>
> Invite the people who will answer customers. They set their own
> passwords.
>
> A one-person workspace works perfectly well too — invite people when
> you need them.
>
> **[Invite someone]** · [Finish]

**On completion:** show a setup summary.

---

## Completion summary

Shown at the end of the administrator tour, and from the setup wizard.

> **Your workspace so far**
>
> ✅ Company name and timezone
> ✅ Business hours
> ✅ Routing — General queue, catch-all rule, General service
> ⬜ **Channel — not connected**
> ⬜ Team — nobody invited yet
> ⬜ AI — not configured
>
> **Customers cannot reach you until a channel is connected.**
>
> **[Connect a channel]** · [I'll do it later]

Ticks and blanks are derived from what is actually configured, never from
which tour steps were viewed. A step somebody clicked through without
doing must not show as done.

---

## Behaviour

| Situation | What happens |
|---|---|
| User selects Skip | Tour closes, does not reappear automatically |
| User closes the browser mid-tour | Resumes at the same step next sign-in |
| A real conversation arrives | Tour pauses; the conversation takes priority |
| User has already configured a step | Skip it — do not tell somebody to do what they have done |
| Screen is too narrow | Show a single welcome card, not anchored bubbles |
| User wants it again | Available from the help menu as **Take the tour** |

## Re-entry points

| Trigger | Tour |
|---|---|
| First sign-in | Full tour for their role |
| Help menu → Take the tour | Full tour, on request |
| Empty Channels screen | Just the channel steps |
| First time opening a conversation | Just the reply/note step |

Short contextual tours are more useful than one long tour. Somebody who
skipped the introduction still benefits from three bubbles at the moment
they open Channels for the first time.

## Writing rules

| Rule | Reason |
|---|---|
| One idea per step | Two ideas means one is forgotten |
| Under 40 words | Longer and it is not read |
| Say what to do, not what exists | "Take a conversation before replying" beats "This is the Pick button" |
| Warn where it prevents pain | The business-hours and test-connection steps exist because of real support volume |
| Never say "simply" or "just" | If it were simple there would be no tour |

## Accessibility

- Keyboard navigable throughout; **Escape** closes.
- Focus moves to each bubble as it appears, and returns sensibly on
  close.
- Mirrors correctly in Arabic, including anchor positions.
- Never traps focus — a user must always be able to leave.

---

## See also

- [Context help](./context-help.md)
- [Empty states](./empty-states.md)
- [Onboarding wizard specification](../product/tenant-onboarding-wizard.md)
- [User Guide §2 Getting Started](../guides/blink-engage-user-guide.md#2-getting-started)
