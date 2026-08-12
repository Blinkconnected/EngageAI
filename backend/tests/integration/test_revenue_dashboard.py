"""The revenue overview: what the Billing Console is allowed to claim.

Every assertion here defends a number a finance team would otherwise quote
without knowing what it is:

- revenue is read from the ledger, not recomputed, so it cannot drift from
  the invoices,
- the reporting window is a *period* and outstanding is a *position*, and the
  response never confuses them,
- two currencies stay two rows, with nowhere to put a combined total,
- the run rate names its own method rather than passing for MRR,
- money crosses the wire as a string.

The clock is never moved. Windows are chosen by passing ``since``/``until``,
which is what the endpoint reads — a test that depended on today's date would
pass in one week of the month and fail in another.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient

from blinkengage.domain.revenue import MINIMUM_DAYS, RunRateMethod
from tests.integration.test_collections_aging import (
    DINAR_INVOICE_TOTAL,
    DOLLAR_INVOICE_TOTAL,
    dinar_invoice,
)
from tests.integration.test_invoice_engine import closed_period_with_usage, issued_invoice
from tests.integration.test_pricing_engine import company_id_of, platform_headers, seed_global

REVENUE = "/api/v1/platform/billing/revenue"


def window(days: int) -> dict[str, str]:
    """A window ending tomorrow, so today's entries fall inside it.

    ``until`` is exclusive everywhere in the billing engine, and an invoice
    issued a moment ago carries a timestamp later than midnight this morning.
    """
    end = datetime.now(UTC).date() + timedelta(days=1)
    return {"since": str(end - timedelta(days=days)), "until": str(end)}


async def dollar_revenue(client: AsyncClient, headers: dict, app: Any, company_id: str) -> dict:
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    return (await issued_invoice(client, headers, period_id))["invoice"]


def row_for(payload: dict, currency: str) -> dict | None:
    return next((r for r in payload["currencies"] if r["currency"] == currency), None)


class TestRevenueComesFromTheLedger:
    async def test_an_issued_invoice_shows_up_as_recognised_revenue(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Issuing is the moment revenue is recognised — it is when the
        ledger entry is written — so the dashboard moves at the same instant
        the customer's invoice does."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        response = await client.get(REVENUE, headers=headers, params=window(30))

        assert response.status_code == 200, response.text
        usd = row_for(response.json(), "USD")
        assert usd is not None
        assert Decimal(usd["revenue"]) == DOLLAR_INVOICE_TOTAL

    async def test_an_unpaid_invoice_is_revenue_and_outstanding_at_once(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Not double counting — the two answer different questions. We have
        earned it (revenue) and we have not been paid it (outstanding), which
        is exactly the state an unpaid invoice is in."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        usd = row_for((await client.get(REVENUE, headers=headers, params=window(30))).json(), "USD")

        assert usd is not None
        assert Decimal(usd["revenue"]) == DOLLAR_INVOICE_TOTAL
        assert Decimal(usd["outstanding"]) == DOLLAR_INVOICE_TOTAL
        assert Decimal(usd["collected"]) == Decimal("0")

    async def test_a_window_before_the_billing_reports_nothing(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The period bound is real. Revenue billed today must not appear in
        last quarter's figures — the bug that makes every historical month
        look like the current one."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        past = {
            "since": str(date(2020, 1, 1)),
            "until": str(date(2020, 2, 1)),
        }
        usd = row_for((await client.get(REVENUE, headers=headers, params=past)).json(), "USD")

        assert usd is not None
        assert Decimal(usd["revenue"]) == Decimal("0")

    async def test_outstanding_ignores_the_window_because_a_debt_does(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Outstanding is a position, not a period figure. Money owed from
        March is still owed in July, and a report that dropped it when the
        window moved would tell a collections team the debt was settled."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        past = {"since": str(date(2020, 1, 1)), "until": str(date(2020, 2, 1))}
        usd = row_for((await client.get(REVENUE, headers=headers, params=past)).json(), "USD")

        assert usd is not None
        assert Decimal(usd["revenue"]) == Decimal("0")
        assert Decimal(usd["outstanding"]) == DOLLAR_INVOICE_TOTAL


class TestNothingSumsAcrossCurrencies:
    async def test_dollars_and_dinars_stay_separate_rows(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        usd_company = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, usd_company)

        await dinar_invoice(client, headers, app, email="revenue.jod@example.example")

        payload = (await client.get(REVENUE, headers=headers, params=window(30))).json()

        assert {r["currency"] for r in payload["currencies"]} == {"USD", "JOD"}
        assert Decimal(row_for(payload, "USD")["revenue"]) == DOLLAR_INVOICE_TOTAL
        assert Decimal(row_for(payload, "JOD")["revenue"]) == DINAR_INVOICE_TOTAL

    async def test_the_response_has_nowhere_to_put_a_combined_total(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Structural rather than a convention somebody has to remember. No
        exchange rate is stored anywhere on purpose, so a figure spanning
        dollars and dinars is not an approximation — it is meaningless."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)

        payload = (await client.get(REVENUE, headers=headers, params=window(30))).json()

        for forbidden in ("total", "total_revenue", "grand_total", "revenue"):
            assert forbidden not in payload, forbidden

    async def test_every_amount_crosses_the_wire_as_a_string(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A JSON number becomes a float in the browser and reintroduces the
        drift ``Decimal`` exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        usd = row_for((await client.get(REVENUE, headers=headers, params=window(30))).json(), "USD")

        assert usd is not None
        for field in ("revenue", "outstanding", "customer_credit", "bad_debt", "collected"):
            assert isinstance(usd[field], str), field
        assert isinstance(usd["run_rate"]["amount"], str)


class TestTheRunRateNamesItsMethod:
    async def test_a_short_window_refuses_to_extrapolate(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Two days scaled by fifteen says more about the window than about
        the business, and somebody would act on it."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        usd = row_for((await client.get(REVENUE, headers=headers, params=window(2))).json(), "USD")

        assert usd is not None
        assert usd["run_rate"]["method"] == RunRateMethod.INSUFFICIENT_HISTORY.value
        assert usd["run_rate"]["is_meaningful"] is False

    async def test_a_long_enough_window_states_the_method_it_used(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        usd = row_for((await client.get(REVENUE, headers=headers, params=window(30))).json(), "USD")

        assert usd is not None
        assert usd["run_rate"]["method"] == RunRateMethod.TRAILING_30_DAY.value
        assert usd["run_rate"]["days_observed"] == 30
        assert usd["run_rate"]["currency"] == "USD"

    async def test_the_rate_scales_the_window_rather_than_reporting_it_raw(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Ten days of billing is a third of a month. Reporting the raw
        window as a monthly figure would understate the business."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await dollar_revenue(client, headers, app, company_id)

        usd = row_for((await client.get(REVENUE, headers=headers, params=window(10))).json(), "USD")

        assert usd is not None
        assert Decimal(usd["run_rate"]["amount"]) == DOLLAR_INVOICE_TOTAL * 3

    async def test_the_threshold_is_the_one_the_domain_states(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)

        at = (await client.get(REVENUE, headers=headers, params=window(MINIMUM_DAYS))).json()
        below = (await client.get(REVENUE, headers=headers, params=window(MINIMUM_DAYS - 1))).json()

        assert all(r["run_rate"]["is_meaningful"] for r in at["currencies"])
        assert not any(r["run_rate"]["is_meaningful"] for r in below["currencies"])


class TestTheWindow:
    async def test_it_defaults_to_the_period_the_rate_is_stated_for(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The headline figure and the rate beside it must describe the same
        thirty days, or the two disagree and neither is wrong."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)

        payload = (await client.get(REVENUE, headers=headers)).json()

        span = date.fromisoformat(payload["period_to"]) - date.fromisoformat(payload["period_from"])
        assert span == timedelta(days=30)
        assert all(r["run_rate"]["days_observed"] == 30 for r in payload["currencies"])

    async def test_a_backwards_window_is_refused_rather_than_returning_zero(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Zero revenue and an impossible window look identical on a tile.
        One is a quiet month; the other is a mistyped date."""
        headers = await platform_headers(client, app)

        response = await client.get(
            REVENUE,
            headers=headers,
            params={"since": "2026-07-01", "until": "2026-06-01"},
        )

        assert response.status_code == 422

    async def test_it_reports_when_the_figures_were_read(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Collections and the daily summaries sweep on a schedule, so a
        console that implied real-time would be lying by omission."""
        headers = await platform_headers(client, app)

        payload = (await client.get(REVENUE, headers=headers)).json()

        assert datetime.fromisoformat(payload["as_of"]).tzinfo is not None


class TestTheBoundary:
    async def test_a_tenant_token_cannot_read_installation_revenue(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Every company's revenue in one response. A customer reaching this
        would be reading their competitors' books."""
        response = await client.get(REVENUE, headers=owner_headers)

        assert response.status_code == 403

    async def test_it_needs_a_token_at_all(self, client: AsyncClient) -> None:
        """401 for no credentials, where the test above asserts 403 for a
        tenant's perfectly valid ones.

        The pair is the clearest statement of the distinction in the suite,
        and it only became true in FastAPI 0.141: before that the bearer
        scheme answered an absent credential with 403, collapsing "who are
        you?" and "not you" into one code.
        """
        assert (await client.get(REVENUE)).status_code == 401
