"""Shared GET-handshake / signature-verification logic for every Meta
platform channel (WhatsApp Cloud API, Messenger, Instagram) — all three
use the identical ``hub.challenge`` GET flow and ``X-Hub-Signature-256``
HMAC scheme, only the message-send/receive shape differs between the
Cloud API (WhatsApp) and the Messenger Platform (Messenger/Instagram).
Free functions, not a shared base class, since ``verify_signature``/
``webhook`` are the only overlapping pieces — see
``docs/architecture/whatsapp-telegram.md`` (which introduced this flow)
and ``docs/architecture/messenger-instagram.md``.
"""

import hashlib
import hmac

from blinkengage.domain.channels import WebhookAck, WebhookRequest


def verify_meta_signature(
    request: WebhookRequest, *, webhook_secret: str | None, verify_token: str | None
) -> bool:
    if request.query_params.get("hub.mode") == "subscribe":
        return request.query_params.get("hub.verify_token") == verify_token
    if not webhook_secret:
        return False
    signature = request.headers.get("x-hub-signature-256", "")
    expected = (
        "sha256=" + hmac.new(webhook_secret.encode(), request.body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(signature, expected)


def meta_hub_challenge_ack(request: WebhookRequest) -> WebhookAck | None:
    """Returns the handshake ack if this is a GET challenge request, else
    ``None`` (meaning: proceed to normal ``receive_message`` handling)."""
    if request.query_params.get("hub.mode") == "subscribe":
        return WebhookAck(status_code=200, body=request.query_params.get("hub.challenge"))
    return None
