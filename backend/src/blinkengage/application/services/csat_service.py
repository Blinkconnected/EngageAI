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

from dataclasses import dataclass
from uuid import UUID

from blinkengage.core.config import Settings
from blinkengage.core.security import InvalidTokenError, TokenType, create_token, decode_token
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    AuthenticationError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
)
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.reporting import CsatResponse
from blinkengage.infrastructure.repositories.conversation_repository import ConversationRepository
from blinkengage.infrastructure.repositories.csat_repository import CsatResponseRepository
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository

_MIN_RATING = 1
_MAX_RATING = 5


@dataclass(frozen=True)
class CsatContext:
    """What the public feedback page (``/feedback/{conversation_id}``)
    needs to decide what to show: the rating form directly, a thank-you
    screen (already answered), or the contact-info backfill step first."""

    conversation_id: UUID
    already_responded: bool
    needs_contact_info: bool


class CsatService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        responses: CsatResponseRepository,
        customers: CustomerRepository,
        events: DomainEventPublisher,
        settings: Settings,
    ) -> None:
        self._conversations = conversations
        self._responses = responses
        self._customers = customers
        self._events = events
        self._settings = settings

    def build_survey_url(self, *, conversation_id: UUID) -> str:
        token, _ = create_token(
            subject=conversation_id, settings=self._settings, token_type=TokenType.CSAT
        )
        base = self._settings.public_base_url.rstrip("/")
        # Points at the frontend SPA's public feedback page, not the raw
        # API endpoint — a customer clicking this needs a page to look at
        # (the rating form, or the contact-info step first), not a bare
        # JSON response. Both origins are the same host in every
        # deployment (nginx routes /api/* to the backend and everything
        # else to the frontend — see docker/nginx/*.conf), so
        # public_base_url is correct for both.
        return f"{base}/feedback/{conversation_id}?token={token}"

    def _verify_token(self, *, conversation_id: UUID, token: str) -> None:
        try:
            payload = decode_token(token, settings=self._settings, expected_type=TokenType.CSAT)
        except InvalidTokenError as exc:
            raise AuthenticationError("CSAT survey link is invalid or expired") from exc
        if payload["sub"] != str(conversation_id):
            raise AuthenticationError("CSAT survey link is invalid or expired")

    async def get_context(self, *, conversation_id: UUID, token: str) -> CsatContext:
        self._verify_token(conversation_id=conversation_id, token=token)
        conversation = await self._conversations.get_by_id_any_company(conversation_id)
        if conversation is None:
            raise EntityNotFoundError("Conversation", conversation_id)

        already_responded = await self._responses.get_by_conversation(conversation_id) is not None
        customer = await self._customers.get_by_id_any_company(customer_id=conversation.customer_id)
        needs_contact_info = customer is None or (not customer.email and not customer.phone)
        return CsatContext(
            conversation_id=conversation_id,
            already_responded=already_responded,
            needs_contact_info=needs_contact_info,
        )

    async def submit_contact_info(
        self, *, conversation_id: UUID, token: str, email: str | None, phone: str | None
    ) -> Customer:
        self._verify_token(conversation_id=conversation_id, token=token)
        conversation = await self._conversations.get_by_id_any_company(conversation_id)
        if conversation is None:
            raise EntityNotFoundError("Conversation", conversation_id)

        customer = await self._customers.get_by_id_any_company(customer_id=conversation.customer_id)
        if customer is None:
            raise EntityNotFoundError("Customer", conversation.customer_id)

        # Backfill only — never overwrites a value the customer (or an
        # agent) already supplied, since this step only ever runs when
        # get_context() found both missing in the first place.
        if email and not customer.email:
            normalized_email = email.strip().lower()
            existing = await self._customers.get_by_email(
                company_id=customer.company_id, email=normalized_email
            )
            if existing is not None and existing.id != customer.id:
                raise EntityAlreadyExistsError("Customer", "email", normalized_email)
            customer.email = normalized_email
        if phone and not customer.phone:
            customer.phone = phone.strip()
        return customer

    async def submit(
        self, *, conversation_id: UUID, token: str, rating: int, comment: str | None
    ) -> CsatResponse:
        if not (_MIN_RATING <= rating <= _MAX_RATING):
            raise ValueError(f"rating must be between {_MIN_RATING} and {_MAX_RATING}")
        self._verify_token(conversation_id=conversation_id, token=token)

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
