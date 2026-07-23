"""The agent-facing real-time WebSocket gateway. See
``docs/architecture/notifications.md``.

Distinct from the Web Chat WebSocket (M12, customer-facing, keyed by an
anonymous session token): this one authenticates with the same JWT access
token every REST call uses (as a ``?token=`` query param — browsers can't
set arbitrary headers on a WebSocket handshake), and is keyed by the
authenticated user.

Three things happen over one connection:

1. **Presence** — connecting flips ``Agent.status`` from ``OFFLINE`` to
   ``ONLINE`` (never overriding an explicit ``AWAY``); disconnecting
   always sets ``OFFLINE``, since a disconnected agent genuinely can't
   receive live work.
2. **Notifications** — the connection subscribes to the user's personal
   realtime channel and forwards whatever ``NotificationService.create``
   publishes there, live.
3. **Typing** — the only inbound frame type. Forwarded to
   ``ConversationService.send_typing_indicator``, finally invoking
   ``ChannelProvider.typing_indicator`` for real.
"""

import asyncio
import contextlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import (
    get_agent_service_ws,
    get_conversation_service_ws,
    get_db_session_ws,
    get_realtime_publisher_ws,
    get_settings_dep_ws,
)
from blinkengage.api.schemas.realtime import TypingFrameIn
from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import notification_channel_name
from blinkengage.core.config import Settings
from blinkengage.core.logging import get_logger
from blinkengage.core.security import InvalidTokenError, TokenType, decode_token
from blinkengage.domain.exceptions import DomainError
from blinkengage.infrastructure.database.models.agent import AgentStatus
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository

logger = get_logger(__name__)

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/agent")
async def agent_gateway(
    websocket: WebSocket,
    settings: Annotated[Settings, Depends(get_settings_dep_ws)],
    session: Annotated[AsyncSession, Depends(get_db_session_ws)],
    realtime: Annotated[RealtimePublisher, Depends(get_realtime_publisher_ws)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service_ws)],
    agent_service: Annotated[AgentService, Depends(get_agent_service_ws)],
) -> None:
    token = websocket.query_params.get("token")
    if token is None:
        await websocket.close(code=4401)
        return
    try:
        claims = decode_token(token, settings=settings, expected_type=TokenType.ACCESS)
    except InvalidTokenError:
        await websocket.close(code=4401)
        return

    user_id = UUID(claims["sub"])
    company_id = UUID(claims["company_id"])

    await websocket.accept()

    agent = await AgentRepository(session).get_by_user_id(company_id=company_id, user_id=user_id)
    if agent is not None and agent.status == AgentStatus.OFFLINE:
        await agent_service.update(
            company_id=company_id,
            agent_id=agent.id,
            title=None,
            department_id=None,
            status=AgentStatus.ONLINE,
        )
        await session.commit()

    async def _forward() -> None:
        async with realtime.subscribe(notification_channel_name(user_id)) as pubsub:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    await websocket.send_text(data if isinstance(data, str) else data.decode())

    forward_task = asyncio.create_task(_forward())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = TypingFrameIn.model_validate_json(raw)
            except ValidationError:
                continue  # an unrecognized/malformed frame — ignore, don't drop the connection
            await conversation_service.send_typing_indicator(
                company_id=company_id,
                conversation_id=frame.conversation_id,
                is_typing=frame.is_typing,
            )
            await session.commit()
    except WebSocketDisconnect:
        pass
    except DomainError:
        await websocket.close(code=4400)
    finally:
        forward_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await forward_task
        if agent is not None:
            await agent_service.update(
                company_id=company_id,
                agent_id=agent.id,
                title=None,
                department_id=None,
                status=AgentStatus.OFFLINE,
            )
            await session.commit()
