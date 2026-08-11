"""The confirmation endpoints — the one step a model cannot take.

See ``docs/architecture/ai-tool-calling.md``. There is deliberately no
endpoint for *running* a tool; only for a human deciding on one the
executor refused to run by itself.
"""

from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.ai_tools import AiInvocation, ToolExecutor
from blinkengage.application.ai_tools.catalog import DEFAULT_REGISTRY
from blinkengage.domain.ai_tools import ToolCall
from blinkengage.infrastructure.cache.idempotency import IdempotencyStore
from blinkengage.infrastructure.database.models.ai_action import PendingAiAction
from tests.integration.test_ai_tool_executor import _ctx, _identity, _seed_agent_and_role


async def _propose_role_change(client, owner_headers, app, fake_redis) -> UUID:
    company_id, user_id = await _identity(client, owner_headers)
    agent_id, role_id = await _seed_agent_and_role(client, owner_headers)
    async with app.state.container.session_factory()() as session:
        executor = ToolExecutor(
            registry=DEFAULT_REGISTRY, session=session, idempotency=IdempotencyStore(fake_redis)
        )
        await executor.execute(
            ToolCall(
                id=str(uuid4()),
                name="change_agent_role",
                arguments={"target_agent_id": str(agent_id), "role_id": str(role_id)},
            ),
            ctx=_ctx(session, app.state.container, company_id=company_id, user_id=user_id),
            invocation=AiInvocation(user_request="promote them"),
        )
        await session.commit()
        return (await session.execute(select(PendingAiAction))).scalar_one().id


async def test_listing_tools_requires_authentication(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/ai/tools")).status_code in (401, 403)


async def test_tools_are_filtered_to_what_the_caller_may_use(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.get("/api/v1/ai/tools", headers=owner_headers)
    assert response.status_code == 200, response.text
    names = {item["name"] for item in response.json()["items"]}

    assert "create_department" in names
    # The guarantee that matters, restated at the edge: no destructive
    # tool is offered, because none exists to offer.
    assert not any("delete" in name for name in names)

    high_impact = next(
        item for item in response.json()["items"] if item["name"] == "change_agent_role"
    )
    assert high_impact["requires_confirmation"] is True


async def test_confirming_requires_authentication(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    pending_id = await _propose_role_change(client, owner_headers, app, fake_redis)
    response = await client.post(f"/api/v1/ai/actions/{pending_id}/confirm")
    assert response.status_code in (401, 403)


async def test_confirming_executes_the_parked_action(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    pending_id = await _propose_role_change(client, owner_headers, app, fake_redis)

    response = await client.post(f"/api/v1/ai/actions/{pending_id}/confirm", headers=owner_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["tool"] == "change_agent_role"
    assert body["content"]["role_name"] == "Admin"


async def test_confirming_twice_is_a_conflict(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    pending_id = await _propose_role_change(client, owner_headers, app, fake_redis)

    first = await client.post(f"/api/v1/ai/actions/{pending_id}/confirm", headers=owner_headers)
    second = await client.post(f"/api/v1/ai/actions/{pending_id}/confirm", headers=owner_headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 409, second.text


async def test_confirming_a_fabricated_id_is_not_found(
    client: AsyncClient, owner_headers: dict
) -> None:
    """A model inventing a plausible id gets nowhere."""
    response = await client.post(f"/api/v1/ai/actions/{uuid4()}/confirm", headers=owner_headers)
    assert response.status_code == 404


async def test_another_companys_pending_action_is_not_found(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    pending_id = await _propose_role_change(client, owner_headers, app, fake_redis)

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company B",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b-actions@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    headers_b = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.post(f"/api/v1/ai/actions/{pending_id}/confirm", headers=headers_b)

    # 404, not 403: confirming that an id exists but belongs to somebody
    # else is itself a disclosure.
    assert response.status_code == 404


async def test_rejecting_prevents_later_confirmation(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    pending_id = await _propose_role_change(client, owner_headers, app, fake_redis)

    rejected = await client.post(f"/api/v1/ai/actions/{pending_id}/reject", headers=owner_headers)
    assert rejected.status_code == 204, rejected.text

    confirmed = await client.post(f"/api/v1/ai/actions/{pending_id}/confirm", headers=owner_headers)
    assert confirmed.status_code == 409
