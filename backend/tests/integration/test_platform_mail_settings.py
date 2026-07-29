"""The mail relay settings API.

Two properties carry the security weight here and are pinned directly:
the password never leaves the server, and a tenant administrator cannot
reach these endpoints at all.
"""

from typing import Any

from httpx import AsyncClient

from tests.integration.test_pricing_engine import platform_headers

SETTINGS = "/api/v1/platform/settings/mail"

VALID = {
    "host": "smtp.provider.test",
    "port": 587,
    "security": "starttls",
    "from_address": "noreply@example.test",
    "from_name": "Blink Engage",
    "username": "apikey",
    "password": "s3cret",
    "timeout_seconds": 15,
}


class TestAccess:
    async def test_a_tenant_administrator_cannot_read_them(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """These are installation settings. A company owner has no
        business reading the relay every tenant's mail goes through."""
        response = await client.get(SETTINGS, headers=owner_headers)
        assert response.status_code == 403

    async def test_a_tenant_administrator_cannot_change_them(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.put(SETTINGS, headers=owner_headers, json=VALID)
        assert response.status_code == 403


class TestReadWrite:
    async def test_defaults_come_from_the_environment(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        response = await client.get(SETTINGS, headers=headers)
        assert response.status_code == 200
        assert response.json()["customised"] is False

    async def test_the_password_is_never_returned(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        saved = await client.put(SETTINGS, headers=headers, json=VALID)

        assert saved.status_code == 200
        assert "password" not in saved.json()
        assert saved.json()["password_set"] is True
        # And not on the read path either.
        fetched = await client.get(SETTINGS, headers=headers)
        assert "s3cret" not in fetched.text

    async def test_saving_without_a_password_keeps_the_stored_one(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The form never receives the password back, so a round-trip
        that omits it must not erase it."""
        headers = await platform_headers(client, app)
        await client.put(SETTINGS, headers=headers, json=VALID)

        without = {key: value for key, value in VALID.items() if key != "password"}
        without["host"] = "smtp.changed.test"
        updated = await client.put(SETTINGS, headers=headers, json=without)

        assert updated.json()["host"] == "smtp.changed.test"
        assert updated.json()["password_set"] is True

    async def test_an_empty_password_clears_it(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await client.put(SETTINGS, headers=headers, json=VALID)

        cleared = await client.put(SETTINGS, headers=headers, json={**VALID, "password": ""})

        assert cleared.json()["password_set"] is False

    async def test_reset_falls_back_to_the_environment(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The way back for an operator who has misconfigured the relay
        from the console."""
        headers = await platform_headers(client, app)
        await client.put(SETTINGS, headers=headers, json=VALID)

        reset = await client.delete(SETTINGS, headers=headers)

        assert reset.json()["customised"] is False
        assert reset.json()["host"] != VALID["host"]

    async def test_the_actor_is_recorded(self, client: AsyncClient, app: Any) -> None:
        headers = await platform_headers(client, app)
        saved = await client.put(SETTINGS, headers=headers, json=VALID)
        assert saved.json()["updated_by_email"]

    async def test_a_bad_sender_address_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        response = await client.put(
            SETTINGS, headers=headers, json={**VALID, "from_address": "not-an-address"}
        )
        assert response.status_code == 422

    async def test_a_bad_port_is_refused(self, client: AsyncClient, app: Any) -> None:
        headers = await platform_headers(client, app)
        response = await client.put(SETTINGS, headers=headers, json={**VALID, "port": 0})
        assert response.status_code == 422


class TestTestSend:
    async def test_a_refused_send_answers_200_with_the_relays_words(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The relay's refusal is the *answer* to this request, not an
        error in serving it — and the operator needs the message the
        relay gave, not a generic failure."""
        headers = await platform_headers(client, app)
        # Port 9 is the discard protocol: nothing will answer SMTP there.
        await client.put(
            SETTINGS,
            headers=headers,
            json={**VALID, "host": "127.0.0.1", "port": 9, "timeout_seconds": 1},
        )

        response = await client.post(
            f"{SETTINGS}/test", headers=headers, json={"to_address": "ops@example.test"}
        )

        assert response.status_code == 200
        assert response.json()["delivered"] is False
        assert response.json()["detail"]
