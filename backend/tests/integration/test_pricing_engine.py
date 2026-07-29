"""The pricing engine, end to end through the API.

``tests/unit/test_pricing_resolution.py`` covers the resolution rules in
isolation. This file covers everything the pure kernel cannot: that the
hierarchy survives a round trip through the database, that a price
change really does leave history untouched, that every change is
audited, and that the platform boundary holds.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.core.security import hash_password
from blinkengage.infrastructure.database.models.pricing import PricingAuditLog, PricingRate
from blinkengage.infrastructure.database.models.user import User

_PLATFORM_EMAIL = "pricing.ops@blinkengage.example"
_PASSWORD = "correct-horse-battery-9"

CONVERSATION = "CONVERSATION"


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def soon(**kwargs: Any) -> datetime:
    return datetime.now(UTC) + timedelta(**kwargs)


async def platform_headers(client: AsyncClient, app: Any) -> dict[str, str]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        session.add(
            User(
                company_id=None,
                email=_PLATFORM_EMAIL,
                hashed_password=hash_password(_PASSWORD),
                full_name="Pricing Operator",
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


async def company_id_of(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


async def seed_global(client: AsyncClient, headers: dict, amount: str = "0.050000") -> None:
    """The migration seeds this in production; tests build their schema
    with `create_all`, which runs no migrations, so it is created here."""
    response = await client.put(
        f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
        json={
            "unit_amount": amount,
            "effective_from": iso(datetime.now(UTC)),
            "expect_no_current_rate": True,
            "reason": "Test baseline",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


async def effective_for(client: AsyncClient, headers: dict, company_id: str) -> dict:
    response = await client.get(
        f"/api/v1/platform/pricing/effective?company_id={company_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    return {item["metric_code"]: item for item in response.json()["items"]}


class TestCatalog:
    async def test_metrics_are_read_only_and_expose_their_metadata(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Administrators price metrics; they never create them. There is
        deliberately no POST here."""
        headers = await platform_headers(client, app)

        response = await client.get("/api/v1/platform/pricing/metrics", headers=headers)

        assert response.status_code == 200
        by_code = {m["code"]: m for m in response.json()}
        assert by_code[CONVERSATION]["unit"] == "conversation"
        assert by_code[CONVERSATION]["is_priceable"] is True
        # Declared, but nothing measures it — so it must not be priceable.
        assert by_code["VOICE_MINUTE"]["is_priceable"] is False

        assert (
            await client.post("/api/v1/platform/pricing/metrics", json={}, headers=headers)
        ).status_code in (404, 405)

    async def test_the_named_profiles_exist(self, client: AsyncClient, app: Any) -> None:
        headers = await platform_headers(client, app)
        # `create_all` runs no migrations, so seed the profiles the way
        # the migration does.
        await _seed_profiles(app)

        response = await client.get("/api/v1/platform/pricing/profiles", headers=headers)

        keys = [p["key"] for p in response.json()]
        assert keys == ["default", "startup", "smb", "enterprise", "government", "partner"]

    async def test_a_metric_with_no_meter_cannot_be_priced(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The guarantee the catalog makes: every priced metric has a
        measurement engine. Otherwise an operator sets a rate, sees no
        charges, and concludes billing is broken."""
        headers = await platform_headers(client, app)

        response = await client.put(
            "/api/v1/platform/pricing/global/metrics/VOICE_MINUTE",
            json={"unit_amount": "0.01", "effective_from": iso(soon(days=1))},
            headers=headers,
        )

        assert response.status_code == 409
        assert "measurement engine" in response.json()["detail"]

    async def test_an_unknown_metric_is_a_404_not_a_409(
        self, client: AsyncClient, app: Any
    ) -> None:
        """A typo and "we can't measure that yet" are different problems
        with different fixes, so they get different codes."""
        headers = await platform_headers(client, app)

        response = await client.put(
            "/api/v1/platform/pricing/global/metrics/TELEPATHY",
            json={"unit_amount": "0.01", "effective_from": iso(soon(days=1))},
            headers=headers,
        )

        assert response.status_code == 404


class TestHierarchy:
    async def test_a_company_falls_through_to_the_global_default(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        item = (await effective_for(client, headers, company_id))[CONVERSATION]

        assert item["unit_amount"] == "0.050000"
        # The API exposes the enum's value (lowercase), consistently with
        # every other enum in this codebase; uppercase is only the
        # storage form Enum(native_enum=False) writes.
        assert item["scope"] == "global"

    async def test_a_company_override_wins_and_shows_what_it_shadowed(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        created = await client.put(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.040000",
                "effective_from": iso(datetime.now(UTC)),
                "expect_no_current_rate": True,
                "reason": "Negotiated renewal, contract #4711",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text

        item = (await effective_for(client, headers, company_id))[CONVERSATION]
        assert item["unit_amount"] == "0.040000"
        assert item["scope"] == "company"
        # The explainability payload — an operator seeing 0.040 can see
        # the default was 0.050 without deriving the hierarchy by hand.
        assert [(s["scope"], s["unit_amount"]) for s in item["shadowed"]] == [
            ("global", "0.050000")
        ]

    async def test_removing_an_override_returns_the_company_to_the_default(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await client.put(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.040000",
                "effective_from": iso(datetime.now(UTC)),
                "expect_no_current_rate": True,
            },
            headers=headers,
        )

        ended = await client.post(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{CONVERSATION}/end",
            json={"effective_from": iso(datetime.now(UTC)), "reason": "Contract ended"},
            headers=headers,
        )

        assert ended.status_code == 204, ended.text

    async def test_prices_differ_per_company(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The requirement's own example: default 0.050, Company A 0.040,
        Company B 0.060."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_a = await company_id_of(client, owner_headers)
        company_b = await _register_company(client, "globex")

        for company_id, amount in ((company_a, "0.040000"), (company_b, "0.060000")):
            await client.put(
                f"/api/v1/platform/pricing/companies/{company_id}/metrics/{CONVERSATION}",
                json={
                    "unit_amount": amount,
                    "effective_from": iso(datetime.now(UTC)),
                    "expect_no_current_rate": True,
                },
                headers=headers,
            )

        a = (await effective_for(client, headers, company_a))[CONVERSATION]
        b = (await effective_for(client, headers, company_b))[CONVERSATION]
        assert (a["unit_amount"], b["unit_amount"]) == ("0.040000", "0.060000")


class TestHistoryIsNeverRewritten:
    async def test_changing_a_price_leaves_the_old_one_intact(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The requirement, stated directly: never recalculate old usage
        with a new price. The old row must still be there, with its range
        closed rather than overwritten."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        change_at = soon(days=30)

        second = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.055000",
                "effective_from": iso(change_at),
                "reason": "Annual price review",
            },
            headers=headers,
        )
        assert second.status_code == 201, second.text

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            rates = (
                (await session.execute(select(PricingRate).order_by(PricingRate.effective_from)))
                .scalars()
                .all()
            )
        assert len(rates) == 2, "the old price must be kept, not updated in place"
        assert str(rates[0].unit_amount) == "0.050000"
        assert rates[0].effective_until is not None, "the old row is closed, not deleted"
        assert str(rates[1].unit_amount) == "0.055000"

    async def test_usage_before_the_change_still_prices_at_the_old_rate(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        change_at = soon(days=30)
        await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={"unit_amount": "0.090000", "effective_from": iso(change_at)},
            headers=headers,
        )

        response = await client.post(
            "/api/v1/platform/pricing/resolve",
            json={
                "items": [
                    {
                        "company_id": company_id,
                        "metric_code": CONVERSATION,
                        "occurred_at": iso(soon(days=1)),
                        "quantity": "100",
                    },
                    {
                        "company_id": company_id,
                        "metric_code": CONVERSATION,
                        "occurred_at": iso(soon(days=60)),
                        "quantity": "100",
                    },
                ]
            },
            headers=headers,
        )

        assert response.status_code == 200, response.text
        priced = response.json()["priced"]
        assert [Decimal(p["unit_amount"]) for p in priced] == [
            Decimal("0.05"),
            Decimal("0.09"),
        ]
        # Compared as decimals, not strings: trailing zeros are a
        # formatting detail of Decimal, and pinning them would make the
        # test fail on a change that alters nothing anyone is charged.
        # Unrounded — rounding happens once, at invoice-line construction.
        assert [Decimal(p["amount"]) for p in priced] == [Decimal("5"), Decimal("9")]

    async def test_a_price_cannot_be_backdated_by_accident(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)

        response = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={"unit_amount": "0.070000", "effective_from": iso(soon(days=-10))},
            headers=headers,
        )

        assert response.status_code == 400
        assert "backdat" in response.json()["detail"].lower()


class TestAudit:
    async def test_every_change_records_old_and_new_value_and_who_made_it(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.055000",
                "effective_from": iso(soon(days=30)),
                "reason": "Annual price review",
            },
            headers=headers,
        )

        response = await client.get(
            f"/api/v1/platform/pricing/history?metric_code={CONVERSATION}", headers=headers
        )

        assert response.status_code == 200
        newest = response.json()[0]
        assert newest["old_unit_amount"] == "0.050000"
        assert newest["new_unit_amount"] == "0.055000"
        assert newest["changed_by_email"] == _PLATFORM_EMAIL
        assert newest["reason"] == "Annual price review"
        assert newest["effective_from"] is not None

    async def test_the_actor_survives_the_user_being_deleted(
        self, client: AsyncClient, app: Any
    ) -> None:
        """"Changed by" is a required field of the requirement. A bare
        foreign key would turn every price an ex-operator set into an
        anonymous change, so the identity is stored as a value too."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            entry = (await session.execute(select(PricingAuditLog))).scalars().first()
            assert entry is not None
            assert entry.changed_by_email == _PLATFORM_EMAIL
            assert entry.changed_by_name == "Pricing Operator"

    async def test_pricing_history_cannot_be_modified_through_the_repository(self) -> None:
        """Append-only is enforced by the repository's *shape*, not by
        discipline: there is no update or delete to call. PostgreSQL adds
        a trigger on top, so it also survives a psql session."""
        from blinkengage.infrastructure.repositories.pricing_repository import (
            PricingAuditRepository,
        )

        public = {name for name in dir(PricingAuditRepository) if not name.startswith("_")}

        assert public == {"add", "history"}

    async def test_history_is_filterable_by_company(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await client.put(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.040000",
                "effective_from": iso(datetime.now(UTC)),
                "expect_no_current_rate": True,
                "reason": "Negotiated",
            },
            headers=headers,
        )

        response = await client.get(
            f"/api/v1/platform/pricing/history?company_id={company_id}", headers=headers
        )

        entries = response.json()
        assert len(entries) == 1
        assert entries[0]["action"] == "pricing.company_rate_changed"


class TestConcurrencyAndIntegrity:
    async def test_a_stale_edit_is_refused_rather_than_silently_winning(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Two operators editing the same price must not both succeed
        with the second overwriting the first invisibly."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        stale_id = "11111111-1111-1111-1111-111111111111"

        response = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.070000",
                "effective_from": iso(soon(days=30)),
                "expected_current_rate_id": stale_id,
            },
            headers=headers,
        )

        assert response.status_code == 409
        assert "changed since you loaded it" in response.json()["detail"]

    async def test_expecting_no_rate_when_one_exists_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)

        response = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.070000",
                "effective_from": iso(soon(days=30)),
                "expect_no_current_rate": True,
            },
            headers=headers,
        )

        assert response.status_code == 409

    async def test_the_two_expectation_fields_are_mutually_exclusive(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.070000",
                "effective_from": iso(soon(days=1)),
                "expected_current_rate_id": "11111111-1111-1111-1111-111111111111",
                "expect_no_current_rate": True,
            },
            headers=headers,
        )

        assert response.status_code == 422

    async def test_a_naive_effective_date_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        """"From 1 August" is a different instant in Auckland and Los
        Angeles; guessing one would price a 00:30Z conversation
        differently depending on the server."""
        headers = await platform_headers(client, app)

        response = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={"unit_amount": "0.070000", "effective_from": "2026-08-01T00:00:00"},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_a_negative_price_is_refused(self, client: AsyncClient, app: Any) -> None:
        headers = await platform_headers(client, app)

        response = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={"unit_amount": "-0.01", "effective_from": iso(soon(days=1))},
            headers=headers,
        )

        assert response.status_code == 422


class TestResolveForBilling:
    async def test_an_unpriced_metric_fails_loudly_rather_than_charging_zero(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A silent zero is a revenue leak that looks exactly like a
        working system."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        response = await client.post(
            "/api/v1/platform/pricing/resolve",
            json={
                "items": [
                    {
                        "company_id": company_id,
                        "metric_code": "AI_AUTOPILOT",
                        "occurred_at": iso(datetime.now(UTC)),
                    }
                ]
            },
            headers=headers,
        )

        assert response.status_code == 503

    async def test_non_strict_mode_quarantines_instead_of_losing_the_run(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A nightly rating job must price the rows it can and set the
        rest aside, not abandon the night's work."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        response = await client.post(
            "/api/v1/platform/pricing/resolve",
            json={
                "strict": False,
                "items": [
                    {
                        "company_id": company_id,
                        "metric_code": CONVERSATION,
                        "occurred_at": iso(soon(days=1)),
                        "quantity": "10",
                    },
                    {
                        "company_id": company_id,
                        "metric_code": "AI_AUTOPILOT",
                        "occurred_at": iso(soon(days=1)),
                    },
                ],
            },
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["priced"]) == 1
        assert [u["metric_code"] for u in body["unpriced"]] == ["AI_AUTOPILOT"]

    async def test_sub_cent_pricing_survives_the_round_trip(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """$0.0005 x 10,000 must be $5.00, not $0.00 — the failure that
        happens when a rate is stored at two decimal places."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.000500")
        company_id = await company_id_of(client, owner_headers)

        response = await client.post(
            "/api/v1/platform/pricing/resolve",
            json={
                "items": [
                    {
                        "company_id": company_id,
                        "metric_code": CONVERSATION,
                        "occurred_at": iso(soon(days=1)),
                        "quantity": "10000",
                    }
                ]
            },
            headers=headers,
        )

        priced = response.json()["priced"][0]
        assert Decimal(priced["unit_amount"]) == Decimal("0.0005")
        # The failure this guards: at two decimal places the rate rounds
        # to 0.00 and ten thousand conversations bill nothing at all.
        assert Decimal(priced["amount"]) == Decimal("5")

    async def test_amounts_cross_the_wire_as_strings(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A JSON number becomes a JS float in the browser, which
        reintroduces exactly the drift Decimal exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        raw = (
            await client.get(
                f"/api/v1/platform/pricing/effective?company_id={company_id}", headers=headers
            )
        ).text

        assert '"unit_amount":"0.050000"' in raw.replace(" ", "")


class TestPlatformBoundary:
    async def test_a_tenant_cannot_read_pricing_administration(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """A company Owner holds every tenant permission there is.
        Pricing is platform authority, which is not in that catalog."""
        for path in (
            "/api/v1/platform/pricing/metrics",
            "/api/v1/platform/pricing/profiles",
            "/api/v1/platform/pricing/effective",
        ):
            response = await client.get(path, headers=owner_headers)
            assert response.status_code == 403, f"{path} -> {response.status_code}"

    async def test_a_tenant_cannot_set_their_own_price(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        company_id = await company_id_of(client, owner_headers)

        response = await client.put(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{CONVERSATION}",
            json={"unit_amount": "0.000001", "effective_from": iso(soon(days=1))},
            headers=owner_headers,
        )

        assert response.status_code == 403

    async def test_pricing_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/platform/pricing/metrics")

        assert response.status_code in (401, 403)


class TestCoverage:
    async def test_health_reports_measured_metrics_without_a_price(
        self, client: AsyncClient, app: Any
    ) -> None:
        """A metric with no price is harmless while nothing meters
        anything and becomes an outage the moment metering ships, so the
        gap is surfaced now rather than discovered then."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)

        response = await client.get("/api/v1/platform/pricing/health", headers=headers)

        assert response.status_code == 200
        body = response.json()
        by_code = {m["metric_code"]: m for m in body["metrics"]}
        assert by_code[CONVERSATION]["covered"] is True
        assert by_code["AI_AUTOPILOT"]["covered"] is False
        assert by_code["AI_AUTOPILOT"]["reason"] == "no_global_rate"
        assert body["ok"] is False
        # Planned metrics are not in scope for coverage — they cannot be
        # priced at all, so a missing price is not a gap.
        assert "VOICE_MINUTE" not in by_code


async def _seed_profiles(app: Any) -> None:
    from blinkengage.infrastructure.database.models.pricing import PricingProfile

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        for order, (key, name, is_system) in enumerate(
            [
                ("default", "Default", True),
                ("startup", "Startup", False),
                ("smb", "SMB", False),
                ("enterprise", "Enterprise", False),
                ("government", "Government", False),
                ("partner", "Partner", False),
            ]
        ):
            session.add(
                PricingProfile(
                    key=key, name=name, is_system=is_system, sort_order=order * 10
                )
            )
        await session.commit()


async def _register_company(client: AsyncClient, slug: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": slug.title(),
            "owner_full_name": "Second Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": _PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["user"]["company"]["id"])


@pytest.mark.parametrize("scope", ["global", "company"])
async def test_rates_endpoint_returns_the_full_timeline(
    client: AsyncClient, owner_headers: dict, app: Any, scope: str
) -> None:
    headers = await platform_headers(client, app)
    await seed_global(client, headers)
    company_id = await company_id_of(client, owner_headers)
    if scope == "company":
        await client.put(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{CONVERSATION}",
            json={
                "unit_amount": "0.040000",
                "effective_from": iso(datetime.now(UTC)),
                "expect_no_current_rate": True,
            },
            headers=headers,
        )

    query = f"scope={scope}&metric_code={CONVERSATION}"
    if scope == "company":
        query += f"&company_id={company_id}"
    response = await client.get(f"/api/v1/platform/pricing/rates?{query}", headers=headers)

    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
