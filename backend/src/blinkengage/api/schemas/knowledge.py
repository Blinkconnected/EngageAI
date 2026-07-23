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
