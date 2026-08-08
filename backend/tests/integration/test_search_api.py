"""Integration tests for Global Search (`GET /search`). See
``docs/architecture/global-search.md``.
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.search_service import _SEARCHABLES
from blinkengage.infrastructure.database.models.rbac import Role, RolePermission
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)


async def _search(client: AsyncClient, headers: dict, q: str) -> dict:
    response = await client.get("/api/v1/search", params={"q": q}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _titles(body: dict, entity_type: str) -> list[str]:
    return [hit["title"] for hit in body["results"] if hit["entity_type"] == entity_type]


async def test_finds_a_customer_by_name_email_and_phone(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post(
        "/api/v1/customers",
        json={
            "full_name": "Zephyr Quinlan",
            "email": "zephyr@example.com",
            "phone": "+15550009999",
        },
        headers=owner_headers,
    )

    for term in ("Zephyr", "zephyr@example", "5550009999"):
        body = await _search(client, owner_headers, term)
        assert _titles(body, "customer") == ["Zephyr Quinlan"], f"no match for {term!r}"


async def test_finds_a_queue_by_name_and_description(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post(
        "/api/v1/queues",
        json={"name": "Escalations", "description": "Tier-three specialists only"},
        headers=owner_headers,
    )

    assert _titles(await _search(client, owner_headers, "Escalat"), "queue") == ["Escalations"]
    # `GET /queues` has no `search` param at all — matching on description
    # is search-only behavior, so this proves the new repository rather
    # than a pre-existing one.
    assert _titles(await _search(client, owner_headers, "Tier-three"), "queue") == ["Escalations"]


async def test_finds_a_team_a_quick_reply_and_a_knowledge_article(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post(
        "/api/v1/teams",
        json={"name": "Nightshift Crew", "description": "Overnight coverage"},
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/quick-replies",
        json={
            "shortcut": "/refundpolicy",
            "title": "Refund policy",
            "body": "We refund within 30 days.",
        },
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/knowledge/articles",
        json={"title": "Refund policy explained", "body": "Full details of refunds."},
        headers=owner_headers,
    )

    assert _titles(await _search(client, owner_headers, "Nightshift"), "team") == [
        "Nightshift Crew"
    ]
    refund = await _search(client, owner_headers, "Refund")
    assert _titles(refund, "quick_reply") == ["Refund policy"]
    assert _titles(refund, "knowledge_article") == ["Refund policy explained"]


async def test_finds_a_conversation_via_its_customers_name(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """A Conversation has no title of its own — global search is the only
    place conversations are text-searchable at all, matched and labelled
    through their customer."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    session = session_response.json()

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
                    "external_customer_name": "Marisol Okonkwo",
                    "external_message_id": "ext-1",
                    "body": "Hello",
                },
            },
            db_session,
        )
        await db_session.commit()

    # The web-chat customer is created by the session endpoint, so rename
    # it to something distinctive before searching.
    customers = await client.get(
        "/api/v1/customers", params={"page_size": 100}, headers=owner_headers
    )
    customer_id = customers.json()["items"][0]["id"]
    await client.patch(
        f"/api/v1/customers/{customer_id}",
        json={"full_name": "Marisol Okonkwo"},
        headers=owner_headers,
    )

    body = await _search(client, owner_headers, "Marisol")
    assert _titles(body, "conversation") == ["Marisol Okonkwo"]


async def test_finds_the_things_an_administrator_configures(
    client: AsyncClient, owner_headers: dict
) -> None:
    """Configuration is searchable, not only day-to-day work.

    An administrator asked to change "the Platinum SLA" or "the Riyadh
    department" arrives knowing the name and nothing else. Before this,
    search covered conversations and customers but not a single thing on
    a settings screen, so the only route to them was remembering which
    of a dozen pages each one lived on.
    """
    await client.post(
        "/api/v1/departments", json={"name": "Riyadh Operations"}, headers=owner_headers
    )
    await client.post(
        "/api/v1/services",
        json={
            "code": "platinum-onboarding",
            "name": "Platinum Onboarding",
            "sla": {"first_response_minutes": 15},
        },
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/sla-policies",
        json={"name": "Platinum Response", "first_response_target_minutes": 5},
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "whatsapp",
            "display_name": "Riyadh Hotline",
            "credentials": {
                "access_token": "test-token",
                "phone_number_id": "1234567890",
                "verify_token": "verify-me",
            },
            # A Meta channel: the App Secret is required rather than
            # generated, so creation 400s without it.
            "webhook_secret": "meta-app-secret",
        },
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/faqs",
        json={"question": "When does Riyadh Operations open?", "answer": "Sunday to Thursday."},
        headers=owner_headers,
    )

    riyadh = await _search(client, owner_headers, "Riyadh")
    assert _titles(riyadh, "department") == ["Riyadh Operations"]
    assert _titles(riyadh, "channel") == ["Riyadh Hotline"]
    assert _titles(riyadh, "faq") == ["When does Riyadh Operations open?"]

    platinum = await _search(client, owner_headers, "Platinum")
    assert _titles(platinum, "service") == ["Platinum Onboarding"]
    assert _titles(platinum, "sla_policy") == ["Platinum Response"]


async def test_finds_a_channel_by_its_type_and_a_service_by_its_code(
    client: AsyncClient, owner_headers: dict
) -> None:
    """The name somebody gave a thing is rarely the name it is known by.

    Channels get called "Main line"; the person hunting for one searches
    "whatsapp". Services are referenced by code in routing rules, so a
    code is what an administrator arrives with when tracing where a rule
    points.
    """
    await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "whatsapp",
            "display_name": "Main line",
            "credentials": {
                "access_token": "test-token",
                "phone_number_id": "1234567890",
                "verify_token": "verify-me",
            },
            # A Meta channel: the App Secret is required rather than
            # generated, so creation 400s without it.
            "webhook_secret": "meta-app-secret",
        },
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/services",
        json={"code": "vip-escalation", "name": "Concierge", "sla": {}},
        headers=owner_headers,
    )

    assert _titles(await _search(client, owner_headers, "whatsapp"), "channel") == ["Main line"]
    assert _titles(await _search(client, owner_headers, "vip-escal"), "service") == ["Concierge"]


async def test_finds_an_faq_by_words_that_appear_only_in_its_answer(
    client: AsyncClient, owner_headers: dict
) -> None:
    """The distinguishing words are usually in the answer.

    A question reads "Do you deliver?"; what makes it the right FAQ is
    the city named in the answer. Matching questions alone would miss
    the entry that answers exactly what was asked.
    """
    await client.post(
        "/api/v1/faqs",
        json={"question": "Do you deliver?", "answer": "We deliver across Jeddah within a day."},
        headers=owner_headers,
    )

    body = await _search(client, owner_headers, "Jeddah")
    assert _titles(body, "faq") == ["Do you deliver?"]


async def test_a_long_faq_answer_is_shortened_to_one_line(
    client: AsyncClient, owner_headers: dict
) -> None:
    """Answers run to paragraphs; result rows are one line.

    Sent whole, a single FAQ would push every other result off the
    screen, and its newlines would break the layout the other types use.
    """
    answer = "Paragraph one.\n\n" + ("Refund terms in detail. " * 40)
    await client.post(
        "/api/v1/faqs",
        json={"question": "Kaleidoscope refunds?", "answer": answer},
        headers=owner_headers,
    )

    body = await _search(client, owner_headers, "Kaleidoscope")
    subtitle = next(h["subtitle"] for h in body["results"] if h["entity_type"] == "faq")
    assert "\n" not in subtitle
    assert len(subtitle) <= 121  # 120 characters plus the ellipsis
    assert subtitle.endswith("…")


async def test_roles_are_searchable_only_by_somebody_who_can_manage_them(
    client: AsyncClient, owner_headers: dict
) -> None:
    """Stricter than the rest of the configuration types, on purpose.

    There is no `roles.read` — only `roles.manage`. A list of role names
    is a sketch of how a company delegates authority, which is not
    something an agent needs and not something to hand out through a
    search box.
    """
    await client.post(
        "/api/v1/roles",
        json={"name": "Nightshift Supervisor", "permission_codes": ["conversations.read"]},
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/agents",
        json={
            "email": "role-search-agent@acme.example",
            "full_name": "Role Search Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "role-search-agent@acme.example", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert _titles(await _search(client, owner_headers, "Nightshift"), "role") == [
        "Nightshift Supervisor"
    ]

    agent_view = await _search(client, agent_headers, "Nightshift")
    assert "role" not in set(agent_view["searched_entity_types"])
    assert _titles(agent_view, "role") == []


async def test_a_query_shorter_than_two_characters_returns_nothing(
    client: AsyncClient, owner_headers: dict
) -> None:
    """Enforced server-side, not only in the UI — an ILIKE '%a%' fan-out
    across every searchable table matches nearly everything while telling
    the caller nothing."""
    await client.post(
        "/api/v1/customers", json={"full_name": "Ada Lovelace"}, headers=owner_headers
    )

    body = await _search(client, owner_headers, "a")
    assert body["results"] == []
    assert body["searched_entity_types"] == []


async def test_results_are_scoped_to_the_callers_own_company(client: AsyncClient) -> None:
    company_a = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company A",
            "owner_full_name": "Owner A",
            "owner_email": "search-owner-a@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    company_b = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company B",
            "owner_full_name": "Owner B",
            "owner_email": "search-owner-b@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    headers_a = {"Authorization": f"Bearer {company_a.json()['tokens']['access_token']}"}
    headers_b = {"Authorization": f"Bearer {company_b.json()['tokens']['access_token']}"}

    await client.post("/api/v1/customers", json={"full_name": "Xylophone Zebra"}, headers=headers_a)

    assert _titles(await _search(client, headers_a, "Xylophone"), "customer") == ["Xylophone Zebra"]
    assert _titles(await _search(client, headers_b, "Xylophone"), "customer") == []


async def _revoke_agent_role_permissions(app: Any, company_id: str, codes: set[str]) -> None:
    """Removes `RolePermission` rows from the company's system Agent role
    directly — the only way to construct a narrower Agent in these
    fixtures, since the Agent role is granted every `*.read` permission
    by default (see `domain/rbac.py`'s DEFAULT_ROLE_PERMISSIONS) and
    there is no roles.manage HTTP endpoint to revoke one via the API.
    Must run *before* the agent logs in: permissions are resolved once,
    at login, and baked into the access token."""
    from uuid import UUID

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        role = (
            await session.execute(
                select(Role).where(Role.company_id == UUID(company_id), Role.name == "Agent")
            )
        ).scalar_one()
        grants = (
            (await session.execute(select(RolePermission).where(RolePermission.role_id == role.id)))
            .scalars()
            .all()
        )
        for grant in grants:
            if grant.permission_code in codes:
                await session.delete(grant)
        await session.commit()


async def test_only_searches_entity_types_the_caller_can_read(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """One search spans every entity type at once, each with its own
    permission, so the route can't be gated by a single
    `require_permission` — SearchService filters per type instead. A
    caller lacking `queues.read`/`workflows.read` must get neither those
    results nor those types listed as searched, while still getting the
    types they can read."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    await client.post("/api/v1/queues", json={"name": "Searchable Queue"}, headers=owner_headers)
    await client.post(
        "/api/v1/customers", json={"full_name": "Searchable Customer"}, headers=owner_headers
    )
    await client.post(
        "/api/v1/agents",
        json={
            "email": "search-agent@acme.example",
            "full_name": "Search Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    await _revoke_agent_role_permissions(app, company_id, {"queues.read", "workflows.read"})

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "search-agent@acme.example", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    body = await _search(client, agent_headers, "Searchable")

    searched = set(body["searched_entity_types"])
    assert "customer" in searched
    assert "queue" not in searched
    assert "workflow" not in searched
    assert _titles(body, "customer") == ["Searchable Customer"]
    # The queue genuinely exists and matches the term — it's absent
    # purely because this caller can't read queues.
    assert _titles(body, "queue") == []
    assert _titles(await _search(client, owner_headers, "Searchable"), "queue") == [
        "Searchable Queue"
    ]


async def test_a_caller_with_no_readable_entity_types_gets_an_empty_result(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """Not a 403 — search degrades to "nothing to search" rather than
    failing the whole request, which is what lets one endpoint serve
    callers with wildly different permission sets."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    await client.post(
        "/api/v1/agents",
        json={
            "email": "no-read-agent@acme.example",
            "full_name": "No Read Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )

    # Taken from the registry rather than listed by hand: a new searchable
    # entity type would otherwise leave this agent able to read one thing,
    # and the test would keep passing while proving nothing.
    await _revoke_agent_role_permissions(
        app, company_id, {searchable.permission for searchable in _SEARCHABLES}
    )

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "no-read-agent@acme.example", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    body = await _search(client, agent_headers, "anything")
    assert body["results"] == []
    assert body["searched_entity_types"] == []


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/search", params={"q": "test"})
    assert response.status_code in (401, 403)
