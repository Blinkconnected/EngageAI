"""Conversation Memory — working memory for one conversation.

Pure value objects; the store that holds them is
``application/services/conversation_memory_service.py``.

**A deliberately different contract from the other three tiers.** This
carries no confidence, no evidence, no lifecycle, no steward and no human
state — every field of the memory-fact contract is meaningless for state
that dies when the conversation closes. Modelling it as a fact would mean
either eight permanently-null columns or loosening the contract for the
tiers that need it, and the contract is the reason the platform is
trustworthy.

It exists because without it an assistant reveals it is not really
following the thread: a customer who gave their order number at turn three
is asked for it again at turn twenty. That is the most recognisable
failure in conversational software and it is a memory problem, not a model
problem.

**The boundary is distillation.** Working memory is not evidence, and
nothing here is ever believed. At the end of a conversation a separate,
asynchronous step may turn some of it into evidence-backed facts in
Customer or Organizational memory — and that step is gated, so a company
that forbids learning still gets full working memory during conversations
and retains nothing after them. That is a coherent product for a regulated
tenant rather than an all-or-nothing switch.

Stage 2 builds the store and the contract. It does **not** build the
distillation step, which requires deciding what is worth remembering and
is therefore an Intelligence concern.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

#: Working memory is bounded on purpose. An unbounded structure grows with
#: conversation length until it no longer fits in any prompt and the thing
#: it was built to prevent — forgetting turn three — happens anyway, just
#: later and less predictably.
MAX_ENTITIES = 50
MAX_OPEN_QUESTIONS = 20
MAX_COMMITMENTS = 20
MAX_PREFERENCES = 20

#: The shape stored in Redis, versioned so a deployment reading a value
#: written by an older one migrates rather than crashes.
CURRENT_SCHEMA_VERSION = 1


class EntityKind(StrEnum):
    """What kind of thing was resolved in the conversation.

    A closed set, because these are read by name downstream — an
    open-ended bag would let two callers write ``order`` and ``order_id``
    and neither would find the other's.
    """

    ORDER = "order"
    PRODUCT = "product"
    INVOICE = "invoice"
    AMOUNT = "amount"
    DATE = "date"
    LOCATION = "location"
    PERSON = "person"
    REFERENCE = "reference"
    OTHER = "other"


@dataclass(frozen=True)
class ResolvedEntity:
    """Something concrete the conversation established.

    ``turn`` is kept so a later reader can say *"you mentioned order 4471
    earlier"* and be right about when — and so the oldest entries are the
    ones evicted when the bound is reached.
    """

    kind: EntityKind
    value: str
    turn: int
    label: str | None = None


@dataclass(frozen=True)
class OpenQuestion:
    """Something asked and not yet answered.

    The highest-value item here. A conversation that closes with an open
    question is the shape of most bad support experiences, and it is
    invisible unless something tracks it.
    """

    text: str
    asked_by: str
    turn: int
    answered: bool = False


@dataclass(frozen=True)
class Commitment:
    """Something the company said it would do, in this thread.

    Deliberately *not* the same thing as a ``promise_made`` memory fact. A
    commitment here is working state — noticed, unconfirmed, gone when the
    conversation ends. It becomes a fact only when a human confirms it,
    because "we'll refund you by Thursday" is an obligation and inferring
    one nobody made is worse than missing one that was.
    """

    text: str
    turn: int
    due_at: datetime | None = None


@dataclass(frozen=True)
class WorkingMemory:
    """Everything the platform is holding about a live conversation.

    Immutable. Every mutation returns a new value, so a caller cannot
    accidentally share and mutate one instance across two requests — which
    matters here because two agents can have the same conversation open.
    """

    conversation_id: UUID
    company_id: UUID
    entities: tuple[ResolvedEntity, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    commitments: tuple[Commitment, ...] = ()
    stated_preferences: tuple[str, ...] = ()
    #: A rolling recap of turns already dropped from the message window, so
    #: a long conversation does not require re-reading its whole history.
    summary: str | None = None
    turn_count: int = 0
    updated_at: datetime | None = None
    schema_version: int = CURRENT_SCHEMA_VERSION

    def with_entity(self, entity: ResolvedEntity) -> WorkingMemory:
        """Adds or replaces an entity.

        Replacement is by ``(kind, value)``: the same order number
        mentioned three times is one entity, not three, and letting it be
        three would evict genuinely different entities to make room for
        duplicates.
        """
        kept = tuple(
            existing
            for existing in self.entities
            if not (existing.kind is entity.kind and existing.value == entity.value)
        )
        return replace(self, entities=_bound(kept + (entity,), MAX_ENTITIES))

    def with_open_question(self, question: OpenQuestion) -> WorkingMemory:
        return replace(
            self, open_questions=_bound(self.open_questions + (question,), MAX_OPEN_QUESTIONS)
        )

    def answering(self, text: str) -> WorkingMemory:
        """Marks the matching open question answered.

        Kept rather than removed, so the record of the conversation still
        shows the question was asked. A question that vanished when
        answered would make "were they ever asked?" unanswerable.
        """
        return replace(
            self,
            open_questions=tuple(
                replace(question, answered=True)
                if question.text == text and not question.answered
                else question
                for question in self.open_questions
            ),
        )

    def with_commitment(self, commitment: Commitment) -> WorkingMemory:
        return replace(self, commitments=_bound(self.commitments + (commitment,), MAX_COMMITMENTS))

    def with_preference(self, preference: str) -> WorkingMemory:
        if preference in self.stated_preferences:
            return self
        return replace(
            self,
            stated_preferences=_bound(self.stated_preferences + (preference,), MAX_PREFERENCES),
        )

    def with_summary(self, summary: str) -> WorkingMemory:
        return replace(self, summary=summary)

    def advanced(self) -> WorkingMemory:
        return replace(self, turn_count=self.turn_count + 1)

    @property
    def unanswered_questions(self) -> tuple[OpenQuestion, ...]:
        return tuple(question for question in self.open_questions if not question.answered)

    @property
    def is_empty(self) -> bool:
        return not (
            self.entities
            or self.open_questions
            or self.commitments
            or self.stated_preferences
            or self.summary
        )


def _bound[T](items: tuple[T, ...], limit: int) -> tuple[T, ...]:
    """Keeps the newest ``limit`` items.

    Oldest-first eviction, because in a conversation the recent turn is
    almost always the relevant one — and because an unbounded structure
    fails silently by growing past what any consumer can use.
    """
    return items[-limit:] if len(items) > limit else items


def to_payload(memory: WorkingMemory) -> dict[str, Any]:
    """Serialises for the store. Plain JSON types only."""
    return {
        "schema_version": memory.schema_version,
        "conversation_id": str(memory.conversation_id),
        "company_id": str(memory.company_id),
        "entities": [
            {
                "kind": entity.kind.value,
                "value": entity.value,
                "turn": entity.turn,
                "label": entity.label,
            }
            for entity in memory.entities
        ],
        "open_questions": [
            {
                "text": question.text,
                "asked_by": question.asked_by,
                "turn": question.turn,
                "answered": question.answered,
            }
            for question in memory.open_questions
        ],
        "commitments": [
            {
                "text": commitment.text,
                "turn": commitment.turn,
                "due_at": commitment.due_at.isoformat() if commitment.due_at else None,
            }
            for commitment in memory.commitments
        ],
        "stated_preferences": list(memory.stated_preferences),
        "summary": memory.summary,
        "turn_count": memory.turn_count,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


def from_payload(payload: dict[str, Any]) -> WorkingMemory:
    """Reads a stored value back.

    Unknown entity kinds fall back to ``OTHER`` and unparseable timestamps
    to ``None``, rather than raising. A conversation must not become
    unusable because a newer deployment wrote a value this one does not
    recognise — the same reasoning ``ServiceContext.setting`` applies to a
    version written before a module existed.
    """
    version = int(payload.get("schema_version", CURRENT_SCHEMA_VERSION))
    if version > CURRENT_SCHEMA_VERSION:
        # Written by a newer deployment. Reading it as if it were ours
        # would silently drop whatever it added, so the honest answer is an
        # empty working memory: the conversation continues, slightly less
        # informed, instead of continuing on a misread value.
        return WorkingMemory(
            conversation_id=UUID(payload["conversation_id"]),
            company_id=UUID(payload["company_id"]),
            schema_version=version,
        )

    return WorkingMemory(
        conversation_id=UUID(payload["conversation_id"]),
        company_id=UUID(payload["company_id"]),
        entities=tuple(
            ResolvedEntity(
                kind=_entity_kind(item.get("kind")),
                value=str(item.get("value", "")),
                turn=int(item.get("turn", 0)),
                label=item.get("label"),
            )
            for item in payload.get("entities", [])
        ),
        open_questions=tuple(
            OpenQuestion(
                text=str(item.get("text", "")),
                asked_by=str(item.get("asked_by", "")),
                turn=int(item.get("turn", 0)),
                answered=bool(item.get("answered", False)),
            )
            for item in payload.get("open_questions", [])
        ),
        commitments=tuple(
            Commitment(
                text=str(item.get("text", "")),
                turn=int(item.get("turn", 0)),
                due_at=_parse_dt(item.get("due_at")),
            )
            for item in payload.get("commitments", [])
        ),
        stated_preferences=tuple(payload.get("stated_preferences", [])),
        summary=payload.get("summary"),
        turn_count=int(payload.get("turn_count", 0)),
        updated_at=_parse_dt(payload.get("updated_at")),
        schema_version=version,
    )


def _entity_kind(value: object) -> EntityKind:
    try:
        return EntityKind(str(value))
    except ValueError:
        return EntityKind.OTHER


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MAX_COMMITMENTS",
    "MAX_ENTITIES",
    "MAX_OPEN_QUESTIONS",
    "MAX_PREFERENCES",
    "Commitment",
    "EntityKind",
    "OpenQuestion",
    "ResolvedEntity",
    "WorkingMemory",
    "from_payload",
    "to_payload",
]
