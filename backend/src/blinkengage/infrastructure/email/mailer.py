"""Shared plain-text transactional email sender, over the platform's own
SMTP relay — never a company's customer-facing ``EmailProvider`` channel
credentials.

The relay is configured either by environment variable or from the
platform console (see ``docs/architecture/platform-admin.md``); this
module takes a resolved ``MailConfig`` and does not care which produced
it.

``send_plain_email`` keeps its ``Settings``-based signature so existing
callers are untouched, and resolves the environment configuration
itself. Anything that can reach the database should prefer
``send_with_config`` with the resolved configuration, so a relay changed
in the console takes effect without a redeploy.
"""

from email.message import EmailMessage

import aiosmtplib

from blinkengage.core.config import Settings
from blinkengage.domain.mail import MailConfig, MailSecurity


class MailDeliveryError(RuntimeError):
    """The relay refused the message or could not be reached.

    Carries the relay's own words where there are any — "535
    authentication failed" tells an operator to fix the password, while
    "could not send email" sends them looking at DNS.
    """


def build_message(config: MailConfig, *, to_address: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"{config.from_name} <{config.from_address}>"
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)
    return message


async def send_with_config(
    config: MailConfig, *, to_address: str, subject: str, body: str
) -> None:
    """Sends one message over the configured relay.

    ``use_tls`` and ``start_tls`` are passed explicitly rather than left
    to aiosmtplib's autodetection: the library will happily fall back to
    an unencrypted session against a relay that does not offer
    STARTTLS, which would put a password on the wire in clear. Being
    explicit turns that into a failure the operator sees.
    """
    try:
        await aiosmtplib.send(
            build_message(config, to_address=to_address, subject=subject, body=body),
            hostname=config.host,
            port=config.port,
            username=config.username or None,
            password=config.password or None,
            use_tls=config.security is MailSecurity.TLS,
            start_tls=config.security is MailSecurity.STARTTLS,
            timeout=config.timeout_seconds,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        raise MailDeliveryError(str(exc) or exc.__class__.__name__) from exc


async def send_plain_email(settings: Settings, *, to_address: str, subject: str, body: str) -> None:
    """Backwards-compatible entry point for callers with only settings."""
    from blinkengage.application.services.platform_settings_service import (
        environment_mail_config,
    )

    await send_with_config(
        environment_mail_config(settings),
        to_address=to_address,
        subject=subject,
        body=body,
    )
