"""FAQs end to end: authoring, publication, indexing, retrieval, isolation.

Runs against SQLite with the ``hashing`` embedding provider and the exact
vector index, per this suite's "no external services" rule — the same
combination ``test_semantic_retrieval.py`` uses, and for the same reason:
everything except the provider's semantics is the real thing.

The tests that matter most are the publication ones. An FAQ is the only
knowledge-base content written to be shown to *customers*, so "an
unpublished answer is not retrievable" and "unpublishing takes it out of
the index" are the two properties that decide whether a company can trust
the feature at all.
"""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.application.services.faq_retrieval_service import FaqRetrievalService
from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.embedding import (
    OWNER_FAQ,
    Embedding,
    KnowledgeIndexState,
)
from blinkengage.infrastructure.database.models.faq import Faq
from blinkengage.infrastructure.embeddings.providers.hashing import HashingEmbeddingProvider
from blinkengage.infrastructure.repositories.faq_repository import (
    FaqLexicalSearchRepository,
    FaqRepository,
)
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
)
from blinkengage.infrastructure.vector.factory import build_vector_index

DIMENSIONS = 1536

REFUND_QUESTION = "How long do refunds take?"
REFUND_ANSWER = "Refunds are returned to the original card within five working days."


def _provider() -> EmbeddingProvider:
    return HashingEmbeddingProvider(credentials={}, model=None, dimensions=DIMENSIONS)


def _embedding_service(session, *, with_provider: bool = True) -> EmbeddingService:
    """``with_provider=False`` is a real configuration, not a mock.

    A boolean rather than ``provider=None``, because ``None`` is exactly
    the value under test — "no embedding provider configured" — and a
    default that silently substituted one would make the degradation test
    assert nothing.
    """
    return EmbeddingService(
        provider=_provider() if with_provider else None,
        chunks=KnowledgeChunkRepository(session),
        embeddings=EmbeddingRepository(session),
    )


def _retrieval(session, *, with_provider: bool = True) -> FaqRetrievalService:
    return FaqRetrievalService(
        faqs=FaqRepository(session),
        lexical=FaqLexicalSearchRepository(session),
        vector_index=build_vector_index(session),
        embeddings=_embedding_service(session, with_provider=with_provider),
    )


async def _create(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    question: str = REFUND_QUESTION,
    answer: str = REFUND_ANSWER,
    **extra: object,
) -> dict:
    response = await client.post(
        "/api/v1/faqs",
        json={"question": question, "answer": answer, **extra},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _company_id(app) -> UUID:
    async with app.state.container.session_factory()() as session:
        company = (await session.execute(select(Company))).scalars().first()
        assert company is not None
        return company.id


async def _index_all(app) -> None:
    """Runs what the sweep runs, in-process."""
    async with app.state.container.session_factory()() as session:
        faqs = FaqRepository(session)
        service = _embedding_service(session)
        for faq in (await session.execute(select(Faq))).scalars().all():
            result = await service.index_faq(faq)
            if faq.deleted_at is not None or not faq.is_published:
                faq.index_state = KnowledgeIndexState.SKIPPED
            else:
                await faqs.mark_indexed(faq=faq, content_hash=result.digest or "")
        await session.commit()


class TestAuthoring:
    async def test_an_faq_is_created_unpublished(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The one asymmetry with knowledge articles, and the reason FAQ
        is its own entity: this content is shown to customers."""
        faq = await _create(client, owner_headers)

        assert faq["is_published"] is False
        assert faq["index_state"] == KnowledgeIndexState.PENDING

    async def test_publishing_is_an_explicit_act(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        faq = await _create(client, owner_headers)

        response = await client.patch(
            f"/api/v1/faqs/{faq['id']}", json={"is_published": True}, headers=owner_headers
        )

        assert response.status_code == 200
        assert response.json()["is_published"] is True

    async def test_a_question_without_an_answer_is_a_400_not_a_500(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/faqs",
            json={"question": "Do you deliver?", "answer": " "},
            headers=owner_headers,
        )

        # The caller made the mistake, and the response says which.
        assert response.status_code in {400, 422}

    async def test_an_unsupported_locale_is_refused(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/faqs",
            json={"question": "Q?", "answer": "A.", "locale": "fr"},
            headers=owner_headers,
        )

        assert response.status_code == 400

    async def test_tags_reuse_the_company_tag_catalog(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        faq = await _create(client, owner_headers, tags=["billing", "refunds"])

        assert faq["tags"] == ["billing", "refunds"]

    async def test_new_faqs_append_to_the_end_of_the_list(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        first = await _create(client, owner_headers, question="First?")
        second = await _create(client, owner_headers, question="Second?")

        assert second["display_order"] > first["display_order"]

    async def test_reordering_moves_only_what_it_names(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        first = await _create(client, owner_headers, question="First?")
        second = await _create(client, owner_headers, question="Second?")
        third = await _create(client, owner_headers, question="Third?")

        response = await client.post(
            "/api/v1/faqs/reorder",
            json={"ordered_ids": [third["id"], first["id"]]},
            headers=owner_headers,
        )
        assert response.status_code == 200

        listed = await client.get("/api/v1/faqs?page_size=50", headers=owner_headers)
        order = [item["id"] for item in listed.json()["items"]]
        assert order[0] == third["id"]
        assert order[1] == first["id"]
        # The one nobody named kept its place behind them rather than
        # being dropped or shuffled to the front.
        assert second["id"] in order


class TestIndexing:
    async def test_a_published_faq_is_embedded_as_one_vector(self, app, client, owner_headers):
        """One vector, not a chunk set. That simplification is what made
        a separate entity worth having."""
        faq = await _create(client, owner_headers, is_published=True)
        await _index_all(app)

        async with app.state.container.session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(Embedding).where(
                            Embedding.owner_type == OWNER_FAQ,
                            Embedding.owner_id == UUID(faq["id"]),
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert len(rows) == 1

    async def test_an_unpublished_faq_is_never_embedded(self, app, client, owner_headers):
        faq = await _create(client, owner_headers)  # unpublished by default
        await _index_all(app)

        async with app.state.container.session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(Embedding).where(Embedding.owner_id == UUID(faq["id"]))
                    )
                )
                .scalars()
                .all()
            )

        assert rows == []

    async def test_unpublishing_takes_the_vector_out_of_the_index(self, app, client, owner_headers):
        """The property that decides whether publication can be trusted.

        A retrievable unpublished FAQ is one the AI quotes at a customer
        after somebody took it down.
        """
        faq = await _create(client, owner_headers, is_published=True)
        await _index_all(app)

        await client.patch(
            f"/api/v1/faqs/{faq['id']}", json={"is_published": False}, headers=owner_headers
        )
        await _index_all(app)

        async with app.state.container.session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(Embedding).where(Embedding.owner_id == UUID(faq["id"]))
                    )
                )
                .scalars()
                .all()
            )

        assert rows == []

    async def test_deleting_an_faq_marks_it_for_removal_from_the_index(
        self, app, client, owner_headers
    ):
        faq = await _create(client, owner_headers, is_published=True)
        await _index_all(app)

        await client.delete(f"/api/v1/faqs/{faq['id']}", headers=owner_headers)

        async with app.state.container.session_factory()() as session:
            row = await session.get(Faq, UUID(faq["id"]))
            assert row is not None
            assert row.deleted_at is not None
            # Queued, in the same transaction as the delete — taking the
            # vector out is what makes the deletion real.
            assert row.index_state == KnowledgeIndexState.PENDING

        await _index_all(app)
        async with app.state.container.session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(Embedding).where(Embedding.owner_id == UUID(faq["id"]))
                    )
                )
                .scalars()
                .all()
            )
        assert rows == []

    async def test_retagging_does_not_cost_a_re_embedding(self, app, client, owner_headers):
        """A vector encodes neither a tag nor a category, so a retag must
        not mark the row pending and pay the provider again."""
        faq = await _create(client, owner_headers, is_published=True)
        await _index_all(app)

        await client.patch(
            f"/api/v1/faqs/{faq['id']}", json={"tags": ["billing"]}, headers=owner_headers
        )

        async with app.state.container.session_factory()() as session:
            row = await session.get(Faq, UUID(faq["id"]))
            assert row is not None
            assert row.index_state == KnowledgeIndexState.INDEXED

    async def test_editing_the_answer_does_queue_a_re_embedding(self, app, client, owner_headers):
        faq = await _create(client, owner_headers, is_published=True)
        await _index_all(app)

        await client.patch(
            f"/api/v1/faqs/{faq['id']}",
            json={"answer": "Refunds now take three working days."},
            headers=owner_headers,
        )

        async with app.state.container.session_factory()() as session:
            row = await session.get(Faq, UUID(faq["id"]))
            assert row is not None
            assert row.index_state == KnowledgeIndexState.PENDING


class TestRetrieval:
    async def test_search_finds_an_faq_by_its_own_words(self, app, client, owner_headers):
        await _create(client, owner_headers, is_published=True)
        await _index_all(app)

        response = await client.get("/api/v1/faqs/search?q=refunds", headers=owner_headers)

        assert response.status_code == 200
        body = response.json()
        assert len(body["hits"]) == 1
        assert body["hits"][0]["faq"]["question"] == REFUND_QUESTION
        # Why it is here, not just that it is.
        assert body["hits"][0]["sources"]

    async def test_search_matches_a_term_that_appears_only_in_the_answer(
        self, app, client, owner_headers
    ):
        """The reason both fields are embedded and both are searched: a
        customer types a product name the question never mentions."""
        await _create(
            client,
            owner_headers,
            question="How can I pay?",
            answer="We accept Visa, Mastercard and eFAWATEERcom.",
            is_published=True,
        )
        await _index_all(app)

        response = await client.get("/api/v1/faqs/search?q=eFAWATEERcom", headers=owner_headers)

        assert [hit["faq"]["question"] for hit in response.json()["hits"]] == ["How can I pay?"]

    async def test_an_unpublished_faq_is_not_returned_by_search(self, app, client, owner_headers):
        await _create(client, owner_headers)  # unpublished
        await _index_all(app)

        response = await client.get("/api/v1/faqs/search?q=refunds", headers=owner_headers)

        assert response.json()["hits"] == []

    async def test_search_degrades_to_lexical_without_an_embedding_provider(
        self, app, registered_owner
    ):
        """A provider outage must not make a company's published answers
        unfindable — it must make them findable by keyword and say so."""
        company_id = await _company_id(app)
        async with app.state.container.session_factory()() as session:
            session.add(
                Faq(
                    company_id=company_id,
                    question=REFUND_QUESTION,
                    answer=REFUND_ANSWER,
                    is_published=True,
                )
            )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            outcome = await _retrieval(session, with_provider=False).search(
                company_id=company_id, query="refunds"
            )

        assert outcome.degraded is True
        assert outcome.reason == "embeddings_not_configured"
        assert len(outcome.hits) == 1

    async def test_a_query_too_short_to_mean_anything_returns_nothing(self, app, registered_owner):
        company_id = await _company_id(app)
        async with app.state.container.session_factory()() as session:
            outcome = await _retrieval(session).search(company_id=company_id, query="a")

        assert outcome.hits == []
        assert outcome.reason == "query_too_short"

    async def test_locale_filtering_still_returns_language_neutral_faqs(
        self, app, client, owner_headers
    ):
        """An FAQ with no locale — a price, a phone number — belongs in
        every language's list rather than none."""
        await _create(
            client, owner_headers, question="What are your hours?", locale="en", is_published=True
        )
        await _create(
            client,
            owner_headers,
            question="What is the delivery fee?",
            answer="Three dinars.",
            is_published=True,
        )
        await _index_all(app)

        response = await client.get(
            "/api/v1/faqs?locale=en&published_only=true&page_size=50", headers=owner_headers
        )

        questions = {item["question"] for item in response.json()["items"]}
        assert "What are your hours?" in questions
        assert "What is the delivery fee?" in questions


class TestIsolationAndAccess:
    async def test_one_company_never_retrieves_another_companys_faq(
        self, app, client, owner_headers
    ):
        """The vector index filters by company and the hydration filters
        again — a single point of failure for tenant isolation is not
        one."""
        await _create(client, owner_headers, is_published=True)

        other_company = Company(name="Other Co", slug=f"other-{uuid4().hex[:8]}")
        async with app.state.container.session_factory()() as session:
            session.add(other_company)
            await session.flush()
            other_id = other_company.id
            session.add(
                Faq(
                    company_id=other_id,
                    question="Their private question?",
                    answer="Their private answer.",
                    is_published=True,
                )
            )
            await session.commit()

        await _index_all(app)

        async with app.state.container.session_factory()() as session:
            outcome = await _retrieval(session).search(company_id=other_id, query="refunds")

        assert all(hit.faq.company_id == other_id for hit in outcome.hits)

    async def test_reading_an_faq_from_another_company_is_a_404(self, app, client, owner_headers):
        other_company = Company(name="Other Co 2", slug=f"other2-{uuid4().hex[:8]}")
        async with app.state.container.session_factory()() as session:
            session.add(other_company)
            await session.flush()
            foreign = Faq(
                company_id=other_company.id,
                question="Theirs?",
                answer="Theirs.",
                is_published=True,
            )
            session.add(foreign)
            await session.commit()
            foreign_id = foreign.id

        response = await client.get(f"/api/v1/faqs/{foreign_id}", headers=owner_headers)

        assert response.status_code == 404

    async def test_managing_faqs_requires_a_permission(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/faqs", json={"question": "Q?", "answer": "A."})

        assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_faq_events_reach_the_audit_log(app, client, owner_headers, drain_outbox) -> None:
    """FAQ writes ride the existing outbox, so they are audited with no
    new machinery — the audit consumer binds everything."""
    faq = await _create(client, owner_headers)
    await client.patch(
        f"/api/v1/faqs/{faq['id']}", json={"is_published": True}, headers=owner_headers
    )
    await drain_outbox()

    response = await client.get("/api/v1/audit-logs?page_size=100", headers=owner_headers)
    actions = {row["action"] for row in response.json()["items"]}

    assert "faq.created" in actions
    assert "faq.updated" in actions
