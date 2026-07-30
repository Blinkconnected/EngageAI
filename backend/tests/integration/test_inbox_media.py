"""Inline media in a conversation, end to end.

The properties pinned here are the ones that make inline media work at all:
a browser can fetch the bytes without a header it cannot send, a video can
be seeked without downloading it whole, and a leaked URL is worth almost
nothing.
"""

import io
from typing import Any
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from PIL import Image

CONVERSATIONS = "/api/v1/conversations"


def png_bytes(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (140, 198, 63)).save(buffer, format="PNG")
    return buffer.getvalue()


async def a_conversation(
    client: AsyncClient, headers: dict, registered_owner: dict, app: Any
) -> str:
    """An open conversation with a customer, created the way a real one is —
    through the inbound ingest path rather than by inserting rows."""
    from tests.integration.test_conversation_messaging import _create_conversation

    conversation, _ = await _create_conversation(client, headers, registered_owner, app)
    return str(conversation["id"])


async def upload(
    client: AsyncClient,
    headers: dict,
    conversation_id: str,
    *,
    filename: str,
    content_type: str,
    data: bytes,
) -> dict:
    response = await client.post(
        f"{CONVERSATIONS}/{conversation_id}/attachments",
        headers=headers,
        files={"file": (filename, data, content_type)},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


class TestAttachmentMetadata:
    async def test_an_image_records_its_dimensions(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """So the conversation can reserve the right space *before* the
        image loads. Without this a thread of photos reflows as each
        arrives, and an agent loses their place mid-sentence."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)

        body = await upload(
            client,
            owner_headers,
            conversation_id,
            filename="receipt.png",
            content_type="image/png",
            data=png_bytes(800, 450),
        )

        assert body["width"] == 800
        assert body["height"] == 450

    async def test_a_non_image_has_no_dimensions_and_that_is_fine(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)

        body = await upload(
            client,
            owner_headers,
            conversation_id,
            filename="notes.pdf",
            content_type="application/pdf",
            data=b"%PDF-1.4 not really a pdf",
        )

        assert body["width"] is None
        assert body["height"] is None

    async def test_bytes_that_are_not_really_an_image_do_not_fail_the_upload(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """Refusing an upload because a header was unusual would turn a
        cosmetic nicety into a lost customer message."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)

        body = await upload(
            client,
            owner_headers,
            conversation_id,
            filename="claims-to-be.png",
            content_type="image/png",
            data=b"absolutely not a png",
        )

        assert body["width"] is None
        assert body["kind"] == "image"


class TestMessageAttachments:
    async def test_a_message_carries_everything_needed_to_render(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """Including the media URL, minted with the message rather than by a
        request per attachment: twenty photos would otherwise need twenty
        extra round trips before anything could be shown."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        uploaded = await upload(
            client,
            owner_headers,
            conversation_id,
            filename="photo.png",
            content_type="image/png",
            data=png_bytes(400, 300),
        )
        await client.post(
            f"{CONVERSATIONS}/{conversation_id}/messages",
            headers=owner_headers,
            json={"body": "Here it is", "attachment_ids": [uploaded["id"]]},
        )

        listed = await client.get(
            f"{CONVERSATIONS}/{conversation_id}/messages", headers=owner_headers
        )

        attachment = next(
            a for m in listed.json()["items"] for a in m["attachments"]
        )
        assert attachment["kind"] == "image"
        assert attachment["inline"] is True
        assert attachment["needs_fallback"] is False
        assert attachment["width"] == 400
        assert attachment["media_url"]

    async def test_a_plain_file_gets_no_media_url(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """Handing out a media URL for a spreadsheet invites somebody to try
        embedding it."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        uploaded = await upload(
            client,
            owner_headers,
            conversation_id,
            filename="data.csv",
            content_type="text/csv",
            data=b"a,b\n1,2\n",
        )
        await client.post(
            f"{CONVERSATIONS}/{conversation_id}/messages",
            headers=owner_headers,
            json={"body": "csv", "attachment_ids": [uploaded["id"]]},
        )

        listed = await client.get(
            f"{CONVERSATIONS}/{conversation_id}/messages", headers=owner_headers
        )
        attachment = next(a for m in listed.json()["items"] for a in m["attachments"])

        assert attachment["kind"] == "file"
        assert attachment["inline"] is False
        assert attachment["media_url"] is None


class TestStreaming:
    async def test_the_browser_can_fetch_bytes_without_an_auth_header(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """The whole reason signed URLs exist: an `<img src>` cannot send
        one."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        data = png_bytes(120, 90)
        uploaded = await upload(
            client,
            owner_headers,
            conversation_id,
            filename="p.png",
            content_type="image/png",
            data=data,
        )
        await client.post(
            f"{CONVERSATIONS}/{conversation_id}/messages",
            headers=owner_headers,
            json={"body": "x", "attachment_ids": [uploaded["id"]]},
        )
        listed = await client.get(
            f"{CONVERSATIONS}/{conversation_id}/messages", headers=owner_headers
        )
        media_url = next(
            a["media_url"] for m in listed.json()["items"] for a in m["attachments"]
        )

        # No Authorization header at all.
        response = await client.get(media_url)

        assert response.status_code == 200, response.text
        assert response.content == data
        assert response.headers["content-type"] == "image/png"
        # `inline`, not `attachment` — the difference between showing the
        # photo and downloading it.
        assert response.headers["content-disposition"].startswith("inline")
        assert response.headers["accept-ranges"] == "bytes"

    async def test_a_range_request_returns_only_that_range(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """What lets somebody drag a video's scrubber instead of waiting for
        the whole file."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        data = png_bytes(300, 300)
        media_url = await self._media_url(
            client, owner_headers, conversation_id, data, "image/png"
        )

        response = await client.get(media_url, headers={"Range": "bytes=10-19"})

        assert response.status_code == 206
        assert response.content == data[10:20]
        assert response.headers["content-range"] == f"bytes 10-19/{len(data)}"

    async def test_a_suffix_range_reads_the_end(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """How a browser finds the metadata at the end of an MP4 that was
        not written for streaming."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        data = png_bytes(200, 200)
        media_url = await self._media_url(
            client, owner_headers, conversation_id, data, "image/png"
        )

        response = await client.get(media_url, headers={"Range": "bytes=-16"})

        assert response.status_code == 206
        assert response.content == data[-16:]

    async def test_media_is_cacheable_but_private(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """Immutable, because an attachment's bytes never change — which is
        what makes scrolling back up a long conversation instant. Private,
        because the URL is per-tenant and must not sit in a shared proxy."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        media_url = await self._media_url(
            client, owner_headers, conversation_id, png_bytes(50, 50), "image/png"
        )

        response = await client.get(media_url)

        cache_control = response.headers["cache-control"]
        assert "private" in cache_control
        assert "immutable" in cache_control

    @staticmethod
    async def _media_url(
        client: AsyncClient,
        headers: dict,
        conversation_id: str,
        data: bytes,
        content_type: str,
    ) -> str:
        uploaded = await upload(
            client,
            headers,
            conversation_id,
            filename="f",
            content_type=content_type,
            data=data,
        )
        await client.post(
            f"{CONVERSATIONS}/{conversation_id}/messages",
            headers=headers,
            json={"body": "x", "attachment_ids": [uploaded["id"]]},
        )
        listed = await client.get(
            f"{CONVERSATIONS}/{conversation_id}/messages", headers=headers
        )
        return str(
            next(a["media_url"] for m in listed.json()["items"] for a in m["attachments"])
        )


class TestWhatALeakedUrlCannotDo:
    async def test_a_tampered_signature_is_refused(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        media_url = await TestStreaming._media_url(
            client, owner_headers, conversation_id, png_bytes(60, 60), "image/png"
        )
        query = parse_qs(urlparse(media_url).query)
        tampered = media_url.replace(query["sig"][0], "0" * 64)

        response = await client.get(tampered)

        assert response.status_code == 403

    async def test_an_extended_expiry_is_refused(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        """The expiry is signed, so pushing it out invalidates the URL."""
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        media_url = await TestStreaming._media_url(
            client, owner_headers, conversation_id, png_bytes(60, 60), "image/png"
        )
        query = parse_qs(urlparse(media_url).query)
        extended = media_url.replace(query["exp"][0], str(int(query["exp"][0]) + 999_999))

        response = await client.get(extended)

        assert response.status_code == 403

    async def test_no_signature_at_all_is_refused(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
    ) -> None:
        conversation_id = await a_conversation(client, owner_headers, registered_owner, app)
        media_url = await TestStreaming._media_url(
            client, owner_headers, conversation_id, png_bytes(60, 60), "image/png"
        )
        bare = media_url.split("?")[0]

        response = await client.get(bare)

        # Missing required query parameters.
        assert response.status_code == 422
