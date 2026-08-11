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

import re
from dataclasses import dataclass
from uuid import UUID

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import AiNotConfiguredError

_SENTIMENTS = frozenset({"positive", "neutral", "negative"})
_NEXT_BEST_ACTIONS = frozenset(
    {"send_reply", "escalate_to_queue", "close_conversation", "no_action_needed"}
)


@dataclass(frozen=True, slots=True)
class AutopilotReply:
    """The model's self-assessed answer to "can I handle this myself?" —
    see ``_parse_autopilot_reply``'s defensive fallback for why
    ``needs_handoff=True``/``confidence=0.0`` is always the safe default
    on anything unparseable, never an auto-send."""

    reply: str | None
    confidence: float
    needs_handoff: bool


class AiService:
    def __init__(self, *, provider: AiProvider | None, events: DomainEventPublisher) -> None:
        self._provider = provider
        self._events = events

    def _require_provider(self) -> AiProvider:
        if self._provider is None:
            raise AiNotConfiguredError()
        return self._provider

    async def _publish_completed(
        self,
        *,
        operation: str,
        company_id: UUID,
        conversation_id: UUID | None,
        actor_user_id: UUID | None = None,
    ) -> None:
        # actor_user_id is what makes per-agent AI usage reporting
        # possible: the reporting consumer resolves it to an Agent and
        # counts the call against them. It is legitimately None for AI
        # Autopilot's own SLA-triggered runs, which no human initiated —
        # those are attributed to the conversation's assigned agent, if
        # any, by the consumer instead.
        await self._events.publish(
            DomainEvent(
                event_type="ai.completed",
                company_id=company_id,
                aggregate_type="conversation" if conversation_id else "ai_operation",
                aggregate_id=conversation_id,
                actor_user_id=actor_user_id,
                payload={"operation": operation},
            )
        )

    async def suggest_reply(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        conversation_history: str,
        actor_user_id: UUID | None = None,
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
            operation="suggest_reply",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
        )
        return result

    async def suggest_autopilot_reply(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        conversation_history: str,
        business_profile: str | None = None,
        grounding: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> AutopilotReply:
        """Like ``suggest_reply``, but for AI Autopilot (see
        docs/architecture/ai-engine.md): asks the model to also
        self-assess its own confidence and whether a human should take
        over instead, in the same completion — one API call, not two.
        Never trusted blindly: ``_parse_autopilot_reply`` defaults to
        ``needs_handoff=True``/``confidence=0.0``/``reply=None`` on
        anything that doesn't parse, so a malformed response can only
        ever result in a human handoff, never an unreviewed auto-send.

        **``business_profile`` and ``grounding`` are what the model is
        allowed to know.** Before they existed this prompt said "using
        only information present in the conversation history" and was
        handed nothing else — so a customer who asked the company's name,
        address or opening hours was asking for something the model had
        no way to know and no instruction to decline. It answered anyway:
        invented hours, an invented product list, and the bracketed
        ``[Company name]`` placeholder that a model emits when it is
        composing around a fact it does not have. Every one of those went
        straight to a customer unreviewed, because this path has no human
        in it.

        Retrieval alone would not have fixed it. A knowledge base can be
        empty, or simply not contain the answer, and the failure being
        prevented is precisely what the model does when the answer is
        *absent*. So the refusal rule below is unconditional and stated
        whether or not anything was retrieved: state no business fact
        that is not written above, never invent, never bracket a
        placeholder, and hand off instead. The bracket rule is explicit
        because a placeholder is the one failure that looks like
        cooperation — a blank would have been caught by the confidence
        check, whereas ``[Company name]`` reads as a completed reply.
        """
        provider = self._require_provider()
        sections = [
            "You are an AI customer support agent handling this conversation "
            "autonomously, with no human reviewing your reply before it's sent."
        ]
        if business_profile:
            sections.append("ABOUT THIS BUSINESS (authoritative):\n" + business_profile)
        if grounding:
            sections.append(grounding)
        sections.append(
            "FACTUAL GROUNDING — these rules override helpfulness:\n"
            "- The ONLY facts about this business you may state are those written "
            "above and those the customer stated themselves. Everything above is "
            "the complete set of what you know.\n"
            "- Never guess, estimate or infer a business fact — opening hours, "
            "prices, addresses, phone numbers, product ranges, policies, delivery "
            "times, stock. Plausible is not the same as true.\n"
            "- Never write a placeholder of any kind. Square brackets, a blank to "
            "be filled in later, or a generic stand-in like 'our company' in place "
            "of a name you were not given: if you are reaching for one, the fact is "
            "missing and this is a handoff.\n"
            "- If the customer asks for a fact you were not given above, do not "
            "answer it. Set HANDOFF: YES.\n"
            "- Reply in the language the customer wrote in."
        )
        sections.append(
            "Respond in EXACTLY this format on three lines:\n"
            "REPLY: <your proposed reply to the customer's most recent message, or "
            "leave blank if you cannot help>\n"
            "CONFIDENCE: <a whole number 0-100 for how confident you are this reply "
            "fully and correctly resolves the customer's message>\n"
            "HANDOFF: <YES if a human should take over instead — for example a "
            "refund, a complaint, anything requiring account changes, any question "
            "asking for a business fact you were not given above, or if you're "
            "not fully sure — or NO otherwise>"
        )
        result = await provider.complete(
            system="\n\n".join(sections),
            prompt=conversation_history,
            max_tokens=500,
            temperature=0.2,
        )
        await self._publish_completed(
            operation="suggest_autopilot_reply",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
        )
        return _parse_autopilot_reply(result)

    async def summarize_conversation(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        conversation_history: str,
        actor_user_id: UUID | None = None,
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
            actor_user_id=actor_user_id,
        )
        return result

    async def translate(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        text: str,
        target_language: str,
        actor_user_id: UUID | None = None,
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
            operation="translate",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
        )
        return result

    async def detect_language(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        text: str,
        actor_user_id: UUID | None = None,
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
            operation="detect_language",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
        )
        return result.strip().rstrip(".")

    async def analyze_sentiment(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        text: str,
        actor_user_id: UUID | None = None,
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
            operation="analyze_sentiment",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
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
        actor_user_id: UUID | None = None,
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
            operation="suggest_tags",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
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
        candidate_faqs: list[tuple[str, str]] | None = None,
        actor_user_id: UUID | None = None,
    ) -> str:
        """Answers from the company's own published material.

        This covered "Knowledge Search" and "FAQ Search" with one call
        because no FAQ entity existed to search — *"this project's
        Knowledge Base never named a distinct FAQ entity for a parallel
        search to be built against"*. One exists now, so this grounds on
        both, and the ordering is the point rather than a detail.

        **FAQs come first, and are labelled as approved answers.** An FAQ
        is a complete answer somebody wrote and published for exactly this
        question; an article passage is raw material the model has to
        summarise. Handing the model both without saying which is which
        invites it to paraphrase a curated answer into an uncurated one —
        which is how a company that carefully worded its refund policy
        finds the platform explaining refunds in its own words instead.
        """
        provider = self._require_provider()
        faqs = candidate_faqs or []
        if not candidate_articles and not faqs:
            return "No relevant knowledge base articles were found."

        sections: list[str] = []
        if faqs:
            sections.append(
                "APPROVED ANSWERS (prefer these; they are published answers to this "
                "exact kind of question — reuse their wording where it fits):\n"
                + "\n\n".join(f"Q: {question}\nA: {answer}" for question, answer in faqs)
            )
        if candidate_articles:
            sections.append(
                "REFERENCE MATERIAL (background; summarise only what is needed):\n"
                + "\n\n".join(f"Article: {title}\n{body}" for title, body in candidate_articles)
            )
        articles_text = "\n\n".join(sections)

        result = await provider.complete(
            system=(
                "Answer the user's question using only the information provided below. "
                "If it does not contain an answer, say so rather than guessing.\n\n" + articles_text
            ),
            prompt=query,
            max_tokens=500,
            temperature=0.2,
        )
        await self._publish_completed(
            operation="answer_from_knowledge_base",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
        )
        return result

    async def improve_grammar(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        text: str,
        actor_user_id: UUID | None = None,
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
            operation="improve_grammar",
            company_id=company_id,
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
        )
        return result

    async def rewrite_professionally(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID | None,
        text: str,
        actor_user_id: UUID | None = None,
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
            actor_user_id=actor_user_id,
        )
        return result

    async def suggest_next_best_action(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        conversation_history: str,
        actor_user_id: UUID | None = None,
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
            actor_user_id=actor_user_id,
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


#: An unfilled placeholder, in the forms a model actually emits: square
#: or curly brackets around a short span. Matched on the *reply text*, as
#: a backstop to the prompt rule forbidding them.
#:
#: A prompt rule is a strong tendency, not a guarantee, and this
#: particular failure is the one that reaches a customer looking like a
#: finished answer — "اسم الشركة هو [اسم الشركة]" is well-formed, fluent,
#: confidently self-scored, and worthless. A rule the model follows 95%
#: of the time still means one customer in twenty, so the check is also
#: made mechanically where it cannot be talked out of.
#:
#: Scoped so it fires on placeholders and not on the legitimate reasons a
#: reply contains brackets. A placeholder is a *description of a missing
#: fact* — "[Company name]", "[اسم الشركة]", "{address}" — so the span
#: must contain at least one letter and consist only of letters, spaces
#: and the separators that appear in placeholder names (``_``, ``-``,
#: ``/``). That deliberately spares an order reference like ``[#12345]``
#: or ``[REF-2024]``: digits and ``#`` are how a real identifier is
#: written, and holding a genuine reply because it cites one would trade
#: this bug for a quieter one.
#:
#: The span must also be digit-free. A placeholder names a *concept*
#: ("Company name", "عنوان الموقع") and a reference carries a *number*
#: ("[#12345]", "[REF-2024]"); excluding digits outright separates the
#: two more reliably than trying to describe every reference format a
#: company might use.
#:
#: Unicode-aware by default in Python 3 — the letter classes match Arabic
#: script, which is the language this defect was found in.
_PLACEHOLDER_PATTERN = re.compile(
    r"[\[\{]\s*"  # opening bracket
    r"[^\W\d_]"  # first character must be a letter (any script)
    r"[^\d\]\}\n]{0,58}"  # then anything but digits, newlines or a bracket
    r"[\]\}]",  # closing bracket
    re.UNICODE,
)


def _contains_placeholder(reply: str) -> bool:
    return _PLACEHOLDER_PATTERN.search(reply) is not None


def _parse_autopilot_reply(raw: str) -> AutopilotReply:
    """Conservative by construction: every field starts at the "hand this
    off to a human" default, and only a cleanly-parsed, in-range
    CONFIDENCE line plus an explicit HANDOFF: NO can ever produce an
    auto-sendable result — any missing/malformed line leaves the unsafe
    default in place rather than guessing.

    A reply containing an unfilled placeholder is forced to a handoff
    here regardless of what the model scored itself — see
    ``_PLACEHOLDER_PATTERN``."""
    reply: str | None = None
    confidence = 0.0
    needs_handoff = True
    for line in raw.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("reply:"):
            value = stripped.split(":", 1)[1].strip()
            reply = value or None
        elif lowered.startswith("confidence:"):
            value = stripped.split(":", 1)[1].strip().rstrip("%")
            try:
                parsed = float(value)
            except ValueError:
                continue
            if 0.0 <= parsed <= 100.0:
                confidence = parsed / 100.0
        elif lowered.startswith("handoff:"):
            value = stripped.split(":", 1)[1].strip().lower()
            if value == "no":
                needs_handoff = False
            elif value == "yes":
                needs_handoff = True
    if reply is not None and _contains_placeholder(reply):
        # Deliberately keeps the reply text rather than blanking it: the
        # handoff notification is more useful to the agent picking this up
        # if they can see what the model was about to send, and nothing
        # downstream sends a reply once needs_handoff is set.
        needs_handoff = True
        confidence = 0.0
    return AutopilotReply(reply=reply, confidence=confidence, needs_handoff=needs_handoff)
