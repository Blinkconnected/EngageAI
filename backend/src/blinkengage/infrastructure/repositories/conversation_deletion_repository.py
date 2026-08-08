"""Reads and writes for conversation deletion requests."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.conversation_deletion import DeletionRequestStatus
from blinkengage.infrastructure.database.models.conversation_deletion_request import (
    ConversationDeletionRequest,
)


class ConversationDeletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: ConversationDeletionRequest) -> ConversationDeletionRequest:
        """Adds and flushes, so the caller has a real id.

        The primary key default is applied by SQLAlchemy at INSERT, not at
        construction, so ``request.id`` is ``None`` until something
        flushes. Everything after this needs it — the notification
        payload, the response body — and today they only get it because
        an unrelated SELECT happens to trigger an autoflush first.
        Depending on that ordering means a later refactor that removes
        the SELECT turns the id into ``None`` and the endpoint into a 500.
        """
        self._session.add(request)
        await self._session.flush()
        return request

    async def get(
        self, *, company_id: UUID, request_id: UUID
    ) -> ConversationDeletionRequest | None:
        result = await self._session.execute(
            select(ConversationDeletionRequest).where(
                ConversationDeletionRequest.id == request_id,
                ConversationDeletionRequest.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_for_conversation(
        self, *, company_id: UUID, conversation_id: UUID
    ) -> ConversationDeletionRequest | None:
        """The open request against this conversation, if there is one.

        Read before creating so a second agent gets a clear "somebody has
        already asked" rather than a unique-constraint violation, and read
        on the conversation itself so the interface can show the pending
        state instead of offering the button again.
        """
        result = await self._session.execute(
            select(ConversationDeletionRequest).where(
                ConversationDeletionRequest.company_id == company_id,
                ConversationDeletionRequest.conversation_id == conversation_id,
                ConversationDeletionRequest.status == DeletionRequestStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        status: DeletionRequestStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ConversationDeletionRequest], int]:
        conditions = [ConversationDeletionRequest.company_id == company_id]
        if status is not None:
            conditions.append(ConversationDeletionRequest.status == status)

        total = await self._session.scalar(
            select(func.count()).select_from(ConversationDeletionRequest).where(*conditions)
        )
        result = await self._session.execute(
            select(ConversationDeletionRequest)
            .where(*conditions)
            # Oldest first, unlike most lists here. This is a queue of work
            # somebody owes an answer to, and the request that has been
            # waiting longest is the one to answer next.
            .order_by(ConversationDeletionRequest.created_at)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def count_pending(self, *, company_id: UUID) -> int:
        """Drives the badge on the approvals screen — an administrator has
        to know work is waiting without going to look for it."""
        total = await self._session.scalar(
            select(func.count())
            .select_from(ConversationDeletionRequest)
            .where(
                ConversationDeletionRequest.company_id == company_id,
                ConversationDeletionRequest.status == DeletionRequestStatus.PENDING,
            )
        )
        return int(total or 0)
