"""Redacting a message, and reading the record of past redactions.

Gated on ``messages.redact`` — Administrators and the Owner, never an
Agent. See ``docs/architecture/message-redaction.md`` for why redaction
rather than deletion, and why an agent does not hold it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from blinkengage.api.deps import get_message_redaction_service, require_permission
from blinkengage.api.schemas.message_redaction import (
    MessageRedactionRequest,
    MessageRedactionResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.message_redaction_service import MessageRedactionService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.message_redaction import RedactionRuleViolation

router = APIRouter(tags=["message-redaction"])

_STATUS_BY_CODE = {
    "not_found": status.HTTP_404_NOT_FOUND,
    # Already gone. A conflict rather than a success, so a duplicate
    # delivery cannot append a second account of one removal.
    "already_redacted": status.HTTP_409_CONFLICT,
}


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/redact",
    response_model=MessageRedactionResponse,
    status_code=status.HTTP_200_OK,
)
async def redact_message(
    conversation_id: UUID,
    message_id: UUID,
    payload: MessageRedactionRequest,
    auth: Annotated[AuthContext, Depends(require_permission("messages.redact"))],
    service: Annotated[MessageRedactionService, Depends(get_message_redaction_service)],
) -> MessageRedactionResponse:
    """Remove what a message said. **This cannot be undone.**

    The message stays in the thread — in order, attributed, timestamped,
    marked redacted — because a message sent over WhatsApp or email
    cannot be unsent and deleting our copy would destroy our half of a
    record the customer still holds.
    """
    try:
        record = await service.redact(
            company_id=auth.company_id,
            conversation_id=conversation_id,
            message_id=message_id,
            reason=payload.reason,
            actor_user_id=auth.user_id,
        )
    except RedactionRuleViolation as violation:
        raise HTTPException(
            status_code=_STATUS_BY_CODE.get(violation.code, status.HTTP_400_BAD_REQUEST),
            detail=violation.message,
        ) from violation
    return MessageRedactionResponse.model_validate(record)


@router.get("/message-redactions", response_model=Page[MessageRedactionResponse])
async def list_message_redactions(
    auth: Annotated[AuthContext, Depends(require_permission("messages.redact"))],
    service: Annotated[MessageRedactionService, Depends(get_message_redaction_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[MessageRedactionResponse]:
    """Every redaction this company has performed, newest first.

    Gated on the same permission as performing one: the list names
    customers and quotes the reasons given, so it is not less sensitive
    than the action it records.
    """
    items, total = await service.list_for_company(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
    )
    return Page(
        items=[MessageRedactionResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
