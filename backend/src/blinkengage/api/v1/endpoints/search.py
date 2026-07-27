from typing import Annotated

from fastapi import APIRouter, Depends, Query

from blinkengage.api.deps import enforce_search_rate_limit, get_search_service
from blinkengage.api.schemas.search import SearchHitResponse, SearchResponse
from blinkengage.application.services.search_service import SearchService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def global_search(
    auth: Annotated[AuthContext, Depends(enforce_search_rate_limit)],
    service: Annotated[SearchService, Depends(get_search_service)],
    q: Annotated[str, Query(min_length=1, max_length=255)],
) -> SearchResponse:
    """Searches every entity type the caller can read, in one request.

    Deliberately gated on authentication alone rather than any single
    ``require_permission`` — one search spans nine entity types with
    nine different permissions, so a route-level gate would 403 a caller
    who legitimately can't read one of them. ``SearchService`` filters
    per entity type against the caller's own permission set instead, and
    reports back which types it actually searched.
    """
    outcome = await service.search(company_id=auth.company_id, term=q, permissions=auth.permissions)
    return SearchResponse(
        query=q,
        results=[
            SearchHitResponse(
                entity_type=hit.entity_type,
                id=hit.id,
                title=hit.title,
                subtitle=hit.subtitle,
            )
            for hit in outcome.hits
        ],
        searched_entity_types=outcome.searched_entity_types,
    )
