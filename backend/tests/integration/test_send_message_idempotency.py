"""``Idempotency-Key`` on message send.

See ``api.idempotency`` and ``docs/api/mobile-integration-guide.md``. The
scenario every test here stands in for is the same one: a phone sent a
reply, the connection dropped before the 201 came back, and the client
cannot tell whether the customer received the message. Retrying must be
safe.
"""

import hashlib

import orjson
from httpx import AsyncClient
from sqlalchemy import func, select

from blinkengage.api.idempotency import REPLAY_HEADER
from blinkengage.api.schemas.conversation import SendMessageRequest
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from tests.integration.test_conversation_messaging import _create_conversation


async def _outbound_count(app) -> int:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(Message)
                .where(Message.direction == MessageDirection.OUTBOUND)
            )
        ).scalar_one()


async def test_replaying_a_key_returns_the_original_message_and_sends_nothing(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    url = f"/api/v1/conversations/{conversation['id']}/messages"
    body = {"body": "We are on it."}
    headers = {**owner_headers, "Idempotency-Key": "11111111-2222-3333-4444-555555555555"}

    first = await client.post(url, json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = await client.post(url, json=body, headers=headers)
    assert second.status_code == 201, second.text

    # Same message, not a second one — same id, and the customer's thread
    # has exactly one agent reply in it.
    assert second.json()["id"] == first.json()["id"]
    assert await _outbound_count(app) == 1

    # And the client can tell which one it got. Without this a caller has
    # no way to distinguish "my retry was absorbed" from "I sent twice and
    # the first response was lost".
    assert REPLAY_HEADER not in first.headers
    assert second.headers[REPLAY_HEADER] == "true"


async def test_a_different_key_sends_a_second_message(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The guarantee is per key, not per body. An agent deliberately
    sending the same words twice must still get two messages."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    url = f"/api/v1/conversations/{conversation['id']}/messages"
    body = {"body": "Still there?"}

    first = await client.post(url, json=body, headers={**owner_headers, "Idempotency-Key": "a"})
    second = await client.post(url, json=body, headers={**owner_headers, "Idempotency-Key": "b"})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]
    assert await _outbound_count(app) == 2


async def test_reusing_a_key_with_a_different_body_is_refused(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A client bug, and refused rather than absorbed: returning the first
    message would hand back a plausible response to a request that was
    never performed, which is the failure this feature exists to prevent
    rather than a form of it."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    url = f"/api/v1/conversations/{conversation['id']}/messages"
    headers = {**owner_headers, "Idempotency-Key": "reused"}

    first = await client.post(url, json={"body": "First wording"}, headers=headers)
    assert first.status_code == 201, first.text

    second = await client.post(url, json={"body": "Completely different"}, headers=headers)
    assert second.status_code == 422, second.text
    assert "different request body" in second.json()["detail"]
    assert await _outbound_count(app) == 1


async def test_the_same_key_against_another_conversation_is_a_separate_request(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The key is scoped to the conversation. A client that reuses a key
    across conversations gets two messages — replaying the first
    conversation's reply into the second would be a worse outcome than the
    duplicate the header prevents."""
    first_conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    second_conversation, _ = await _create_conversation(
        client, owner_headers, registered_owner, app
    )
    assert first_conversation["id"] != second_conversation["id"]

    headers = {**owner_headers, "Idempotency-Key": "shared-key"}
    body = {"body": "Thanks for waiting."}
    first = await client.post(
        f"/api/v1/conversations/{first_conversation['id']}/messages", json=body, headers=headers
    )
    second = await client.post(
        f"/api/v1/conversations/{second_conversation['id']}/messages", json=body, headers=headers
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["conversation_id"] == first_conversation["id"]
    assert second.json()["conversation_id"] == second_conversation["id"]
    assert await _outbound_count(app) == 2


async def test_one_agents_key_cannot_absorb_another_agents_send(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A key is a promise about one person's retry. Two agents working the
    same conversation must each get their own message even if they present
    the same key with the same wording — otherwise one agent's send is
    silently swallowed and they are shown somebody else's message as
    though it were theirs."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    url = f"/api/v1/conversations/{conversation['id']}/messages"

    created = await client.post(
        "/api/v1/agents",
        json={
            "email": "second-agent@acme.example",
            "full_name": "Second Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "second-agent@acme.example", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    body = {"body": "Looking into it."}
    key = {"Idempotency-Key": "same-key-different-people"}
    first = await client.post(url, json=body, headers={**owner_headers, **key})
    second = await client.post(url, json=body, headers={**agent_headers, **key})

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]
    assert REPLAY_HEADER not in second.headers
    assert await _outbound_count(app) == 2


async def test_sending_without_the_header_behaves_exactly_as_before(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The contract is opt-in from both sides. Every existing caller —
    the web console included — must be unaffected by its addition."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    url = f"/api/v1/conversations/{conversation['id']}/messages"
    body = {"body": "Sent twice on purpose."}

    first = await client.post(url, json=body, headers=owner_headers)
    second = await client.post(url, json=body, headers=owner_headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]
    assert await _outbound_count(app) == 2


async def test_a_key_held_by_an_in_flight_request_is_told_to_wait(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, fake_redis
) -> None:
    """Two retries can overlap on a slow network. The second must not be
    allowed to do the work again, and must not be handed a response that
    does not exist yet — so it is told to retry, which is the one honest
    answer available."""
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    url = f"/api/v1/conversations/{conversation['id']}/messages"
    body = {"body": "Racing."}
    headers = {**owner_headers, "Idempotency-Key": "in-flight"}

    # Stands in for a request that took the reservation and has not
    # finished: exactly the state the store is left in mid-request.
    company_id = registered_owner["user"]["company"]["id"]
    user_id = registered_owner["user"]["id"]
    scope = f"conversations.send_message:{company_id}:{user_id}:{conversation['id']}"
    digest = hashlib.sha256(b"in-flight").hexdigest()
    request_fingerprint = hashlib.sha256(
        SendMessageRequest(**body).model_dump_json().encode()
    ).hexdigest()
    await fake_redis.set(
        f"idempotency:{scope}:{digest}",
        orjson.dumps({"state": "in_flight", "fingerprint": request_fingerprint}),
    )

    response = await client.post(url, json=body, headers=headers)

    assert response.status_code == 409, response.text
    assert "still in progress" in response.json()["detail"]
    assert await _outbound_count(app) == 0
