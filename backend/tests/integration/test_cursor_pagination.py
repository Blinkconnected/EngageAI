"""Keyset paging on the two lists that change while being read.

See ``api.cursors``. What offset paging gets wrong is not the duplicate —
a client keying by id can drop that — it is the row returned on *no* page
at all, because rows shifted between requests. On the conversation list
that row is somebody's unanswered customer.
"""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from blinkengage.api import cursors
from blinkengage.domain.pagination import Cursor
from tests.integration.test_conversation_messaging import _create_conversation


def _cursor_from(item: dict) -> str:
    """Build the cursor a client would send after seeing ``item``.

    Constructed here rather than read from ``next_cursor`` because the
    first page of a real client's paging has no cursor to follow — this is
    exactly the seed step a client performs once, before the loop.
    """
    return cursors.encode(Cursor(id=UUID(item["id"])))


async def _page(client: AsyncClient, url: str, headers: dict, **params) -> dict:
    response = await client.get(url, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _send(client: AsyncClient, headers: dict, conversation_id: str, body: str) -> None:
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"body": body},
        headers=headers,
    )
    assert response.status_code == 201, response.text


def test_a_cursor_round_trips() -> None:
    original = Cursor(id=uuid4())
    assert cursors.decode(cursors.encode(original)) == original


def test_garbage_is_rejected_rather_than_guessed_at() -> None:
    for raw in ["not-base64!!", "", "eyJ2Ijo5OTl9"]:  # last one is {"v":999}
        with pytest.raises(cursors.InvalidCursor):
            cursors.decode(raw)


async def test_messages_page_through_by_cursor_without_gaps_or_repeats(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    for index in range(7):
        await _send(client, owner_headers, conversation["id"], f"Reply {index}")

    url = f"/api/v1/conversations/{conversation['id']}/messages"

    # The first page is fetched without a cursor, as a real client's would
    # be — and gets none back, because it did not ask to page by cursor.
    first = await _page(client, url, owner_headers, page_size=3)
    assert first["next_cursor"] is None
    seen: list[str] = [item["id"] for item in first["items"]]
    cursor = _cursor_from(first["items"][-1])

    # Bounded rather than ``while True``. A cursor that fails to advance
    # is a real and easy bug — it was this feature's first one — and the
    # symptom is a test suite that hangs instead of a test that fails.
    for _ in range(10):
        page = await _page(client, url, owner_headers, page_size=3, cursor=cursor)
        seen.extend(item["id"] for item in page["items"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    else:
        raise AssertionError("paging did not terminate — the cursor is not advancing")

    # 8 = 7 replies + the customer's opening message.
    assert len(seen) == 8
    assert len(set(seen)) == 8, "a row was returned on two pages"


async def test_a_message_arriving_mid_page_does_not_hide_an_older_one(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The bug keyset paging exists to fix. Reading newest-first while new
    messages arrive at that same end shifts every offset by one, so an
    offset-paged reader steps straight over a message. The cursor names a
    row rather than a position, so it does not move under the reader.

    Asserted as a property of the whole traversal rather than as an
    expected page. Which *page* a given row lands on depends on the
    ordering's tie-break, and these messages are written within the same
    second — the guarantee being tested is that every row is delivered
    exactly once, not where it appears.
    """
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    originals = [f"Original {index}" for index in range(4)]
    for body in originals:
        await _send(client, owner_headers, conversation["id"], body)

    url = f"/api/v1/conversations/{conversation['id']}/messages"
    first = await _page(client, url, owner_headers, page_size=2)
    seen = list(first["items"])
    cursor = _cursor_from(first["items"][-1])

    # A new message lands at the top while the client is mid-scroll.
    await _send(client, owner_headers, conversation["id"], "Arrived mid-scroll")

    for _ in range(10):
        page = await _page(client, url, owner_headers, page_size=2, cursor=cursor)
        seen.extend(page["items"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    else:
        raise AssertionError("paging did not terminate — the cursor is not advancing")

    ids = [item["id"] for item in seen]
    assert len(set(ids)) == len(ids), "a row was returned on two pages"

    bodies = [item["body"] for item in seen]
    # Nothing was skipped to make room for the arrival — which is the
    # failure offset paging produces here and the one a client cannot
    # detect, let alone repair.
    for body in originals:
        assert body in bodies, f"{body!r} was skipped entirely"


async def test_conversations_page_by_cursor_and_end_cleanly(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    for _ in range(3):
        await _create_conversation(client, owner_headers, registered_owner, app)

    url = "/api/v1/conversations"
    first = await _page(client, url, owner_headers, page_size=2)
    assert len(first["items"]) == 2
    cursor = _cursor_from(first["items"][-1])

    second = await _page(client, url, owner_headers, page_size=2, cursor=cursor)

    seen = [item["id"] for item in first["items"]] + [item["id"] for item in second["items"]]
    assert len(set(seen)) == len(seen)
    # A short page means the end, so no cursor is offered onwards.
    assert second["next_cursor"] is None


async def test_the_total_does_not_shrink_as_a_client_pages(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """``total`` means "rows matching this filter", and must mean the same
    thing on page four as on page one. Counting only what remains after
    the cursor would turn "20 of 60" into "20 of 40" with nothing having
    changed — a number that moves on its own reads as a bug in whatever
    is displaying it."""
    for _ in range(3):
        await _create_conversation(client, owner_headers, registered_owner, app)

    url = "/api/v1/conversations"
    first = await _page(client, url, owner_headers, page_size=2)
    assert first["total"] == 3

    second = await _page(
        client, url, owner_headers, page_size=2, cursor=_cursor_from(first["items"][-1])
    )

    assert second["total"] == 3


async def test_a_cursor_naming_another_companys_conversation_reveals_nothing(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A keyset resolves its sort value by looking the anchor row up. That
    lookup is scoped to the caller's company, so a cursor naming somebody
    else's conversation cannot be used as an oracle for its
    ``last_message_at`` — the page comes back empty rather than sliced at
    a position derived from foreign data."""
    for _ in range(3):
        await _create_conversation(client, owner_headers, registered_owner, app)
    ours = await _page(client, "/api/v1/conversations", owner_headers, page_size=10)
    assert ours["total"] == 3

    company_b = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company B",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b-cursor@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    headers_b = {"Authorization": f"Bearer {company_b.json()['tokens']['access_token']}"}

    # Company B pages its own (empty) list using a cursor that names one of
    # Company A's conversations.
    stolen = _cursor_from(ours["items"][0])
    page = await _page(client, "/api/v1/conversations", headers_b, page_size=10, cursor=stolen)

    assert page["items"] == []
    assert page["total"] == 0


async def test_a_cursor_from_another_conversation_does_not_slice_this_one(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Same rule one level down: a message cursor is resolved within the
    conversation being read, so a cursor from a different thread cannot
    position this one."""
    first, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    second, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    await _send(client, owner_headers, first["id"], "In the first thread")
    await _send(client, owner_headers, second["id"], "In the second thread")

    first_messages = await _page(
        client, f"/api/v1/conversations/{first['id']}/messages", owner_headers, page_size=10
    )
    foreign = _cursor_from(first_messages["items"][0])

    page = await _page(
        client,
        f"/api/v1/conversations/{second['id']}/messages",
        owner_headers,
        page_size=10,
        cursor=foreign,
    )

    assert page["items"] == []


async def test_an_invalid_cursor_is_a_422_not_a_silent_first_page(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Quietly serving page 1 to a client that asked for page 5 looks like
    the list restarted, and a paging loop that never advances is far
    harder to see than an error."""
    await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.get(
        "/api/v1/conversations", headers=owner_headers, params={"cursor": "not-a-real-cursor"}
    )

    assert response.status_code == 422, response.text
    assert "cursor" in response.json()["detail"].lower()


async def test_offset_paging_is_unchanged_and_advertises_no_cursor(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Additive means additive: every existing caller keeps the response
    it had, with one new field that is always null for them."""
    await _create_conversation(client, owner_headers, registered_owner, app)

    page = await _page(client, "/api/v1/conversations", owner_headers, page=1, page_size=20)

    assert page["page"] == 1
    assert page["page_size"] == 20
    assert page["total"] == 1
    assert page["next_cursor"] is None
