"""Platform (super) administration: the cross-tenant seam.

These tests exist mostly to pin the *boundaries*. The platform tier is
the one place that steps outside "one JWT, one company_id, every query
filtered", so the valuable assertions are the negative ones: a platform
token must not reach tenant data, a tenant token must not reach the
platform API, and a suspension must actually stop an already-issued
token rather than waiting for it to expire.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.core.security import hash_password
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.user import User

_PLATFORM_EMAIL = "platform.ops@blinkengage.example"
_PASSWORD = "correct-horse-battery-9"


async def _create_platform_admin(app: Any) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        session.add(
            User(
                company_id=None,
                email=_PLATFORM_EMAIL,
                hashed_password=hash_password(_PASSWORD),
                full_name="Platform Operator",
                is_company_owner=False,
                is_platform_admin=True,
            )
        )
        await session.commit()


async def _platform_headers(client: AsyncClient, app: Any) -> dict[str, str]:
    await _create_platform_admin(app)
    response = await client.post(
        "/api/v1/auth/login", json={"email": _PLATFORM_EMAIL, "password": _PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


class TestIsolationBoundary:
    async def test_a_platform_token_cannot_reach_tenant_data(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The whole product promise: platform staff cannot read
        customers' conversations. A platform token carries no company, so
        every tenant route refuses it outright."""
        headers = await _platform_headers(client, app)

        for path in ("/api/v1/conversations", "/api/v1/customers", "/api/v1/agents"):
            response = await client.get(path, headers=headers)
            assert response.status_code == 403, f"{path} -> {response.status_code}"

    async def test_a_platform_token_cannot_read_auth_me(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await _platform_headers(client, app)
        response = await client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 403

    async def test_a_tenant_token_cannot_reach_the_platform_api(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """A company Owner holds every tenant permission there is —
        platform authority is deliberately not among them, so it cannot
        be reached by editing a role."""
        response = await client.get("/api/v1/platform/companies", headers=owner_headers)
        assert response.status_code == 403

    async def test_the_platform_api_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/platform/companies")
        assert response.status_code in (401, 403)


class TestCompanyOverview:
    async def test_lists_companies_with_size_counts_but_no_content(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        response = await client.get("/api/v1/platform/companies", headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] >= 1
        row = body["items"][0]
        assert {"id", "name", "slug", "status", "user_count", "conversation_count"} <= set(row)
        # Never the settings blob (which holds the tenant's own AI
        # credentials config) and never tenant rows.
        assert "settings" not in row
        assert "ai_config" not in row

    async def test_filters_by_status(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)
        await client.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            json={"status": "suspended"},
            headers=headers,
        )

        suspended = await client.get(
            "/api/v1/platform/companies?status_filter=suspended", headers=headers
        )
        trial = await client.get(
            "/api/v1/platform/companies?status_filter=trial", headers=headers
        )

        assert [row["id"] for row in suspended.json()["items"]] == [company_id]
        assert company_id not in [row["id"] for row in trial.json()["items"]]


class TestSuspension:
    async def test_suspending_blocks_an_already_issued_token_immediately(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The important one. An access token stays cryptographically
        valid for its full lifetime, so suspension has to be enforced per
        request — otherwise a suspended company keeps working for up to
        15 minutes."""
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 200

        await client.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            json={"status": "suspended", "reason": "non-payment"},
            headers=headers,
        )

        response = await client.get("/api/v1/conversations", headers=owner_headers)
        assert response.status_code == 403
        assert "suspended" in response.json()["detail"].lower()

    async def test_suspending_blocks_sign_in_with_an_actionable_message(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Not "wrong password" — telling someone their credentials
        failed when the real problem is a suspended workspace sends them
        to reset a password that was never the issue."""
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            owner = (
                await session.execute(select(User).where(User.is_company_owner.is_(True)))
            ).scalars().first()
            assert owner is not None
            email = owner.email
            owner.hashed_password = hash_password(_PASSWORD)
            await session.commit()

        await client.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            json={"status": "suspended"},
            headers=headers,
        )

        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
        )

        assert response.status_code == 401
        assert "suspended" in response.json()["detail"].lower()
        assert "password" not in response.json()["detail"].lower()

    async def test_reactivating_restores_access(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)
        await client.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            json={"status": "suspended"},
            headers=headers,
        )
        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 403

        await client.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            json={"status": "active"},
            headers=headers,
        )

        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 200

    async def test_a_status_change_is_recorded_for_audit(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A platform operator changing a customer's account state must be
        reconstructable later."""
        from blinkengage.infrastructure.database.models.event_outbox import EventOutbox

        company_id = await _company_id(client, owner_headers)
        headers = await _platform_headers(client, app)

        await client.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            json={"status": "suspended", "reason": "non-payment"},
            headers=headers,
        )

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(EventOutbox).where(
                            EventOutbox.event_type == "platform.company_status_changed"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(events) == 1
        payload = events[0].payload
        assert payload["status"] == "suspended"
        assert payload["previous_status"] == "trial"
        assert payload["reason"] == "non-payment"

    async def test_suspending_an_unknown_company_is_a_404(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await _platform_headers(client, app)
        response = await client.patch(
            "/api/v1/platform/companies/11111111-1111-1111-1111-111111111111/status",
            json={"status": "suspended"},
            headers=headers,
        )
        assert response.status_code == 404


class TestSoftDeletedCompany:
    async def test_a_soft_deleted_companys_users_cannot_sign_in(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Previously nothing on any auth path read `Company.deleted_at`,
        so a closed company's users kept signing in indefinitely."""
        company_id = await _company_id(client, owner_headers)
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            from datetime import UTC, datetime

            company = await session.get(Company, company_id)
            assert company is not None
            company.deleted_at = datetime.now(UTC)
            owner = (
                await session.execute(select(User).where(User.is_company_owner.is_(True)))
            ).scalars().first()
            assert owner is not None
            email = owner.email
            owner.hashed_password = hash_password(_PASSWORD)
            await session.commit()

        response = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
        )

        assert response.status_code == 401
        assert "no longer active" in response.json()["detail"].lower()


@pytest.mark.parametrize("status_value", ["trial", "active", "suspended"])
async def test_every_company_status_is_settable(
    client: AsyncClient, owner_headers: dict, app: Any, status_value: str
) -> None:
    company_id = await _company_id(client, owner_headers)
    headers = await _platform_headers(client, app)

    response = await client.patch(
        f"/api/v1/platform/companies/{company_id}/status",
        json={"status": status_value},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == status_value
    assert CompanyStatus(status_value)
