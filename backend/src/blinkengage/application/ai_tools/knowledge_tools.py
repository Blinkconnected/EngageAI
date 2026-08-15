"""What the admin assistant may look up. Two tools, both read-only.

See ``docs/architecture/company-ai-brain.md`` (Phase 4G-1).

The assistant answers questions about a company's own structured knowledge —
"what did we approve for the DIA 500 price?", "is that still a draft?" — and
answering them needs retrieval, not authority. So these two tools read, and
there is deliberately no third one that writes.

**Why read-only is structural rather than promised.** ``ToolSpec.mutating``
is ``False`` and no handler here holds anything that could change a record:
``ToolContext`` exposes application services and nothing else, and the only
service either handler touches is :class:`KnowledgeRecordService`, whose
write methods (``create_draft``, ``publish``, ``supersede``, ``archive``)
are never named in this module. A model that asked for a price change reaches
no handler that could make one, which is a different guarantee from a handler
that declines.

**Visibility is the Brain's, unchanged.** Both tools filter through
``retrieval_policy.is_visible`` at ``COMPANY_ADMIN``, the audience that
already exists for exactly this caller. That is what admits DRAFTs — an
administrator discussing an unapproved record is the whole point — and what
still refuses ARCHIVED, because a withdrawn record's period is left intact
for the audit trail and admitting it would reintroduce the ambiguity the
resolution contract exists to prevent. Neither tool carves an exception.

**Tenant scope is never an argument.** ``company_id`` comes from
``ToolContext.auth`` and the registry refuses to register a tool that
declares it, so there is no schema for a model to lie to. If a foreign row
ever reaches the visibility predicate it raises
:class:`CrossTenantAccessError`, which is *not* a ``DomainError`` and so is
not converted into a sentence for the model to explain — see
``executor._run``. A tenant leak reported as assistant prose is a leak nobody
investigates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from blinkengage.application.ai_tools.registry import ToolRegistry
from blinkengage.application.ai_tools.spec import ConfirmationPolicy, ToolContext, ToolSpec
from blinkengage.domain.brain.retrieval_policy import is_visible
from blinkengage.domain.brain.subject_matching import rank_subjects
from blinkengage.domain.brain.vocabulary import BrainAudience
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
)
from blinkengage.infrastructure.database.models.knowledge_record import KnowledgeRecord

#: Every argument model inherits this, exactly as the default catalog's do.
_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)

#: How many of the company's records to consider for one search. The same
#: ceiling ``CompanyBrain`` scans with, for the same reason: a question that
#: touches more than a handful of subjects is not one this path answers well,
#: and scanning an entire catalogue per turn costs without buying anything.
SCAN_LIMIT = 500

#: How many hits the model is told about. Small on purpose — a tool result is
#: prompt context, and forty records of attributes crowds out the question.
MAX_RESULTS = 10


class SearchKnowledgeArgs(BaseModel):
    model_config = _STRICT

    #: ``search_text``, not ``query`` — and the difference is a rule, not a
    #: preference. ``test_no_tool_is_a_generic_escape_hatch`` refuses any tool
    #: argument named ``query``, ``sql``, ``expression``, ``code`` or
    #: ``script``, because a field with one of those names is how a tool
    #: quietly becomes a way for a model to choose *what runs*. What this
    #: field holds is a sentence to match subjects in; naming it after what
    #: it is keeps the guard intact and honest.
    search_text: str = Field(min_length=1, max_length=500)
    #: Constrained to the enum, so an invented type is a schema error the
    #: model is told about rather than a filter that silently matches nothing.
    record_type: KnowledgeRecordType | None = None
    #: Off by default. A draft was never approved, and an assistant that
    #: mixes drafts into an ordinary answer is quoting something nobody
    #: agreed to — the administrator has to ask for them.
    include_drafts: bool = False


class GetKnowledgeRecordArgs(BaseModel):
    model_config = _STRICT

    record_id: UUID


@dataclass(frozen=True, slots=True)
class _VisibilityView:
    """The five values ``is_visible`` decides on, lifted off the ORM row.

    An explicit view rather than the mapped class, so the domain rule keeps
    depending on five fields instead of on infrastructure.
    """

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


def _admin_can_see(record: KnowledgeRecord, *, company_id: UUID, at: datetime) -> bool:
    """One predicate, used by both tools, for the one audience they serve."""
    return is_visible(
        _visibility_view(record),
        company_id=company_id,
        audience=BrainAudience.COMPANY_ADMIN,
        at=at,
    )


def _summary(record: KnowledgeRecord) -> dict[str, Any]:
    """What the model is told about a record.

    Assembled field by field rather than serialised from the row: this
    becomes prompt context *and* part of the audit record, so it carries
    what an answer needs — the values, their lifecycle, where they came
    from — and nothing that merely happened to be on the table.
    """
    return {
        "record_id": str(record.id),
        "record_type": KnowledgeRecordType(record.record_type).value,
        "subject_label": record.subject_label,
        "attributes": dict(record.attributes or {}),
        # Carried on every hit, not just on request: an assistant that shows
        # a value without saying whether it is approved has answered the
        # easy half of the question.
        "lifecycle_state": KnowledgeLifecycleState(record.lifecycle_state).value,
        "access_level": KnowledgeAccessLevel(record.access_level).value,
        "version": record.version,
        "effective_from": record.effective_from.isoformat() if record.effective_from else None,
        "effective_until": record.effective_until.isoformat() if record.effective_until else None,
        #: Provenance. The administrator's first question about any figure the
        #: assistant quotes is where it came from, and a citation the caller
        #: has to go and look up separately is one nobody looks up.
        "source_reference": record.source_reference,
        "created_from": record.created_from,
    }


async def _search_knowledge(ctx: ToolContext, args: SearchKnowledgeArgs) -> dict[str, Any]:
    at = datetime.now(UTC)

    # Company-scoped at the query, not filtered afterwards. Note there is no
    # ``at=`` here: the period rule belongs to ``is_visible`` below, which
    # also has to decide about drafts (which have no period) and archived
    # rows (which keep theirs). Pre-filtering by period would hide drafts
    # from the one audience allowed to see them.
    candidates = await ctx.services.knowledge_records.list_records(
        company_id=ctx.company_id,
        record_type=args.record_type,
        limit=SCAN_LIMIT,
    )

    visible = [
        record for record in candidates if _admin_can_see(record, company_id=ctx.company_id, at=at)
    ]
    if not args.include_drafts:
        visible = [
            record
            for record in visible
            if KnowledgeLifecycleState(record.lifecycle_state) is not KnowledgeLifecycleState.DRAFT
        ]

    ordered = rank_subjects(args.search_text, [record.subject_key for record in visible])
    ranking = {key: position for position, key in enumerate(ordered)}
    hits = sorted(
        (record for record in visible if record.subject_key in ranking),
        key=lambda record: (ranking[record.subject_key], -record.version),
    )

    return {
        "total": len(hits),
        # Reported rather than silently applied: an assistant that says "we
        # have three prices" off a shortened list is confidently wrong.
        "has_more": len(hits) > MAX_RESULTS,
        "records": [_summary(record) for record in hits[:MAX_RESULTS]],
    }


async def _get_knowledge_record(ctx: ToolContext, args: GetKnowledgeRecordArgs) -> dict[str, Any]:
    at = datetime.now(UTC)

    # Company-scoped inside the service: another company's id raises
    # EntityNotFoundError, which is what the model is told. Not "forbidden" —
    # answering that would confirm the record exists.
    record = await ctx.services.knowledge_records.get(
        company_id=ctx.company_id, record_id=args.record_id
    )

    if not _admin_can_see(record, company_id=ctx.company_id, at=at):
        # Same answer as a record that does not exist, deliberately. A
        # distinct "you may not see this" would make the tool an oracle for
        # what a company has withdrawn.
        raise EntityNotFoundError("KnowledgeRecord", args.record_id)

    versions = await ctx.services.knowledge_records.list_versions(
        company_id=ctx.company_id,
        record_type=KnowledgeRecordType(record.record_type),
        subject_label=record.subject_label,
    )

    return {
        "record": _summary(record),
        # The chain runs through the same predicate as the record itself.
        # One visibility rule, applied everywhere, beats a history view with
        # its own quietly different one.
        "version_chain": [
            _summary(version)
            for version in versions
            if _admin_can_see(version, company_id=ctx.company_id, at=at)
        ],
        "source_reference": record.source_reference,
    }


def register_knowledge_tools(registry: ToolRegistry) -> None:
    """Add the read-only knowledge tools to a registry."""
    registry.register(
        ToolSpec(
            name="search_knowledge",
            description=(
                "Search this workspace's structured knowledge records — prices, policies, "
                "specifications and the like. Pass the administrator's own words as "
                "search_text. Returns each record's values, its lifecycle state and where "
                "it came from. Read-only: it cannot change anything."
            ),
            args_model=SearchKnowledgeArgs,
            handler=_search_knowledge,
            permission="knowledge_records.read",
            confirmation=ConfirmationPolicy.NONE,
            mutating=False,
        )
    )
    registry.register(
        ToolSpec(
            name="get_knowledge_record",
            description=(
                "Fetch one structured knowledge record by id, with its version history "
                "and provenance. Read-only: it cannot change anything."
            ),
            args_model=GetKnowledgeRecordArgs,
            handler=_get_knowledge_record,
            permission="knowledge_records.read",
            confirmation=ConfirmationPolicy.NONE,
            mutating=False,
        )
    )


__all__ = [
    "MAX_RESULTS",
    "SCAN_LIMIT",
    "GetKnowledgeRecordArgs",
    "SearchKnowledgeArgs",
    "register_knowledge_tools",
]
