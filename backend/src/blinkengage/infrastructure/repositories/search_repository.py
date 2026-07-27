"""Global Search — one lean query per entity type. See
``docs/architecture/global-search.md``.

Deliberately **not** built by calling each entity's own paginated
``list_for_company(search=...)``, even though four of them already accept
a ``search`` param and reusing them would be the obvious "reuse existing
backend functionality" reading. Those methods are built for a full list
page, and fanning out across 8 of them per keystroke would mean:

* 16 queries, not 8 — each one also runs a separate ``COUNT(*)`` over the
  same filtered subquery to populate ``Page.total``, which global search
  never displays (it shows "top N per type", not "1 of 4,213").
* Eager loads global search doesn't need — ``CustomerRepository`` pulls
  ``customer_tags -> tag``, ``AgentRepository`` pulls ``user`` +
  ``department`` + ``team_memberships -> team``, ``TeamRepository`` pulls
  its members.

What *is* reused is the convention, exactly: the same ``search`` param
name, the same ``f"%{term}%"`` + ``ilike`` idiom, the same company
scoping and ``deleted_at IS NULL`` filters, and the same searchable
columns each entity's own list endpoint already searches — so a global
search hit and that entity's own filtered list can never disagree about
what matches.

Every method caps its own result count (``limit``) and returns plain
rows, never ORM objects with lazy relationships, so nothing here can
trigger an N+1 on serialization.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.agent import Agent
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.knowledge import (
    KnowledgeArticle,
    KnowledgeCategory,
)
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.quick_reply import QuickReply
from blinkengage.infrastructure.database.models.team import Team
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.database.models.workflow import WorkflowDefinition


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One result, normalized across every entity type. ``entity_type``
    is the same string the API and frontend key off (see
    ``api/schemas/search.py``'s ``SearchEntityType``)."""

    entity_type: str
    id: UUID
    title: str
    subtitle: str | None


class SearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _pattern(term: str) -> str:
        return f"%{term}%"

    async def search_customers(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Customer.id, Customer.full_name, Customer.email, Customer.phone)
            .where(
                Customer.company_id == company_id,
                Customer.deleted_at.is_(None),
                or_(
                    Customer.full_name.ilike(pattern),
                    Customer.email.ilike(pattern),
                    Customer.phone.ilike(pattern),
                ),
            )
            .order_by(Customer.full_name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="customer", id=row[0], title=row[1], subtitle=row[2] or row[3])
            for row in result.all()
        ]

    async def search_agents(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Agent.id, User.full_name, User.email, Agent.title)
            .join(User, User.id == Agent.user_id)
            .where(
                Agent.company_id == company_id,
                Agent.deleted_at.is_(None),
                or_(
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                    Agent.title.ilike(pattern),
                ),
            )
            .order_by(User.full_name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="agent", id=row[0], title=row[1], subtitle=row[3] or row[2])
            for row in result.all()
        ]

    async def search_conversations(
        self, *, company_id: UUID, term: str, limit: int
    ) -> list[SearchHit]:
        """A ``Conversation`` has no title/subject column of its own, so
        it's matched (and labelled) through its customer — the same way
        the Inbox already identifies a conversation to an agent. Its own
        ``GET /conversations`` has no ``search`` param at all today; this
        is the only place conversations are text-searchable."""
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Conversation.id, Customer.full_name, Conversation.status)
            .join(Customer, Customer.id == Conversation.customer_id)
            .where(
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
                or_(Customer.full_name.ilike(pattern), Customer.email.ilike(pattern)),
            )
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )
        return [
            SearchHit(
                entity_type="conversation",
                id=row[0],
                title=row[1],
                subtitle=row[2].value if row[2] is not None else None,
            )
            for row in result.all()
        ]

    async def search_knowledge_articles(
        self, *, company_id: UUID, term: str, limit: int
    ) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(KnowledgeArticle.id, KnowledgeArticle.title, KnowledgeArticle.is_published)
            .where(
                KnowledgeArticle.company_id == company_id,
                KnowledgeArticle.deleted_at.is_(None),
                or_(
                    KnowledgeArticle.title.ilike(pattern),
                    KnowledgeArticle.body.ilike(pattern),
                ),
            )
            .order_by(KnowledgeArticle.title)
            .limit(limit)
        )
        return [
            SearchHit(
                entity_type="knowledge_article",
                id=row[0],
                title=row[1],
                subtitle="published" if row[2] else "draft",
            )
            for row in result.all()
        ]

    async def search_knowledge_categories(
        self, *, company_id: UUID, term: str, limit: int
    ) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(KnowledgeCategory.id, KnowledgeCategory.name)
            .where(
                KnowledgeCategory.company_id == company_id,
                KnowledgeCategory.deleted_at.is_(None),
                KnowledgeCategory.name.ilike(pattern),
            )
            .order_by(KnowledgeCategory.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="knowledge_category", id=row[0], title=row[1], subtitle=None)
            for row in result.all()
        ]

    async def search_quick_replies(
        self, *, company_id: UUID, term: str, limit: int
    ) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(QuickReply.id, QuickReply.title, QuickReply.shortcut)
            .where(
                QuickReply.company_id == company_id,
                QuickReply.deleted_at.is_(None),
                or_(QuickReply.shortcut.ilike(pattern), QuickReply.title.ilike(pattern)),
            )
            .order_by(QuickReply.shortcut)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="quick_reply", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]

    async def search_teams(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Team.id, Team.name, Team.description)
            .where(
                Team.company_id == company_id,
                Team.deleted_at.is_(None),
                or_(Team.name.ilike(pattern), Team.description.ilike(pattern)),
            )
            .order_by(Team.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="team", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]

    async def search_queues(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Queue.id, Queue.name, Queue.description)
            .where(
                Queue.company_id == company_id,
                Queue.deleted_at.is_(None),
                or_(Queue.name.ilike(pattern), Queue.description.ilike(pattern)),
            )
            .order_by(Queue.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="queue", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]

    async def search_workflows(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(
                WorkflowDefinition.id,
                WorkflowDefinition.name,
                WorkflowDefinition.trigger_event_type,
            )
            .where(
                WorkflowDefinition.company_id == company_id,
                WorkflowDefinition.deleted_at.is_(None),
                or_(
                    WorkflowDefinition.name.ilike(pattern),
                    WorkflowDefinition.description.ilike(pattern),
                ),
            )
            .order_by(WorkflowDefinition.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="workflow", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]
