# Deleting a conversation

Deleting a conversation is the one irreversible thing anybody does in
this product, and until now one person could do it alone.

A conversation is the record of what a company said to a customer. It is
evidence in a dispute, an input to every report, and in regulated
industries something the company is obliged to keep. `DELETE
/conversations/{id}` — gated on `conversations.delete`, held only by the
Owner — removed one quietly, with no reason recorded and nothing to
consult afterwards.

So deletion became a request somebody else approves. The direct delete
still exists, unchanged, for whoever legitimately holds that authority;
what is new is a route through it for everybody else, and a record that
outlives the conversation either way.

## Two permissions, deliberately different people

| Permission | Who has it by default | What it allows |
|---|---|---|
| `conversations.delete_request` | Agent, Admin, Owner | Ask for a conversation to be deleted |
| `conversations.delete_approve` | Admin, Owner | Decide on a request |
| `conversations.delete` | **Owner only** | Delete outright, with no request and no recorded reason |

Deciding and deleting are separate permissions, and that separation is
what makes approval the route rather than a formality.

An earlier version of this feature gave Admin `conversations.delete` —
the tenant administrator is precisely who a request is addressed to, and
an approval queue only the Owner can clear does not get cleared. But
that one permission also carried the direct `DELETE /conversations/{id}`
endpoint, so an administrator could walk around the process they exist
to be the second half of, and leave nothing behind saying why: a direct
delete records no reason. Splitting it means the only way anybody but
the Owner removes a conversation is with a written reason and a second
name against it.

`conversations.delete` also gates something that is not obvious from
its name: `POST /agents/{agent_id}/removal` with `mode: "permanent"`,
which destroys every conversation belonging to a departing agent in one
call. `docs/architecture/administration.md` records that the check was
added precisely so "a default Admin, who is explicitly denied
`conversations.delete`", could not reach that effect in bulk — an
explicit separation-of-duties boundary. Granting Admin the permission
silently removed that boundary as well as the approval one. Anything
gated on `conversations.delete` should be read as *destroys records
without recording why*, and granted accordingly.

The Owner keeps the direct route deliberately. One accountable person
per company should not have to stage an approval they do not want, and
the audit log records that they did exactly that.

**The revocation needed a migration** (`d1c8b30f5a27`). The generic
permission sync is additive-only and never revokes, so removing the
grant from `DEFAULT_ROLE_PERMISSIONS` alone would have left every
existing Admin still holding it. The migration skips roles with
`permissions_customized = true`: a company that deliberately gave its
Admins direct deletion has made a decision, and silently overruling it
is worse than the inconsistency. Verified on 37 live companies — Admin
0/37 direct after, 37/37 approve, Owner 37/37 direct — and reversible.

Requests are addressed to **whoever holds `conversations.delete_approve`**, never
to a role by name. Roles are renameable and companies invent their own;
a notification addressed to "Admin" would silently stop reaching the
people who can act the moment somebody creates a "Supervisor".

## The flow

```
agent                         administrator
  │
  ├─ POST /conversations/{id}/deletion-request
  │     { reason }                             → pending
  │                                            → notification to every approver
  │                                              except the requester
  │
  │                            ├─ GET /conversation-deletion-requests?status=pending
  │                            │
  │                            ├─ POST .../{id}/approve  { note? }
  │                            │     → conversation soft-deleted
  │                            │     → conversation.deleted event
  │                            │     → approved, decided_by, decided_at
  │                            │
  │                            └─ POST .../{id}/reject   { note }
  │                                  → conversation untouched
  │                                  → rejected, note recorded
  │
  └─ notification: your request was approved / rejected
```

Approval performs the deletion **in the same request**. An approval that
records a decision and then relies on a second call to carry it out is an
approval that can silently not happen.

It deletes through `ConversationService.delete`, not through the
repository — the same soft delete and the same `conversation.deleted`
event a direct delete produces, so the two paths cannot drift apart.

## The rules, and what each one prevents

All of them are in `domain/conversation_deletion.py`, away from the
database, because each exists to stop a nameable outcome.

**A reason is mandatory, minimum 10 characters, whitespace collapsed
before measuring.** The approver will have the customer's name and these
sentences and nothing else, often days later. Measuring the raw string
would let somebody past the floor by holding down the space bar.

**One open request per conversation.** Enforced by a partial unique index
(`WHERE status = 'pending'`) as well as a service check, so a race
produces a clean 409 rather than two rows. Two agents noticing the same
problem would otherwise leave an administrator approving one while the
other stays pending against a conversation that no longer exists.

**A request is decided once.** Two administrators open the same queue and
both approve: without this, the second approval deletes an
already-deleted conversation and writes a second audit entry — two
records of one deletion, different timestamps, different names.

**The requester does not decide their own request.** This is *not* a
security boundary: anybody who can approve can also delete outright, and
the rule cannot stop them. It is about the record. An approval is worth
keeping only if it shows two people, and one name on both halves makes
the whole step ceremony. Somebody who holds the authority and does not
want a second opinion should delete the conversation directly and be
recorded as having done exactly that.

**A rejection must explain itself; an approval need not.** An approval
stands on the request's own reason. A rejection contradicts it, and the
person who asked has to learn something rather than watching their
request quietly disappear.

## The record outlives the conversation

`conversation_deletion_requests` is not soft-deletable and its
`conversation_id` foreign key is `ON DELETE SET NULL`, not `CASCADE`.

Once the conversation is gone, this row is the only account of what
happened: the reason, the customer's name (denormalised onto the row for
exactly this reason — "delete conversation 4f3c…" is not reviewable),
who asked, who agreed, and when. Cascading it away with its conversation
would delete the paperwork along with the thing the paperwork explains.

Conversations are soft-deleted in normal operation, so the row survives
either way today. The `SET NULL` is for the hard purge that does not
exist yet.

## Status mapping

| Rule | HTTP |
|---|---|
| `reason_too_short` / `reason_too_long` | 400 (422 when Pydantic catches it first) |
| `not_found` | 404 |
| `already_requested` | 409 |
| `already_decided` | 409 |
| `self_approval` | 403 |

409 for the two collisions specifically, so a client knows to refresh
rather than to change what it sent.

A conversation in another company is a **404**, not a 403 — a
cross-company id must not be confirmed to exist.

## In the product

**On the conversation.** A quiet, error-coloured icon at the end of the
header bar's action row: destructive, and rarely the thing being done.
It opens a short form, not a confirmation dialog, and the form says out
loud that nothing is deleted yet — somebody who presses a button labelled
"delete" and sees the conversation still there will press it again.

Once a request is open, **everybody looking at that conversation sees a
banner** naming who asked and quoting their reason, and the button
disappears. This is deliberately not scoped to the requester: an agent
about to invest in a long reply needs to know it may be on its way out,
and a second agent needs to know not to ask again.

**The queue** is `/deletion-approvals`, under **Work** in the sidebar
rather than under Organisation — it is a queue somebody owes an answer
to, not a settings page. It is gated on `conversations.delete_approve`, so it
only appears for people who can actually decide. Each request is a card,
not a table row, because the reason is the whole basis of the decision
and it is set as prose rather than truncated into a cell. Tabs separate
what is waiting from what has been settled; a decided request is a
record, and shows no buttons.

## Verification performed

- `tests/unit/test_conversation_deletion_rules.py` (11) — every rule
  above, including whitespace-only reasons, both terminal states
  refusing a second decision, and an orphaned request (`None` requester)
  staying decidable rather than being read as self-approval and stuck
  forever.
- `tests/integration/test_conversation_deletion.py` (18) — asking does
  not delete; the reason floor over HTTP; the second request 409ing; the
  pending state readable by anybody who can read the conversation;
  cross-company 404; approval deleting the conversation; the paperwork
  surviving it, with both names resolved; rejection keeping the
  conversation and recording why; a rejection without a note refused; a
  request decided twice 409ing; the owner refused their own approval; an
  ordinary agent able to ask but not to see the queue or decide;
  company-scoped listing; the status filter; approvers notified; the
  requester told the outcome; and nobody notified about their own
  request.
- `features/conversations/ConversationDeletion.test.tsx` (12) — the
  request flow end to end, "nothing is deleted yet" stated, a
  four-character reason keeping the button disabled, the banner shown to
  everybody with the button withdrawn, the action hidden without
  permission, the reason rendered as prose, the irreversibility warning,
  a rejection requiring its note, decided requests showing the decision
  and no buttons, the tabs separating waiting from settled, the empty
  state, and a concurrent decision surfacing as a conflict.
