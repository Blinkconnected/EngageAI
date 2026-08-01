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
        kind=resolved.kind.value, id=resolved.id, name=resolved.name, label=resolved.describe()
    )


def _change(row: ConversationOwnership) -> OwnershipChangeResponse:
    reason: OwnershipReason = row.reason
    return OwnershipChangeResponse(
        owner=_owner(row.owner_kind, row.owner_id, row.owner_name),
        previous=_owner(row.previous_kind, row.previous_id, row.previous_name),
        reason=reason.value,
        reason_text=REASON_TEXT[reason],
        at=row.owned_from,
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

    current = await ownership.current(conversation_id)
    timeline = await ownership.timeline(conversation_id)

    return ConversationOwnershipResponse(
        current=(
            None
            if current is None
            else CurrentOwnershipResponse(
                owner=OwnerResponse(
                    kind=current.owner.kind.value,
                    id=current.owner.id,
                    name=current.owner.name,
                    label=current.owner.describe(),
                ),
                reason=current.reason.value,
                reason_text=REASON_TEXT[current.reason],
                since=current.since,
                holds_until=current.holds_until,
                held=current.is_held(now=datetime.now(UTC)),
            )
        ),
        timeline=[_change(row) for row in timeline],
    )


__all__ = ["router"]
