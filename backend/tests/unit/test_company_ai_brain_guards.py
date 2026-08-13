"""The rules the Company AI Brain must not lose.

Phase 1 ships contracts rather than a pipeline, so these are the tests that
matter most: they pin the invariants *before* there is an implementation to
bend them around. Every one of them corresponds to a way the Brain could
plausibly be built wrong — a customer-facing answer grounded in a draft, a
retrieval that forgot its tenant filter, an assistant that published its own
proposal, a knowledge mailbox that manufactured a customer.

See ``docs/architecture/company-ai-brain.md``.

One deliberate deviation from the brief is recorded in
``test_superseded_answers_only_within_its_own_period``: SUPERSEDED knowledge
*is* resolvable, on purpose, and the safety property being asserted is period
arithmetic rather than lifecycle state.
"""

from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from blinkengage.domain.brain import (
    AnswerDisposition,
    BrainAudience,
    BrainRequest,
    ChannelPurpose,
    ConflictVerdict,
    CrossTenantAccessError,
    CustomerSignals,
    EmotionalState,
    EscalationRisk,
    Formality,
    InboundEnvelope,
    IngestionRoute,
    KnowledgeAuthority,
    KnowledgeAvailability,
    KnowledgeClaim,
    KnowledgeProposal,
    PublicationCandidate,
    PublicationRefusal,
    authority_of,
    choose_response_strategy,
    creates_customer,
    de_escalation_directive,
    detect_conflict,
    filter_visible,
    ingestion_identity,
    is_visible,
    proposal_requires_approval,
    publication_gate,
    route_inbound,
)
from blinkengage.domain.brain.conflicts import CrossTenantComparisonError
from blinkengage.domain.brain.publication import (
    APPROVE_RESTRICTED_PERMISSION,
    PUBLISH_PERMISSION,
)
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
COMPANY_A = UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B = UUID("22222222-2222-2222-2222-222222222222")


@dataclass(frozen=True)
class _Record:
    """Structurally satisfies ``RetrievableRecord``, in five fields."""

    company_id: UUID
    lifecycle_state: KnowledgeLifecycleState
    access_level: KnowledgeAccessLevel = KnowledgeAccessLevel.PUBLIC_TO_AI
    effective_from: datetime | None = None
    effective_until: datetime | None = None


def _visible(record: _Record, audience: BrainAudience = BrainAudience.CUSTOMER) -> bool:
    return is_visible(record, company_id=COMPANY_A, audience=audience, at=NOW)


# --- the package exists, and is pure ----------------------------------


def test_the_brain_package_exists() -> None:
    assert (SRC / "domain" / "brain" / "__init__.py").is_file()
    assert (SRC / "application" / "brain" / "orchestrator.py").is_file()


def test_the_brains_domain_rules_never_reach_into_infrastructure() -> None:
    """Structural, for the reason the memory single-writer guard is.

    A behavioural test covers the paths somebody thought to write. This covers
    the ones nobody has written yet — which is where the next direct
    repository read inside a policy function would otherwise appear.

    Scoped to ``domain/brain`` deliberately. The application layer in this
    codebase *does* import models and repositories — ``autopilot_service``
    imports both — so extending this to ``application/brain`` would not be a
    stricter version of the same rule, it would be a different and wrong one.
    What must stay true is that the rules themselves are pure: a policy that
    can read a row is a policy that needs a database to test, and a policy
    that needs a database to test is one that stops being tested.
    """
    offenders: list[str] = []
    for path in sorted((SRC / "domain" / "brain").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            if "blinkengage.infrastructure" in module:
                offenders.append(f"{path.name}: imports {module}")

    assert offenders == [], "\n".join(offenders)


def test_the_brain_has_no_send_path() -> None:
    """AutopilotService stays the only thing that replies without a human.

    The Brain supplies grounding, policy and tone. If it ever acquires a
    channel provider, a message repository or the Autopilot service itself,
    it has acquired the ability to answer a customer directly — and the
    approval model becomes advisory without anybody deciding that it should.
    """
    forbidden = ("autopilot", "channel_provider", "channels.providers", "connectors")
    offenders: list[str] = []
    for path in sorted(
        [*(SRC / "domain" / "brain").rglob("*.py"), *(SRC / "application" / "brain").rglob("*.py")]
    ):
        source = path.read_text().lower()
        tree = ast.parse(path.read_text(), filename=str(path))
        imported = {
            (node.module or "").lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        for needle in forbidden:
            if any(needle in module for module in imported):
                offenders.append(f"{path.name}: imports {needle}")
        assert "def send" not in source, f"{path.name} defines a send function"

    assert offenders == [], "\n".join(offenders)


# --- tenant scope is mandatory ----------------------------------------


def test_a_brain_request_cannot_be_made_without_a_company() -> None:
    """The tenant boundary, expressed as a signature rather than a filter."""
    with pytest.raises(TypeError):
        BrainRequest(audience=BrainAudience.CUSTOMER, query="what is the price?")  # type: ignore[call-arg]


def test_a_brain_request_carries_its_company() -> None:
    request = BrainRequest(company_id=COMPANY_A, audience=BrainAudience.CUSTOMER, query="price?")
    assert request.company_id == COMPANY_A


def test_cross_tenant_retrieval_raises_rather_than_filters() -> None:
    """Another company's row here is a bug, not a case to handle politely."""
    intruder = _Record(COMPANY_B, KnowledgeLifecycleState.ACTIVE)

    with pytest.raises(CrossTenantAccessError):
        is_visible(intruder, company_id=COMPANY_A, audience=BrainAudience.CUSTOMER, at=NOW)

    with pytest.raises(CrossTenantAccessError):
        filter_visible(
            [_Record(COMPANY_A, KnowledgeLifecycleState.ACTIVE), intruder],
            company_id=COMPANY_A,
            audience=BrainAudience.CUSTOMER,
            at=NOW,
        )


def test_cross_tenant_conflict_comparison_raises() -> None:
    mine = KnowledgeClaim(COMPANY_A, KnowledgeRecordType.PRICE, "enterprise")
    theirs = KnowledgeClaim(COMPANY_B, KnowledgeRecordType.PRICE, "enterprise")

    with pytest.raises(CrossTenantComparisonError):
        detect_conflict(mine, theirs)


# --- lifecycle: what may answer a customer ----------------------------


def test_draft_never_answers_a_customer() -> None:
    draft = _Record(COMPANY_A, KnowledgeLifecycleState.DRAFT)

    assert _visible(draft) is False
    assert _visible(draft, BrainAudience.INTERNAL_AGENT) is False
    # The assistant is the one audience that must see drafts — discussing
    # unpublished work is its entire purpose.
    assert _visible(draft, BrainAudience.COMPANY_ADMIN) is True
    assert authority_of(KnowledgeLifecycleState.DRAFT) is KnowledgeAuthority.PROPOSAL


def test_archived_never_answers_anyone() -> None:
    """Withdrawn, and its period is left intact for the audit trail.

    Which means it *can* overlap a later active record — so admitting it would
    reintroduce exactly the ambiguity resolution exists to prevent.
    """
    archived = _Record(
        COMPANY_A,
        KnowledgeLifecycleState.ARCHIVED,
        effective_from=NOW - timedelta(days=30),
        effective_until=NOW + timedelta(days=30),
    )

    for audience in BrainAudience:
        assert _visible(archived, audience) is False


def test_superseded_answers_only_within_its_own_period() -> None:
    """**Deliberate deviation from the brief**, recorded here rather than hidden.

    The brief asks that SUPERSEDED never resolve for customers. Implementing
    that literally would break shipped, documented behaviour:
    ``RESOLVABLE_STATES`` includes SUPERSEDED because publishing a price change
    effective next month supersedes today's record *immediately*, while the
    replacement does not yet cover today. Excluding it would leave the subject
    unpriced for a month because somebody scheduled a change correctly.

    The safety property actually wanted is "stale knowledge must not answer as
    current", and that is guaranteed by the period, not the state. So this is
    what is pinned.
    """
    current = _Record(
        COMPANY_A,
        KnowledgeLifecycleState.SUPERSEDED,
        effective_from=NOW - timedelta(days=30),
        effective_until=NOW + timedelta(days=1),
    )
    expired = _Record(
        COMPANY_A,
        KnowledgeLifecycleState.SUPERSEDED,
        effective_from=NOW - timedelta(days=90),
        effective_until=NOW - timedelta(days=30),
    )

    assert _visible(current) is True
    assert _visible(expired) is False
    assert authority_of(KnowledgeLifecycleState.SUPERSEDED) is KnowledgeAuthority.APPROVED


def test_an_active_record_outside_its_period_does_not_answer() -> None:
    """The same rule, applied to the state nobody suspects."""
    not_yet = _Record(
        COMPANY_A,
        KnowledgeLifecycleState.ACTIVE,
        effective_from=NOW + timedelta(days=1),
    )

    assert _visible(not_yet) is False


def test_restricted_and_internal_never_reach_a_customer() -> None:
    for level in (KnowledgeAccessLevel.INTERNAL, KnowledgeAccessLevel.RESTRICTED):
        record = _Record(COMPANY_A, KnowledgeLifecycleState.ACTIVE, access_level=level)
        assert _visible(record) is False

    internal = _Record(
        COMPANY_A, KnowledgeLifecycleState.ACTIVE, access_level=KnowledgeAccessLevel.INTERNAL
    )
    assert _visible(internal, BrainAudience.INTERNAL_AGENT) is True


# --- conflicts --------------------------------------------------------


def _price(
    amount: str, *, start: datetime | None = None, end: datetime | None = None
) -> KnowledgeClaim:
    return KnowledgeClaim(
        company_id=COMPANY_A,
        record_type=KnowledgeRecordType.PRICE,
        subject_key="enterprise-plan",
        attributes={"amount": amount, "currency": "JOD"},
        effective_from=start,
        effective_until=end,
    )


def test_a_contradicting_price_is_a_conflict_not_a_choice() -> None:
    """The brief's example: existing 15 JOD, incoming email says 18."""
    assert detect_conflict(_price("18"), _price("15")) is ConflictVerdict.VALUE_CONFLICT


def test_first_statement_about_a_subject_is_not_a_conflict() -> None:
    assert detect_conflict(_price("15"), None) is ConflictVerdict.NO_CONFLICT


def test_restating_the_same_price_is_identical_not_a_change() -> None:
    assert detect_conflict(_price("15"), _price("15")) is ConflictVerdict.IDENTICAL


def test_a_scheduled_change_supersedes_rather_than_conflicts() -> None:
    existing = _price("15", start=NOW - timedelta(days=30), end=NOW)
    scheduled = _price("18", start=NOW, end=None)

    assert detect_conflict(scheduled, existing) is ConflictVerdict.SUPERSEDES


def test_same_value_overlapping_periods_is_still_a_data_problem() -> None:
    existing = _price("15", start=NOW - timedelta(days=30), end=NOW + timedelta(days=30))
    overlapping = _price("15", start=NOW - timedelta(days=10), end=NOW + timedelta(days=60))

    assert detect_conflict(overlapping, existing) is ConflictVerdict.PERIOD_CONFLICT


# --- publication and provenance ---------------------------------------


def _candidate(**overrides: object) -> PublicationCandidate:
    base: dict[str, object] = {
        "company_id": COMPANY_A,
        "record_type": KnowledgeRecordType.PRODUCT,
        "access_level": KnowledgeAccessLevel.PUBLIC_TO_AI,
        "provenance": "company_admin",
        "approved_by_user_id": uuid4(),
        "approved_at": NOW,
    }
    base.update(overrides)
    return PublicationCandidate(**base)  # type: ignore[arg-type]


def test_publication_requires_provenance() -> None:
    decision = publication_gate(
        _candidate(provenance=None), granted_permissions=frozenset({PUBLISH_PERMISSION})
    )

    assert decision.permitted is False
    assert PublicationRefusal.MISSING_PROVENANCE in decision.refusals


def test_publication_requires_a_named_human() -> None:
    decision = publication_gate(
        _candidate(approved_by_user_id=None, approved_at=None),
        granted_permissions=frozenset({PUBLISH_PERMISSION}),
    )

    assert decision.permitted is False
    assert PublicationRefusal.MISSING_APPROVER in decision.refusals


def test_publication_requires_the_permission() -> None:
    decision = publication_gate(_candidate(), granted_permissions=frozenset())

    assert decision.permitted is False
    assert PublicationRefusal.MISSING_PERMISSION in decision.refusals


def test_a_price_cannot_be_published_without_human_approval() -> None:
    """Not configurable downward, whatever the sender's trust level."""
    decision = publication_gate(
        _candidate(
            record_type=KnowledgeRecordType.PRICE,
            provenance="trusted_mailbox",
            approved_by_user_id=None,
            approved_at=None,
        ),
        granted_permissions=frozenset({PUBLISH_PERMISSION}),
    )

    assert decision.permitted is False
    assert PublicationRefusal.SENSITIVE_REQUIRES_HUMAN_APPROVAL in decision.refusals


def test_restricted_needs_its_own_permission() -> None:
    decision = publication_gate(
        _candidate(access_level=KnowledgeAccessLevel.RESTRICTED),
        granted_permissions=frozenset({PUBLISH_PERMISSION}),
    )

    assert PublicationRefusal.RESTRICTED_REQUIRES_APPROVAL_PERMISSION in decision.refusals

    permitted = publication_gate(
        _candidate(access_level=KnowledgeAccessLevel.RESTRICTED),
        granted_permissions=frozenset({PUBLISH_PERMISSION, APPROVE_RESTRICTED_PERMISSION}),
    )
    assert permitted.permitted is True


def test_an_unresolved_conflict_blocks_publication() -> None:
    decision = publication_gate(
        _candidate(conflict=ConflictVerdict.VALUE_CONFLICT),
        granted_permissions=frozenset({PUBLISH_PERMISSION}),
    )

    assert decision.permitted is False
    assert PublicationRefusal.UNRESOLVED_CONFLICT in decision.refusals


def test_the_gate_reports_every_refusal_not_the_first() -> None:
    decision = publication_gate(
        _candidate(provenance=None, approved_by_user_id=None, approved_at=None),
        granted_permissions=frozenset(),
    )

    assert {
        PublicationRefusal.MISSING_PROVENANCE,
        PublicationRefusal.MISSING_APPROVER,
        PublicationRefusal.MISSING_PERMISSION,
    } <= set(decision.refusals)


def test_a_complete_candidate_publishes() -> None:
    assert (
        publication_gate(
            _candidate(), granted_permissions=frozenset({PUBLISH_PERMISSION})
        ).permitted
        is True
    )


# --- the admin assistant proposes, and never publishes -----------------


def test_an_assistant_proposal_is_never_authoritative() -> None:
    proposal = KnowledgeProposal(
        company_id=COMPANY_A,
        record_type=KnowledgeRecordType.PRICE,
        subject_label="Enterprise plan",
        attributes={"amount": "15", "currency": "JOD"},
        provenance="company_admin",
    )

    assert proposal.authority is KnowledgeAuthority.PROPOSAL
    assert proposal_requires_approval(proposal) is True


def test_a_proposal_missing_information_is_incomplete() -> None:
    """The admin said "we changed pricing" and not from when."""
    proposal = KnowledgeProposal(
        company_id=COMPANY_A,
        record_type=KnowledgeRecordType.PRICE,
        subject_label="Enterprise plan",
        missing_fields=("effective_from",),
    )

    assert proposal.is_complete is False


# --- email ingestion is not customer support ---------------------------


def test_a_knowledge_mailbox_never_creates_a_customer() -> None:
    assert creates_customer(ChannelPurpose.KNOWLEDGE_INGESTION) is False
    assert creates_customer(ChannelPurpose.OTHER) is False
    assert creates_customer(ChannelPurpose.CUSTOMER_SUPPORT) is True


def test_knowledge_mail_routes_away_from_the_conversation_pipeline() -> None:
    envelope = InboundEnvelope(
        company_id=COMPANY_A,
        channel_config_id=uuid4(),
        purpose=ChannelPurpose.KNOWLEDGE_INGESTION,
        message_id="<abc@company.com>",
    )

    assert route_inbound(envelope) is IngestionRoute.KNOWLEDGE


def test_ingestion_identity_is_company_scoped_and_durable() -> None:
    """Not ``\\Seen``, and not global.

    The same Message-ID arriving at two companies is two documents; a global
    key would let one company's ingestion suppress another's.
    """
    config = uuid4()
    mine = InboundEnvelope(COMPANY_A, config, ChannelPurpose.KNOWLEDGE_INGESTION, "<x@a>")
    theirs = InboundEnvelope(COMPANY_B, config, ChannelPurpose.KNOWLEDGE_INGESTION, "<x@a>")

    assert ingestion_identity(mine) != ingestion_identity(theirs)
    assert ingestion_identity(mine) == ingestion_identity(mine)
    assert str(COMPANY_A) in ingestion_identity(mine)


# --- response strategy, tone and de-escalation -------------------------


def test_customer_language_and_formality_reach_the_strategy() -> None:
    strategy = choose_response_strategy(
        availability=KnowledgeAvailability(authoritative_hits=1),
        language="ar-JO",
        formality=Formality.INFORMAL,
    )

    assert strategy.tone.language == "ar-JO"
    assert strategy.tone.formality is Formality.INFORMAL
    assert strategy.disposition is AnswerDisposition.ANSWER


def test_an_angry_customer_gets_de_escalation_and_a_human_offered() -> None:
    directive = de_escalation_directive(
        emotional_state=EmotionalState.ANGRY,
        escalation_risk=EscalationRisk.HIGH,
        language="ar-JO",
        formality=Formality.INFORMAL,
    )

    assert directive.acknowledge_frustration is True
    assert directive.offer_human_escalation is True
    assert directive.keep_brief is True
    assert directive.avoid_blame is True


def test_a_frustrated_customer_is_acknowledged() -> None:
    directive = de_escalation_directive(
        emotional_state=EmotionalState.FRUSTRATED,
        escalation_risk=EscalationRisk.MEDIUM,
        language="en",
        formality=Formality.NEUTRAL,
    )

    assert directive.acknowledge_frustration is True


def test_a_confused_customer_gets_steps_not_precision() -> None:
    directive = de_escalation_directive(
        emotional_state=EmotionalState.CONFUSED,
        escalation_risk=EscalationRisk.LOW,
        language="en",
        formality=Formality.NEUTRAL,
    )

    assert directive.step_by_step is True
    assert directive.offer_human_escalation is False


def test_hostility_is_never_mirrored() -> None:
    """Language and register are mirrored. Abuse is not, in every state.

    ``mirror_hostility`` is typed ``Literal[False]``, so enabling it fails the
    type check as well as this test.
    """
    for state in EmotionalState:
        for risk in EscalationRisk:
            directive = de_escalation_directive(
                emotional_state=state,
                escalation_risk=risk,
                language="ar-JO",
                formality=Formality.INFORMAL,
            )
            assert directive.mirror_hostility is False
            assert directive.mirror_language is True
            assert directive.avoid_blame is True


# --- the platform does not invent -------------------------------------


def test_contradiction_escalates_and_states_nothing() -> None:
    strategy = choose_response_strategy(
        availability=KnowledgeAvailability(conflicted=True, authoritative_hits=2)
    )

    assert strategy.disposition is AnswerDisposition.ESCALATE
    assert strategy.may_state_company_facts is False


def test_a_price_with_no_authoritative_record_is_never_answered_from_prose() -> None:
    """No fallback to the nearest-looking passage. That is how an expired
    price gets quoted a year later."""
    strategy = choose_response_strategy(
        availability=KnowledgeAvailability(
            requires_authoritative=True, authoritative_hits=0, supporting_hits=4
        )
    )

    assert strategy.disposition is AnswerDisposition.CLARIFY
    assert strategy.may_state_company_facts is False


def test_an_angry_customer_with_no_price_is_escalated_not_interrogated() -> None:
    strategy = choose_response_strategy(
        availability=KnowledgeAvailability(requires_authoritative=True, authoritative_hits=0),
        emotional_state=EmotionalState.ANGRY,
        escalation_risk=EscalationRisk.HIGH,
    )

    assert strategy.disposition is AnswerDisposition.ESCALATE


def test_policy_forbidding_ai_wins_over_everything() -> None:
    strategy = choose_response_strategy(
        availability=KnowledgeAvailability(authoritative_hits=3), ai_may_answer=False
    )

    assert strategy.disposition is AnswerDisposition.DECLINE
    assert strategy.may_state_company_facts is False


def test_supporting_material_alone_is_offered_for_confirmation() -> None:
    strategy = choose_response_strategy(
        availability=KnowledgeAvailability(supporting_hits=2, authoritative_hits=0)
    )

    assert strategy.disposition is AnswerDisposition.CONFIRM


def test_signals_default_to_calm_and_neutral() -> None:
    signals = CustomerSignals()

    assert signals.emotional_state is EmotionalState.CALM
    assert signals.escalation_risk is EscalationRisk.LOW
    assert signals.dialect is None
