"""The orchestrator, wired to the knowledge the platform already stores.

Phase 1 named this seam; this is the first thing to occupy it. It answers one
question — *does this company have an authoritative record for what is being
asked, and may it be stated?* — and hands the answer to Autopilot as grounding.

What it deliberately does not do: send anything, decide whether Autopilot may
reply, or change any threshold. It returns :class:`BrainAdvice`, which has
nothing to send with. Better grounding constrains what may be said; it does not
widen permission.

The lookup is by identity, never resemblance. A subject named in the question
is resolved through the shipped ``KnowledgeRecordService.resolve()``, which
returns exactly one record, ``None``, or raises on contradiction — and each of
those three becomes a different response strategy rather than a different
amount of confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from blinkengage.application.services.knowledge_record_service import (
    KnowledgeRecordService,
)
from blinkengage.core.logging import get_logger
from blinkengage.domain.brain.context import BrainAdvice, BrainRequest
from blinkengage.domain.brain.response_strategy import (
    KnowledgeAvailability,
    choose_response_strategy,
)
from blinkengage.domain.brain.retrieval_policy import CrossTenantAccessError, is_visible
from blinkengage.domain.brain.subject_matching import match_subjects
from blinkengage.domain.brain.verification import GroundingFacts, value_claims
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
    OverlappingRecordError,
)
from blinkengage.infrastructure.database.models.knowledge_record import KnowledgeRecord

logger = get_logger(__name__)

#: Record types whose answer must come from a structured record or not at all.
#:
#: A price and an SLA term are values, and the nearest-looking passage is not a
#: value. The other types describe things, where a passage is a legitimate
#: answer, so they do not set the absence signal.
AUTHORITATIVE_ONLY: frozenset[KnowledgeRecordType] = frozenset(
    {
        KnowledgeRecordType.PRICE,
        KnowledgeRecordType.SLA_TERM,
        KnowledgeRecordType.POLICY_PARAM,
    }
)

#: How many of the company's subjects to consider per turn. A ceiling rather
#: than a page: a question naming more than a handful of distinct products is
#: not a question the structured path answers well, and scanning the whole
#: catalogue on every inbound message is a cost with no matching benefit.
SUBJECT_SCAN_LIMIT = 500


class CompanyBrain:
    """One company's Brain. Satisfies ``BrainOrchestrator``."""

    def __init__(self, *, records: KnowledgeRecordService) -> None:
        self._records = records

    async def advise(self, request: BrainRequest) -> BrainAdvice:
        """Ground one turn, or say plainly that it cannot be grounded."""
        at = request.at or datetime.now(UTC)
        resolved: list[KnowledgeRecord] = []
        conflicted = False
        looked_up = False
        requires_authoritative = False

        try:
            candidates = await self._records.list_records(
                company_id=request.company_id, at=at, limit=SUBJECT_SCAN_LIMIT
            )
            # Subject detection runs over *every* record the company has for
            # this subject, including ones that may not answer: drafts,
            # archived rows, restricted material.
            #
            # That looks backwards and is the security-relevant part. What is
            # being decided here is "did the customer ask about something this
            # company prices?", which is a property of the question, not of
            # whether an approved answer happens to exist. Filtering first
            # meant a company whose only price record was still a DRAFT looked
            # like a company that sells nothing priced — so the verifier never
            # engaged, and a figure the model invented sailed through. The
            # unapproved row must still be able to say "this is a priced
            # subject" while being wholly unable to answer.
            by_key = {record.subject_key: record for record in candidates}

            for subject_key in match_subjects(request.query, by_key):
                looked_up = True
                record = by_key[subject_key]
                record_type = KnowledgeRecordType(record.record_type)
                if record_type in AUTHORITATIVE_ONLY:
                    requires_authoritative = True
                try:
                    authoritative = await self._records.resolve(
                        company_id=request.company_id,
                        record_type=record_type,
                        subject_label=record.subject_label,
                        at=at,
                    )
                except OverlappingRecordError:
                    # Two records claim one subject over one instant. Never
                    # pick: a retrieval layer that returns the higher-scoring
                    # row converts a data problem into a quotation.
                    logger.warning(
                        "brain_contradictory_knowledge",
                        company_id=str(request.company_id),
                        subject_key=subject_key,
                    )
                    conflicted = True
                    continue
                # Authority is granted here and only here. ``resolve`` applies
                # lifecycle and period; audience and access level are this
                # boundary's to apply, so a RESTRICTED record that resolves
                # perfectly still cannot answer a customer.
                #
                # Through an explicit view rather than by handing the ORM row
                # to the domain: the rule depends on five values, not on a
                # mapped class.
                if authoritative is not None and is_visible(
                    _visibility_view(authoritative),
                    company_id=request.company_id,
                    audience=request.audience,
                    at=at,
                ):
                    resolved.append(authoritative)
        except CrossTenantAccessError:
            # Never degraded. Every other failure here is an availability
            # problem and costs an answer; this one means a row from another
            # company reached the boundary, and the generic handler below
            # would turn a tenant leak into a quiet "no grounding today" that
            # nobody would ever look at.
            raise
        except Exception:
            # Degrades to ungrounded, exactly as Autopilot's own retrieval
            # does. A knowledge store that is down must not take Autopilot
            # down with it — the model still has the business profile and is
            # still forbidden from inventing, so the worst case is a handoff.
            logger.warning("brain_lookup_failed", company_id=str(request.company_id), exc_info=True)
            return BrainAdvice(
                company_id=request.company_id,
                strategy=choose_response_strategy(
                    availability=KnowledgeAvailability(),
                    emotional_state=request.signals.emotional_state,
                    escalation_risk=request.signals.escalation_risk,
                    language=request.signals.language,
                    formality=request.signals.formality,
                ),
                rationale="knowledge_lookup_failed",
                # `requires_authority` is true on this path even though the
                # lookup never got far enough to know. It is the conservative
                # reading and the only safe one: the alternative says "no
                # priced subject was named" on the strength of a query that
                # errored, which would let a figure through precisely when
                # the platform is least able to check it.
                facts=GroundingFacts(requires_authority=True, unavailable=True),
            )

        availability = KnowledgeAvailability(
            authoritative_hits=len(resolved),
            absent=looked_up and not resolved,
            conflicted=conflicted,
            requires_authoritative=requires_authoritative,
        )
        strategy = choose_response_strategy(
            availability=availability,
            emotional_state=request.signals.emotional_state,
            escalation_risk=request.signals.escalation_risk,
            language=request.signals.language,
            formality=request.signals.formality,
        )

        return BrainAdvice(
            company_id=request.company_id,
            strategy=strategy,
            grounded_record_ids=tuple(record.id for record in resolved),
            rationale=strategy.reason,
            grounding=_render(resolved, conflicted=conflicted, absent=availability.absent),
            facts=GroundingFacts(
                requires_authority=requires_authoritative,
                authoritative_hits=len(resolved),
                conflicted=conflicted,
                unavailable=False,
                supported_values=_supported_values(resolved),
            ),
        )


def _supported_values(records: list[KnowledgeRecord]) -> frozenset[str]:
    """Every figure this company has approved for this turn.

    Both the attribute values and the subject labels, because a correct reply
    quotes both: "our 500 Mbps DIA costs 180 JOD" carries the price from the
    attributes and the 500 from the product's own name. Omitting labels would
    make the verifier reject the sentence it is supposed to permit.

    Nothing from the customer's message is included here — see the note on
    ``GroundingFacts.supported_values``.
    """
    supported: set[str] = set()
    for record in records:
        for value in (record.attributes or {}).values():
            supported |= value_claims(str(value))
        supported |= value_claims(record.subject_label)
    return frozenset(supported)


@dataclass(frozen=True, slots=True)
class _VisibilityView:
    """The five values ``is_visible`` decides on, lifted off the ORM row."""

    company_id: UUID
    lifecycle_state: KnowledgeLifecycleState
    access_level: KnowledgeAccessLevel
    effective_from: datetime | None
    effective_until: datetime | None


def _visibility_view(record: KnowledgeRecord) -> _VisibilityView:
    return _VisibilityView(
        company_id=record.company_id,
        lifecycle_state=KnowledgeLifecycleState(record.lifecycle_state),
        access_level=KnowledgeAccessLevel(record.access_level),
        effective_from=record.effective_from,
        effective_until=record.effective_until,
    )


def _render(records: list[KnowledgeRecord], *, conflicted: bool, absent: bool) -> str | None:
    """The authoritative section, or the absence signal, as prompt text.

    Labelled as authoritative and as *not* to be paraphrased, for the reason
    Autopilot already separates approved answers from reference material: a
    model handed a value and a passage without being told which is which
    rewrites the value into prose and loses the number.
    """
    if conflicted:
        return (
            "AUTHORITATIVE COMPANY FACTS: unavailable — this company holds "
            "two conflicting records for what was asked. Do not state or "
            "estimate the value. Say it is being confirmed and hand over."
        )

    if not records:
        if absent:
            return (
                "AUTHORITATIVE COMPANY FACTS: none on record for what was "
                "asked. Do not state, estimate or recall a value from "
                "anywhere else. Say the company does not have it on record "
                "and offer to confirm."
            )
        return None

    lines = [
        "AUTHORITATIVE COMPANY FACTS (approved by this company; quote these "
        "values exactly and never paraphrase a number):"
    ]
    for record in records:
        attributes = ", ".join(
            f"{key}={value}" for key, value in sorted(dict(record.attributes or {}).items())
        )
        lines.append(f"- {record.subject_label} [{record.record_type}]: {attributes}")
    return "\n".join(lines)


__all__ = ["AUTHORITATIVE_ONLY", "SUBJECT_SCAN_LIMIT", "CompanyBrain"]
