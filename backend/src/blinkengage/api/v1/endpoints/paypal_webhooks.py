"""Public, unauthenticated PayPal webhook ingress. See
``docs/architecture/billing.md``.

Unauthenticated in the HTTP sense — PayPal has no bearer token to
present — but never *unverified*: ``BillingService.handle_webhook``
asks PayPal itself to confirm the signature before acting on anything,
and refuses outright if no ``PAYPAL_WEBHOOK_ID`` is configured. Without
that, anyone who could reach this URL could activate a paid subscription
for free.

**This route always answers 204, even when it rejects the request.** That
is deliberate and the opposite of the usual advice. PayPal retries any
non-2xx delivery for up to three days, so returning an error for an
event we have already durably recorded — or for one we will never
handle — buys nothing but a retry storm against a payment path. The real
outcome goes to the log, and the ``billing_webhook_events`` table is the
durable record of what was accepted.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from blinkengage.api.deps import get_billing_service
from blinkengage.application.services.billing_service import BillingService
from blinkengage.domain.exceptions import BillingNotConfiguredError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/paypal", tags=["billing"])


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def receive_paypal_webhook(
    request: Request,
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> None:
    try:
        body: dict[str, Any] = await request.json()
    except ValueError:
        logger.warning("paypal_webhook_unparseable_body")
        return

    # Header names are lower-cased by Starlette's case-insensitive
    # mapping; the client reads them lower-case to match.
    headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        outcome = await service.handle_webhook(headers=headers, body=body)
    except BillingNotConfiguredError:
        # An installation with no PayPal configuration should not be
        # receiving these at all. Logged loudly, but still 204: retrying
        # will not make credentials appear.
        logger.error("paypal_webhook_received_but_billing_not_configured")
        return

    logger.info(
        "paypal_webhook_processed",
        extra={"event_type": body.get("event_type"), "outcome": outcome},
    )
