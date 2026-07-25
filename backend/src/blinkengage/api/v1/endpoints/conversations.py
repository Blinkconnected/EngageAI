from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from blinkengage.api.deps import (
    get_conversation_service,
    get_csat_service,
    get_internal_note_service,
    require_permission,
)
from blinkengage.api.schemas.conversation import (
    AttachmentResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageResponse,
    SendMessageRequest,
)
from blinkengage.api.schemas.csat import CsatSurveyLinkResponse
from blinkengage.api.schemas.internal_note import (
    InternalNoteCreateRequest,
    InternalNoteResponse,
    InternalNoteUpdateRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.csat_service import CsatService
from blinkengage.application.services.internal_note_service import InternalNoteService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.conversation import ConversationStatus
from blinkengage.infrastructure.database.models.message import Message, MessageAttachment

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _to_message_response(
    message: Message, attachments: list[MessageAttachment]
) -> MessageResponse:
    response = MessageResponse.model_validate(message)
    return response.model_copy(
        update={"attachments": [AttachmentResponse.model_validate(a) for a in attachments]}
    )


@router.get("", response_model=Page[ConversationResponse])
async def list_conversations(
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    page_params: Annotated[PageParams, Depends()],
    status_filter: ConversationStatus | None = None,
    customer_id: UUID | None = None,
) -> Page[ConversationResponse]:
    items, total = await service.list_conversations(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        status=status_filter,
        customer_id=customer_id,
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
        queue_id=payload.queue_id,
        actor_user_id=auth.user_id,
    )
    return ConversationResponse.model_validate(conversation)


@router.post("/{conversation_id}/csat-survey-link", response_model=CsatSurveyLinkResponse)
async def generate_csat_survey_link(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
    csat_service: Annotated[CsatService, Depends(get_csat_service)],
) -> CsatSurveyLinkResponse:
    await conversation_service.get(company_id=auth.company_id, conversation_id=conversation_id)
    url = csat_service.build_survey_url(conversation_id=conversation_id)
    return CsatSurveyLinkResponse(url=url)


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
    attachments_by_message = await service.list_attachments_for_messages(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        message_ids=[item.id for item in items],
    )
    return Page(
        items=[
            _to_message_response(item, attachments_by_message.get(item.id, [])) for item in items
        ],
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
    attachments_by_message = await service.list_attachments_for_messages(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        message_ids=[message.id],
    )
    return _to_message_response(message, attachments_by_message.get(message.id, []))


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


@router.get("/{conversation_id}/notes", response_model=Page[InternalNoteResponse])
async def list_internal_notes(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[InternalNoteService, Depends(get_internal_note_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[InternalNoteResponse]:
    items, total = await service.list_notes(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        offset=page_params.offset,
        limit=page_params.page_size,
    )
    return Page(
        items=[InternalNoteResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post(
    "/{conversation_id}/notes",
    response_model=InternalNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_internal_note(
    conversation_id: UUID,
    payload: InternalNoteCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[InternalNoteService, Depends(get_internal_note_service)],
) -> InternalNoteResponse:
    note = await service.create(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        body=payload.body,
        author_user_id=auth.user_id,
    )
    return InternalNoteResponse.model_validate(note)


@router.patch("/{conversation_id}/notes/{note_id}", response_model=InternalNoteResponse)
async def update_internal_note(
    conversation_id: UUID,
    note_id: UUID,
    payload: InternalNoteUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[InternalNoteService, Depends(get_internal_note_service)],
) -> InternalNoteResponse:
    note = await service.update(
        company_id=auth.company_id, note_id=note_id, body=payload.body, actor_user_id=auth.user_id
    )
    return InternalNoteResponse.model_validate(note)


@router.delete("/{conversation_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_internal_note(
    conversation_id: UUID,
    note_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[InternalNoteService, Depends(get_internal_note_service)],
) -> None:
    await service.delete(company_id=auth.company_id, note_id=note_id, actor_user_id=auth.user_id)
