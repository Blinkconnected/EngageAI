"""Unit tests for per-channel-type credential shape validation. See
``docs/architecture/channel-integration-spec.md`` gap #4.
"""

import pytest

from blinkengage.domain.exceptions import InvalidChannelCredentialsError
from blinkengage.infrastructure.channels.credential_schemas import validate_channel_credentials


class TestWhatsApp:
    def test_accepts_complete_credentials(self) -> None:
        validate_channel_credentials(
            "whatsapp",
            {"phone_number_id": "123", "access_token": "tok", "verify_token": "verify"},
        )

    def test_rejects_missing_access_token(self) -> None:
        with pytest.raises(InvalidChannelCredentialsError) as exc_info:
            validate_channel_credentials(
                "whatsapp", {"phone_number_id": "123", "verify_token": "verify"}
            )
        assert "access_token" in str(exc_info.value)

    def test_rejects_empty_string_fields(self) -> None:
        with pytest.raises(InvalidChannelCredentialsError):
            validate_channel_credentials(
                "whatsapp", {"phone_number_id": "", "access_token": "tok", "verify_token": "v"}
            )


class TestTelegram:
    def test_accepts_bot_token(self) -> None:
        validate_channel_credentials("telegram", {"bot_token": "123:abc"})

    def test_rejects_missing_bot_token(self) -> None:
        with pytest.raises(InvalidChannelCredentialsError):
            validate_channel_credentials("telegram", {})


class TestEmail:
    def test_accepts_smtp_only(self) -> None:
        validate_channel_credentials("email", {"smtp_host": "smtp.example.com"})

    def test_accepts_smtp_and_imap(self) -> None:
        validate_channel_credentials(
            "email",
            {
                "smtp_host": "smtp.example.com",
                "imap_host": "imap.example.com",
                "imap_username": "user",
                "imap_password": "pass",
            },
        )

    def test_rejects_missing_smtp_host(self) -> None:
        with pytest.raises(InvalidChannelCredentialsError) as exc_info:
            validate_channel_credentials("email", {"smtp_username": "user"})
        assert "smtp_host" in str(exc_info.value)


class TestWebChat:
    def test_accepts_empty_credentials(self) -> None:
        validate_channel_credentials("web_chat", {})


class TestUnvalidatedChannelTypes:
    def test_messenger_and_instagram_are_now_validated(self) -> None:
        """They were permissive, which is why the console offered them as
        "manual JSON setup": an operator had to know the exact field names
        with nothing checking them, and a typo produced a channel that
        saved cleanly and never delivered a message."""
        for channel_type in ("messenger", "instagram"):
            with pytest.raises(InvalidChannelCredentialsError):
                validate_channel_credentials(channel_type, {})
            # A real access token is all either needs.
            validate_channel_credentials(channel_type, {"access_token": "tok"})

    def test_sms_is_still_unvalidated(self) -> None:
        """SMS has many providers with genuinely different credentials, so
        it keeps the generic form until one is modelled properly. Asserted
        rather than left implicit, so adding a schema is a deliberate
        change to this test and not a silent behaviour shift."""
        validate_channel_credentials("sms", {})
