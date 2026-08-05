"""Stage 3: the Service is the only place SLA can be written.

See ``docs/architecture/service-centric-migration.md``.

The failure this closes is not a crash. Where a service owns a queue, the
service's targets are what every clock uses — so a queue-level edit saves a
number the platform never measures, and the administrator leaves believing a
promise that is not in effect. ``ConfigurationDriftDetector`` hunts for that
after the fact; this stops it being written in the first place.

Three things have to hold together, and the second is the one that makes it
shippable rather than merely correct:

1. A **change** to an owned queue's SLA is refused, naming the service.
2. Re-sending the **stored value** is not a change. The queue editor submits
   every field it renders, so a rule that refused on presence would make
   renaming a queue impossible — the feature would be correct and unusable.
3. A company with **no service** is untouched, which is most of the
   installation until Stage 2 runs. Their queue is still the only place their
   SLA lives.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.test_routing_explainability import _archive_every_service, _queue
from tests.integration.test_service_resolution_ingest import a_service

pytestmark = pytest.mark.asyncio


async def _own(app: Any, company_id: uuid.UUID, queue_id: str, name: str = "Support") -> None:
    factory = app.state.container.session_factory()
    async with factory() as session:
        await a_service(session, company_id, name, queue_id=uuid.UUID(queue_id))
        await session.commit()


class TestAnOwnedQueueRefusesSlaEdits:
    async def test_a_changed_first_response_target_is_refused(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(client, owner_headers, name="Support queue")
        await _own(app, company_id, queue_id)

        response = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"first_response_target_minutes": 45},
            headers=owner_headers,
        )

        assert response.status_code == 409, response.text

    async def test_the_refusal_names_the_service_to_edit_instead(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A refusal that only says no leaves somebody with a disabled field
        and nowhere to go. The next question is always "then where?"."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(client, owner_headers, name="Support queue")
        await _own(app, company_id, queue_id, name="Billing")

        response = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"first_response_target_minutes": 45},
            headers=owner_headers,
        )

        detail = response.json()["detail"]
        assert "Billing" in detail
        assert "Support queue" in detail
        assert "First response target" in detail

    async def test_a_changed_sla_policy_is_refused_too(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Both shapes of the queue tier, or the closed door has a window in
        it: a company that cannot set minutes would simply attach a policy."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(client, owner_headers, name="Support queue")
        policy = await client.post(
            "/api/v1/sla-policies",
            json={
                "name": "Gold",
                "first_response_target_minutes": 5,
                "resolution_target_minutes": 60,
            },
            headers=owner_headers,
        )
        assert policy.status_code == 201, policy.text
        await _own(app, company_id, queue_id)

        response = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"sla_policy_id": policy.json()["id"]},
            headers=owner_headers,
        )

        assert response.status_code == 409, response.text
        assert "SLA policy" in response.json()["detail"]


class TestTheQueueIsStillEditable:
    async def test_resending_the_stored_value_is_not_a_change(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The one that makes this shippable. ``QueueEditDialog`` submits
        every field it renders whether or not anybody touched it, so a rule
        refusing on *presence* would make renaming an owned queue impossible
        — correct, and unusable."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(
            client, owner_headers, name="Support queue", first_response_target_minutes=20
        )
        await _own(app, company_id, queue_id)

        response = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={
                "name": "Renamed queue",
                # Exactly what the dialog would send back, untouched.
                "first_response_target_minutes": 20,
            },
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed queue"

    async def test_everything_that_is_not_sla_still_saves(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Only SLA moved to the service. Autopilot, strategy and the rest are
        queue runtime and stay where they are."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(client, owner_headers, name="Support queue")
        await _own(app, company_id, queue_id)

        response = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"autopilot_enabled": True, "assignment_strategy": "round_robin"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["autopilot_enabled"] is True


class TestACompanyWithoutServicesIsUntouched:
    async def test_its_queue_sla_is_still_writable(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Most of the installation until Stage 2 runs. Their queue is the
        only place their SLA lives, and nothing here narrows that."""
        await _archive_every_service(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support queue")

        response = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"first_response_target_minutes": 45},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["first_response_target_minutes"] == 45

    async def test_a_service_that_names_no_queue_owns_nothing(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Having a directory is not the same as having an owner. A service
        with no queue leaves the rules to place conversations, and leaves that
        queue's SLA the one in effect."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(client, owner_headers, name="Support queue")
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support")
            await session.commit()

        response = await client.patch(
            f"/api/v1/queues/{queue_id}",
            json={"first_response_target_minutes": 45},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text


class TestTheScreenIsToldWhoOwnsIt:
    async def test_the_queue_response_names_the_owning_service(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """So the field can be disabled *and* linked. A greyed-out box with no
        destination is a dead end."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(client, owner_headers, name="Support queue")
        await _own(app, company_id, queue_id, name="Billing")

        body = (await client.get(f"/api/v1/queues/{queue_id}", headers=owner_headers)).json()

        assert body["sla_owned_by_service"]["service_name"] == "Billing"

    async def test_an_unowned_queue_says_so(self, client: AsyncClient, owner_headers: dict) -> None:
        await _archive_every_service(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support queue")

        body = (await client.get(f"/api/v1/queues/{queue_id}", headers=owner_headers)).json()

        assert body["sla_owned_by_service"] is None

    async def test_the_list_answers_per_queue_without_a_query_each(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The queues screen needs this per row. Asked once for the whole
        page, because a query per row to render a label is how a list screen
        becomes slow without anybody noticing."""
        await _archive_every_service(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        owned = await _queue(client, owner_headers, name="Owned queue")
        free = await _queue(client, owner_headers, name="Free queue")
        await _own(app, company_id, owned, name="Billing")

        listing = (await client.get("/api/v1/queues", headers=owner_headers)).json()
        by_id = {row["id"]: row for row in listing["items"]}

        assert by_id[owned]["sla_owned_by_service"]["service_name"] == "Billing"
        assert by_id[free]["sla_owned_by_service"] is None
