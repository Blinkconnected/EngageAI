"""Inbound gateway webhooks — `/api/v1/payment-webhooks/*`.

Its **own router**, mounted outside `/webhooks`, rather than another
path under the channel webhook router. The channel router owns
`/webhooks/{channel_config_id}`, which matches any single path segment
— a PayPal route added there is parsed as a channel id and answered
with a 422 while PayPal records a delivery failure. That exact bug
shipped once already; a separate prefix makes it structurally
impossible rather than a matter of declaration order.

Unauthenticated, like every webhook: the caller is a machine with no
session. Authenticity comes from the provider's signature, which is
verified against the provider itself before anything is acted on. An
unverified webhook is treated as though it never arrived — acting on
one would let anybody who can reach this URL mark an invoice paid.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from blinkengage.api.deps import get_payment_providers, get_payment_service
from blinkengage.application.services.financial_audit_service import AuditActor
from blinkengage.application.services.payment_service import PaymentService
from blinkengage.core.logging import get_logger
from blinkengage.domain.payments import PaymentProviderKind
from blinkengage.infrastructure.payments.registry import (
    PaymentProviderRegistry,
    UnknownProviderError,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/payment-webhooks", tags=["payment-webhooks"])

#: The PayPal events worth acting on. An order that was approved is not
#: money; a capture that completed is. Everything else is logged and
#: acknowledged — a webhook this system does not care about must still
#: get a 200, or PayPal retries it for days.
_CAPTURE_EVENTS = frozenset(
    {
        "CHECKOUT.ORDER.APPROVED",
        "PAYMENT.CAPTURE.COMPLETED",
    }
)


@router.post("/paypal", status_code=status.HTTP_200_OK)
async def paypal_webhook(
    request: Request,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    providers: Annotated[PaymentProviderRegistry, Depends(get_payment_providers)],
) -> dict[str, str]:
    """Receives PayPal's notifications.

    Always answers 200, even when the event is ignored or the signature
    fails. PayPal retries a non-2xx for three days, and a webhook this
    system cannot use will never become usable by being sent again —
    the retry storm is pure noise. What actually happened is in the log
    and, when money moved, in the financial audit trail.
    """
    body: dict[str, Any] = await request.json()
    event_type = str(body.get("event_type", ""))

    try:
        adapter = providers.get(PaymentProviderKind.PAYPAL.value)
    except UnknownProviderError:
        logger.warning("paypal_webhook_unconfigured", event_type=event_type)
        return {"status": "ignored"}

    if not await adapter.verify_webhook(
        headers=dict(request.headers), body=body
    ):
        # Deliberately not a 401. A 401 tells an attacker probing this
        # endpoint that their forgery was detected and that a valid
        # signature would have worked; a 200 that does nothing tells
        # them nothing at all.
        logger.warning("paypal_webhook_unverified", event_type=event_type)
        return {"status": "ignored"}

    if event_type not in _CAPTURE_EVENTS:
        logger.info("paypal_webhook_ignored", event_type=event_type)
        return {"status": "ignored"}

    reference = _order_reference(body)
    if reference is None:
        logger.warning("paypal_webhook_no_order_reference", event_type=event_type)
        return {"status": "ignored"}

    # `capture` does not raise on a decline — a refused card is an
    # ordinary outcome, recorded on the intent rather than thrown. It
    # returns None both for "we do not know this order" and for "the
    # gateway refused it", and neither is something PayPal should retry.
    payment = await payments.capture(
        provider=PaymentProviderKind.PAYPAL.value,
        provider_reference=reference,
        actor=AuditActor.system_actor("PayPal webhook"),
    )
    if payment is None:
        logger.info("paypal_webhook_not_captured", reference=reference)
        return {"status": "ignored"}

    logger.info(
        "paypal_webhook_captured", reference=reference, payment_id=str(payment.id)
    )
    return {"status": "captured"}


def _order_reference(body: dict[str, Any]) -> str | None:
    """Finds the order id, whichever event shape arrived.

    ``CHECKOUT.ORDER.APPROVED`` carries the order as ``resource.id``.
    ``PAYMENT.CAPTURE.COMPLETED`` carries the *capture* as
    ``resource.id`` and the order only as a link — the same trap as the
    retired subscription integration, where the capture id was mistaken
    for the subscription id and every payment was dropped as unknown.
    """
    resource = body.get("resource") or {}
    if not isinstance(resource, dict):
        return None

    supplementary = resource.get("supplementary_data") or {}
    related = (
        supplementary.get("related_ids") if isinstance(supplementary, dict) else None
    ) or {}
    if isinstance(related, dict) and related.get("order_id"):
        return str(related["order_id"])

    for link in resource.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        if str(link.get("rel", "")).lower() == "up":
            href = str(link.get("href", ""))
            if "/checkout/orders/" in href:
                return href.rsplit("/", 1)[-1]

    # Only now fall back to `resource.id`, and only for the event where
    # it genuinely is the order.
    if str(body.get("event_type", "")) == "CHECKOUT.ORDER.APPROVED" and resource.get("id"):
        return str(resource["id"])
    return None


__all__ = ["router"]
