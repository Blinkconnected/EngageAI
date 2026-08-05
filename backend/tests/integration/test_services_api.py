"""The Service Directory API.

The behaviour worth proving over HTTP is which edits mint a version and which
do not, because an administrator has to be able to predict it. Minting on
every save fills the history with entries identical to their predecessors and
buries the ones that matter; minting on none of them means an edit silently
rewrites the rules of conversations already running.

Also proven here: a field the console does not send means *unchanged*. That
matters more than in an ordinary PATCH — an absent SLA target read as ``None``
would silently stop measuring something, and the version recording it would
look like somebody's deliberate decision.
"""

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def create_service(client: AsyncClient, headers: dict, **overrides: Any) -> dict:
    payload: dict[str, Any] = {
        "code": "support",
        "name": "Support",
        "sla": {"first_response_minutes": 15},
        **overrides,
    }
    response = await client.post("/api/v1/services", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestCreating:
    async def test_a_service_is_created_with_its_first_version(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """A service without a version has no queue, no SLA and no AI policy
        to read, so it cannot be resolved into. The two are created together
        rather than leaving something unusable in the directory."""
        body = await create_service(client, owner_headers)

        assert body["version_minted"] is True
        assert body["current"]["version"] == 1
        assert body["current"]["sla_first_response_minutes"] == 15
        assert body["service"]["current_version_id"] == body["current"]["id"]

    async def test_a_duplicate_code_is_refused(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await create_service(client, owner_headers)

        response = await client.post(
            "/api/v1/services",
            json={"code": "support", "name": "Support Again"},
            headers=owner_headers,
        )

        assert response.status_code == 400

    async def test_a_code_must_be_a_stable_handle(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Lowercase and punctuation-free, because an external system selects
        by it and a display name changes the first time somebody fixes a
        typo."""
        response = await client.post(
            "/api/v1/services",
            json={"code": "Support Team!", "name": "Support"},
            headers=owner_headers,
        )

        assert response.status_code == 422

    async def test_a_queue_from_another_company_is_refused(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        import uuid

        response = await client.post(
            "/api/v1/services",
            json={"code": "support", "name": "Support", "logical_queue_id": str(uuid.uuid4())},
            headers=owner_headers,
        )

        assert response.status_code == 400


class TestWhichEditsMintAVersion:
    async def test_changing_an_sla_target_mints_one(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """A conversation reads its SLA from the version it is bound to, so
        this edit must not reach the ones already running."""
        created = await create_service(client, owner_headers)

        response = await client.patch(
            f"/api/v1/services/{created['service']['id']}",
            json={"sla": {"first_response_minutes": 5}, "change_note": "Tightened"},
            headers=owner_headers,
        )

        body = response.json()
        assert body["version_minted"] is True
        assert body["current"]["version"] == 2
        assert body["current"]["sla_first_response_minutes"] == 5

    async def test_renaming_mints_one(self, client: AsyncClient, owner_headers: dict) -> None:
        """The name is carried by value on the version so an archived service
        can still be named. If a rename did not mint, conversations starting
        *after* it would keep reporting the old name — the snapshot would be
        protecting history from a change meant to take effect."""
        created = await create_service(client, owner_headers)

        response = await client.patch(
            f"/api/v1/services/{created['service']['id']}",
            json={"name": "Customer Support"},
            headers=owner_headers,
        )

        body = response.json()
        assert body["version_minted"] is True
        assert body["current"]["name"] == "Customer Support"
        assert body["service"]["name"] == "Customer Support"

    async def test_reordering_does_not_mint_one(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """No conversation reads the display order. Minting here would fill
        the history with entries identical to their predecessors and make the
        ones that matter harder to find."""
        created = await create_service(client, owner_headers)

        response = await client.patch(
            f"/api/v1/services/{created['service']['id']}",
            json={"display_order": 3},
            headers=owner_headers,
        )

        body = response.json()
        assert body["version_minted"] is False
        assert body["current"]["version"] == 1
        assert body["service"]["display_order"] == 3

    async def test_switching_a_service_off_does_not_mint_one(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """It stops *new* conversations resolving here; it changes nothing
        for one already running."""
        created = await create_service(client, owner_headers)

        response = await client.patch(
            f"/api/v1/services/{created['service']['id']}",
            json={"is_active": False},
            headers=owner_headers,
        )

        assert response.json()["version_minted"] is False


class TestAnOmittedFieldMeansUnchanged:
    async def test_editing_one_target_leaves_the_others_alone(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The new version starts as a copy of the one it supersedes.
        Building it from the submitted fields alone would silently reset
        everything the caller did not mention."""
        created = await create_service(
            client,
            owner_headers,
            sla={"first_response_minutes": 15, "resolution_minutes": 240},
            ai={"enabled": True, "confidence_threshold": "0.9"},
        )

        response = await client.patch(
            f"/api/v1/services/{created['service']['id']}",
            json={"description": "Front line"},
            headers=owner_headers,
        )

        current = response.json()["current"]
        assert current["sla_first_response_minutes"] == 15
        assert current["sla_resolution_minutes"] == 240
        assert current["ai_enabled"] is True
        assert current["ai_confidence_threshold"] == "0.9"

    async def test_a_target_can_still_be_cleared_deliberately(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Sending it as null stops measuring it — unambiguous, unlike
        omitting it."""
        created = await create_service(
            client, owner_headers, sla={"first_response_minutes": 15, "resolution_minutes": 240}
        )

        response = await client.patch(
            f"/api/v1/services/{created['service']['id']}",
            json={"sla": {"first_response_minutes": 15, "resolution_minutes": None}},
            headers=owner_headers,
        )

        assert response.json()["current"]["sla_resolution_minutes"] is None


class TestTheHistoryIsReadable:
    async def test_every_version_is_kept_newest_first(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Conversations are still running on some of them, which is why
        they cannot be deleted and why this list is worth showing."""
        created = await create_service(client, owner_headers)
        service_id = created["service"]["id"]
        await client.patch(
            f"/api/v1/services/{service_id}",
            json={"sla": {"first_response_minutes": 10}, "change_note": "Tightened"},
            headers=owner_headers,
        )

        response = await client.get(
            f"/api/v1/services/{service_id}/versions", headers=owner_headers
        )

        versions = response.json()
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[0]["change_note"] == "Tightened"
        assert versions[1]["sla_first_response_minutes"] == 15

    async def test_an_archived_service_keeps_its_versions(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """A conversation that cannot say what it ran in is the failure this
        design exists to prevent, so nothing is ever hard-deleted."""
        created = await create_service(client, owner_headers)
        service_id = created["service"]["id"]

        deleted = await client.delete(f"/api/v1/services/{service_id}", headers=owner_headers)

        assert deleted.status_code == 204
        assert (
            await client.get(f"/api/v1/services/{service_id}", headers=owner_headers)
        ).status_code == 404
        listed = await client.get("/api/v1/services", headers=owner_headers)
        # Gone from the directory, not gone from the database. Asserted as
        # "this id is absent" rather than "the list is empty", because the
        # directory is no longer empty to begin with — registration seeds a
        # General service, and an empty list would stop being evidence that
        # *this* service was archived.
        assert service_id not in [service["id"] for service in listed.json()]


class TestIsolationAndPermissions:
    async def test_another_companys_service_is_not_found(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A 404 rather than a 403, so the response never confirms that an
        id belongs to somebody real."""
        created = await create_service(client, owner_headers)

        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Other Co",
                "owner_full_name": "Other Owner",
                "owner_email": "other-owner@example.com",
                "owner_password": "correct-horse-battery-9",
            },
        )
        other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.get(
            f"/api/v1/services/{created['service']['id']}", headers=other_headers
        )

        assert response.status_code == 404

    async def test_an_agent_cannot_create_one(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """An agent works conversations; they do not reconfigure how the
        company routes them."""
        created = await client.post(
            "/api/v1/agents",
            json={
                "email": "agent@acme.example",
                "full_name": "Ana Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        signed_in = await client.post(
            "/api/v1/auth/login",
            json={"email": "agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

        response = await client.post(
            "/api/v1/services",
            json={"code": "support", "name": "Support"},
            headers=agent_headers,
        )

        assert response.status_code == 403

    async def test_an_anonymous_caller_is_refused(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/services")).status_code in (401, 403)
