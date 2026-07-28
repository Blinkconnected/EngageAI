"""Unit tests for the credential-redaction boundary used by "Test
Connection" and the periodic health-monitoring sweep. See
``docs/architecture/channel-integration-spec.md`` and
``infrastructure/channels/error_sanitizer.py``'s own docstring for the
real incident (a Telegram bot token leaking into broadly-readable
storage) this module exists to close.
"""

import httpx

from blinkengage.domain.channels import HealthStatus
from blinkengage.infrastructure.channels.error_sanitizer import (
    classify_health_check_failure,
    redact_credentials,
    safe_health_check,
)


class _CatchesInternallyProvider:
    """Mirrors TelegramProvider/WhatsAppProvider/_meta_messaging's own
    ``health_check()`` shape: catches its library's ordinary HTTP error
    itself and returns ``HealthStatus(healthy=False, detail=...)``
    directly — it never raises, so this exercises the *return* path, not
    the ``except`` path, of ``safe_health_check``."""

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials

    async def health_check(self) -> HealthStatus:
        token = self._credentials["bot_token"]
        return HealthStatus(
            healthy=False,
            detail=f"Client error '401 Unauthorized' for url 'https://api.telegram.org/bot{token}/getMe'",
        )


class _RaisesProvider:
    """A credential field with an invalid shape can make the underlying
    HTTP client raise before a request is even attempted, in a type the
    provider's own internal try/except doesn't catch — this exercises the
    ``except`` path of ``safe_health_check``."""

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials

    async def health_check(self) -> HealthStatus:
        raise ValueError(f"invalid URL: contains secret {self._credentials['api_key']}")


class _HealthyProvider:
    async def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=True)


class _RaisesHttpStatusErrorProvider:
    """Doesn't catch its own httpx error at all — exercises
    safe_health_check's backstop classifying a *real* httpx.HTTPStatusError
    (as opposed to _RaisesProvider's ValueError, which isn't an httpx
    error at all and must classify as "network")."""

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    async def health_check(self) -> HealthStatus:
        request = httpx.Request("GET", "https://example.com")
        response = httpx.Response(self._status_code, request=request)
        response.raise_for_status()
        return HealthStatus(healthy=True)  # pragma: no cover - unreachable


def test_redact_credentials_replaces_every_known_secret_value() -> None:
    text = "token abc123secret was rejected by host.example.com"
    redacted = redact_credentials(text, {"api_key": "abc123secret", "host": "host.example.com"})
    assert "abc123secret" not in redacted
    assert "host.example.com" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_credentials_ignores_short_values() -> None:
    # Short values (ports, booleans-as-strings) are common substrings of
    # unrelated text — redacting them would mangle ordinary error messages.
    text = "connection refused on port 587"
    assert redact_credentials(text, {"smtp_port": "587"}) == text


async def test_safe_health_check_redacts_credential_returned_directly_in_detail() -> None:
    """The exact bug this test guards against: a provider that catches its
    own HTTP error internally (every current provider does) and returns
    the credential-embedding detail as a normal, non-exception
    HealthStatus — redacting only the ``except`` branch would leave this
    wide open."""
    credentials = {"bot_token": "123456:AA-live-secret-token"}
    status = await safe_health_check(_CatchesInternallyProvider(credentials), credentials)
    assert status.healthy is False
    assert status.detail is not None
    assert "123456:AA-live-secret-token" not in status.detail
    assert "[REDACTED]" in status.detail


async def test_safe_health_check_redacts_credential_from_a_raised_exception() -> None:
    credentials = {"api_key": "sk-live-secret-abc123"}
    status = await safe_health_check(_RaisesProvider(credentials), credentials)
    assert status.healthy is False
    assert status.detail is not None
    assert "sk-live-secret-abc123" not in status.detail
    assert "[REDACTED]" in status.detail


async def test_safe_health_check_passes_through_a_healthy_result_unchanged() -> None:
    status = await safe_health_check(_HealthyProvider(), {"api_key": "sk-live-secret-abc123"})
    assert status == HealthStatus(healthy=True)


async def test_safe_health_check_works_with_no_credentials() -> None:
    status = await safe_health_check(_HealthyProvider(), {})
    assert status.healthy is True


def test_classify_status_401_403_404_as_configuration() -> None:
    """A response that means OUR credentials/setup are wrong — the
    provider's server is reachable and working, it's rejecting us
    specifically."""
    request = httpx.Request("GET", "https://example.com")
    for status_code in (401, 403, 404):
        response = httpx.Response(status_code, request=request)
        exc = httpx.HTTPStatusError("rejected", request=request, response=response)
        assert classify_health_check_failure(exc) == "configuration"


def test_classify_status_5xx_as_provider() -> None:
    """Any other status (5xx, or an unexpected 4xx like 429) means the
    provider's own infrastructure is having a problem, not us."""
    request = httpx.Request("GET", "https://example.com")
    for status_code in (429, 500, 502, 503):
        response = httpx.Response(status_code, request=request)
        exc = httpx.HTTPStatusError("failed", request=request, response=response)
        assert classify_health_check_failure(exc) == "provider"


def test_classify_connection_level_error_as_network() -> None:
    """No response was ever received at all — indistinguishable from
    "their servers are unreachable," not a credentials problem."""
    request = httpx.Request("GET", "https://example.com")
    exc = httpx.ConnectError("connection refused", request=request)
    assert classify_health_check_failure(exc) == "network"


async def test_safe_health_check_classifies_a_provider_side_5xx() -> None:
    status = await safe_health_check(_RaisesHttpStatusErrorProvider(503), {})
    assert status.healthy is False
    assert status.origin == "provider"


async def test_safe_health_check_classifies_an_auth_rejection_as_configuration() -> None:
    status = await safe_health_check(_RaisesHttpStatusErrorProvider(401), {})
    assert status.healthy is False
    assert status.origin == "configuration"


async def test_safe_health_check_classifies_a_non_httpx_exception_as_network() -> None:
    """_RaisesProvider raises a bare ValueError — not an httpx error at
    all, so there's no status code to classify by; treated the same as
    "couldn't reach the server."""
    status = await safe_health_check(_RaisesProvider({"api_key": "sk-live-secret-abc123"}), {})
    assert status.healthy is False
    assert status.origin == "network"


async def test_safe_health_check_preserves_origin_a_provider_already_set() -> None:
    """A provider that classifies its own caught exception (every real
    provider does) sets `origin` on its returned HealthStatus directly —
    safe_health_check must pass that through, not override it."""

    class _AlreadyClassifiedProvider:
        async def health_check(self) -> HealthStatus:
            return HealthStatus(
                healthy=False, detail="getMe returned ok=false", origin="configuration"
            )

    status = await safe_health_check(_AlreadyClassifiedProvider(), {})
    assert status.origin == "configuration"
