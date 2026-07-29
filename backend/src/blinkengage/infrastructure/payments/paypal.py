"""PayPal, as a ``PaymentProvider``. See ``docs/architecture/billing.md``.

Built on the **Orders v2** API rather than Subscriptions. This product
bills in arrears from measured usage: the amount is not known until the
period closes, so there is nothing for a fixed-price recurring plan to
charge. An order is created for an invoice that already exists, for an
amount already calculated — which also means a pricing change can never
be applied retroactively by a gateway that held a stale plan.

Deliberately no SDK. PayPal's official Python SDK is deprecated for the
v2 APIs, and the surface this needs is six endpoints — a dependency that
has to be tracked, audited and patched forever is a poor trade for that.
"""

import time
from decimal import Decimal
from typing import Any

import httpx

from blinkengage.domain.money import BILLING_CURRENCY
from blinkengage.domain.payments import PaymentIntentStatus, PaymentProviderKind
from blinkengage.infrastructure.payments.base import (
    PaymentProviderError,
    ProviderCapture,
    ProviderIntent,
    ProviderRefund,
)

_LIVE_BASE_URL = "https://api-m.paypal.com"
_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

# Refresh this many seconds before the token actually expires, so a
# request never leaves with a token that dies in flight.
_TOKEN_REFRESH_MARGIN_SECONDS = 60
_TIMEOUT_SECONDS = 30

#: PayPal order status -> our neutral vocabulary. ``APPROVED`` is
#: deliberately still PENDING: the customer has agreed, but no money has
#: moved until the capture succeeds, and recording it as complete at
#: approval time would book revenue that can still fail.
_ORDER_STATUS: dict[str, PaymentIntentStatus] = {
    "CREATED": PaymentIntentStatus.PENDING,
    "SAVED": PaymentIntentStatus.PENDING,
    "APPROVED": PaymentIntentStatus.PENDING,
    "PAYER_ACTION_REQUIRED": PaymentIntentStatus.PENDING,
    "COMPLETED": PaymentIntentStatus.COMPLETED,
    "VOIDED": PaymentIntentStatus.CANCELLED,
}


class PayPalProvider:
    """A thin REST wrapper over PayPal Orders v2.

    Unlike every other outbound integration in this codebase
    (WhatsApp/Telegram/ERPNext/OpenAI all authenticate with a static
    credential), PayPal requires an OAuth2 client-credentials exchange:
    the client id and secret buy a bearer token that expires. The token
    is cached in memory and refreshed a minute before expiry, so a burst
    of calls costs one token request rather than one per call.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        webhook_id: str | None = None,
        sandbox: bool = True,
        brand_name: str = "Blink Engage",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._webhook_id = webhook_id
        self._brand_name = brand_name
        self._base_url = _SANDBOX_BASE_URL if sandbox else _LIVE_BASE_URL
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def kind(self) -> str:
        return PaymentProviderKind.PAYPAL.value

    # --- transport ---------------------------------------------------

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        response = await client.post(
            f"{self._base_url}/v1/oauth2/token",
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            # Never echo the response body here — a failed token exchange
            # is almost always a bad client id/secret, and PayPal's error
            # payload repeats the credential back.
            raise PaymentProviderError(
                "PayPal rejected the configured API credentials.",
                status_code=response.status_code,
            )
        payload = response.json()
        self._token = str(payload["access_token"])
        lifetime = float(payload.get("expires_in", 3600))
        self._token_expires_at = time.monotonic() + lifetime - _TOKEN_REFRESH_MARGIN_SECONDS
        return self._token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if idempotency_key is not None:
            # PayPal's own replay protection. A retried capture after a
            # network timeout returns the original result instead of
            # taking the money twice — the one failure mode a payments
            # integration cannot recover from on its own.
            headers["PayPal-Request-Id"] = idempotency_key
        async with httpx.AsyncClient() as client:
            token = await self._access_token(client)
            headers["Authorization"] = f"Bearer {token}"
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json,
                timeout=_TIMEOUT_SECONDS,
            )
        if response.status_code not in expected:
            raise PaymentProviderError(_describe_error(response), status_code=response.status_code)
        if not response.content:
            return {}
        return dict(response.json())

    # --- payments ----------------------------------------------------

    async def create_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str,
        description: str,
        return_url: str,
        cancel_url: str,
    ) -> ProviderIntent:
        """Creates a PayPal order for an invoice.

        ``reference`` is the invoice number, sent as ``invoice_id`` so it
        appears on the customer's PayPal receipt and in the merchant's
        transaction search. That is what makes a disputed charge
        traceable back to a document six months later.
        """
        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "invoice_id": reference,
                    "description": description[:127],
                    "amount": {
                        "currency_code": currency,
                        # PayPal takes two decimal places for USD and
                        # rejects more. The invoice total is already
                        # rounded to the currency's scale by the billing
                        # engine, so this formats rather than rounds.
                        "value": f"{amount:.2f}",
                    },
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": self._brand_name,
                        "user_action": "PAY_NOW",
                        "return_url": return_url,
                        "cancel_url": cancel_url,
                    }
                }
            },
        }
        data = await self._request(
            "POST", "/v2/checkout/orders", json=payload, idempotency_key=f"order-{reference}"
        )
        return _to_intent(data)

    async def capture(self, provider_reference: str) -> ProviderCapture:
        data = await self._request(
            "POST",
            f"/v2/checkout/orders/{provider_reference}/capture",
            json={},
            idempotency_key=f"capture-{provider_reference}",
        )
        capture = _first_capture(data)
        if capture is None:
            raise PaymentProviderError(
                f"PayPal order {provider_reference} was captured but returned no capture."
            )
        amount = capture.get("amount") or {}
        return ProviderCapture(
            capture_reference=str(capture["id"]),
            amount=Decimal(str(amount.get("value", "0"))),
            currency=str(amount.get("currency_code", BILLING_CURRENCY.code)),
            status=_ORDER_STATUS.get(
                str(capture.get("status", "")).upper(), PaymentIntentStatus.PENDING
            ),
        )

    async def get_intent(self, provider_reference: str) -> ProviderIntent:
        data = await self._request("GET", f"/v2/checkout/orders/{provider_reference}")
        return _to_intent(data)

    async def refund(
        self, *, capture_reference: str, amount: Decimal, currency: str, reason: str
    ) -> ProviderRefund:
        """Refunds a capture, wholly or in part.

        Against the *capture*, not the order: PayPal refunds money that
        moved, and the order is only the request that moved it.
        """
        payload = {
            "amount": {"value": f"{amount:.2f}", "currency_code": currency},
            "note_to_payer": reason[:255],
        }
        data = await self._request(
            "POST",
            f"/v2/payments/captures/{capture_reference}/refund",
            json=payload,
            idempotency_key=f"refund-{capture_reference}-{amount:.2f}",
        )
        refunded = data.get("amount") or {}
        status = str(data.get("status", "")).upper()
        return ProviderRefund(
            refund_reference=str(data["id"]),
            amount=Decimal(str(refunded.get("value", amount))),
            currency=str(refunded.get("currency_code", currency)),
            # PENDING is treated as success-in-progress: PayPal has
            # accepted the refund and will settle it. Only a hard failure
            # state means the money is staying put.
            succeeded=status in {"COMPLETED", "PENDING"},
        )

    # --- webhooks ----------------------------------------------------

    async def verify_webhook(self, *, headers: dict[str, str], body: dict[str, Any]) -> bool:
        """Asks PayPal whether it really sent this webhook.

        Deliberately the API-based check rather than verifying the
        certificate chain locally: PayPal rotates its signing
        certificates, and an offline verifier that caches or pins them
        fails closed at rotation time — silently rejecting real payment
        events, which is the worst possible failure mode for billing.
        The cost is one extra round trip per webhook, on a path that
        fires a handful of times per customer per month.
        """
        if not self._webhook_id:
            # No configured webhook id means nothing can be verified.
            # Fail closed: an unverifiable webhook that marks invoices
            # paid is worse than no webhook at all.
            return False
        lowered = {key.lower(): value for key, value in headers.items()}
        payload = {
            "auth_algo": lowered.get("paypal-auth-algo", ""),
            "cert_url": lowered.get("paypal-cert-url", ""),
            "transmission_id": lowered.get("paypal-transmission-id", ""),
            "transmission_sig": lowered.get("paypal-transmission-sig", ""),
            "transmission_time": lowered.get("paypal-transmission-time", ""),
            "webhook_id": self._webhook_id,
            "webhook_event": body,
        }
        if not all(
            payload[key]
            for key in (
                "auth_algo",
                "cert_url",
                "transmission_id",
                "transmission_sig",
                "transmission_time",
            )
        ):
            # A genuine PayPal delivery always carries all five. A
            # request missing any of them is not worth a round trip.
            return False
        data = await self._request(
            "POST", "/v1/notifications/verify-webhook-signature", json=payload
        )
        return str(data.get("verification_status", "")).upper() == "SUCCESS"

    async def health_check(self) -> tuple[bool, str | None]:
        try:
            async with httpx.AsyncClient() as client:
                await self._access_token(client)
        except (PaymentProviderError, httpx.HTTPError) as exc:
            return False, str(exc)
        return True, None


def _to_intent(data: dict[str, Any]) -> ProviderIntent:
    approval_url = next(
        (
            str(link["href"])
            for link in data.get("links", [])
            if str(link.get("rel", "")).lower() in {"approve", "payer-action"}
        ),
        None,
    )
    return ProviderIntent(
        provider_reference=str(data["id"]),
        status=_ORDER_STATUS.get(str(data.get("status", "")).upper(), PaymentIntentStatus.PENDING),
        approval_url=approval_url,
    )


def _first_capture(data: dict[str, Any]) -> dict[str, Any] | None:
    for unit in data.get("purchase_units", []):
        captures = (unit.get("payments") or {}).get("captures") or []
        if captures:
            return dict(captures[0])
    return None


def _describe_error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"PayPal returned {response.status_code}."
    name = body.get("name") or body.get("error")
    message = body.get("message") or body.get("error_description")
    details = body.get("details") or []
    issue = details[0].get("issue") if details and isinstance(details[0], dict) else None
    parts = [str(part) for part in (name, issue, message) if part]
    return " — ".join(parts) if parts else f"PayPal returned {response.status_code}."


__all__ = ["PayPalProvider"]
