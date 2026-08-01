"""Conversation ownership — ``/api/v1/conversations/{id}/ownership``.

Read-only. Ownership moves as a *consequence* of something — a pickup, a
transfer, a resolution, a window expiring — and an endpoint that set it
directly would be a way to change who is answerable without the thing that
made them answerable ever happening.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from blinkengage.api.deps import get_conversation_service, get_ownership_service, require_permission
from blinkengage.api.schemas.ownership import (
    ConversationOwnershipResponse,
    CurrentOwnershipResponse,
    OwnerResponse,
    OwnershipChangeResponse,
)
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.ownership_service import OwnershipService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.ownership import REASON_TEXT, Owner, OwnerKind, OwnershipReason
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _owner(kind: OwnerKind | None, owner_id: UUID | None, name: str | None) -> OwnerResponse:
    resolved = Owner(kind=kind or OwnerKind.NOBODY, id=owner_id, name=name)
    return OwnerResponse(
        kind=resolved.kind.value,
        id=resolved.id,
        name=resolved.name,
        label=resolved.describe(),
        responsibility=resolved.responsibility.value,
        unowned=resolved.is_nobody,
    )


def _change(row: ConversationOwnership, *, until: datetime) -> OwnershipChangeResponse:
    """One hop, and how long it lasted.

    ``until`` is the next row's moment, or now for the last one — which is
    what makes an in-flight conversation countable rather than a gap.
    """
    reason: OwnershipReason = row.reason
    return OwnershipChangeResponse(
        owner=_owner(row.owner_kind, row.owner_id, row.owner_name),
        previous=_owner(row.previous_kind, row.previous_id, row.previous_name),
        reason=reason.value,
        reason_text=REASON_TEXT[reason],
        at=row.owned_from,
        held_for_seconds=max((until - row.owned_from).total_seconds(), 0.0),
        actor_user_id=row.actor_user_id,
        note=row.note,
    )


@router.get("/{conversation_id}/ownership", response_model=ConversationOwnershipResponse)
async def read_ownership(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    conversations: Annotated[ConversationService, Depends(get_conversation_service)],
    ownership: Annotated[OwnershipService, Depends(get_ownership_service)],
) -> ConversationOwnershipResponse:
    """Who owns this, why, since when, who owned it before, and why it moved.

    The conversation is fetched first purely to enforce tenancy — the
    ownership rows carry a ``company_id`` but reading them directly would
    make this endpoint the one place that checked it for itself.
    """
    await conversations.get(company_id=auth.company_id, conversation_id=conversation_id)

    now = datetime.now(UTC)
    current = await ownership.current(conversation_id)
    timeline = await ownership.timeline(conversation_id)

    # Each hop lasts until the next one, and the last until now.
    boundaries = [row.owned_from for row in timeline[1:]] + [now]
    latest = timeline[-1] if timeline else None

    return ConversationOwnershipResponse(
        current=(
            None
            if current is None
            else CurrentOwnershipResponse(
                owner=_owner(current.owner.kind, current.owner.id, current.owner.name),
                reason=current.reason.value,
                reason_text=REASON_TEXT[current.reason],
                since=current.since,
                holds_until=current.holds_until,
                held=current.is_held(now=now),
                held_for_seconds=max(current.held_for(now=now).total_seconds(), 0.0),
            )
        ),
        previous=(
            None
            if latest is None or latest.previous_kind is None
            else _owner(latest.previous_kind, latest.previous_id, latest.previous_name)
        ),
        # The arrival is not a hand-over, so a conversation that has only
        # ever sat in its queue reports zero rather than one.
        transfers=max(len(timeline) - 1, 0),
        timeline=[
            _change(row, until=until) for row, until in zip(timeline, boundaries, strict=True)
        ],
    )


__all__ = ["router"]
