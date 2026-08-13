"""Phase 2: the structured record actually reaches the customer's answer.

The gap this closes was specific and embarrassing: `knowledge_records` shipped
with lifecycle, provenance, approval and deterministic resolution, and nothing
on the path to a customer had ever read it. Autopilot grounded on FAQs and
article passages, so publishing a price change through the API altered
precisely nothing about what the platform told a customer.

These tests pin the two halves of the fix — identity-based subject matching,
and the Brain's advice reaching Autopilot's prompt — plus the three outcomes
that must never collapse into each other: a value, an absence, and a
contradiction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from blinkengage.application.brain.service import CompanyBrain
from blinkengage.application.services.autopilot_service import AutopilotService
from blinkengage.domain.brain import (
    AnswerDisposition,
    BrainAdvice,
    BrainAudience,
    BrainRequest,
    CrossTenantAccessError,
    match_subjects,
    query_tokens,
)
from blinkengage.domain.brain.response_strategy import (
    KnowledgeAvailability,
    choose_response_strategy,
)
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
    OverlappingRecordError,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
COMPANY = UUID("11111111-1111-1111-1111-111111111111")


# --- subject matching: identity, not resemblance ----------------------


def test_a_named_product_is_found_in_a_question() -> None:
    assert match_subjects("how much is DIA 500 Mbps?", ["dia-500-mbps"]) == ("dia-500-mbps",)


def test_punctuation_and_spacing_do_not_change_the_match() -> None:
    assert match_subjects("price for DIA/500  Mbps", ["dia-500-mbps"]) == ("dia-500-mbps",)


def test_arabic_folding_and_arabic_indic_digits_match() -> None:
    """``خدمة ٥٠٠`` in a question finds the record written ``خدمه-500``.

    The same canonicaliser the record was written with — teh marbuta folded,
    Arabic-Indic digits mapped — so an Arabic question is not a second-class
    lookup.
    """
    assert match_subjects("كم سعر خدمة ٥٠٠ عندكم؟", ["خدمه-500"]) == ("خدمه-500",)


def test_scattered_tokens_do_not_match() -> None:
    """Contiguity is the point. A bag-of-words match would accept this, and
    identity retrieval that guesses is resemblance retrieval with extra steps."""
    assert match_subjects("is DIA available at 500 sites, in mbps terms?", ["dia-500-mbps"]) == ()


def test_the_more_specific_subject_comes_first() -> None:
    found = match_subjects("what does DIA 500 Mbps cost", ["dia", "dia-500-mbps"])

    assert found[0] == "dia-500-mbps"


def test_a_question_with_no_letters_or_digits_matches_nothing() -> None:
    """`canonical_subject_key` raises on such a label; a query is not a label."""
    assert query_tokens("؟؟؟ ...") == ()
    assert match_subjects("!!!", ["dia-500-mbps"]) == ()


# --- the brain, against a stubbed record service ----------------------


@dataclass
class _Record:
    company_id: UUID
    record_type: KnowledgeRecordType
    subject_key: str
    subject_label: str
    attributes: dict[str, Any]
    lifecycle_state: KnowledgeLifecycleState = KnowledgeLifecycleState.ACTIVE
    access_level: KnowledgeAccessLevel = KnowledgeAccessLevel.PUBLIC_TO_AI
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    id: UUID = uuid4()


class _Records:
    """Stands in for ``KnowledgeRecordService`` with its three outcomes."""

    def __init__(self, records: list[_Record], *, overlapping: bool = False) -> None:
        self._records = records
        self._overlapping = overlapping

    async def list_records(self, **_: Any) -> list[_Record]:
        return self._records

    async def resolve(self, *, subject_label: str, **_: Any) -> _Record | None:
        if self._overlapping:
            raise OverlappingRecordError("dia-500-mbps", "PRICE")
        for record in self._records:
            if record.subject_label == subject_label:
                return record
        return None


def _price(**overrides: Any) -> _Record:
    base: dict[str, Any] = {
        "company_id": COMPANY,
        "record_type": KnowledgeRecordType.PRICE,
        "subject_key": "dia-500-mbps",
        "subject_label": "DIA 500 Mbps",
        "attributes": {"amount": "180", "currency": "JOD"},
        "effective_from": NOW - timedelta(days=30),
    }
    base.update(overrides)
    return _Record(**base)


def _brain(records: list[_Record], *, overlapping: bool = False) -> CompanyBrain:
    return CompanyBrain(records=_Records(records, overlapping=overlapping))  # type: ignore[arg-type]


def _request(query: str = "how much is DIA 500 Mbps?") -> BrainRequest:
    return BrainRequest(company_id=COMPANY, audience=BrainAudience.CUSTOMER, query=query, at=NOW)


@pytest.mark.asyncio
async def test_an_approved_price_reaches_the_prompt_as_a_value() -> None:
    advice = await _brain([_price()]).advise(_request())

    assert advice.strategy.disposition is AnswerDisposition.ANSWER
    assert advice.grounding is not None
    assert "180" in advice.grounding
    assert "JOD" in advice.grounding
    assert "DIA 500 Mbps" in advice.grounding
    assert len(advice.grounded_record_ids) == 1


@pytest.mark.asyncio
async def test_the_grounding_forbids_paraphrasing_the_number() -> None:
    """A model handed a value and a passage without being told which is which
    rewrites the value into prose and loses the number."""
    advice = await _brain([_price()]).advise(_request())

    assert advice.grounding is not None
    assert "never paraphrase" in advice.grounding.lower()


@pytest.mark.asyncio
async def test_a_draft_price_never_reaches_a_customer_answer() -> None:
    advice = await _brain([_price(lifecycle_state=KnowledgeLifecycleState.DRAFT)]).advise(
        _request()
    )

    assert advice.grounded_record_ids == ()
    assert advice.grounding is None or "180" not in advice.grounding


@pytest.mark.asyncio
async def test_an_expired_price_is_absent_not_quoted() -> None:
    """The failure this whole path exists to prevent: a 2025 price in 2026."""
    advice = await _brain([_price(effective_until=NOW - timedelta(days=1))]).advise(_request())

    assert advice.grounded_record_ids == ()
    assert advice.grounding is None or "180" not in advice.grounding


@pytest.mark.asyncio
async def test_a_restricted_price_never_reaches_a_customer_answer() -> None:
    advice = await _brain([_price(access_level=KnowledgeAccessLevel.RESTRICTED)]).advise(_request())

    assert advice.grounded_record_ids == ()


@pytest.mark.asyncio
async def test_a_contradiction_is_surfaced_and_never_resolved() -> None:
    advice = await _brain([_price()], overlapping=True).advise(_request())

    assert advice.strategy.disposition is AnswerDisposition.ESCALATE
    assert advice.strategy.may_state_company_facts is False
    assert advice.grounding is not None
    assert "conflicting" in advice.grounding.lower()
    assert "180" not in advice.grounding


@pytest.mark.asyncio
async def test_a_question_about_nothing_the_company_stores_is_not_an_absence() -> None:
    """No subject named means no structured lookup ran, so no absence signal.

    Only a lookup that *matched a subject and found nothing* is an absence.
    Emitting the signal for every unrelated question would tell the model the
    company has no facts at all.
    """
    advice = await _brain([_price()]).advise(_request("what are your opening hours?"))

    assert advice.grounding is None


@pytest.mark.asyncio
async def test_a_knowledge_failure_degrades_to_ungrounded_not_to_an_error() -> None:
    class _Broken:
        async def list_records(self, **_: Any) -> list[_Record]:
            raise RuntimeError("database is down")

    advice = await CompanyBrain(records=_Broken()).advise(_request())  # type: ignore[arg-type]

    assert advice.rationale == "knowledge_lookup_failed"
    assert advice.grounding is None


@pytest.mark.asyncio
async def test_a_cross_tenant_row_fails_loudly_rather_than_degrading() -> None:
    """The one failure the Brain must not swallow.

    Every other error here is availability and costs an answer. A row from
    another company reaching the boundary is a leak, and the broad handler
    that makes a dead database survivable would otherwise turn it into a
    quiet "no grounding today" that nobody ever looks at.
    """
    intruder = _price(company_id=UUID("22222222-2222-2222-2222-222222222222"))

    with pytest.raises(CrossTenantAccessError):
        await _brain([intruder]).advise(_request())


# --- autopilot consumes it, and nothing else changes -------------------


class _StubBrain:
    def __init__(self, grounding: str | None) -> None:
        self._grounding = grounding
        self.calls = 0

    async def advise(self, request: BrainRequest) -> BrainAdvice:
        self.calls += 1
        return BrainAdvice(
            company_id=request.company_id,
            strategy=choose_response_strategy(availability=KnowledgeAvailability()),
            grounding=self._grounding,
        )


def _autopilot(**kwargs: Any) -> AutopilotService:
    return AutopilotService(
        conversations=object(),  # type: ignore[arg-type]
        messages=object(),  # type: ignore[arg-type]
        companies=object(),  # type: ignore[arg-type]
        events=object(),  # type: ignore[arg-type]
        conversation_service=object(),  # type: ignore[arg-type]
        **kwargs,
    )


@pytest.mark.asyncio
async def test_autopilot_puts_authoritative_facts_in_its_grounding() -> None:
    brain = _StubBrain("AUTHORITATIVE COMPANY FACTS: DIA 500 Mbps = 180 JOD")
    service = _autopilot(brain=brain)

    grounding = await service._grounding_for(company_id=COMPANY, query="price of DIA 500?")

    assert grounding is not None
    assert "180 JOD" in grounding
    assert brain.calls == 1


@pytest.mark.asyncio
async def test_autopilot_without_a_brain_behaves_exactly_as_before() -> None:
    """Every existing caller constructs this service without one."""
    service = _autopilot()

    assert await service._grounding_for(company_id=COMPANY, query="anything") is None


@pytest.mark.asyncio
async def test_a_brain_failure_never_costs_autopilot_its_reply() -> None:
    class _Exploding:
        async def advise(self, request: BrainRequest) -> BrainAdvice:
            raise RuntimeError("brain is down")

    service = _autopilot(brain=_Exploding())

    assert await service._grounding_for(company_id=COMPANY, query="price?") is None


@pytest.mark.asyncio
async def test_an_empty_question_short_circuits_before_the_brain() -> None:
    brain = _StubBrain("facts")
    service = _autopilot(brain=brain)

    assert await service._grounding_for(company_id=COMPANY, query="   ") is None
    assert brain.calls == 0


@pytest.mark.asyncio
async def test_a_semantic_retrieval_failure_does_not_discard_approved_facts() -> None:
    """The weakest retriever must not be able to veto the strongest one."""

    class _BrokenFaqs:
        async def grounding_answers(self, **_: Any) -> list[Any]:
            raise RuntimeError("vector index is down")

    brain = _StubBrain("AUTHORITATIVE COMPANY FACTS: DIA 500 Mbps = 180 JOD")
    service = _autopilot(brain=brain, faqs=_BrokenFaqs())

    grounding = await service._grounding_for(company_id=COMPANY, query="price?")

    assert grounding is not None
    assert "180 JOD" in grounding
