"""``FcmPushSender`` — Firebase Cloud Messaging, HTTP v1. See
``docs/architecture/notifications.md``.

One transport reaches Android, iOS and web, because Firebase relays to
APNs itself. That is the reason this is the first transport implemented:
adding APNs directly would mean a second credential type and an HTTP/2
client for the same delivered notification.

**Every rejection is classified, never swallowed.** FCM distinguishes a
dead token from a throttle, and the two need opposite responses — delete
the row, or try again shortly. A transport that logged both identically
would either keep pushing at uninstalled apps forever or quietly drop
notifications during a Google incident.
"""

from typing import Any, Final

import httpx
import orjson

from blinkengage.core.logging import get_logger
from blinkengage.domain.push import (
    DevicePlatform,
    PushMessage,
    PushOutcome,
    PushResult,
    PushSender,
)
from blinkengage.infrastructure.push.service_account import (
    ServiceAccount,
    ServiceAccountError,
    ServiceAccountTokenProvider,
)

logger = get_logger(__name__)

_SEND_URL: Final[str] = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

#: FCM's own error codes that mean "this token will never work again".
#: ``UNREGISTERED`` is an uninstalled app or a rotated token;
#: ``SENDER_ID_MISMATCH`` is a token minted for a different Firebase
#: project, which no amount of retrying will fix either.
_DEAD_TOKEN_CODES: Final[frozenset[str]] = frozenset(
    {"UNREGISTERED", "SENDER_ID_MISMATCH", "INVALID_REGISTRATION"}
)

_SEND_TIMEOUT_SECONDS: Final[float] = 15.0


class FcmPushSender(PushSender):
    transport = "fcm"

    def __init__(self, *, project_id: str, account: ServiceAccount) -> None:
        self._project_id = project_id
        self._tokens = ServiceAccountTokenProvider(account)
        # One client for the sender's lifetime, unlike the per-call
        # `async with httpx.AsyncClient()` the channel providers use. A
        # provider sends one message per request; a dispatch sweep sends a
        # batch, and re-establishing TLS to the same host for each message
        # would make the handshake cost more than the push. Closed by
        # `aclose()`, which the sweep calls in a finally block.
        self._client = httpx.AsyncClient(timeout=_SEND_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(self, message: PushMessage) -> PushResult:
        try:
            access_token = await self._tokens.token(self._client)
        except ServiceAccountError as exc:
            # A credential fault is nobody's device's fault. Retryable, so
            # that fixing the configuration delivers whatever is still
            # inside the dispatch window rather than nothing.
            logger.error("fcm_credentials_unusable", error=str(exc))
            return PushResult(PushOutcome.RETRY, detail="credentials_unusable")

        try:
            response = await self._client.post(
                _SEND_URL.format(project_id=self._project_id),
                content=orjson.dumps({"message": self._build_message(message)}),
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            return PushResult(PushOutcome.RETRY, detail=f"transport:{type(exc).__name__}")

        if response.is_success:
            return PushResult(PushOutcome.DELIVERED)

        error_code = _error_code(response)
        if error_code in _DEAD_TOKEN_CODES or response.status_code == 404:
            return PushResult(PushOutcome.DEVICE_GONE, detail=error_code or "http_404")

        # Everything else — a 401 from a revoked key, a 429 throttle, a
        # 503 during an incident, a 400 from a payload this code got
        # wrong — is retried. The dispatch window bounds how long that
        # can go on, so "retry" can never mean "forever".
        return PushResult(
            PushOutcome.RETRY, detail=error_code or f"http_{response.status_code}"
        )

    def _build_message(self, message: PushMessage) -> dict[str, Any]:
        """The v1 message body.

        ``notification`` is what the operating system renders when the app
        is not in the foreground; ``data`` is what the app reads to open
        the right screen. Both are sent, always — an app that only handled
        ``data`` would show nothing while backgrounded, which is the one
        moment a push exists for.
        """
        body: dict[str, Any] = {
            "token": message.token,
            "notification": {"title": message.title, "body": message.body},
        }
        if message.data:
            body["data"] = dict(message.data)

        if message.platform is DevicePlatform.ANDROID:
            # A conversation assignment is a "come and look now" alert, so
            # it gets the priority that wakes a dozing device. Anything
            # lower is delivered at the system's convenience, which on
            # Android can mean minutes.
            body["android"] = {"priority": "high"}
        elif message.platform is DevicePlatform.IOS:
            body["apns"] = {
                "headers": {"apns-priority": "10"},
                # Without an explicit sound, iOS delivers silently, and a
                # silent alert for "a customer is waiting" is not what
                # anybody enabling push asked for.
                "payload": {"aps": {"sound": "default"}},
            }
        return body


def _error_code(response: httpx.Response) -> str | None:
    """FCM's own error code, dug out of the error envelope.

    Shape: ``{"error": {"status": "NOT_FOUND", "details": [{"@type":
    "...FcmError", "errorCode": "UNREGISTERED"}]}}``. The specific
    ``errorCode`` is the one that distinguishes a dead token, so it wins
    over the generic ``status`` when both are present. Any parse failure
    returns ``None`` and the caller falls back to the HTTP status —
    a body that cannot be read must never be mistaken for a dead device.
    """
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    for detail in error.get("details") or []:
        if isinstance(detail, dict) and detail.get("errorCode"):
            return str(detail["errorCode"])
    status = error.get("status")
    return str(status) if status else None


__all__ = ["FcmPushSender"]
