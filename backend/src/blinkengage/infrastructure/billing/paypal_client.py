"""``PayPalClient`` — a thin REST wrapper over the PayPal Subscriptions
API. See ``docs/architecture/billing.md``.

Unlike every other outbound integration in this codebase
(WhatsApp/Telegram/ERPNext/OpenAI all authenticate with a static
credential), PayPal requires an OAuth2 client-credentials exchange: the
client id and secret buy a bearer token that expires. The token is
cached in memory and refreshed a minute before expiry, so a burst of
calls costs one token request rather than one per call.

Deliberately no SDK. PayPal's official Python SDK is deprecated for the
v2 APIs, and the surface this product needs is five endpoints — a
dependency that has to be tracked, audited and patched forever is a poor
trade for that.
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

_LIVE_BASE_URL = "https://api-m.paypal.com"
_SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"

# Refresh this many seconds before the token actually expires, so a
# request never leaves with a token that dies in flight.
_TOKEN_REFRESH_MARGIN_SECONDS = 60
_TIMEOUT_SECONDS = 30


class PayPalError(RuntimeError):
    """A PayPal API call failed.

    Carries PayPal's own message where it has one — "PLAN_NOT_ACTIVE"
    or "PAYEE_ACCOUNT_RESTRICTED" tells an operator what to fix, while a
    bare 400 tells them nothing.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class PayPalSubscription:
    """The subset of PayPal's subscription resource this product stores.

    A dataclass rather than the raw dict so the mapping from PayPal's
    wire format lives in one place — callers never index into a provider
    payload by string key.
    """

    subscription_id: str
    status: str
    approval_url: str | None
    next_billing_time: str | None


class PayPalClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        environment: str = "sandbox",
        base_url: str | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = (
            base_url.rstrip("/")
            if base_url
            else (_LIVE_BASE_URL if environment == "live" else _SANDBOX_BASE_URL)
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # --- auth -------------------------------------------------------

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
            raise PayPalError(
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
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            token = await self._access_token(client)
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=json,
                timeout=_TIMEOUT_SECONDS,
            )
        if response.status_code not in expected:
            raise PayPalError(_describe_error(response), status_code=response.status_code)
        if not response.content:
            return {}
        return dict(response.json())

    # --- catalog ----------------------------------------------------

    async def create_product(self, *, name: str, description: str | None) -> str:
        payload: dict[str, Any] = {"name": name, "type": "SERVICE", "category": "SOFTWARE"}
        if description:
            payload["description"] = description
        data = await self._request("POST", "/v1/catalogs/products", json=payload)
        return str(data["id"])

    async def create_plan(
        self,
        *,
        product_id: str,
        name: str,
        description: str | None,
        amount: Decimal,
        currency: str,
        interval_unit: str,
    ) -> str:
        """Creates a PayPal Plan with a single, infinitely-recurring
        billing cycle.

        ``total_cycles: 0`` means "renew forever" — a subscription ends
        because someone cancels it, not because it quietly ran out of
        cycles and stopped billing without anybody noticing.
        """
        payload: dict[str, Any] = {
            "product_id": product_id,
            "name": name,
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {"interval_unit": interval_unit, "interval_count": 1},
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,
                    "pricing_scheme": {
                        "fixed_price": {"value": f"{amount:.2f}", "currency_code": currency}
                    },
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                # PayPal suspends the subscription itself after this many
                # consecutive failures, which is what turns a lapsed
                # payment into a BILLING.SUBSCRIPTION.SUSPENDED webhook
                # we can act on.
                "payment_failure_threshold": 3,
            },
        }
        if description:
            payload["description"] = description
        data = await self._request("POST", "/v1/billing/plans", json=payload)
        return str(data["id"])

    async def deactivate_plan(self, plan_id: str) -> None:
        await self._request("POST", f"/v1/billing/plans/{plan_id}/deactivate")

    # --- subscriptions ----------------------------------------------

    async def create_subscription(
        self,
        *,
        plan_id: str,
        subscriber_email: str | None,
        brand_name: str,
        return_url: str,
        cancel_url: str,
        custom_id: str,
    ) -> PayPalSubscription:
        """Creates a subscription in APPROVAL_PENDING and returns the
        link the customer must visit to approve it.

        ``custom_id`` carries our own company id through PayPal and back
        out on every webhook, so an inbound event can be resolved to a
        tenant even if the subscription row were somehow missing.
        """
        payload: dict[str, Any] = {
            "plan_id": plan_id,
            "custom_id": custom_id,
            "application_context": {
                "brand_name": brand_name,
                "user_action": "SUBSCRIBE_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
                "shipping_preference": "NO_SHIPPING",
            },
        }
        if subscriber_email:
            payload["subscriber"] = {"email_address": subscriber_email}
        data = await self._request("POST", "/v1/billing/subscriptions", json=payload)
        return _to_subscription(data)

    async def get_subscription(self, subscription_id: str) -> PayPalSubscription:
        data = await self._request("GET", f"/v1/billing/subscriptions/{subscription_id}")
        return _to_subscription(data)

    async def cancel_subscription(self, subscription_id: str, *, reason: str) -> None:
        await self._request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/cancel",
            json={"reason": reason},
        )

    # --- webhooks ---------------------------------------------------

    async def verify_webhook_signature(
        self, *, webhook_id: str, headers: dict[str, str], body: dict[str, Any]
    ) -> bool:
        """Asks PayPal whether it really sent this webhook.

        Deliberately the API-based check rather than verifying the
        certificate chain locally: PayPal rotates its signing
        certificates, and an offline verifier that caches or pins them
        fails closed at rotation time — silently rejecting real payment
        events, which is the worst possible failure mode for billing.
        The cost is one extra round trip per webhook, on a path that
        fires a handful of times per customer per month.
        """
        payload = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": webhook_id,
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
        except (PayPalError, httpx.HTTPError) as exc:
            return False, str(exc)
        return True, None


def _to_subscription(data: dict[str, Any]) -> PayPalSubscription:
    approval_url = next(
        (
            str(link["href"])
            for link in data.get("links", [])
            if str(link.get("rel", "")).lower() == "approve"
        ),
        None,
    )
    billing_info = data.get("billing_info") or {}
    return PayPalSubscription(
        subscription_id=str(data["id"]),
        status=str(data.get("status", "APPROVAL_PENDING")),
        approval_url=approval_url,
        next_billing_time=billing_info.get("next_billing_time"),
    )


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
