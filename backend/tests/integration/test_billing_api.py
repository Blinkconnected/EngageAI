"""Subscription billing through PayPal.

The assertions worth having here are the ones that protect money and
access, not the CRUD:

- a replayed webhook must not charge twice,
- an unverified webhook must not activate anything,
- suspension must actually lock the tenant out, and reactivation must
  actually let them back in,
- a payment must never undo a suspension a *human* imposed,
- one tenant must never see another's subscription.

PayPal itself is stubbed. Its wire formats are pinned by the fixtures
below, taken from PayPal's own webhook documentation — the point of these
tests is our reaction to those payloads, not PayPal's uptime.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.api.deps import get_billing_service
from blinkengage.application.services.billing_service import BillingService
from blinkengage.core.security import hash_password
from blinkengage.infrastructure.billing.paypal_client import PayPalSubscription
from blinkengage.infrastructure.database.models.billing import (
    BillingPayment,
    BillingPlan,
    BillingWebhookEvent,
    Subscription,
)
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.billing_repository import (
    BillingPlanRepository,
    PaymentRepository,
    SubscriptionRepository,
    WebhookEventRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository

_PLATFORM_EMAIL = "billing.ops@blinkengage.example"
_PASSWORD = "correct-horse-battery-9"
_WEBHOOK_ID = "WH-TEST-0001"


class FakePayPal:
    """Stands in for ``PayPalClient`` with the same call surface.

    ``verified`` is the switch the signature-rejection test flips — the
    real client asks PayPal to verify a delivery, and the interesting
    behaviour is what we do when PayPal says no.
    """

    def __init__(self) -> None:
        self.verified = True
        self.cancelled: list[str] = []
        self.created_subscriptions: list[str] = []
        self._counter = 0

    async def create_product(self, *, name: str, description: str | None) -> str:
        return "PROD-TEST"

    async def create_plan(self, **kwargs: Any) -> str:
        self._counter += 1
        return f"P-TEST-{self._counter}"

    async def deactivate_plan(self, plan_id: str) -> None:
        return None

    async def create_subscription(self, **kwargs: Any) -> PayPalSubscription:
        self._counter += 1
        subscription_id = f"I-SUB-{self._counter}"
        self.created_subscriptions.append(subscription_id)
        return PayPalSubscription(
            subscription_id=subscription_id,
            status="APPROVAL_PENDING",
            approval_url=f"https://www.sandbox.paypal.com/approve/{subscription_id}",
            next_billing_time=None,
        )

    async def get_subscription(self, subscription_id: str) -> PayPalSubscription:
        return PayPalSubscription(
            subscription_id=subscription_id,
            status="ACTIVE",
            approval_url=None,
            next_billing_time=None,
        )

    async def cancel_subscription(self, subscription_id: str, *, reason: str) -> None:
        self.cancelled.append(subscription_id)

    async def verify_webhook_signature(self, **kwargs: Any) -> bool:
        return self.verified


@pytest.fixture
def paypal(app: Any) -> FakePayPal:
    """Wires a stubbed PayPal into the app and turns billing on.

    Overrides ``get_billing_service`` rather than patching the client
    module, so the service is assembled exactly as production assembles
    it — real repositories, real session, real event publisher.
    """
    fake = FakePayPal()
    settings = app.state.container.settings()
    settings.paypal_webhook_id = _WEBHOOK_ID
    settings.billing_failed_payments_before_suspend = 3

    from typing import Annotated

    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession

    from blinkengage.api.deps import get_db_session, get_event_publisher
    from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher

    def _override(
        session: Annotated[AsyncSession, Depends(get_db_session)],
        events: Annotated[OutboxEventPublisher, Depends(get_event_publisher)],
    ) -> BillingService:
        return BillingService(
            plans=BillingPlanRepository(session),
            subscriptions=SubscriptionRepository(session),
            payments=PaymentRepository(session),
            webhook_events=WebhookEventRepository(session),
            companies=CompanyRepository(session),
            events=events,
            settings=settings,
            paypal=fake,  # type: ignore[arg-type]
        )

    app.dependency_overrides[get_billing_service] = _override
    return fake


async def _platform_headers(client: AsyncClient, app: Any) -> dict[str, str]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        session.add(
            User(
                company_id=None,
                email=_PLATFORM_EMAIL,
                hashed_password=hash_password(_PASSWORD),
                full_name="Billing Operator",
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


async def _create_plan(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> dict:
    payload = {
        "name": "Business",
        "description": "For growing teams",
        "amount": "49.00",
        "currency": "USD",
        "interval": "month",
    } | overrides
    response = await client.post("/api/v1/platform/plans", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _subscribe(client: AsyncClient, owner_headers: dict, plan_id: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscribe", json={"plan_id": plan_id}, headers=owner_headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _event(event_type: str, resource: dict[str, Any], *, event_id: str | None = None) -> dict:
    return {
        "id": event_id or f"WH-EVT-{uuid4()}",
        "event_type": event_type,
        "resource": resource,
    }


def _webhook_headers() -> dict[str, str]:
    """The five headers a genuine PayPal delivery carries. The real
    client refuses to spend a verification round trip without all of
    them, so the stub is fed a complete set."""
    return {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/cert.pem",
        "paypal-transmission-id": str(uuid4()),
        "paypal-transmission-sig": "signature",
        "paypal-transmission-time": "2026-07-29T10:00:00Z",
    }


async def _post_webhook(client: AsyncClient, body: dict) -> None:
    response = await client.post(
        "/api/v1/webhooks/paypal", json=body, headers=_webhook_headers()
    )
    # Always 204 — PayPal retries any non-2xx for three days, so an error
    # response on a payment path buys a retry storm and nothing else.
    assert response.status_code == 204, response.text


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


class TestPlanCatalog:
    async def test_a_platform_admin_publishes_a_plan_to_paypal(
        self, client: AsyncClient, app: Any, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)

        plan = await _create_plan(client, headers)

        assert plan["is_purchasable"] is True
        assert plan["amount"] == "49.00"
        assert plan["interval"] == "month"

    async def test_a_tenant_cannot_manage_the_catalog(
        self, client: AsyncClient, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """The price list is platform property. A company Owner holds
        every tenant permission there is and still cannot edit it."""
        response = await client.post(
            "/api/v1/platform/plans",
            json={"name": "Free For Me", "amount": "0.01", "interval": "month"},
            headers=owner_headers,
        )
        assert response.status_code == 403

    async def test_a_withdrawn_plan_disappears_from_the_tenant_catalog(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)

        await client.patch(
            f"/api/v1/platform/plans/{plan['id']}/status",
            json={"is_active": False},
            headers=headers,
        )

        tenant_plans = await client.get("/api/v1/billing/plans", headers=owner_headers)
        assert [p["id"] for p in tenant_plans.json()] == []
        # ...but the operator still sees it, because they need to know
        # what they have withdrawn.
        all_plans = await client.get("/api/v1/platform/plans", headers=headers)
        assert [p["id"] for p in all_plans.json()] == [plan["id"]]


class TestSubscribing:
    async def test_subscribing_returns_an_approval_link_and_does_not_activate(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """Marking a subscription active on our own say-so would grant a
        paid workspace to anyone who started a checkout and walked away.
        Only PayPal's webhook activates it."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)

        subscription = await _subscribe(client, owner_headers, plan["id"])

        assert subscription["status"] == "approval_pending"
        assert subscription["approval_url"].startswith("https://www.sandbox.paypal.com/approve/")

    async def test_subscribing_twice_is_refused(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """Two live subscriptions means paying twice for one workspace,
        with no way to tell from the product which one is real."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        subscription = await _subscribe(client, owner_headers, plan["id"])
        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.ACTIVATED",
                {"id": paypal.created_subscriptions[0], "status": "ACTIVE"},
            ),
        )
        assert subscription["status"] == "approval_pending"

        again = await client.post(
            "/api/v1/billing/subscribe", json={"plan_id": plan["id"]}, headers=owner_headers
        )

        assert again.status_code == 409
        assert "already has an active subscription" in again.json()["detail"]

    async def test_an_agent_cannot_commit_the_company_to_a_charge(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """`billing.manage` is Owner-only by default — it is the one
        action in the product that moves real money."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        agent_headers = await _make_agent(client, app, owner_headers)

        response = await client.post(
            "/api/v1/billing/subscribe", json={"plan_id": plan["id"]}, headers=agent_headers
        )

        assert response.status_code == 403

    async def test_cancelling_does_not_take_the_workspace_away(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """They have paid through the end of the period. Ending access
        the moment they click cancel would be taking the balance of the
        term they already bought."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])

        response = await client.post(
            "/api/v1/billing/cancel", json={"reason": "Too expensive"}, headers=owner_headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert paypal.cancelled == paypal.created_subscriptions
        # Still working.
        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 200

    async def test_a_company_never_sees_another_companys_billing(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        other_headers = await _register_other_company(client)

        overview = await client.get("/api/v1/billing", headers=other_headers)

        assert overview.status_code == 200
        assert overview.json()["subscription"] is None


class TestWebhooks:
    async def test_activation_marks_the_subscription_active(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])

        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.ACTIVATED",
                {
                    "id": paypal.created_subscriptions[0],
                    "status": "ACTIVE",
                    "billing_info": {"next_billing_time": "2026-08-29T10:00:00Z"},
                },
            ),
        )

        overview = await client.get("/api/v1/billing", headers=owner_headers)
        assert overview.json()["subscription"]["status"] == "active"
        assert overview.json()["subscription"]["current_period_end"] is not None

    async def test_a_replayed_webhook_does_not_charge_twice(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """The single most important test in this file. PayPal delivers
        at-least-once and retries every non-2xx for three days, so the
        same payment arrives more than once as a matter of course."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        payment = _event(
            "PAYMENT.SALE.COMPLETED",
            {
                "id": "CAPTURE-1",
                "billing_agreement_id": paypal.created_subscriptions[0],
                "amount": {"total": "49.00", "currency": "USD"},
                "create_time": "2026-07-29T10:00:00Z",
            },
            event_id="WH-EVT-STABLE",
        )

        await _post_webhook(client, payment)
        await _post_webhook(client, payment)
        await _post_webhook(client, payment)

        overview = await client.get("/api/v1/billing", headers=owner_headers)
        assert len(overview.json()["payments"]) == 1
        assert overview.json()["payments"][0]["amount"] == "49.00"

    async def test_the_same_capture_under_a_new_event_id_is_still_not_charged_twice(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """Belt and braces behind the event-id check: PayPal can report
        the same capture under more than one event, and a duplicated
        charge in the revenue history is a defect a customer disputes."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        resource = {
            "id": "CAPTURE-DUP",
            "billing_agreement_id": paypal.created_subscriptions[0],
            "amount": {"total": "49.00", "currency": "USD"},
            "create_time": "2026-07-29T10:00:00Z",
        }

        await _post_webhook(client, _event("PAYMENT.SALE.COMPLETED", resource))
        await _post_webhook(client, _event("PAYMENT.SALE.COMPLETED", resource))

        overview = await client.get("/api/v1/billing", headers=owner_headers)
        assert len(overview.json()["payments"]) == 1

    async def test_an_unverified_webhook_changes_nothing(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """Anyone can POST to this URL. If an unverified request could
        activate a subscription, the product would be free."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        paypal.verified = False

        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.ACTIVATED",
                {"id": paypal.created_subscriptions[0], "status": "ACTIVE"},
            ),
        )

        overview = await client.get("/api/v1/billing", headers=owner_headers)
        assert overview.json()["subscription"]["status"] == "approval_pending"

    async def test_a_forged_webhook_cannot_burn_a_real_event_id(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """A rejected delivery must not be recorded, or a forger could
        pre-register an event id and make the genuine delivery get
        skipped as a duplicate."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        body = _event(
            "BILLING.SUBSCRIPTION.ACTIVATED",
            {"id": paypal.created_subscriptions[0], "status": "ACTIVE"},
            event_id="WH-EVT-CONTESTED",
        )

        paypal.verified = False
        await _post_webhook(client, body)
        paypal.verified = True
        await _post_webhook(client, body)

        overview = await client.get("/api/v1/billing", headers=owner_headers)
        assert overview.json()["subscription"]["status"] == "active"
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            stored = (
                (
                    await session.execute(
                        select(BillingWebhookEvent).where(
                            BillingWebhookEvent.paypal_event_id == "WH-EVT-CONTESTED"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(stored) == 1

    async def test_an_unknown_event_type_is_ignored_quietly(
        self, client: AsyncClient, app: Any, paypal: FakePayPal
    ) -> None:
        """PayPal sends far more event types than this product
        subscribes to. Erroring on them would turn every unrelated
        account event into a three-day retry storm."""
        await _post_webhook(
            client, _event("CHECKOUT.ORDER.APPROVED", {"id": "irrelevant"})
        )

    async def test_a_webhook_for_an_unknown_subscription_is_ignored(
        self, client: AsyncClient, paypal: FakePayPal
    ) -> None:
        await _post_webhook(
            client,
            _event("BILLING.SUBSCRIPTION.ACTIVATED", {"id": "I-NOT-OURS", "status": "ACTIVE"}),
        )


class TestSuspensionAndRecovery:
    async def test_paypal_suspending_the_subscription_locks_the_tenant_out(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 200

        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.SUSPENDED",
                {"id": paypal.created_subscriptions[0], "status": "SUSPENDED"},
            ),
        )

        response = await client.get("/api/v1/conversations", headers=owner_headers)
        assert response.status_code == 403
        assert "suspended" in response.json()["detail"].lower()

    async def test_one_failed_payment_does_not_lock_anyone_out(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """PayPal retries a declined payment on its own schedule. Taking
        a customer's helpdesk away over one transient decline would be a
        far worse defect than a few days of unpaid service."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])

        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
                {"id": paypal.created_subscriptions[0]},
            ),
        )

        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 200
        overview = await client.get("/api/v1/billing", headers=owner_headers)
        assert overview.json()["subscription"]["failed_payment_count"] == 1

    async def test_repeated_failures_eventually_suspend(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])

        for _ in range(3):
            await _post_webhook(
                client,
                _event(
                    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
                    {"id": paypal.created_subscriptions[0]},
                ),
            )

        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 403

    async def test_a_payment_restores_access_after_a_billing_suspension(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.SUSPENDED",
                {"id": paypal.created_subscriptions[0], "status": "SUSPENDED"},
            ),
        )
        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 403

        await _post_webhook(
            client,
            _event(
                "PAYMENT.SALE.COMPLETED",
                {
                    "id": "CAPTURE-RECOVERY",
                    "billing_agreement_id": paypal.created_subscriptions[0],
                    "amount": {"total": "49.00", "currency": "USD"},
                    "create_time": "2026-07-29T10:00:00Z",
                },
            ),
        )

        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 200

    async def test_a_payment_does_not_undo_a_suspension_an_operator_imposed(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """The asymmetry that matters. A company shut off for abuse must
        stay off, whatever PayPal later reports — otherwise anyone can
        buy their way back in."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        company_id = await _company_id(client, owner_headers)
        await client.patch(
            f"/api/v1/platform/companies/{company_id}/status",
            json={"status": "suspended", "reason": "abuse"},
            headers=headers,
        )

        await _post_webhook(
            client,
            _event(
                "PAYMENT.SALE.COMPLETED",
                {
                    "id": "CAPTURE-BUYBACK",
                    "billing_agreement_id": paypal.created_subscriptions[0],
                    "amount": {"total": "49.00", "currency": "USD"},
                    "create_time": "2026-07-29T10:00:00Z",
                },
            ),
        )

        assert (await client.get("/api/v1/conversations", headers=owner_headers)).status_code == 403

    async def test_a_suspended_company_still_receives_customer_messages(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """A billing dispute must not make the tenant silently drop their
        own customers. Only *their* access is blocked."""
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.SUSPENDED",
                {"id": paypal.created_subscriptions[0], "status": "SUSPENDED"},
            ),
        )

        # The web-chat ingress route is public and untouched by suspension.
        response = await client.post(
            "/api/v1/web-chat/session", json={"company_slug": "acme-corp"}
        )

        assert response.status_code != 403

    async def test_a_billing_suspension_is_recorded_for_audit(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        """Suspending a customer's account is exactly the sort of thing
        that must be reconstructable later — including that a billing
        rule did it, not a person."""
        from blinkengage.infrastructure.database.models.event_outbox import EventOutbox

        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])

        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.SUSPENDED",
                {"id": paypal.created_subscriptions[0], "status": "SUSPENDED"},
            ),
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
        assert events[0].payload["source"] == "billing"
        assert events[0].payload["status"] == "suspended"


class TestUnconfiguredInstallation:
    async def test_billing_reports_itself_unconfigured_rather_than_erroring(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """No ``paypal`` fixture here — this is an installation whose
        operator never connected PayPal. The page must still load and say
        so, rather than offering a Subscribe button that can only fail."""
        response = await client.get("/api/v1/billing", headers=owner_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["is_configured"] is False
        assert body["plans"] == []
        assert body["subscription"] is None

    async def test_subscribing_without_paypal_is_a_clear_503(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/billing/subscribe", json={"plan_id": str(uuid4())}, headers=owner_headers
        )

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"].lower()


class TestPlatformVisibility:
    async def test_the_console_sees_who_is_paying_without_seeing_their_content(
        self, client: AsyncClient, app: Any, owner_headers: dict, paypal: FakePayPal
    ) -> None:
        headers = await _platform_headers(client, app)
        plan = await _create_plan(client, headers)
        await _subscribe(client, owner_headers, plan["id"])
        await _post_webhook(
            client,
            _event(
                "BILLING.SUBSCRIPTION.ACTIVATED",
                {"id": paypal.created_subscriptions[0], "status": "ACTIVE"},
            ),
        )

        companies = await client.get("/api/v1/platform/companies", headers=headers)

        row = companies.json()["items"][0]
        assert row["plan_name"] == "Business"
        assert row["subscription_status"] == "active"
        # The promise still holds: billing state, never billing content.
        assert "settings" not in row
        assert "ai_config" not in row


async def test_money_survives_a_round_trip_without_drifting(app: Any) -> None:
    """Stored as NUMERIC, never a float. 19.99 has no exact binary float
    representation, so a float column turns a price into 19.989999… and
    an invoice total drifts by a cent over enough rows."""
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        company = (await session.execute(select(Company))).scalars().first()
        if company is None:
            company = Company(name="Numeric Co", slug="numeric-co", status=CompanyStatus.TRIAL)
            session.add(company)
            await session.flush()
        plan = BillingPlan(
            name="Cents", amount=Decimal("19.99"), currency="USD", interval="month"
        )
        session.add(plan)
        await session.flush()
        subscription = Subscription(
            company_id=company.id, plan_id=plan.id, paypal_subscription_id="I-NUMERIC"
        )
        session.add(subscription)
        await session.flush()
        session.add(
            BillingPayment(
                company_id=company.id,
                subscription_id=subscription.id,
                paypal_capture_id="CAPTURE-NUMERIC",
                amount=Decimal("19.99"),
                currency="USD",
                status="COMPLETED",
                occurred_at=datetime.now(UTC),
            )
        )
        await session.commit()

    async with session_factory() as session:
        stored = (
            (
                await session.execute(
                    select(BillingPayment).where(
                        BillingPayment.paypal_capture_id == "CAPTURE-NUMERIC"
                    )
                )
            )
            .scalars()
            .one()
        )
        assert stored.amount == Decimal("19.99")
        assert stored.amount * 3 == Decimal("59.97")


async def _register_other_company(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Globex",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea@globex.example",
            "owner_password": _PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


async def _make_agent(client: AsyncClient, app: Any, owner_headers: dict) -> dict[str, str]:
    """Creates an agent and returns their headers.

    ``POST /agents`` puts the new user on the company's default Agent
    role, which deliberately holds neither billing permission.
    """
    email = "agent.billing@acme.example"
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Ann Agent", "password": _PASSWORD},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
