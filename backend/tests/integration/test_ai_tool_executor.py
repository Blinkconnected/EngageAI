"""The execution pipeline, end to end against a real database.

See ``docs/architecture/ai-tool-calling.md``.

Every test here is written from the attacker's side of the boundary: what
happens when the model asks for something it should not get. The model
itself is never involved — a ``ToolCall`` is constructed directly, which
is exactly what a compromised or confused model would emit, minus the
nondeterminism.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.ai_tools import (
    AiInvocation,
    ToolContext,
    ToolExecutionError,
    ToolExecutor,
    ToolServices,
)
from blinkengage.application.ai_tools.catalog import DEFAULT_REGISTRY
from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.department_service import DepartmentService
from blinkengage.application.services.knowledge_record_service import KnowledgeRecordService
from blinkengage.application.services.role_service import RoleService
from blinkengage.application.services.team_service import TeamService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.ai_tools import ToolCall, ToolResultStatus
from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, SystemRole
from blinkengage.infrastructure.cache.idempotency import IdempotencyStore
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.ai_action import AiActionLog, PendingAiAction
from blinkengage.infrastructure.database.models.department import Department
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.knowledge_record_repository import (
    KnowledgeRecordRepository,
)
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.team_repository import TeamRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository

OWNER_PERMISSIONS = DEFAULT_ROLE_PERMISSIONS[SystemRole.OWNER]


def _services(session, container) -> ToolServices:
    events = OutboxEventPublisher(EventOutboxRepository(session))
    return ToolServices(
        departments=DepartmentService(
            departments=DepartmentRepository(session),
            agents=AgentRepository(session),
            events=events,
        ),
        teams=TeamService(
            teams=TeamRepository(session),
            agents=AgentRepository(session),
            events=events,
        ),
        agents=AgentService(
            session=session,
            settings=container.settings(),
            agents=AgentRepository(session),
            users=UserRepository(session),
            roles=RoleRepository(session),
            companies=CompanyRepository(session),
            events=events,
            refresh_tokens=RefreshTokenStore(container.redis()),
        ),
        roles=RoleService(roles=RoleRepository(session), events=events),
        knowledge_records=KnowledgeRecordService(
            records=KnowledgeRecordRepository(session), events=events
        ),
    )


def _ctx(session, container, *, company_id: UUID, user_id: UUID, permissions=None) -> ToolContext:
    return ToolContext(
        auth=AuthContext(
            user_id=user_id,
            company_id=company_id,
            permissions=frozenset(OWNER_PERMISSIONS if permissions is None else permissions),
        ),
        services=_services(session, container),
        correlation_id="test-correlation",
    )


def _executor(session, fake_redis) -> ToolExecutor:
    return ToolExecutor(
        registry=DEFAULT_REGISTRY, session=session, idempotency=IdempotencyStore(fake_redis)
    )


def _call(name: str, arguments: dict, call_id: str | None = None) -> ToolCall:
    return ToolCall(id=call_id or str(uuid4()), name=name, arguments=arguments)


async def _identity(client: AsyncClient, headers: dict) -> tuple[UUID, UUID]:
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return UUID(me["company"]["id"]), UUID(me["id"])


# --- rejection paths ------------------------------------------------------


async def test_unknown_tool_is_rejected(client, owner_headers, app, fake_redis) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("delete_company", {}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert "Unknown tool" in result.content["error"]


async def test_malformed_arguments_are_rejected(client, owner_headers, app, fake_redis) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("create_department", {"name": ""}),  # violates min_length
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert result.content["error"] == "Invalid arguments"
    assert result.content["details"], "the model must be told which field was wrong"


async def test_extra_arguments_are_rejected(client, owner_headers, app, fake_redis) -> None:
    """``extra='forbid'``. A field nobody declared is a field nobody
    reviewed, whatever it happens to be called."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("create_department", {"name": "Support", "is_admin": True}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert any("is_admin" in detail["field"] for detail in result.content["details"])


@pytest.mark.parametrize("injected", ["company_id", "user_id", "permission", "actor_user_id"])
async def test_identity_injection_is_rejected(
    client, owner_headers, app, fake_redis, injected: str
) -> None:
    """The model may not supply who it is or what it may do.

    These are not merely ignored — they are refused, so an attempt is
    visible rather than silently discarded.
    """
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("create_department", {"name": "Support", injected: str(uuid4())}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert any(injected in detail["field"] for detail in result.content["details"])


async def test_unauthorized_tool_is_rejected(client, owner_headers, app, fake_redis) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("create_department", {"name": "Support"}),
            ctx=_ctx(
                session,
                app.state.container,
                company_id=company_id,
                user_id=user_id,
                permissions={"departments.read"},  # can look, cannot create
            ),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert "departments.manage" in result.content["error"]

    async with app.state.container.session_factory()() as session:
        count = (await session.execute(select(Department))).scalars().all()
    assert count == [], "a refused tool must not have created anything"


async def test_cross_tenant_access_is_rejected(client, owner_headers, app, fake_redis) -> None:
    """Scope comes from the context, so a tool run in company B's context
    cannot see company A's data even with A's ids to hand."""
    company_a, user_a = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call("create_department", {"name": "Company A Only"}),
            ctx=_ctx(session, app.state.container, company_id=company_a, user_id=user_a),
            invocation=AiInvocation(),
        )
        await session.commit()

    registered_b = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company B",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b-tools@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    headers_b = {"Authorization": f"Bearer {registered_b.json()['tokens']['access_token']}"}
    company_b, user_b = await _identity(client, headers_b)

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("list_departments", {}),
            ctx=_ctx(session, app.state.container, company_id=company_b, user_id=user_b),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.OK
    assert result.content["total"] == 0
    assert result.content["departments"] == []


# --- the happy path, audited ---------------------------------------------


async def test_successful_action_runs_and_is_audited(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("create_department", {"name": "Technical Support"}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(
                user_request="Create a Technical Support team.",
                model_identifier="openai:gpt-4o-mini",
                correlation_id="corr-1",
            ),
        )
        await session.commit()

    assert result.status is ToolResultStatus.OK
    assert result.content["name"] == "Technical Support"

    async with app.state.container.session_factory()() as session:
        log = (
            await session.execute(select(AiActionLog).where(AiActionLog.result == "ok"))
        ).scalar_one()

    assert log.company_id == company_id
    assert log.actor_user_id == user_id
    assert log.tool_name == "create_department"
    assert log.validated_input["name"] == "Technical Support"
    assert log.before_state is None, "nothing existed before"
    assert log.after_state["name"] == "Technical Support"
    assert log.user_request == "Create a Technical Support team."
    assert log.model_identifier == "openai:gpt-4o-mini"
    assert log.correlation_id == "corr-1"


async def test_refusals_are_audited_too(client, owner_headers, app, fake_redis) -> None:
    """A model repeatedly attempting what it may not do is the pattern
    worth being able to find later."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call("create_department", {"name": "Nope"}),
            ctx=_ctx(
                session,
                app.state.container,
                company_id=company_id,
                user_id=user_id,
                permissions={"departments.read"},
            ),
            invocation=AiInvocation(),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        log = (await session.execute(select(AiActionLog))).scalar_one()
    assert log.result == "error"
    assert log.error_detail == "permission_denied"


async def test_secrets_never_reach_the_audit_record(client, owner_headers, app, fake_redis) -> None:
    """No tool declares a secret argument — the registry refuses one — so
    this checks the whole recorded row for anything that looks like a
    credential, which is the property that actually matters."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call("create_department", {"name": "Support"}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(user_request="make support"),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        log = (await session.execute(select(AiActionLog))).scalar_one()

    serialized = repr(
        [log.validated_input, log.before_state, log.after_state, log.user_request]
    ).lower()
    for forbidden in ("password", "hashed", "token", "secret", "api_key", "credential"):
        assert forbidden not in serialized


async def test_a_replayed_tool_call_is_idempotent(client, owner_headers, app, fake_redis) -> None:
    """Same call id twice creates one department, not two."""
    company_id, user_id = await _identity(client, owner_headers)
    call_id = str(uuid4())

    for _ in range(2):
        async with app.state.container.session_factory()() as session:
            result = await _executor(session, fake_redis).execute(
                _call("create_department", {"name": "Billing"}, call_id=call_id),
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
            await session.commit()
        assert result.status is ToolResultStatus.OK

    async with app.state.container.session_factory()() as session:
        departments = (await session.execute(select(Department))).scalars().all()
    assert len(departments) == 1


# --- confirmation ---------------------------------------------------------


async def _seed_agent_and_role(client: AsyncClient, owner_headers: dict) -> tuple[UUID, UUID]:
    created = await client.post(
        "/api/v1/agents",
        json={
            "email": "tool-agent@acme.example",
            "full_name": "Tool Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    roles = (await client.get("/api/v1/roles", headers=owner_headers)).json()
    items = roles["items"] if isinstance(roles, dict) else roles
    admin = next(r for r in items if r["name"] == "Admin")
    return UUID(created.json()["id"]), UUID(admin["id"])


async def test_high_impact_action_requires_confirmation(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    agent_id, role_id = await _seed_agent_and_role(client, owner_headers)

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call(
                "change_agent_role",
                {"target_agent_id": str(agent_id), "role_id": str(role_id)},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(user_request="make them an admin"),
        )
        await session.commit()

    assert result.status is ToolResultStatus.CONFIRMATION_REQUIRED
    assert "pending_action_id" in result.content

    async with app.state.container.session_factory()() as session:
        pending = (await session.execute(select(PendingAiAction))).scalar_one()
        assert pending.consumed_at is None
        # The summary is built from validated arguments, never from model prose.
        assert "change_agent_role" in pending.summary


async def test_a_fabricated_confirmation_is_rejected(
    client, owner_headers, app, fake_redis
) -> None:
    """A model cannot assert that a user approved something."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as exc:
            await _executor(session, fake_redis).confirm(
                uuid4(),
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
    assert exc.value.reason == "not_found"


async def test_an_expired_confirmation_is_rejected(client, owner_headers, app, fake_redis) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    agent_id, role_id = await _seed_agent_and_role(client, owner_headers)

    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call(
                "change_agent_role",
                {"target_agent_id": str(agent_id), "role_id": str(role_id)},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        pending = (await session.execute(select(PendingAiAction))).scalar_one()
        pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        pending_id = pending.id

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as exc:
            await _executor(session, fake_redis).confirm(
                pending_id,
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
    assert exc.value.reason == "expired"


async def test_a_consumed_confirmation_cannot_run_twice(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    agent_id, role_id = await _seed_agent_and_role(client, owner_headers)

    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call(
                "change_agent_role",
                {"target_agent_id": str(agent_id), "role_id": str(role_id)},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()
        pending_id = (await session.execute(select(PendingAiAction))).scalar_one().id

    async with app.state.container.session_factory()() as session:
        first = await _executor(session, fake_redis).confirm(
            pending_id,
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()
    assert first.status is ToolResultStatus.OK

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as exc:
            await _executor(session, fake_redis).confirm(
                pending_id,
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
    assert exc.value.reason == "consumed"


async def test_state_changed_after_proposal_is_rejected(
    client, owner_headers, app, fake_redis
) -> None:
    """The human approved a diff. If the world moved underneath it, that
    diff no longer describes what would happen."""
    company_id, user_id = await _identity(client, owner_headers)
    agent_id, admin_role_id = await _seed_agent_and_role(client, owner_headers)

    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call(
                "change_agent_role",
                {"target_agent_id": str(agent_id), "role_id": str(admin_role_id)},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()
        pending_id = (await session.execute(select(PendingAiAction))).scalar_one().id

    # Somebody else moves the agent while the dialog is open. Promoting
    # them to Admin by hand is a genuine change away from the state the
    # proposal was priced against (a new agent starts on Agent), which is
    # what makes this a real staleness check rather than a no-op edit.
    changed = await client.put(
        f"/api/v1/agents/{agent_id}/role",
        json={"role_id": str(admin_role_id)},
        headers=owner_headers,
    )
    assert changed.status_code == 200, changed.text

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as exc:
            await _executor(session, fake_redis).confirm(
                pending_id,
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
    assert exc.value.reason == "stale"


async def test_confirmation_rechecks_permission(client, owner_headers, app, fake_redis) -> None:
    """Ten minutes is long enough to lose a role."""
    company_id, user_id = await _identity(client, owner_headers)
    agent_id, role_id = await _seed_agent_and_role(client, owner_headers)

    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call(
                "change_agent_role",
                {"target_agent_id": str(agent_id), "role_id": str(role_id)},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()
        pending_id = (await session.execute(select(PendingAiAction))).scalar_one().id

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as exc:
            await _executor(session, fake_redis).confirm(
                pending_id,
                ctx=_ctx(
                    session,
                    app.state.container,
                    company_id=company_id,
                    user_id=user_id,
                    permissions={"ai.use"},
                ),
                invocation=AiInvocation(),
            )
    assert exc.value.reason == "permission_denied"


async def test_confirmation_from_another_company_is_not_found(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    agent_id, role_id = await _seed_agent_and_role(client, owner_headers)

    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).execute(
            _call(
                "change_agent_role",
                {"target_agent_id": str(agent_id), "role_id": str(role_id)},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()
        pending_id = (await session.execute(select(PendingAiAction))).scalar_one().id

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as exc:
            await _executor(session, fake_redis).confirm(
                pending_id,
                ctx=_ctx(session, app.state.container, company_id=uuid4(), user_id=user_id),
                invocation=AiInvocation(),
            )
    assert exc.value.reason == "not_found"
