"""FAQ CRUD, publication and ordering.

See ``docs/architecture/faq.md``.

The service owns two things the repository deliberately does not: the
contract (``domain/faq.validate_content`` runs before anything reaches the
session, so "every FAQ has a question and an answer" is a property of the
store) and the decision to queue re-indexing — which happens on the write
path, in the same transaction, exactly as ``KnowledgeService`` does it and
for the same reason: a consumer reacting to the event would make "the FAQ
changed" and "the index knows it changed" two facts a broker hiccup can
separate.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.faq import (
    DEFAULT_IS_PUBLISHED,
    FaqContent,
    embeddable_text,
    next_display_order,
    normalise_locale,
    reordered,
    validate_content,
)
from blinkengage.infrastructure.database.models.embedding import KnowledgeIndexState
from blinkengage.infrastructure.database.models.faq import Faq, FaqTag
from blinkengage.infrastructure.repositories.faq_repository import FaqRepository


def _content(faq: Faq) -> FaqContent:
    return FaqContent(question=faq.question, answer=faq.answer)


def _mark_for_reindex(faq: Faq) -> None:
    """Queues an FAQ for the semantic-index sweep.

    Attempts and the previous error are cleared because this is new work
    about new content: carrying a failure count forward would let an FAQ
    that once failed exhaust its retries against text since corrected.
    """
    faq.index_state = KnowledgeIndexState.PENDING
    faq.index_attempts = 0
    faq.index_error = None


class FaqService:
    def __init__(self, *, faqs: FaqRepository, events: DomainEventPublisher) -> None:
        self._faqs = faqs
        self._events = events

    async def get(self, *, company_id: UUID, faq_id: UUID) -> Faq:
        faq = await self._faqs.get_by_id(company_id=company_id, faq_id=faq_id)
        if faq is None:
            raise EntityNotFoundError("Faq", faq_id)
        return faq

    async def list_faqs(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        search: str | None = None,
        category_id: UUID | None = None,
        locale: str | None = None,
        published_only: bool = False,
    ) -> tuple[list[Faq], int]:
        return await self._faqs.list_for_company(
            company_id=company_id,
            offset=offset,
            limit=limit,
            search=search,
            category_id=category_id,
            locale=normalise_locale(locale),
            published_only=published_only,
        )

    async def create(
        self,
        *,
        company_id: UUID,
        question: str,
        answer: str,
        category_id: UUID | None = None,
        locale: str | None = None,
        is_published: bool | None = None,
        tags: list[str] | None = None,
        actor_user_id: UUID | None = None,
    ) -> Faq:
        content = FaqContent(question=question, answer=answer)
        validate_content(content)

        existing_orders = await self._faqs.display_orders(company_id=company_id)
        # Tags resolved *before* construction and passed in, rather than
        # attached after the flush. A never-loaded collection on an
        # already-persistent row cannot be lazy-loaded inside an async
        # session (`MissingGreenlet`); a transient object's collection is
        # "loaded" from the start. Exactly the lesson
        # `KnowledgeService.create_article` records — and the endpoint
        # reads `faq_tags` to build its response, so getting this wrong
        # fails on every create rather than only on tagged ones.
        resolved = await self._faqs.resolve_tags(company_id=company_id, tag_names=tags or [])
        faq = await self._faqs.add(
            Faq(
                company_id=company_id,
                category_id=category_id,
                question=question.strip(),
                answer=answer.strip(),
                locale=normalise_locale(locale),
                is_published=DEFAULT_IS_PUBLISHED if is_published is None else is_published,
                display_order=next_display_order(existing_orders),
                faq_tags=[FaqTag(tag=tag) for tag in resolved],
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="faq.created",
                company_id=company_id,
                aggregate_type="faq",
                aggregate_id=faq.id,
                actor_user_id=actor_user_id,
                # The question travels; the answer does not. An FAQ is
                # company-authored rather than customer content, so this
                # carries no privacy weight — but the audit log keeps
                # every event forever and an answer can be pages long, so
                # copying it into a second store buys nothing.
                payload={"question": faq.question, "is_published": faq.is_published},
            )
        )
        return faq

    async def update(
        self,
        *,
        company_id: UUID,
        faq_id: UUID,
        question: str | None = None,
        answer: str | None = None,
        category_id: UUID | None = None,
        locale: str | None = None,
        is_published: bool | None = None,
        tags: list[str] | None = None,
        actor_user_id: UUID | None = None,
    ) -> Faq:
        faq = await self.get(company_id=company_id, faq_id=faq_id)
        before = embeddable_text(_content(faq))
        was_published = faq.is_published

        if question is not None or answer is not None:
            candidate = FaqContent(
                question=question if question is not None else faq.question,
                answer=answer if answer is not None else faq.answer,
            )
            validate_content(candidate)
            faq.question = candidate.question.strip()
            faq.answer = candidate.answer.strip()

        if category_id is not None:
            faq.category_id = category_id
        if locale is not None:
            faq.locale = normalise_locale(locale)
        if is_published is not None:
            faq.is_published = is_published
        if tags is not None:
            resolved = await self._faqs.resolve_tags(company_id=company_id, tag_names=tags)
            await self._faqs.set_tags(faq=faq, tags=resolved)

        # Re-index only when the embeddable text or the *visibility*
        # changed. Retagging or recategorising costs no embedding call —
        # a vector encodes neither — but unpublishing must reach the index
        # immediately, because a retrievable unpublished FAQ is one the AI
        # will quote at a customer after somebody took it down.
        if embeddable_text(_content(faq)) != before or faq.is_published != was_published:
            _mark_for_reindex(faq)

        await self._events.publish(
            DomainEvent(
                event_type="faq.updated",
                company_id=company_id,
                aggregate_type="faq",
                aggregate_id=faq.id,
                actor_user_id=actor_user_id,
                payload={"question": faq.question, "is_published": faq.is_published},
            )
        )
        return faq

    async def delete(
        self, *, company_id: UUID, faq_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        faq = await self.get(company_id=company_id, faq_id=faq_id)
        await self._faqs.soft_delete(faq)
        await self._events.publish(
            DomainEvent(
                event_type="faq.deleted",
                company_id=company_id,
                aggregate_type="faq",
                aggregate_id=faq.id,
                actor_user_id=actor_user_id,
                payload={"question": faq.question},
            )
        )

    async def reorder(
        self, *, company_id: UUID, ordered_ids: list[UUID], actor_user_id: UUID | None = None
    ) -> list[Faq]:
        """Moves the FAQs named, leaving the rest behind them in order.

        Partial by design. An administrator reordering the five FAQs on
        one filtered screen must not silently reshuffle the forty they
        never loaded, which is what a "this list *is* the order" contract
        would do — see ``domain/faq.reordered``.

        No re-index: order is not embedded.
        """
        current = await self._faqs.ordered_ids(company_id=company_id)
        positions = reordered(current=current, ordered_ids=ordered_ids)
        faqs = await self._faqs.get_many(company_id=company_id, faq_ids=list(positions))
        for faq in faqs:
            faq.display_order = positions[faq.id]
        faqs.sort(key=lambda item: item.display_order)
        return faqs
