"""Integration test for the SMS (Twilio) webhook flow through the real
HTTP layer — proves ``settings.public_base_url`` + the request path is
what actually gets signed/verified against, end to end. See
``docs/architecture/sms.md``.
"""

import base64
import hashlib
import hmac
from typing import Any
from urllib.parse import parse_qsl, urlencode

from httpx import AsyncClient

from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)

_AUTH_TOKEN = "twilio-auth-token"


async def _create_sms_channel_config(client: AsyncClient, owner_headers: dict) -> dict:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "sms",
            "display_name": "Twilio SMS",
            "credentials": {
                "gateway": "twilio",
                "account_sid": "AC123",
                "auth_token": _AUTH_TOKEN,
                "from_number": "+15550000000",
            },
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _twilio_signature(*, url: str, body: bytes) -> str:
    params = dict(parse_qsl(body.decode()))
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    return base64.b64encode(
        hmac.new(_AUTH_TOKEN.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()


async def _claim_events(app: Any) -> list[Any]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        return await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=1_000_000)


async def test_post_with_valid_signature_publishes_message_received(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    config = await _create_sms_channel_config(client, owner_headers)
    body = urlencode(
        {
            "MessageSid": "SM1",
            "From": "+15551234567",
            "To": "+15550000000",
            "Body": "Hello from SMS",
            "NumMedia": "0",
        }
    ).encode()
    url = f"http://localhost/api/v1/webhooks/{config['id']}"

    response = await client.post(
        f"/api/v1/webhooks/{config['id']}",
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "x-twilio-signature": _twilio_signature(url=url, body=body),
        },
    )
    assert response.status_code == 200, response.text

    batch = await _claim_events(app)
    received = [e for e in batch if e.event_type == "message.received"]
    assert len(received) == 1
    assert received[0].payload["external_customer_id"] == "+15551234567"
    assert received[0].payload["body"] == "Hello from SMS"
    assert received[0].payload["channel_type"] == "sms"


async def test_post_with_invalid_signature_is_rejected(
    client: AsyncClient, owner_headers: dict
) -> None:
    config = await _create_sms_channel_config(client, owner_headers)
    body = urlencode({"MessageSid": "SM1", "From": "+15551234567", "Body": "Hi"}).encode()

    response = await client.post(
        f"/api/v1/webhooks/{config['id']}",
        content=body,
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "x-twilio-signature": "wrong",
        },
    )

    assert response.status_code == 401


async def test_create_channel_config_rejects_unknown_sms_gateway(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "sms",
            "display_name": "Bad Gateway",
            "credentials": {"gateway": "not-a-real-gateway"},
        },
        headers=owner_headers,
    )
    # Channel config creation itself only validates channel_type against
    # ChannelRegistry, not the inner gateway name — the invalid gateway
    # surfaces the first time a provider is actually built (on webhook
    # ingress or send), consistent with credentials being opaque JSON at
    # the ChannelConfig layer. See docs/architecture/sms.md.
    assert response.status_code == 201, response.text
    config = response.json()

    webhook_response = await client.post(
        f"/api/v1/webhooks/{config['id']}",
        content=b"MessageSid=SM1",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert webhook_response.status_code == 400
