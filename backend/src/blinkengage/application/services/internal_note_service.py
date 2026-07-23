"""Internal Note CRUD, scoped under a conversation. See
``docs/architecture/knowledge-quick-replies-notes.md``.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.internal_note import InternalNote
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.internal_note_repository import (
    InternalNoteRepository,
)


class InternalNoteService:
    def __init__(
        self,
        *,
        notes: InternalNoteRepository,
        conversations: ConversationRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._notes = notes
        self._conversations = conversations
        self._events = events

    async def _require_conversation(self, *, company_id: UUID, conversation_id: UUID) -> None:
        conversation = await self._conversations.get_by_id(
            company_id=company_id, conversation_id=conversation_id
        )
        if conversation is None:
            raise EntityNotFoundError("Conversation", conversation_id)

    async def list_notes(
        self, *, company_id: UUID, conversation_id: UUID, offset: int, limit: int
    ) -> tuple[list[InternalNote], int]:
        await self._require_conversation(company_id=company_id, conversation_id=conversation_id)
        return await self._notes.list_for_conversation(
            company_id=company_id, conversation_id=conversation_id, offset=offset, limit=limit
        )

    async def create(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        body: str,
        author_user_id: UUID | None,
    ) -> InternalNote:
        await self._require_conversation(company_id=company_id, conversation_id=conversation_id)
        note = await self._notes.add(
            InternalNote(
                company_id=company_id,
                conversation_id=conversation_id,
                author_user_id=author_user_id,
                body=body,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="internal_note.created",
                company_id=company_id,
                aggregate_type="internal_note",
                aggregate_id=note.id,
                actor_user_id=author_user_id,
                payload={"conversation_id": str(conversation_id), "note_id": str(note.id)},
            )
        )
        return note

    async def update(
        self,
        *,
        company_id: UUID,
        note_id: UUID,
        body: str,
        actor_user_id: UUID | None = None,
    ) -> InternalNote:
        note = await self._notes.get_by_id(company_id=company_id, note_id=note_id)
        if note is None:
            raise EntityNotFoundError("InternalNote", note_id)
        note.body = body
        await self._events.publish(
            DomainEvent(
                event_type="internal_note.updated",
                company_id=company_id,
                aggregate_type="internal_note",
                aggregate_id=note.id,
                actor_user_id=actor_user_id,
                payload={"conversation_id": str(note.conversation_id), "note_id": str(note.id)},
            )
        )
        return note

    async def delete(
        self, *, company_id: UUID, note_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        note = await self._notes.get_by_id(company_id=company_id, note_id=note_id)
        if note is None:
            raise EntityNotFoundError("InternalNote", note_id)
        conversation_id = note.conversation_id
        await self._notes.delete(note)
        await self._events.publish(
            DomainEvent(
                event_type="internal_note.deleted",
                company_id=company_id,
                aggregate_type="internal_note",
                aggregate_id=note_id,
                actor_user_id=actor_user_id,
                payload={"conversation_id": str(conversation_id)},
            )
        )
