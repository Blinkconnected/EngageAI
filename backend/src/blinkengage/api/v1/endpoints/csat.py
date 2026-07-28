"""Public, unauthenticated CSAT survey-response endpoint — a customer
follows a signed survey link (generated via
``POST /conversations/{id}/csat-survey-link``, see ``conversations.py``)
and submits a rating with no session/JWT of their own, the same
trust model ``web_chat.py``'s public endpoints already use. See
``docs/architecture/reports-analytics.md``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from blinkengage.api.deps import get_csat_service
from blinkengage.api.schemas.csat import (
    CsatContactInfoRequest,
    CsatContactInfoResponse,
    CsatContextResponse,
    CsatSubmitRequest,
    CsatSubmitResponse,
)
from blinkengage.application.services.csat_service import CsatService
from blinkengage.core.rate_limit import rate_limit_dependency

router = APIRouter(prefix="/csat", tags=["csat"])

# Public, unauthenticated endpoints — rate limited per client IP like every
# other pre-auth public endpoint (webchat session creation, login/register),
# since a valid-looking request needs no credential beyond a guessable-in-
# principle token. Each route gets its own scope so a flood against one
# doesn't eat into another's budget.
_csat_context_rate_limit = rate_limit_dependency(scope="csat_context", limit=30, window_seconds=60)
_csat_contact_info_rate_limit = rate_limit_dependency(
    scope="csat_contact_info", limit=30, window_seconds=60
)
_csat_rate_limit = rate_limit_dependency(scope="csat_respond", limit=30, window_seconds=60)


@router.get(
    "/{conversation_id}",
    response_model=CsatContextResponse,
    dependencies=[Depends(_csat_context_rate_limit)],
)
async def get_csat_context(
    conversation_id: UUID,
    service: Annotated[CsatService, Depends(get_csat_service)],
    token: Annotated[str, Query(...)],
) -> CsatContextResponse:
    """Tells the public feedback page (``/feedback/{conversation_id}``)
    what to render: the rating form directly, a thank-you screen (already
    answered), or a contact-info step first (customer has neither an
    email nor a phone number on file)."""
    context = await service.get_context(conversation_id=conversation_id, token=token)
    return CsatContextResponse(
        conversation_id=context.conversation_id,
        already_responded=context.already_responded,
        needs_contact_info=context.needs_contact_info,
    )


@router.post(
    "/{conversation_id}/contact-info",
    response_model=CsatContactInfoResponse,
    dependencies=[Depends(_csat_contact_info_rate_limit)],
)
async def submit_csat_contact_info(
    conversation_id: UUID,
    payload: CsatContactInfoRequest,
    service: Annotated[CsatService, Depends(get_csat_service)],
    token: Annotated[str, Query(...)],
) -> CsatContactInfoResponse:
    await service.submit_contact_info(
        conversation_id=conversation_id,
        token=token,
        email=payload.email,
        phone=payload.phone,
    )
    return CsatContactInfoResponse(conversation_id=conversation_id)


@router.post(
    "/{conversation_id}/respond",
    response_model=CsatSubmitResponse,
    dependencies=[Depends(_csat_rate_limit)],
)
async def submit_csat_response(
    conversation_id: UUID,
    payload: CsatSubmitRequest,
    service: Annotated[CsatService, Depends(get_csat_service)],
    token: Annotated[str, Query(...)],
) -> CsatSubmitResponse:
    response = await service.submit(
        conversation_id=conversation_id,
        token=token,
        rating=payload.rating,
        comment=payload.comment,
    )
    return CsatSubmitResponse(
        conversation_id=response.conversation_id, rating=response.rating, comment=response.comment
    )
