"""Requesting a conversation's deletion, and deciding on it.

See ``docs/architecture/conversation-deletion.md``. The rules themselves
live in ``domain.conversation_deletion``; this coordinates them with the
database, the audit trail and the people who have to be told.
"""

from datetime import UTC, datetime
from uuid import UUID

from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.domain.conversation_deletion import (
    DeletionRequestStatus,
    DeletionRuleViolation,
    ensure_decidable,
    ensure_not_self_approval,
    validate_reason,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.infrastructure.database.models.conversation_deletion_request import (
    ConversationDeletionRequest,
)
from blinkengage.infrastructure.repositories.conversation_deletion_repository import (
    ConversationDeletionRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository

#: The permission that makes somebody an approver. Requests are addressed
#: to whoever holds it rather than to a role by name, because roles are
#: renameable and a company that invents a "Supervisor" must not silently
#: stop anybody being told.
APPROVER_PERMISSION = "conversations.delete_approve"

NOTIFICATION_REQUESTED = "conversation.deletion_requested"
NOTIFICATION_DECIDED = "conversation.deletion_decided"


class ConversationDeletionService:
    def __init__(
        self,
        *,
        requests: ConversationDeletionRepository,
        conversations: ConversationService,
        customers: CustomerRepository,
        roles: RoleRepository,
        notifications: NotificationService,
        events: DomainEventPublisher,
    ) -> None:
        self._requests = requests
        self._conversations = conversations
        self._customers = customers
        self._roles = roles
        self._notifications = notifications
        self._events = events

    async def request(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        reason: str,
        actor_user_id: UUID | None,
    ) -> ConversationDeletionRequest:
        """Ask for a conversation to be deleted.

        Deliberately does not check whether the caller *could* delete it
        themselves. Somebody who holds the approver permission and asks
        anyway is choosing to have a second person agree, which is a
        choice worth allowing rather than second-guessing.
        """
        cleaned = validate_reason(reason)
        # 404s for a conversation in another company, so this cannot be
        # used to find out whether an id exists elsewhere.
        conversation = await self._conversations.get(
            company_id=company_id, conversation_id=conversation_id
        )

        existing = await self._requests.get_pending_for_conversation(
            company_id=company_id, conversation_id=conversation_id
        )
        if existing is not None:
            raise DeletionRuleViolation(
                code="already_requested",
                message="Somebody has already asked for this conversation to be deleted.",
            )

        customer = await self._customers.get_by_id(
            company_id=company_id, customer_id=conversation.customer_id
        )
        request = await self._requests.add(
            ConversationDeletionRequest(
                company_id=company_id,
                conversation_id=conversation_id,
                # Copied, not joined: the queue and the audit trail have to
                # still name the customer once the conversation is gone.
                customer_name=customer.full_name if customer is not None else None,
                status=DeletionRequestStatus.PENDING,
                requested_by_user_id=actor_user_id,
                reason=cleaned,
            )
        )

        await self._notify_approvers(company_id=company_id, request=request)
        await self._events.publish(
            DomainEvent(
                event_type="conversation.deletion_requested",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation_id,
                actor_user_id=actor_user_id,
                payload={"reason": cleaned},
            )
        )
        return request

    async def approve(
        self,
        *,
        company_id: UUID,
        request_id: UUID,
        note: str | None,
        actor_user_id: UUID | None,
    ) -> ConversationDeletionRequest:
        """Agree, and delete the conversation.

        The deletion happens here rather than being left to the caller to
        do afterwards: an approval that records a decision and then
        depends on a second request to carry it out is an approval that
        can silently not happen.
        """
        request = await self._load_decidable(
            company_id=company_id, request_id=request_id, actor_user_id=actor_user_id
        )

        if request.conversation_id is not None:
            await self._conversations.delete(
                company_id=company_id,
                conversation_id=request.conversation_id,
                actor_user_id=actor_user_id,
            )

        self._record_decision(
            request,
            status=DeletionRequestStatus.APPROVED,
            actor_user_id=actor_user_id,
            note=note,
        )
        await self._notify_requester(request)
        await self._events.publish(
            DomainEvent(
                event_type="conversation.deletion_approved",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=request.conversation_id,
                actor_user_id=actor_user_id,
                payload={"reason": request.reason, "note": note},
            )
        )
        return request

    async def reject(
        self,
        *,
        company_id: UUID,
        request_id: UUID,
        note: str,
        actor_user_id: UUID | None,
    ) -> ConversationDeletionRequest:
        """Decline, and say why.

        The note is required here and optional on approval. An approval
        stands on the request's own reason; a rejection contradicts it,
        and the requester needs to learn something rather than watching
        their request disappear.
        """
        cleaned = validate_reason(note)
        request = await self._load_decidable(
            company_id=company_id, request_id=request_id, actor_user_id=actor_user_id
        )
        self._record_decision(
            request,
            status=DeletionRequestStatus.REJECTED,
            actor_user_id=actor_user_id,
            note=cleaned,
        )
        await self._notify_requester(request)
        await self._events.publish(
            DomainEvent(
                event_type="conversation.deletion_rejected",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=request.conversation_id,
                actor_user_id=actor_user_id,
                payload={"reason": request.reason, "note": cleaned},
            )
        )
        return request

    async def list(
        self,
        *,
        company_id: UUID,
        status: DeletionRequestStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ConversationDeletionRequest], int]:
        return await self._requests.list_for_company(
            company_id=company_id, status=status, offset=offset, limit=limit
        )

    async def pending_for_conversation(
        self, *, company_id: UUID, conversation_id: UUID
    ) -> ConversationDeletionRequest | None:
        return await self._requests.get_pending_for_conversation(
            company_id=company_id, conversation_id=conversation_id
        )

    async def count_pending(self, *, company_id: UUID) -> int:
        return await self._requests.count_pending(company_id=company_id)

    async def _load_decidable(
        self, *, company_id: UUID, request_id: UUID, actor_user_id: UUID | None
    ) -> ConversationDeletionRequest:
        request = await self._requests.get(company_id=company_id, request_id=request_id)
        if request is None:
            raise DeletionRuleViolation(
                code="not_found", message="That deletion request does not exist."
            )
        ensure_decidable(request.status)
        ensure_not_self_approval(
            requested_by_user_id=request.requested_by_user_id, actor_user_id=actor_user_id
        )
        return request

    @staticmethod
    def _record_decision(
        request: ConversationDeletionRequest,
        *,
        status: DeletionRequestStatus,
        actor_user_id: UUID | None,
        note: str | None,
    ) -> None:
        request.status = status
        request.decided_by_user_id = actor_user_id
        request.decided_at = datetime.now(UTC)
        request.decision_note = note

    async def _notify_approvers(
        self, *, company_id: UUID, request: ConversationDeletionRequest
    ) -> None:
        """Tell everybody who can decide, except the person who asked.

        A request nobody is told about is a request that waits until
        somebody happens to open the right screen — which, for the one
        destructive action in the product, is the wrong way round.
        """
        approvers = await self._roles.list_users_with_permission(
            company_id=company_id, code=APPROVER_PERMISSION
        )
        subject = request.customer_name or "a conversation"
        for approver in approvers:
            if approver.id == request.requested_by_user_id:
                continue
            await self._notifications.create(
                company_id=company_id,
                user_id=approver.id,
                notification_type=NOTIFICATION_REQUESTED,
                title="A conversation is waiting to be deleted",
                body=f"Somebody asked to delete the conversation with {subject}.",
                payload={"request_id": str(request.id), "reason": request.reason},
            )

    async def _notify_requester(self, request: ConversationDeletionRequest) -> None:
        if request.requested_by_user_id is None:
            return
        subject = request.customer_name or "a conversation"
        decided = request.status.value
        await self._notifications.create(
            company_id=request.company_id,
            user_id=request.requested_by_user_id,
            notification_type=NOTIFICATION_DECIDED,
            title=f"Your deletion request was {decided}",
            body=f"The request to delete the conversation with {subject} was {decided}.",
            payload={"request_id": str(request.id), "note": request.decision_note},
        )


__all__ = [
    "APPROVER_PERMISSION",
    "NOTIFICATION_DECIDED",
    "NOTIFICATION_REQUESTED",
    "ConversationDeletionService",
]
