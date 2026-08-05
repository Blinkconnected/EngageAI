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


class TestARegisteredCompanyIsServiceFirst:
    """Company → Service → Queue → catch-all rule, from the first second.

    Until a Service existed there was nowhere for "AI is a queue worker, not
    a first responder" to be true: the pickup delay lives on a Service, and a
    company without one fell through to a platform default of zero. A company
    registered now owns that promise rather than inheriting a fallback.
    """

    async def test_registration_creates_a_service(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        response = await client.get("/api/v1/services", headers=owner_headers)

        assert response.status_code == 200, response.text
        services = _rows(response.json())
        assert len(services) == 1, "one, so the directory reads as a starting point"
        assert services[0]["name"] == "General"

    async def test_the_service_feeds_the_queue_the_catch_all_rule_points_at(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Otherwise a conversation resolves to a Service that sends it
        somewhere the routing rules never mentioned, and the two answers to
        "where does this go" disagree on day one."""
        queues = _rows((await client.get("/api/v1/queues", headers=owner_headers)).json())
        rules = _rows((await client.get("/api/v1/routing-rules", headers=owner_headers)).json())
        services = _rows((await client.get("/api/v1/services", headers=owner_headers)).json())
        detail = await client.get(f"/api/v1/services/{services[0]['id']}", headers=owner_headers)

        assert detail.status_code == 200, detail.text
        version = detail.json()["current"]
        assert version is not None, "a service with no version can route nothing"
        assert str(version["logical_queue_id"]) == str(queues[0]["id"])
        assert str(rules[0]["target_queue_id"]) == str(queues[0]["id"])

    async def test_it_is_named_the_company_default(self, registered_owner: dict, app: Any) -> None:
        """``FallbackStage`` otherwise resolves to whichever Service sorts
        first, which would make reordering the Services screen change which
        one catches unclaimed conversations."""
        import uuid as _uuid

        from blinkengage.domain.company_settings import default_service_id
        from blinkengage.infrastructure.database.models.company import Company
        from blinkengage.infrastructure.database.models.service_directory import Service

        company_id = _uuid.UUID(registered_owner["user"]["company"]["id"])
        factory = app.state.container.session_factory()
        async with factory() as session:
            company = await session.get(Company, company_id)
            assert company is not None
            chosen = default_service_id(company.settings)
            assert chosen is not None, "the company states which service is its default"
            service = await session.get(Service, chosen)

        assert service is not None, "and it names one that exists"
        assert service.company_id == company_id

    async def test_ai_waits_for_a_human_because_a_service_now_says_so(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The queue-worker promise, made true by configuration a company
        owns rather than by the platform asserting it."""
        services = _rows((await client.get("/api/v1/services", headers=owner_headers)).json())
        detail = await client.get(f"/api/v1/services/{services[0]['id']}", headers=owner_headers)

        assert detail.json()["current"]["ai_pickup_delay_seconds"] == 30

    async def test_the_seeded_service_does_not_veto_the_company_ai_switch(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The trap this avoids, and it is not hypothetical.

        ``Policy.AI_ENGAGEMENT`` checks the company's kill switch and its
        Autopilot opt-in *before* it reaches the service, and both default to
        off — so a new company's AI is silent either way and nothing is less
        safe for having this on. What it buys is that an administrator who
        turns Autopilot on company-wide, the way every company did before
        Services existed, is not answered with silence by a service they
        never configured.

        Seeded off, this platform would deny with ``SERVICE_DISABLED`` and
        the only place saying so is a routing decision row.
        """
        services = _rows((await client.get("/api/v1/services", headers=owner_headers)).json())
        detail = await client.get(f"/api/v1/services/{services[0]['id']}", headers=owner_headers)

        assert detail.json()["current"]["ai_enabled"] is True

    async def test_ai_is_still_off_until_the_company_turns_it_on(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The other half, and the one that matters for a healthcare or
        government tenant: nothing automated reaches a customer on the day
        they register. The service permits AI; the company has not asked
        for it."""
        company = (await client.get("/api/v1/company", headers=owner_headers)).json()
        autopilot = ((company.get("settings") or {}).get("ai") or {}).get("autopilot") or {}

        assert autopilot.get("enabled", False) is False
