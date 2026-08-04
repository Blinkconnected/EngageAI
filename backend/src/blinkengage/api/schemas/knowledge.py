from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeCategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: UUID | None = None


class KnowledgeCategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: UUID | None = None


class KnowledgeCategoryResponse(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeArticleCreateRequest(BaseModel):
    category_id: UUID | None = None
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    is_published: bool = True
    tags: list[str] = Field(default_factory=list)


class KnowledgeArticleUpdateRequest(BaseModel):
    category_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1)
    is_published: bool | None = None
    tags: list[str] | None = None


class KnowledgeArticleResponse(BaseModel):
    id: UUID
    category_id: UUID | None
    title: str
    body: str
    is_published: bool
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class KnowledgeSearchHit(BaseModel):
    """One hybrid-retrieval result.

    ``sources`` and ``ranks`` are returned rather than kept server-side
    because the first question anybody asks of a search result is "why is
    this here?" — and after replacing a substring match with a fused
    ranking, an administrator comparing the two needs to see which half
    found what. It is also what makes a bad ranking reportable rather than
    merely felt.
    """

    article: KnowledgeArticleResponse
    score: float
    sources: list[str]
    ranks: dict[str, int]
    excerpt: str | None = None
    chunk_id: UUID | None = None


class KnowledgeSearchResponse(BaseModel):
    """Results plus an honest account of how they were produced.

    ``degraded``/``reason`` exist so a client can say "semantic search is
    switched off" instead of silently showing keyword-only results that
    look like the whole answer. A search that quietly halves its own
    recall is worse than one that says it did.
    """

    hits: list[KnowledgeSearchHit]
    sources: list[str]
    degraded: bool
    reason: str | None = None


class KnowledgeIndexStatusResponse(BaseModel):
    """Operator view of the semantic index for one company."""

    embeddings_enabled: bool
    model: str | None
    dimensions: int
    chunks_total: int
    chunks_embedded: int
    articles_pending: int
    articles_failed: int
