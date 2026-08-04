"""The SLA an administrator configured is the SLA the engine enforces.

This is the end-to-end half of ``tests/unit/test_sla_target_resolution.py``.
The unit test pins the rule; this one pins that the rule is actually the one
ingest uses, which is where the original defect lived.

The failure it closes was total and silent. An administrator built an SLA
policy, attached it to the queue their conversations land in, and measured
nothing: ingest read targets from the service directory alone, found none, and
started no clocks. ``conversation_sla_clocks`` held **zero rows across the
entire installation** — so the Breached work queue was permanently empty, SLA
health never entered Inbox ordering, and no conversation story ever mentioned
a deadline. Nothing anywhere reported a fault.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.sla import PLATFORM_DEFAULT_SLA_TARGETS, SlaTargetSource, SlaTimer
from blinkengage.infrastructure.database.models.sla_clock import ConversationSlaClock

pytestmark = pytest.mark.asyncio


async def _clocks(session: Any) -> dict[str, ConversationSlaClock]:
    rows = (await session.execute(select(ConversationSlaClock))).scalars().all()
    return {str(row.timer): row for row in rows}


async def _send_one_message(client: AsyncClient, owner_headers: dict, app: Any, company_id: str):
    from tests.integration.test_routing_explainability import _ingest, _web_chat_session

    chat = await _web_chat_session(client, owner_headers)
    factory = app.state.container.session_factory()
    async with factory() as session:
        await _ingest(session, company_id=company_id, chat=chat)
        await session.commit()


class TestAQueueSlaIsHonoured:
    async def test_a_policy_attached_to_a_queue_starts_the_clocks(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The case that measured nothing at all.

        No service directory — which is every company on a fresh
        installation — and an SLA configured exactly where the product's own
        screens invite you to configure it.
        """
        policy = await client.post(
            "/api/v1/sla-policies",
            json={
                "name": "Front line",
                "first_response_target_minutes": 3,
                "resolution_target_minutes": 15,
                "warning_threshold_percent": 80,
                "business_hours_aware": False,
            },
            headers=owner_headers,
        )
        assert policy.status_code in (200, 201), policy.text

        queues = (await client.get("/api/v1/queues", headers=owner_headers)).json()
        queue_id = (queues["items"] if isinstance(queues, dict) else queues)[0]["id"]
        attached = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"sla_policy_id": policy.json()["id"]},
            headers=owner_headers,
        )
        assert attached.status_code == 200, attached.text

        await _send_one_message(
            client, owner_headers, app, registered_owner["user"]["company"]["id"]
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            clocks = await _clocks(session)

        assert clocks, "the queue's policy started clocks — this used to be empty"
        assert clocks[SlaTimer.FIRST_RESPONSE].target_minutes == 3
        assert clocks[SlaTimer.RESOLUTION].target_minutes == 15

    async def test_the_queue_wait_clock_stays_unmeasured(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A queue policy has never been able to express one, and inventing a
        number would be the platform making a promise on the company's
        behalf."""
        await _send_one_message(
            client, owner_headers, app, registered_owner["user"]["company"]["id"]
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            clocks = await _clocks(session)

        queue_clock = clocks.get(SlaTimer.QUEUE)
        assert queue_clock is None or queue_clock.target_minutes is None


class TestThePlatformDefaultIsTheFloor:
    async def test_a_company_that_configured_nothing_still_measures(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """No service, no policy, nothing attached.

        Before this tier existed such a company got an Inbox whose ordering,
        Breached queue and SLA health were permanently empty, with nothing
        anywhere explaining why.
        """
        await _send_one_message(
            client, owner_headers, app, registered_owner["user"]["company"]["id"]
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            clocks = await _clocks(session)

        assert clocks, "the platform default applies when nobody configured anything"
        assert (
            clocks[SlaTimer.FIRST_RESPONSE].target_minutes
            == PLATFORM_DEFAULT_SLA_TARGETS.first_response_minutes
        )


class TestTheClockRemembersWhoSetItsDeadline:
    """ "Why is this due in three minutes?" must be answerable later.

    The target itself has always been frozen onto the clock so a
    configuration change at noon cannot move a deadline already running. With
    three tiers able to supply it, the *source* needs freezing for the same
    reason — reconstructing it afterwards would read a service, a queue and a
    policy as they stand now rather than as they stood at the start.
    """

    async def test_a_queue_policy_is_recorded_as_the_author(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        policy = await client.post(
            "/api/v1/sla-policies",
            json={
                "name": "Front line",
                "first_response_target_minutes": 3,
                "resolution_target_minutes": 15,
                "warning_threshold_percent": 80,
                "business_hours_aware": False,
            },
            headers=owner_headers,
        )
        queues = (await client.get("/api/v1/queues", headers=owner_headers)).json()
        queue_id = (queues["items"] if isinstance(queues, dict) else queues)[0]["id"]
        await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"sla_policy_id": policy.json()["id"]},
            headers=owner_headers,
        )

        await _send_one_message(
            client, owner_headers, app, registered_owner["user"]["company"]["id"]
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            clocks = await _clocks(session)

        assert clocks[SlaTimer.FIRST_RESPONSE].target_source is SlaTargetSource.QUEUE

    async def test_the_platform_default_says_so_rather_than_staying_silent(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """An unexplained deadline on a company that configured nothing is
        the thing most likely to be mistaken for a bug."""
        await _send_one_message(
            client, owner_headers, app, registered_owner["user"]["company"]["id"]
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            clocks = await _clocks(session)

        assert clocks[SlaTimer.FIRST_RESPONSE].target_source is SlaTargetSource.PLATFORM_DEFAULT
