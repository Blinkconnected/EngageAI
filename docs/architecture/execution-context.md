# Execution Context

Every conversation in Blink Engage runs inside an **ExecutionContext** — the
single operational contract passed to every module.

Routing, SLA, AI, automation, knowledge, reporting and whatever ships next all
need the same things: how the business behaves for this conversation, how this
customer is treated, and what is true of the conversation right now. Before
this type existed, each module fetched those separately — which meant each
could fetch something *different*, and two modules disagreeing about a
customer's tier is a bug that only appears under timing nobody reproduces.

```
ExecutionContext
├── ServiceContext        immutable, versioned    how the business behaves
├── CustomerContext       immutable, versioned    how this customer is treated
├── ConversationFacts     snapshot                what is true right now
└── CompanyCapabilities   company-wide switches   what the company permits
```

Source:
[`domain/execution_context.py`](../../backend/src/blinkengage/domain/execution_context.py),
[`domain/service_context.py`](../../backend/src/blinkengage/domain/service_context.py),
[`domain/customer_context.py`](../../backend/src/blinkengage/domain/customer_context.py).

---

## The rule

A module that receives an ExecutionContext **cannot look anything up again**,
because it holds no ids to look up with — only resolved contexts. That is the
point, and it is structural rather than a convention people are asked to
follow.

If a module needs something the context does not carry, the answer is to add
it here — deliberately, where every module sees the same value — not to open
a repository in the corner of a service and read a second version of the
truth.

---

## Two immutable contexts, one mutable snapshot

The distinction is explicit rather than implied, and it matters at the call
site.

`execution.service.sla` is a decision made when the conversation began. It
cannot move under a reader. An administrator halving the first-response target
at noon does not rewrite the deadline of every conversation opened that
morning — an agent watching a countdown would see it jump.

`execution.conversation.status` is what was true a moment ago. It makes no
claim to be stable; it exists so every module in one execution reasons about
the *same* moment rather than each re-reading a row that is moving.

Both are correct. Conflating them is how a system starts deciding on stale
state without anybody knowing which half was stale.

---

## Service Context

Resolved **once**, by the Routing Engine, at the start of the conversation. No
downstream module performs its own service lookup.

Carries the service's SLA targets, AI policy, queue binding, and its name and
queue name **as values** — so a conversation can still say what it is running
in after the service is renamed or archived.

Bound conversations keep their version. `ContextBindingReason` distinguishes
a conversation that simply started here (`BOUND_AT_START`) from one an
administrator deliberately moved (`REBOUND_BY_ADMINISTRATOR`,
`REROUTED_TO_ANOTHER_SERVICE`).

A context whose version is behind the current one is **stale**, and stale is
the guarantee working, not a fault. The console shows it so a supervisor
wondering why two conversations in one queue have different deadlines gets an
answer.

### Growing without breaking old versions

`extras` is a namespaced bag read through `setting(namespace, key, default)`.
A version written before a module existed has no entry for it and answers with
the caller's default rather than raising — so a conversation bound to an old
version keeps running. Malformed stored JSON also answers with the default: a
context that raised on bad data would take a conversation down over a
configuration mistake.

---

## Customer Context

The counterpart, with one hazard the Service Context does not have.

A service changes when an administrator edits it: rarely, deliberately. A
customer record changes **constantly** — a CRM sync writes a field back, an
agent corrects a phone number, `last_seen_at` is touched on every visit.
Minting a version on every change would produce one version per conversation,
a chain nobody can read, and effectively no versioning at all.

So a version is minted from a **fingerprint of the routing-relevant attributes
only**:

```
tier · is_vip · language · timezone · country_code
contract_id · pricing_profile_id · segment
contact_preference · preferred_agent_id
```

Equal fingerprint → reuse the version, write nothing. **Renaming a customer
does not fork their history; promoting them to VIP does.**

The fingerprint is a SHA-256 over canonically ordered JSON, deliberately not
Python's `hash()`, which is salted per process and would silently fork every
customer's history on restart. A `UUID` and its string form produce the same
digest, so a change of type upstream cannot look like a change of customer.
`None` and `""` fold together, so clearing a field to empty does not mint a
version.

A test asserts every field declared routing-relevant actually moves the
digest — a field on that list the function ignores would be a change that
silently never takes effect.

### What it deliberately does not carry

Not a copy of the customer record. An address, a phone number and a notes
field belong to the customer profile, which a module can open if a human asks
to see it. Copying them here would make every profile edit look
routing-relevant, and would put personal data into an immutable versioned
store that has no business holding it.

---

## Company Capabilities

Company-wide switches that no service or customer may override — currently
`ai_enabled`, `ai_provider_configured` and `autopilot_enabled`.

Every field defaults to the *unavailable* answer, and `capabilities=None`
means the caller did not say. The [Policy Engine](./policy-engine.md) treats
that as nothing-available rather than guessing, because the alternative is a
forgotten field turning a compliance kill switch back on by omission.

There is deliberately no `automation_enabled`: no such company-level setting
exists today, and a capability with nothing behind it makes a policy look
enforced when it is not.

---

## An unknown customer is a normal case

`customer` is `None` for a first message on anonymous web chat, or an
unrecognised number. Common, not exceptional — so every reader must handle it
and every convenience answers sensibly without one.

An unknown customer is explicitly **not** priority. The alternative treats
every stranger as a named account.

Likewise `language` is `None` for undetected, not English. A module needing a
concrete language substitutes its own default and can say that it did; one
handed a wrong language cannot.

---

## Facts, not decisions

The context answers *what is true*. It does not answer *what is allowed* —
that is the [Policy Engine](./policy-engine.md), which takes an
ExecutionContext and returns a decision with a reason and a source.

`is_priority` is a derived fact. `ai_may_engage` was a property here and was
**removed** when the Policy Engine landed: a business rule answerable on the
context is one the AI module reads, the automation module forgets, and a third
reimplements differently — and a bare boolean can never explain itself in the
Routing Inspector. A test asserts it cannot come back.

---

## See also

- [Policy Engine](./policy-engine.md)
- [Queue architecture](./queue-architecture.md)
- [Routing rules](./routing-rules.md)
- [Queue lifecycle](./queue-lifecycle.md)
