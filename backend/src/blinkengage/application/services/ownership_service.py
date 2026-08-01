"""Moving responsibility, and recording every move.

See ``docs/architecture/queue-lifecycle.md``.

The model has to answer five questions — *who owns this, why, since when, who
owned it before, and why it changed* — and the last two are only answerable
from a history. So every transition is a row, and the current owner is the
newest one rather than a column that could disagree with it.

**Ownership never touches status or queue.** Not once, in this whole module.
That is the point of the milestone: a conversation can be resolved and still
owned, waiting and owned by its queue, in progress and owned by nobody. A
method here that also set a status would be re-coupling the two things this
exists to separate, and it would do it in the place nobody thinks to look.
"""

import uuid
from datetime import UTC, datetime

from blinkengage.domain.ownership import (
    NOBODY,
    Owner,
    OwnerKind,
    Ownership,
    OwnershipReason,
    OwnershipRules,
    hold_until,
)
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership
from blinkengage.infrastructure.repositories.ownership_repository import (
    OwnershipRepository,
)


class OwnershipService:
    def __init__(self, repository: OwnershipRepository) -> None:
        self._repository = repository

    async def current(self, conversation_id: uuid.UUID) -> Ownership | None:
        """Who owns it now. ``None`` only before anything ever has."""
        row = await self._repository.current(conversation_id)
        return _to_ownership(row) if row is not None else None

    async def timeline(self, conversation_id: uuid.UUID) -> list[ConversationOwnership]:
        """Every transition, oldest first — the order a story is read in."""
        return await self._repository.timeline(conversation_id)

    async def transfer(
        self,
        *,
        conversation_id: uuid.UUID,
        company_id: uuid.UUID,
        to: Owner,
        reason: OwnershipReason,
        rules: OwnershipRules | None = None,
        actor_user_id: uuid.UUID | None = None,
        note: str | None = None,
        now: datetime | None = None,
    ) -> Ownership:
        """Hands responsibility to somebody, recording both sides.

        Idempotent on the owner: handing a conversation to whoever already
        holds it changes nothing and writes nothing. A timeline with
        "Sara took over from Sara" in it is a timeline people stop reading,
        and the retry that produces it is ordinary.
        """
        moment = now or datetime.now(UTC)
        rules = rules or OwnershipRules()
        existing = await self._repository.current(conversation_id)
        previous = _to_owner(existing) if existing is not None else NOBODY

        if previous.kind is to.kind and previous.id == to.id:
            return _to_ownership(existing) if existing is not None else _fresh(to, moment, reason)

        row = await self._repository.add(
            ConversationOwnership(
                conversation_id=conversation_id,
                company_id=company_id,
                owner_kind=to.kind,
                owner_id=to.id,
                owner_name=to.name,
                previous_kind=previous.kind,
                previous_id=previous.id,
                previous_name=previous.name,
                reason=reason,
                owned_from=moment,
                holds_until=hold_until(rules, owner=to, from_moment=moment),
                actor_user_id=actor_user_id,
                note=note,
            )
        )
        return _to_ownership(row)

    async def release_to_queue(
        self,
        *,
        conversation_id: uuid.UUID,
        company_id: uuid.UUID,
        queue: Owner,
        reason: OwnershipReason,
        actor_user_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> Ownership:
        """Hands it back to the queue.

        Back to the *queue*, never to nobody. A conversation owned by nobody
        is one nothing will pick up and no escalation can find; the queue is
        answerable until somebody takes it, which is the difference between
        "unassigned" and "unowned".
        """
        return await self.transfer(
            conversation_id=conversation_id,
            company_id=company_id,
            to=queue,
            reason=reason,
            actor_user_id=actor_user_id,
            now=now,
        )

    async def expired_holds(
        self, *, now: datetime, limit: int = 500
    ) -> list[ConversationOwnership]:
        """Sticky holds that have lapsed and not yet been released.

        The sweep's query. A lapsed hold does not release itself — the row
        is a historical fact and cannot be edited — so something has to
        notice and write the next row. Until it does, the conversation is
        still owned by somebody whose claim has run out, which
        ``Ownership.is_held`` reports honestly.
        """
        return await self._repository.expired_holds(now=now, limit=limit)


def _to_owner(row: ConversationOwnership) -> Owner:
    return Owner(kind=row.owner_kind, id=row.owner_id, name=row.owner_name)


def _to_ownership(row: ConversationOwnership) -> Ownership:
    return Ownership(
        owner=_to_owner(row),
        since=row.owned_from,
        reason=row.reason,
        holds_until=row.holds_until,
    )


def _fresh(owner: Owner, moment: datetime, reason: OwnershipReason) -> Ownership:
    return Ownership(owner=owner, since=moment, reason=reason)


def queue_owner(queue_id: uuid.UUID, queue_name: str | None) -> Owner:
    """The queue, as an owner. A helper because it is written everywhere."""
    return Owner(kind=OwnerKind.QUEUE, id=queue_id, name=queue_name)


def agent_owner(agent_id: uuid.UUID, agent_name: str | None) -> Owner:
    return Owner(kind=OwnerKind.HUMAN_AGENT, id=agent_id, name=agent_name)


#: AI as a queue worker. A constant because it carries no id — there is one
#: AI, and giving it a kind of its own is what stops "AI has it" being
#: recorded as "nobody has it".
AI_OWNER = Owner(kind=OwnerKind.AI_QUEUE_WORKER)


__all__ = [
    "AI_OWNER",
    "OwnershipService",
    "agent_owner",
    "queue_owner",
]
