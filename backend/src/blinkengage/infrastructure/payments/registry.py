"""Resolves a provider name to the adapter that handles it.

See ``docs/architecture/billing.md``.

Every payment stores the provider that produced it, so a refund years
later has to find the same adapter. The registry is that lookup, and it
raises rather than falling back: silently substituting a different
gateway for one that is no longer configured would refund from the
wrong account.
"""

from blinkengage.core.config import Settings
from blinkengage.domain.payment_providers import ProviderConfig, ProviderReadiness
from blinkengage.domain.payments import PaymentProviderKind
from blinkengage.infrastructure.payments.base import PaymentProvider
from blinkengage.infrastructure.payments.manual import ManualProvider
from blinkengage.infrastructure.payments.paypal import PayPalProvider


class UnknownProviderError(RuntimeError):
    """A payment names a provider that is not configured."""


class PaymentProviderRegistry:
    def __init__(self, providers: dict[str, PaymentProvider]) -> None:
        self._providers = providers

    @classmethod
    def from_settings(cls, settings: Settings) -> "PaymentProviderRegistry":
        # Manual is always present: bank transfers do not depend on
        # configuration, and an operator must never be unable to record
        # money that has genuinely arrived.
        providers: dict[str, PaymentProvider] = {PaymentProviderKind.MANUAL.value: ManualProvider()}
        if settings.paypal_client_id and settings.paypal_client_secret:
            providers[PaymentProviderKind.PAYPAL.value] = PayPalProvider(
                client_id=settings.paypal_client_id,
                client_secret=settings.paypal_client_secret,
                webhook_id=settings.paypal_webhook_id,
                sandbox=settings.paypal_sandbox,
                brand_name=settings.paypal_brand_name,
            )
        return cls(providers)

    @classmethod
    def from_configs(cls, configs: dict[str, ProviderConfig]) -> "PaymentProviderRegistry":
        """Built from what an operator configured in the console.

        **A provider is registered only if an adapter exists for it.** A
        scheme whose credentials are stored but whose integration is not
        written must not appear here: the registry is what the checkout
        asks "can this be paid?", and answering yes for something that
        cannot complete puts a dead button in front of a customer. Those
        providers report ``AWAITING_INTEGRATION`` on the settings screen
        instead, which is the honest place to say it.

        Manual is added unconditionally, for the reason above.
        """
        providers: dict[str, PaymentProvider] = {PaymentProviderKind.MANUAL.value: ManualProvider()}

        paypal = configs.get(PaymentProviderKind.PAYPAL.value)
        if paypal is not None and paypal.readiness() is ProviderReadiness.ACTIVE:
            providers[PaymentProviderKind.PAYPAL.value] = PayPalProvider(
                client_id=paypal.get("client_id"),
                client_secret=paypal.get("client_secret"),
                webhook_id=paypal.get("webhook_id"),
                sandbox=paypal.sandbox,
                brand_name=paypal.get("brand_name") or "Blink Engage",
            )

        # eFAWATEERcom, CliQ, MEPS and Network International are deliberately
        # absent until their adapters exist. See docs/architecture/billing.md.
        return cls(providers)

    def get(self, kind: str) -> PaymentProvider:
        try:
            return self._providers[kind]
        except KeyError:
            raise UnknownProviderError(
                f"Payment provider '{kind}' is not configured on this deployment."
            ) from None

    def available(self) -> list[str]:
        return sorted(self._providers)

    def __contains__(self, kind: str) -> bool:
        return kind in self._providers


__all__ = ["PaymentProviderRegistry", "UnknownProviderError"]
