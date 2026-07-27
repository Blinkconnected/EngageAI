"""Internal Customer Rating CRUD — staff-only stars + optional note on a
customer, never exposed to the customer themselves. See
``docs/architecture/core-crm.md``.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.customer import CustomerInternalRating
from blinkengage.infrastructure.repositories.customer_internal_rating_repository import (
    CustomerInternalRatingRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository


class CustomerInternalRatingService:
    def __init__(
        self,
        *,
        ratings: CustomerInternalRatingRepository,
        customers: CustomerRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._ratings = ratings
        self._customers = customers
        self._events = events

    async def _require_customer(self, *, company_id: UUID, customer_id: UUID) -> None:
        customer = await self._customers.get_by_id(company_id=company_id, customer_id=customer_id)
        if customer is None:
            raise EntityNotFoundError("Customer", customer_id)

    async def list_ratings(
        self, *, company_id: UUID, customer_id: UUID, offset: int, limit: int
    ) -> tuple[list[CustomerInternalRating], int]:
        await self._require_customer(company_id=company_id, customer_id=customer_id)
        return await self._ratings.list_for_customer(
            company_id=company_id, customer_id=customer_id, offset=offset, limit=limit
        )

    async def summary(self, *, company_id: UUID, customer_id: UUID) -> tuple[float | None, int]:
        return await self._ratings.summary_for_customer(
            company_id=company_id, customer_id=customer_id
        )

    async def summary_map(
        self, *, company_id: UUID, customer_ids: list[UUID]
    ) -> dict[UUID, tuple[float | None, int]]:
        return await self._ratings.summary_for_customers(
            company_id=company_id, customer_ids=customer_ids
        )

    async def create(
        self,
        *,
        company_id: UUID,
        customer_id: UUID,
        stars: int,
        note: str | None,
        rated_by_user_id: UUID | None,
    ) -> CustomerInternalRating:
        await self._require_customer(company_id=company_id, customer_id=customer_id)
        rating = await self._ratings.add(
            CustomerInternalRating(
                company_id=company_id,
                customer_id=customer_id,
                rated_by_user_id=rated_by_user_id,
                stars=stars,
                note=note,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="customer_internal_rating.created",
                company_id=company_id,
                aggregate_type="customer_internal_rating",
                aggregate_id=rating.id,
                actor_user_id=rated_by_user_id,
                payload={"customer_id": str(customer_id), "stars": stars},
            )
        )
        return rating

    async def update(
        self,
        *,
        company_id: UUID,
        rating_id: UUID,
        stars: int,
        note: str | None,
        actor_user_id: UUID | None = None,
    ) -> CustomerInternalRating:
        rating = await self._ratings.get_by_id(company_id=company_id, rating_id=rating_id)
        if rating is None:
            raise EntityNotFoundError("CustomerInternalRating", rating_id)
        rating.stars = stars
        rating.note = note
        await self._events.publish(
            DomainEvent(
                event_type="customer_internal_rating.updated",
                company_id=company_id,
                aggregate_type="customer_internal_rating",
                aggregate_id=rating.id,
                actor_user_id=actor_user_id,
                payload={"customer_id": str(rating.customer_id), "stars": stars},
            )
        )
        return rating

    async def delete(
        self, *, company_id: UUID, rating_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        rating = await self._ratings.get_by_id(company_id=company_id, rating_id=rating_id)
        if rating is None:
            raise EntityNotFoundError("CustomerInternalRating", rating_id)
        customer_id = rating.customer_id
        await self._ratings.delete(rating)
        await self._events.publish(
            DomainEvent(
                event_type="customer_internal_rating.deleted",
                company_id=company_id,
                aggregate_type="customer_internal_rating",
                aggregate_id=rating_id,
                actor_user_id=actor_user_id,
                payload={"customer_id": str(customer_id)},
            )
        )
