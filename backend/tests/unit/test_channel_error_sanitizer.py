"""Unit tests for the credential-redaction boundary used by "Test
Connection" and the periodic health-monitoring sweep. See
``docs/architecture/channel-integration-spec.md`` and
``infrastructure/channels/error_sanitizer.py``'s own docstring for the
real incident (a Telegram bot token leaking into broadly-readable
storage) this module exists to close.
"""

from blinkengage.domain.channels import HealthStatus
from blinkengage.infrastructure.channels.error_sanitizer import (
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
