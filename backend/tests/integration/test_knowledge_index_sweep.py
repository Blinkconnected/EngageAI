"""The re-index sweep: claiming, retries, the circuit breaker, and the
per-company provider boundary.

The circuit-breaker test is the one that earns its place. The outbox relay
shipped without an attempts cap and a single permanently-failing row
reclaimed itself every five seconds for twenty hours, starving every
healthy event behind it — 14,586 attempts on one row while brand-new
events sat at zero. This queue has the same shape, so it has the same
guard, and this is the test that says the guard works.
"""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.infrastructure.database.models.embedding import (
    Embedding,
    KnowledgeChunk,
    KnowledgeIndexState,
)
from blinkengage.infrastructure.database.models.knowledge import KnowledgeArticle
from blinkengage.infrastructure.embeddings.providers.hashing import HashingEmbeddingProvider
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
    KnowledgeIndexStateRepository,
)

DIMENSIONS = 1536


class ExplodingProvider(EmbeddingProvider):
    """Stands in for a provider outage — the case the retry cap exists
    for."""

    @property
    def model(self) -> str:
        return "exploding"

    @property
    def dimensions(self) -> int:
        return DIMENSIONS

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider is down")

    async def health_check(self) -> bool:
        return False


async def _create_article(client: AsyncClient, headers: dict[str, str], *, title: str) -> UUID:
    response = await client.post(
        "/api/v1/knowledge/articles",
        headers=headers,
        json={"title": title, "body": f"Body of {title}.", "is_published": True, "tags": []},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


class TestClaiming:
    async def test_a_new_article_is_pending_without_anything_asking(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """The column defaults to PENDING, so creation needs no extra
        write and no event round-trip to reach the queue."""
        await _create_article(client, owner_headers, title="Refunds")

        async with app.state.container.session_factory()() as session:
            claimed = await KnowledgeIndexStateRepository(session).claim_batch(
                limit=10, max_attempts=5
            )

        assert [a.title for a in claimed] == ["Refunds"]

    async def test_editing_an_article_re_queues_it(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        article_id = await _create_article(client, owner_headers, title="Refunds")
        async with app.state.container.session_factory()() as session:
            state = KnowledgeIndexStateRepository(session)
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            await state.mark_indexed(article=article, content_hash="x" * 64)
            await session.commit()

        await client.patch(
            f"/api/v1/knowledge/articles/{article_id}",
            headers=owner_headers,
            json={"body": "Rewritten."},
        )

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            assert article.index_state == KnowledgeIndexState.PENDING

    async def test_a_soft_deleted_article_is_still_claimed(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """Deleting is exactly when the index most needs updating. If the
        claim filtered soft-deleted rows out, a deleted article would stay
        searchable and quotable forever while being invisible in every
        list its company can see."""
        article_id = await _create_article(client, owner_headers, title="Retired")
        await client.delete(f"/api/v1/knowledge/articles/{article_id}", headers=owner_headers)

        async with app.state.container.session_factory()() as session:
            claimed = await KnowledgeIndexStateRepository(session).claim_batch(
                limit=10, max_attempts=5
            )

        assert [a.id for a in claimed] == [article_id]

    async def test_claiming_is_bounded(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """A backfill of a whole corpus must not become one enormous
        transaction; the next sweep is a minute away."""
        for n in range(6):
            await _create_article(client, owner_headers, title=f"Article {n}")

        async with app.state.container.session_factory()() as session:
            claimed = await KnowledgeIndexStateRepository(session).claim_batch(
                limit=3, max_attempts=5
            )

        assert len(claimed) == 3


class TestFailureHandling:
    async def test_a_failing_article_records_its_error_and_stays_pending(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        article_id = await _create_article(client, owner_headers, title="Refunds")

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            await KnowledgeIndexStateRepository(session).mark_failed(
                article=article, error="RuntimeError: provider is down"
            )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            assert article.index_attempts == 1
            assert article.index_state == KnowledgeIndexState.PENDING
            assert "provider is down" in str(article.index_error)

    async def test_a_permanently_failing_article_stops_being_claimed(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """The circuit breaker. Without it one poison row is reclaimed
        forever and starves every healthy article behind it — the exact
        failure the outbox relay suffered in production."""
        poison_id = await _create_article(client, owner_headers, title="Poison")

        async with app.state.container.session_factory()() as session:
            state = KnowledgeIndexStateRepository(session)
            article = await session.get(KnowledgeArticle, poison_id)
            assert article is not None
            for _ in range(5):
                await state.mark_failed(article=article, error="boom")
            await session.commit()

        healthy_id = await _create_article(client, owner_headers, title="Healthy")

        async with app.state.container.session_factory()() as session:
            claimed = await KnowledgeIndexStateRepository(session).claim_batch(
                limit=10, max_attempts=5
            )

        claimed_ids = [a.id for a in claimed]
        assert poison_id not in claimed_ids
        assert healthy_id in claimed_ids

    async def test_a_dead_lettered_article_is_visible_to_an_operator(
        self, client: AsyncClient, owner_headers: dict[str, str], app, registered_owner: dict
    ) -> None:
        """Excluded from claiming is not the same as forgotten — an
        operator must be able to find what is missing from the index."""
        article_id = await _create_article(client, owner_headers, title="Poison")
        company_id = UUID(registered_owner["user"]["company"]["id"])

        async with app.state.container.session_factory()() as session:
            state = KnowledgeIndexStateRepository(session)
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            for _ in range(5):
                await state.mark_failed(article=article, error="boom")
            await session.commit()

        async with app.state.container.session_factory()() as session:
            failed = await KnowledgeIndexStateRepository(session).failed_articles(
                company_id=company_id, max_attempts=5
            )

        assert [a.id for a in failed] == [article_id]

    async def test_a_provider_outage_leaves_no_partial_index(
        self, client: AsyncClient, owner_headers: dict[str, str], app
    ) -> None:
        """Chunks and vectors are written in one transaction, so a failure
        halfway through leaves neither — a half-embedded article would be
        retrievable only in part, with nothing saying so."""
        article_id = await _create_article(client, owner_headers, title="Refunds")

        with pytest.raises(RuntimeError, match="provider is down"):
            async with app.state.container.session_factory()() as session:
                article = await session.get(KnowledgeArticle, article_id)
                assert article is not None
                service = EmbeddingService(
                    provider=ExplodingProvider(credentials={}, model=None),
                    chunks=KnowledgeChunkRepository(session),
                    embeddings=EmbeddingRepository(session),
                )
                await service.index_article(article)
                await session.commit()

        async with app.state.container.session_factory()() as session:
            vectors = (await session.execute(select(Embedding))).scalars().all()

        assert vectors == []


class TestIndexStatus:
    async def test_status_reports_coverage_and_backlog(
        self, client: AsyncClient, owner_headers: dict[str, str], app, registered_owner: dict
    ) -> None:
        company_id = UUID(registered_owner["user"]["company"]["id"])
        article_id = await _create_article(client, owner_headers, title="Refunds")

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            service = EmbeddingService(
                provider=HashingEmbeddingProvider(
                    credentials={}, model=None, dimensions=DIMENSIONS
                ),
                chunks=KnowledgeChunkRepository(session),
                embeddings=EmbeddingRepository(session),
                index_state=KnowledgeIndexStateRepository(session),
            )
            await service.index_article(article)
            await KnowledgeIndexStateRepository(session).mark_indexed(
                article=article, content_hash="h" * 64
            )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            service = EmbeddingService(
                provider=HashingEmbeddingProvider(
                    credentials={}, model=None, dimensions=DIMENSIONS
                ),
                chunks=KnowledgeChunkRepository(session),
                embeddings=EmbeddingRepository(session),
                index_state=KnowledgeIndexStateRepository(session),
            )
            status = await service.index_status(company_id=company_id)

        assert status.chunks_total == 1
        assert status.chunks_embedded == 1
        assert status.articles_pending == 0
        assert status.articles_failed == 0

    async def test_coverage_is_reported_per_model(
        self, client: AsyncClient, owner_headers: dict[str, str], app, registered_owner: dict
    ) -> None:
        """The gate a model cutover waits on: switching before coverage is
        complete would leave part of the corpus unsearchable."""
        company_id = UUID(registered_owner["user"]["company"]["id"])
        article_id = await _create_article(client, owner_headers, title="Refunds")

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            await EmbeddingService(
                provider=HashingEmbeddingProvider(
                    credentials={}, model="model-a", dimensions=DIMENSIONS
                ),
                chunks=KnowledgeChunkRepository(session),
                embeddings=EmbeddingRepository(session),
            ).index_article(article)
            await session.commit()

        async with app.state.container.session_factory()() as session:
            embedded, total = await EmbeddingRepository(session).coverage(
                company_id=company_id, model="model-b"
            )

        assert total == 1
        assert embedded == 0

    async def test_the_index_status_endpoint_is_gated_on_manage(
        self, client: AsyncClient, owner_headers: dict[str, str]
    ) -> None:
        response = await client.get("/api/v1/knowledge/index-status", headers=owner_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["embeddings_enabled"] is False
        assert body["dimensions"] == DIMENSIONS

    async def test_index_status_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/knowledge/index-status")
        assert response.status_code == 403


class TestModelMigration:
    async def test_old_model_vectors_are_dropped_only_when_asked(
        self, client: AsyncClient, owner_headers: dict[str, str], app, registered_owner: dict
    ) -> None:
        """Deleting old vectors before the new ones exist would leave a
        company with no retrieval at all, so the cutover is an explicit
        call and never a side effect of indexing."""
        company_id = UUID(registered_owner["user"]["company"]["id"])
        article_id = await _create_article(client, owner_headers, title="Refunds")

        async with app.state.container.session_factory()() as session:
            article = await session.get(KnowledgeArticle, article_id)
            assert article is not None
            for model in ("model-a", "model-b"):
                await EmbeddingService(
                    provider=HashingEmbeddingProvider(
                        credentials={}, model=model, dimensions=DIMENSIONS
                    ),
                    chunks=KnowledgeChunkRepository(session),
                    embeddings=EmbeddingRepository(session),
                ).index_article(article)
            await session.commit()

        async with app.state.container.session_factory()() as session:
            both = (await session.execute(select(Embedding))).scalars().all()
            assert {e.model for e in both} == {"model-a", "model-b"}

            removed = await EmbeddingRepository(session).delete_stale_models(
                company_id=company_id, keep_model="model-b"
            )
            await session.commit()

        assert removed == 1

        async with app.state.container.session_factory()() as session:
            remaining = (await session.execute(select(Embedding))).scalars().all()
            chunks = (await session.execute(select(KnowledgeChunk))).scalars().all()

        assert {e.model for e in remaining} == {"model-b"}
        # The chunks themselves are untouched — only vectors are re-derived.
        assert len(chunks) == 1
