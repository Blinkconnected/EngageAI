"""Unit tests for ``AiService`` against a fake ``AiProvider`` — no HTTP
involved, focused on prompt-shaping, response-parsing/normalization, and
event publishing. See ``docs/architecture/ai-engine.md``.
"""

from uuid import uuid4

import pytest

from blinkengage.application.services.ai_service import AiService
from blinkengage.domain.events import DomainEvent
from blinkengage.domain.exceptions import AiNotConfiguredError


class FakeAiProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        self.calls.append(
            {
                "system": system,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return self.response

    async def health_check(self) -> bool:
        return True


class FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


@pytest.fixture
def events() -> FakeEventPublisher:
    return FakeEventPublisher()


def _service(provider: FakeAiProvider | None, events: FakeEventPublisher) -> AiService:
    return AiService(provider=provider, events=events)  # type: ignore[arg-type]


class TestNotConfigured:
    async def test_raises_when_provider_is_none(self, events: FakeEventPublisher) -> None:
        service = _service(None, events)

        with pytest.raises(AiNotConfiguredError):
            await service.suggest_reply(
                company_id=uuid4(), conversation_id=uuid4(), conversation_history="hi"
            )

        assert events.published == []


class TestSuggestReply:
    async def test_returns_completion_and_publishes_event(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("Sure, happy to help!")
        service = _service(provider, events)
        company_id, conversation_id = uuid4(), uuid4()

        result = await service.suggest_reply(
            company_id=company_id,
            conversation_id=conversation_id,
            conversation_history="Customer: help me",
        )

        assert result == "Sure, happy to help!"
        assert provider.calls[0]["prompt"] == "Customer: help me"
        assert len(events.published) == 1
        event = events.published[0]
        assert event.event_type == "ai.completed"
        assert event.company_id == company_id
        assert event.aggregate_type == "conversation"
        assert event.aggregate_id == conversation_id
        assert event.payload == {"operation": "suggest_reply"}


class TestSummarizeConversation:
    async def test_returns_summary(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("Customer wants a refund; agent is processing it.")
        service = _service(provider, events)

        result = await service.summarize_conversation(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert "refund" in result
        assert events.published[0].payload == {"operation": "summarize_conversation"}


class TestTranslate:
    async def test_includes_target_language_in_system_prompt(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("Hola")
        service = _service(provider, events)

        result = await service.translate(
            company_id=uuid4(), conversation_id=None, text="Hello", target_language="Spanish"
        )

        assert result == "Hola"
        assert "Spanish" in str(provider.calls[0]["system"])
        event = events.published[0]
        assert event.aggregate_type == "ai_operation"
        assert event.aggregate_id is None


class TestDetectLanguage:
    async def test_strips_whitespace_and_trailing_period(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider(" French. ")
        service = _service(provider, events)

        result = await service.detect_language(company_id=uuid4(), conversation_id=None, text="x")

        assert result == "French"


class TestAnalyzeSentiment:
    @pytest.mark.parametrize("raw,expected", [("Positive", "positive"), ("NEGATIVE.", "negative")])
    async def test_normalizes_known_sentiment(
        self, events: FakeEventPublisher, raw: str, expected: str
    ) -> None:
        provider = FakeAiProvider(raw)
        service = _service(provider, events)

        result = await service.analyze_sentiment(company_id=uuid4(), conversation_id=None, text="x")

        assert result == expected

    async def test_falls_back_to_neutral_on_unrecognized_response(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("I'm not sure")
        service = _service(provider, events)

        result = await service.analyze_sentiment(company_id=uuid4(), conversation_id=None, text="x")

        assert result == "neutral"


class TestSuggestTags:
    async def test_empty_available_tags_short_circuits_without_calling_provider(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("should never be reached")
        service = _service(provider, events)

        result = await service.suggest_tags(
            company_id=uuid4(), conversation_id=None, text="x", available_tags=[]
        )

        assert result == []
        assert provider.calls == []
        assert events.published == []

    async def test_only_returns_tags_from_allowed_list(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("Billing, made-up-tag, urgent")
        service = _service(provider, events)

        result = await service.suggest_tags(
            company_id=uuid4(),
            conversation_id=None,
            text="x",
            available_tags=["Billing", "Urgent", "Refund"],
        )

        assert result == ["Billing", "Urgent"]

    async def test_matches_case_insensitively_and_preserves_catalog_casing(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("billing")
        service = _service(provider, events)

        result = await service.suggest_tags(
            company_id=uuid4(), conversation_id=None, text="x", available_tags=["Billing"]
        )

        assert result == ["Billing"]

    async def test_none_response_returns_empty_list(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("none")
        service = _service(provider, events)

        result = await service.suggest_tags(
            company_id=uuid4(), conversation_id=None, text="x", available_tags=["Billing"]
        )

        assert result == []


class TestAnswerFromKnowledgeBase:
    async def test_no_candidates_returns_static_message_without_calling_provider(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("should never be reached")
        service = _service(provider, events)

        result = await service.answer_from_knowledge_base(
            company_id=uuid4(), conversation_id=None, query="how do I?", candidate_articles=[]
        )

        assert result == "No relevant knowledge base articles were found."
        assert provider.calls == []
        assert events.published == []

    async def test_includes_articles_in_system_prompt(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("You can reset it from settings.")
        service = _service(provider, events)

        result = await service.answer_from_knowledge_base(
            company_id=uuid4(),
            conversation_id=None,
            query="how do I reset my password?",
            candidate_articles=[("Password Reset", "Go to settings and click reset.")],
        )

        assert result == "You can reset it from settings."
        assert "Password Reset" in str(provider.calls[0]["system"])


class TestImproveGrammarAndRewrite:
    async def test_improve_grammar_returns_corrected_text(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("I am going to the store.")
        service = _service(provider, events)

        result = await service.improve_grammar(company_id=uuid4(), conversation_id=None, text="x")

        assert result == "I am going to the store."
        assert events.published[0].payload == {"operation": "improve_grammar"}

    async def test_rewrite_professionally_returns_rewritten_text(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("We appreciate your patience.")
        service = _service(provider, events)

        result = await service.rewrite_professionally(
            company_id=uuid4(), conversation_id=None, text="x"
        )

        assert result == "We appreciate your patience."
        assert events.published[0].payload == {"operation": "rewrite_professionally"}


class TestSuggestNextBestAction:
    async def test_parses_well_formed_response(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider(
            "action: escalate_to_queue\nreason: Customer is requesting a manager."
        )
        service = _service(provider, events)

        result = await service.suggest_next_best_action(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result == {
            "action": "escalate_to_queue",
            "reason": "Customer is requesting a manager.",
        }

    async def test_falls_back_to_no_action_needed_on_unknown_action(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("action: delete_everything\nreason: because")
        service = _service(provider, events)

        result = await service.suggest_next_best_action(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result["action"] == "no_action_needed"

    async def test_falls_back_to_no_action_needed_on_unparseable_response(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("I think you should just wait.")
        service = _service(provider, events)

        result = await service.suggest_next_best_action(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result["action"] == "no_action_needed"
        assert result["reason"] == "I think you should just wait."


class TestSuggestAutopilotReply:
    async def test_parses_a_well_formed_high_confidence_response(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider(
            "REPLY: We're open 9-5 Monday to Friday.\nCONFIDENCE: 90\nHANDOFF: NO"
        )
        service = _service(provider, events)
        company_id, conversation_id = uuid4(), uuid4()

        result = await service.suggest_autopilot_reply(
            company_id=company_id, conversation_id=conversation_id, conversation_history="..."
        )

        assert result.reply == "We're open 9-5 Monday to Friday."
        assert result.confidence == 0.9
        assert result.needs_handoff is False
        assert len(events.published) == 1
        assert events.published[0].payload == {"operation": "suggest_autopilot_reply"}

    async def test_handoff_yes_is_respected_even_with_high_confidence(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("REPLY: I can process that refund.\nCONFIDENCE: 95\nHANDOFF: YES")
        service = _service(provider, events)

        result = await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result.needs_handoff is True

    async def test_blank_reply_line_is_none_not_an_empty_string(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("REPLY:\nCONFIDENCE: 20\nHANDOFF: YES")
        service = _service(provider, events)

        result = await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result.reply is None

    async def test_confidence_percent_sign_is_tolerated(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("REPLY: ok\nCONFIDENCE: 80%\nHANDOFF: NO")
        service = _service(provider, events)

        result = await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result.confidence == 0.8

    async def test_out_of_range_confidence_is_ignored_leaving_the_conservative_default(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("REPLY: ok\nCONFIDENCE: 150\nHANDOFF: NO")
        service = _service(provider, events)

        result = await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result.confidence == 0.0
        # HANDOFF: NO was still parsed correctly — an out-of-range
        # CONFIDENCE line doesn't invalidate every other line.
        assert result.needs_handoff is False

    async def test_completely_unparseable_response_defaults_to_safe_handoff(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("I'm not sure how to answer that in the format you want.")
        service = _service(provider, events)

        result = await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result.reply is None
        assert result.confidence == 0.0
        assert result.needs_handoff is True


class TestAutopilotGrounding:
    """What Autopilot is allowed to know, and what it does when it does
    not know. The defect these cover: asked its own company's name and
    address in Arabic, Autopilot answered with a bracketed placeholder,
    and asked its opening hours it invented "9am to 5pm" — all
    auto-sent, because this path has no human reviewing it."""

    async def test_business_profile_is_given_to_the_model(self, events: FakeEventPublisher) -> None:
        provider = FakeAiProvider("REPLY: ok\nCONFIDENCE: 90\nHANDOFF: NO")
        service = _service(provider, events)

        await service.suggest_autopilot_reply(
            company_id=uuid4(),
            conversation_id=uuid4(),
            conversation_history="...",
            business_profile="Company name: Blink Connected\nLocation: Amman, Jordan",
        )

        system = provider.calls[0]["system"]
        assert isinstance(system, str)
        assert "Blink Connected" in system
        assert "Amman, Jordan" in system

    async def test_retrieved_material_is_given_to_the_model(
        self, events: FakeEventPublisher
    ) -> None:
        provider = FakeAiProvider("REPLY: ok\nCONFIDENCE: 90\nHANDOFF: NO")
        service = _service(provider, events)

        await service.suggest_autopilot_reply(
            company_id=uuid4(),
            conversation_id=uuid4(),
            conversation_history="...",
            grounding="APPROVED ANSWERS:\nQ: Do you deliver?\nA: Yes, within 3 days.",
        )

        system = provider.calls[0]["system"]
        assert isinstance(system, str)
        assert "within 3 days" in system

    async def test_the_refusal_rule_is_stated_even_with_nothing_to_ground_on(
        self, events: FakeEventPublisher
    ) -> None:
        """The ungrounded prompt must still forbid invention — an empty
        knowledge base is exactly when the model is most tempted to fill
        the gap, so this is the case that must not silently relax."""
        provider = FakeAiProvider("REPLY: ok\nCONFIDENCE: 90\nHANDOFF: NO")
        service = _service(provider, events)

        await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        system = provider.calls[0]["system"]
        assert isinstance(system, str)
        assert "Never guess" in system
        assert "Never write a placeholder" in system

    @pytest.mark.parametrize(
        ("reply", "label"),
        [
            ("اسم الشركة هو [اسم الشركة].", "the Arabic company-name placeholder, as reported"),
            ("موقعنا هو [عنوان الموقع].", "the Arabic address placeholder, as reported"),
            ("Our company is [Company Name].", "an English placeholder"),
            ("We are at {address}.", "a curly-brace placeholder"),
            ("We open at [business_hours].", "a snake_case placeholder"),
        ],
    )
    async def test_a_placeholder_reply_is_forced_to_handoff(
        self, events: FakeEventPublisher, reply: str, label: str
    ) -> None:
        """Regardless of what the model scored itself. A placeholder is
        the one failure that reads as a finished answer, so the prompt
        rule against it is backed by a mechanical check that cannot be
        talked out of."""
        provider = FakeAiProvider(f"REPLY: {reply}\nCONFIDENCE: 95\nHANDOFF: NO")
        service = _service(provider, events)

        result = await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result.needs_handoff is True, label
        assert result.confidence == 0.0
        # The text is kept, not blanked: the agent picking up the handoff
        # is better off seeing what the model was about to send.
        assert result.reply == reply

    @pytest.mark.parametrize(
        ("reply", "label"),
        [
            ("Your order [#12345] shipped today.", "an order reference"),
            ("See ticket [REF-2024] for details.", "a ticket reference"),
            ("The total is $45 (including tax).", "ordinary parenthetical prose"),
            ("Use the code SAVE20 at checkout.", "a promo code"),
        ],
    )
    async def test_a_legitimate_bracketed_reference_still_sends(
        self, events: FakeEventPublisher, reply: str, label: str
    ) -> None:
        """The guard must not hold real replies. A reference carries a
        number; a placeholder names a concept — that is the distinction
        the pattern draws, and trading this bug for replies that never
        arrive would be no improvement."""
        provider = FakeAiProvider(f"REPLY: {reply}\nCONFIDENCE: 95\nHANDOFF: NO")
        service = _service(provider, events)

        result = await service.suggest_autopilot_reply(
            company_id=uuid4(), conversation_id=uuid4(), conversation_history="..."
        )

        assert result.needs_handoff is False, label
        assert result.confidence == 0.95
