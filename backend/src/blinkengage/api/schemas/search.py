from typing import Literal
from uuid import UUID

from pydantic import BaseModel

#: Every entity type global search can return. The frontend keys its
#: per-type labels/icons/links off these exact strings — see
#: ``frontend/src/features/search/types.ts``.
SearchEntityType = Literal[
    "conversation",
    "customer",
    "knowledge_article",
    "knowledge_category",
    "quick_reply",
    "agent",
    "team",
    "queue",
    "workflow",
]


class SearchHitResponse(BaseModel):
    entity_type: SearchEntityType
    id: UUID
    title: str
    subtitle: str | None


class SearchResponse(BaseModel):
    """Results are grouped per entity type client-side off ``entity_type``
    rather than nested here, so adding a new searchable entity never
    changes this envelope's shape. ``searched_entity_types`` is what the
    caller's own permissions actually allowed — a caller lacking, say,
    ``workflows.read`` gets no workflow results *and* is told workflows
    weren't searched, rather than being left to infer "no matches" from
    an empty list."""

    query: str
    results: list[SearchHitResponse]
    searched_entity_types: list[SearchEntityType]
