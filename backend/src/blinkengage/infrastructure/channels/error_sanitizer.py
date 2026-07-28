"""Strips credential values out of provider error text before it's
persisted or returned anywhere. Phase 1: Channel Experience made provider
failures durable and broadly readable for the first time (a ``Message``
row visible to anyone with ``conversations.read``, a
``ChannelConnectionLog``/``ChannelConfig.last_health_detail`` visible to
anyone with ``channels.read``) — a real incident found during that
milestone's review: ``TelegramProvider`` embeds the bot token directly in
its request URL, and ``httpx.HTTPStatusError``'s default message includes
the full request URL, so a routine 401/403 from Telegram put the live bot
token in plaintext into storage any ordinary agent could read. Redacting
every known credential value at the one boundary where provider error
text becomes a stored string closes this for every current and future
provider, not just Telegram's specific URL-embedding pattern.
"""

from typing import Any

import httpx

from blinkengage.domain.channel_provider import ChannelProvider
from blinkengage.domain.channels import HealthCheckOrigin, HealthStatus

_MIN_REDACTABLE_LENGTH = 6  # shorter values (ports, booleans-as-strings) aren't worth redacting

#: A provider's own credentials/setup being wrong — ours to fix, never the
#: provider's infrastructure being down.
_CONFIGURATION_STATUS_CODES = frozenset({401, 403, 404})


def redact_credentials(text: str, credentials: dict[str, Any]) -> str:
    for value in credentials.values():
        if isinstance(value, str) and len(value) >= _MIN_REDACTABLE_LENGTH and value in text:
            text = text.replace(value, "[REDACTED]")
    return text


def classify_health_check_failure(exc: Exception) -> HealthCheckOrigin:
    """Infers whose fault an unhealthy check is from the exception a
    provider's outbound HTTP call raised, so the Status page can say more
    than a flat "unhealthy" — see ``domain.channels.HealthCheckOrigin``
    for what each value means.

    ``httpx.HTTPStatusError`` means the provider's own server actually
    responded — with 401/403/404, that response is rejecting *our*
    credentials/setup (``"configuration"``); any other status (5xx, or an
    unexpected 4xx like 429) is the provider having its own problem
    (``"provider"``). Any other ``httpx.RequestError`` (connect refused,
    DNS failure, timeout) means no response was ever received at all —
    indistinguishable from "their servers are unreachable," so treated
    the same as a provider-side outage (``"network"``, which the Status
    page still reads as "not us"). A provider whose own ``health_check``
    doesn't route through ``httpx`` at all (Email's SMTP/IMAP checks)
    classifies its own failures directly rather than going through this
    function — see ``providers/email.py``.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in _CONFIGURATION_STATUS_CODES:
            return "configuration"
        return "provider"
    return "network"


async def safe_health_check(provider: ChannelProvider, credentials: dict[str, Any]) -> HealthStatus:
    """``ChannelProvider.health_check()`` implementations only catch the
    exception types their own outbound library raises for an ordinary
    rejected request (e.g. ``httpx.HTTPError``) — a credential field with
    an invalid shape (e.g. a stray newline pasted into a URL) can make
    the underlying client raise a *different* exception
    (``httpx.InvalidURL`` is not an ``httpx.HTTPError``) before a request
    is even attempted, which providers don't catch. "Test Connection" and
    the periodic health-monitoring sweep both exist specifically to turn
    a broken credential into a graceful ``HealthStatus(healthy=False,
    ...)``, never an unhandled 500 or a silently-stale status — so both
    call through this one shared, deliberately broad backstop, with the
    same credential redaction ``ConversationService.send_reply`` applies
    to send failures.

    Redaction is applied on *both* return paths, not just the exception
    one: every current provider's own ``health_check()`` already catches
    its library's ordinary HTTP error type internally and returns
    ``HealthStatus(healthy=False, detail=str(exc))`` directly (e.g.
    ``TelegramProvider``, whose bot token sits in the request URL that
    ``httpx.HTTPStatusError``'s default message embeds) — that detail
    reaches here as a normal, non-exception return value, so redacting
    only the ``except`` branch would leave the exact leak this module
    exists to close wide open on a provider's ordinary unhealthy path.
    """
    try:
        status = await provider.health_check()
    except Exception as exc:  # noqa: BLE001 - see docstring
        origin: HealthCheckOrigin = (
            classify_health_check_failure(exc) if isinstance(exc, httpx.HTTPError) else "network"
        )
        return HealthStatus(
            healthy=False, detail=redact_credentials(str(exc), credentials), origin=origin
        )
    if status.detail:
        return HealthStatus(
            healthy=status.healthy,
            detail=redact_credentials(status.detail, credentials),
            origin=status.origin,
        )
    return status
