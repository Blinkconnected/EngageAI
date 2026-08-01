"""Payment processing, reversal, refunds and collections, end to end.

The gateway itself is stubbed — a test that talks to PayPal's sandbox
would be testing PayPal's uptime, not this code. What is *not* stubbed
is everything the money touches: the intent, the payment, the
allocation, the invoice's state machine, the audit trail and the
company's billing standing.

Each test pins a rule the code has to enforce rather than merely intend:

- an abandoned checkout leaves nothing in the ledger,
- capturing twice takes the money once,
- a reversal reopens a settled invoice instead of leaving it "paid",
- allocated money cannot be refunded out from under an invoice,
- a notice is sent once, however often the sweep runs,
- suspension is billing-only and never touches compliance status.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from blinkengage.api.deps import get_payment_providers
from blinkengage.domain.collections import BillingStatus, DunningStage
from blinkengage.domain.payments import PaymentIntentStatus
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.invoicing import Invoice
from blinkengage.infrastructure.payments.base import (
    PaymentProviderError,
    ProviderCapture,
    ProviderIntent,
    ProviderRefund,
)
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry
from tests.integration.test_invoice_engine import closed_period_with_usage, issued_invoice
from tests.integration.test_pricing_engine import (
    company_id_of,
    platform_headers,
    seed_global,
)


class StubProvider:
    """A gateway that does exactly what it is told to.

    Records every call, so a test can assert that a redelivered webhook
    did *not* reach the provider a second time — the difference between
    "idempotent" and "happens to produce the same answer twice".
    """

    def __init__(self) -> None:
        self.kind = "paypal"
        self.created: list[Decimal] = []
        self.captures: list[str] = []
        self.refunds: list[Decimal] = []
        self.capture_fails = False
        self.refund_fails = False
        self.order_status = PaymentIntentStatus.PENDING
        self.verify_webhook_result = True

    async def create_intent(self, **kwargs: Any) -> ProviderIntent:
        self.created.append(kwargs["amount"])
        return ProviderIntent(
            provider_reference=f"ORDER-{len(self.created)}",
            status=PaymentIntentStatus.PENDING,
            approval_url="https://paypal.test/approve",
        )

    async def capture(self, provider_reference: str) -> ProviderCapture:
        self.captures.append(provider_reference)
        if self.capture_fails:
            raise PaymentProviderError("INSTRUMENT_DECLINED", status_code=422)
        return ProviderCapture(
            capture_reference=f"CAPTURE-{provider_reference}",
            amount=self._amount,
            currency="USD",
            status=PaymentIntentStatus.COMPLETED,
        )

    async def get_intent(self, provider_reference: str) -> ProviderIntent:
        return ProviderIntent(provider_reference=provider_reference, status=self.order_status)

    async def refund(self, **kwargs: Any) -> ProviderRefund:
        if self.refund_fails:
            raise PaymentProviderError("REFUND_CAPTURE_TOO_OLD")
        self.refunds.append(kwargs["amount"])
        return ProviderRefund(
            refund_reference=f"REFUND-{len(self.refunds)}",
            amount=kwargs["amount"],
            currency=kwargs["currency"],
            succeeded=True,
        )

    async def verify_webhook(self, **kwargs: Any) -> bool:
        return self.verify_webhook_result

    _amount = Decimal("0.20")


@pytest.fixture
def gateway(app: Any) -> StubProvider:
    """Replaces the registry for the whole app, so both the API routes
    and the services behind them see the same stub."""
    stub = StubProvider()
    app.dependency_overrides[get_payment_providers] = lambda: PaymentProviderRegistry(
        {"paypal": stub, "manual": stub}
    )
    return stub


async def paid_invoice(
    client: AsyncClient, headers: dict, app: Any, company_id: str, gateway: StubProvider
) -> tuple[dict, str]:
    """An issued invoice, paid in full through the gateway."""
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    invoice = (await issued_invoice(client, headers, period_id))["invoice"]
    gateway._amount = Decimal(invoice["total_amount"])

    checkout = await client.post(
        f"/api/v1/platform/payments/checkout/{invoice['id']}",
        headers=headers,
        json={"provider": "paypal"},
    )
    assert checkout.status_code == 201, checkout.text
    reference = checkout.json()["provider_reference"]

    captured = await client.post(
        f"/api/v1/platform/payments/capture/paypal/{reference}", headers=headers
    )
    assert captured.status_code == 200, captured.text
    return invoice, reference


class TestCheckout:
    async def test_an_intent_is_not_a_payment(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """A customer who opens checkout and closes the tab must leave
        nothing in the ledger."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]

        await client.post(
            f"/api/v1/platform/payments/checkout/{invoice['id']}",
            headers=headers,
            json={"provider": "paypal"},
        )

        detail = await client.get(f"/api/v1/platform/invoices/{invoice['id']}", headers=headers)
        assert Decimal(detail.json()["invoice"]["amount_paid"]) == Decimal("0")
        assert detail.json()["invoice"]["status"] == "issued"

    async def test_reloading_returns_the_same_order(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """Otherwise every page load leaves another abandoned order in
        the merchant's dashboard — and two live orders the customer
        could both pay."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]

        first = await client.post(
            f"/api/v1/platform/payments/checkout/{invoice['id']}",
            headers=headers,
            json={"provider": "paypal"},
        )
        second = await client.post(
            f"/api/v1/platform/payments/checkout/{invoice['id']}",
            headers=headers,
            json={"provider": "paypal"},
        )

        assert second.json()["reused"] is True
        assert second.json()["provider_reference"] == first.json()["provider_reference"]
        assert len(gateway.created) == 1

    async def test_a_settled_invoice_cannot_be_paid_again(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)

        again = await client.post(
            f"/api/v1/platform/payments/checkout/{invoice['id']}",
            headers=headers,
            json={"provider": "paypal"},
        )
        assert again.status_code == 409


class TestCapture:
    async def test_capture_records_and_allocates(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)

        detail = await client.get(f"/api/v1/platform/invoices/{invoice['id']}", headers=headers)
        body = detail.json()
        assert body["invoice"]["status"] == "paid"
        assert Decimal(body["invoice"]["amount_paid"]) == Decimal(invoice["total_amount"])
        assert Decimal(body["amount_outstanding"]) == Decimal("0")

    async def test_capturing_twice_takes_the_money_once(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """Gateway webhooks are delivered at least once. Charging twice
        is the one failure a payments integration cannot undo itself."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, reference = await paid_invoice(client, headers, app, company_id, gateway)

        redelivered = await client.post(
            f"/api/v1/platform/payments/capture/paypal/{reference}", headers=headers
        )

        assert redelivered.status_code == 200
        assert len(gateway.captures) == 1, "the provider was called a second time"
        detail = await client.get(f"/api/v1/platform/invoices/{invoice['id']}", headers=headers)
        assert Decimal(detail.json()["invoice"]["amount_paid"]) == Decimal(invoice["total_amount"])

    async def test_a_declined_capture_leaves_the_invoice_unpaid(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        checkout = await client.post(
            f"/api/v1/platform/payments/checkout/{invoice['id']}",
            headers=headers,
            json={"provider": "paypal"},
        )
        gateway.capture_fails = True

        failed = await client.post(
            f"/api/v1/platform/payments/capture/paypal/" f"{checkout.json()['provider_reference']}",
            headers=headers,
        )

        # 200 with a failed intent, not a 5xx or a 409: the decline is
        # an outcome to be recorded, and a rolled-back request would
        # discard the reason the customer needs.
        assert failed.status_code == 200
        assert failed.json()["status"] == "failed"
        detail = await client.get(f"/api/v1/platform/invoices/{invoice['id']}", headers=headers)
        assert detail.json()["invoice"]["status"] == "issued"
        assert Decimal(detail.json()["invoice"]["amount_paid"]) == Decimal("0")

    async def test_the_failure_reason_is_kept_in_the_providers_words(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """ "INSTRUMENT_DECLINED" tells a customer what to fix. "failed"
        tells them nothing."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        await client.post(
            f"/api/v1/platform/payments/checkout/{invoice['id']}",
            headers=headers,
            json={"provider": "paypal"},
        )
        gateway.capture_fails = True
        await client.post("/api/v1/platform/payments/capture/paypal/ORDER-1", headers=headers)

        intents = await client.get(
            f"/api/v1/platform/payments/intents/{company_id}", headers=headers
        )
        intent = intents.json()[0]
        assert intent["status"] == "failed"
        assert "INSTRUMENT_DECLINED" in intent["failure_reason"]


class TestReversal:
    async def test_reversing_reopens_a_settled_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """A chargeback means the money genuinely is not there. An
        invoice frozen at PAID would be the system insisting it has been
        paid when it has not."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)

        allocation_id = await self._allocation_id(client, headers, invoice["id"], app)
        reversed_ = await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": "Chargeback raised by the customer's bank."},
        )

        assert reversed_.status_code == 200, reversed_.text
        assert reversed_.json()["status"] == "issued"
        assert Decimal(reversed_.json()["amount_paid"]) == Decimal("0")

    async def test_reversing_a_late_invoice_reopens_it_as_overdue(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """A reversal does not make a late invoice punctual again."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)

        async with app.state.container.session_factory()() as session:
            await session.execute(
                update(Invoice)
                .where(Invoice.id == uuid.UUID(invoice["id"]))
                .values(due_date=date(2020, 1, 1))
            )
            await session.commit()

        allocation_id = await self._allocation_id(client, headers, invoice["id"], app)
        reversed_ = await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": "Transfer bounced."},
        )

        assert reversed_.json()["status"] == "overdue"

    async def test_a_reversal_must_state_a_reason(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)
        allocation_id = await self._allocation_id(client, headers, invoice["id"], app)

        refused = await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": ""},
        )
        assert refused.status_code == 422

    async def test_reversing_twice_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """Both succeeding would subtract the amount twice and leave the
        invoice showing less paid than was ever allocated to it."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)
        allocation_id = await self._allocation_id(client, headers, invoice["id"], app)

        body = {"reason": "Applied to the wrong invoice."}
        first = await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json=body,
        )
        second = await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json=body,
        )

        assert first.status_code == 200
        assert second.status_code == 409

    async def test_the_reversal_is_audited_with_both_states(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)
        allocation_id = await self._allocation_id(client, headers, invoice["id"], app)
        await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": "Chargeback 4021."},
        )

        trail = await client.get(
            f"/api/v1/platform/invoices/audit/entity/invoice/{invoice['id']}", headers=headers
        )
        reopened = next(
            event for event in trail.json() if event["event_type"] == "invoice.reopened"
        )
        assert reopened["previous_state"] == "paid"
        assert reopened["new_state"] == "issued"
        assert reopened["reason"] == "Chargeback 4021."

    @staticmethod
    async def _allocation_id(client: AsyncClient, headers: dict, invoice_id: str, app: Any) -> str:
        from blinkengage.infrastructure.database.models.invoicing import PaymentAllocation

        async with app.state.container.session_factory()() as session:
            row = await session.execute(
                select(PaymentAllocation.id).where(
                    PaymentAllocation.invoice_id == uuid.UUID(invoice_id),
                    PaymentAllocation.reversed.is_(False),
                )
            )
            return str(row.scalar_one())


class TestRefunds:
    async def test_allocated_money_cannot_be_refunded(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """The obstacle is the point: a refund that silently leaves an
        invoice marked paid is how a ledger drifts from reality."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)
        payment_id = await self._payment_id(client, headers, company_id)

        refused = await client.post(
            f"/api/v1/platform/payments/{payment_id}/refund",
            headers=headers,
            json={"amount": "0.10", "reason": "Customer complaint."},
        )

        assert refused.status_code == 409
        assert "Reverse the allocation first" in refused.json()["detail"]
        assert gateway.refunds == [], "the provider was contacted despite the refusal"

    async def test_refunding_works_once_the_allocation_is_reversed(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)
        allocation_id = await TestReversal._allocation_id(client, headers, invoice["id"], app)
        await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": "Goodwill refund agreed."},
        )
        payment_id = await self._payment_id(client, headers, company_id)

        refunded = await client.post(
            f"/api/v1/platform/payments/{payment_id}/refund",
            headers=headers,
            json={"amount": invoice["total_amount"], "reason": "Goodwill refund agreed."},
        )

        assert refunded.status_code == 201, refunded.text
        assert refunded.json()["status"] == "completed"
        assert Decimal(refunded.json()["amount"]) == Decimal(invoice["total_amount"])

    async def test_a_refund_cannot_exceed_what_is_left(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)
        allocation_id = await TestReversal._allocation_id(client, headers, invoice["id"], app)
        await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": "Refund agreed."},
        )
        payment_id = await self._payment_id(client, headers, company_id)
        body = {"amount": "0.10", "reason": "Partial refund."}
        await client.post(
            f"/api/v1/platform/payments/{payment_id}/refund", headers=headers, json=body
        )

        too_much = await client.post(
            f"/api/v1/platform/payments/{payment_id}/refund",
            headers=headers,
            json={"amount": "0.15", "reason": "The rest."},
        )

        assert too_much.status_code == 409
        assert "already refunded" in too_much.json()["detail"]

    async def test_a_failed_refund_is_recorded_not_lost(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """The row is written before the provider is called. The
        opposite order loses money with no trace when the process dies
        mid-call."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await paid_invoice(client, headers, app, company_id, gateway)
        allocation_id = await TestReversal._allocation_id(client, headers, invoice["id"], app)
        await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": "Refund agreed."},
        )
        payment_id = await self._payment_id(client, headers, company_id)
        gateway.refund_fails = True

        failed = await client.post(
            f"/api/v1/platform/payments/{payment_id}/refund",
            headers=headers,
            json={"amount": "0.10", "reason": "Attempted refund."},
        )

        # 201 with a *failed* refund on the body, not a 409: the row
        # recording the attempt is the point, and raising would roll it
        # back. RefundNotPermittedError still 409s, because that refusal
        # happens before anything is recorded.
        assert failed.status_code == 201
        assert failed.json()["status"] == "failed"
        listed = await client.get(
            f"/api/v1/platform/payments/{payment_id}/refunds", headers=headers
        )
        assert [row["status"] for row in listed.json()] == ["failed"]
        assert "REFUND_CAPTURE_TOO_OLD" in listed.json()[0]["failure_reason"]

    @staticmethod
    async def _payment_id(client: AsyncClient, headers: dict, company_id: str) -> str:
        payments = await client.get(
            f"/api/v1/platform/invoices/payments/company/{company_id}", headers=headers
        )
        return str(payments.json()[0]["id"])


class TestCollections:
    async def test_notices_escalate_as_the_invoice_ages(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])

        await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=3)).isoformat()},
        )

        notices = await client.get(
            f"/api/v1/platform/payments/collections/notices/{invoice['id']}",
            headers=headers,
        )
        assert [row["stage"] for row in notices.json()] == [
            "upcoming",
            "due_today",
            "first_notice",
        ]

    async def test_a_notice_is_sent_once_however_often_the_sweep_runs(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """Nobody has ever been pleased to receive four identical final
        notices."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])
        params = {"today": (due + timedelta(days=3)).isoformat()}

        first = await client.post(
            "/api/v1/platform/payments/collections/run", headers=headers, params=params
        )
        second = await client.post(
            "/api/v1/platform/payments/collections/run", headers=headers, params=params
        )

        assert first.json()["notices_sent"] == 3
        assert second.json()["notices_sent"] == 0

    async def test_the_sequence_ends_in_suspension(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])

        run = await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=21)).isoformat()},
        )

        assert run.json()["suspended"] == [company_id]
        async with app.state.container.session_factory()() as session:
            company = await session.get(Company, uuid.UUID(company_id))
            assert company is not None
            assert company.billing_status is BillingStatus.PAYMENT_SUSPENDED
            # The whole reason these are separate columns.
            assert company.status is not CompanyStatus.SUSPENDED

    async def test_an_exempt_company_is_never_auto_suspended(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])
        await client.put(
            f"/api/v1/platform/payments/collections/{company_id}/exemption",
            headers=headers,
            json={"never_auto_suspend": True, "reason": "Government payment cycle."},
        )

        run = await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=21)).isoformat()},
        )

        assert run.json()["suspended"] == []
        # Still warned, though — the exemption withholds enforcement,
        # not information.
        notices = await client.get(
            f"/api/v1/platform/payments/collections/notices/{invoice['id']}",
            headers=headers,
        )
        assert DunningStage.SUSPENDED.value in [row["stage"] for row in notices.json()]

    async def test_paying_reinstates_the_company(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])
        await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=21)).isoformat()},
        )
        gateway._amount = Decimal(invoice["total_amount"])

        checkout = await client.post(
            f"/api/v1/platform/payments/checkout/{invoice['id']}",
            headers=headers,
            json={"provider": "paypal"},
        )
        await client.post(
            f"/api/v1/platform/payments/capture/paypal/" f"{checkout.json()['provider_reference']}",
            headers=headers,
        )
        run = await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=22)).isoformat()},
        )

        assert run.json()["reinstated"] == [company_id]
        async with app.state.container.session_factory()() as session:
            company = await session.get(Company, uuid.UUID(company_id))
            assert company is not None
            assert company.billing_status is BillingStatus.ACTIVE

    async def test_reinstating_does_not_lift_a_compliance_suspension(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """The single most important consequence of keeping the two
        columns apart."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])
        await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=21)).isoformat()},
        )
        async with app.state.container.session_factory()() as session:
            await session.execute(
                update(Company)
                .where(Company.id == uuid.UUID(company_id))
                .values(status=CompanyStatus.SUSPENDED)
            )
            await session.commit()

        await client.post(
            f"/api/v1/platform/payments/collections/{company_id}/reinstate",
            headers=headers,
            json={"reason": "Paid by wire."},
        )

        async with app.state.container.session_factory()() as session:
            company = await session.get(Company, uuid.UUID(company_id))
            assert company is not None
            assert company.billing_status is not BillingStatus.PAYMENT_SUSPENDED
            assert company.status is CompanyStatus.SUSPENDED

    async def test_billing_standing_reports_the_next_action_date(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        async with app.state.container.session_factory()() as session:
            await session.execute(
                update(Invoice)
                .where(Invoice.id == uuid.UUID(invoice["id"]))
                .values(due_date=date(2020, 1, 1))
            )
            await session.commit()

        standing = await client.get("/api/v1/platform/payments/collections/status", headers=headers)

        row = next(r for r in standing.json() if r["company_id"] == company_id)
        assert row["overdue_invoices"] == 1
        assert row["next_action_on"] is not None


class TestWritingOffEndsThePursuit:
    """Abandoning a receivable used to be ledger-only.

    The invoice kept its OVERDUE status — correctly, since it genuinely was
    never paid — and OVERDUE is what the dunning sweep selects on. So a
    written-off invoice kept sending notices on the same schedule as a live
    one and kept the company suspended indefinitely, because nothing
    downstream ever made it stop being overdue. Finance had no way out of that
    except editing rows.
    """

    async def test_a_written_off_invoice_stops_being_chased(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])

        chased = await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=3)).isoformat()},
        )
        assert chased.json()["notices_sent"] >= 1, "the fixture must actually be chased"

        written = await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Customer entered administration; debt abandoned."},
        )
        assert written.status_code == 200, written.text

        # Far enough forward that every remaining stage would be owed.
        later = await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": (due + timedelta(days=40)).isoformat()},
        )

        assert later.json()["notices_sent"] == 0
        assert later.json()["suspended"] == []

    async def test_it_no_longer_holds_the_company_overdue(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """The status a console shows, and the one suspension is decided
        from."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])
        overdue_day = (due + timedelta(days=3)).isoformat()

        await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": overdue_day},
        )
        standing = await client.get(
            "/api/v1/platform/payments/collections/status",
            headers=headers,
            params={"only_behind": False},
        )
        before = {row["company_id"]: row["billing_status"] for row in standing.json()}
        assert before.get(company_id) == "payment_overdue"

        await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Uncollectable."},
        )
        await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": overdue_day},
        )

        standing = await client.get(
            "/api/v1/platform/payments/collections/status",
            headers=headers,
            params={"only_behind": False},
        )
        after = {row["company_id"]: row["billing_status"] for row in standing.json()}
        assert after.get(company_id) == "active"

    async def test_a_suspended_company_is_released_once_the_debt_is_written_off(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """The failure this fix exists for. A company suspended over a debt
        nobody is pursuing is a company nobody can serve, and before this
        there was no path back that did not involve editing rows."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        due = date.fromisoformat(invoice["due_date"])
        # Past the whole sequence, so the suspension step fires.
        suspend_day = (due + timedelta(days=25)).isoformat()

        run = await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": suspend_day},
        )
        assert company_id in run.json()["suspended"]

        await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Uncollectable."},
        )
        released = await client.post(
            "/api/v1/platform/payments/collections/run",
            headers=headers,
            params={"today": suspend_day},
        )

        assert company_id in released.json()["reinstated"]

    async def test_a_customer_can_still_pay_a_written_off_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """Recovery happens. Writing a debt off is a decision about chasing
        it, not a refusal to accept the money — so the payment path
        deliberately does not consult ``written_off_at``."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]

        await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Uncollectable."},
        )

        payment = await client.post(
            "/api/v1/platform/invoices/payments",
            headers=headers,
            json={
                "company_id": company_id,
                "amount": invoice["total_amount"],
                "currency": invoice["currency"],
                "method": "manual",
                "reference": "recovered-by-phone",
                "received_at": datetime.now(UTC).isoformat(),
            },
        )
        assert payment.status_code == 201, payment.text

        allocated = await client.post(
            f"/api/v1/platform/invoices/payments/{payment.json()['id']}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
        )

        assert allocated.status_code == 200, allocated.text
        # The invoice settles normally. Nothing about having been written off
        # blocks the money, which is the whole point — a write-off decides
        # whether we chase, not whether we accept.
        assert allocated.json()["invoice"]["status"] == "paid"


class TestSuspensionAccess:
    async def test_a_billing_administrator_can_still_sign_in(
        self, client: AsyncClient, owner_headers: dict, app: Any, gateway: StubProvider
    ) -> None:
        """Locking out everyone who can pay turns a late invoice into a
        permanently lost customer."""
        company_id = await company_id_of(client, owner_headers)
        async with app.state.container.session_factory()() as session:
            await session.execute(
                update(Company)
                .where(Company.id == uuid.UUID(company_id))
                .values(billing_status=BillingStatus.PAYMENT_SUSPENDED)
            )
            await session.commit()

        me = await client.get("/api/v1/auth/me", headers=owner_headers)
        assert me.status_code == 200

    async def test_the_message_says_what_to_do_about_it(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """ "Contact your administrator" is useless advice to the
        administrator, who is the person reading it."""
        from blinkengage.domain.exceptions import CompanyNotActiveError

        assert "unpaid invoice" in str(CompanyNotActiveError("payment_suspended"))


ALLOCATIONS = "/api/v1/platform/payments/allocations"


async def allocated_invoice(
    client: AsyncClient,
    headers: dict,
    app: Any,
    company_id: str,
    *,
    reference: str = "WIRE-88",
) -> tuple[dict, str]:
    """An issued invoice, settled by a manually recorded payment.

    Manual rather than through the gateway stub: a bank transfer is the
    payment an operator most often has to find an allocation for again,
    because it is the one that gets applied to the wrong invoice.
    """
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    invoice = (await issued_invoice(client, headers, period_id))["invoice"]
    payment = await client.post(
        "/api/v1/platform/invoices/payments",
        headers=headers,
        json={
            "company_id": company_id,
            "amount": invoice["total_amount"],
            "received_at": datetime.now(UTC).isoformat(),
            "reference": reference,
        },
    )
    assert payment.status_code == 201, payment.text
    allocated = await client.post(
        f"/api/v1/platform/invoices/payments/{payment.json()['id']}/allocate",
        headers=headers,
        json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
    )
    assert allocated.status_code == 200, allocated.text
    return invoice, str(payment.json()["id"])


async def jordanian_company(client: AsyncClient, headers: dict, app: Any) -> str:
    """A company billed in dinars, priced in dinars.

    A second *real* currency rather than a stub one, because the failure
    this guards against — a figure that spans both — only exists when two
    currencies genuinely coexist in the same installation.
    """
    from tests.integration.test_jordan_billing import register

    account = await register(client, app)
    seeded = await client.put(
        "/api/v1/platform/pricing/global/metrics/BILLABLE_MESSAGE",
        headers=headers,
        json={
            "unit_amount": "0.035000",
            "effective_from": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
            "reason": "JOD default",
            "currency": "JOD",
            # Backdated on purpose: the price has to cover usage metered
            # before it was configured, and the engine requires that said
            # out loud.
            "allow_backdating": True,
        },
    )
    assert seeded.status_code in (200, 201), seeded.text
    return str(account["user"]["company"]["id"])


class TestAllocationListing:
    """Finding an allocation — which until now took a SQL client.

    Reversal shipped with the payment engine and the listing did not, so
    the console could offer *Reverse* against an id nothing exposed.
    These pin both halves of closing that: the row is findable, and the
    id on it is the one the reversal route accepts.
    """

    async def test_an_allocation_can_be_found_and_then_reversed(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The gap itself. An operator who cannot find the allocation
        cannot reverse it, however correct the reversal route is."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, payment_id = await allocated_invoice(client, headers, app, company_id)

        listed = await client.get(ALLOCATIONS, headers=headers)

        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["total"] == 1
        row = body["currencies"][0]["allocations"][0]
        # Both documents are named, not merely referenced: an operator
        # decides whether to reverse by reading the invoice number and
        # the payment reference, and a row of bare UUIDs sends them
        # somewhere else to find out what they are looking at.
        assert row["payment_id"] == payment_id
        assert row["payment_reference"] == "WIRE-88"
        assert row["invoice_id"] == invoice["id"]
        assert row["invoice_number"] == invoice["invoice_number"]
        assert Decimal(row["amount"]) == Decimal(invoice["total_amount"])
        assert row["currency"] == invoice["currency"]
        assert row["allocated_at"]
        assert row["reversed"] is False

        reversed_ = await client.post(
            f"{ALLOCATIONS}/{row['id']}/reverse",
            headers=headers,
            json={"reason": "Transfer bounced."},
        )

        # A listing whose ids the reversal route rejects would close
        # nothing, so the round trip is the assertion that matters.
        assert reversed_.status_code == 200, reversed_.text
        assert Decimal(reversed_.json()["amount_paid"]) == Decimal("0")

    async def test_a_reversed_allocation_is_still_listed(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """An allocation is marked reversed, never deleted. A list that
        dropped them would erase the money's history from the only screen
        that shows it — and leave "why is this invoice unpaid again?"
        unanswerable."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, _ = await allocated_invoice(client, headers, app, company_id)
        first = (await client.get(ALLOCATIONS, headers=headers)).json()
        await client.post(
            f"{ALLOCATIONS}/{first['currencies'][0]['allocations'][0]['id']}/reverse",
            headers=headers,
            json={"reason": "Applied to the wrong invoice."},
        )

        body = (await client.get(ALLOCATIONS, headers=headers)).json()

        assert body["total"] == 1
        group = body["currencies"][0]
        row = group["allocations"][0]
        assert row["reversed"] is True
        assert row["reversal_reason"] == "Applied to the wrong invoice."
        assert row["reversed_at"]
        # The amount moves between the two totals rather than vanishing
        # from both: money that was applied and then taken back is a
        # different fact from money that was never applied.
        assert Decimal(group["allocated_total"]) == Decimal("0")
        assert Decimal(group["reversed_total"]) == Decimal(invoice["total_amount"])
        assert group["matching"] == 1

    async def test_the_filters_narrow_to_one_payment_or_one_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """One bank transfer can clear three invoices and one invoice can
        take three transfers, so "everything" is the one view nobody
        investigating a specific document wants."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice, first_payment = await allocated_invoice(
            client, headers, app, company_id, reference="WIRE-1"
        )
        # Reversed so the invoice has room for the second transfer, which
        # is also the commonest reason two allocations exist against one
        # invoice: the first was wrong and was replaced.
        listed = (await client.get(ALLOCATIONS, headers=headers)).json()
        await client.post(
            f"{ALLOCATIONS}/{listed['currencies'][0]['allocations'][0]['id']}/reverse",
            headers=headers,
            json={"reason": "Wrong invoice; re-applying."},
        )
        second_payment = await client.post(
            "/api/v1/platform/invoices/payments",
            headers=headers,
            json={
                "company_id": company_id,
                "amount": invoice["total_amount"],
                "received_at": datetime.now(UTC).isoformat(),
                "reference": "WIRE-2",
            },
        )
        await client.post(
            f"/api/v1/platform/invoices/payments/{second_payment.json()['id']}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
        )

        everything = (await client.get(ALLOCATIONS, headers=headers)).json()
        by_payment = (
            await client.get(ALLOCATIONS, headers=headers, params={"payment_id": first_payment})
        ).json()
        by_invoice = (
            await client.get(ALLOCATIONS, headers=headers, params={"invoice_id": invoice["id"]})
        ).json()
        by_company = (
            await client.get(ALLOCATIONS, headers=headers, params={"company_id": company_id})
        ).json()
        elsewhere = (
            await client.get(ALLOCATIONS, headers=headers, params={"company_id": str(uuid.uuid4())})
        ).json()

        assert everything["total"] == 2
        assert by_payment["total"] == 1
        assert by_payment["currencies"][0]["allocations"][0]["payment_id"] == first_payment
        assert by_invoice["total"] == 2
        assert by_company["total"] == 2
        # A company with no allocations is an empty page, not a 404: the
        # question "what has this customer had applied?" has the answer
        # "nothing", and that is not an error.
        assert elsewhere["total"] == 0
        assert elsewhere["currencies"] == []

    async def test_dinars_and_dollars_are_never_added_together(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Nothing in this build converts and no exchange rate is stored,
        so a total spanning both currencies would be a number that means
        nothing in either. The shape is what prevents one being computed:
        there is no money field anywhere above a currency group."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        usd_company = await company_id_of(client, owner_headers)
        usd_invoice, _ = await allocated_invoice(client, headers, app, usd_company)
        jod_company = await jordanian_company(client, headers, app)
        jod_invoice, _ = await allocated_invoice(
            client, headers, app, jod_company, reference="CLIQ-3"
        )

        body = (await client.get(ALLOCATIONS, headers=headers)).json()

        assert set(body) == {"total", "limit", "offset", "currencies"}
        groups = {group["currency"]: group for group in body["currencies"]}
        assert set(groups) == {jod_invoice["currency"], usd_invoice["currency"]}
        assert Decimal(groups[usd_invoice["currency"]]["allocated_total"]) == Decimal(
            usd_invoice["total_amount"]
        )
        assert Decimal(groups[jod_invoice["currency"]]["allocated_total"]) == Decimal(
            jod_invoice["total_amount"]
        )
        # Counting rows is the one total that has no currency to be wrong
        # in, which is why the page carries a count and not an amount.
        assert body["total"] == sum(group["matching"] for group in body["currencies"]) == 2
        for group in body["currencies"]:
            assert all(row["currency"] == group["currency"] for row in group["allocations"])

    async def test_the_total_counts_the_filter_not_the_page(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A list with limit/offset and no total cannot render honest
        pagination: nothing on the page says whether there is another
        one. The pages must also be disjoint — allocations written in one
        transaction share a timestamp, so an order that did not break the
        tie would show a row twice or not at all."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        for part in ("0.05", "0.05", "0.10"):
            payment = await client.post(
                "/api/v1/platform/invoices/payments",
                headers=headers,
                json={
                    "company_id": company_id,
                    "amount": part,
                    "received_at": datetime.now(UTC).isoformat(),
                },
            )
            allocated = await client.post(
                f"/api/v1/platform/invoices/payments/{payment.json()['id']}/allocate",
                headers=headers,
                json={"invoice_id": invoice["id"], "amount": part},
            )
            assert allocated.status_code == 200, allocated.text

        first = (await client.get(ALLOCATIONS, headers=headers, params={"limit": 2})).json()
        second = (
            await client.get(ALLOCATIONS, headers=headers, params={"limit": 2, "offset": 2})
        ).json()

        assert first["total"] == second["total"] == 3
        first_ids = [row["id"] for row in first["currencies"][0]["allocations"]]
        second_ids = [row["id"] for row in second["currencies"][0]["allocations"]]
        assert len(first_ids) == 2
        assert len(second_ids) == 1
        assert len(set(first_ids) | set(second_ids)) == 3
        # The per-currency totals cover the whole filter, not the page —
        # a figure that shrank as somebody paged through would read as
        # money moving.
        assert Decimal(first["currencies"][0]["allocated_total"]) == Decimal("0.20")
        assert Decimal(second["currencies"][0]["allocated_total"]) == Decimal("0.20")

    async def test_amounts_cross_the_wire_as_strings(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A JSON number becomes a float in the browser, which
        reintroduces exactly the drift ``Decimal`` exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await allocated_invoice(client, headers, app, company_id)

        group = (await client.get(ALLOCATIONS, headers=headers)).json()["currencies"][0]

        assert isinstance(group["allocated_total"], str)
        assert isinstance(group["reversed_total"], str)
        assert isinstance(group["allocations"][0]["amount"], str)
