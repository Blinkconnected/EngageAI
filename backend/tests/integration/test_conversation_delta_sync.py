"""``GET /conversations?updated_since=`` — the delta a resuming client asks for.

See ``docs/api/mobile-integration-guide.md``. The scenario: a phone was
offline for hours, and re-paging the whole Inbox to discover what changed
is exactly the request that is slowest on exactly the network that is
worst.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.integration.test_conversation_messaging import _create_conversation


async def _list(client: AsyncClient, headers: dict, **params) -> dict:
    response = await client.get("/api/v1/conversations", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_future_cursor_returns_nothing(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The common case on a healthy client: nothing has changed since it
    last synced, and the answer must be cheap and empty rather than the
    whole Inbox."""
    await _create_conversation(client, owner_headers, registered_owner, app)

    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    page = await _list(client, owner_headers, updated_since=future)

    assert page["items"] == []
    # The total reflects the filter too — a count that ignored it would
    # tell the client "1 of 40" under an empty list.
    assert page["total"] == 0


async def test_a_past_cursor_returns_the_conversation(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    page = await _list(client, owner_headers, updated_since=past)

    assert [item["id"] for item in page["items"]] == [conversation["id"]]


async def test_replying_brings_a_conversation_back_into_the_delta(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The load-bearing assumption behind the whole feature: activity on a
    conversation moves its ``updated_at``. If sending a message left the
    row's timestamp alone, a client would sync and correctly conclude that
    nothing had happened."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)

    # Take a cursor that is already past everything, so the delta is empty...
    cursor = datetime.now(UTC)
    before = await _list(client, owner_headers, updated_since=cursor.isoformat())
    assert before["items"] == []
    assert before["total"] == 0

    # ...then do something worth syncing.
    reply = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"body": "On it."},
        headers=owner_headers,
    )
    assert reply.status_code == 201, reply.text

    page = await _list(client, owner_headers, updated_since=cursor.isoformat())
    assert [item["id"] for item in page["items"]] == [conversation["id"]]


async def test_the_cursor_is_exclusive(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A client that stores the newest ``updated_at`` it received and sends
    it back must not be handed that same row again on every single poll —
    which is what an inclusive comparison would do, forever."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)

    everything = await _list(client, owner_headers)
    newest = everything["items"][0]["updated_at"]

    page = await _list(client, owner_headers, updated_since=newest)
    assert page["items"] == []
    assert conversation["id"] not in [item["id"] for item in page["items"]]


async def test_delta_sync_composes_with_the_other_filters(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """``updated_since`` narrows the existing list rather than replacing
    it, so a client can keep whatever filter its screen is showing."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    # Read the status back rather than asserting a particular one: which
    # state routing leaves a new conversation in is a lifecycle detail
    # this test has no business pinning down.
    actual_status = (await _list(client, owner_headers))["items"][0]["status"]
    assert actual_status != "closed"

    matching = await _list(client, owner_headers, updated_since=past, status_filter=actual_status)
    other = await _list(client, owner_headers, updated_since=past, status_filter="closed")

    assert [item["id"] for item in matching["items"]] == [conversation["id"]]
    assert other["items"] == []


async def test_a_conversation_in_another_company_is_never_in_the_delta(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Tenant isolation is not weakened by a new filter. Worth asserting
    rather than assuming: ``updated_since`` is the first list parameter
    whose natural implementation ("everything that changed") says nothing
    about companies."""
    await _create_conversation(client, owner_headers, registered_owner, app)

    company_b = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company B",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    headers_b = {"Authorization": f"Bearer {company_b.json()['tokens']['access_token']}"}
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    page = await _list(client, headers_b, updated_since=past)

    assert page["items"] == []
    assert page["total"] == 0
