"""The printed invoice, over the wire.

Three questions this file exists to answer, and each has bitten a billing
system somewhere:

- **Who may download it.** An operator may fetch any company's invoice; a
  tenant may fetch only their own, and asking for somebody else's must not
  even confirm the id exists.
- **What it says.** Not "did bytes come back" — the invoice number, the
  totals and the currency's own decimal places have to be *in* the file,
  because that is what a customer reads.
- **What it refuses.** A draft has no number and has been sent to nobody. A
  file that looks like an invoice but is not one is worse than an error.
"""

import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

# Before the rest of the imports, deliberately: `importorskip` has to run
# first to skip rather than error, and a collection error would take the
# whole tenant-boundary suite down while reading like unrelated noise.
PdfReader = pytest.importorskip("pypdf").PdfReader  # noqa: E402

from httpx import AsyncClient  # noqa: E402

from tests.integration.test_collections_aging import dinar_invoice  # noqa: E402
from tests.integration.test_invoice_engine import (  # noqa: E402
    closed_period_with_usage,
    draft_invoice,
    issued_invoice,
)
from tests.integration.test_pricing_engine import (  # noqa: E402
    company_id_of,
    platform_headers,
    seed_global,
)


def text_of(content: bytes) -> str:
    """Everything the PDF actually says, as a reader's client would see it."""
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() for page in reader.pages)


async def an_issued_invoice(client: AsyncClient, headers: dict, app: Any, company_id: str) -> dict:
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    return (await issued_invoice(client, headers, period_id))["invoice"]


class TestWhatTheDocumentSays:
    async def test_it_is_a_pdf_and_names_the_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)

        response = await client.get(
            f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")
        assert invoice["invoice_number"] in text_of(response.content)

    async def test_it_carries_every_field_a_customer_needs(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The list a finance department checks an invoice against. A
        document missing one of these is one they send back."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)

        response = await client.get(
            f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
        )
        text = text_of(response.content)

        assert invoice["invoice_number"] in text
        assert invoice["customer_name"] in text
        assert invoice["currency"] in text
        assert invoice["due_date"] in text
        # The line, with the three quantities that explain the charge.
        assert "Billable" in text
        assert "Unit price" in text
        assert "Amount outstanding" in text

    async def test_a_dinar_invoice_keeps_its_third_decimal_place(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The fils is real money. A dinar total printed at the dollar's two
        places is wrong on the document a customer pays from."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        invoice = await dinar_invoice(client, headers, app, email="pdf-jod@example.example")

        response = await client.get(
            f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
        )
        text = text_of(response.content)

        assert "JOD" in text
        # 1.750, not 1.75 — three places, from the currency itself.
        assert "1.750" in text

    async def test_it_reads_the_frozen_snapshot_rather_than_reprising_it(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The whole reason an invoice is a copy. Change the price after
        issuance and the document must not move — a bill that rewrites
        itself is one nobody can pay against."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)
        before = text_of(
            (
                await client.get(
                    f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
                )
            ).content
        )

        # Ten times the price, from now on. Not `seed_global`, which
        # refuses to overwrite: this is a genuine repricing, the kind that
        # happens between one month and the next.
        repriced = await client.put(
            "/api/v1/platform/pricing/global/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.500000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "A tenfold increase, after this invoice was issued.",
            },
        )
        assert repriced.status_code in (200, 201), repriced.text

        after = text_of(
            (
                await client.get(
                    f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
                )
            ).content
        )

        assert before == after
        assert Decimal(invoice["total_amount"]) > 0

    async def test_a_credit_note_appears_on_the_invoice_it_corrects(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Both documents are printed, because reconciling them later is the
        entire reason corrections are credit notes rather than edits."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)
        creditable = (
            await client.get(
                f"/api/v1/platform/invoices/{invoice['id']}/creditable", headers=headers
            )
        ).json()
        note = await client.post(
            f"/api/v1/platform/invoices/{invoice['id']}/credit-notes",
            headers=headers,
            json={
                "lines": [
                    {
                        "invoice_line_id": creditable["lines"][0]["invoice_line_id"],
                        "quantity": "1",
                    }
                ],
                "reason": "Billed for a message we sent ourselves.",
            },
        )
        assert note.status_code == 201, note.text

        text = text_of(
            (
                await client.get(
                    f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
                )
            ).content
        )

        assert note.json()["credit_note_number"] in text
        assert "Billed for a message we sent ourselves." in text


class TestWhatItRefuses:
    async def test_a_draft_has_no_pdf(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """It carries no number and has been sent to nobody. A file that
        looks like an invoice but is not one is the most confusing thing
        this endpoint could produce."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        draft = (await draft_invoice(client, headers, period_id))["invoice"]

        response = await client.get(
            f"/api/v1/platform/invoices/{draft['id']}/pdf", headers=headers
        )

        assert response.status_code == 409

    async def test_an_unknown_invoice_is_not_found(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.get(
            "/api/v1/platform/invoices/00000000-0000-0000-0000-000000000000/pdf",
            headers=headers,
        )

        assert response.status_code == 404


class TestTheBoundary:
    async def test_a_customer_can_download_their_own_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)

        response = await client.get(
            f"/api/v1/billing/invoices/{invoice['id']}/pdf", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert invoice["invoice_number"] in text_of(response.content)

    async def test_a_customer_cannot_download_somebody_elses(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """**404, not 403.** Distinguishing "not yours" from "does not
        exist" confirms an invoice id exists, and that is itself a leak
        across tenants."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        theirs = await dinar_invoice(client, headers, app, email="stranger@example.example")

        response = await client.get(
            f"/api/v1/billing/invoices/{theirs['id']}/pdf", headers=owner_headers
        )

        assert response.status_code == 404

    async def test_a_platform_operator_can_download_any(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        theirs = await dinar_invoice(client, headers, app, email="anycompany@example.example")

        response = await client.get(
            f"/api/v1/platform/invoices/{theirs['id']}/pdf", headers=headers
        )

        assert response.status_code == 200, response.text

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/platform/invoices/{invoice_id}/pdf",
            "/api/v1/billing/invoices/{invoice_id}/pdf",
        ],
    )
    async def test_neither_route_answers_without_a_token(
        self, client: AsyncClient, owner_headers: dict, app: Any, path: str
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)

        response = await client.get(path.format(invoice_id=invoice["id"]))

        assert response.status_code in (401, 403)

    async def test_a_tenant_token_cannot_use_the_platform_route(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)

        response = await client.get(
            f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=owner_headers
        )

        assert response.status_code == 403


class TestADocumentThatIsNoLongerABill:
    async def test_a_cancelled_invoice_says_so_on_its_face(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Its only other hint is a zero balance, which is exactly what a
        fully paid invoice shows. A customer who cannot tell the two apart
        pays a withdrawn bill."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await draft_invoice(client, headers, period_id))["invoice"]
        issued = await client.post(
            f"/api/v1/platform/invoices/{invoice['id']}/issue", headers=headers
        )
        assert issued.status_code == 200, issued.text
        cancelled = await client.post(
            f"/api/v1/platform/invoices/{invoice['id']}/cancel",
            headers=headers,
            json={"reason": "Raised against the wrong period."},
        )
        assert cancelled.status_code == 200, cancelled.text

        text = text_of(
            (
                await client.get(
                    f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
                )
            ).content
        )

        assert "CANCELLED" in text
        assert "not payable" in text

    async def test_a_written_off_invoice_says_it_is_no_longer_pursued(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Different from cancelled, and the difference matters: the
        customer still owes it, we have simply stopped asking."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)
        written = await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Liquidated; no prospect of recovery."},
        )
        assert written.status_code in (200, 201), written.text

        text = text_of(
            (
                await client.get(
                    f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
                )
            ).content
        )

        assert "written off" in text
        assert "CANCELLED" not in text

    async def test_an_ordinary_invoice_carries_no_notice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)

        text = text_of(
            (
                await client.get(
                    f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
                )
            ).content
        )

        assert "CANCELLED" not in text
        assert "written off" not in text


class TestTheIssuerIdentifiesItself:
    async def test_the_legal_entity_appears_in_both_languages(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """An invoice is a legal document. The name on it has to be the name
        on the company's registration, and in Jordan that is both scripts."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        invoice = await an_issued_invoice(client, headers, app, company_id)

        text = text_of(
            (
                await client.get(
                    f"/api/v1/platform/invoices/{invoice['id']}/pdf", headers=headers
                )
            ).content
        )

        assert "International Connect for information technology" in text
        # The Arabic is shaped into presentation forms before it is drawn,
        # so the extracted text holds those rather than the base letters —
        # which is the proof it was shaped rather than dumped raw.
        assert any(0xFE70 <= ord(ch) <= 0xFEFF for ch in text)
