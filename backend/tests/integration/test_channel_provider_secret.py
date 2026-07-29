"""Meta channels must use Meta's App Secret as their webhook secret.

This pins the fix for the worst failure this integration had: the webhook
secret was auto-generated for every channel, but Meta signs each delivery
with the **App Secret** from the app dashboard. A generated value meant
the verification handshake passed (that uses ``verify_token``), the
channel reported itself connected and healthy, and then every inbound
message failed its signature check and was silently discarded.

"Verification is green and no messages arrive" is not a diagnosable
symptom, which is why the value is now required up front.
"""

from typing import Any

import pytest
from httpx import AsyncClient

CHANNELS = "/api/v1/channel-configs"

WHATSAPP = {
    "channel_type": "whatsapp",
    "display_name": "Support WhatsApp",
    "credentials": {"phone_number_id": "123456", "access_token": "token"},
}
MESSENGER = {
    "channel_type": "messenger",
    "display_name": "Support Messenger",
    "credentials": {"access_token": "page-token"},
}


class TestProviderSignedSecret:
    @pytest.mark.parametrize("payload", [WHATSAPP, MESSENGER])
    async def test_a_meta_channel_without_an_app_secret_is_refused(
        self, client: AsyncClient, owner_headers: dict, payload: dict[str, Any]
    ) -> None:
        response = await client.post(CHANNELS, headers=owner_headers, json=payload)

        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        # The message has to name what the value is and where to get it —
        # "webhook_secret is required" would send somebody to invent one,
        # which is the original bug.
        assert "App Secret" in detail
        assert "Settings" in detail

    @pytest.mark.parametrize("payload", [WHATSAPP, MESSENGER])
    async def test_a_meta_channel_with_an_app_secret_connects(
        self, client: AsyncClient, owner_headers: dict, payload: dict[str, Any]
    ) -> None:
        response = await client.post(
            CHANNELS,
            headers=owner_headers,
            json={**payload, "webhook_secret": "the-real-meta-app-secret"},
        )

        assert response.status_code == 201, response.text

    async def test_a_generated_secret_is_never_substituted(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The stored secret must be exactly what the operator gave, or
        signature verification fails against Meta's."""
        import uuid as _uuid

        from sqlalchemy import select

        from blinkengage.infrastructure.database.models.channel_config import ChannelConfig

        created = await client.post(
            CHANNELS,
            headers=owner_headers,
            json={**WHATSAPP, "webhook_secret": "exact-app-secret"},
        )
        config_id = _uuid.UUID(created.json()["id"])

        async with app.state.container.session_factory()() as session:
            stored = (
                await session.execute(
                    select(ChannelConfig.webhook_secret).where(ChannelConfig.id == config_id)
                )
            ).scalar_one()

        assert stored == "exact-app-secret"


class TestNonMetaChannels:
    async def test_telegram_still_gets_a_generated_secret(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Telegram registers its own webhook server-side and has no
        dashboard to paste anything into, so a generated secret is
        correct there — the requirement is specific to providers that
        sign with a secret of their own."""
        response = await client.post(
            CHANNELS,
            headers=owner_headers,
            json={
                "channel_type": "telegram",
                "display_name": "Support Telegram",
                "credentials": {"bot_token": "123:abc"},
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["webhook_secret"]


class TestMessengerValidation:
    async def test_messenger_credentials_are_now_validated(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Messenger and Instagram had no schema at all, so a typo saved
        cleanly and produced a channel that never delivered a message."""
        response = await client.post(
            CHANNELS,
            headers=owner_headers,
            json={
                "channel_type": "messenger",
                "display_name": "Typo Messenger",
                # `acces_token`, not `access_token`.
                "credentials": {"acces_token": "oops"},
                "webhook_secret": "app-secret",
            },
        )

        assert response.status_code == 400
        assert "access_token" in response.json()["detail"]

    async def test_a_verify_token_is_generated_for_messenger(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """A value the operator invents and pastes into Meta — there is
        nothing to look up, so there is no reason to make them think of
        one."""
        response = await client.post(
            CHANNELS,
            headers=owner_headers,
            json={**MESSENGER, "webhook_secret": "app-secret"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["verify_token"]
