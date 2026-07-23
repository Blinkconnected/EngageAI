"""``AiService`` — every AI Engine capability, built once on top of the
minimal ``AiProvider.complete()`` contract. See
``docs/architecture/ai-engine.md``.

Each method publishes an ``ai.completed`` domain event after finishing
(operation type + conversation id if applicable) — this is the "AI
completed" event named in the project's original event-bus mandate, and
lets a future Reports & Analytics "AI Reports" view (M23) build off the
durable event stream without this service needing its own usage-logging
table.
"""

from uuid import UUID

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import AiNotConfiguredError

_SENTIMENTS = frozenset({"positive", "neutral", "negative"})
_NEXT_BEST_ACTIONS = frozenset(
    {"send_reply", "escalate_to_queue", "close_conversation", "no_action_needed"}
)


class AiService:
    def __init__(self, *, provider: AiProvider | None, events: DomainEventPublisher) -> None:
        self._provider = provider
        self._events = events

    def _require_provider(self) -> AiProvider:
        if self._provider is None:
            raise AiNotConfiguredError()
        return self._provider

    async def _publish_completed(
        self, *, operation: str, company_id: UUID, conversation_id: UUID | None
    ) -> None:
        await self._events.publish(
            DomainEvent(
                event_type="ai.completed",
                company_id=company_id,
                aggregate_type="conversation" if conversation_id else "ai_operation",
                aggregate_id=conversation_id,
                payload={"operation": operation},
            )
        )

    async def suggest_reply(
        self, *, company_id: UUID, conversation_id: UUID, conversation_history: str
    ) -> str:
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                "You are a helpful, professional customer support agent. Draft a concise, "
                "polite reply to the customer's most recent message, using only information "
                "present in the conversation history."
            ),
            prompt=conversation_history,
            max_tokens=500,
            temperature=0.4,
        )
        await self._publish_completed(
            operation="suggest_reply", company_id=company_id, conversation_id=conversation_id
        )
        return result

    async def summarize_conversation(
        self, *, company_id: UUID, conversation_id: UUID, conversation_history: str
    ) -> str:
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                "Summarize this customer support conversation in 2-4 sentences: what the "
                "customer wants, what's been done so far, and what's still outstanding."
            ),
            prompt=conversation_history,
            max_tokens=300,
            temperature=0.2,
        )
        await self._publish_completed(
            operation="summarize_conversation",
            company_id=company_id,
            conversation_id=conversation_id,
        )
        return result

    async def translate(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        text: str,
        target_language: str,
    ) -> str:
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                f"Translate the user's text to {target_language}. Return only the "
                "translation, with no explanation or preamble."
            ),
            prompt=text,
            max_tokens=1000,
            temperature=0.2,
        )
        await self._publish_completed(
            operation="translate", company_id=company_id, conversation_id=conversation_id
        )
        return result

    async def detect_language(
        self, *, company_id: UUID, conversation_id: UUID | None, text: str
    ) -> str:
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                "Identify the language of the user's text. Respond with only the language "
                "name in English (e.g. 'Spanish', 'Japanese'), nothing else."
            ),
            prompt=text,
            max_tokens=10,
            temperature=0.0,
        )
        await self._publish_completed(
            operation="detect_language", company_id=company_id, conversation_id=conversation_id
        )
        return result.strip().rstrip(".")

    async def analyze_sentiment(
        self, *, company_id: UUID, conversation_id: UUID | None, text: str
    ) -> str:
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                "Classify the sentiment of the user's text as exactly one word: "
                "'positive', 'neutral', or 'negative'. Respond with only that word."
            ),
            prompt=text,
            max_tokens=5,
            temperature=0.0,
        )
        await self._publish_completed(
            operation="analyze_sentiment", company_id=company_id, conversation_id=conversation_id
        )
        normalized = result.strip().lower().rstrip(".")
        return normalized if normalized in _SENTIMENTS else "neutral"

    async def suggest_tags(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        text: str,
        available_tags: list[str],
    ) -> list[str]:
        """Only ever picks from ``available_tags`` (the company's real Tag
        catalog, M8) — never invents a new tag name, avoiding a hallucinated
        tag silently polluting the catalog."""
        provider = self._require_provider()
        if not available_tags:
            return []
        result = await provider.complete(
            system=(
                "Given this list of allowed tags: "
                f"{', '.join(available_tags)}. "
                "Pick the ones that apply to the user's text. Respond with only a "
                "comma-separated list of the applicable tags from that list, or 'none' if "
                "none apply."
            ),
            prompt=text,
            max_tokens=100,
            temperature=0.0,
        )
        await self._publish_completed(
            operation="suggest_tags", company_id=company_id, conversation_id=conversation_id
        )
        if result.strip().lower() == "none":
            return []
        allowed = {tag.lower(): tag for tag in available_tags}
        suggested = [part.strip() for part in result.split(",")]
        return [allowed[name.lower()] for name in suggested if name.lower() in allowed]

    async def answer_from_knowledge_base(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        query: str,
        candidate_articles: list[tuple[str, str]],
    ) -> str:
        """Covers both "Knowledge Search" and "FAQ Search" — the same
        capability (answer a question by grounding in a set of help-
        center articles), not two separate systems; this project's
        Knowledge Base (M20) never named a distinct "FAQ" entity for a
        parallel search to be built against."""
        provider = self._require_provider()
        if not candidate_articles:
            return "No relevant knowledge base articles were found."
        articles_text = "\n\n".join(
            f"Article: {title}\n{body}" for title, body in candidate_articles
        )
        result = await provider.complete(
            system=(
                "Answer the user's question using only the information in the provided "
                "knowledge base articles below. If the articles don't contain an answer, "
                "say so rather than guessing.\n\n" + articles_text
            ),
            prompt=query,
            max_tokens=500,
            temperature=0.2,
        )
        await self._publish_completed(
            operation="answer_from_knowledge_base",
            company_id=company_id,
            conversation_id=conversation_id,
        )
        return result

    async def improve_grammar(
        self, *, company_id: UUID, conversation_id: UUID | None, text: str
    ) -> str:
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                "Fix any spelling and grammar mistakes in the user's text. Keep the meaning "
                "and tone unchanged. Respond with only the corrected text."
            ),
            prompt=text,
            max_tokens=1000,
            temperature=0.2,
        )
        await self._publish_completed(
            operation="improve_grammar", company_id=company_id, conversation_id=conversation_id
        )
        return result

    async def rewrite_professionally(
        self, *, company_id: UUID, conversation_id: UUID | None, text: str
    ) -> str:
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                "Rewrite the user's text in a more professional, courteous tone suitable for "
                "customer support, keeping the same meaning. Respond with only the rewritten "
                "text."
            ),
            prompt=text,
            max_tokens=1000,
            temperature=0.3,
        )
        await self._publish_completed(
            operation="rewrite_professionally",
            company_id=company_id,
            conversation_id=conversation_id,
        )
        return result

    async def suggest_next_best_action(
        self, *, company_id: UUID, conversation_id: UUID, conversation_history: str
    ) -> dict[str, str]:
        """Advisory only — surfaced to the agent to review, never
        auto-executed. Auto-executing an AI-suggested action (e.g.
        closing a conversation) is a business-policy decision this
        milestone doesn't assume; the suggested ``action`` uses the same
        vocabulary the M19 Workflow Engine's actions already use
        (``assign_to_queue``-style naming), so a company could wire an
        "auto-apply" workflow on top of this later without a new
        vocabulary to reconcile."""
        provider = self._require_provider()
        result = await provider.complete(
            system=(
                "Given this customer support conversation, suggest the single best next "
                "action. Respond in exactly this format on two lines:\n"
                "action: <one of send_reply, escalate_to_queue, close_conversation, "
                "no_action_needed>\n"
                "reason: <one short sentence>"
            ),
            prompt=conversation_history,
            max_tokens=150,
            temperature=0.2,
        )
        await self._publish_completed(
            operation="suggest_next_best_action",
            company_id=company_id,
            conversation_id=conversation_id,
        )
        return _parse_next_best_action(result)


def _parse_next_best_action(raw: str) -> dict[str, str]:
    action = "no_action_needed"
    reason = raw.strip()
    for line in raw.splitlines():
        lowered = line.strip().lower()
        if lowered.startswith("action:"):
            candidate = line.split(":", 1)[1].strip().lower()
            if candidate in _NEXT_BEST_ACTIONS:
                action = candidate
        elif lowered.startswith("reason:"):
            reason = line.split(":", 1)[1].strip()
    return {"action": action, "reason": reason}
