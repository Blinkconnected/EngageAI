"""Redacting a message, and everything downstream of it.

See ``docs/architecture/message-redaction.md``. The rules live in
``domain.message_redaction``; this carries them out.

The hard part is not blanking a column. It is that a message's content
does not stay in the message: it is copied into provider metadata,
uploaded to object storage as attachments, and cited by Memory and
Learning. Redaction that removes only the row's ``body`` leaves the
content in four other places and reports success.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.learning_observation import ContentRefKind
from blinkengage.domain.memory import EvidenceSourceType
from blinkengage.domain.message_redaction import (
    RedactionOutcome,
    RedactionRuleViolation,
    RedactionScope,
    ensure_not_already_redacted,
    strip_metadata,
    validate_reason,
)
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.learning import (
    LearningObservation,
    LearningObservationRef,
)
from blinkengage.infrastructure.database.models.memory import MemoryEvidence
from blinkengage.infrastructure.database.models.message import Message, MessageAttachment
from blinkengage.infrastructure.database.models.message_redaction import MessageRedaction
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore

#: Both taken from the enums rather than written out. Spelling one of
#: these wrong is silent: the delete matches nothing, the count reads 0,
#: the audit row says "0 evidence removed", and the citation survives.
#: An early version of this file guessed `"MESSAGE"` and would have left
#: every memory citation intact while reporting success.
_MEMORY_MESSAGE_SOURCE = EvidenceSourceType.MESSAGE.value
_LEARNING_MESSAGE_REF = ContentRefKind.MESSAGE.value


class MessageRedactionService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        attachment_store: AttachmentStore,
        events: DomainEventPublisher,
    ) -> None:
        self._session = session
        self._attachments = attachment_store
        self._events = events

    async def redact(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        reason: str,
        actor_user_id: UUID | None,
    ) -> MessageRedaction:
        """Remove what a message said. Keep that it was said.

        One transaction. Either every copy of the content goes and the
        record is written, or nothing changes — a partial redaction that
        reported success would be the worst possible outcome, because
        nobody would look again.
        """
        cleaned = validate_reason(reason)
        message = await self._load(
            company_id=company_id, conversation_id=conversation_id, message_id=message_id
        )
        ensure_not_already_redacted(message.redacted_at)

        redacted_at = datetime.now(UTC)

        # 1. Attachments first. If object storage refuses, the whole
        #    transaction rolls back and the message keeps its content —
        #    far better than a message that reads "redacted" beside a
        #    downloadable file of what it said.
        attachments_purged = await self._purge_attachments(message)

        # 2. The content itself, overwritten in place. Not a soft flag:
        #    after this the bytes are gone from the row, and only a
        #    backup taken before now still holds them.
        message.body = None
        message.message_metadata = strip_metadata(message.message_metadata)
        message.redacted_at = redacted_at
        message.redacted_by_user_id = actor_user_id

        # 3. Everything that cited it. Memory and Learning store pointers
        #    rather than copies (by deliberate design — see
        #    MemoryEvidence's docstring), so nothing here is deleting
        #    customer content a second time. What it removes is the
        #    *citation*: a fact whose evidence is a redacted message is a
        #    fact nobody can check, and a redacted message must never be
        #    the reason the platform believes something.
        memory_removed = await self._detach_memory_evidence(
            company_id=company_id, message_id=message_id
        )
        learning_detached = await self._detach_learning_observations(
            company_id=company_id, message_id=message_id
        )

        outcome = RedactionOutcome(
            attachments_purged=attachments_purged,
            memory_evidence_removed=memory_removed,
            learning_observations_detached=learning_detached,
        )
        record = await self._write_record(
            company_id=company_id,
            conversation_id=conversation_id,
            message=message,
            reason=cleaned,
            actor_user_id=actor_user_id,
            redacted_at=redacted_at,
            outcome=outcome,
        )

        # Carries no content, by construction. An event describing a
        # redaction that quoted what was redacted would republish it to
        # every consumer and into the outbox table.
        await self._events.publish(
            DomainEvent(
                event_type="message.redacted",
                company_id=company_id,
                aggregate_type="message",
                aggregate_id=message_id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation_id),
                    "reason": cleaned,
                    "attachments_purged": attachments_purged,
                },
            )
        )
        return record

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[MessageRedaction], int]:
        from sqlalchemy import func

        total = await self._session.scalar(
            select(func.count())
            .select_from(MessageRedaction)
            .where(MessageRedaction.company_id == company_id)
        )
        result = await self._session.execute(
            select(MessageRedaction)
            .where(MessageRedaction.company_id == company_id)
            .order_by(MessageRedaction.redacted_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def _load(self, *, company_id: UUID, conversation_id: UUID, message_id: UUID) -> Message:
        """The message, scoped to its company *and* its conversation.

        Both, not either. Scoping by company alone would let a caller
        redact any message in their tenant through any conversation id
        they can see, which turns a per-conversation permission check
        into a company-wide one.
        """
        # An explicit join: Message carries `conversation_id` and no ORM
        # relationship, so tenancy is only reachable through Conversation.
        result = await self._session.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
            )
        )
        message = result.scalar_one_or_none()
        if message is None:
            # 404 rather than 403 — a cross-tenant id must not be
            # confirmed to exist.
            raise RedactionRuleViolation(
                code="not_found", message="That message does not exist in this conversation."
            )
        return message

    async def _purge_attachments(self, message: Message) -> int:
        """Delete the objects, then the rows.

        That order on purpose. Deleting rows first and failing on storage
        would leave orphaned objects nobody knows about — still
        downloadable by anyone holding a key, with nothing left in the
        database pointing at them to find later.
        """
        result = await self._session.execute(
            select(MessageAttachment).where(MessageAttachment.message_id == message.id)
        )
        attachments = list(result.scalars().all())
        for attachment in attachments:
            await self._attachments.delete(key=attachment.storage_key)
        if attachments:
            await self._session.execute(
                delete(MessageAttachment).where(MessageAttachment.message_id == message.id)
            )
        return len(attachments)

    async def _detach_memory_evidence(self, *, company_id: UUID, message_id: UUID) -> int:
        result = await self._session.execute(
            delete(MemoryEvidence).where(
                MemoryEvidence.company_id == company_id,
                MemoryEvidence.source_type == _MEMORY_MESSAGE_SOURCE,
                MemoryEvidence.source_id == message_id,
            )
        )
        return int(result.rowcount or 0)

    async def _detach_learning_observations(self, *, company_id: UUID, message_id: UUID) -> int:
        """Cut the message out of every observation that cited it.

        Learning does not observe messages — it observes *conversations*
        (`SourceKind.CONVERSATION`) and cites the individual messages it
        drew on through `LearningObservationRef`. So the thing to remove
        is the citation, not the observation: discarding the whole
        observation would throw away what the platform learned from the
        rest of a conversation because one message in it was redacted.

        The refs are deleted rather than flagged. `ref_kind`/`ref_id` is
        polymorphic with no foreign key — the model's own docstring says
        "integrity is the erasure path's job", and this is that path.
        """
        refs = await self._session.execute(
            select(LearningObservationRef.observation_id).where(
                LearningObservationRef.company_id == company_id,
                LearningObservationRef.ref_kind == _LEARNING_MESSAGE_REF,
                LearningObservationRef.ref_id == message_id,
            )
        )
        observation_ids = [row[0] for row in refs.all()]
        if not observation_ids:
            return 0

        await self._session.execute(
            delete(LearningObservationRef).where(
                LearningObservationRef.company_id == company_id,
                LearningObservationRef.ref_kind == _LEARNING_MESSAGE_REF,
                LearningObservationRef.ref_id == message_id,
            )
        )
        # An observation left with no content at all is no longer
        # evidence of anything, so it goes to a terminal state rather
        # than staying eligible for the next clustering run.
        emptied = await self._session.execute(
            update(LearningObservation)
            .where(
                LearningObservation.company_id == company_id,
                LearningObservation.id.in_(observation_ids),
                ~LearningObservation.content_refs.any(),
            )
            .values(state="discarded")
        )
        _ = emptied
        return len(observation_ids)

    async def _write_record(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        message: Message,
        reason: str,
        actor_user_id: UUID | None,
        redacted_at: datetime,
        outcome: RedactionOutcome,
    ) -> MessageRedaction:
        customer_name: str | None = None
        conversation = await self._session.get(Conversation, conversation_id)
        if conversation is not None:
            customer = await self._session.get(Customer, conversation.customer_id)
            customer_name = customer.full_name if customer is not None else None

        actor_name: str | None = None
        if actor_user_id is not None:
            actor = await self._session.get(User, actor_user_id)
            actor_name = actor.full_name if actor is not None else None

        record = MessageRedaction(
            company_id=company_id,
            message_id=message.id,
            conversation_id=conversation_id,
            customer_name=customer_name,
            redacted_by_user_id=actor_user_id,
            # Copied, not joined: the audit trail must still name the
            # person after they leave and their row is gone.
            redacted_by_name=actor_name,
            reason=reason,
            scope=RedactionScope.MESSAGE_AND_ATTACHMENTS,
            attachments_purged=outcome.attachments_purged,
            memory_evidence_removed=outcome.memory_evidence_removed,
            learning_observations_detached=outcome.learning_observations_detached,
            redacted_at=redacted_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record


__all__ = ["MessageRedactionService"]
