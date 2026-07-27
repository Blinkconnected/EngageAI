"""Global Search — fans one query term out across every entity type the
caller is actually allowed to read. See
``docs/architecture/global-search.md``.

Permission handling is the whole reason this is a service and not a bare
endpoint: unlike every other list endpoint (each gated by exactly one
``require_permission`` on the route), one search request spans nine
entity types with nine different permissions. Gating the *route* on any
single one of them would 403 an agent who legitimately can't read
workflows but can read customers. Instead the route requires only
authentication, and this service filters per entity type against the
caller's own permission set — so a caller only ever sees results from
the types they could already open directly.
"""

from dataclasses import dataclass
from uuid import UUID

from blinkengage.infrastructure.repositories.search_repository import (
    SearchHit,
    SearchRepository,
)

#: Per-entity-type cap. Global search is a "jump to the thing I'm
#: thinking of" affordance, not a report — a type with more matches than
#: this is a signal the caller should open that entity's own filtered
#: list page (which does paginate), not scroll a palette.
DEFAULT_PER_TYPE_LIMIT = 5

#: Below this, an ILIKE '%a%' across nine tables matches nearly
#: everything while telling the caller nothing — enforced here (not only
#: in the UI) so a direct API caller can't trigger the expensive
#: full-scan fan-out with a single character either.
MIN_QUERY_LENGTH = 2


@dataclass(frozen=True, slots=True)
class _Searchable:
    entity_type: str
    permission: str
    method_name: str


#: Order here is the order results are returned in, and the order the UI
#: renders type groups in — most-frequently-jumped-to first.
_SEARCHABLES: tuple[_Searchable, ...] = (
    _Searchable("conversation", "conversations.read", "search_conversations"),
    _Searchable("customer", "customers.read", "search_customers"),
    _Searchable("agent", "agents.read", "search_agents"),
    _Searchable("knowledge_article", "knowledge_base.read", "search_knowledge_articles"),
    _Searchable("knowledge_category", "knowledge_base.read", "search_knowledge_categories"),
    _Searchable("quick_reply", "quick_replies.read", "search_quick_replies"),
    _Searchable("team", "teams.read", "search_teams"),
    _Searchable("queue", "queues.read", "search_queues"),
    _Searchable("workflow", "workflows.read", "search_workflows"),
)


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    hits: list[SearchHit]
    searched_entity_types: list[str]


class SearchService:
    def __init__(self, *, search: SearchRepository) -> None:
        self._search = search

    async def search(
        self,
        *,
        company_id: UUID,
        term: str,
        permissions: frozenset[str],
        per_type_limit: int = DEFAULT_PER_TYPE_LIMIT,
    ) -> SearchOutcome:
        normalized = term.strip()
        if len(normalized) < MIN_QUERY_LENGTH:
            return SearchOutcome(hits=[], searched_entity_types=[])

        allowed = [s for s in _SEARCHABLES if s.permission in permissions]
        if not allowed:
            return SearchOutcome(hits=[], searched_entity_types=[])

        # Sequential, not asyncio.gather: every branch shares this
        # request's single AsyncSession, and a SQLAlchemy AsyncSession is
        # explicitly not safe for concurrent use — gathering here would
        # interleave statements on one connection and raise
        # InterfaceError under load. Nine capped, indexed-company-scoped
        # queries in sequence is the correct trade for that safety; see
        # docs/architecture/global-search.md on why the per-type limit
        # and minimum query length matter more than parallelism here.
        results: list[SearchHit] = []
        for searchable in allowed:
            method = getattr(self._search, searchable.method_name)
            results.extend(
                await method(company_id=company_id, term=normalized, limit=per_type_limit)
            )

        return SearchOutcome(hits=results, searched_entity_types=[s.entity_type for s in allowed])


__all__ = ["DEFAULT_PER_TYPE_LIMIT", "MIN_QUERY_LENGTH", "SearchOutcome", "SearchService"]
