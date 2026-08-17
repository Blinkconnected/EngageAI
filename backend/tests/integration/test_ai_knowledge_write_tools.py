"""The four mutating knowledge tools, driven through the real pipeline.

Every test goes through ``ToolExecutor.execute`` and, where a change is
actually made, through ``ToolExecutor.confirm``. That is the point: the
handler is the small half, and what makes a publication safe is the parking
step, the re-authorisation, the staleness check and the gate around it.

The shape to notice throughout is that a mutation takes *two* calls with a
human in between, and that the first one changes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.ai_tools import (
    DEFAULT_REGISTRY,
    AiInvocation,
    ToolContext,
    ToolExecutionError,
    ToolExecutor,
    ToolServices,
)
from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.department_service import DepartmentService
from blinkengage.application.services.knowledge_record_service import KnowledgeRecordService
from blinkengage.application.services.role_service import RoleService
from blinkengage.application.services.team_service import TeamService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.ai_tools import ToolCall, ToolResultStatus
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
    KnowledgeRecordType,
)
from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, SystemRole
from blinkengage.infrastructure.cache.idempotency import IdempotencyStore
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.knowledge_record import KnowledgeRecord
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


def _records(session: Any) -> KnowledgeRecordService:
    return KnowledgeRecordService(
        records=KnowledgeRecordRepository(session),
        events=OutboxEventPublisher(EventOutboxRepository(session)),
    )


def _services(session: Any, container: Any) -> ToolServices:
    events = OutboxEventPublisher(EventOutboxRepository(session))
    return ToolServices(
        departments=DepartmentService(
            departments=DepartmentRepository(session),
            agents=AgentRepository(session),
            events=events,
        ),
        teams=TeamService(
            teams=TeamRepository(session), agents=AgentRepository(session), events=events
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
        knowledge_records=_records(session),
    )


def _ctx(
    session: Any,
    container: Any,
    *,
    company_id: UUID,
    user_id: UUID,
    permissions: frozenset[str] | None = None,
) -> ToolContext:
    return ToolContext(
        auth=AuthContext(
            user_id=user_id,
            company_id=company_id,
            permissions=OWNER_PERMISSIONS if permissions is None else permissions,
        ),
        services=_services(session, container),
        correlation_id="test-correlation",
    )


def _executor(session: Any, fake_redis: Any) -> ToolExecutor:
    return ToolExecutor(
        registry=DEFAULT_REGISTRY, session=session, idempotency=IdempotencyStore(fake_redis)
    )


def _call(name: str, arguments: dict[str, Any], call_id: str | None = None) -> ToolCall:
    return ToolCall(id=call_id or str(uuid4()), name=name, arguments=arguments)


async def _identity(client: AsyncClient, headers: dict[str, str]) -> tuple[UUID, UUID]:
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return UUID(me["company"]["id"]), UUID(me["id"])


def _iso(days: int = -30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


PROPOSAL: dict[str, Any] = {
    "record_type": "PRICE",
    "subject_label": "DIA 500 Mbps",
    "attributes": {"amount": "180", "currency": "JOD"},
    "effective_from": _iso(),
    "source_reference": "Price list 2026-01, approved by Finance",
}


async def _seed(
    session: Any,
    *,
    company_id: UUID,
    subject_label: str = "DIA 500 Mbps",
    amount: str = "180",
    publish: bool = False,
    source_reference: str | None = "Price list 2026-01",
    access_level: KnowledgeAccessLevel = KnowledgeAccessLevel.PUBLIC_TO_AI,
) -> Any:
    service = _records(session)
    record = await service.create_draft(
        company_id=company_id,
        record_type=KnowledgeRecordType.PRICE,
        subject_label=subject_label,
        attributes={"amount": Decimal(amount), "currency": "JOD"},
        effective_from=datetime.now(UTC) - timedelta(days=30),
        access_level=access_level,
        source_reference=source_reference,
    )
    if publish:
        await service.publish(company_id=company_id, record_id=record.id)
    await session.flush()
    return record


async def _other_company(session: Any) -> UUID:
    company = Company(name="Rival Telecom", slug=f"rival-{uuid4().hex[:8]}")
    session.add(company)
    await session.flush()
    return company.id


async def _state_of(app: Any, company_id: UUID, record_id: UUID) -> str:
    async with app.state.container.session_factory()() as session:
        record = await session.get(KnowledgeRecord, record_id)
        assert record is not None
        assert record.company_id == company_id
        return str(record.lifecycle_state)


# ======================= propose_knowledge_update =======================


async def test_a_proposal_creates_a_draft_and_nothing_more(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("propose_knowledge_update", dict(PROPOSAL)),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    # No confirmation: a draft grants nothing, so making the model wait for a
    # human before it may *suggest* something would be friction with no
    # safety behind it.
    assert result.status is ToolResultStatus.OK
    assert result.content["proposed"]["lifecycle_state"] == "DRAFT"
    assert result.content["conflict"] == "NO_CONFLICT"
    assert "draft" in result.content["note"].lower()

    record_id = UUID(result.content["proposed"]["record_id"])
    assert await _state_of(app, company_id, record_id) == "DRAFT"


async def test_a_proposal_cannot_make_itself_authoritative(
    client, owner_headers, app, fake_redis
) -> None:
    """The property the whole draft-only design rests on."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("propose_knowledge_update", dict(PROPOSAL)),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    record_id = UUID(result.content["proposed"]["record_id"])
    async with app.state.container.session_factory()() as session:
        record = await session.get(KnowledgeRecord, record_id)
        assert record is not None
        assert record.lifecycle_state == KnowledgeLifecycleState.DRAFT
        assert record.approved_by_user_id is None, "nobody approved a draft"
        assert record.approved_at is None


async def test_a_proposal_needs_the_propose_permission(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    stripped = frozenset(OWNER_PERMISSIONS) - {"knowledge_records.propose"}
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("propose_knowledge_update", dict(PROPOSAL)),
            ctx=_ctx(
                session,
                app.state.container,
                company_id=company_id,
                user_id=user_id,
                permissions=stripped,
            ),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert result.content["error"] == "Missing required permission: knowledge_records.propose"


async def test_a_proposal_lands_in_the_callers_company(
    client, owner_headers, app, fake_redis
) -> None:
    """Tenant scope comes from the token. There is no argument to aim it
    somewhere else, so the only thing to assert is where it landed."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        rival = await _other_company(session)
        await session.commit()

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("propose_knowledge_update", dict(PROPOSAL)),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    record_id = UUID(result.content["proposed"]["record_id"])
    async with app.state.container.session_factory()() as session:
        record = await session.get(KnowledgeRecord, record_id)
        assert record is not None
        assert record.company_id == company_id
        assert record.company_id != rival


@pytest.mark.parametrize(
    "forged",
    [
        pytest.param({"company_id": str(uuid4())}, id="company_id"),
        pytest.param({"user_id": str(uuid4())}, id="user_id"),
        pytest.param({"approved_by_user_id": str(uuid4())}, id="approved_by_user_id"),
        pytest.param({"lifecycle_state": "ACTIVE"}, id="lifecycle_state"),
    ],
)
async def test_a_proposal_refuses_forged_identity_or_authority_fields(
    client, owner_headers, app, fake_redis, forged: dict[str, Any]
) -> None:
    """Refused, not ignored. A model that could set ``lifecycle_state`` would
    publish by naming a field."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("propose_knowledge_update", {**PROPOSAL, **forged}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert result.content["error"] == "Invalid arguments"


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"record_type": "INVENTED"}, id="unknown-type"),
        pytest.param({"subject_label": ""}, id="empty-subject"),
        pytest.param({"source_reference": ""}, id="empty-provenance"),
        pytest.param({"effective_from": "not-a-date"}, id="bad-date"),
        pytest.param({"attributes": "180 JOD"}, id="attributes-not-an-object"),
    ],
)
async def test_a_malformed_proposal_is_refused(
    client, owner_headers, app, fake_redis, override: dict[str, Any]
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("propose_knowledge_update", {**PROPOSAL, **override}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert result.content["error"] == "Invalid arguments"


async def test_a_proposal_with_attributes_the_type_rejects_is_a_domain_error(
    client, owner_headers, app, fake_redis
) -> None:
    """A PRICE without an amount is schema-valid JSON and invalid knowledge.
    The domain says so, and the model is told rather than the draft stored."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call(
                "propose_knowledge_update",
                {**PROPOSAL, "attributes": {"currency": "JOD"}},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR


# ======================= publish_knowledge_record =======================


async def test_publishing_parks_and_changes_nothing_yet(
    client, owner_headers, app, fake_redis
) -> None:
    """The first call is a proposal to a human, not an action."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert result.status is ToolResultStatus.CONFIRMATION_REQUIRED
    assert result.content["pending_action_id"]
    assert "cannot approve it yourself" in result.content["message"]
    assert await _state_of(app, company_id, record_id) == "DRAFT"


async def test_confirming_publishes_and_records_the_human_as_approver(
    client, owner_headers, app, fake_redis
) -> None:
    """``publication_gate`` requires an approver and this is where it comes
    from: the authenticated administrator who came back to confirm."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        executor = _executor(session, fake_redis)
        ctx = _ctx(session, app.state.container, company_id=company_id, user_id=user_id)
        parked = await executor.execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=ctx,
            invocation=AiInvocation(),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).confirm(
            UUID(parked.content["pending_action_id"]),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert result.status is ToolResultStatus.OK
    assert result.content["published"]["lifecycle_state"] == "ACTIVE"
    assert result.content["approved_by_user_id"] == str(user_id)

    async with app.state.container.session_factory()() as session:
        stored = await session.get(KnowledgeRecord, record_id)
        assert stored is not None
        # The approver on the row is the confirming human, not the model and
        # not a value that arrived in an argument.
        assert stored.approved_by_user_id == user_id
        assert stored.approved_at is not None


async def test_the_gate_refuses_a_record_with_no_provenance(
    client, owner_headers, app, fake_redis
) -> None:
    """``publication_gate``'s first refusal, reached through the tool. A price
    whose source nobody recorded is a number the platform cannot defend."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id, source_reference=None)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).confirm(
            UUID(parked.content["pending_action_id"]),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert result.status is ToolResultStatus.ERROR
    assert "MISSING_PROVENANCE" in result.content["error"]
    assert await _state_of(app, company_id, record_id) == "DRAFT"


async def test_the_gate_refuses_restricted_material(client, owner_headers, app, fake_redis) -> None:
    """``knowledge_records.approve_restricted`` is not a permission any role
    holds, so restricted knowledge cannot be published through the assistant
    at all. That is the safe direction, and it is the gate saying so."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(
            session, company_id=company_id, access_level=KnowledgeAccessLevel.RESTRICTED
        )
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).confirm(
            UUID(parked.content["pending_action_id"]),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert result.status is ToolResultStatus.ERROR
    assert "RESTRICTED_REQUIRES_APPROVAL_PERMISSION" in result.content["error"]
    assert await _state_of(app, company_id, record_id) == "DRAFT"


async def test_publishing_needs_the_publish_permission(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    stripped = frozenset(OWNER_PERMISSIONS) - {"knowledge_records.publish"}
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(
                session,
                app.state.container,
                company_id=company_id,
                user_id=user_id,
                permissions=stripped,
            ),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert result.content["error"] == "Missing required permission: knowledge_records.publish"
    assert await _state_of(app, company_id, record_id) == "DRAFT"


async def test_the_permission_is_rechecked_at_confirmation(
    client, owner_headers, app, fake_redis
) -> None:
    """Nothing is trusted twice. A role can change while a human reads the
    dialog, and an approval must be judged against authority held now."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as raised:
            await _executor(session, fake_redis).confirm(
                UUID(parked.content["pending_action_id"]),
                ctx=_ctx(
                    session,
                    app.state.container,
                    company_id=company_id,
                    user_id=user_id,
                    permissions=frozenset(OWNER_PERMISSIONS) - {"knowledge_records.publish"},
                ),
                invocation=AiInvocation(),
            )

    assert raised.value.reason == "permission_denied"
    assert await _state_of(app, company_id, record_id) == "DRAFT"


async def test_another_companys_record_cannot_be_published(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        rival = await _other_company(session)
        theirs = await _seed(session, company_id=rival, subject_label="Rival DIA 500 Mbps")
        await session.commit()
        rival_record_id = theirs.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(rival_record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    # It never even parks: the state reader cannot find the record, so the
    # confirmation attempt has nothing to price up.
    if parked.status is ToolResultStatus.CONFIRMATION_REQUIRED:
        async with app.state.container.session_factory()() as session:
            result = await _executor(session, fake_redis).confirm(
                UUID(parked.content["pending_action_id"]),
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
        assert result.status is ToolResultStatus.ERROR
        assert "Rival" not in str(result.content)

    assert await _state_of(app, rival, rival_record_id) == "DRAFT"


async def test_a_confirmation_cannot_be_replayed(client, owner_headers, app, fake_redis) -> None:
    """One approval, one effect. Two confirmations arriving together cannot
    both find the action unconsumed — the claim is a conditional UPDATE."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    pending_id = UUID(parked.content["pending_action_id"])
    async with app.state.container.session_factory()() as session:
        first = await _executor(session, fake_redis).confirm(
            pending_id,
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()
    assert first.status is ToolResultStatus.OK

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as raised:
            await _executor(session, fake_redis).confirm(
                pending_id,
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
    assert raised.value.reason == "consumed"

    async with app.state.container.session_factory()() as session:
        versions = (
            (
                await session.execute(
                    select(KnowledgeRecord).where(KnowledgeRecord.company_id == company_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(versions) == 1, "a replayed confirmation must not publish twice"


async def test_a_rejected_action_never_runs(client, owner_headers, app, fake_redis) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("publish_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    pending_id = UUID(parked.content["pending_action_id"])
    async with app.state.container.session_factory()() as session:
        await _executor(session, fake_redis).reject(
            pending_id,
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        with pytest.raises(ToolExecutionError) as raised:
            await _executor(session, fake_redis).confirm(
                pending_id,
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
    assert raised.value.reason == "rejected"
    assert await _state_of(app, company_id, record_id) == "DRAFT"


# ====================== supersede_knowledge_record ======================


async def test_superseding_parks_then_replaces_the_active_version(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id, publish=True)
        await session.commit()
        record_id = record.id

    args = {
        "record_id": str(record_id),
        "attributes": {"amount": "195", "currency": "JOD"},
        "effective_from": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "source_reference": "Price list 2026-09",
    }

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("supersede_knowledge_record", args),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert parked.status is ToolResultStatus.CONFIRMATION_REQUIRED
    assert await _state_of(app, company_id, record_id) == "ACTIVE", "nothing yet"

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).confirm(
            UUID(parked.content["pending_action_id"]),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert result.status is ToolResultStatus.OK
    replacement = result.content["replacement"]
    assert replacement["attributes"]["amount"] == "195"
    assert replacement["lifecycle_state"] == "ACTIVE"

    async with app.state.container.session_factory()() as session:
        outgoing = await session.get(KnowledgeRecord, record_id)
        assert outgoing is not None
        # The old period closes exactly where the new one opens: half-open,
        # so there is no instant where both answer and no gap where neither
        # does.
        assert outgoing.effective_until is not None
        assert outgoing.effective_until.isoformat() == replacement["effective_from"]
        assert outgoing.lifecycle_state == KnowledgeLifecycleState.SUPERSEDED


async def test_superseding_needs_the_publish_permission(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id, publish=True)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call(
                "supersede_knowledge_record",
                {
                    "record_id": str(record_id),
                    "attributes": {"amount": "195", "currency": "JOD"},
                    "effective_from": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    "source_reference": "Price list 2026-09",
                },
            ),
            ctx=_ctx(
                session,
                app.state.container,
                company_id=company_id,
                user_id=user_id,
                permissions=frozenset(OWNER_PERMISSIONS) - {"knowledge_records.publish"},
            ),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert result.content["error"] == "Missing required permission: knowledge_records.publish"
    assert await _state_of(app, company_id, record_id) == "ACTIVE"


async def test_superseding_another_companys_record_is_refused(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        rival = await _other_company(session)
        theirs = await _seed(
            session, company_id=rival, subject_label="Rival DIA 500 Mbps", publish=True
        )
        await session.commit()
        rival_record_id = theirs.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call(
                "supersede_knowledge_record",
                {
                    "record_id": str(rival_record_id),
                    "attributes": {"amount": "1", "currency": "JOD"},
                    "effective_from": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                    "source_reference": "not mine",
                },
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    if parked.status is ToolResultStatus.CONFIRMATION_REQUIRED:
        async with app.state.container.session_factory()() as session:
            result = await _executor(session, fake_redis).confirm(
                UUID(parked.content["pending_action_id"]),
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
        assert result.status is ToolResultStatus.ERROR

    async with app.state.container.session_factory()() as session:
        untouched = await session.get(KnowledgeRecord, rival_record_id)
        assert untouched is not None
        assert untouched.attributes["amount"] == "180"
        assert untouched.lifecycle_state == KnowledgeLifecycleState.ACTIVE


# ======================= archive_knowledge_record =======================


async def test_archiving_parks_then_withdraws(client, owner_headers, app, fake_redis) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id, publish=True)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("archive_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert parked.status is ToolResultStatus.CONFIRMATION_REQUIRED
    assert await _state_of(app, company_id, record_id) == "ACTIVE", "not withdrawn yet"

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).confirm(
            UUID(parked.content["pending_action_id"]),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert result.status is ToolResultStatus.OK
    assert result.content["withdrawn"]["lifecycle_state"] == "ARCHIVED"
    assert await _state_of(app, company_id, record_id) == "ARCHIVED"


async def test_archiving_succeeds_without_provenance(
    client, owner_headers, app, fake_redis
) -> None:
    """The reason archive skips ``publication_gate``.

    A record with no source cannot be *published* — the gate says so. It must
    still be withdrawable, or the platform would be unable to retract exactly
    the material it most wants to stop saying.
    """
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id, source_reference=None)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("archive_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).confirm(
            UUID(parked.content["pending_action_id"]),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    assert result.status is ToolResultStatus.OK
    assert await _state_of(app, company_id, record_id) == "ARCHIVED"


async def test_archiving_needs_the_publish_permission(
    client, owner_headers, app, fake_redis
) -> None:
    """Withdrawing a price changes what the platform says just as surely as
    publishing one, so it takes the same authority."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        record = await _seed(session, company_id=company_id, publish=True)
        await session.commit()
        record_id = record.id

    async with app.state.container.session_factory()() as session:
        result = await _executor(session, fake_redis).execute(
            _call("archive_knowledge_record", {"record_id": str(record_id)}),
            ctx=_ctx(
                session,
                app.state.container,
                company_id=company_id,
                user_id=user_id,
                permissions=frozenset(OWNER_PERMISSIONS) - {"knowledge_records.publish"},
            ),
            invocation=AiInvocation(),
        )

    assert result.status is ToolResultStatus.ERROR
    assert result.content["error"] == "Missing required permission: knowledge_records.publish"
    assert await _state_of(app, company_id, record_id) == "ACTIVE"


async def test_archiving_another_companys_record_is_refused(
    client, owner_headers, app, fake_redis
) -> None:
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        rival = await _other_company(session)
        theirs = await _seed(
            session, company_id=rival, subject_label="Rival DIA 500 Mbps", publish=True
        )
        await session.commit()
        rival_record_id = theirs.id

    async with app.state.container.session_factory()() as session:
        parked = await _executor(session, fake_redis).execute(
            _call("archive_knowledge_record", {"record_id": str(rival_record_id)}),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(),
        )
        await session.commit()

    if parked.status is ToolResultStatus.CONFIRMATION_REQUIRED:
        async with app.state.container.session_factory()() as session:
            result = await _executor(session, fake_redis).confirm(
                UUID(parked.content["pending_action_id"]),
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
        assert result.status is ToolResultStatus.ERROR

    assert await _state_of(app, rival, rival_record_id) == "ACTIVE"


# ============================== the registry ==============================


async def test_an_invented_mutation_tool_reaches_nothing(
    client, owner_headers, app, fake_redis
) -> None:
    """The registry is an allowlist. A name nobody registered reaches no
    handler that refuses — it reaches nothing."""
    company_id, user_id = await _identity(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        for invented in ("publish_all_drafts", "approve_restricted", "grant_permission"):
            result = await _executor(session, fake_redis).execute(
                _call(invented, {"record_id": str(uuid4())}),
                ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
                invocation=AiInvocation(),
            )
            assert result.status is ToolResultStatus.ERROR
            assert "Unknown tool" in result.content["error"]
