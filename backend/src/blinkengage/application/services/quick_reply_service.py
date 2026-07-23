"""Quick Reply CRUD. See
``docs/architecture/knowledge-quick-replies-notes.md``.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityAlreadyExistsError, EntityNotFoundError
from blinkengage.infrastructure.database.models.quick_reply import QuickReply
from blinkengage.infrastructure.repositories.quick_reply_repository import QuickReplyRepository


class QuickReplyService:
    def __init__(
        self, *, quick_replies: QuickReplyRepository, events: DomainEventPublisher
    ) -> None:
        self._quick_replies = quick_replies
        self._events = events

    async def list_quick_replies(
        self, *, company_id: UUID, offset: int, limit: int, search: str | None
    ) -> tuple[list[QuickReply], int]:
        return await self._quick_replies.list_for_company(
            company_id=company_id, offset=offset, limit=limit, search=search
        )

    async def get(self, *, company_id: UUID, reply_id: UUID) -> QuickReply:
        quick_reply = await self._quick_replies.get_by_id(company_id=company_id, reply_id=reply_id)
        if quick_reply is None:
            raise EntityNotFoundError("QuickReply", reply_id)
        return quick_reply

    async def create(
        self,
        *,
        company_id: UUID,
        shortcut: str,
        title: str,
        body: str,
        actor_user_id: UUID | None = None,
    ) -> QuickReply:
        if await self._quick_replies.get_by_shortcut(company_id=company_id, shortcut=shortcut):
            raise EntityAlreadyExistsError("QuickReply", "shortcut", shortcut)
        quick_reply = await self._quick_replies.add(
            QuickReply(company_id=company_id, shortcut=shortcut, title=title, body=body)
        )
        await self._events.publish(
            DomainEvent(
                event_type="quick_reply.created",
                company_id=company_id,
                aggregate_type="quick_reply",
                aggregate_id=quick_reply.id,
                actor_user_id=actor_user_id,
                payload={"shortcut": shortcut, "title": title},
            )
        )
        return quick_reply

    async def update(
        self,
        *,
        company_id: UUID,
        reply_id: UUID,
        shortcut: str | None,
        title: str | None,
        body: str | None,
        is_active: bool | None,
        actor_user_id: UUID | None = None,
    ) -> QuickReply:
        quick_reply = await self.get(company_id=company_id, reply_id=reply_id)
        if shortcut is not None and shortcut != quick_reply.shortcut:
            if await self._quick_replies.get_by_shortcut(company_id=company_id, shortcut=shortcut):
                raise EntityAlreadyExistsError("QuickReply", "shortcut", shortcut)
            quick_reply.shortcut = shortcut
        if title is not None:
            quick_reply.title = title
        if body is not None:
            quick_reply.body = body
        if is_active is not None:
            quick_reply.is_active = is_active

        await self._events.publish(
            DomainEvent(
                event_type="quick_reply.updated",
                company_id=company_id,
                aggregate_type="quick_reply",
                aggregate_id=quick_reply.id,
                actor_user_id=actor_user_id,
                payload={"shortcut": quick_reply.shortcut, "is_active": quick_reply.is_active},
            )
        )
        return quick_reply

    async def delete(
        self, *, company_id: UUID, reply_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        quick_reply = await self.get(company_id=company_id, reply_id=reply_id)
        await self._quick_replies.soft_delete(quick_reply)
        await self._events.publish(
            DomainEvent(
                event_type="quick_reply.deleted",
                company_id=company_id,
                aggregate_type="quick_reply",
                aggregate_id=reply_id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )
