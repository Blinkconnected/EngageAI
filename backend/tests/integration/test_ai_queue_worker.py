"""AI as a queue worker, and the gate that decides whether it may be one.

The gate is the interesting part. It was five inline conditions, one of which
is a **compliance kill switch** — the promise a company makes that no
AI-generated content reaches its customers. Migrating it wrong would mean AI
answering customers of a company that had switched AI off, and nothing would
fail, no test would go red, and nobody would find out from the platform.

So the tests below are about refusal: each switch, on its own, must stop AI —
and must say which switch it was, because "AI did not answer" sends an
administrator hunting through four screens.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.routing_decisions import RoutingDecisionKind
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from tests.integration.test_routing_explainability import (
    _ingest,
    _queue,
    _routing_rule,
    _web_chat_session,
)
from tests.integration.test_service_resolution_ingest import a_service

pytestmark = pytest.mark.asyncio


async def _autopilot_queue(client: AsyncClient, headers: dict) -> str:
    queue_id = await _queue(client, headers, name="Support", autopilot_enabled=True)
    await _routing_rule(client, headers, queue_id=queue_id)
    return queue_id


async def _run(
    client: AsyncClient,
    headers: dict,
    registered_owner: dict,
    app: Any,
    *,
    settings: dict[str, Any] | None = None,
    with_service: bool = True,
    provider: bool = True,
) -> tuple[Conversation, list[RoutingDecisionRecord]]:
    chat = await _web_chat_session(client, headers)
    await _autopilot_queue(client, headers)
    company_id = uuid.UUID(registered_owner["user"]["company"]["id"])

    factory = app.state.container.session_factory()
    async with factory() as session:
        if with_service:
            await a_service(session, company_id, "Support")
        company = await session.get(Company, company_id)
        assert company is not None
        if settings is not None:
            company.settings = {**(company.settings or {}), **settings}
        if provider:
            # A configured provider, because "AI cannot work at all" is
            # reported before "the company chose not to use it here" — you
            # cannot act on a choice about something that does not
            # function. Without this every refusal below reads
            # ``no_ai_provider`` and the switch under test is never
            # reached.
            company.ai_config = {
                "provider": "openai",
                "api_key": "sk-test",
                "model": "gpt-4o-mini",
            }
        await session.commit()

        await _ingest(session, company_id=str(company_id), chat=chat)
        await session.commit()

        conversation = (await session.execute(select(Conversation))).scalar_one()
        rows = list(
            (
                await session.execute(
                    select(RoutingDecisionRecord).order_by(RoutingDecisionRecord.decided_at)
                )
            )
            .scalars()
            .all()
        )
    return conversation, rows


def _ai_decision(rows: list[RoutingDecisionRecord]) -> RoutingDecisionRecord | None:
    return next((r for r in rows if r.policy == "ai_engagement"), None)


class TestTheComplianceSwitchSurvivedTheMigration:
    async def test_the_company_switch_alone_stops_ai(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The switch a compliance officer reaches for. Everything else is
        configured for AI and it still must not answer."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False, "autopilot": {"enabled": True}}},
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "company_disabled"
        assert decision.policy_source == "company_settings"

    async def test_autopilot_off_is_a_different_answer(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A company may want agent-facing suggestions without AI answering
        customers. Reporting that as "AI is off" would send an administrator
        to switch on something already on."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": True, "autopilot": {"enabled": False}}},
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "autopilot_disabled"

    async def test_the_activation_mode_is_its_own_answer(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Autopilot on, but running on SLA triggers and agent requests
        only. Not "Autopilot is off" — it is on, and does not answer this."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={
                "ai": {
                    "enabled": True,
                    "autopilot": {"enabled": True, "activate_on_new_conversation": False},
                }
            },
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "autopilot_mode_excludes_this"

    async def test_the_refusal_is_recorded_not_merely_a_branch(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """ "AI did not answer" sends an administrator hunting through four
        screens. A recorded decision with a source tells them which one."""
        _, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False}},
        )

        decision = _ai_decision(rows)
        assert decision is not None
        assert decision.kind is RoutingDecisionKind.POLICY_EVALUATED
        assert "switched off" in decision.policy_text


class TestTheLegacyPathIsUntouched:
    async def test_a_company_with_no_services_asks_no_policy(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """No service directory means no ExecutionContext to evaluate
        against, so the original five conditions still run — unchanged, for
        the companies this still describes."""
        _, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False}},
            with_service=False,
        )

        assert _ai_decision(rows) is None

    async def test_and_still_refuses_when_the_company_switch_is_off(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The promise holds on both paths. That it is unrecorded on the
        legacy one is a gap in explainability, never in enforcement."""
        conversation, _ = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False, "autopilot": {"enabled": True}}},
            with_service=False,
        )

        assert conversation.autopilot_active is False


class TestNoProviderIsReportedBeforeAnyChoice:
    async def test_it_outranks_the_autopilot_switches(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """ "AI cannot work at all" before "the company chose not to use it
        here". An administrator told Autopilot is off, who switches it on
        and finds AI still silent, has been sent the wrong way."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": True, "autopilot": {"enabled": False}}},
            provider=False,
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "no_ai_provider"
