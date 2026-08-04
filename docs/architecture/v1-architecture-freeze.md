# Architecture freeze — Version 1.0

*What is settled, what is deliberately not, and whether this ships.*

Frozen means: **the shape is decided and further change needs a reason beyond
preference.** It does not mean finished. Several frozen domains have known
limitations listed below; they are frozen because the limitation is understood
and bounded, not because it is absent.

---

## 1. Frozen domains

| Domain | Owns | Enforced by | State |
|---|---|---|---|
| **Authentication** | Password, sessions, tokens, login | `auth_service` | ✅ frozen |
| **Authorization** | Roles, permissions, access decisions | `domain/rbac.py` — a pure leaf; stdlib only, no project imports, so it cannot participate in a cycle | ✅ frozen |
| **Company** | Company, departments, teams, business hours, business configuration | Repositories + `Company.settings` | ✅ frozen |
| **Routing** | Service resolution, queue selection, assignment | Append-only `routing_decisions` | ✅ frozen |
| **Ownership** | Who is answerable for a conversation | Append-only `conversation_ownership`; AST guard | ✅ frozen this milestone |
| **Conversation lifecycle** | The eight states and the legal moves between them | `domain/lifecycle.py` | ✅ frozen |
| **SLA** | Clocks, deadlines, breaches, health | `conversation_sla_clocks` + decisions | ✅ frozen |
| **SLA target resolution** | Which tier supplies the deadlines | `resolve_sla_targets`: service → queue → platform | ✅ frozen this milestone |
| **AI Autopilot** | Classification, suggestions, engagement, confidence | `AutopilotService` + `Policy.AI_ENGAGEMENT` | ⚠️ frozen with **G1** open |
| **Billing** | Usage, pricing, invoices, payments, ledger | Immutable metering; one rate resolver | ✅ frozen |
| **Explainability** | The Conversation Story and Routing Inspector | `ConversationInspectorService` — an assembler, no storage of its own | ✅ frozen |
| **Inbox** | Operational state, work queues, ordering | `domain/operational_state.py`, `domain/inbox_views.py` | ✅ frozen |
| **Identity** | Profile, email lifecycle, verification, restrictions, Identity Health | — | ❌ **designed, not built** |

---

## 2. Approved invariants

Each of these is enforced by something that fails, not by convention.

1. **Ownership has exactly one source of truth.** `conversation_ownership` is
   the business history; `assigned_agent_id` is a projection of it. Every
   transition goes through `OwnershipService.transfer`, which writes the
   history row and the projection together.
   *Enforced by* `tests/unit/test_ownership_is_the_only_writer.py` — an AST
   guard with a two-entry allow-list, verified by planting a real writer.

2. **A company is operable the moment it exists.** Registration seeds a queue
   and a catch-all rule; no conversation can reach nothing.
   *Enforced by* `test_new_company_can_go_live.py`, end to end from
   registration alone.

3. **The UI and the engine never disagree.** A setting a screen exposes is the
   setting the engine enforces — AI confidence threshold, pickup delay, SLA
   targets.
   *Enforced by* the service→company and service→queue→platform resolvers,
   each with a single implementation.

4. **Evidence never costs the conversation — but the handover is not
   evidence.** Routing decisions, SLA transitions and ingest's ownership
   records are best-effort and SAVEPOINT-isolated, so a failed audit write
   rolls back only itself and the customer is still answered.

   The one deliberate exception: `ConversationService._record_ownership`
   **propagates**. Once an ownership transition became the thing that moves
   `assigned_agent_id`, it stopped being a note *about* the handover and became
   the handover; swallowing there would report a conversation assigned to
   somebody who does not have it.
   *Enforced by* `TestRecordingNeverCostsTheConversation`, which injects a real
   constraint violation into the decision writer.

5. **Metering never knows prices, and metering records are immutable.**
   *Enforced by* append-only triggers and `test_metering_separation.py`.

6. **AI never speaks after a human takes control.**
   *Enforced by* three independent writers of `autopilot_active=False` and the
   consumer's first-check on that flag.

7. **The platform never invents what it does not know.** The Inspector reports
   gaps explicitly rather than rendering a blank section — and never shows a
   raw identifier to a reader.
   *Enforced by* `TestItNeverShowsAnIdentifierToAPerson` (added this milestone,
   verified by disabling the fix).

8. **A superadmin manages companies and billing and cannot read tenant
   conversations, customers or messages.**

9. **Every business fact has exactly one owner.**
   *Recorded in* `docs/architecture/domain-ownership.md`; the two ambiguities
   it found are closed.

10. **No raw translation key is ever visible in production.**

---

## 3. Known limitations

Accepted, understood, bounded.

| # | Limitation | Why it is acceptable |
|---|---|---|
| L1 | `assigned_agent_id` is a **maintained** projection, not a **derived** one | Nothing writes it independently, and one guard fails if that changes. Removing the column needs an indexed current-owner view plus a reconciliation sweep — ordinary work, not research. |
| L2 | SLA health and operational state are each expressed twice, in Python and SQL | The Inbox must order across a whole company (a SQL problem); a single conversation must read its own state (a Python problem). Both held by drift tests that have already caught real bugs. |
| L3 | Queue-tier SLA supplies only two of the four clocks | Neither an `SlaPolicy` nor the legacy queue fields has ever expressed queue-wait or next-response. They stay unmeasured rather than invented; a company wanting them defines a service. |
| L4 | AI hand-off records no decision (**G2**) | Behaviour is correct; only the *why* is unrecorded. |
| L5 | No policy decision is recorded for service-less companies (**G4**) | Same shape as L4 and closes with G1. |
| L6 | `ai.resume_delay_seconds` is configuration nothing obeys (**G3**) | Documented, tested, deliberately unbuilt. |
| L7 | Runtime lanes have storage and a domain model and nothing creates them | The Inspector reports *not in use* rather than showing a blank field. |
| L8 | `ReleasePolicy.ON_RESOLVE` / `ON_CLOSE` are consulted by nothing | Resolve and close deliberately do not move ownership — sticky ownership is what makes a customer's follow-up reach the person who already knows them. |
| L9 | Transfer to a department records the **queue** as owner, not the team | The conversation genuinely sits in the queue; the department is on the conversation and in `conversation_transfers`. But "escalated to Sales" is not visible in the ownership timeline. |

---

## 4. Remaining Version 1.0 blockers

**P0 — must not ship without.**

| # | Blocker | Status |
|---|---|---|
| B1 | **G1: AI is a first responder for every current tenant.** `pickup_delay` falls back to 0 without a service, so the queue-worker promise holds for nobody here. The domain default is already 30s — the fix is one line; the decision is whether every tenant's AI should start waiting. | ⛔ open — needs a product decision |
| B2 | **Identity Phase 1 not built.** A user's own email verification gates nothing; the first person to click the link unlocks the company for everyone. The mailbox is the account-reset path. | ⛔ open — designed and approved, unimplemented |

**P1 — ship-blocking for a paid launch, not for a pilot.**

| # | Blocker | Status |
|---|---|---|
| B3 | eFAWATEERcom and MEPS payment adapters | ⛔ blocked on integration specs you hold |
| B4 | Go-live checklist — a company cannot currently tell whether it is ready to receive traffic | open |
| B5 | Onboarding wizard still orders ERP before Queues | open |

**P2 — quality, not correctness.** Required/optional field labels; AI blocking
reason surfaced on the settings screen; channel ordering; pricing visibility on
the plan screen.

---

## 5. Go / No-Go

### Recommendation: **Go for a controlled pilot. No-Go for general availability.**

**What earns the Go.** The engine is sound and, more importantly, *provable*.
Every business decision the platform makes is recorded, explainable and
readable by a person. The invariants in §2 are enforced by tests that fail
rather than by documents that are ignored — and three of them were added this
milestone after finding real defects, two of which were live in production. A
full lifecycle was driven end to end through a real WhatsApp conversation on
the live installation, and every subsystem — routing, SLA, ownership, AI, the
Story, the decision log and metering — observed the same facts.

**What blocks general availability.**

- **B2 is a security boundary, not a feature.** Account verification gating
  nothing means the account-recovery path is unproven for every user after the
  first. That is not something to ship to financial institutions or government
  and fix later.
- **B1 makes a headline promise untrue.** "AI waits so your agents get first
  refusal" is what the product says; today it does not do that for anybody.
  Small to fix, but shipping it as-is means the documentation is wrong on the
  first day.

**What a pilot looks like.** A known set of tenants, onboarded with a service
directory defined (which closes G1, G4 and L5 for them), on channels whose
providers are configured, with invoicing manual until B3 lands.

**The honest summary:** the architecture is ready to freeze. The product is not
yet ready for everyone.
