"""Installation-level settings, edited from the platform console.

See ``docs/architecture/platform-admin.md``.

Today this is the outbound mail relay. The shape is deliberately general
— one row per settings group — because "the operator needs to change X
without a redeploy" is a request that arrives repeatedly, and answering
it with a new table each time is how a settings system ends up as
fifteen tables nobody can enumerate.

**Stored settings override the environment; they never replace it.** An
installation that has never opened the console keeps working on its
environment variables, and one that has keeps working if the row is
deleted. A setting that only works after somebody fills in a form takes
the next fresh deployment down.
"""

from dataclasses import asdict
from datetime import datetime

from blinkengage.core.config import Settings
from blinkengage.domain.mail import MailConfig, MailSecurity, from_stored
from blinkengage.infrastructure.database.models.platform_settings import (
    SMTP_KEY,
    PlatformSetting,
)
from blinkengage.infrastructure.repositories.platform_settings_repository import (
    PlatformSettingsRepository,
)


def environment_mail_config(settings: Settings) -> MailConfig:
    """The configuration an installation has without touching the console.

    ``smtp_use_tls`` is the historical boolean, and it maps to STARTTLS
    rather than implicit TLS: the default port has always been 587, and
    reading the old flag as implicit TLS would break every existing
    installation the first time this code ran.
    """
    return MailConfig(
        host=settings.smtp_host,
        port=settings.smtp_port,
        security=MailSecurity.STARTTLS if settings.smtp_use_tls else MailSecurity.NONE,
        from_address=settings.smtp_from_address,
        from_name=settings.smtp_from_name,
        # Empty environment variables are normalised to None. An unset
        # variable and one set to "" mean the same thing — no
        # credential — and letting "" through would report
        # `password_set: true` for a relay with no password, which is
        # precisely the ambiguity that field exists to remove.
        username=settings.smtp_username or None,
        password=settings.smtp_password or None,
    )


class PlatformSettingsService:
    def __init__(
        self, *, repository: PlatformSettingsRepository, settings: Settings
    ) -> None:
        self._repository = repository
        self._settings = settings

    async def mail_config(self) -> MailConfig:
        """The relay configuration actually in force, password included.

        The only caller that should use this is the one about to send a
        message. Everything user-facing goes through ``mail_view``.
        """
        stored = await self._repository.get(SMTP_KEY)
        return from_stored(
            stored.value if stored else None,
            defaults=environment_mail_config(self._settings),
        )

    async def mail_view(self) -> tuple[MailConfig, bool, str | None, datetime | None]:
        """What the console displays: the configuration without the
        password, whether a password is set at all, and who last changed
        it.

        ``password_set`` matters because a blank field otherwise means
        two different things — "no authentication" and "authenticated,
        but we will not show you the secret" — and an operator cannot
        tell which without trying to send.
        """
        stored = await self._repository.get(SMTP_KEY)
        config = from_stored(
            stored.value if stored else None,
            defaults=environment_mail_config(self._settings),
        )
        return (
            config.redacted(),
            config.password is not None,
            stored.updated_by_email if stored else None,
            stored.updated_at if stored else None,
        )

    async def is_customised(self) -> bool:
        """Whether the console has overridden the environment.

        Shown so an operator reading unfamiliar values knows whether
        they came from a deploy or from somebody editing this form.
        """
        return await self._repository.get(SMTP_KEY) is not None

    async def save_mail_config(
        self, config: MailConfig, *, actor_email: str | None
    ) -> MailConfig:
        """Stores the relay configuration.

        A ``None`` password is preserved from what is already stored,
        because the API never sends the password back and a naive
        round-trip of the form would otherwise erase it. An empty string
        clears it — see ``domain/mail.py``.
        """
        existing = await self._repository.get(SMTP_KEY)
        value = asdict(config)
        value["security"] = config.security.value

        if config.password is None and existing is not None:
            value["password"] = existing.value.get("password")

        await self._repository.upsert(
            PlatformSetting(key=SMTP_KEY, value=value, updated_by_email=actor_email)
        )
        return config.redacted()

    async def reset_mail_config(self) -> MailConfig:
        """Drops the override and falls back to the environment.

        Deliberately offered: an operator who has misconfigured the
        relay from the console needs a way back that does not require a
        database session, and "delete the row" is a safer instruction
        than "guess what the environment variables were".
        """
        await self._repository.delete(SMTP_KEY)
        return environment_mail_config(self._settings).redacted()


__all__ = ["PlatformSettingsService", "environment_mail_config"]
