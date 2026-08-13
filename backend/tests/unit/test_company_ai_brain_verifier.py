"""Phase 3: a company figure nobody approved does not reach a customer.

Phase 2 gave Autopilot the approved records and asked the model to quote them.
This is the difference between asking and enforcing. The failure it closes is
invisible from the inside: handed an absence signal, a model usually says "I
don't have that on record" and occasionally says "I believe it's around 120
JOD" — fluently, at high confidence, in the customer's own dialect. Nothing
downstream can tell those apart, because both are well-formed replies.

The verifier sits at the one place it can: after every existing gate, on the
generated reply, immediately before the single send. It can only withhold.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from blinkengage.application.brain.service import CompanyBrain
from blinkengage.application.services.autopilot_service import AutopilotService
from blinkengage.domain.brain import (
    BrainAudience,
    BrainRequest,
    CrossTenantAccessError,
    GroundingFacts,
    VerificationOutcome,
    VerificationReason,
    value_claims,
    verify_reply,
)
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
    OverlappingRecordError,
)
from blinkengage.domain.routing_decisions import ai_released_decision

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
AUTOPILOT = SRC / "application" / "services" / "autopilot_service.py"

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
COMPANY = UUID("11111111-1111-1111-1111-111111111111")
OTHER_COMPANY = UUID("22222222-2222-2222-2222-222222222222")

#: A company that has approved 180 JOD for DIA 500 Mbps.
APPROVED = GroundingFacts(
    requires_authority=True,
    authoritative_hits=1,
    supported_values=frozenset({"180", "500", "JOD".lower()}) | value_claims("DIA 500 Mbps"),
)


# --- rule 1: an authoritative value is the source of truth -------------


def test_a_reply_quoting_the_approved_price_is_allowed() -> None:
    verdict = verify_reply("Our 500 Mbps DIA costs 180 JOD.", APPROVED)

    assert verdict.outcome is VerificationOutcome.ALLOW
    assert verdict.reason is VerificationReason.AUTHORITY_CONFIRMED
    assert verdict.may_send is True


def test_the_approved_value_is_recognised_however_it_is_written() -> None:
    """``180``, ``180.00`` and ``180,00`` are one figure, not three.

    Without this the verifier withholds a correct answer for spelling a
    number differently — and a safety control that blocks correct answers is
    a safety control somebody switches off.
    """
    for spelling in ("180", "180.00", "180,00", "180.0"):
        verdict = verify_reply(f"That plan is {spelling} JOD.", APPROVED)
        assert verdict.outcome is VerificationOutcome.ALLOW, spelling


def test_arabic_indic_digits_in_a_reply_are_recognised() -> None:
    verdict = verify_reply("سعرها ١٨٠ دينار.", APPROVED)

    assert verdict.outcome is VerificationOutcome.ALLOW


def test_a_reply_inventing_a_different_figure_is_blocked() -> None:
    """The case the file exists for: an approved 180, a confident 120."""
    verdict = verify_reply("Our 500 Mbps DIA costs 120 JOD.", APPROVED)

    assert verdict.outcome is VerificationOutcome.BLOCK
    assert verdict.reason is VerificationReason.UNSUPPORTED_VALUE
    assert "120" in verdict.unsupported_values


# --- rule 2: no authority means no figure ------------------------------


def _absent() -> GroundingFacts:
    return GroundingFacts(requires_authority=True, authoritative_hits=0)


def test_a_price_with_no_authoritative_record_is_blocked() -> None:
    verdict = verify_reply("I believe the price is around 120 JOD.", _absent())

    assert verdict.outcome is VerificationOutcome.BLOCK
    assert verdict.reason is VerificationReason.AUTHORITY_ABSENT


def test_an_availability_claim_with_a_figure_is_blocked_without_authority() -> None:
    verdict = verify_reply("We can deliver that within 3 working days.", _absent())

    assert verdict.outcome is VerificationOutcome.BLOCK


def test_a_policy_claim_with_a_figure_is_blocked_without_authority() -> None:
    verdict = verify_reply("You can cancel free of charge within 14 days.", _absent())

    assert verdict.outcome is VerificationOutcome.BLOCK


def test_the_customers_own_number_does_not_authorise_the_reply() -> None:
    """ "Is it 120 JOD?" → "Yes, 120 JOD" must not pass.

    Seeding the supported set from the customer's message would be the
    cheapest possible way to make the platform quote a price it never
    approved: say the number first, and it agrees with you.
    """
    verdict = verify_reply("Yes, that's right — 120 JOD.", _absent())

    assert verdict.outcome is VerificationOutcome.BLOCK


def test_a_deferral_with_no_figure_is_allowed() -> None:
    """The behaviour the absence signal actually asks for.

    Blocking this would punish the model for doing exactly the right thing,
    and would turn every unanswerable pricing question into a handoff even
    when AI handled it correctly.
    """
    verdict = verify_reply(
        "I don't have that on record — let me confirm and come back to you.", _absent()
    )

    assert verdict.outcome is VerificationOutcome.ALLOW
    assert verdict.reason is VerificationReason.NO_COMPANY_CLAIM


# --- rule 3: conflict never resolves itself ----------------------------


def test_conflicting_records_escalate_and_never_pick() -> None:
    facts = GroundingFacts(requires_authority=True, authoritative_hits=2, conflicted=True)

    verdict = verify_reply("Our 500 Mbps package is 120 JOD.", facts)

    assert verdict.outcome is VerificationOutcome.ESCALATE
    assert verdict.reason is VerificationReason.AUTHORITY_CONFLICT


def test_a_conflict_is_not_resolved_by_the_reply_matching_one_of_them() -> None:
    """Quoting record A's value does not make record B stop existing."""
    facts = GroundingFacts(
        requires_authority=True,
        authoritative_hits=2,
        conflicted=True,
        supported_values=frozenset({"120", "150"}),
    )

    assert verify_reply("It is 120 JOD.", facts).outcome is VerificationOutcome.ESCALATE


# --- rule 4: could-not-check is not the same as nothing-found ----------


def test_grounding_failure_escalates_and_is_reported_as_its_own_reason() -> None:
    facts = GroundingFacts(requires_authority=True, unavailable=True)

    verdict = verify_reply("It costs 180 JOD.", facts)

    assert verdict.outcome is VerificationOutcome.ESCALATE
    assert verdict.reason is VerificationReason.GROUNDING_UNAVAILABLE


def test_unavailable_is_never_reported_as_absent() -> None:
    """ "We don't have that" and "we could not look" are different sentences
    to a customer and different problems to an operator."""
    unavailable = verify_reply(
        "180 JOD.", GroundingFacts(requires_authority=True, unavailable=True)
    )
    absent = verify_reply("180 JOD.", _absent())

    assert unavailable.reason is not absent.reason


# --- generic conversation is not the verifier's business ---------------


def test_a_question_naming_no_priced_subject_is_untouched() -> None:
    verdict = verify_reply(
        "DIA means a dedicated line that is not shared with other subscribers.",
        GroundingFacts(requires_authority=False),
    )

    assert verdict.outcome is VerificationOutcome.ALLOW
    assert verdict.reason is VerificationReason.NO_COMPANY_CLAIM


def test_generic_explanation_containing_a_number_is_untouched() -> None:
    """Not a hallucination detector. With no priced subject named, a figure in
    a general explanation is not the platform's to verify."""
    verdict = verify_reply(
        "Business lines are typically sold in 100, 500 and 1000 Mbps tiers.",
        GroundingFacts(requires_authority=False),
    )

    assert verdict.outcome is VerificationOutcome.ALLOW


# --- claim extraction --------------------------------------------------


def test_value_claims_finds_figures_and_ignores_prose() -> None:
    assert value_claims("no numbers here at all") == frozenset()
    assert "180" in value_claims("costs 180 JOD")


def test_value_claims_is_total_on_text_with_no_alphanumerics() -> None:
    """``canonical_subject_key`` raises on such input; a reply is not a label."""
    assert value_claims("؟؟؟ ...") == frozenset()


# --- the brain supplies the facts, from the same lookup ----------------


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
    def __init__(self, records: list[_Record], *, overlapping: bool = False) -> None:
        self._records = records
        self._overlapping = overlapping

    async def list_records(self, **_: Any) -> list[_Record]:
        return self._records

    async def resolve(self, *, subject_label: str, **_: Any) -> _Record | None:
        if self._overlapping:
            raise OverlappingRecordError("dia-500-mbps", "PRICE")
        return next((r for r in self._records if r.subject_label == subject_label), None)


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
async def test_an_approved_record_produces_facts_that_allow_the_right_reply() -> None:
    advice = await _brain([_price()]).advise(_request())

    assert advice.facts.requires_authority is True
    assert advice.facts.authoritative_hits == 1
    assert verify_reply("It is 180 JOD.", advice.facts).outcome is VerificationOutcome.ALLOW
    assert verify_reply("It is 120 JOD.", advice.facts).outcome is VerificationOutcome.BLOCK


@pytest.mark.asyncio
async def test_a_draft_record_cannot_authorise_a_figure() -> None:
    advice = await _brain([_price(lifecycle_state=KnowledgeLifecycleState.DRAFT)]).advise(
        _request()
    )

    assert verify_reply("It is 180 JOD.", advice.facts).outcome is not VerificationOutcome.ALLOW


@pytest.mark.asyncio
async def test_a_superseded_record_outside_its_period_cannot_authorise_a_figure() -> None:
    advice = await _brain(
        [
            _price(
                lifecycle_state=KnowledgeLifecycleState.SUPERSEDED,
                effective_from=NOW - timedelta(days=90),
                effective_until=NOW - timedelta(days=30),
            )
        ]
    ).advise(_request())

    assert verify_reply("It is 180 JOD.", advice.facts).outcome is not VerificationOutcome.ALLOW


@pytest.mark.asyncio
async def test_an_archived_record_cannot_authorise_a_figure() -> None:
    advice = await _brain(
        [
            _price(
                lifecycle_state=KnowledgeLifecycleState.ARCHIVED,
                effective_until=NOW + timedelta(days=30),
            )
        ]
    ).advise(_request())

    assert verify_reply("It is 180 JOD.", advice.facts).outcome is not VerificationOutcome.ALLOW


@pytest.mark.asyncio
async def test_a_restricted_record_cannot_authorise_a_customer_facing_figure() -> None:
    advice = await _brain([_price(access_level=KnowledgeAccessLevel.RESTRICTED)]).advise(_request())

    assert verify_reply("It is 180 JOD.", advice.facts).outcome is not VerificationOutcome.ALLOW


@pytest.mark.asyncio
async def test_conflicting_records_reach_the_verifier_as_a_conflict() -> None:
    advice = await _brain([_price()], overlapping=True).advise(_request())

    assert advice.facts.conflicted is True
    assert verify_reply("It is 180 JOD.", advice.facts).outcome is VerificationOutcome.ESCALATE


@pytest.mark.asyncio
async def test_a_brain_lookup_failure_reaches_the_verifier_as_unavailable() -> None:
    class _Broken:
        async def list_records(self, **_: Any) -> list[_Record]:
            raise RuntimeError("database is down")

    advice = await CompanyBrain(records=_Broken()).advise(_request())  # type: ignore[arg-type]

    assert advice.facts.unavailable is True
    assert advice.facts.requires_authority is True
    verdict = verify_reply("It is 180 JOD.", advice.facts)
    assert verdict.reason is VerificationReason.GROUNDING_UNAVAILABLE


@pytest.mark.asyncio
async def test_another_tenants_record_never_authorises_and_never_degrades() -> None:
    with pytest.raises(CrossTenantAccessError):
        await _brain([_price(company_id=OTHER_COMPANY)]).advise(_request())


# --- autopilot integration --------------------------------------------


class _Advice:
    def __init__(self, facts: GroundingFacts, grounding: str | None = None) -> None:
        self.facts = facts
        self.grounding = grounding
        self.calls = 0

    async def advise(self, request: BrainRequest) -> Any:
        self.calls += 1
        from blinkengage.domain.brain.context import BrainAdvice
        from blinkengage.domain.brain.response_strategy import (
            KnowledgeAvailability,
            choose_response_strategy,
        )

        return BrainAdvice(
            company_id=request.company_id,
            strategy=choose_response_strategy(availability=KnowledgeAvailability()),
            grounding=self.grounding,
            facts=self.facts,
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
async def test_the_brain_is_consulted_once_per_turn() -> None:
    """The verifier must judge the reply against the knowledge the model was
    given. A second lookup could return something else."""
    brain = _Advice(APPROVED, grounding="FACTS")
    service = _autopilot(brain=brain)

    bundle = await service._ground(company_id=COMPANY, query="price of DIA 500 Mbps?")

    assert brain.calls == 1
    assert bundle.prompt == "FACTS"
    assert bundle.advice is not None
    assert bundle.advice.facts is APPROVED


@pytest.mark.asyncio
async def test_a_cross_tenant_error_propagates_out_of_autopilot_grounding() -> None:
    class _Leaky:
        async def advise(self, request: BrainRequest) -> Any:
            raise CrossTenantAccessError(COMPANY, OTHER_COMPANY)

    service = _autopilot(brain=_Leaky())

    with pytest.raises(CrossTenantAccessError):
        await service._ground(company_id=COMPANY, query="price?")


@pytest.mark.asyncio
async def test_a_brain_outage_produces_unavailable_facts_not_absent_ones() -> None:
    class _Exploding:
        async def advise(self, request: BrainRequest) -> Any:
            raise RuntimeError("brain is down")

    service = _autopilot(brain=_Exploding())

    bundle = await service._ground(company_id=COMPANY, query="price?")

    assert bundle.advice is not None
    assert bundle.advice.facts.unavailable is True
    assert bundle.advice.facts.requires_authority is True


@pytest.mark.asyncio
async def test_without_a_brain_the_facts_require_no_authority() -> None:
    """Every existing caller constructs Autopilot without one, and their
    behaviour must be exactly what it was."""
    service = _autopilot()

    bundle = await service._ground(company_id=COMPANY, query="anything")

    assert bundle.advice is None
    assert bundle.prompt is None
    assert verify_reply("anything at all, 120 JOD", GroundingFacts()).may_send is True


# --- structural guarantees --------------------------------------------


def _autopilot_ast() -> ast.Module:
    return ast.parse(AUTOPILOT.read_text(), filename=str(AUTOPILOT))


def test_the_verifier_runs_exactly_once() -> None:
    calls = [
        node
        for node in ast.walk(_autopilot_ast())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "verify_reply"
    ]

    assert len(calls) == 1, "the gate must be one gate, not one per branch"


def test_there_is_still_exactly_one_send_path() -> None:
    """The verifier withholds; it never sends. If a second `send_reply` ever
    appears here, something has grown its own way to answer a customer."""
    sends = [
        node
        for node in ast.walk(_autopilot_ast())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "send_reply"
    ]

    assert len(sends) == 1


def test_the_verifier_runs_after_the_confidence_gate() -> None:
    """Order is the guarantee. Running before the threshold would let the
    verifier's ALLOW be read as permission by something downstream; running
    after means it can only ever subtract from what was already permitted.
    """
    source = AUTOPILOT.read_text()

    assert source.index("result.confidence < threshold") < source.index("verify_reply(")
    assert source.index("verify_reply(") < source.index("send_reply(")


def test_the_verifier_cannot_reach_a_sender() -> None:
    """It decides; it owns no transport and no repository.

    Structural rather than textual: the module's prose says "send it", and a
    substring check would fail on its own documentation. What matters is that
    it imports nothing that could carry a message and defines nothing that
    could deliver one.
    """
    path = SRC / "domain" / "brain" / "verification.py"
    tree = ast.parse(path.read_text(), filename=str(path))

    imported = {(node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any("infrastructure" in module for module in imported)
    assert not any("application" in module for module in imported)

    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert not any(name.startswith("send") for name in functions)


def test_both_verifier_handoff_reasons_are_in_the_closed_vocabulary() -> None:
    """An unmapped reason records no routing decision at all, so the
    conversation would show AI handing back with no explanation — and "AI
    withheld a price it could not support" is the most useful thing that
    screen could say.
    """
    for reason in ("unverified_company_fact", "knowledge_not_decidable"):
        decision = ai_released_decision(reason)
        assert decision is not None, reason
        assert decision.reason.value == reason
