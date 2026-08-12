"""End-to-end semantic retrieval: index an article, search it, and prove
the tenant boundary holds.

Runs against SQLite with the ``hashing`` embedding provider and the exact
vector index, per this suite's "no external services" rule. That
combination is not a mock — it is the real ``EmbeddingService``, the real
``KnowledgeRetrievalService``, the real fusion and the real repositories;
only the provider's *semantics* are crude and the search is exhaustive
rather than approximate. The pgvector path is verified separately against
a real PostgreSQL, and ``test_vector_index_parity`` asserts the two
adapters agree.
"""

from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import get_db_session, get_embedding_service
from blinkengage.application.services.embedding_service import (
    EmbeddingService,
    article_content_hash,
)
from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.embedding import (
    OWNER_KNOWLEDGE_CHUNK,
    Embedding,
    KnowledgeChunk,
)
from blinkengage.infrastructure.database.models.knowledge import KnowledgeArticle
from blinkengage.infrastructure.embeddings.providers.hashing import HashingEmbeddingProvider
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
    KnowledgeIndexStateRepository,
)

DIMENSIONS = 1536


def _provider(model: str | None = None) -> EmbeddingProvider:
    return HashingEmbeddingProvider(credentials={}, model=model, dimensions=DIMENSIONS)


def _service(session, provider: EmbeddingProvider | None = _provider()) -> EmbeddingService:
    return EmbeddingService(
        provider=provider,
        chunks=KnowledgeChunkRepository(session),
        embeddings=EmbeddingRepository(session),
        index_state=KnowledgeIndexStateRepository(session),
    )


async def _create_article(
    client: AsyncClient, headers: dict[str, str], *, title: str, body: str
) -> UUID:
    response = await client.post(
        "/api/v1/knowledge/articles",
        headers=headers,
        json={"title": title, "body": body, "is_published": True, "tags": []},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _index_all(app) -> None:
    """Runs what the sweep runs, synchronously — the same claim query, the
    same service, the same repositories, without Celery.

    Claiming through ``KnowledgeIndexStateRepository`` rather than a
    hand-written SELECT is the point: a helper that picked articles its own
    way would pass while the real sweep skipped them, which is exactly how
    the soft-delete case stayed broken until this test was written.
    """
    async with app.state.container.session_factory()() as session:
        state = KnowledgeIndexStateRepository(session)
        claimed = await state.claim_batch(limit=100, max_attempts=5)
        service = _service(session)
        for article in claimed:
            if article.deleted_at is None and article.is_published:
                await service.index_article(article)
            else:
                await service.remove_article(company_id=article.company_id, article_id=article.id)
            await state.mark_indexed(
                article=article,
                content_hash=article_content_hash(title=article.title, body=article.body),
            )
        await session.commit()


@pytest.fixture
def semantic_search_enabled(app):
    """Turns semantic retrieval on for the HTTP path.

    The platform default is ``EMBEDDING_PROVIDER=disabled``, and the suite
    keeps it that way so the *degraded* path is what an unconfigured
    deployment actually gets — tested directly in
    ``test_search_is_degraded_and_says_so_without_a_provider``. Tests that
    are about semantic behaviour override the dependency instead of
    changing the global default, so both states are covered rather than
    whichever one the environment happened to have.
    """

    async def _override(
        session: AsyncSession = Depends(get_db_session),
    ) -> EmbeddingService:
        return _service(session)

    app.dependency_overrides[get_embedding_service] = _override
    yield app
    app.dependency_overrides.pop(get_embedding_service, None)


class TestIndexing:
    async def test_indexing_an_article_creates_chunks_and_vectors(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        await _create_article(
            client, owner_headers, title="Refund policy", body="We refund within 14 days."
        )

        await _index_all(app)

        from sqlalchemy import select

        async with app.state.container.session_factory()() as session:
            chunks = (await session.execute(select(KnowledgeChunk))).scalars().all()
            vectors = (await session.execute(select(Embedding))).scalars().all()

        assert len(chunks) == 1
        assert len(vectors) == 1
        assert vectors[0].owner_type == OWNER_KNOWLEDGE_CHUNK
        assert vectors[0].owner_id == chunks[0].id
        assert vectors[0].dimensions == DIMENSIONS
        assert len(vectors[0].vector) == DIMENSIONS

    async def test_reindexing_unchanged_text_embeds_nothing(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """The incremental path. Re-embedding unchanged chunks is the
        difference between a feature a company leaves on and one they
        switch off."""
        article_id = await _create_article(
            client, owner_headers, title="Shipping", body="We ship within two days."
        )
        await _index_all(app)

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            result = await _service(session).index_article(article)

        assert result.chunks_embedded == 0
        assert result.chunks_created == 0
        assert result.chunks_updated == 0

    async def test_editing_one_paragraph_re_embeds_only_that_chunk(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        paragraphs = [f"Paragraph {n} about topic {n}. " + "filler " * 60 for n in range(4)]
        article_id = await _create_article(
            client, owner_headers, title="Manual", body="\n\n".join(paragraphs)
        )
        await _index_all(app)

        paragraphs[2] = "Paragraph 2 completely rewritten. " + "different " * 60
        response = await client.patch(
            f"/api/v1/knowledge/articles/{article_id}",
            headers=owner_headers,
            json={"body": "\n\n".join(paragraphs)},
        )
        assert response.status_code == 200, response.text

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            result = await _service(session).index_article(article)
            await session.commit()

        assert result.chunks_updated == 1
        assert result.chunks_embedded == 1

    async def test_shortening_an_article_deletes_orphan_chunks_and_their_vectors(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """`Embedding.owner_id` has no foreign key, so nothing in the
        database enforces this — the repository does, and this is the test
        that stands in for referential integrity."""
        long_body = "\n\n".join(f"Paragraph {n}. " + "word " * 80 for n in range(6))
        article_id = await _create_article(client, owner_headers, title="Guide", body=long_body)
        await _index_all(app)

        from sqlalchemy import select

        async with app.state.container.session_factory()() as session:
            before = len((await session.execute(select(KnowledgeChunk))).scalars().all())
        assert before > 1

        await client.patch(
            f"/api/v1/knowledge/articles/{article_id}",
            headers=owner_headers,
            json={"body": "Now very short."},
        )
        await _index_all(app)

        async with app.state.container.session_factory()() as session:
            chunks = (await session.execute(select(KnowledgeChunk))).scalars().all()
            vectors = (await session.execute(select(Embedding))).scalars().all()

        assert len(chunks) == 1
        # No vector outlives its chunk.
        assert {v.owner_id for v in vectors} == {c.id for c in chunks}

    async def test_deleting_an_article_removes_it_from_the_index(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """A soft-deleted article whose chunks stayed indexed would be
        invisible in every list the company can see while the AI kept
        quoting it."""
        article_id = await _create_article(
            client, owner_headers, title="Retired offer", body="Half price forever."
        )
        await _index_all(app)

        response = await client.delete(
            f"/api/v1/knowledge/articles/{article_id}", headers=owner_headers
        )
        assert response.status_code == 204
        await _index_all(app)

        from sqlalchemy import select

        async with app.state.container.session_factory()() as session:
            chunks = (await session.execute(select(KnowledgeChunk))).scalars().all()
            vectors = (await session.execute(select(Embedding))).scalars().all()

        assert chunks == []
        assert vectors == []

    async def test_indexing_works_without_an_embedding_provider(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """Chunking is free and useful on its own: turning embeddings on
        later becomes a backfill rather than a cold start."""
        article_id = await _create_article(
            client, owner_headers, title="Hours", body="We open at nine."
        )

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            result = await _service(session, provider=None).index_article(article)
            await session.commit()

        assert result.chunks_total == 1
        assert result.chunks_embedded == 0


class TestSearch:
    async def test_search_finds_an_article_by_exact_wording(
        self, client: AsyncClient, owner_headers: dict[str, str], app, semantic_search_enabled
    ) -> None:
        await _create_article(
            client, owner_headers, title="Refund policy", body="We refund within 14 days."
        )
        await _index_all(app)

        response = await client.get(
            "/api/v1/knowledge/search", headers=owner_headers, params={"q": "refund"}
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["hits"]) == 1
        assert body["hits"][0]["article"]["title"] == "Refund policy"

    async def test_a_hit_reports_which_retrievers_found_it(
        self, client: AsyncClient, owner_headers: dict[str, str], app, semantic_search_enabled
    ) -> None:
        """ "Why is this here?" is answerable from the response itself."""
        await _create_article(
            client, owner_headers, title="Refund policy", body="We refund within 14 days."
        )
        await _index_all(app)

        response = await client.get(
            "/api/v1/knowledge/search", headers=owner_headers, params={"q": "refund"}
        )

        hit = response.json()["hits"][0]
        assert "lexical" in hit["sources"]
        assert "semantic" in hit["sources"]
        assert hit["ranks"]["lexical"] >= 1
        assert hit["excerpt"]

    async def test_search_is_degraded_and_says_so_without_a_provider(
        self, client: AsyncClient, owner_headers: dict[str, str], app, monkeypatch
    ) -> None:
        """A search that quietly halves its own recall is worse than one
        that says it did."""
        await _create_article(
            client, owner_headers, title="Refund policy", body="We refund within 14 days."
        )

        response = await client.get(
            "/api/v1/knowledge/search", headers=owner_headers, params={"q": "refund"}
        )

        body = response.json()
        assert response.status_code == 200
        assert body["degraded"] is True
        assert body["reason"] == "embeddings_not_configured"
        # Still useful: the lexical half is a real search.
        assert len(body["hits"]) == 1
        assert body["sources"] == ["lexical"]

    async def test_unpublished_articles_are_not_returned_by_default(
        self, client: AsyncClient, owner_headers: dict[str, str], app, semantic_search_enabled
    ) -> None:
        response = await client.post(
            "/api/v1/knowledge/articles",
            headers=owner_headers,
            json={
                "title": "Draft refund policy",
                "body": "We refund within 30 days.",
                "is_published": False,
                "tags": [],
            },
        )
        assert response.status_code == 201
        await _index_all(app)

        response = await client.get(
            "/api/v1/knowledge/search", headers=owner_headers, params={"q": "refund"}
        )

        assert response.json()["hits"] == []

    async def test_a_very_short_query_returns_nothing_rather_than_noise(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        response = await client.get(
            "/api/v1/knowledge/search", headers=owner_headers, params={"q": "a"}
        )

        body = response.json()
        assert body["hits"] == []
        assert body["reason"] == "query_too_short"

    async def test_search_requires_authentication(self, client: AsyncClient) -> None:
        """401 for a route reached with no credentials at all.

        This asserted 403 until FastAPI 0.141, whose ``HTTPBearer`` raises
        401 for absent credentials rather than 403 — the semantically
        correct code, and the one RFC 9110 specifies for "no credentials"
        as against "credentials that do not suffice".

        The previous docstring said it asserted the behaviour "as it
        actually behaves rather than as it might ideally, so this test
        fails if that contract changes". It did change, and this test is
        how that was found. Kept in that spirit: asserted as it behaves.
        """
        response = await client.get("/api/v1/knowledge/search", params={"q": "refund"})
        assert response.status_code == 401


class TestTenantIsolation:
    """The invariant the whole design is arranged around: no cross-tenant
    embeddings, ever, by any path."""

    async def test_search_never_returns_another_companys_article(
        self, client: AsyncClient, owner_headers: dict[str, str], app, semantic_search_enabled
    ) -> None:
        await _create_article(
            client, owner_headers, title="Acme refund policy", body="We refund within 14 days."
        )

        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Other Corp",
                "owner_full_name": "Bob Other",
                "owner_email": "bob@other.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        assert other.status_code == 201, other.text
        other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
        from datetime import UTC, datetime

        from sqlalchemy import update

        from blinkengage.infrastructure.database.models.user import User

        other_company_id = UUID(other.json()["user"]["company"]["id"])
        async with app.state.container.session_factory()() as session:
            moment = datetime.now(UTC)
            await session.execute(
                update(Company).where(Company.id == other_company_id).values(verified_at=moment)
            )
            await session.execute(
                update(User)
                .where(User.company_id == other_company_id)
                .values(email_verified_at=moment)
            )
            await session.commit()

        await _create_article(
            client, other_headers, title="Other refund policy", body="We refund within 90 days."
        )
        await _index_all(app)

        acme = await client.get(
            "/api/v1/knowledge/search", headers=owner_headers, params={"q": "refund"}
        )
        theirs = await client.get(
            "/api/v1/knowledge/search", headers=other_headers, params={"q": "refund"}
        )

        assert [h["article"]["title"] for h in acme.json()["hits"]] == ["Acme refund policy"]
        assert [h["article"]["title"] for h in theirs.json()["hits"]] == ["Other refund policy"]

    async def test_the_vector_index_cannot_be_asked_across_companies(self, app) -> None:
        """Structural, not conventional: ``company_id`` is a required
        argument, so a caller cannot express a cross-tenant search."""
        from blinkengage.infrastructure.vector.exact_index import ExactVectorIndex

        async with app.state.container.session_factory()() as session:
            index = ExactVectorIndex(session)
            with pytest.raises(TypeError):
                await index.search(  # type: ignore[call-arg]
                    model="hashing-1536", query_vector=[0.1] * DIMENSIONS, limit=5
                )

    async def test_a_vector_search_filters_by_company_before_ranking(
        self, app, owner_headers: dict[str, str]
    ) -> None:
        """The failure this guards against is subtle: an ANN index ranks
        before predicates apply, so "search then filter" returns whatever
        fraction of the top-k happened to belong to the right tenant."""
        from sqlalchemy import select

        from blinkengage.infrastructure.vector.exact_index import ExactVectorIndex

        async with app.state.container.session_factory()() as session:
            company = (await session.execute(select(Company))).scalars().first()
            assert company is not None
            stranger_id = uuid4()

            repo = EmbeddingRepository(session)
            mine = uuid4()
            theirs = uuid4()
            await repo.upsert(
                company_id=company.id,
                owner_type=OWNER_KNOWLEDGE_CHUNK,
                owner_id=mine,
                model="hashing-1536",
                dimensions=DIMENSIONS,
                content_hash="a" * 64,
                vector=[1.0] + [0.0] * (DIMENSIONS - 1),
            )
            # A row belonging to nobody in this test's company, with a
            # vector *closer* to the query than the legitimate one.
            session.add(
                Embedding(
                    company_id=stranger_id,
                    owner_type=OWNER_KNOWLEDGE_CHUNK,
                    owner_id=theirs,
                    model="hashing-1536",
                    dimensions=DIMENSIONS,
                    content_hash="b" * 64,
                    vector=[1.0] + [0.0] * (DIMENSIONS - 1),
                )
            )
            await session.flush()

            matches = await ExactVectorIndex(session).search(
                company_id=company.id,
                model="hashing-1536",
                query_vector=[1.0] + [0.0] * (DIMENSIONS - 1),
                limit=10,
            )

        assert [match.owner_id for match in matches] == [mine]


class TestModelIsolation:
    async def test_vectors_from_another_model_are_never_ranked_together(
        self, app, owner_headers: dict[str, str]
    ) -> None:
        """A half-finished model migration must return *fewer* results, not
        two models' vectors ranked against each other — which is not a
        degraded ranking but a meaningless one."""
        from sqlalchemy import select

        from blinkengage.infrastructure.vector.exact_index import ExactVectorIndex

        async with app.state.container.session_factory()() as session:
            company = (await session.execute(select(Company))).scalars().first()
            assert company is not None
            repo = EmbeddingRepository(session)
            old_model_owner = uuid4()
            await repo.upsert(
                company_id=company.id,
                owner_type=OWNER_KNOWLEDGE_CHUNK,
                owner_id=old_model_owner,
                model="previous-model",
                dimensions=DIMENSIONS,
                content_hash="c" * 64,
                vector=[1.0] + [0.0] * (DIMENSIONS - 1),
            )

            matches = await ExactVectorIndex(session).search(
                company_id=company.id,
                model="hashing-1536",
                query_vector=[1.0] + [0.0] * (DIMENSIONS - 1),
                limit=10,
            )

        assert matches == []
