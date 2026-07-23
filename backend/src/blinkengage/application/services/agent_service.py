"""Agent service — creates a new ``User`` + ``Agent`` profile together.

Inviting a teammate (as opposed to `AuthService.register_company`, which
creates a brand-new company) adds a login identity to an *existing*
company and immediately grants it the company's default "Agent" role.
There is no email-invite flow yet (no notification infrastructure exists
until Phase 4) — the admin creating the agent sets an initial password
directly, which the agent can change later once a password-change
endpoint exists.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.security import hash_password
from blinkengage.domain.exceptions import EntityAlreadyExistsError, EntityNotFoundError
from blinkengage.domain.rbac import SystemRole
from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.rbac import UserRole
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository


class AgentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        agents: AgentRepository,
        users: UserRepository,
        roles: RoleRepository,
    ) -> None:
        self._session = session
        self._agents = agents
        self._users = users
        self._roles = roles

    async def create(
        self,
        *,
        company_id: UUID,
        email: str,
        full_name: str,
        password: str,
        title: str | None,
        department_id: UUID | None,
    ) -> Agent:
        normalized_email = email.strip().lower()
        if await self._users.get_by_email(normalized_email) is not None:
            raise EntityAlreadyExistsError("User", "email", normalized_email)

        user = await self._users.add(
            User(
                company_id=company_id,
                email=normalized_email,
                hashed_password=hash_password(password),
                full_name=full_name.strip(),
                is_company_owner=False,
            )
        )

        agent_role = await self._roles.get_by_name(company_id=company_id, name=SystemRole.AGENT)
        if agent_role is None:
            raise EntityNotFoundError("Role", SystemRole.AGENT.value)
        self._session.add(UserRole(user_id=user.id, role_id=agent_role.id))

        agent = await self._agents.add(
            Agent(
                company_id=company_id,
                user_id=user.id,
                department_id=department_id,
                title=title,
                status=AgentStatus.OFFLINE,
            )
        )
        await self._session.flush()

        reloaded = await self._agents.get_by_id(company_id=company_id, agent_id=agent.id)
        assert reloaded is not None
        return reloaded

    async def get(self, *, company_id: UUID, agent_id: UUID) -> Agent:
        agent = await self._agents.get_by_id(company_id=company_id, agent_id=agent_id)
        if agent is None:
            raise EntityNotFoundError("Agent", agent_id)
        return agent

    async def list_agents(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Agent], int]:
        return await self._agents.list_for_company(
            company_id=company_id, offset=offset, limit=limit
        )

    async def update(
        self,
        *,
        company_id: UUID,
        agent_id: UUID,
        title: str | None,
        department_id: UUID | None,
        status: AgentStatus | None,
    ) -> Agent:
        agent = await self.get(company_id=company_id, agent_id=agent_id)
        if title is not None:
            agent.title = title
        if department_id is not None:
            agent.department_id = department_id
        if status is not None:
            agent.status = status
        return agent

    async def delete(self, *, company_id: UUID, agent_id: UUID) -> None:
        agent = await self.get(company_id=company_id, agent_id=agent_id)
        await self._agents.soft_delete(agent)
