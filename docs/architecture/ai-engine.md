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
exactly: `@AiProviderRegistry.register("openai"|"claude"|"ollama")` class
decorators, discovered via a blanket
`import infrastructure.ai.providers  # noqa: F401` at the point of use.

## Platform-level configuration, not per-company

`ChannelConfig` (WhatsApp, Telegram, email, ...) is inherently
per-tenant — each company has its own WhatsApp Business number, its own
SMTP box. The AI Engine is different: it's a platform capability a
company either has turned on or doesn't, with one shared API key/model
per deployment. New `settings.ai_provider`
(`"openai" | "claude" | "ollama" | "disabled"`, defaulting to
`"disabled"`), `settings.ai_model`, `settings.ai_default_max_tokens`, and
per-provider credential/base-URL settings
(`openai_api_key`/`anthropic_api_key`/`ollama_base_url`/...) follow the
same environment-configured pattern `settings.smtp_*` (M21) already
established for platform-level, not per-tenant, capabilities. A
per-company "bring your own AI provider" model is a real possible future
need but isn't built speculatively here — nothing about `AiProvider`'s
credential-carrying constructor blocks adding it later without a breaking
change.

`build_ai_provider(settings) -> AiProvider | None` returns `None` when
`ai_provider == "disabled"` — the default, meaning a fresh deployment has
AI Engine features off until an operator configures a provider.

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
