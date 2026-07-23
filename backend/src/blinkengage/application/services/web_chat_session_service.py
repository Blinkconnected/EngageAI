"""Orchestrates Web Chat visitor session creation/resumption. See
``docs/architecture/web-chat.md``.
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from blinkengage.domain.exceptions import EntityNotFoundError, InvalidChannelTypeError
from blinkengage.infrastructure.cache.chat_session_store import ChatSessionData, ChatSessionStore
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository


@dataclass(frozen=True, slots=True)
class WebChatSession:
    session_token: str
    customer_id: UUID


class WebChatSessionService:
    def __init__(
        self,
        *,
        channel_configs: ChannelConfigRepository,
        customers: CustomerRepository,
        sessions: ChatSessionStore,
        session_ttl: timedelta,
    ) -> None:
        self._channel_configs = channel_configs
        self._customers = customers
        self._sessions = sessions
        self._session_ttl = session_ttl

    async def start_or_resume(
        self, *, channel_config_id: UUID, existing_session_token: str | None
    ) -> WebChatSession:
        if existing_session_token is not None:
            data = await self._sessions.get(existing_session_token)
            if data is not None and data.channel_config_id == channel_config_id:
                await self._sessions.touch(existing_session_token, ttl=self._session_ttl)
                return WebChatSession(
                    session_token=existing_session_token, customer_id=data.customer_id
                )

        config = await self._channel_configs.get_by_id_any_company(channel_config_id)
        if config is None or not config.is_active:
            raise EntityNotFoundError("ChannelConfig", channel_config_id)
        if config.channel_type != "web_chat":
            raise InvalidChannelTypeError(config.channel_type)

        customer = await self._customers.add(
            Customer(
                company_id=config.company_id,
                full_name="Web Visitor",
                email=None,
                phone=None,
                notes=None,
                custom_fields={"source": "web_chat"},
            )
        )
        token = await self._sessions.create(
            data=ChatSessionData(
                customer_id=customer.id,
                channel_config_id=channel_config_id,
                company_id=config.company_id,
            ),
            ttl=self._session_ttl,
        )
        return WebChatSession(session_token=token, customer_id=customer.id)
