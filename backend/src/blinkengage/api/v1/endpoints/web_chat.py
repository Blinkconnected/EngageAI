"""Web Chat REST session endpoint + WebSocket gateway. See
``docs/architecture/web-chat.md``.
"""

import asyncio
import contextlib
from typing import Annotated
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import (
    get_channel_provider_factory_ws,
    get_chat_session_store_ws,
    get_db_session_ws,
    get_event_publisher_ws,
    get_realtime_publisher_ws,
    get_web_chat_session_service,
)
from blinkengage.api.schemas.web_chat import (
    CreateChatSessionRequest,
    CreateChatSessionResponse,
    WidgetMessageIn,
)
from blinkengage.application.services.inbound_message_events import (
    publish_inbound_message_events,
)
from blinkengage.application.services.web_chat_session_service import WebChatSessionService
from blinkengage.core.rate_limit import rate_limit_dependency
from blinkengage.domain.exceptions import DomainError
from blinkengage.infrastructure.cache.chat_session_store import ChatSessionStore
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.channels.providers.web_chat import session_channel_name
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)

router = APIRouter(prefix="/web-chat", tags=["web-chat"])

_session_rate_limit = rate_limit_dependency(scope="webchat_session", limit=30, window_seconds=60)


@router.post(
    "/{channel_config_id}/sessions",
    response_model=CreateChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_session_rate_limit)],
)
async def create_or_resume_session(
    channel_config_id: UUID,
    payload: CreateChatSessionRequest,
    service: Annotated[WebChatSessionService, Depends(get_web_chat_session_service)],
) -> CreateChatSessionResponse:
    result = await service.start_or_resume(
        channel_config_id=channel_config_id, existing_session_token=payload.session_token
    )
    return CreateChatSessionResponse(
        session_token=result.session_token, customer_id=result.customer_id
    )


@router.websocket("/ws/{channel_config_id}")
async def webchat_gateway(
    websocket: WebSocket,
    channel_config_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session_ws)],
    sessions: Annotated[ChatSessionStore, Depends(get_chat_session_store_ws)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher_ws)],
    factory: Annotated[ChannelProviderFactory, Depends(get_channel_provider_factory_ws)],
    events: Annotated[OutboxEventPublisher, Depends(get_event_publisher_ws)],
) -> None:
    token = websocket.query_params.get("token")
    session_data = await sessions.get(token) if token else None
    if token is None or session_data is None or session_data.channel_config_id != channel_config_id:
        await websocket.close(code=4401)
        return

    config = await ChannelConfigRepository(session).get_by_id_any_company(channel_config_id)
    if config is None or not config.is_active:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    provider = factory.build(config)

    async def _forward() -> None:
        async with realtime.subscribe(session_channel_name(token)) as pubsub:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await websocket.send_text(
                        message["data"]
                        if isinstance(message["data"], str)
                        else message["data"].decode()
                    )

    forward_task = asyncio.create_task(_forward())
    try:
        while True:
            raw = await websocket.receive_text()
            frame = WidgetMessageIn.model_validate_json(raw)
            payload = orjson.dumps(
                {
                    "session_token": token,
                    "customer_id": str(session_data.customer_id),
                    "body": frame.body,
                    "reply_to_external_message_id": frame.reply_to_external_message_id,
                }
            )
            messages = await provider.receive_message(payload)
            await publish_inbound_message_events(events, config=config, messages=messages)
            await session.commit()
    except WebSocketDisconnect:
        pass
    except DomainError:
        await websocket.close(code=4400)
    finally:
        forward_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await forward_task
