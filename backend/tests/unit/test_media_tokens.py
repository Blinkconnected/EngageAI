"""Signed, short-lived media URLs.

The properties that matter are all about what a leaked URL can do: it must
be useless after minutes, useless against a different attachment, and
useless against another tenant.
"""

import uuid

import pytest

from blinkengage.core.config import Settings
from blinkengage.core.media_tokens import (
    DEFAULT_TTL_SECONDS,
    MediaTokenError,
    sign,
    verify,
)

NOW = 1_800_000_000


def _settings() -> Settings:
    return Settings(
        jwt_secret_key="a" * 40,
        credentials_encryption_key="b" * 40,
        database_url="sqlite+aiosqlite:///:memory:",
    )


class TestRoundTrip:
    def test_a_fresh_signature_verifies(self) -> None:
        settings = _settings()
        attachment, company = uuid.uuid4(), uuid.uuid4()
        token = sign(
            attachment_id=attachment,
            company_id=company,
            settings=settings,
            now=NOW,
        )

        verify(
            attachment_id=attachment,
            company_id=company,
            expires_at=token.expires_at,
            signature=token.signature,
            settings=settings,
            now=NOW + 1,
        )

    def test_the_default_lifetime_is_minutes_not_hours(self) -> None:
        """Long enough to load and scrub a large video; short enough that a
        URL captured in a log or pasted into a chat is already useless."""
        assert 60 <= DEFAULT_TTL_SECONDS <= 3600


class TestWhatALeakedUrlCannotDo:
    def test_it_expires(self) -> None:
        settings = _settings()
        attachment, company = uuid.uuid4(), uuid.uuid4()
        token = sign(
            attachment_id=attachment, company_id=company, settings=settings, now=NOW
        )

        with pytest.raises(MediaTokenError):
            verify(
                attachment_id=attachment,
                company_id=company,
                expires_at=token.expires_at,
                signature=token.signature,
                settings=settings,
                now=token.expires_at + 1,
            )

    def test_it_does_not_work_for_another_attachment(self) -> None:
        settings = _settings()
        company = uuid.uuid4()
        token = sign(
            attachment_id=uuid.uuid4(),
            company_id=company,
            settings=settings,
            now=NOW,
        )

        with pytest.raises(MediaTokenError):
            verify(
                attachment_id=uuid.uuid4(),
                company_id=company,
                expires_at=token.expires_at,
                signature=token.signature,
                settings=settings,
                now=NOW,
            )

    def test_it_does_not_work_for_another_tenant(self) -> None:
        """The company is part of what is signed, not merely checked
        afterwards."""
        settings = _settings()
        attachment = uuid.uuid4()
        token = sign(
            attachment_id=attachment,
            company_id=uuid.uuid4(),
            settings=settings,
            now=NOW,
        )

        with pytest.raises(MediaTokenError):
            verify(
                attachment_id=attachment,
                company_id=uuid.uuid4(),
                expires_at=token.expires_at,
                signature=token.signature,
                settings=settings,
                now=NOW,
            )

    def test_the_expiry_cannot_be_extended(self) -> None:
        """It is signed, so pushing the timestamp out invalidates it."""
        settings = _settings()
        attachment, company = uuid.uuid4(), uuid.uuid4()
        token = sign(
            attachment_id=attachment, company_id=company, settings=settings, now=NOW
        )

        with pytest.raises(MediaTokenError):
            verify(
                attachment_id=attachment,
                company_id=company,
                expires_at=token.expires_at + 86_400,
                signature=token.signature,
                settings=settings,
                now=NOW,
            )

    def test_a_garbage_signature_is_refused(self) -> None:
        settings = _settings()
        with pytest.raises(MediaTokenError):
            verify(
                attachment_id=uuid.uuid4(),
                company_id=uuid.uuid4(),
                expires_at=NOW + 600,
                signature="not-a-signature",
                settings=settings,
                now=NOW,
            )


def test_a_media_signature_is_not_a_session_token() -> None:
    """Derived from a separate key context, so a media signature can never
    be mistaken for — or used as — a session credential even if a future
    refactor confuses the two."""
    settings = _settings()
    attachment, company = uuid.uuid4(), uuid.uuid4()
    token = sign(attachment_id=attachment, company_id=company, settings=settings, now=NOW)

    # A bare HMAC hex digest, carrying no identity and no claims — nothing a
    # JWT decoder would accept.
    assert len(token.signature) == 64
    assert all(character in "0123456789abcdef" for character in token.signature)
