# Blink Engage Help Center

**The content set that powers in-product help.**

Seven documents. Together they specify everything a user reads inside the
product without leaving it: the help panel, field tooltips, empty
screens, error messages, the first-run tour, and what help search finds.

- **Source of truth for all content:**
  [blink-engage-user-guide.md](../guides/blink-engage-user-guide.md)
- **Nothing here is implementation.** These are the words. How they are
  delivered is a separate decision.

---

## The documents

| Document | Contains | Entries |
|---|---|---|
| [help-ids.md](./help-ids.md) | Permanent identifiers for every screen and feature | 89 |
| [context-help.md](./context-help.md) | What the help panel shows on each screen | 22 |
| [tooltips.md](./tooltips.md) | One-line help for individual fields | 88 |
| [empty-states.md](./empty-states.md) | What each screen says when it has nothing to show | 30 |
| [error-messages.md](./error-messages.md) | Every user-facing error, in plain English | 47 |
| [product-tour.md](./product-tour.md) | The guided first-run introduction | 2 tours, 13 steps |
| [search-index.md](./search-index.md) | Keywords and aliases so search finds things | 70+ features |

## How they fit together

```
                        help-ids.md
                   (the permanent index)
                             │
        ┌──────────┬─────────┼─────────┬──────────┐
        ▼          ▼         ▼         ▼          ▼
   context-help  tooltips  empty-   error-    search-
   (per screen)  (per      states   messages  index
                  field)   (per     (per      (per
                           screen)  failure)  feature)
                             │
                             ▼
                       product-tour
                   (first-run sequence)
```

**`help_id` is the join.** Everything keys off it, which is why it must
never be renamed or reused.

## Reading order

**Building the help system:** start with `help-ids.md`. Everything else
is content hung off those identifiers.

**Writing new content:** find the `help_id` first. If it does not exist,
register it before writing.

**Adding a feature:** it needs an id, a context-help entry, tooltips for
its fields, an empty state, and search aliases. Any one missing leaves a
user stuck somewhere.

---

## Principles

These are the rules that produced the content, kept here so the next
person writing an entry matches it.

**Say what to do, not what things are called.**
"Take a conversation before replying" beats "This is the Pick button".

**Never blame the user.**
"You entered an invalid value" → "That date is in the past."

**Distinguish "you cannot" from "not configured".**
A permission problem and a plan problem look identical to a user and need
completely different actions. Always say which.

**Empty and filtered are different.**
"No conversations yet" and "no conversations match these filters" send
the user in opposite directions. Getting this wrong sends someone off to
create something they already have.

**Explain absence rather than hiding it.**
Six things people look for do not exist yet. Each returns an explanation
and who to ask, not a dead link.

**Preserve what the user typed.**
An error that discards a long reply turns an annoyance into a complaint.

**Show a reference on server errors.**
The correlation id turns an afternoon of searching into a single lookup.

---

## What does not exist yet

Named consistently across every document, because a user who searches for
one of these deserves an answer rather than silence:

| Feature | What help says |
|---|---|
| Knowledge screen (articles, FAQs, quick replies) | Knowledge is real and powers AI answers; there is no editor. Ask your provider |
| Workflows screen | The engine exists; there is no builder. Ask your provider |
| API keys | Not available. Speak to your provider |
| Knowledge version history | Editing replaces content permanently |
| Conversation tags | Tags are on customers, not conversations |
| Mobile app | Responsive web only |
| Learning acting on findings | It observes and reports; it does not act |

> These were verified against the running product, not assumed from the
> documentation. Three of them — the Knowledge screen, the Workflows
> screen and API keys — have working APIs and no interface, which is
> exactly the kind of gap a help system must be honest about.

---

## Coverage summary

| | |
|---|---|
| Screens with context help | 22 |
| Fields with tooltips | 88 |
| Empty states | 30 |
| Error messages | 47 |
| Tour steps | 13 across 2 tours |
| Registered help IDs | 89 |
| **Total help entries** | **~289** |

Every domain error type the platform maps to an HTTP status has a plain-
English message. Every screen in the navigation has a context-help entry.

## If only part of this is built

In priority order, by support tickets prevented:

1. **Error messages** — users meet these at their worst moment.
2. **The five critical tooltips** — test connection, business hours,
   internal note, catch-all rule, timezone.
3. **The three critical empty states** — no channels, missing catch-all,
   empty Intelligence.
4. **Symptom searches** — the sixteen queries in
   [search-index.md](./search-index.md#searches-that-must-return-an-answer).
5. **The administrator tour** — mostly it prevents the same problems
   earlier.
6. Everything else.

---

## Maintaining this

| When you… | Do this |
|---|---|
| Add a screen | Register an id, write context help, add search aliases |
| Add a field | Add a tooltip |
| Add an error | Add a plain-English message |
| Build a no-UI feature's screen | Move its entries from "does not exist" to the real page, and update symptom searches |
| Rename a screen | Change the title. **Never the `help_id`** |
| Retire a screen | Mark the id retired. Do not delete the row |

> **Outdated help is worse than missing help.** A user who reads
> instructions for a button that is not there concludes the product is
> broken, or that they are. Everything here was checked against the
> running product before it was written; keep it that way.

---

## See also

- [Blink Engage User Guide](../guides/blink-engage-user-guide.md) — the source of truth
- [Administrator Guide](../guides/administrator-guide.md)
- [Onboarding wizard specification](../product/tenant-onboarding-wizard.md)
- [Navigation proposal](../architecture/navigation-information-architecture.md)
