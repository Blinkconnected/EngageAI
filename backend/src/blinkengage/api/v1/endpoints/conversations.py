from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from blinkengage.api.deps import get_conversation_service, require_permission
from blinkengage.api.schemas.conversation import (
    AttachmentResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageResponse,
    SendMessageRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.conversation import ConversationStatus

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=Page[ConversationResponse])
async def list_conversations(
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    page_params: Annotated[PageParams, Depends()],
    status_filter: ConversationStatus | None = None,
) -> Page[ConversationResponse]:
    items, total = await service.list_conversations(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        status=status_filter,
    )
    return Page(
        items=[ConversationResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.get(company_id=auth.company_id, conversation_id=conversation_id)
    return ConversationResponse.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.update(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        status=payload.status,
        assigned_agent_id=payload.assigned_agent_id,
        actor_user_id=auth.user_id,
    )
    return ConversationResponse.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.delete"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> None:
    await service.delete(
        company_id=auth.company_id, conversation_id=conversation_id, actor_user_id=auth.user_id
    )


@router.get("/{conversation_id}/messages", response_model=Page[MessageResponse])
async def list_messages(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[MessageResponse]:
    items, total = await service.list_messages(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        offset=page_params.offset,
        limit=page_params.page_size,
    )
    return Page(
        items=[MessageResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> MessageResponse:
    message = await service.send_reply(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        body=payload.body,
        attachment_ids=payload.attachment_ids,
        actor_user_id=auth.user_id,
    )
    return MessageResponse.model_validate(message)


@router.post(
    "/{conversation_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    file: Annotated[UploadFile, File()],
) -> AttachmentResponse:
    data = await file.read()
    attachment = await service.upload_attachment(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )
    return AttachmentResponse.model_validate(attachment)


@router.get("/{conversation_id}/attachments/{attachment_id}/download")
async def download_attachment(
    conversation_id: UUID,
    attachment_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> Response:
    data, attachment = await service.download_attachment(
        company_id=auth.company_id, conversation_id=conversation_id, attachment_id=attachment_id
    )
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'attachment; filename="{attachment.filename}"'},
    )
