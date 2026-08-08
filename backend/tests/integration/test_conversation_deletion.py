"""Deleting a conversation takes two people.

A conversation is the record of what a company said to a customer:
evidence in a dispute, an input to every report, and in some industries
something the company is obliged to keep. The property these tests
defend is that no single person can make one disappear quietly — and,
just as importantly, that the paperwork survives the conversation.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.rbac import Role, RolePermission

REASON = "Customer asked us to remove their personal data under GDPR."


async def _seed_conversation(client: AsyncClient, headers: dict, app: Any) -> str:
    """A real conversation, created the way one really arrives."""
    from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
        handle_message_received,
    )

    company_id = (await client.get("/api/v1/auth/me", headers=headers)).json()["company"]["id"]
    config = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=headers,
    )
    config_id = config.json()["id"]
    session = (await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})).json()

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            {
                "event_type": "message.received",
                "company_id": company_id,
                "aggregate_type": "message",
                "aggregate_id": None,
                "actor_user_id": None,
                "payload": {
                    "channel_config_id": config_id,
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_customer_name": "Delible Customer",
                    "external_message_id": "ext-del-1",
                    "body": "Please forget me",
                },
            },
            db_session,
        )
        await db_session.commit()

    # The web-chat session creates the customer as "Web Visitor"; renaming
    # it gives the deletion record a name worth asserting on.
    customers = await client.get("/api/v1/customers", params={"page_size": 50}, headers=headers)
    await client.patch(
        f"/api/v1/customers/{customers.json()['items'][0]['id']}",
        json={"full_name": "Delible Customer"},
        headers=headers,
    )

    listing = await client.get("/api/v1/conversations", params={"page_size": 50}, headers=headers)
    return str(listing.json()["items"][0]["id"])


async def _second_admin(client: AsyncClient, owner_headers: dict, app: Any) -> dict:
    """Another user who can approve.

    The owner cannot decide their own request, which is the whole point,
    so almost every test here needs a second pair of hands.
    """
    await client.post(
        "/api/v1/agents",
        json={
            "email": "deletion-approver@acme.example",
            "full_name": "Approving Admin",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    # Agents are seeded into the Agent role, which cannot approve. Grant
    # that role the approver permission directly — there is no HTTP route
    # for editing role grants in these fixtures.
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        role = (
            await session.execute(
                select(Role).where(Role.company_id == UUID(company_id), Role.name == "Agent")
            )
        ).scalar_one()
        session.add(RolePermission(role_id=role.id, permission_code="conversations.delete_approve"))
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "deletion-approver@acme.example", "password": "correct-horse-battery-9"},
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def conversation_id(client: AsyncClient, owner_headers: dict, app: Any) -> str:
    return await _seed_conversation(client, owner_headers, app)


class TestAsking:
    async def test_asking_does_not_delete_anything(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        """The entire point. A request is a request."""
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == "pending"
        still_there = await client.get(
            f"/api/v1/conversations/{conversation_id}", headers=owner_headers
        )
        assert still_there.status_code == 200

    async def test_a_reason_is_required(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        # Whoever reviews this has nothing else to go on.
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": "spam"},
            headers=owner_headers,
        )

        assert response.status_code in {400, 422}

    async def test_only_one_request_can_be_open_at_a_time(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        """Two agents notice the same problem.

        A second pending row would leave an administrator approving one
        and the other still open against a conversation that is gone.
        """
        await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )

        second = await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": "Duplicate of the request already open."},
            headers=owner_headers,
        )

        assert second.status_code == 409

    async def test_anybody_who_can_see_it_can_see_that_deletion_was_asked_for(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        # Otherwise the interface offers a button that will only 409.
        assert (
            await client.get(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                headers=owner_headers,
            )
        ).json() is None

        await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )

        pending = await client.get(
            f"/api/v1/conversations/{conversation_id}/deletion-request", headers=owner_headers
        )
        assert pending.json()["reason"] == REASON

    async def test_a_conversation_in_another_company_is_not_found(
        self, client: AsyncClient, conversation_id: str
    ) -> None:
        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Other Co",
                "owner_full_name": "Other Owner",
                "owner_email": "deletion-other@test.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=headers,
        )

        # 404, not 403: a cross-company id must not be confirmed to exist.
        assert response.status_code == 404


class TestDeciding:
    async def test_approval_deletes_the_conversation(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        request_id = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()["id"]
        approver = await _second_admin(client, owner_headers, app)

        response = await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/approve",
            json={"note": "Confirmed with the customer."},
            headers=approver,
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "approved"
        gone = await client.get(f"/api/v1/conversations/{conversation_id}", headers=owner_headers)
        assert gone.status_code == 404

    async def test_the_paperwork_outlives_the_conversation(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        """What the record is for.

        Once the conversation is gone, the reason, the customer's name,
        who asked and who agreed are the only account of what happened.
        """
        request_id = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()["id"]
        approver = await _second_admin(client, owner_headers, app)
        await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/approve",
            json={},
            headers=approver,
        )

        listing = await client.get("/api/v1/conversation-deletion-requests", headers=owner_headers)
        record = next(r for r in listing.json()["items"] if r["id"] == request_id)
        assert record["reason"] == REASON
        assert record["customer_name"] == "Delible Customer"
        assert record["requested_by_name"] is not None
        assert record["decided_by_name"] == "Approving Admin"
        assert record["decided_at"] is not None

    async def test_rejection_keeps_the_conversation_and_says_why(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        request_id = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()["id"]
        approver = await _second_admin(client, owner_headers, app)

        response = await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/reject",
            json={"note": "We must keep this for the open billing dispute."},
            headers=approver,
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "rejected"
        assert "billing dispute" in response.json()["decision_note"]
        alive = await client.get(f"/api/v1/conversations/{conversation_id}", headers=owner_headers)
        assert alive.status_code == 200

    async def test_a_rejection_must_explain_itself(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        """An approval stands on the request's own reason. A rejection
        contradicts it, so the requester has to learn something."""
        request_id = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()["id"]
        approver = await _second_admin(client, owner_headers, app)

        response = await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/reject",
            json={},
            headers=approver,
        )

        assert response.status_code == 400

    async def test_a_request_is_decided_once(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        request_id = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()["id"]
        approver = await _second_admin(client, owner_headers, app)
        await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/approve",
            json={},
            headers=approver,
        )

        again = await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/approve",
            json={},
            headers=approver,
        )

        assert again.status_code == 409

    async def test_the_requester_cannot_approve_their_own(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        """The owner holds every permission, including the approver one,
        and still cannot wave through their own request — an approval
        with one name on both halves is not an approval."""
        request_id = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()["id"]

        response = await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/approve",
            json={},
            headers=owner_headers,
        )

        assert response.status_code == 403
        assert "own deletion request" in response.json()["detail"]


class TestWhoMayDoWhat:
    async def test_an_ordinary_agent_cannot_decide(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        await client.post(
            "/api/v1/agents",
            json={
                "email": "deletion-agent@acme.example",
                "full_name": "Ordinary Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "deletion-agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # They can ask...
        asked = await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=agent_headers,
        )
        assert asked.status_code == 201

        # ...and they cannot see the queue or decide.
        assert (
            await client.get("/api/v1/conversation-deletion-requests", headers=agent_headers)
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/conversation-deletion-requests/{asked.json()['id']}/approve",
                json={},
                headers=agent_headers,
            )
        ).status_code == 403

    async def test_an_administrator_approves_but_cannot_delete_behind_the_process(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        """What the two-permission split is for.

        `conversations.delete_approve` decides; `conversations.delete`
        removes a conversation outright, with no request and no recorded
        reason, and belongs to the Owner alone. Without the split an
        administrator could walk around the approval they are the point
        of — and leave nothing behind saying why.
        """
        approver = await _second_admin(client, owner_headers, app)

        # Can decide.
        assert (
            await client.get("/api/v1/conversation-deletion-requests", headers=approver)
        ).status_code == 200

        # Cannot delete directly.
        response = await client.delete(f"/api/v1/conversations/{conversation_id}", headers=approver)
        assert response.status_code == 403
        assert (
            await client.get(f"/api/v1/conversations/{conversation_id}", headers=owner_headers)
        ).status_code == 200

    async def test_the_owner_can_still_delete_directly(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        """The escape hatch stays, and stays with one accountable person.

        An Owner who does not want a second opinion should not be forced
        to stage one; they should delete it and be recorded as having
        done exactly that.
        """
        response = await client.delete(
            f"/api/v1/conversations/{conversation_id}", headers=owner_headers
        )

        assert response.status_code == 204

    async def test_the_queue_is_scoped_to_the_callers_company(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )
        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Nosy Co",
                "owner_full_name": "Nosy Owner",
                "owner_email": "deletion-nosy@test.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        listing = await client.get("/api/v1/conversation-deletion-requests", headers=headers)

        assert listing.json()["items"] == []

    async def test_the_queue_can_be_narrowed_to_what_still_needs_a_decision(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str
    ) -> None:
        await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )

        pending = await client.get(
            "/api/v1/conversation-deletion-requests",
            params={"status": "pending"},
            headers=owner_headers,
        )
        approved = await client.get(
            "/api/v1/conversation-deletion-requests",
            params={"status": "approved"},
            headers=owner_headers,
        )

        assert pending.json()["total"] == 1
        assert approved.json()["total"] == 0

    async def test_requesting_requires_authentication(
        self, client: AsyncClient, conversation_id: str
    ) -> None:
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
        )

        assert response.status_code in (401, 403)


class TestTellingPeople:
    async def test_the_approvers_are_told_without_having_to_look(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        """A request nobody is told about waits until somebody happens to
        open the right screen — the wrong way round for the one
        destructive action in the product."""
        approver = await _second_admin(client, owner_headers, app)

        await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )

        inbox = await client.get("/api/v1/notifications", headers=approver)
        titles = [n["title"] for n in inbox.json()["items"]]
        assert any("waiting to be deleted" in title for title in titles)

    async def test_the_person_who_asked_hears_the_outcome(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        request_id = (
            await client.post(
                f"/api/v1/conversations/{conversation_id}/deletion-request",
                json={"reason": REASON},
                headers=owner_headers,
            )
        ).json()["id"]
        approver = await _second_admin(client, owner_headers, app)

        await client.post(
            f"/api/v1/conversation-deletion-requests/{request_id}/reject",
            json={"note": "We must keep this for the open billing dispute."},
            headers=approver,
        )

        inbox = await client.get("/api/v1/notifications", headers=owner_headers)
        titles = [n["title"] for n in inbox.json()["items"]]
        assert any("rejected" in title for title in titles)

    async def test_the_notification_can_actually_be_followed_to_the_request(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        """The payload carries a real id, not the string "None".

        The primary key is applied at INSERT, not at construction, so
        this only works because the row is flushed before the
        notification is written. It used to work by accident — an
        unrelated SELECT happened to autoflush first — and a refactor
        removing that SELECT would have left every notification pointing
        at nothing, silently.
        """
        approver = await _second_admin(client, owner_headers, app)

        created = await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )

        inbox = await client.get("/api/v1/notifications", headers=approver)
        notification = next(
            n for n in inbox.json()["items"] if "waiting to be deleted" in n["title"]
        )
        assert notification["payload"]["request_id"] == created.json()["id"]

    async def test_nobody_is_told_about_their_own_request(
        self, client: AsyncClient, owner_headers: dict, conversation_id: str, app: Any
    ) -> None:
        # The owner can approve, so they are an approver — but they are
        # also the one who just asked, and telling somebody what they
        # have this second done is noise.
        await _second_admin(client, owner_headers, app)

        await client.post(
            f"/api/v1/conversations/{conversation_id}/deletion-request",
            json={"reason": REASON},
            headers=owner_headers,
        )

        inbox = await client.get("/api/v1/notifications", headers=owner_headers)
        titles = [n["title"] for n in inbox.json()["items"]]
        assert not any("waiting to be deleted" in title for title in titles)
