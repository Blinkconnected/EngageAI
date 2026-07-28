# AI Engine

M22 of the roadmap, closing Phase 4 (Engagement Intelligence). Every AI
capability the CLAUDE.md spec names — reply suggestions, conversation
summary, translation, language detection, sentiment analysis, auto
tagging, knowledge search, FAQ search, grammar improvement, professional
rewrite, next-best-action — built on one minimal provider contract shared
by OpenAI, Claude, and Ollama.

M22 itself shipped the API layer only, by design (see "API surface"
below) — a Product & UX Review afterward flagged the resulting gap
directly: ten fully-tested capabilities with no way for an agent to ever
reach them. "Frontend surface" documents the first two capabilities
wired into the actual agent workspace; the remaining eight follow the
same pattern.

## Frontend surface: Reply Suggestions and Conversation Summary

The first two of the ten capabilities to get a UI, chosen because they're
the highest-value, lowest-interaction-risk starting point (see the
Product & UX Review's "AI Experience" section for why): a draft an agent
edits before sending, and a read-only recap. Both live in
`frontend/src/features/conversations/aiApi.ts` (`useSuggestReplyMutation`,
`useSummarizeConversationMutation`), gated in the UI on the `ai.use`
permission via `usePermissions()` — the same permission the backend
already enforces, so the gate is a UX nicety (hide a control that would
just 403) not a real second access-control layer.

- **Reply Suggestions** (`ReplyBox.tsx`): an "AI" icon button next to the
  attach-file control calls `POST /ai/conversations/{id}/reply-suggestion`
  and sets the suggestion as the composer's draft text — never sent
  automatically. This is the human-in-the-loop pattern the rest of the AI
  Engine already committed to (see "Advisory-only Next Best Action"
  above) applied to its most-requested capability: the agent reviews and
  edits before hitting Send, same as if they'd typed it themselves.
- **Conversation Summary** (`ConversationSidebar.tsx`): a "Generate
  summary" button calls `POST /ai/conversations/{id}/summary` on demand
  and renders the result inline. Not fetched automatically on mount —
  every call is a real, metered LLM request, the same reasoning
  `enforce_ai_rate_limit` already applies server-side.

Both surfaces render the platform's existing 503 (`AiNotConfiguredError`,
company AI disabled or no provider configured) as a plain inline `Alert`
via the shared `extractErrorMessage` helper, not a raw error boundary or
a silent failure — an agent at a company with AI turned off sees "AI
features are not enabled for your company," not a broken button.

Frontend tests (`ConversationViewPage.test.tsx`, "AI features" block):
the suggestion populates the composer, a 503 renders the friendly error,
both controls are absent without `ai.use`, and the summary panel renders
its result with a passing accessibility check.

## One `complete()` method, not one method per feature

`domain/ai_provider.py`'s `AiProvider` ABC has exactly two abstract
methods: `complete(system, prompt, max_tokens, temperature) -> str` and
`health_check() -> bool`. This is a deliberate departure from
`ChannelProvider` (11 abstract methods — WhatsApp/Telegram/Messenger
genuinely have different native capabilities that abstraction has to
name). Every LLM backend has the exact same fundamental capability: take a
prompt, return text. The ten AI features are prompt-engineering
differences, not capability differences, so they live once in
`application/services/ai_service.py::AiService`, shared across all three
providers, instead of being duplicated three times inside each provider
class. Still an ABC, not a `Protocol`, for the same reason as
`ChannelProvider`/`SmsGateway`: providers are looked up by name from a
plain config string (`settings.ai_provider`), which needs registry-based
lookup, not structural typing against a reference already in scope.

`infrastructure/ai/registry.py`'s `AiProviderRegistry` and
`infrastructure/ai/factory.py`'s `build_ai_provider()` mirror
`ChannelRegistry`/`ChannelProviderFactory` and `SmsGatewayRegistry`
exactly: `@AiProviderRegistry.register(name)` class decorators —
`"openai"`, `"claude"`, `"gemini"`, `"azure_openai"`, `"ollama"`,
`"mistral"`, `"groq"`, `"deepseek"` — discovered via a blanket
`import infrastructure.ai.providers  # noqa: F401` at the point of use.
Groq/DeepSeek/Mistral all expose an OpenAI-compatible Chat Completions
API and share one implementation, `infrastructure/ai/providers/
_openai_compatible.py`'s `OpenAiCompatibleProvider` (not itself
registered — an internal base class each of the three subclasses,
overriding only `_DEFAULT_MODEL`/`_DEFAULT_BASE_URL`); `OpenAiProvider`
itself was deliberately left as its own separate, unrelated-milestone
file rather than retrofitted onto this shared base. Gemini
(`generateContent`, a `contents`/`systemInstruction` request shape, no
`messages` array, an API key query parameter) and Azure OpenAI (model
selected by *deployment name in the URL*, an `api-key` header, a
required `api-version` query parameter) are each different enough from
every OpenAI-style API that they get their own bespoke `complete()`/
`health_check()` implementations.

## Platform-level configuration, with an optional per-company override

`ChannelConfig` (WhatsApp, Telegram, email, ...) is inherently
per-tenant — each company has its own WhatsApp Business number, its own
SMTP box. The AI Engine started differently: a platform capability a
company either had turned on or didn't, with one shared API key/model
per deployment. `settings.ai_provider` (one of the 8 registered provider
names above, or `"disabled"`, the default), `settings.ai_model`,
`settings.ai_default_max_tokens`, and per-provider credential/base-URL
settings (`openai_api_key`/`anthropic_api_key`/`gemini_api_key`/
`azure_openai_api_key`/`azure_openai_base_url`/
`azure_openai_deployment_name`/`azure_openai_api_version`/
`mistral_api_key`/`groq_api_key`/`deepseek_api_key`/`ollama_base_url`/...)
follow the same environment-configured pattern `settings.smtp_*` (M21)
already established for platform-level, not per-tenant, capabilities —
this remains the *default* every company gets out of the box. Azure
OpenAI's resource endpoint/deployment name are account-specific with no
sensible universal default, so unlike every other provider's base URL
they're left unset (`None`) rather than pointing at a real default host.

What's since been added: a company can now **bring its own provider and
key** instead (see "Per-company provider override" below) — this was
named at the time as "a real possible future need... nothing about
`AiProvider`'s credential-carrying constructor blocks adding it later
without a breaking change," and that held true; the override layers on
top of the platform default rather than replacing this section's design.

`build_ai_provider(settings) -> AiProvider | None` returns `None` when
`ai_provider == "disabled"` — the default, meaning a fresh deployment has
AI Engine features off until an operator configures a provider (or a
company configures its own, per below).

## Per-company provider override

`Company.ai_config` — a *dedicated encrypted column*
(`infrastructure.database.encrypted_json.EncryptedJSON`, the same
AES-256-GCM-at-rest mechanism `ChannelConfig.credentials` already uses),
**not** a key inside the plain-JSON `Company.settings` blob, because
unlike every other admin setting this one carries a real secret (the
provider API key). Shape: `{"provider": <one of the 8 registered
names>, "api_key": str | None, "model": str | None, "base_url": str |
None, "deployment_name": str | None, "api_version": str | None}`, or
`None` for "no override, use the platform default." The last two keys
are Azure OpenAI-only (harmless, unread by every other provider) —
`base_url` doubles as Azure's "resource endpoint" rather than adding a
fourth field for a concept that's really just "the base URL for this
provider," same as every other provider already uses it for.

- **Precedence**: `infrastructure/ai/factory.py`'s
  `build_ai_provider_for_company(settings, company_ai_config)` — falls
  back to the plain `build_ai_provider(settings)` (platform default)
  whenever the company has no override (`ai_config` is `None`/has no
  `provider`) or when an individual field (`model`/`base_url`) is left
  unset on an override that does exist. `api/deps.py`'s `get_ai_provider`
  dependency now looks up the caller's `Company` and calls this instead
  of the old platform-only path, so every `/ai/*` endpoint transparently
  picks up a company's own key with zero changes to `AiService` itself.
- **Never returned to the frontend**: `GET /company/ai-config`
  (`api.schemas.company.AiConfigResponse`) exposes `provider`/`model`/
  `base_url` and a boolean `api_key_set` — never the key. Write-only,
  same convention as channel credentials. `PUT /company/ai-config`
  (`company.manage`) accepts an optional `api_key`; omitting it leaves
  whatever was previously saved untouched (`CompanyService
  .update_ai_config`), so changing just the model doesn't force
  re-entering a key that hasn't changed — **but only when `provider` is
  unchanged**. A key is scoped to the vendor it was saved under
  (`existing.get("provider") == provider`); switching the dropdown to a
  different provider without entering a new key clears `api_key_set`
  back to `False` rather than silently forwarding the old vendor's live
  secret into the new one's `Authorization` header (the frontend's own
  "leave blank to keep it" helper text would otherwise invite exactly
  that). `AiSettingsPanel.tsx`'s `savedApiKeySet` is scoped to the
  currently-selected provider for the same reason, not just whatever was
  loaded on mount. Setting `provider: null` clears the override
  entirely — there's deliberately no way to clear *only* the key while
  keeping a provider selected, since a stored-but-unusable
  half-configured provider is a worse state than "no override."
- **Audit-safe**: `company.ai_config_updated` (published on every
  `PUT /company/ai-config`) carries `{"provider": ..., "api_key_set":
  bool}` — never the raw key — since this codebase's audit-log consumer
  subscribes to *every* domain event unconditionally (`ROUTING_KEYS =
  ["#"]"`, see `docs/architecture/administration.md`) and a leaked key in
  an audit row would defeat the whole point of encrypting it at rest.
- **Frontend**: `frontend/src/features/company/panels/AiSettingsPanel.tsx`
  — a Provider select ("Platform default" plus every registered
  provider), a password-masked API Key field (shown for every provider
  except Ollama, which needs no key, only a Base URL), a Model field,
  and a Base URL field, with an explicit Save button (disabled until the
  form is both dirty and valid — every key-requiring provider needs
  *some* usable key, either already-saved or freshly entered, before
  Save is enabled). Azure OpenAI additionally shows a required
  Deployment Name field and an optional API Version field once selected
  (Save stays disabled without both a resource endpoint and a
  deployment name — a bare API key isn't enough to actually reach an
  Azure deployment).

## Fails as 503, not 404/400/500

`AiService._require_provider()` raises `AiNotConfiguredError` (new,
`domain/exceptions/__init__.py`) whenever the platform has no AI provider
configured. Mapped in `core/exceptions.py`'s `_STATUS_MAP` to
**503 Service Unavailable** — this is a deployment/configuration state
("the platform hasn't turned this on"), not a missing resource (404) or a
client mistake (400), so 503 is the honest signal for a client to
distinguish "retry with different input" from "this feature isn't
available here."

Every `AiService` method calls `_require_provider()` first, before any
other short-circuit (e.g. `suggest_tags`/`answer_from_knowledge_base`
returning early when there's nothing to work with) — so a disabled
platform always surfaces 503 consistently, never a silent empty result
that could be mistaken for "the AI checked and found nothing."

## One permission, not ten

`ai.use` (new) gates all ten `/ai/*` endpoints. Contrasted with Internal
Notes (M20), which reused `conversations.read`/`manage` rather than
minting a new permission — because a note is just another way to
interact with a conversation the agent already has access to, with no new
access-control question behind it. AI calls are different: every call
becomes a real, external, metered LLM API cost, so a company genuinely
needs "who can spend our AI budget" as an independent on/off switch per
role. But ten granular permissions (`ai.suggest_reply`, `ai.translate`,
...) would be fragmentation with no real access-control distinction behind
it — nobody needs to grant reply suggestions but not sentiment analysis.
One permission, seeded into `Owner` (implicitly, via the full-permission
set) and the default `Admin`/`Agent` roles.

## Advisory-only Next Best Action

`suggest_next_best_action` returns `{"action": ..., "reason": ...}` for
the agent to read and decide on — never auto-executed. Auto-applying an
AI-suggested action (e.g. closing a conversation on the model's say-so)
is a business-policy decision this milestone doesn't assume the answer
to. The `action` vocabulary
(`send_reply`/`escalate_to_queue`/`close_conversation`/
`no_action_needed`) deliberately mirrors the Workflow Engine's (M19)
action-naming style, so a company that *does* want to wire an "auto-apply
what the AI suggests" workflow later can do so on top of this without a
vocabulary to reconcile between two systems. Module-level
`_parse_next_best_action` falls back to `no_action_needed` whenever the
model's response doesn't parse into the exact expected two-line format —
a malformed model response degrades to "do nothing," never to a crash or
an unvalidated free-text action string.

## AI Autopilot (P4.18)

Autopilot is the one place in this system where AI output reaches a
customer **without a human reviewing it first** — every other AI feature
(reply suggestions, next best action) is explicitly advisory-only, per
the two sections above. Its whole design is therefore about being
conservative by default and handing back to a human at the first sign of
doubt.

**Three independent opt-ins, all required.** A conversation only ever
becomes AI-handled when `Company.settings.ai.autopilot.enabled` (the
Autopilot-specific switch, default off — read via
`domain/company_settings.py`'s `is_autopilot_enabled`), the routed-to
queue's own `Queue.autopilot_enabled` column (default false), **and**
`Company.settings.ai.enabled` (the company-wide "Enable AI Engine
features" master switch, default on — `is_ai_enabled`) are *all* on,
*and* a real provider is actually configured for that company
(`is_ai_available_for_company`). The per-queue half is a real FK-backed
column rather than a queue-id list inside the settings JSON blob,
consistent with every other queue-level behavior (`assignment_strategy`,
`sla_policy_id`); the Autopilot-specific half exists so Autopilot can be
paused everywhere instantly without touching every queue.

`is_ai_enabled` is checked in *two* places, not one: `_route_and_assign`
(so a conversation is never routed to Autopilot at all while the master
switch is off) and `ai_autopilot_consumer.handle_event` (so a
conversation already routed to Autopilot before the switch was flipped
off hands off on its very next inbound message, instead of continuing
to auto-reply). Before this, `is_ai_enabled` was enforced only at
`enforce_ai_rate_limit` — the agent-facing `/ai/*` endpoints (Suggest
reply, Summary) — so turning the master switch off silently left
Autopilot running: exactly the kind of gap a Healthcare/Financial/
Government compliance reviewer would treat as a false promise, since the
switch's own help text says it stops *all* AI-generated content.

**Where it plugs in.** `conversation_ingest_consumer.py`'s
`_route_and_assign` (which only ever runs for a brand-new conversation)
sets `Conversation.autopilot_active = True` and returns *instead of*
running `AssignmentEngine.select_agent` — an autopilot conversation is
deliberately never also assigned to a human, or both would think they
own it. All the actual reply-or-handoff work then happens in a separate
consumer, `ai_autopilot_consumer.py`, bound to `message.persisted`
(published for every INBOUND message). That event already fired for the
conversation's *first* message earlier in the same transaction, so the
first turn and every turn after it go through exactly the same code
path — no special-cased "first message" branch.

**The confidence contract.** `AiService.suggest_autopilot_reply` asks
for a three-line response (`REPLY:`/`CONFIDENCE:` 0-100/`HANDOFF:`
YES|NO) and parses it with `_parse_autopilot_reply`, which starts every
field at its *unsafe-to-send* default (`reply=None`, `confidence=0.0`,
`needs_handoff=True`) and only ever relaxes them on a cleanly-parsed
line. A malformed, truncated, or off-format response can therefore only
ever produce a handoff, never an unreviewed auto-send. The consumer
hands off if **any** of: the model asked for a handoff, no reply was
produced, or confidence < the company's threshold
(`settings.ai.autopilot.confidence_threshold`, default 0.7 — stored
0.0-1.0, shown as a percentage in the UI). Asking the model to
self-assess is the pragmatic option available at this abstraction layer:
`AiProvider.complete()` returns text, not token log-probs, and adding a
second scoring call per message would double the per-message AI cost for
a signal that's still ultimately the model's own opinion.

**Handoff path.** Clearing `autopilot_active` publishes
`conversation.autopilot_handoff_needed` (payload: conversation id,
`reason`, `confidence`), which the existing
`NotificationRuleRegistry` picks up via a new `AutopilotHandoffNeededRule`
— notifying the queue's department, mirroring
`ConversationTransferredRule`'s department branch (an autopilot
conversation is unassigned by construction, so there's no single agent
to target; with no department on the queue it simply becomes visible,
unassigned, in the Inbox like any other queued work). No new realtime
frame type was needed — the existing `notification` frame already
delivers instantly, with toast/browser/sound handling and
click-to-navigate already wired.

**Taking over.** Every existing path that assigns a human clears
`autopilot_active`: `ConversationRepository.claim()` (i.e. `pick()`),
`ConversationService.transfer()`, and `ConversationService.update()`'s
`assigned_agent_id` branch. There's deliberately no separate "take over
from AI" endpoint — picking up the conversation *is* taking over, and a
third assignment-mutation path would be a fourth place to keep this
invariant in sync. `ConversationSidebar.tsx` now renders a "Pick up"
button (gated on `conversations.pick`) whenever `assigned_agent_id` is
null and `autopilot_active` is false — the handoff notification
deep-links straight to `/conversations/:id`, and before this button
existed, an agent arriving that way had no ownership action on that
page at all (Transfer requires an existing assignment; Release requires
one too) and had to go back to the Inbox to find the row.

**Distinguishing AI replies from human ones.** `send_reply` takes an
`is_ai_generated: bool = False` parameter — the Autopilot consumer is
the only caller that passes `True` — which stamps
`Message.message_metadata = {"is_ai_generated": True}` on the persisted
row and the same key onto the `message.sent` event payload.
`MessageThread.tsx` renders a small "AI" chip next to any outbound
message carrying that flag. Before this, an Autopilot-sent reply was a
plain `OUTBOUND` message indistinguishable from a human agent's, in the
transcript, the messages API, and the audit log alike — no compliance
reviewer could answer "which replies to this customer were
machine-generated with no human in the loop" from any of the three.

**Idempotency.** `Conversation.autopilot_last_handled_message_id` records
the last inbound message the consumer acted on, so an at-least-once
redelivery of the same `message.persisted` event can't produce a
duplicate auto-reply or a duplicate handoff notification. Same
idempotency-marker convention as `csat_survey_sent_at`/`sla_*_breached_at`.

**Provider disappearing mid-conversation** (disabled, key revoked,
misconfigured) is handled explicitly rather than left to fail silently:
the consumer hands off with `reason="ai_unavailable"` instead of leaving
the customer's message permanently unanswered.

## Hallucination-proof auto-tagging

`suggest_tags` only ever picks from the company's real `Tag` catalog
(`available_tags`, fetched via a new `TagRepository.list_for_company`) —
never invents a tag name the model made up. The system prompt enumerates
the exact allowed list and asks the model to pick a comma-separated
subset (or `"none"`); the response is then matched back against that same
list case-insensitively (`{tag.lower(): tag for tag in available_tags}`),
so a model that free-associates a plausible-but-wrong casing or a tag
that isn't in the list is silently dropped rather than polluting the
catalog with a hallucinated entry.

## Knowledge Search and FAQ Search are the same capability

The roadmap names "Knowledge Search" and "FAQ Search" as separate
features. `answer_from_knowledge_base` covers both: answering a question
by grounding a completion in a set of help-center articles is one
capability regardless of whether a human calls the source material
"knowledge base articles" or "FAQs" — this codebase's Knowledge Base
(M20) never modeled a distinct "FAQ" entity for a parallel search to be
built against, so building two code paths would just be two names for
one behavior. Returns a static "No relevant knowledge base articles were
found." without calling the provider at all when there are no candidate
articles — no wasted API call for a search that can't possibly be
grounded in anything.

## Usage tracking via the event bus, not a new table

Every `AiService` method publishes an `ai.completed` domain event
(`{"operation": "<method name>"}` payload, `aggregate_type="conversation"`
when a `conversation_id` is available, else `"ai_operation"`) after
finishing — this is the "AI completed" event named in the original
event-bus mandate from M10. Rather than building a dedicated AI-usage
table in this milestone, usage tracking rides the same durable outbox
already flowing to every other consumer; a future Reports & Analytics
"AI Reports" view (M23) can build off this event stream directly. No new
tables were added by this milestone's migration — it's permission-seed
only.

## Activation modes, and one decision shared by three triggers (2026-07-28)

Autopilot originally had exactly one way to engage: a brand-new
conversation routed into a queue with `autopilot_enabled`. The decision
logic lived inside `ai_autopilot_consumer`, which binds
`message.persisted` — so the only thing that could ever make Autopilot
act was a *new inbound customer message*.

That shape does not fit either mode added here:

- **SLA** fires precisely *because* nobody replied. There is no inbound
  message coming; waiting for one would mean never replying at all.
- **Agent request** is a human clicking a button, not a message arriving.

So the reply-or-hand-off decision moved to
`application/services/autopilot_service.py`, parameterized by
`AutopilotTrigger`, and the original consumer became one of three
callers:

| Trigger | Caller | Bound to |
|---|---|---|
| `new_message` | `ai_autopilot_consumer` | `message.persisted` |
| `sla` | `autopilot_sla_consumer` | `conversation.sla_warning`, `conversation.sla_breached` |
| `agent_request` | `POST /conversations/{id}/autopilot` | — (`conversations.manage`) |

**Three independent modes under one master switch.**
`settings.ai.autopilot` gains `activate_on_new_conversation` (defaults
**true** — the behavior that predates modes, so existing companies are
unaffected), `activate_on_sla` and `activate_on_agent_request` (both
default false). Any combination may be on; all three off means Autopilot
is idle even while `enabled` is true, which the settings UI warns about.

**Per-mode gating lives in `AutopilotService`, not in each caller** — one
source of truth, so the three triggers cannot drift on what "enabled"
means. `new_message` is deliberately exempt from its own mode check: that
flag governs *activation* on a new conversation (enforced at routing time
in `conversation_ingest_consumer`), and a conversation Autopilot already
owns must keep being answered even if an admin later turns that mode off
— the alternative strands it mid-thread with nobody assigned.

**Idempotency differs per trigger.** `new_message` dedupes on
`autopilot_last_handled_message_id` vs. the inbound message being
answered. The SLA trigger has no message of its own, and comparing ids
would not work either — replying *adds* a message, so after the first run
the newest id is Autopilot's own reply. Instead it checks **direction**:
it only acts when the newest message in the thread is inbound, i.e. the
customer is the one waiting. That is what makes a warning and its
follow-up breach produce one reply rather than two. An agent request is
an explicit human action and is never deduped.

**Activation happens only on success.** The SLA and agent-request
triggers set `autopilot_active` after a usable reply exists, not before —
a run that hands straight back must not strip a conversation from its
agent for nothing.

Note there is deliberately no `Queue.autopilot_enabled` requirement on
the SLA or agent-request paths: that flag governs which queues hand
*brand-new* conversations to AI instead of to a human, a different
decision from "nothing has happened for too long" or "this agent asked".

## Per-agent usage tracking and AI provenance (2026-07-28)

The `ai.completed` event now carries `actor_user_id` (every
`/api/v1/ai/` endpoint passes the calling agent through), and a
successful Autopilot run publishes a new
`conversation.autopilot_replied` carrying `trigger`, `confidence`,
`message_id` and the conversation's `assigned_agent_id`. The audit-log
consumer binds `#`, so both are audited with no new audit machinery.

`agent_ai_daily_stats` mirrors `ai_daily_stats` with an `agent_id`
dimension, keyed `(company_id, agent_id, stat_date, operation)` so the
existing atomic `INSERT … ON CONFLICT DO UPDATE` increment has a
constraint to conflict on. `agent_id` is **NOT NULL**: Postgres treats
NULLs as distinct in a unique constraint, so a nullable column would
insert a new row per event instead of incrementing. Usage with nobody to
attribute it to therefore stays in the company-wide table only.
Attribution order is: the acting user's agent profile, else — for an
unattended Autopilot run — the conversation's assigned agent, else
company-wide only.

Autopilot runs are counted under synthetic `autopilot_<trigger>`
operations. The prefix and derivation live in `domain/ai_operations.py`
because the string is assembled in the reporting consumer and matched in
the reporting repository — exactly the pair that silently drifts.

**Two distinct provenance flags on an outbound message**, so an
administrator can tell three cases apart:
`message_metadata.is_ai_generated` (Autopilot composed and sent it, no
human involved) and `is_ai_assisted` (an agent's own reply whose draft
came from an AI suggestion, edited or not — the composer sets it and
clears it when the draft is emptied). Each key is omitted when false, so
a purely manual reply keeps its historical empty `{}` metadata and the
frontend's strict `=== true` checks keep working.

`GET /reports/ai/usage` returns usage by operation, by agent, and as a
trend bucketed daily/weekly/monthly. Bucketing is folded in the service
layer, not SQL: `date_trunc` is Postgres-only and the repositories stay
portable to the SQLite the test suite runs on. It is a *new* endpoint
rather than a widening of `GET /reports/ai`, whose flat
`[{operation, calls}]` array both the existing panel and both export
formats consume.

## API surface

Ten endpoints under `/api/v1/ai/`, all gated by
`Depends(require_permission("ai.use"))`:

| Endpoint | Capability |
|----------|------------|
| `POST /conversations/{id}/reply-suggestion` | Reply Suggestions |
| `POST /conversations/{id}/summary` | Conversation Summary |
| `POST /conversations/{id}/next-best-action` | Next Best Action |
| `POST /translate` | Translation |
| `POST /detect-language` | Language Detection |
| `POST /sentiment` | Sentiment Analysis |
| `POST /suggest-tags` | Auto Tagging |
| `POST /improve-grammar` | Grammar Improvement |
| `POST /rewrite-professional` | Professional Rewrite |
| `POST /knowledge-search` | Knowledge Search + FAQ Search |

The three conversation-scoped endpoints build their prompt from the
conversation's last 50 messages (`_conversation_history`, oldest-first),
reusing `ConversationService.list_messages` — which already 404s via its
own internal `ConversationService.get()` call, so the endpoint doesn't
redundantly re-check existence. `suggest-tags` fetches the company's tag
catalog via the new `get_tag_repository` dependency; `knowledge-search`
fetches up to 5 matching *published* articles via
`KnowledgeService.list_articles(search=query, ...)`.

## Testing approach

Providers are tested against `httpx.MockTransport` (no new dependency —
`httpx` is already used this way for every other HTTP-based channel
provider, e.g. `test_whatsapp_provider.py`), verifying the exact request
shape (endpoint path, auth header, model/payload fields) each provider
sends and how each parses a response. `AiService` is tested against a
hand-built `FakeAiProvider` test double — no HTTP involved — focused on
prompt-shaping, response normalization (sentiment/next-best-action
fallback behavior, tag-matching against an allowed list), and that
`ai.completed` is published with the right payload. The API layer is
tested end-to-end against the real app with `get_ai_provider` overridden
to a fake provider, covering: authentication is required, every endpoint
surfaces 503 when `ai_provider` is left at its `"disabled"` default (the
out-of-the-box state), and each capability's happy path including tag/
article filtering against real seeded data.

## Verification performed

49 new tests added (375 → 424 passing), all green under `pytest -q`,
`ruff check`/`ruff format --check`, and `mypy src`:

- `tests/unit/test_ai_providers.py` (11 tests) — OpenAI/Claude/Ollama
  request shape, model selection, response parsing, health-check
  true/false paths.
- `tests/unit/test_ai_service.py` (19 tests) — the `AiNotConfiguredError`
  path, every capability's happy path and event payload, sentiment
  fallback-to-neutral, next-best-action fallback-to-no-action-needed
  (both on an unknown action and on an unparseable response),
  tag-matching against an allowed list (including case-insensitivity and
  a `"none"` response), and knowledge-search's empty-candidates
  short-circuit.
- `tests/integration/test_ai_api.py` (19 tests) — unauthenticated access
  is rejected, every endpoint 503s while AI is disabled (the default),
  every capability's happy path against a fake provider, a 404 for an
  unknown conversation, tag suggestions filtered to a real company tag
  catalog, and knowledge search grounded in a real published article
  (plus its no-articles static-message fallback).

The migration (`a7b8c9d0e1f2`, seeding `ai.use` into `permissions`) was
verified against the real running Postgres via
`docker compose exec backend alembic upgrade head`, then a downgrade and
re-upgrade cycle. No docker-compose changes were needed — the AI Engine
is synchronous request/response only, with no new Celery consumer
process, unlike M19/M21's event-bus consumers.

### Per-company provider override

15 new tests: `tests/unit/test_ai_factory.py` (7) — precedence between a
company override and the platform default across all three providers,
including the "override present but missing a field falls back to that
one platform setting" case and Ollama's base-URL-only (no API key)
credential shape. `tests/integration/test_company_api.py`'s new
`TestAiConfig` class (8) — default (no-override) state, view-but-not-edit
for a non-`company.manage` caller, the raw key never appearing in any
response body, changing the model without resending the key preserving
it, clearing the provider reverting to the default state, Ollama needing
no key, and a 422 on an unrecognized provider name.

The new migration (`b2c3d4e5f6a7`, adding `companies.ai_config` as a
`LargeBinary` column) was verified against the real running Postgres via
`docker compose exec backend alembic upgrade head` and a downgrade/
re-upgrade cycle, the same bar every migration in this codebase is held
to.

### Expanded provider support (P4.17): Gemini, Azure OpenAI, Mistral, Groq, DeepSeek

Added 5 new `AiProvider` implementations alongside the original three —
no changes to `domain/ai_provider.py`, `AiService`, `api/schemas/ai.py`,
or `api/v1/endpoints/ai.py` were needed, exactly as this abstraction was
designed to allow. Touched instead: `infrastructure/ai/providers/`
(5 new files + the shared `_openai_compatible.py` base + `__init__.py`'s
discovery imports), `infrastructure/ai/factory.py` (new
`_credentials_for()`/`build_ai_provider_for_company()` branches, Azure
OpenAI's being the one genuinely new shape — an extra
`deployment_name`/`api_version` pair alongside the existing
`api_key`/`base_url`), `core/config.py` (widened `ai_provider` `Literal`
+ 12 new per-provider `Settings` fields), `.env.example`,
`api/schemas/company.py` (widened `AiConfigProvider` `Literal` + two new
optional fields on both request/response schemas),
`CompanyService.update_ai_config` and its endpoint (threading the two
new fields through), and the frontend (`types.ts`, `AiSettingsPanel.tsx`
— a generalized "does this provider need a key" check plus Azure's two
extra conditional fields).

No migration was needed for `Company.ai_config` itself (already a
schema-less encrypted JSON blob — the two new keys are additive and
backward compatible; existing rows with only the original four keys
remain valid, read back as `None` for the two new ones).

37 new tests added, all green under `pytest -q`, `ruff check`, and
`mypy src`:

- `tests/unit/test_ai_providers.py` (+16) — one `TestXProvider` class
  per new provider: Groq/DeepSeek/Mistral's shared request/response
  shape via `OpenAiCompatibleProvider` (mocked at the shared
  `_openai_compatible` module, not each provider's own module, since
  that's where the HTTP call actually executes), Gemini's `contents`/
  `systemInstruction` shape and query-parameter API key, and Azure
  OpenAI's deployment-name-in-the-URL/`api-key`-header/`api-version`
  scheme (including a custom-API-version case and confirming no
  `"model"` field is ever sent in the body).
- `tests/unit/test_ai_factory.py` (+4) — Gemini as a representative
  simple "api_key + optional base_url" provider (company override and
  platform-default paths), and Azure OpenAI as the one provider needing
  its extra fields threaded through both the company-override and
  platform-default-fallback paths.
- `tests/integration/test_company_api.py`'s `TestAiConfig` (+2) — each
  of the 5 new provider names is accepted end-to-end, and Azure OpenAI's
  `deployment_name`/`api_version` round-trip correctly (set, returned,
  never exposing the key).
- `tests/integration/test_admin_plugins_api.py` — the existing
  `test_lists_every_registered_plugin_type` test's exact-set assertion
  on `ai_providers` was updated to the full 8-provider list (this is the
  Admin Plugins overview page, which enumerates every registered
  provider name — a real, if incidental, consumer of the registry that
  needed updating alongside the registry itself).
- Frontend: `CompanySettingsPage.test.tsx` (+2) — every new provider
  appears as a select option, and Azure OpenAI's Save button stays
  disabled until both a resource endpoint *and* a deployment name are
  filled in, not just an API key.

### AI Autopilot (P4.18)

29 new backend tests + 3 frontend, all green under `pytest -q`,
`ruff check`, `mypy src`, `tsc`, `eslint`, `vitest`, and `vite build`:

- `tests/integration/test_ai_autopilot_consumer.py` (7, new file) — the
  high-confidence auto-send path (an OUTBOUND `Message` row actually
  persisted, `autopilot_active` still true, still unassigned), the
  low-confidence handoff path (no message sent, `autopilot_active`
  cleared, `conversation.autopilot_handoff_needed` published with
  `reason="low_confidence"`), `HANDOFF: YES` overriding a high
  confidence, a completely unparseable model response defaulting to
  handoff rather than auto-send, at-least-once redelivery not
  double-sending, a non-autopilot conversation being ignored entirely
  (asserted by making the provider factory *raise* if called), and a
  malformed event payload being ignored.
- `tests/integration/test_assignment_and_routing.py` (+3) — an
  autopilot-enabled queue setting `autopilot_active` and skipping human
  assignment *despite an eligible online agent existing*, plus both
  fallback paths (company-wide switch off; no provider configured)
  assigning a human normally.
- `tests/integration/test_notification_consumer.py` (+2) — the handoff
  event notifying every agent in the queue's department (with the
  reason-specific body text), and creating no notification when the
  queue has no department.
- `tests/unit/test_ai_service.py` (+6) — `_parse_autopilot_reply`'s
  well-formed path, `HANDOFF: YES` winning over high confidence, a blank
  `REPLY:` line parsing to `None` (not `""`), a `%`-suffixed confidence
  being tolerated, an out-of-range confidence being ignored while other
  lines still parse, and a completely unparseable response defaulting to
  the conservative handoff triple.
- `tests/unit/test_company_settings.py` (+4) and
  `tests/unit/test_ai_factory.py` (+3) — the new settings readers'
  defaults/explicit values/out-of-range/non-numeric/null-section cases,
  and `is_ai_available_for_company`.
- `tests/integration/test_conversations_api.py` (+2) — `pick()` and
  `transfer()` each clearing `autopilot_active`.
- `tests/integration/test_queues_api.py` (+3) — `autopilot_enabled`
  defaulting to false on create, settable on create, and togglable both
  ways on update.
- Frontend `CompanySettingsPage.test.tsx` (+3) — Autopilot off by
  default with the threshold field hidden, enabling + saving a
  threshold, and an out-of-range threshold disabling Save.

The migration (`8b9c0d1e2f3a`, adding `conversations.autopilot_active`/
`conversations.autopilot_last_handled_message_id`/
`queues.autopilot_enabled`) is additive with `server_default="false"` on
both booleans, so it applies cleanly to existing rows. A new
`ai-autopilot-consumer` service was added to both `docker-compose.yml`
and `docker-compose.prod.yml` (both validated via
`docker compose config`), mirroring `csat-dispatch-consumer`'s shape —
it needs Redis alongside Postgres/RabbitMQ for the same reason (building
a `ConversationService` requires a realtime publisher).
