# AI tool calling

**Status:** current (M2A + M2B). The execution foundation only — there is
no conversational AI administrator yet, and no onboarding. Those are M2C
and later. What exists is the machinery any of them must go through.

Companion to [`ai-engine.md`](./ai-engine.md), which covers the twelve
text capabilities (`suggest_reply`, `summarize_conversation`, …). Those
are unchanged and unaffected.

---

## 1. The problem this solves

An AI that can *change* a workspace is a different security proposition
from one that suggests replies. A wrong suggestion is ignored; a wrong
mutation moves an agent out of a department, changes who can see billing,
or answers a customer twice.

Two failure modes drive the whole design:

- **The model is not trustworthy input.** It may be confused, or steered
  by text a customer wrote into a conversation it later summarises. Its
  output is a *request*, treated exactly as an unauthenticated HTTP body
  would be.
- **A prompt is not a control.** "Never delete anything" in a system
  prompt is a preference. The guarantees below are properties of the
  code: an absent tool cannot be called however the model is asked.

---

## 2. The pipeline

```
model turn
  → ToolCall {id, name, arguments}       untrusted in every field
  → registry allowlist                   unknown name → error, nothing runs
  → strict schema validation             extra="forbid", typed, bounded
  → AuthContext                          identity from the request
  → tenant scope                         company_id injected, never supplied
  → permission check                     an existing RBAC code
  → confirmation policy                  high-impact parks, does not run
  → application service                  business rules, events, outbox
  → audit                                before/after, request, model, result
  → ToolResult                           structured, screened
```

Implemented in `application/ai_tools/executor.py`. Nothing else in the
platform may run a tool.

### Refusals are data

An unknown tool, a bad argument, a missing permission — each returns a
`ToolResult` with status `error`, which goes back to the model so it can
correct itself. Raising would end the turn and, worse, would take the
refusal *outside* the audited path. Refusals are recorded: a model
repeatedly attempting what it may not do is exactly the pattern somebody
should be able to find later.

---

## 3. What the model can never do

| Guarantee | How it is enforced | Where |
|---|---|---|
| **Call a destructive tool** | None is registered, and the registry refuses to register a name containing `delete`, `remove`, `purge`, `drop`, `reset`, `truncate`, `wipe`, `erase`, `destroy` | `registry.FORBIDDEN_NAME_FRAGMENTS`, asserted in CI |
| **Supply its own identity** | `company_id`, `user_id`, `permission`, `actor_user_id` and friends are refused *as argument names* at registration; `extra="forbid"` rejects them at call time | `registry.RESERVED_ARGUMENT_NAMES` |
| **Reach a repository** | A handler is given `ToolServices` — four application services, no session, no container, no lookup-by-name | `spec.ToolServices` |
| **Run arbitrary code or SQL** | No tool takes "what to run" as an argument; dispatch is a dict lookup on reviewed names | CI test over names *and* argument fields |
| **Approve its own high-impact action** | Approval is an authenticated HTTP request consuming a server-held row, once | `PendingAiAction` |
| **Put a secret in the audit log** | Secret-shaped argument names are refused at registration, so the declared schema *is* the allowlist; a recursive scrub covers hand-built state | `registry.SECRET_NAME_FRAGMENTS`, `audit.py` |

Deletion is not merely absent from the AI — the platform already models
it as an approval workflow (`conversations.delete_request` →
`delete_approve`, with `conversations.delete` Owner-only). The AI cannot
even file the request; it directs the user to that human path.

---

## 4. Confirmation

High-impact actions (declared `ConfirmationPolicy.REQUIRED`) are never
executed by the executor. It validates, reads the current state, writes a
`PendingAiAction`, and returns `confirmation_required`.

```
POST /api/v1/ai/actions/{id}/confirm
```

That endpoint re-checks **everything**, because ten minutes is long
enough for any of it to have changed:

1. the action exists, in the caller's company, proposed by this caller
2. it is neither consumed nor rejected nor expired
3. the caller still holds the tool's permission
4. **the before-state still matches** — if the workspace moved, the human
   approved a diff that no longer describes what would happen
5. a conditional `UPDATE` claims it, so two simultaneous confirmations
   cannot both execute

**Bulk escalates automatically.** Any validated list argument longer than
`BULK_ESCALATION_THRESHOLD` (5) requires confirmation regardless of the
tool's own policy — a property of the executor, so it holds for the bulk
tool nobody has written yet.

The summary shown to the user is built from **validated arguments**,
never from the model's prose. A model that could author that text could
describe a change as milder than it is, and the person would be approving
the description rather than the action.

---

## 5. Provider support

| Provider | Tool calling | Notes |
|---|---|---|
| `openai` | ✅ | Chat Completions `tools`/`tool_calls`, `tool_choice: auto` |
| `claude` | ✅ | Messages `tools` + `tool_use` blocks (`input_schema`, interleaved with text) |
| `gemini`, `azure_openai`, `mistral`, `groq`, `deepseek`, `ollama` | ❌ | Refuse explicitly |

`AiProvider.supports_tools` is a class-level declaration, defaulting to
`False` — a new provider is non-capable until its author says otherwise,
because claiming support you lack fails at the worst possible moment.

**There is no text-parsing fallback, deliberately.** Prompting a
non-capable model to emit JSON and parsing whatever comes back puts a
guesser in front of a mutation pipeline. A provider either speaks the
structured protocol or the feature is unavailable on it;
`ToolCallingNotSupportedError` says so plainly.

`complete()` is untouched — same signature, same behaviour, same twelve
callers.

---

## 6. Audit

Two layers.

**`AuditLog` (existing)** — tools call application services, so the
ordinary domain event is published and the `#`-bound consumer records it
exactly as it records a human's action.

**`AiActionLog` (new)** — what that cannot express: `before_state`,
`after_state`, `user_request`, `model_identifier`, plus actor, company,
session, turn, tool, validated input, correlation id, result and
timestamp. Written for successes *and* refusals. Append-only, no
soft-delete, `actor_user_id` on `SET NULL` so the record outlives the
account.

`model_identifier` is `"provider:model"` — `"openai:gpt-4o-mini"`. "The
AI did it" is not an answer to "which model, on which provider".

---

## 7. Idempotency

Reuses M1's `IdempotencyStore` — the same primitive behind
`Idempotency-Key` on message send — scoped
`ai_tool:{company}:{user}:{tool}` and keyed on the provider's own
`tool_call_id`. A retried turn replays its original result instead of
creating a second department. There is deliberately no second idempotency
mechanism: two would behave differently under failure, and the difference
would surface exactly once, in production.

---

## 8. Not yet built

- No conversational surface. Nothing calls `ToolExecutor` in production
  yet; M2C adds the AI administrator on top of it.
- `AiActionLog.session_id`/`turn_id` are nullable plain UUIDs — sessions
  arrive with that surface. An audit write must never fail because the
  thing it refers to does not exist yet.
- Four tools only (`list_departments`, `create_department`, `create_team`,
  `change_agent_role`). Enough to exercise every branch of the pipeline;
  the registry grows in M2C.
- No AI usage billing. The integration point is the existing
  `BillableEvent`/`UsageRecord` metering, deferred by decision.

---

## See also

- [`ai-engine.md`](./ai-engine.md) — the twelve text capabilities and provider config
- [`auth-rbac.md`](./auth-rbac.md) — the permission catalog tools bind to
- [`event-bus.md`](./event-bus.md) — how the ordinary audit trail is written
