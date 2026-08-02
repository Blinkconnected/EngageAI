from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)

from blinkengage.api.deps import (
    get_ai_service,
    get_autopilot_service,
    get_conversation_service,
    get_csat_service,
    get_internal_note_service,
    get_media_company_id,
    get_settings_dep,
    require_permission,
)
from blinkengage.api.range_requests import parse_range_header
from blinkengage.api.schemas.conversation import (
    AttachmentResponse,
    ConversationResponse,
    ConversationTransferRequest,
    ConversationTransferResponse,
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
from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.autopilot_service import AutopilotService, AutopilotTrigger
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.csat_service import CsatService
from blinkengage.application.services.internal_note_service import InternalNoteService
from blinkengage.core.auth_context import AuthContext
from blinkengage.core.config import Settings
from blinkengage.core.media_tokens import MediaTokenError, sign, verify
from blinkengage.domain.inbox_views import InboxView
from blinkengage.domain.media import (
    is_inline_renderable,
    kind_for,
    may_need_fallback,
)
from blinkengage.domain.operational_state import STATE_TEXT
from blinkengage.domain.sla import SlaHealth
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationPriority,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.message import Message, MessageAttachment
from blinkengage.infrastructure.repositories.conversation_repository import InboxRow

#: How long a browser may keep an attachment's bytes. An attachment is
#: immutable once uploaded, so this is bounded only by the signed URL's
#: own lifetime being shorter — the cache entry outlives the URL, which
#: is what makes scrolling back up a conversation instant.
MEDIA_CACHE_SECONDS = 60 * 60 * 24 * 7

router = APIRouter(prefix="/conversations", tags=["conversations"])


def attachment_response(
    attachment: MessageAttachment,
    *,
    conversation_id: UUID,
    company_id: UUID,
    settings: Settings,
) -> AttachmentResponse:
    """One attachment, with everything the console needs to render it.

    The media URL is minted here rather than by a separate round trip per
    attachment: a conversation with twenty photos would otherwise need
    twenty extra requests before it could show anything, which is precisely
    the stutter this work exists to remove.
    """
    kind = kind_for(attachment.content_type)
    inline = is_inline_renderable(attachment.content_type)

    media_url: str | None = None
    if inline:
        token = sign(attachment_id=attachment.id, company_id=company_id, settings=settings)
        media_url = (
            f"{settings.api_v1_prefix}/conversations/{conversation_id}"
            f"/attachments/{attachment.id}/media"
            f"?exp={token.expires_at}&sig={token.signature}"
        )

    return AttachmentResponse(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        validation_status=attachment.validation_status,
        message_id=attachment.message_id,
        created_at=attachment.created_at,
        kind=kind,
        inline=inline,
        needs_fallback=may_need_fallback(attachment.content_type),
        width=attachment.width,
        height=attachment.height,
        media_url=media_url,
    )


def _to_message_response(
    message: Message,
    attachments: list[MessageAttachment],
    *,
    company_id: UUID,
    settings: Settings,
) -> MessageResponse:
    response = MessageResponse.model_validate(message)
    return response.model_copy(
        update={
            "attachments": [
                attachment_response(
                    a,
                    conversation_id=message.conversation_id,
                    company_id=company_id,
                    settings=settings,
                )
                for a in attachments
            ]
        }
    )


def _to_conversation_response(
    conversation: Conversation,
    unread_count: int = 0,
    sla_health: SlaHealth = SlaHealth.HEALTHY,
    customer_name: str | None = None,
    row: InboxRow | None = None,
) -> ConversationResponse:
    """One conversation, with the operational facts that are not on its row.

    ``row`` is present for the Inbox, which needs every conversation to
    explain why it is visible. The single-conversation endpoints pass none:
    the detail screen shows the whole Conversation Story, which answers the
    same question in far more depth.
    """
    response = ConversationResponse.model_validate(conversation)
    update: dict[str, object] = {
        "unread_count": unread_count,
        "sla_health": sla_health,
        "customer_name": customer_name,
    }
    if row is not None:
        update.update(
            {
                "state": row.state,
                "state_text": STATE_TEXT[row.state],
                "owner_kind": row.owner.kind.value,
                "owner_label": row.owner.describe(),
                "owner_since": row.owner_since,
                "last_event": row.last_event,
                "last_event_kind": row.last_event_kind,
                "last_event_at": row.last_event_at,
            }
        )
    return response.model_copy(update=update)


async def _one(service: ConversationService, conversation: Conversation) -> ConversationResponse:
    """One conversation with the two things that are not on its row.

    Every endpoint here that returns a single conversation returns exactly
    this — so a field derived rather than stored (SLA health, unread count)
    is added in one place and cannot be forgotten by the next endpoint.
    """
    unread = await service.unread_counts(conversation_ids=[conversation.id])
    health = await service.sla_health(
        company_id=conversation.company_id, conversation_ids=[conversation.id]
    )
    return _to_conversation_response(
        conversation,
        unread.get(conversation.id, 0),
        health.get(conversation.id, SlaHealth.HEALTHY),
    )


async def _viewer_agent_id(service: ConversationService, auth: AuthContext) -> UUID | None:
    """The agent profile of whoever is asking, if they have one.

    ``None`` for a supervisor or owner with no agent profile — which makes
    "assigned to me" empty rather than wrong. It used to be neither: a null
    id compared with SQL equality matched every *unassigned* conversation, so
    the whole backlog came back as somebody's personal list.
    """
    return await service.agent_id_for_user(company_id=auth.company_id, user_id=auth.user_id)


@router.get("/workload", response_model=dict[str, int])
async def read_workload(
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> dict[str, int]:
    """How many conversations are in each work queue.

    Counted across the company in one query rather than over the loaded page:
    a count taken from fifty rows is wrong in exactly the situation it matters,
    which is a busy queue.
    """
    counts = await service.workload(
        company_id=auth.company_id,
        viewer_agent_id=await _viewer_agent_id(service, auth),
    )
    return {view.value: count for view, count in counts.items()}


@router.get("", response_model=Page[ConversationResponse])
async def list_conversations(
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    page_params: Annotated[PageParams, Depends()],
    status_filter: ConversationStatus | None = None,
    customer_id: UUID | None = None,
    assigned_agent_id: UUID | None = None,
    queue_id: UUID | None = None,
    priority: ConversationPriority | None = None,
    unassigned_only: bool = False,
    view: InboxView | None = None,
) -> Page[ConversationResponse]:
    rows, total = await service.list_conversations(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        status=status_filter,
        customer_id=customer_id,
        assigned_agent_id=assigned_agent_id,
        queue_id=queue_id,
        priority=priority,
        unassigned_only=unassigned_only,
        view=view,
        viewer_agent_id=await _viewer_agent_id(service, auth),
    )
    unread_counts = await service.unread_counts(
        conversation_ids=[row.conversation.id for row in rows]
    )
    return Page(
        items=[
            _to_conversation_response(
                row.conversation,
                unread_counts.get(row.conversation.id, 0),
                row.sla_health,
                row.customer_name,
                row,
            )
            for row in rows
        ],
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
    return await _one(service, conversation)


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
        assigned_agent_id=None,
        priority=payload.priority,
        queue_id=payload.queue_id,
        actor_user_id=auth.user_id,
    )
    return await _one(service, conversation)


@router.post(
    "/{conversation_id}/transfer",
    response_model=ConversationTransferResponse,
    status_code=status.HTTP_201_CREATED,
)
async def transfer_conversation(
    conversation_id: UUID,
    payload: ConversationTransferRequest,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.transfer"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationTransferResponse:
    transfer = await service.transfer(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        target_type=payload.target_type,
        to_agent_id=payload.to_agent_id,
        to_department_id=payload.to_department_id,
        note=payload.note,
        actor_user_id=auth.user_id,
    )
    return ConversationTransferResponse.model_validate(transfer)


@router.post("/{conversation_id}/pick", response_model=ConversationResponse)
async def pick_conversation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.pick"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.pick(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        actor_user_id=auth.user_id,
    )
    return await _one(service, conversation)


@router.post("/{conversation_id}/autopilot", response_model=ConversationResponse)
async def request_autopilot(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    autopilot: Annotated[AutopilotService, Depends(get_autopilot_service)],
    ai_service: Annotated[AiService, Depends(get_ai_service)],
) -> ConversationResponse:
    """Hand this conversation to AI Autopilot on the agent's explicit
    request — the "On Agent Request" activation mode.

    Rides ``conversations.manage`` rather than a new permission: an agent
    who may reply to a conversation may also ask AI to reply on their
    behalf, and a bespoke permission would be invisible on every existing
    role until someone remembered to grant it.

    Returns the conversation either way. Autopilot may decline (low
    confidence, the model asking for a human, no configured provider), in
    which case it hands straight back and ``autopilot_active`` is false
    in the response — the caller can see that it didn't take over.
    """
    outcome = await autopilot.run(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        trigger=AutopilotTrigger.AGENT_REQUEST,
        ai_service_factory=lambda: ai_service,
        actor_user_id=auth.user_id,
    )
    if outcome.reason == "mode_disabled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AI Autopilot's 'on agent request' mode is turned off for this company. "
                "An administrator can enable it in Settings → AI."
            ),
        )
    if outcome.reason == "ai_unavailable":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI is not configured or is currently unavailable for this company.",
        )

    conversation = await service.get(company_id=auth.company_id, conversation_id=conversation_id)
    return await _one(service, conversation)


@router.delete("/{conversation_id}/autopilot", response_model=ConversationResponse)
async def stop_autopilot(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    """Take a conversation back from AI Autopilot — the inverse of
    ``POST /conversations/{id}/autopilot``, and the only way to stop
    Autopilot on a conversation that is already assigned (which
    ``/pick`` cannot do).

    Rides ``conversations.manage``, symmetric with the POST: an agent who
    may hand a conversation to AI may take it back. Idempotent — stopping
    Autopilot on a conversation it doesn't hold returns the conversation
    unchanged rather than erroring.
    """
    conversation = await service.take_over_from_autopilot(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        actor_user_id=auth.user_id,
    )
    return await _one(service, conversation)


@router.post("/{conversation_id}/release", response_model=ConversationResponse)
async def release_conversation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.release"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> ConversationResponse:
    conversation = await service.release(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        actor_user_id=auth.user_id,
        actor_has_transfer_permission=auth.has_permission("conversations.transfer"),
    )
    return await _one(service, conversation)


@router.get("/{conversation_id}/transfers", response_model=Page[ConversationTransferResponse])
async def list_conversation_transfers(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[ConversationTransferResponse]:
    items, total = await service.list_transfers(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        offset=page_params.offset,
        limit=page_params.page_size,
    )
    return Page(
        items=[ConversationTransferResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


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
    settings: Annotated[Settings, Depends(get_settings_dep)],
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
            _to_message_response(
                item,
                attachments_by_message.get(item.id, []),
                company_id=auth.company_id,
                settings=settings,
            )
            for item in items
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
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> MessageResponse:
    message = await service.send_reply(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        body=payload.body,
        attachment_ids=payload.attachment_ids,
        actor_user_id=auth.user_id,
        is_ai_assisted=payload.is_ai_assisted,
    )
    attachments_by_message = await service.list_attachments_for_messages(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        message_ids=[message.id],
    )
    return _to_message_response(
        message,
        attachments_by_message.get(message.id, []),
        company_id=auth.company_id,
        settings=settings,
    )


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
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AttachmentResponse:
    data = await file.read()
    attachment = await service.upload_attachment(
        company_id=auth.company_id,
        conversation_id=conversation_id,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        data=data,
    )
    # Through the same builder as the message path, so an attachment gets
    # its kind, dimensions and media URL the moment it is uploaded — the
    # composer can then show a real preview before the reply is even sent.
    return attachment_response(
        attachment,
        conversation_id=conversation_id,
        company_id=auth.company_id,
        settings=settings,
    )


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


@router.get("/{conversation_id}/attachments/{attachment_id}/media")
async def stream_attachment_media(
    conversation_id: UUID,
    attachment_id: UUID,
    request: Request,
    exp: int,
    sig: str,
    company: Annotated[UUID, Depends(get_media_company_id)],
    service: Annotated[ConversationService, Depends(get_conversation_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> Response:
    """Serves an attachment's bytes for **inline display**.

    Authenticated by a short-lived signature in the query string rather
    than a bearer token, because an ``<img src>`` cannot send a header and
    a ``<video>`` needs range requests against a plain URL to let somebody
    drag the scrubber. See ``core/media_tokens.py`` for why this is a bare
    HMAC and not a second kind of session token.

    Tenant ownership is re-checked against the database on every request,
    not merely trusted from the signature: a leaked URL should be a leak of
    one file for a few minutes, never a way to read another company's
    conversation.

    Supports ``Range``, which is what makes seeking work. Without it a
    browser must download an entire video before playing any of it, and
    seeking backwards downloads it again.

    ``Content-Disposition: inline`` — the point of this endpoint. The
    download endpoint next to it sends ``attachment`` instead, which is the
    only difference an agent clicking "Download" should experience.
    """
    try:
        verify(
            attachment_id=attachment_id,
            company_id=company,
            expires_at=exp,
            signature=sig,
            settings=settings,
        )
    except MediaTokenError as exc:
        # 403 rather than 401: there is no credential to re-present, and a
        # browser prompting for a password over an expired image URL would
        # be nonsense. The console re-fetches the message to get a fresh
        # URL instead.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    attachment = await service.get_attachment(
        company_id=company, conversation_id=conversation_id, attachment_id=attachment_id
    )
    if not is_inline_renderable(attachment.content_type):
        # A signature is only ever minted for renderable kinds, so reaching
        # here means somebody reused a URL against a different attachment
        # id — which the signature would already have refused. Belt and
        # braces, and it keeps "inline" meaning one thing.
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This attachment is not displayed inline; download it instead.",
        )

    total = await service.attachment_size(
        company_id=company, conversation_id=conversation_id, attachment_id=attachment_id
    )
    requested = parse_range_header(request.headers.get("range"), total_size=total)

    # Immutable: an attachment's bytes never change once uploaded, so the
    # browser may keep them for as long as it likes. `private` because the
    # URL is per-tenant and must not be held by a shared proxy.
    common = {
        "Accept-Ranges": "bytes",
        "Cache-Control": f"private, max-age={MEDIA_CACHE_SECONDS}, immutable",
        "Content-Disposition": f'inline; filename="{attachment.filename}"',
    }

    if requested is None:
        data = await service.read_attachment_bytes(
            company_id=company,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
        )
        return Response(content=data, media_type=attachment.content_type, headers=common)

    start, end = requested
    data = await service.read_attachment_bytes(
        company_id=company,
        conversation_id=conversation_id,
        attachment_id=attachment_id,
        offset=start,
        length=end - start + 1,
    )
    return Response(
        content=data,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=attachment.content_type,
        headers={**common, "Content-Range": f"bytes {start}-{end}/{total}"},
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
