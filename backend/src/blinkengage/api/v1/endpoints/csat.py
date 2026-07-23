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
from blinkengage.api.schemas.csat import CsatSubmitRequest, CsatSubmitResponse
from blinkengage.application.services.csat_service import CsatService

router = APIRouter(prefix="/csat", tags=["csat"])


@router.post("/{conversation_id}/respond", response_model=CsatSubmitResponse)
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
