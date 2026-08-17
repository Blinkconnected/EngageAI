"""What the admin assistant may *change* — and what a human must sign first.

See ``docs/architecture/company-ai-brain.md`` (Phase 4G-2).

Four tools, split by what they cost to get wrong. ``propose_knowledge_update``
creates a DRAFT and nothing else: a draft was never true, answers nobody, and
is visible only to an administrator, so an AI that proposes freely costs a
review rather than a wrong quotation. The other three make something
authoritative or withdraw it, and each is ``ConfirmationPolicy.REQUIRED`` —
validated, priced up as a before/after diff, parked as a ``PendingAiAction``,
and executed only when a human comes back through
``ToolExecutor.confirm``. That parking is enforced by the executor, not by
asking the model nicely.

**This module is where ``publication_gate`` finally runs.** The gate has
existed since Phase 1 with no caller — the contract was written before the
enforcement point. Publishing through this path evaluates it, and the
candidate's ``approved_by_user_id`` is the human who confirmed, taken from
``ToolContext.auth`` at confirm time. Never the model, and never a value the
model supplied: the gate's own docstring makes the approver a human on
purpose, and an AI that could name the approver would be approving itself.

**Archiving does not go through the gate**, deliberately. The gate answers
"may this become authoritative?", and withdrawal makes nothing authoritative.
It still requires confirmation and the same publish permission, because
withdrawing a price changes what the platform will say just as surely.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from blinkengage.application.ai_tools.registry import ToolRegistry
from blinkengage.application.ai_tools.spec import ConfirmationPolicy, ToolContext, ToolSpec
from blinkengage.domain.brain.conflicts import (
    ConflictVerdict,
    KnowledgeClaim,
    detect_conflict,
)
from blinkengage.domain.brain.publication import PublicationCandidate, publication_gate
from blinkengage.domain.exceptions import DomainError
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
    validate_attributes,
)

_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PublicationRefused(DomainError):
    """``publication_gate`` said no. Carries the refusals verbatim.

    A ``DomainError`` on purpose: the executor turns these into a structured
    result the model can explain to the administrator, rather than an
    exception that ends the turn. "You cannot publish this because it has no
    provenance" is an answer somebody can act on.
    """

    def __init__(self, refusals: tuple[str, ...]) -> None:
        super().__init__("Publication refused: " + ", ".join(refusals))
        self.refusals = refusals


class ProposeKnowledgeUpdateArgs(BaseModel):
    model_config = _STRICT

    record_type: KnowledgeRecordType
    subject_label: str = Field(min_length=1, max_length=300)
    #: Validated against the type's own schema by the service. A model that
    #: invents a field gets the domain's error back, not a stored record.
    attributes: dict[str, Any]
    effective_from: datetime
    effective_until: datetime | None = None
    #: Required here even though ``create_draft`` allows its absence: a draft
    #: an assistant wrote with no stated origin is one no reviewer can check,
    #: and ``publication_gate`` would refuse it later anyway.
    source_reference: str = Field(min_length=1, max_length=2000)
    access_level: KnowledgeAccessLevel = KnowledgeAccessLevel.PUBLIC_TO_AI


class PublishKnowledgeRecordArgs(BaseModel):
    model_config = _STRICT

    record_id: UUID


class SupersedeKnowledgeRecordArgs(BaseModel):
    model_config = _STRICT

    record_id: UUID
    attributes: dict[str, Any]
    effective_from: datetime
    effective_until: datetime | None = None
    source_reference: str = Field(min_length=1, max_length=2000)


class ArchiveKnowledgeRecordArgs(BaseModel):
    model_config = _STRICT

    record_id: UUID


def _view(record: Any) -> dict[str, Any]:
    """The before/after shape, and what the human is shown in the diff."""
    return {
        "record_id": str(record.id),
        "record_type": KnowledgeRecordType(record.record_type).value,
        "subject_label": record.subject_label,
        "attributes": dict(record.attributes or {}),
        "lifecycle_state": KnowledgeLifecycleState(record.lifecycle_state).value,
        "access_level": KnowledgeAccessLevel(record.access_level).value,
        "version": record.version,
        "effective_from": record.effective_from.isoformat() if record.effective_from else None,
        "effective_until": record.effective_until.isoformat() if record.effective_until else None,
        "source_reference": record.source_reference,
    }


def _as_text(attributes: Any) -> dict[str, str]:
    """``KnowledgeClaim`` compares strings. Values arrive validated, so this
    is a rendering step rather than a normalising one — ``180`` and
    ``180.00`` were already reconciled by ``validate_attributes``."""
    return {key: str(value) for key, value in dict(attributes or {}).items()}


async def _conflict_for(
    ctx: ToolContext, record: Any, attributes: dict[str, Any]
) -> ConflictVerdict:
    """How the proposed values sit against what is currently authoritative.

    Reported to the administrator rather than acted on, and fed to the gate,
    which refuses a blocking verdict. Two records claiming one subject over
    one instant is a data problem; publishing into it would make it an
    answer.
    """
    record_type = KnowledgeRecordType(record.record_type)
    current = await ctx.services.knowledge_records.resolve(
        company_id=ctx.company_id,
        record_type=record_type,
        subject_label=record.subject_label,
    )
    candidate = KnowledgeClaim(
        company_id=ctx.company_id,
        record_type=record_type,
        subject_key=record.subject_key,
        attributes=_as_text(validate_attributes(record_type, dict(attributes))),
        effective_from=record.effective_from,
        effective_until=record.effective_until,
    )
    existing = (
        None
        if current is None or current.id == record.id
        else KnowledgeClaim(
            company_id=current.company_id,
            record_type=KnowledgeRecordType(current.record_type),
            subject_key=current.subject_key,
            attributes=_as_text(current.attributes),
            effective_from=current.effective_from,
            effective_until=current.effective_until,
        )
    )
    return detect_conflict(candidate, existing)


async def _assert_publishable(
    ctx: ToolContext, record: Any, *, conflict: ConflictVerdict
) -> datetime:
    """Run the gate, with the confirming human as the approver.

    The approver is ``ctx.actor_user_id`` — the authenticated administrator
    who came back through ``ToolExecutor.confirm``. Passing it here rather
    than reading it off the record is the whole point: nothing about the
    material being published may grant the right to publish it.
    """
    approved_at = datetime.now(UTC)
    decision = publication_gate(
        PublicationCandidate(
            company_id=ctx.company_id,
            record_type=KnowledgeRecordType(record.record_type),
            access_level=KnowledgeAccessLevel(record.access_level),
            provenance=record.source_reference,
            approved_by_user_id=ctx.actor_user_id,
            approved_at=approved_at,
            conflict=conflict,
        ),
        # Straight from the token. Never from the model, never from the row.
        granted_permissions=ctx.auth.permissions,
    )
    if not decision.permitted:
        raise PublicationRefused(tuple(refusal.value for refusal in decision.refusals))
    return approved_at


# --- handlers ---------------------------------------------------------


async def _propose_knowledge_update(
    ctx: ToolContext, args: ProposeKnowledgeUpdateArgs
) -> dict[str, Any]:
    """A DRAFT, and only ever a DRAFT."""
    record = await ctx.services.knowledge_records.create_draft(
        company_id=ctx.company_id,
        record_type=args.record_type,
        subject_label=args.subject_label,
        attributes=args.attributes,
        effective_from=args.effective_from,
        effective_until=args.effective_until,
        access_level=args.access_level,
        source_reference=args.source_reference,
        # The proposal is attributed to the human who asked for it. There is
        # no AI service account anywhere in this platform.
        actor_user_id=ctx.actor_user_id,
    )
    conflict = await _conflict_for(ctx, record, args.attributes)
    return {
        "proposed": _view(record),
        "conflict": conflict.value,
        "note": (
            "This is a draft. It is not authoritative and will not answer anyone until "
            "a human publishes it."
        ),
    }


async def _publish_knowledge_record(
    ctx: ToolContext, args: PublishKnowledgeRecordArgs
) -> dict[str, Any]:
    record = await ctx.services.knowledge_records.get(
        company_id=ctx.company_id, record_id=args.record_id
    )
    conflict = await _conflict_for(ctx, record, dict(record.attributes or {}))
    approved_at = await _assert_publishable(ctx, record, conflict=conflict)

    published = await ctx.services.knowledge_records.publish(
        company_id=ctx.company_id,
        record_id=args.record_id,
        actor_user_id=ctx.actor_user_id,
        now=approved_at,
    )
    return {"published": _view(published), "approved_by_user_id": str(ctx.actor_user_id)}


async def _supersede_knowledge_record(
    ctx: ToolContext, args: SupersedeKnowledgeRecordArgs
) -> dict[str, Any]:
    record = await ctx.services.knowledge_records.get(
        company_id=ctx.company_id, record_id=args.record_id
    )
    conflict = await _conflict_for(ctx, record, args.attributes)
    approved_at = await _assert_publishable(ctx, record, conflict=conflict)

    replacement = await ctx.services.knowledge_records.supersede(
        company_id=ctx.company_id,
        record_id=args.record_id,
        attributes=args.attributes,
        effective_from=args.effective_from,
        effective_until=args.effective_until,
        source_reference=args.source_reference,
        actor_user_id=ctx.actor_user_id,
        now=approved_at,
    )
    return {"superseded": str(args.record_id), "replacement": _view(replacement)}


async def _archive_knowledge_record(
    ctx: ToolContext, args: ArchiveKnowledgeRecordArgs
) -> dict[str, Any]:
    """Withdraws a record. The row stays readable forever.

    No ``publication_gate`` here: the gate asks whether something may become
    authoritative, and withdrawal makes nothing authoritative. Confirmation
    and the publish permission still apply — withdrawing a price changes what
    the platform will say just as surely as publishing one.
    """
    withdrawn = await ctx.services.knowledge_records.archive(
        company_id=ctx.company_id,
        record_id=args.record_id,
        actor_user_id=ctx.actor_user_id,
    )
    return {"withdrawn": _view(withdrawn)}


# --- state readers (the confirmation staleness check) ------------------


async def _record_state(ctx: ToolContext, args: Any) -> dict[str, Any] | None:
    """What the record looks like now.

    The executor compares this between proposal and confirmation and refuses
    a stale approval. Without it a human could approve a diff that stopped
    describing reality while they were reading it.
    """
    record = await ctx.services.knowledge_records.get(
        company_id=ctx.company_id, record_id=args.record_id
    )
    return _view(record)


async def _proposal_state(ctx: ToolContext, args: ProposeKnowledgeUpdateArgs) -> None:
    """A proposal creates something new, so there is no before."""
    return None


def register_knowledge_write_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="propose_knowledge_update",
            description=(
                "Draft a proposed change to a structured knowledge record. This creates a "
                "DRAFT only — it is not authoritative, answers nobody, and requires a human "
                "to publish it before it takes effect."
            ),
            args_model=ProposeKnowledgeUpdateArgs,
            handler=_propose_knowledge_update,
            permission="knowledge_records.propose",
            confirmation=ConfirmationPolicy.NONE,
            mutating=True,
            state_reader=_proposal_state,
        )
    )
    registry.register(
        ToolSpec(
            name="publish_knowledge_record",
            description=(
                "Make a draft knowledge record authoritative. This changes what the platform "
                "tells customers and always requires the administrator's explicit confirmation."
            ),
            args_model=PublishKnowledgeRecordArgs,
            handler=_publish_knowledge_record,
            permission="knowledge_records.publish",
            confirmation=ConfirmationPolicy.REQUIRED,
            mutating=True,
            state_reader=_record_state,
        )
    )
    registry.register(
        ToolSpec(
            name="supersede_knowledge_record",
            description=(
                "Replace an authoritative record with a new version from a given date. The "
                "outgoing version's period closes exactly where the new one opens. Always "
                "requires the administrator's explicit confirmation."
            ),
            args_model=SupersedeKnowledgeRecordArgs,
            handler=_supersede_knowledge_record,
            permission="knowledge_records.publish",
            confirmation=ConfirmationPolicy.REQUIRED,
            mutating=True,
            state_reader=_record_state,
        )
    )
    registry.register(
        ToolSpec(
            name="archive_knowledge_record",
            description=(
                "Withdraw a knowledge record so it stops answering. The record remains "
                "readable for audit. Always requires the administrator's explicit "
                "confirmation."
            ),
            args_model=ArchiveKnowledgeRecordArgs,
            handler=_archive_knowledge_record,
            permission="knowledge_records.publish",
            confirmation=ConfirmationPolicy.REQUIRED,
            mutating=True,
            state_reader=_record_state,
        )
    )


__all__ = [
    "ArchiveKnowledgeRecordArgs",
    "ProposeKnowledgeUpdateArgs",
    "PublicationRefused",
    "PublishKnowledgeRecordArgs",
    "SupersedeKnowledgeRecordArgs",
    "register_knowledge_write_tools",
]
