"""``CsatService`` — Customer Satisfaction survey links and response
submission. See ``docs/architecture/reports-analytics.md``.

The survey link carries a signed, conversation-scoped ``TokenType.CSAT``
JWT (``core/security.py``) rather than a new bespoke token scheme —
reusing the same signing key/verification path every other token in this
codebase already goes through, just with its own expiry and a
conversation id (not a user id) as the subject. Submitting a response
needs no authenticated session: the token itself, not a company-scoped
JWT, is what proves "the person submitting this was sent this specific
conversation's survey."
"""

from uuid import UUID

from blinkengage.core.config import Settings
from blinkengage.core.security import InvalidTokenError, TokenType, create_token, decode_token
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    AuthenticationError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
)
from blinkengage.infrastructure.database.models.reporting import CsatResponse
from blinkengage.infrastructure.repositories.conversation_repository import ConversationRepository
from blinkengage.infrastructure.repositories.csat_repository import CsatResponseRepository

_MIN_RATING = 1
_MAX_RATING = 5


class CsatService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        responses: CsatResponseRepository,
        events: DomainEventPublisher,
        settings: Settings,
    ) -> None:
        self._conversations = conversations
        self._responses = responses
        self._events = events
        self._settings = settings

    def build_survey_url(self, *, conversation_id: UUID) -> str:
        token, _ = create_token(
            subject=conversation_id, settings=self._settings, token_type=TokenType.CSAT
        )
        base = self._settings.public_base_url.rstrip("/")
        return f"{base}/api/v1/csat/{conversation_id}/respond?token={token}"

    async def submit(
        self, *, conversation_id: UUID, token: str, rating: int, comment: str | None
    ) -> CsatResponse:
        if not (_MIN_RATING <= rating <= _MAX_RATING):
            raise ValueError(f"rating must be between {_MIN_RATING} and {_MAX_RATING}")
        try:
            payload = decode_token(token, settings=self._settings, expected_type=TokenType.CSAT)
        except InvalidTokenError as exc:
            raise AuthenticationError("CSAT survey link is invalid or expired") from exc
        if payload["sub"] != str(conversation_id):
            raise AuthenticationError("CSAT survey link is invalid or expired")

        if await self._responses.get_by_conversation(conversation_id) is not None:
            raise EntityAlreadyExistsError("CsatResponse", "conversation_id", conversation_id)

        conversation = await self._conversations.get_by_id_any_company(conversation_id)
        if conversation is None:
            raise EntityNotFoundError("Conversation", conversation_id)

        response = await self._responses.add(
            CsatResponse(
                company_id=conversation.company_id,
                conversation_id=conversation.id,
                customer_id=conversation.customer_id,
                agent_id=conversation.assigned_agent_id,
                rating=rating,
                comment=comment,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="csat.submitted",
                company_id=conversation.company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                payload={
                    "conversation_id": str(conversation.id),
                    "agent_id": (
                        str(conversation.assigned_agent_id)
                        if conversation.assigned_agent_id
                        else None
                    ),
                    "rating": rating,
                },
            )
        )
        return response
