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
from typing import Any

from blinkengage.core.config import Settings
from blinkengage.domain.mail import MailConfig, MailSecurity, from_stored
from blinkengage.domain.payment_providers import (
    PAYMENT_PROVIDERS_KEY,
    ProviderConfig,
    ProviderView,
    descriptor_for,
)
from blinkengage.domain.payment_providers import apply as payment_apply
from blinkengage.domain.payment_providers import from_stored as payment_providers_from_stored
from blinkengage.domain.payment_providers import to_stored as payment_to_stored
from blinkengage.domain.payments import PaymentProviderKind
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

    # --- Payment providers ------------------------------------------

    async def payment_providers(self) -> dict[str, ProviderConfig]:
        """Every provider's configuration, secrets included.

        For the registry, which is about to build adapters. Everything
        user-facing goes through ``payment_providers_view``.
        """
        stored = await self._repository.get(PAYMENT_PROVIDERS_KEY)
        configs = payment_providers_from_stored(stored.value if stored else None)
        return self._with_environment_paypal(configs, configured=stored is not None)

    async def payment_providers_view(
        self,
    ) -> tuple[dict[str, ProviderView], str | None, datetime | None]:
        """What the console displays: no secrets, and who last changed it.

        Returns ``ProviderView``, not a redacted config — see its docstring.
        A redacted config cannot also report *which* secrets are set, and a
        screen that says "no password configured" about a working merchant
        account is the kind of wrong that gets a credential retyped.
        """
        stored = await self._repository.get(PAYMENT_PROVIDERS_KEY)
        configs = payment_providers_from_stored(stored.value if stored else None)
        configs = self._with_environment_paypal(configs, configured=stored is not None)
        return (
            {kind: config.view() for kind, config in configs.items()},
            stored.updated_by_email if stored else None,
            stored.updated_at if stored else None,
        )

    def _with_environment_paypal(
        self, configs: dict[str, ProviderConfig], *, configured: bool
    ) -> dict[str, ProviderConfig]:
        """Layers the environment under PayPal, the way mail does.

        PayPal was configurable only through environment variables before
        this screen existed. An installation running on those must keep
        working untouched — a setting that only works after somebody fills
        in a form takes the next fresh deployment down.

        The stored row wins where it has a value, so an operator who edits
        the screen overrides the deploy rather than fighting it.
        """
        settings = self._settings
        if not settings.paypal_client_id or not settings.paypal_client_secret:
            return configs

        paypal = configs[PaymentProviderKind.PAYPAL.value]
        from_env = {
            "client_id": settings.paypal_client_id,
            "client_secret": settings.paypal_client_secret,
            "webhook_id": settings.paypal_webhook_id,
            "brand_name": settings.paypal_brand_name,
            "sandbox": settings.paypal_sandbox,
        }
        merged = {**{k: v for k, v in from_env.items() if v not in (None, "")}, **paypal.values}
        configs[PaymentProviderKind.PAYPAL.value] = ProviderConfig(
            kind=paypal.kind,
            # An installation that has never opened this screen still has a
            # working PayPal, so the environment implies enabled.
            enabled=paypal.enabled or not configured,
            values=merged,
        )
        return configs

    async def save_payment_provider(
        self,
        *,
        kind: str,
        enabled: bool,
        values: dict[str, Any],
        actor_email: str | None,
    ) -> ProviderView:
        """Stores one provider's settings, leaving the others alone.

        One provider at a time rather than the whole group: these are
        separate contracts with separate people, and a form that saves all
        six at once makes editing one an opportunity to clear another.

        A secret sent as ``None`` is preserved — see ``apply`` in
        ``domain/payment_providers.py``. Sent as ``""`` it is cleared.
        """
        descriptor = descriptor_for(kind)
        stored = await self._repository.get(PAYMENT_PROVIDERS_KEY)
        configs = payment_providers_from_stored(stored.value if stored else None)

        updated = payment_apply(configs[descriptor.kind.value], values)
        updated = ProviderConfig(kind=updated.kind, enabled=enabled, values=updated.values)
        configs[descriptor.kind.value] = updated

        await self._repository.upsert(
            PlatformSetting(
                key=PAYMENT_PROVIDERS_KEY,
                value=payment_to_stored(configs),
                updated_by_email=actor_email,
            )
        )
        return updated.view()

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
