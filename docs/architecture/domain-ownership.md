# Domain ownership audit

*Every business fact has exactly one owner. This is the audit that checks it.*

Traced against the code, not the intent. Two genuine ambiguities and three
duplicated rules were found; each is below with a recommendation.

---

## The matrix

| Business fact | Owner | Consumers | Exposed as | Clean? |
|---|---|---|---|---|
| **Password, sessions, tokens, login** | Authentication | — | Service | ✅ |
| Password *policy* (min length) | Company (config) → Authentication (enforcement) | Authentication | `company_settings.min_password_length` | ✅ config and rule are correctly separate |
| **Profile, email lifecycle, verification, restrictions, Identity Health** | Identity *(Phase 1)* | API gate, Company admin | Service + events | ⚠️ not built; today split across auth and verification |
| **Roles, permissions, access decisions** | Authorization | API gate, Identity (protected accounts) | `domain/rbac.py`, pure leaf | ✅ imports nothing |
| **Company, teams, departments, business configuration** | Company | Everything | Repositories + `Company.settings` | ✅ |
| **Business hours** | Company | SLA (pause), AI | `domain/business_hours.py` | ✅ |
| **Company verification** | Company | API gate | `Company.verified_at` | ⚠️ currently written by Identity's service — see D3 |
| **Service resolution, queue selection, assignment** | Routing | Conversation, Inbox, Inspector | Decisions + `queue_id` | ✅ |
| **Which service a conversation runs in** | Routing → binding | SLA, AI, Inbox | `ConversationContextBinding` by version | ✅ frozen by value |
| **Conversation lifecycle status** | Conversation | Inbox, SLA, reporting | `Conversation.status` | ✅ |
| **Who is responsible for a conversation** | **Ownership** | Inbox, Inspector, metrics | `conversation_ownership`, append-only | ✅ **A1 resolved** — `assigned_agent_id` is now a projection |
| **Operational state** | Conversation *(derived)* | Inbox | `operational_state()` | ⚠️ **D2 — expressed twice** |
| **Time, deadlines, breaches** | SLA | Inbox, Inspector, reporting | Clocks + decisions | ✅ |
| **SLA health** | SLA | Inbox ordering, Inspector | `Clock.health` | ⚠️ **D1 — expressed twice** |
| **SLA targets** | Service version | SLA | Copied onto the clock at start | ❌ **A3 — the queue's attached policy is written by the UI and read by nothing that matters** |
| **Usage, pricing, invoices, payments, ledger** | Billing | Dashboard, invoices, platform | `_effective_rates` | ✅ fixed this cycle |
| **Effective unit rate** | Billing | Dashboard, estimate, invoice | One resolver | ✅ was duplicated, now single |
| **Classification, suggestions, autopilot, confidence** | AI | Conversation, Inbox | `AutopilotService` | ✅ |
| **AI confidence threshold** | Service version → company fallback | AI | `effective_autopilot_confidence_threshold` | ✅ one resolver |
| **Whether AI may engage** | Policy Engine | Ingest, pickup sweep | `Policy.AI_ENGAGEMENT` | ✅ single evaluator |
| **Event severity** | Inspector domain | Every client | `domain/severity.py` | ✅ backend-only by design |
| **Customer identity** | Company | Conversation, Inbox, ERP | `customers` | ✅ |
| **Unread count** | Conversation | Inbox | Derived from messages | ✅ |
| **What the company officially states** | Knowledge *(designed)* | AI, agents, customers | Versioned articles | ⚠️ not built — [KMI](./knowledge-memory-intelligence.md) |
| **What the platform has learned** | **Memory** | AI, Workflow, CRM, Reporting, Timeline, Analytics | `memory_facts` + evidence | ✅ built — `MemoryManager` is the only writer, guarded by an AST test |
| **How the organization operates** | **Company Behavior** *(reserved)* | Policy, Workflow, Routing, SLA, Assignment | — | 🔒 **reserved, unbuilt — see the A3 warning below** |

---

## A1 — Resolved: two answers to "who has this conversation"

**Was the most significant finding in this audit. Fixed before Identity
Phase 1 began — see [ownership-consistency.md](ownership-consistency.md) for
the full report.**

Two facts were live and written independently: `Conversation.assigned_agent_id`,
a mutable column, and `conversation_ownership`, an append-only timeline.
Overlapping but not identical sets of callers wrote them, and nothing compared
the two.

The concrete defect: the `assign_to_agent` workflow action reached
`ConversationService.update(assigned_agent_id=...)`, which set the column,
cleared `autopilot_active` and wrote no ownership row — so the Inbox showed
the queue as owner while an agent was assigned.

Three further problems surfaced during the fix, none of them in the original
finding:

- `take_over_from_autopilot` — a human taking a conversation *back from AI* —
  wrote no ownership row either. That is the transition every "AI must not
  speak after a human steps in" rule reads.
- `release()` on a conversation with no queue wrote nothing, leaving the
  timeline naming an agent who had just let go.
- Three production wiring sites built `ConversationService` with
  `ownership=None` — the SLA sweep, the workflow engine consumer and the CSAT
  dispatch consumer. Two are the exact paths the defect was about, so a
  corrected `update()` would still have done nothing there.

### How it stands now

`OwnershipService.transfer` is the only place a transition happens; it writes
the history row and then projects it onto `assigned_agent_id`. The rule is
`domain/ownership.assigned_agent`, and it is total over `OwnerKind`.
`ownership` is now a **required** collaborator, and its failures are no longer
swallowed — the row stopped being evidence about the handover and became the
handover.

An AST guard (`tests/unit/test_ownership_is_the_only_writer.py`) fails when
any new code path writes the column outside a two-entry allow-list. Verified
by planting a real writer in a real module.

`assigned_agent_id` remains a *maintained* projection rather than a *derived*
one — documented as transitional architecture, with the two pieces of work
that would remove the column listed in the report.

---

## A2 — Ambiguity: "users within the organisation"

The brief assigns users-within-the-organisation to **Company** and
profile/email/verification to **Identity**. Both are right, and the line
between them needs stating or it will be argued about in every review:

| Fact | Owner |
|---|---|
| That this person belongs to this company | **Company** — `company_id`, invitations, offboarding |
| Their department, team, agent profile | **Company** |
| Their name, email, language, timezone, avatar, verification | **Identity** |
| Their role | **Authorization** |
| Their password | **Authentication** |

*Company owns the membership. Identity owns the person.* Removing someone from
a company is Company's; changing their email is Identity's; neither reaches
into the other.

---

## A3 — Ambiguity: two answers to "what is the SLA target"

**Found by running a real conversation through the live installation**, not by
reading. It is the same shape as A1 and the same shape as the AI confidence
threshold fixed earlier this cycle: *the UI writes one fact and the engine
reads a different one.*

| | `Queue.sla_policy_id` → `SlaPolicy` | `service.sla` → `SlaTargets` |
|---|---|---|
| Written by | The SLA Builder screen, and the Queue editor | The Services screen, frozen onto the service version |
| Read by | `sla_monitor_service` — the `check_sla_breaches` sweep | `SlaEngine` / `SlaLifecycle` → `conversation_sla_clocks` |
| Drives | `conversation.sla_warning` events | **Clocks, Inbox health ordering, the Breached queue, the Conversation Story** |

Ingest resolves targets at
`conversation_ingest_consumer.py:852` — `targets=service.sla if service is not
None else None` — and `_start_clocks` returns immediately when that is `None`.

So a company that has attached an SLA policy to a queue, and has no service
directory, starts **no clocks at all**. On this installation that is the case
for every company: `conversation_sla_clocks` holds **zero rows**.

The consequence is not subtle. An administrator configures an SLA, attaches it
to the queue their conversations land in, and then finds: the Breached work
queue permanently empty, SLA health absent from Inbox ordering, and no SLA
events on any conversation's story. Nothing reports a problem, because from
the engine's point of view nothing is wrong — it was never given a target.

### Recommendation

Resolve it exactly as the AI confidence threshold was resolved, because the
precedent is already set and approved: **the service's targets win where a
service defines them; the queue's attached policy is the fallback where it
does not.** One resolver, the way
`effective_autopilot_confidence_threshold` is one resolver.

The alternative — making Service the only owner and withdrawing the
queue-attached policy from the UI — is defensible but strictly worse today: it
would delete configuration customers have already entered, to fix a problem
caused by the engine ignoring it.

**This is a real bug, not a modelling opinion**, and it blocks any credible
SLA demonstration.

---

## D1 — Duplicated rule: SLA health

`Clock.health()` in Python and the `CASE` expression in
`sla_health_rank.py` are two implementations of one rule.

**Justified, and controlled.** The Inbox must order by health across the whole
company, which is a SQL problem; a per-conversation reading is a Python
problem. Neither can serve the other.

Both read the same thresholds from `domain/sla.py`, and
`test_inbox_sla_order.py` runs every band through both paths on the same rows.
That test found a real defect — SQLite's `julianday` returning 2400.0000001
where PostgreSQL returns 2400, putting a clock one band too healthy.

**Keep, with the drift test as a permanent condition of keeping it.**

---

## D2 — Duplicated rule: operational state

`operational_state()` in Python and `_view_condition()` in SQL. Identical
justification to D1, identical control: `test_inbox_views.py` asserts every
conversation a view returns really is in the state that view claims.

**Keep, on the same terms.**

---

## D3 — Duplicated state: two verifications, one field

`VerificationService.verify()` writes `Company.verified_at` — Identity's
service mutating Company's state, and the reason a user's own verification
gates nothing.

**Resolved by Phase 1**, which splits account verification from company
verification. Company keeps `verified_at` and owns writing it; Identity owns
the account. Listed here so the audit's record matches the plan.

---

## Verdict

**Phase 1 may begin**, with one condition.

- **A1 must be fixed first.** It is a live inconsistency between two systems
  of record, it produces a visibly wrong Inbox row today, and Identity is
  about to add a third kind of account state to a codebase that already has
  two answers to "who has this". Fixing it after would mean building on a
  known-wrong fact.
- **A2 is a documentation fix** — the line above, written down.
- **A3 must be fixed too.** It was found after this audit was first written,
  by sending a real message through the live installation rather than by
  reading — which is itself the finding: three separate reviews of this
  document did not catch it, and one conversation did.
- **D1 and D2 are accepted duplications** with drift tests, and both have
  already earned their keep by catching real bugs.
- **D3 is what Phase 1 exists to fix.**

Everything else in the matrix has exactly one owner.

---

## Reserved: Company Behavior, and why A3 is its cautionary tale

[Company Behavior](./knowledge-memory-intelligence.md#company-behavior-reserved)
is a reserved bounded context that will own *how the organization chooses to
operate* — named practices, procedures and the mapping from a practice to the
configuration that enforces it. It is not built, not scheduled, and has no
schema.

It is recorded **here**, in the ownership audit, because A3 is precisely the
failure it would repeat at scale.

A3 is one business fact with two owners, and the cost was not a modelling
opinion: zero SLA clocks across the entire installation, a permanently empty
Breached queue, and nothing reporting a problem. Behavior compiles into the
configuration of Policy, Workflow, Routing, SLA and Assignment — **five
surfaces that are each already configurable directly today.** Introduced as a
parallel authoring layer, it does not create one A3. It creates five, each
invisible in the same way.

The condition on ever building it, recorded now while it is cheap:

> Behavior must become the **single writer** of the configuration it owns, and
> the direct authoring path must be withdrawn in the same change — never left
> alongside it.

This is the Policy Engine's own migration rule (*"each migration deletes the
local copy rather than leaving both"*) applied to a context that has not
shipped. The hard part of Behavior is not its schema; it is migrating five
existing configuration surfaces, and that cost belongs in the estimate on the
day somebody proposes it.
