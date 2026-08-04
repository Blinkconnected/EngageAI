"""A company that just registered can receive a conversation.

The V1.0 readiness review found this broken end to end. Registration created
a company, an owner and roles; the onboarding wizard walked the administrator
through team, channels and ERP. Neither created a queue or a routing rule —
so the first real customer message resolved no service, matched no rule, and
was recorded ``LEFT_UNROUTED``: *"it reached no queue at all, so nothing will
pick it up."*

The administrator finished setup believing they were live. The platform
diagnosed its own broken state accurately, in a screen they had no reason to
open, and said nothing anywhere they would look.

This is the test that keeps that closed. It is deliberately end-to-end and
deliberately uses nothing but registration: any seeding a future change moves
into onboarding, or a fixture, would not be exercised here — and the whole
point is that a company is operable the moment it exists.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.routing_decisions import RoutingDecisionKind
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.queue import Queue, RoutingRule
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord

pytestmark = pytest.mark.asyncio


def _rows(payload: Any) -> list[dict]:
    """The list, whether the endpoint paginates or not.

    Queues and routing rules answer in different shapes today. A test that
    hard-codes one is a test that breaks when the other is paginated later,
    for a reason that has nothing to do with what it checks.
    """
    return payload["items"] if isinstance(payload, dict) else payload


class TestARegisteredCompanyIsOperable:
    async def test_registration_leaves_somewhere_for_a_message_to_land(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A queue and a rule pointing at it, created by registration itself.

        Not by onboarding: an administrator can skip the wizard — the first
        step offers it — and skipping setup must not produce a company that
        silently drops every conversation.
        """
        queues = _rows((await client.get("/api/v1/queues", headers=owner_headers)).json())

        assert queues, "a brand-new company has a queue"
        assert len(queues) == 1, "exactly one, so the choice is obvious rather than a menu"

        rules = _rows((await client.get("/api/v1/routing-rules", headers=owner_headers)).json())

        assert rules, "and a rule that points at it"
        assert rules[0]["target_queue_id"] == queues[0]["id"]
        assert (
            rules[0]["conditions"] == {}
        ), "a catch-all: the point is that nothing falls through on day one"

    async def test_the_default_rule_loses_to_any_rule_an_administrator_writes(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """It catches what nothing else claimed, rather than competing.

        A seeded rule that outranked real routing would be worse than no
        seeded rule at all — the administrator's own configuration would
        stop working and the cause would be invisible.
        """
        rules = _rows((await client.get("/api/v1/routing-rules", headers=owner_headers)).json())

        # Priority is evaluated lowest-number-first, so a large number here
        # means "only if nothing else matched".
        assert rules[0]["priority"] >= 1000

    async def test_a_first_customer_message_reaches_the_queue(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The whole point, tested end to end.

        Before this, the same walk produced a conversation recorded
        ``LEFT_UNROUTED`` — which the Inbox classifies *critical*, and which
        no agent would have been looking at.
        """
        import uuid as _uuid

        from tests.integration.test_routing_explainability import _ingest, _web_chat_session

        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()

            conversation = (await session.execute(select(Conversation))).scalar_one()
            decisions = list(
                (
                    await session.execute(
                        select(RoutingDecisionRecord).where(
                            RoutingDecisionRecord.conversation_id == conversation.id
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert (
            conversation.queue_id is not None
        ), "the conversation reached a queue — the state this whole test exists for"
        kinds = {row.kind for row in decisions}
        assert RoutingDecisionKind.LEFT_UNROUTED not in kinds, (
            "nothing was stranded: LEFT_UNROUTED is the critical state a brand-new "
            "company used to put every one of its conversations into"
        )
        assert RoutingDecisionKind.QUEUE_SELECTED in kinds

        assert _uuid.UUID(str(conversation.queue_id))

    async def test_the_conversation_is_visible_in_the_inbox(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Reaching a queue is not enough — it has to be somewhere an agent
        is actually looking."""
        from tests.integration.test_routing_explainability import _ingest, _web_chat_session

        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()

        response = await client.get(
            "/api/v1/conversations", params={"view": "waiting_pickup"}, headers=owner_headers
        )

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert items, "it shows up in the queue an agent triages from"
        assert items[0]["state"] == "waiting_for_pickup"
        assert items[0]["owner_kind"] == "queue", "and the queue is answerable for it"


class TestTheSeedIsOnlyASeed:
    async def test_it_is_ordinary_configuration_the_administrator_owns(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Renameable, editable, deletable like anything else.

        A default that could not be changed would be the platform making a
        decision on the customer's behalf permanently, which is a different
        and worse problem than the one being fixed.
        """
        queues = _rows((await client.get("/api/v1/queues", headers=owner_headers)).json())
        queue_id = queues[0]["id"]

        renamed = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"name": "Front line"},
            headers=owner_headers,
        )

        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Front line"

    async def test_every_company_gets_its_own(self, app: Any) -> None:
        """Seeded per company, not shared. A queue is a tenant's own thing."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            queues = list((await session.execute(select(Queue))).scalars().all())
            rules = list((await session.execute(select(RoutingRule))).scalars().all())

        companies = {queue.company_id for queue in queues}
        assert len(companies) == len(queues), "one queue per company, not one shared"
        assert all(rule.company_id in companies for rule in rules)
