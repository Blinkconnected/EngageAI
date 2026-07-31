"""Read-only platform administrators.

Platform authority is otherwise all-or-nothing, deliberately, so that no
tenant role can be edited into it. This tier does not weaken that: it only
ever **narrows** what an operator can do, and a strictly less powerful
principal cannot be an escalation path.

The pairing that matters is that reads stay open while writes close — a
read-only tier that also blocked reading would be pointless, and one that
allowed writing would be a lie.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from blinkengage.api.deps import _READ_ONLY_SAFE_POSTS
from blinkengage.infrastructure.database.models.user import User
from tests.integration.test_pricing_engine import company_id_of, platform_headers

PRICING = "/api/v1/platform/pricing"

#: The two POSTs that write nothing, so the sweep below expects them to be
#: *allowed*. Imported from the gate itself rather than restated here: a
#: second copy of this list is how one of them quietly grows an exemption.
READ_ONLY_SAFE_POSTS = _READ_ONLY_SAFE_POSTS


async def make_read_only(app: Any) -> None:
    async with app.state.container.session_factory()() as session:
        await session.execute(
            update(User)
            .where(User.is_platform_admin.is_(True))
            .values(platform_read_only=True)
        )
        await session.commit()


class TestReadsStayOpen:
    async def test_a_read_only_operator_can_see_effective_pricing(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.get(
            f"{PRICING}/effective", headers=headers, params={"company_id": company_id}
        )

        assert response.status_code == 200

    async def test_a_read_only_operator_can_see_the_history(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The main reason to grant read access at all: auditing what a
        customer was charged, without the authority to change it."""
        headers = await platform_headers(client, app)
        await make_read_only(app)

        assert (await client.get(f"{PRICING}/history", headers=headers)).status_code == 200

    async def test_a_read_only_operator_can_use_the_resolver_preview(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A POST, but a read: it writes nothing, and seeing what the
        resolver will decide is exactly what read access is for."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.post(
            f"{PRICING}/resolve",
            headers=headers,
            json={
                "items": [
                    {
                        "company_id": company_id,
                        "metric_code": "BILLABLE_MESSAGE",
                        "occurred_at": datetime.now(UTC).isoformat(),
                    }
                ],
                "strict": False,
            },
        )

        assert response.status_code == 200

    async def test_the_profile_reports_read_only(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The console needs to know, so it can disable its controls and
        say why rather than letting somebody fill in a form that will be
        refused."""
        headers = await platform_headers(client, app)
        await make_read_only(app)

        response = await client.get("/api/v1/platform/me", headers=headers)

        assert response.json()["read_only"] is True


class TestWritesClose:
    async def test_setting_a_company_price_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.put(
            f"{PRICING}/companies/{company_id}/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.010000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Should not be allowed",
                "expect_no_current_rate": True,
            },
        )

        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    async def test_changing_the_global_price_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await make_read_only(app)

        response = await client.put(
            f"{PRICING}/global/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.010000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Should not be allowed",
            },
        )

        assert response.status_code == 403

    async def test_assigning_a_profile_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.put(
            f"{PRICING}/companies/{company_id}/profile",
            headers=headers,
            json={
                "profile_id": None,
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Should not be allowed",
            },
        )

        assert response.status_code == 403

    async def test_a_full_operator_is_unaffected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The default. Existing platform administrators keep the
        authority they had — the migration backfills the flag to false."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        response = await client.put(
            f"{PRICING}/companies/{company_id}/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.010000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Negotiated",
                "expect_no_current_rate": True,
            },
        )

        assert response.status_code == 201, response.text


class TestEveryPlatformWriteIsGated:
    """The tier applied to the whole platform tier, not just to pricing.

    It was enforced on seven pricing routes and nowhere else, so a read-only
    operator could write off a receivable, post a ledger adjustment, run the
    dunning sweep and suspend a company. Nothing in the console offered those
    actions, which is why it went unnoticed — and the billing console is about
    to render every one of them.

    Discovered from the application's own route table rather than from a list
    somebody has to remember to extend, because the route that ships
    unguarded is always the one added after the list was written.
    """

    #: Methods that only read. Everything else changes something.
    SAFE = frozenset({"GET", "HEAD", "OPTIONS"})

    @staticmethod
    def _mutating_routes(app: Any) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/v1/platform"):
                continue
            for method in getattr(route, "methods", set()) - TestEveryPlatformWriteIsGated.SAFE:
                found.append((method, path))
        return sorted(found)

    @staticmethod
    def _fill(path: str) -> str:
        """A concrete URL for a templated one.

        The ids deliberately do not exist. A refusal must land at the gate,
        before anything is looked up — a read-only operator who gets 404
        rather than 403 has learned whether the row exists, and the check ran
        too late to be a permission.
        """
        filled = path
        while "{" in filled:
            head, _, rest = filled.partition("{")
            name, _, tail = rest.partition("}")
            filled = f"{head}{uuid.uuid4() if 'id' in name.lower() else 'x'}{tail}"
        return filled

    async def test_the_sweep_actually_finds_the_routes(self, app: Any) -> None:
        """A discovery test that discovers nothing passes silently forever."""
        routes = self._mutating_routes(app)
        paths = {path for _method, path in routes}

        assert len(routes) >= 20, routes
        # Named individually so a regression is legible rather than a count.
        assert "/api/v1/platform/ledger/write-offs/{invoice_id}" in paths
        assert "/api/v1/platform/ledger/adjustments" in paths
        assert "/api/v1/platform/payments/collections/run" in paths
        assert "/api/v1/platform/companies/{company_id}/status" in paths

    async def test_a_read_only_operator_is_refused_all_of_them(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await make_read_only(app)

        reached = []
        for method, path in self._mutating_routes(app):
            if path in READ_ONLY_SAFE_POSTS:
                continue
            response = await client.request(method, self._fill(path), headers=headers, json={})
            if response.status_code != 403:
                reached.append(f"{method} {path} -> {response.status_code}")

        assert reached == [], "a read-only operator reached a write route"

    async def test_the_refusal_lands_before_the_lookup(
        self, client: AsyncClient, app: Any
    ) -> None:
        """403 for an id that does not exist, not 404."""
        headers = await platform_headers(client, app)
        await make_read_only(app)

        response = await client.post(
            f"/api/v1/platform/ledger/write-offs/{uuid.uuid4()}",
            headers=headers,
            json={"reason": "probing for existence"},
        )

        assert response.status_code == 403

    async def test_an_operator_who_may_write_still_can(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The gate must refuse the tier, not the route — a guard that blocked
        everybody would pass every assertion above."""
        headers = await platform_headers(client, app)

        response = await client.post(
            "/api/v1/platform/payments/collections/run", headers=headers, json={}
        )

        assert response.status_code == 200, response.text


class TestAuditCurrency:
    async def test_the_history_records_the_rates_own_currency(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A history reading "0.028 USD" for a dinar change is unreadable,
        and worse, looks like a currency mistake somebody made."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await client.put(
            f"{PRICING}/companies/{company_id}/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.035000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Dinar rate",
                "currency": "JOD",
                "expect_no_current_rate": True,
            },
        )

        history = await client.get(
            f"{PRICING}/history", headers=headers, params={"company_id": company_id}
        )

        entry = history.json()[0]
        assert entry["currency"] == "JOD"
