"""Cross-company invoice search and its CSV export.

The gap these cover is that ``GET /platform/invoices`` *requires* a
company id, so a finance team could not ask "what is overdue" without
already knowing whose — which is the opposite of what a search is for.

Each test pins a rule the endpoint has to enforce rather than merely
intend:

- a company id is optional, so the search spans the installation,
- every page states how many invoices the filter matched,
- money crosses the wire as a string and is only ever grouped by
  currency, never added across them,
- an inclusive date range really includes its last day,
- the export follows the *current filter*, and says so when it stops
  short rather than handing back a quietly shortened file.
"""

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from blinkengage.api.v1.endpoints import platform_invoicing
from tests.integration.test_invoice_engine import (
    closed_period_with_usage,
    draft_invoice,
    issued_invoice,
)
from tests.integration.test_pricing_engine import (
    BILLABLE_MESSAGE,
    company_id_of,
    iso,
    platform_headers,
    seed_global,
)

SEARCH = "/api/v1/platform/invoices/search"


async def register_company(client: AsyncClient, slug: str, **overrides: Any) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": slug.title(),
            "owner_full_name": "Another Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "correct-horse-battery-9",
            **overrides,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["user"]["company"]["id"])


async def issued_for_new_company(
    client: AsyncClient, headers: dict, app: Any, slug: str, *, conversations: int = 1
) -> dict:
    company_id = await register_company(client, slug)
    period_id = await closed_period_with_usage(
        client, headers, app, company_id, conversations=conversations
    )
    return await issued_invoice(client, headers, period_id)


async def issued_in_dinars(client: AsyncClient, headers: dict, app: Any, slug: str) -> dict:
    """An issued invoice denominated in JOD.

    Built through the real pipeline rather than by writing a currency
    onto a row: the point of the cross-currency assertions below is that
    two genuinely different books end up in one search result, and a
    hand-forged invoice would prove nothing about how they got there.
    """
    company_id = await register_company(client, slug, country_code="JO")
    seeded = await client.put(
        f"/api/v1/platform/pricing/global/metrics/{BILLABLE_MESSAGE}",
        headers=headers,
        json={
            "unit_amount": "0.035000",
            "effective_from": iso(datetime(2020, 1, 1, tzinfo=UTC)),
            "reason": "JOD default",
            "currency": "JOD",
            # The price has to cover usage metered before it was
            # configured, and the engine requires that said out loud.
            "allow_backdating": True,
        },
    )
    assert seeded.status_code in (200, 201), seeded.text
    # Past the free monthly allowance, so the invoice is a real charge.
    await client.post(
        "/api/v1/platform/usage/records",
        headers=headers,
        json={
            "company_id": company_id,
            "metric_code": BILLABLE_MESSAGE,
            "quantity": "150",
            "occurred_at": iso(datetime.now(UTC)),
            "idempotency_key": f"jod-{company_id}",
            "note": "Above the allowance",
        },
    )
    current = await client.get(
        f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
    )
    period_id = current.json()["period"]["id"]
    await client.post(f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers)
    return await issued_invoice(client, headers, str(period_id))


def items_of(body: dict) -> list[dict]:
    """Every invoice on the page, regardless of which currency's group it
    landed in."""
    return [item for group in body["currencies"] for item in group["items"]]


def group_for(body: dict, currency: str) -> dict:
    return next(group for group in body["currencies"] if group["currency"] == currency)


class TestTheGap:
    async def test_a_company_id_is_optional(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The whole reason this endpoint exists: the sibling list route
        demands a company id, so nothing could answer a question that
        spans companies."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_for_new_company(client, headers, app, "search-one")

        response = await client.get(SEARCH, headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert len({item["company_id"] for item in items_of(body)}) == 2

    async def test_search_is_matched_before_the_invoice_id_route(
        self, client: AsyncClient, app: Any
    ) -> None:
        """FastAPI matches in declaration order. Registered under
        ``/{invoice_id}``, "search" parses as an invoice UUID and every
        request 422s — a collision this repository has shipped twice."""
        headers = await platform_headers(client, app)

        response = await client.get(SEARCH, headers=headers)

        assert response.status_code == 200, response.text

    async def test_a_tenant_cannot_search(self, client: AsyncClient, owner_headers: dict) -> None:
        """A route that lists every company's invoices is the last one
        that may fall outside the platform boundary."""
        response = await client.get(SEARCH, headers=owner_headers)

        assert response.status_code == 403


class TestPagination:
    async def test_every_page_states_what_the_filter_matched(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """limit/offset without a total cannot render honest pagination:
        a reader cannot tell "that is all of them" from "there are four
        hundred more"."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_for_new_company(client, headers, app, "search-page-a")
        await issued_for_new_company(client, headers, app, "search-page-b")

        first = (await client.get(f"{SEARCH}?limit=2&offset=0", headers=headers)).json()
        second = (await client.get(f"{SEARCH}?limit=2&offset=2", headers=headers)).json()

        assert first["total"] == second["total"] == 3
        assert len(items_of(first)) == 2
        assert len(items_of(second)) == 1
        # Echoed back, so a console paginating from the response alone
        # never has to remember what it asked for.
        assert (first["limit"], first["offset"]) == (2, 0)

    async def test_the_page_is_newest_first(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        first = await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        second = await issued_for_new_company(client, headers, app, "search-order")

        body = (await client.get(SEARCH, headers=headers)).json()

        assert [item["id"] for item in items_of(body)] == [
            second["invoice"]["id"],
            first["invoice"]["id"],
        ]

    async def test_the_totals_describe_the_filter_not_the_page(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Figures that shifted as a reader paged would be read as the
        set itself changing."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_for_new_company(client, headers, app, "search-totals")

        whole = (await client.get(SEARCH, headers=headers)).json()
        one = (await client.get(f"{SEARCH}?limit=1", headers=headers)).json()

        assert len(items_of(one)) == 1
        assert group_for(one, "USD")["invoice_count"] == 2
        assert group_for(one, "USD")["total_amount"] == group_for(whole, "USD")["total_amount"]


class TestMoneyOnTheWire:
    async def test_every_amount_is_a_string(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A JSON number becomes a JavaScript float in the browser, which
        reintroduces exactly the drift ``Decimal`` exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )

        body = (await client.get(SEARCH, headers=headers)).json()

        group = group_for(body, "USD")
        for field in ("total_amount", "amount_paid", "amount_credited", "amount_outstanding"):
            assert isinstance(group[field], str), field
        item = group["items"][0]
        for field in ("subtotal_amount", "total_amount", "amount_paid", "amount_credited"):
            assert isinstance(item[field], str), field

    async def test_no_field_anywhere_spans_two_currencies(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Nothing converts and no exchange rate is stored, so a figure
        adding dinars to dollars would mean nothing.

        Pinned as a *shape* assertion rather than a value one: the only
        way to be sure nobody sums the two books is for the response to
        have no field that could hold the answer, and this fails the day
        somebody adds one.
        """
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        dollars = await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        dinars = await issued_in_dinars(client, headers, app, "search-amman")

        body = (await client.get(SEARCH, headers=headers)).json()

        assert set(body) == {"total", "limit", "offset", "currencies", "export_row_cap"}
        # The one figure spanning currencies is a count, which is the
        # only total that can honestly span them.
        assert body["total"] == 2
        assert [group["currency"] for group in body["currencies"]] == ["JOD", "USD"]
        assert Decimal(group_for(body, "USD")["total_amount"]) == Decimal(
            dollars["invoice"]["total_amount"]
        )
        assert Decimal(group_for(body, "JOD")["total_amount"]) == Decimal(
            dinars["invoice"]["total_amount"]
        )

    async def test_an_invoice_is_only_ever_handed_out_inside_its_own_currency(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A flat mixed list is what invites the sum in the first place.
        Grouping the rows makes it unavailable rather than discouraged."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_in_dinars(client, headers, app, "search-irbid")

        body = (await client.get(SEARCH, headers=headers)).json()

        for group in body["currencies"]:
            assert all(item["currency"] == group["currency"] for item in group["items"])

    async def test_outstanding_is_billed_less_paid_less_credited(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The subtotals are summed from the columns the engine already
        maintains, so a search cannot disagree with the documents it
        lists."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        detail = await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await client.post(
            f"/api/v1/platform/invoices/{detail['invoice']['id']}/credit-notes",
            headers=headers,
            json={
                "lines": [{"description": "Overcounted", "quantity": "1", "unit_amount": "0.05"}],
                "reason": "Duplicate conversations counted after a meter fault",
            },
        )

        group = group_for((await client.get(SEARCH, headers=headers)).json(), "USD")

        assert Decimal(group["total_amount"]) == Decimal("0.20")
        assert Decimal(group["amount_credited"]) == Decimal("0.05")
        assert Decimal(group["amount_outstanding"]) == Decimal("0.15")


class TestFilters:
    async def test_filtering_by_company_status_and_currency(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        issued = await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        other = await issued_for_new_company(client, headers, app, "search-filters")
        await draft_invoice(
            client,
            headers,
            await closed_period_with_usage(
                client, headers, app, await register_company(client, "search-draft")
            ),
        )

        by_company = (
            await client.get(f"{SEARCH}?company_id={own_company}", headers=headers)
        ).json()
        by_status = (await client.get(f"{SEARCH}?status=draft", headers=headers)).json()
        by_currency = (await client.get(f"{SEARCH}?currency=JOD", headers=headers)).json()

        assert [item["id"] for item in items_of(by_company)] == [issued["invoice"]["id"]]
        assert by_status["total"] == 1
        assert items_of(by_status)[0]["status"] == "draft"
        assert other["invoice"]["id"] not in {item["id"] for item in items_of(by_status)}
        # No dinar invoices exist, so the answer is an empty result — with
        # no group at all, rather than a JOD group claiming a zero total.
        assert by_currency == {
            "total": 0,
            "limit": 50,
            "offset": 0,
            "currencies": [],
            "export_row_cap": platform_invoicing.EXPORT_ROW_CAP,
        }

    async def test_a_currency_this_build_cannot_bill_in_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        """An unknown code and an empty result are different answers, and
        filtering on a currency this build cannot bill in would silently
        give the second one to somebody who asked the first."""
        headers = await platform_headers(client, app)

        response = await client.get(f"{SEARCH}?currency=EUR", headers=headers)

        assert response.status_code == 422
        assert "EUR" in response.json()["detail"]

    async def test_a_text_query_matches_part_of_an_invoice_number(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        first = await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_for_new_company(client, headers, app, "search-query")

        body = (await client.get(f"{SEARCH}?q=000001", headers=headers)).json()

        assert body["total"] == 1
        assert items_of(body)[0]["invoice_number"] == first["invoice"]["invoice_number"]

    async def test_a_wildcard_in_the_query_is_a_literal(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """An operator pasting a number containing ``%`` is searching for
        it, not widening their filter to everything."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )

        body = (await client.get(f"{SEARCH}?q=%25", headers=headers)).json()

        assert body["total"] == 0

    async def test_a_cleared_search_box_is_not_a_validation_error(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A console clearing its search box sends ``q=``. Refusing that
        makes the act of *undoing* a filter fail."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )

        response = await client.get(f"{SEARCH}?q=", headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1

    async def test_a_draft_never_matches_a_number_search(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A draft has no number precisely so it cannot be quoted; a
        search by number must not surface one."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await draft_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )

        body = (await client.get(f"{SEARCH}?q=INV", headers=headers)).json()

        assert body["total"] == 0

    async def test_an_issued_date_range_includes_its_last_day(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The bug this pins: comparing an inclusive date against a
        timestamp drops everything issued after midnight on that day,
        which is every invoice on it."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        today = datetime.now(UTC).date()

        inside = (
            await client.get(f"{SEARCH}?issued_from={today}&issued_to={today}", headers=headers)
        ).json()
        before = (
            await client.get(f"{SEARCH}?issued_to={today - timedelta(days=1)}", headers=headers)
        ).json()

        assert inside["total"] == 1
        assert before["total"] == 0

    async def test_an_inverted_date_range_is_refused(self, client: AsyncClient, app: Any) -> None:
        """A range that cannot match anything returns an empty page that
        reads exactly like a real answer."""
        headers = await platform_headers(client, app)

        response = await client.get(
            f"{SEARCH}?issued_from=2026-03-01&issued_to=2026-02-01", headers=headers
        )

        assert response.status_code == 422
        assert "issued_from" in response.json()["detail"]

    async def test_a_never_issued_draft_falls_outside_every_date_range(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await draft_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )

        every_range = f"{SEARCH}?issued_from=2000-01-01&issued_to=2099-01-01"
        body = (await client.get(every_range, headers=headers)).json()

        assert body["total"] == 0


class TestCsvExport:
    async def test_the_export_follows_the_current_filter(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Exporting everything when a filter is on screen hands a
        finance team a file that answers a question they did not ask."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        mine = await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_for_new_company(client, headers, app, "search-export")

        response = await client.get(
            f"{SEARCH}?company_id={own_company}&export=csv", headers=headers
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment; filename=" in response.headers["content-disposition"]
        rows = read_csv(response.content)
        assert len(rows) == 1
        assert rows[0]["invoice_number"] == mine["invoice"]["invoice_number"]

    async def test_the_export_ignores_the_page_and_takes_the_whole_filter(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A download that silently returned only the rows on screen is
        the subtlest way to hand somebody an incomplete reconciliation."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_for_new_company(client, headers, app, "search-export-page")

        response = await client.get(f"{SEARCH}?limit=1&export=csv", headers=headers)

        assert len(read_csv(response.content)) == 2

    async def test_every_row_carries_its_own_currency_and_no_row_totals_them(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A trailing totals row over a mixed-currency column is the
        single number this whole design refuses to produce."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_in_dinars(client, headers, app, "search-zarqa")

        rows = read_csv((await client.get(f"{SEARCH}?export=csv", headers=headers)).content)

        assert len(rows) == 2
        assert {row["currency"] for row in rows} == {"JOD", "USD"}
        # Every row is a document: each has an id, so none of them is a
        # summary line masquerading as one.
        assert all(row["invoice_id"] for row in rows)

    async def test_amounts_export_as_plain_decimals(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """No symbol, no thousands separator, no float — what a
        spreadsheet parses is what the database holds."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )

        row = read_csv((await client.get(f"{SEARCH}?export=csv", headers=headers)).content)[0]

        assert Decimal(row["total_amount"]) == Decimal("0.20")
        assert Decimal(row["amount_outstanding"]) == Decimal("0.20")
        assert row["total_amount"].strip("-").replace(".", "").isdigit()

    async def test_the_cap_is_stated_before_anybody_downloads_anything(
        self, client: AsyncClient, app: Any
    ) -> None:
        """A console can only warn about a short file if it knows the cap
        while the filter is still on screen."""
        headers = await platform_headers(client, app)

        body = (await client.get(SEARCH, headers=headers)).json()

        assert body["export_row_cap"] == platform_invoicing.EXPORT_ROW_CAP

    async def test_an_untruncated_export_says_so(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )

        response = await client.get(f"{SEARCH}?export=csv", headers=headers)

        assert response.headers["x-export-truncated"] == "false"
        assert response.headers["x-export-row-cap"] == str(platform_invoicing.EXPORT_ROW_CAP)
        assert response.headers["x-export-row-count"] == "1"
        assert response.headers["x-export-total-matched"] == "1"
        assert "TRUNCATED" not in response.headers["content-disposition"]

    async def test_a_truncated_export_says_so_in_the_filename_too(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: Any
    ) -> None:
        """Headers are gone the moment the file lands on a disk. Whoever
        opens it next week has only the filename, and a finance team
        reconciling against a silently shortened file is exactly the
        failure a cap is supposed to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        own_company = await company_id_of(client, owner_headers)
        await issued_invoice(
            client, headers, await closed_period_with_usage(client, headers, app, own_company)
        )
        await issued_for_new_company(client, headers, app, "search-cap")
        monkeypatch.setattr(platform_invoicing, "EXPORT_ROW_CAP", 1)

        response = await client.get(f"{SEARCH}?export=csv", headers=headers)

        assert response.headers["x-export-truncated"] == "true"
        assert response.headers["x-export-row-count"] == "1"
        assert response.headers["x-export-total-matched"] == "2"
        assert "TRUNCATED-1-of-2" in response.headers["content-disposition"]
        assert len(read_csv(response.content)) == 1

    async def test_an_export_of_nothing_is_still_a_readable_file(
        self, client: AsyncClient, app: Any
    ) -> None:
        """An empty body would download as a zero-byte file that looks
        like a failed request rather than an empty answer."""
        headers = await platform_headers(client, app)

        response = await client.get(f"{SEARCH}?export=csv", headers=headers)

        assert response.status_code == 200
        assert read_csv(response.content) == []
        assert response.headers["x-export-total-matched"] == "0"


class TestWhatOwedMeans:
    """"Outstanding" has to mean the same thing here as everywhere else.

    Three of these documents look like debts if you only subtract paid and
    credited from the total, and none of them is one. Collections, the
    aging report and the ledger all agree; a search that disagreed would
    be the console's headline receivables figure telling a finance team it
    is owed money nobody is chasing.
    """

    async def test_a_written_off_debt_is_no_longer_owed(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        issued = await issued_for_new_company(client, headers, app, "abandoned")
        invoice = issued["invoice"]

        company = {"company_id": invoice["company_id"]}
        before = await client.get(SEARCH, headers=headers, params=company)
        assert Decimal(group_for(before.json(), "USD")["amount_outstanding"]) > 0

        written = await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Liquidated; no prospect of recovery."},
        )
        assert written.status_code in (200, 201), written.text

        after = await client.get(SEARCH, headers=headers, params=company)
        group = group_for(after.json(), "USD")
        # Still billed — we did bill it, and that stays true.
        assert Decimal(group["total_amount"]) == Decimal(invoice["total_amount"])
        # No longer owed. Nobody is chasing it.
        assert Decimal(group["amount_outstanding"]) == Decimal("0")

    async def test_a_draft_was_never_billed_so_is_not_owed(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        draft = await draft_invoice(client, headers, period_id)

        body = (
            await client.get(SEARCH, headers=headers, params={"company_id": company_id})
        ).json()

        group = group_for(body, "USD")
        assert group["invoice_count"] == 1
        assert Decimal(group["total_amount"]) == Decimal(draft["invoice"]["total_amount"])
        assert Decimal(group["amount_outstanding"]) == Decimal("0")

    async def test_a_cancelled_invoice_was_withdrawn_so_is_not_owed(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        draft = await draft_invoice(client, headers, period_id)
        cancelled = await client.post(
            f"/api/v1/platform/invoices/{draft['invoice']['id']}/cancel",
            headers=headers,
            json={"reason": "Billed against the wrong period."},
        )
        assert cancelled.status_code == 200, cancelled.text

        body = (
            await client.get(SEARCH, headers=headers, params={"company_id": company_id})
        ).json()

        assert Decimal(group_for(body, "USD")["amount_outstanding"]) == Decimal("0")

    async def test_the_search_agrees_with_the_aging_report(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The check that matters. Two endpoints, one question, and the
        console shows them on adjacent screens."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        issued = await issued_for_new_company(client, headers, app, "agreeing")
        company_id = issued["invoice"]["company_id"]

        search = (
            await client.get(SEARCH, headers=headers, params={"company_id": company_id})
        ).json()
        aging = (
            await client.get(
                "/api/v1/platform/payments/collections/aging",
                headers=headers,
                params={"company_id": company_id},
            )
        ).json()

        owed_by_search = Decimal(group_for(search, "USD")["amount_outstanding"])
        owed_by_aging = Decimal(aging["currencies"][0]["total_outstanding"])
        assert owed_by_search == owed_by_aging

    async def test_the_detail_view_agrees_too(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        issued = await issued_for_new_company(client, headers, app, "detail-agrees")
        invoice_id = issued["invoice"]["id"]
        await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice_id}",
            headers=headers,
            json={"reason": "Uncollectable."},
        )

        detail = (
            await client.get(f"/api/v1/platform/invoices/{invoice_id}", headers=headers)
        ).json()

        assert Decimal(detail["amount_outstanding"]) == Decimal("0")
        assert detail["invoice"]["written_off_at"] is not None


class TestTheExportIsData:
    async def test_a_customer_name_cannot_execute_in_a_spreadsheet(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A tenant chooses their own company name; our finance team opens
        the export in Excel. A cell beginning with ``=`` is the one place
        those two facts combine into code execution on a finance laptop."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await register_company(
            client, "formula", company_name="=cmd|' /C calc'!A0"
        )
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        await issued_invoice(client, headers, period_id)

        response = await client.get(
            SEARCH, headers=headers, params={"company_id": company_id, "export": "csv"}
        )

        row = read_csv(response.content)[0]
        # Neutralised, not mangled: the name is still readable, it simply
        # is not a formula any more.
        assert row["customer_name"] == "'=cmd|' /C calc'!A0"
        assert not row["customer_name"].startswith("=")

    async def test_an_ordinary_name_is_left_exactly_as_it_is(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The guard must not touch the 99.9% of names that are fine, or
        every reconciliation export grows a stray apostrophe."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await register_company(client, "ordinary", company_name="Acme Trading")
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        await issued_invoice(client, headers, period_id)

        response = await client.get(
            SEARCH, headers=headers, params={"company_id": company_id, "export": "csv"}
        )

        assert read_csv(response.content)[0]["customer_name"] == "Acme Trading"

    async def test_amounts_are_never_quoted_even_when_negative(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A minus sign leads a formula too — but quoting an amount would
        corrupt the very figures the export exists to carry, so the guard
        is deliberately applied to text only."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        issued = await issued_for_new_company(client, headers, app, "amounts")

        response = await client.get(
            SEARCH,
            headers=headers,
            params={"company_id": issued["invoice"]["company_id"], "export": "csv"},
        )

        row = read_csv(response.content)[0]
        assert Decimal(row["total_amount"]) == Decimal(issued["invoice"]["total_amount"])
        assert not row["total_amount"].startswith("'")


def read_csv(content: bytes) -> list[dict[str, str]]:
    """Parses an exported file the way a spreadsheet would.

    ``utf-8-sig`` because the export carries a byte-order mark: without
    one Excel reads a UTF-8 file as the local codepage and turns an
    Arabic customer name into mojibake.
    """
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


async def test_the_search_reads_and_writes_nothing(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """A read endpoint on a router whose other routes issue documents and
    move money. Running the search must leave the documents exactly as
    they were."""
    headers = await platform_headers(client, app)
    await seed_global(client, headers)
    own_company = await company_id_of(client, owner_headers)
    detail = await issued_invoice(
        client, headers, await closed_period_with_usage(client, headers, app, own_company)
    )
    invoice_id = detail["invoice"]["id"]

    await client.get(f"{SEARCH}?export=csv", headers=headers)
    await client.get(SEARCH, headers=headers)

    after = (await client.get(f"/api/v1/platform/invoices/{invoice_id}", headers=headers)).json()
    assert after["invoice"] == detail["invoice"]
    assert after["lines"] == detail["lines"]


async def test_an_unknown_filter_combination_returns_an_empty_page_not_an_error(
    client: AsyncClient, app: Any
) -> None:
    """A search that matches nothing is a valid answer. Only a filter
    that *cannot* be satisfied — an unknown currency, an inverted range —
    is an error."""
    headers = await platform_headers(client, app)

    body = (await client.get(f"{SEARCH}?company_id={uuid4()}&status=paid", headers=headers)).json()

    assert body == {
        "total": 0,
        "limit": 50,
        "offset": 0,
        "currencies": [],
        "export_row_cap": platform_invoicing.EXPORT_ROW_CAP,
    }


async def test_the_range_is_bounded_at_both_ends(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """``issued_from`` alone and ``issued_to`` alone are both valid; a
    half-specified range must not quietly become no range at all."""
    headers = await platform_headers(client, app)
    await seed_global(client, headers)
    own_company = await company_id_of(client, owner_headers)
    await issued_invoice(
        client, headers, await closed_period_with_usage(client, headers, app, own_company)
    )
    tomorrow: date = datetime.now(UTC).date() + timedelta(days=1)

    from_future = (await client.get(f"{SEARCH}?issued_from={tomorrow}", headers=headers)).json()
    until_future = (await client.get(f"{SEARCH}?issued_to={tomorrow}", headers=headers)).json()

    assert from_future["total"] == 0
    assert until_future["total"] == 1
