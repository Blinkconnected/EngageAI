"""Shared plain-text transactional email sender, over the platform's own
SMTP relay (``settings.smtp_*`` — never a company's customer-facing
``EmailProvider`` channel credentials). Originally inlined in
``infrastructure.tasks.notification_email_dispatch_task``; extracted here
so ``AgentService``'s invite-by-email flow (see
``docs/architecture/company-onboarding.md``) can send a message the same
way without duplicating the SMTP call.
"""

from email.message import EmailMessage

import aiosmtplib

from blinkengage.core.config import Settings


async def send_plain_email(settings: Settings, *, to_address: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_address}>"
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
    )
