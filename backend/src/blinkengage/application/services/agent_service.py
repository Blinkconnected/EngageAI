"""Agent service — creates a new ``User`` + ``Agent`` profile together.

Inviting a teammate (as opposed to `AuthService.register_company`, which
creates a brand-new company) adds a login identity to an *existing*
company and immediately grants it the company's default "Agent" role.

Two ways to set the new agent's password (see
``docs/architecture/company-onboarding.md``):

- The caller supplies ``password`` directly (the original, still-
  supported behavior — an Owner/Admin sets it themselves and
  communicates it out of band).
- The caller omits ``password`` (the Company Onboarding Wizard's "Invite
  Agents" step): a random one is generated and emailed to the agent over
  the platform's own SMTP relay, the same one
  ``notification_email_dispatch_task`` already uses — reusing existing
  infrastructure for a new purpose, not a new integration.

Either way the agent can change their password later from their own
profile once logged in.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.config import Settings
from blinkengage.core.logging import get_logger
from blinkengage.core.security import generate_temporary_password, hash_password
from blinkengage.domain.company_settings import min_password_length
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    WeakPasswordError,
)
from blinkengage.domain.rbac import SystemRole
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.rbac import UserRole
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.email.mailer import send_plain_email
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository

logger = get_logger(__name__)


class AgentService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        settings: Settings,
        agents: AgentRepository,
        users: UserRepository,
        roles: RoleRepository,
        companies: CompanyRepository,
        events: DomainEventPublisher,
        refresh_tokens: RefreshTokenStore,
    ) -> None:
        self._session = session
        self._settings = settings
        self._agents = agents
        self._users = users
        self._roles = roles
        self._companies = companies
        self._events = events
        self._refresh_tokens = refresh_tokens

    async def create(
        self,
        *,
        company_id: UUID,
        email: str,
        full_name: str,
        password: str | None,
        title: str | None,
        department_id: UUID | None,
        actor_user_id: UUID | None = None,
    ) -> Agent:
        normalized_email = email.strip().lower()
        if await self._users.get_by_email(normalized_email) is not None:
            raise EntityAlreadyExistsError("User", "email", normalized_email)

        company = await self._companies.get_by_id(company_id)
        required_length = min_password_length(company.settings) if company is not None else None

        invited_by_email = password is None
        resolved_password: str
        if password is None:
            resolved_password = generate_temporary_password(max(required_length or 0, 16))
        else:
            resolved_password = password
            if required_length is not None and len(resolved_password) < required_length:
                raise WeakPasswordError(required_length)

        user = await self._users.add(
            User(
                company_id=company_id,
                email=normalized_email,
                hashed_password=hash_password(resolved_password),
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
        await self._events.publish(
            DomainEvent(
                event_type="agent.created",
                company_id=company_id,
                aggregate_type="agent",
                aggregate_id=reloaded.id,
                actor_user_id=actor_user_id,
                payload={"email": normalized_email},
            )
        )

        if invited_by_email:
            company_name = company.name if company is not None else "Blink Engage"
            try:
                await send_plain_email(
                    self._settings,
                    to_address=normalized_email,
                    subject=f"You've been added to {company_name} on Blink Engage",
                    body=(
                        f"Hi {full_name.strip()},\n\n"
                        f"You've been added as an agent on {company_name}'s Blink Engage "
                        "workspace. Sign in with the credentials below, then change your "
                        "password from your profile.\n\n"
                        f"Email: {normalized_email}\n"
                        f"Temporary password: {resolved_password}\n"
                    ),
                )
            except Exception:
                # Best-effort: the account is created either way — a
                # down/misconfigured SMTP relay must not prevent adding
                # the agent, only the welcome email. Same reasoning as
                # notification_email_dispatch_task's per-recipient
                # failure handling.
                logger.warning(
                    "agent_invite_email_failed", agent_id=str(reloaded.id), exc_info=True
                )

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
        actor_user_id: UUID | None = None,
    ) -> Agent:
        agent = await self.get(company_id=company_id, agent_id=agent_id)
        if title is not None:
            agent.title = title
        if department_id is not None:
            agent.department_id = department_id
        if status is not None:
            agent.status = status
        await self._events.publish(
            DomainEvent(
                event_type="agent.updated",
                company_id=company_id,
                aggregate_type="agent",
                aggregate_id=agent.id,
                actor_user_id=actor_user_id,
                payload={"status": agent.status.value},
            )
        )
        return agent

    async def reset_password(
        self,
        *,
        company_id: UUID,
        agent_id: UUID,
        new_password: str,
        actor_user_id: UUID | None = None,
    ) -> None:
        """Owner/Admin-initiated reset (``agents.manage``) — no current
        password required, unlike the agent's own self-service change
        (``AuthService.change_password``). All of the agent's existing
        sessions are revoked: their password just changed without their
        involvement, so any refresh token issued under the old one
        shouldn't outlive it."""
        agent = await self.get(company_id=company_id, agent_id=agent_id)
        company = await self._companies.get_by_id(company_id)
        if company is not None:
            required_length = min_password_length(company.settings)
            if len(new_password) < required_length:
                raise WeakPasswordError(required_length)
        agent.user.hashed_password = hash_password(new_password)
        await self._refresh_tokens.revoke_all_for_user(user_id=agent.user_id)
        await self._events.publish(
            DomainEvent(
                event_type="agent.password_reset",
                company_id=company_id,
                aggregate_type="agent",
                aggregate_id=agent.id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )

    async def delete(
        self, *, company_id: UUID, agent_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        agent = await self.get(company_id=company_id, agent_id=agent_id)
        await self._agents.soft_delete(agent)
        await self._events.publish(
            DomainEvent(
                event_type="agent.deleted",
                company_id=company_id,
                aggregate_type="agent",
                aggregate_id=agent.id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )
