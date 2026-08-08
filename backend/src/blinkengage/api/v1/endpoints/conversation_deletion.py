"""Requesting a conversation's deletion, and deciding on it.

Two permissions, deliberately different people:

* ``conversations.delete_request`` — ask. Every agent has it.
* ``conversations.delete_approve`` — decide. Company administrators.
* ``conversations.delete`` — delete outright, with no request and no
  recorded reason. The Owner alone.

See ``docs/architecture/conversation-deletion.md``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from blinkengage.api.deps import (
    get_conversation_deletion_service,
    get_user_repository,
    require_permission,
)
from blinkengage.api.schemas.conversation_deletion import (
    ConversationDeletionDecision,
    ConversationDeletionRequestCreate,
    ConversationDeletionRequestResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.conversation_deletion_service import (
    ConversationDeletionService,
)
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.conversation_deletion import DeletionRequestStatus, DeletionRuleViolation
from blinkengage.infrastructure.database.models.conversation_deletion_request import (
    ConversationDeletionRequest,
)
from blinkengage.infrastructure.repositories.user_repository import UserRepository

router = APIRouter(tags=["conversation-deletion"])

#: Which rule maps to which status. A rule the client can fix by sending
#: something different is a 400; a collision with the world as it now is
#: — somebody else got there first, or the request is already decided —
#: is a 409, so a client can retry-or-refresh on exactly those.
_STATUS_BY_CODE = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "already_requested": status.HTTP_409_CONFLICT,
    "already_decided": status.HTTP_409_CONFLICT,
    "self_approval": status.HTTP_403_FORBIDDEN,
}


def _http_error(violation: DeletionRuleViolation) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(violation.code, status.HTTP_400_BAD_REQUEST),
        detail=violation.message,
    )


async def _to_response(
    request: ConversationDeletionRequest, users: UserRepository
) -> ConversationDeletionRequestResponse:
    """Names resolved here rather than joined in the repository.

    The approval queue is at most a page of rows and the same
    administrator usually appears on several of them, so two lookups per
    row would be a join added to every read path to save nothing on the
    only one that matters.
    """
    response = ConversationDeletionRequestResponse.model_validate(request)
    if request.requested_by_user_id is not None:
        requester = await users.get_by_id(request.requested_by_user_id)
        response.requested_by_name = requester.full_name if requester else None
    if request.decided_by_user_id is not None:
        decider = await users.get_by_id(request.decided_by_user_id)
        response.decided_by_name = decider.full_name if decider else None
    return response


@router.post(
    "/conversations/{conversation_id}/deletion-request",
    response_model=ConversationDeletionRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_deletion(
    conversation_id: UUID,
    payload: ConversationDeletionRequestCreate,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.delete_request"))],
    service: Annotated[ConversationDeletionService, Depends(get_conversation_deletion_service)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> ConversationDeletionRequestResponse:
    """Ask for a conversation to be deleted. Nothing is deleted here."""
    try:
        request = await service.request(
            company_id=auth.company_id,
            conversation_id=conversation_id,
            reason=payload.reason,
            actor_user_id=auth.user_id,
        )
    except DeletionRuleViolation as violation:
        raise _http_error(violation) from violation
    return await _to_response(request, users)


@router.get(
    "/conversations/{conversation_id}/deletion-request",
    response_model=ConversationDeletionRequestResponse | None,
)
async def get_pending_deletion_request(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationDeletionService, Depends(get_conversation_deletion_service)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> ConversationDeletionRequestResponse | None:
    """The open request against this conversation, or ``null``.

    Gated on plain ``conversations.read``: anybody who can see the
    conversation should be able to see that its deletion has been asked
    for, rather than being offered a button that will 409.
    """
    request = await service.pending_for_conversation(
        company_id=auth.company_id, conversation_id=conversation_id
    )
    return None if request is None else await _to_response(request, users)


@router.get(
    "/conversation-deletion-requests",
    response_model=Page[ConversationDeletionRequestResponse],
)
async def list_deletion_requests(
    auth: Annotated[AuthContext, Depends(require_permission("conversations.delete_approve"))],
    service: Annotated[ConversationDeletionService, Depends(get_conversation_deletion_service)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
    page_params: Annotated[PageParams, Depends()],
    request_status: Annotated[
        DeletionRequestStatus | None,
        Query(alias="status", description="Filter by decision state. Omit for all."),
    ] = None,
) -> Page[ConversationDeletionRequestResponse]:
    items, total = await service.list(
        company_id=auth.company_id,
        status=request_status,
        offset=page_params.offset,
        limit=page_params.page_size,
    )
    return Page(
        items=[await _to_response(item, users) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post(
    "/conversation-deletion-requests/{request_id}/approve",
    response_model=ConversationDeletionRequestResponse,
)
async def approve_deletion_request(
    request_id: UUID,
    payload: ConversationDeletionDecision,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.delete_approve"))],
    service: Annotated[ConversationDeletionService, Depends(get_conversation_deletion_service)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> ConversationDeletionRequestResponse:
    """Agree — and delete the conversation, in the same request."""
    try:
        request = await service.approve(
            company_id=auth.company_id,
            request_id=request_id,
            note=payload.note,
            actor_user_id=auth.user_id,
        )
    except DeletionRuleViolation as violation:
        raise _http_error(violation) from violation
    return await _to_response(request, users)


@router.post(
    "/conversation-deletion-requests/{request_id}/reject",
    response_model=ConversationDeletionRequestResponse,
)
async def reject_deletion_request(
    request_id: UUID,
    payload: ConversationDeletionDecision,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.delete_approve"))],
    service: Annotated[ConversationDeletionService, Depends(get_conversation_deletion_service)],
    users: Annotated[UserRepository, Depends(get_user_repository)],
) -> ConversationDeletionRequestResponse:
    """Decline, and say why — the note is required in this direction."""
    if payload.note is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Say why you are turning this down. The person who asked only "
                "sees what you write here."
            ),
        )
    try:
        request = await service.reject(
            company_id=auth.company_id,
            request_id=request_id,
            note=payload.note,
            actor_user_id=auth.user_id,
        )
    except DeletionRuleViolation as violation:
        raise _http_error(violation) from violation
    return await _to_response(request, users)
