"""Payment provider adapters. See ``docs/architecture/billing.md``."""

from blinkengage.infrastructure.payments.base import (
    PaymentProvider,
    PaymentProviderError,
    ProviderCapture,
    ProviderIntent,
    ProviderRefund,
)
from blinkengage.infrastructure.payments.manual import ManualProvider
from blinkengage.infrastructure.payments.paypal import PayPalProvider
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry

__all__ = [
    "ManualProvider",
    "PayPalProvider",
    "PaymentProvider",
    "PaymentProviderError",
    "PaymentProviderRegistry",
    "ProviderCapture",
    "ProviderIntent",
    "ProviderRefund",
]
