"""Per-company feature entitlements, controlled by a platform admin.

The load-bearing property is the *safe default*: an installation with no
plans and no overrides must behave exactly as it did before entitlements
existed. Every other assertion here is about the resolution order —
override beats plan beats default — and about a tenant being unable to
grant itself anything.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from blinkengage.core.security import hash_password
from blinkengage.domain.features import FEATURE_KEYS, resolve_features
from blinkengage.infrastructure.database.models.user import User

_PLATFORM_EMAIL = "features.ops@blinkengage.example"
_PASSWORD = "correct-horse-battery-9"


async def _platform_headers(client: AsyncClient, app: Any) -> dict[str, str]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        session.add(
            User(
                company_id=None,
                email=_PLATFORM_EMAIL,
                hashed_password=hash_password(_PASSWORD),
                full_name="Feature Operator",
                is_company_owner=False,
                is_platform_admin=True,
            )
        )
        await session.commit()
    response = await client.post(
        "/api/v1/auth/login", json={"email": _PLATFORM_EMAIL, "password": _PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


class TestResolution:
    """Pure resolution logic, no HTTP — the table that everything else
    depends on."""

    def test_no_plan_and_no_overrides_grants_everything(self) -> None:
        """The property that makes this safe to deploy. Every existing
        company is in exactly this state on upgrade."""
        resolved = resolve_features(plan_features=None, overrides=None)

        assert set(resolved) == FEATURE_KEYS
        assert all(resolved.values())

    def test_a_plan_with_no_declared_features_still_grants_everything(self) -> None:
        """``None`` means "grants everything", not "grants nothing". An
        operator who has not thought about entitlements must not strip
        features from paying customers by accident."""
        assert all(resolve_features(plan_features=None, overrides={}).values())

    def test_an_empty_feature_list_grants_nothing(self) -> None:
        """...but an explicit ``[]`` is a real decision and is honoured.
        This is the distinction ``None`` vs ``[]`` exists to carry."""
        assert not any(resolve_features(plan_features=[], overrides=None).values())

    def test_a_plan_restricts_to_exactly_its_list(self) -> None:
        resolved = resolve_features(plan_features=["ai", "sla"], overrides=None)

        assert resolved["ai"] is True
        assert resolved["sla"] is True
        assert resolved["workflows"] is False

    def test_an_override_beats_the_plan_in_both_directions(self) -> None:
        """So an operator can run a pilot or shut off an abuser without
        inventing a bespoke plan for one customer."""
        resolved = resolve_features(
            plan_features=["ai"], overrides={"workflows": True, "ai": False}
        )

        assert resolved["workflows"] is True
        assert resolved["ai"] is False

    def test_an_unknown_key_is_ignored_rather_than_exploding(self) -> None:
        """A plan or override written against a feature a later release
        removed must not break every request for that company."""
        resolved = resolve_features(plan_features=["ai", "gone"], overrides={"also_gone": True})

        assert "gone" not in resolved
        assert resolved["ai"] is True


class TestEnforcement:
    async def test_everything_works_before_a_platform_admin_touches_anything(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The regression this whole design is arranged to avoid."""
        for path in ("/api/v1/workflows", "/api/v1/knowledge/categories", "/api/v1/sla-policies"):
            response = await client.get(path, headers=owner_headers)
            assert response.status_code == 200, f"{path} -> {response.text}"

    async def test_revoking_a_feature_closes_its_endpoints(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)

        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"workflows": False}},
            headers=headers,
        )

        response = await client.get("/api/v1/workflows", headers=owner_headers)
        assert response.status_code == 402
        assert "not included in this workspace's plan" in response.json()["detail"]

    async def test_a_revoked_feature_answers_402_not_403(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        """403 would send an administrator to edit roles that were never
        the problem. "You have permission; the workspace has not bought
        it" is a different sentence and deserves a different code."""
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)
        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"ai": False}},
            headers=headers,
        )

        response = await client.post(
            "/api/v1/ai/detect-language", json={"text": "hola"}, headers=owner_headers
        )

        assert response.status_code == 402
        assert "AI Engine" in response.json()["detail"]

    async def test_revoking_one_feature_leaves_the_others_alone(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)

        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"workflows": False}},
            headers=headers,
        )

        assert (
            await client.get("/api/v1/knowledge/categories", headers=owner_headers)
        ).status_code == 200

    async def test_restoring_a_feature_reopens_it(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)
        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"workflows": False}},
            headers=headers,
        )
        assert (await client.get("/api/v1/workflows", headers=owner_headers)).status_code == 402

        # An empty map clears every override — which is why this is a PUT.
        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {}},
            headers=headers,
        )

        assert (await client.get("/api/v1/workflows", headers=owner_headers)).status_code == 200

    async def test_report_export_is_gated_without_gating_reports(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        """A plan without exports still gets its dashboards on screen.
        Gating the whole reports router would be the difference between a
        tiered product and a broken one."""
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)
        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"reports_export": False}},
            headers=headers,
        )

        on_screen = await client.get(
            "/api/v1/reports/conversations?date_from=2026-01-01&date_to=2026-12-31",
            headers=owner_headers,
        )
        download = await client.get(
            "/api/v1/reports/conversations?date_from=2026-01-01&date_to=2026-12-31&export=pdf",
            headers=owner_headers,
        )

        assert on_screen.status_code == 200
        assert download.status_code == 402


class TestControl:
    async def test_a_tenant_cannot_grant_itself_a_feature(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        """The whole reason overrides live in their own column rather
        than in the tenant-editable ``settings`` blob."""
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)
        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"workflows": False}},
            headers=headers,
        )

        # A company Owner holds every tenant permission there is.
        via_platform = await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"workflows": True}},
            headers=owner_headers,
        )
        via_settings = await client.patch(
            "/api/v1/company",
            json={"settings": {"feature_overrides": {"workflows": True}}},
            headers=owner_headers,
        )

        assert via_platform.status_code == 403
        assert (await client.get("/api/v1/workflows", headers=owner_headers)).status_code == 402
        # Even if the settings write succeeded, it changes nothing —
        # entitlement is never read from `settings`.
        assert via_settings.status_code in (200, 403, 422)
        assert (await client.get("/api/v1/workflows", headers=owner_headers)).status_code == 402

    async def test_the_console_says_why_a_feature_is_off(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        """An operator fixes a plan-disabled feature differently from an
        override-disabled one, so the answer has to carry its source."""
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)
        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"ai": False}},
            headers=headers,
        )

        response = await client.get(
            f"/api/v1/platform/companies/{company_id}/features", headers=headers
        )

        states = {row["key"]: row for row in response.json()}
        assert states["ai"]["enabled"] is False
        assert states["ai"]["source"] == "override"
        assert states["workflows"]["enabled"] is True
        assert states["workflows"]["source"] == "default"

    async def test_an_unknown_feature_key_is_refused_not_stored(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        """A typo that persists silently looks like a working toggle that
        does nothing."""
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)

        response = await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"nonexistent_feature": False}},
            headers=headers,
        )

        assert response.status_code == 404

    async def test_a_feature_change_is_recorded_for_audit(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        from sqlalchemy import select

        from blinkengage.infrastructure.database.models.event_outbox import EventOutbox

        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)

        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"ai": False}},
            headers=headers,
        )

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            events = (
                (
                    await session.execute(
                        select(EventOutbox).where(
                            EventOutbox.event_type == "platform.company_features_changed"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(events) == 1
        assert events[0].payload["overrides"] == {"ai": False}

    async def test_the_catalog_is_platform_only(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        assert (
            await client.get("/api/v1/platform/features", headers=owner_headers)
        ).status_code == 403


class TestTenantVisibility:
    async def test_the_profile_carries_the_features_the_ui_should_render(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The frontend hides what isn't here, so nobody is shown a page
        that 402s the moment they open it."""
        response = await client.get("/api/v1/auth/me", headers=owner_headers)

        assert set(response.json()["features"]) == FEATURE_KEYS

    async def test_a_revoked_feature_disappears_from_the_profile(
        self, client: AsyncClient, app: Any, owner_headers: dict
    ) -> None:
        headers = await _platform_headers(client, app)
        company_id = await _company_id(client, owner_headers)

        await client.put(
            f"/api/v1/platform/companies/{company_id}/features",
            json={"overrides": {"ai": False, "erp": False}},
            headers=headers,
        )

        response = await client.get("/api/v1/auth/me", headers=owner_headers)
        features = set(response.json()["features"])
        assert "ai" not in features
        assert "erp" not in features
        assert "workflows" in features


@pytest.mark.parametrize("feature_key", sorted(FEATURE_KEYS))
async def test_every_catalogued_feature_is_settable(
    client: AsyncClient, app: Any, owner_headers: dict, feature_key: str
) -> None:
    """Guards against a feature being added to the catalog but never
    wired to anything an operator can actually control."""
    headers = await _platform_headers(client, app)
    company_id = await _company_id(client, owner_headers)

    response = await client.put(
        f"/api/v1/platform/companies/{company_id}/features",
        json={"overrides": {feature_key: False}},
        headers=headers,
    )

    assert response.status_code == 200
    states = {row["key"]: row for row in response.json()}
    assert states[feature_key]["enabled"] is False
    assert states[feature_key]["source"] == "override"
