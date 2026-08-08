"""Global Search — one lean query per entity type. See
``docs/architecture/global-search.md``.

Deliberately **not** built by calling each entity's own paginated
``list_for_company(search=...)``, even though four of them already accept
a ``search`` param and reusing them would be the obvious "reuse existing
backend functionality" reading. Those methods are built for a full list
page, and fanning out across all of them per keystroke would mean:

* Twice the queries — each one also runs a separate ``COUNT(*)`` over the
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
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.department import Department
from blinkengage.infrastructure.database.models.faq import Faq
from blinkengage.infrastructure.database.models.knowledge import (
    KnowledgeArticle,
    KnowledgeCategory,
)
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.quick_reply import QuickReply
from blinkengage.infrastructure.database.models.rbac import Role
from blinkengage.infrastructure.database.models.service_directory import Service
from blinkengage.infrastructure.database.models.sla import SlaPolicy
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

    @staticmethod
    def _snippet(body: str, *, length: int = 120) -> str:
        """A one-line preview of long-form text.

        FAQ answers run to paragraphs. Sent whole they would push the
        result list off the screen, and their newlines would break the
        single-line layout every other result type uses, so they are
        flattened and cut here rather than in each caller.
        """
        flattened = " ".join(body.split())
        if len(flattened) <= length:
            return flattened
        return flattened[:length].rstrip() + "…"

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

    async def search_departments(
        self, *, company_id: UUID, term: str, limit: int
    ) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Department.id, Department.name, Department.description)
            .where(
                Department.company_id == company_id,
                Department.deleted_at.is_(None),
                or_(Department.name.ilike(pattern), Department.description.ilike(pattern)),
            )
            .order_by(Department.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="department", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]

    async def search_services(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Service.id, Service.name, Service.code, Service.description)
            .where(
                Service.company_id == company_id,
                Service.deleted_at.is_(None),
                # Code as well as name: routing rules and integrations
                # refer to services by code, so that is what somebody
                # arrives with when they are tracing where a rule points.
                or_(
                    Service.name.ilike(pattern),
                    Service.code.ilike(pattern),
                    Service.description.ilike(pattern),
                ),
            )
            .order_by(Service.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="service", id=row[0], title=row[1], subtitle=row[3] or row[2])
            for row in result.all()
        ]

    async def search_sla_policies(
        self, *, company_id: UUID, term: str, limit: int
    ) -> list[SearchHit]:
        # No soft-delete column on this model, unlike most of the others.
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(SlaPolicy.id, SlaPolicy.name, SlaPolicy.description)
            .where(
                SlaPolicy.company_id == company_id,
                or_(SlaPolicy.name.ilike(pattern), SlaPolicy.description.ilike(pattern)),
            )
            .order_by(SlaPolicy.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="sla_policy", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]

    async def search_channels(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(ChannelConfig.id, ChannelConfig.display_name, ChannelConfig.channel_type)
            .where(
                ChannelConfig.company_id == company_id,
                ChannelConfig.deleted_at.is_(None),
                # Type as well as name, so somebody searching "whatsapp"
                # finds the channel whoever set it up called "Main line".
                or_(
                    ChannelConfig.display_name.ilike(pattern),
                    ChannelConfig.channel_type.ilike(pattern),
                ),
            )
            .order_by(ChannelConfig.display_name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="channel", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]

    async def search_faqs(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        """Both the question and the answer.

        A customer's wording rarely matches the question as written, and
        the distinguishing words are often only in the answer — a product
        name, a price, a place. Searching the question alone would miss
        the FAQ that answers exactly what was asked.

        Unpublished FAQs are included rather than filtered out: an
        administrator searching their own knowledge needs to find the
        draft they are part-way through writing. Published ones come
        first, so what customers can actually see outranks what is still
        being drafted when the per-type cap bites.
        """
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Faq.id, Faq.question, Faq.answer)
            .where(
                Faq.company_id == company_id,
                Faq.deleted_at.is_(None),
                or_(Faq.question.ilike(pattern), Faq.answer.ilike(pattern)),
            )
            .order_by(Faq.is_published.desc(), Faq.question)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="faq", id=row[0], title=row[1], subtitle=self._snippet(row[2]))
            for row in result.all()
        ]

    async def search_roles(self, *, company_id: UUID, term: str, limit: int) -> list[SearchHit]:
        """Gated on ``roles.manage`` — there is no ``roles.read``.

        That is stricter than the other configuration types on purpose. A
        list of role names is a sketch of how the company delegates
        authority, which is not something an agent needs and not
        something to hand out through a search box.
        """
        # No soft-delete column on this model.
        pattern = self._pattern(term)
        result = await self._session.execute(
            select(Role.id, Role.name, Role.description)
            .where(
                Role.company_id == company_id,
                or_(Role.name.ilike(pattern), Role.description.ilike(pattern)),
            )
            .order_by(Role.name)
            .limit(limit)
        )
        return [
            SearchHit(entity_type="role", id=row[0], title=row[1], subtitle=row[2])
            for row in result.all()
        ]
