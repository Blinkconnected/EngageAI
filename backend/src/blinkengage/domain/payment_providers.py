"""What payment providers there are, and how each one is actually paid.

See ``docs/architecture/billing.md``.

The temptation with payment providers is to model them all as "a gateway":
credentials in, redirect out, webhook back. That works for PayPal and it is
wrong for most of what Jordan actually uses, in a way that produces a checkout
button leading somewhere the scheme does not have.

So the first thing here is not a provider list, it is a list of **flows** —
because the flow decides what the customer is shown, what the platform stores,
and how money gets matched back to an invoice. Two providers sharing a flow can
share a screen; two providers sharing only the word "payment" cannot.

Nothing in this module talks to a network. It is the description of what a
provider *is* and what configuring it requires; the adapters live in
``infrastructure/payments/`` and the credentials live encrypted in
``platform_settings``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from blinkengage.domain.payments import PaymentProviderKind


class PaymentFlow(StrEnum):
    """How money actually reaches us. The distinction the UI is built on."""

    #: Hosted checkout. The customer leaves, pays, and comes back, and the
    #: gateway confirms out of band. PayPal, MEPS, Network International.
    REDIRECT = "redirect"

    #: **Bill presentment.** The bill is pushed *to the scheme*, and the
    #: customer then pays it at any bank channel they already use — app,
    #: branch, ATM, wallet — quoting a reference. There is no redirect and no
    #: checkout page: the platform's job is to publish the bill and then
    #: reconcile the notification that comes back. eFAWATEERcom.
    BILL_PRESENTMENT = "bill_presentment"

    #: The customer pushes money to us against a reference, on their own
    #: initiative and their own schedule. Nothing is "started" on our side, so
    #: there is no intent to expire and no redirect to fail — only an incoming
    #: transfer to match. CliQ, bank transfer.
    CREDIT_TRANSFER = "credit_transfer"

    #: An operator records money that has genuinely arrived. Always available,
    #: because no configuration can be a precondition for recording a fact.
    OPERATOR_ENTRY = "operator_entry"


class ProviderReadiness(StrEnum):
    """What an operator is actually looking at on the settings screen.

    Three states rather than a boolean, because "we have not set this up" and
    "this cannot be set up yet" are different problems and only one of them is
    the operator's to fix.
    """

    #: Configured, and an adapter exists that can talk to it.
    ACTIVE = "active"
    #: An adapter exists; nobody has entered credentials.
    NOT_CONFIGURED = "not_configured"
    #: Credentials can be entered and are stored, but no adapter exists yet —
    #: the scheme's integration specification is not in the codebase. Shown
    #: plainly rather than as a working button, because a checkout that
    #: cannot complete is worse than one that is honestly absent.
    AWAITING_INTEGRATION = "awaiting_integration"


@dataclass(frozen=True, slots=True)
class CredentialField:
    """One thing an operator has to type in.

    Declared as data rather than as a form component so the API, the console
    and the validation all read the same list. A field the backend requires
    and the form does not render is a provider that can never be saved.
    """

    name: str
    label: str
    #: Secrets are write-only: never returned on a read, and an absent value
    #: on a write means "unchanged" rather than "cleared". See ``apply``.
    secret: bool = False
    required: bool = True
    help_text: str | None = None
    #: For a fixed set of choices — rendered as a select rather than a box.
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Everything true of a provider before anybody configures it."""

    kind: PaymentProviderKind
    label: str
    flow: PaymentFlow
    #: ISO 3166-1 alpha-2 codes this provider serves. Empty means everywhere.
    #: A Jordanian scheme offered to a customer in Germany is not a feature.
    countries: tuple[str, ...]
    fields: tuple[CredentialField, ...]
    #: Whether an adapter exists in this codebase. ``False`` is not a defect
    #: to be hidden — it is the honest state of a scheme whose specification
    #: we hold a contract for but no code against.
    has_adapter: bool
    description: str = ""
    #: Set when ``has_adapter`` is False, so the console can say *why* rather
    #: than leaving somebody to guess whether they typed something wrong.
    pending_note: str | None = None

    @property
    def secret_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.secret)

    def serves(self, country_code: str | None) -> bool:
        if not self.countries:
            return True
        return country_code is not None and country_code.upper() in self.countries


_SANDBOX = CredentialField(
    name="sandbox",
    label="Test mode",
    required=False,
    help_text="Use the scheme's test environment. No real money moves.",
)


# --- The providers -------------------------------------------------------
#
# Field names mirror each scheme's own vocabulary rather than being
# normalised. An operator copying values out of a bank's onboarding pack
# should find the same words on this screen; renaming "outlet reference" to
# "merchant id" for tidiness is how credentials end up in the wrong box.

MANUAL = ProviderDescriptor(
    kind=PaymentProviderKind.MANUAL,
    label="Manual entry",
    flow=PaymentFlow.OPERATOR_ENTRY,
    countries=(),
    fields=(),
    has_adapter=True,
    description=(
        "Record a payment that has already arrived — a bank transfer, a cheque, "
        "a cash settlement. Always available and needs no configuration."
    ),
)

PAYPAL = ProviderDescriptor(
    kind=PaymentProviderKind.PAYPAL,
    label="PayPal",
    flow=PaymentFlow.REDIRECT,
    countries=(),
    fields=(
        CredentialField("client_id", "Client ID"),
        CredentialField("client_secret", "Client secret", secret=True),
        CredentialField(
            "webhook_id",
            "Webhook ID",
            required=False,
            help_text="Required to verify payment notifications from PayPal.",
        ),
        CredentialField("brand_name", "Brand name shown at checkout", required=False),
        _SANDBOX,
    ),
    has_adapter=True,
    description="Card and PayPal-balance checkout, for customers outside Jordan.",
)

EFAWATEERCOM = ProviderDescriptor(
    kind=PaymentProviderKind.EFAWATEERCOM,
    label="eFAWATEERcom",
    flow=PaymentFlow.BILL_PRESENTMENT,
    countries=("JO",),
    fields=(
        CredentialField(
            "biller_code",
            "Biller code",
            help_text="Issued by your sponsoring bank when you are onboarded as a biller.",
        ),
        CredentialField(
            "service_code",
            "Service code",
            help_text="The bill type under your biller code.",
        ),
        CredentialField("api_base_url", "API base URL"),
        CredentialField("client_id", "Client ID"),
        CredentialField("client_secret", "Client secret", secret=True),
        CredentialField(
            "notification_secret",
            "Notification secret",
            secret=True,
            required=False,
            help_text=(
                "Used to verify that an incoming payment notification really "
                "came from the scheme. Without it, notifications are not trusted."
            ),
        ),
        _SANDBOX,
    ),
    has_adapter=False,
    pending_note=(
        "Credentials are stored, but no bills are pushed yet: the scheme's "
        "integration specification is not in this codebase."
    ),
    description=(
        "Publish an invoice as a bill. The customer then pays it through any "
        "bank app, branch, ATM or wallet by quoting the reference, and the "
        "payment is matched back to the invoice automatically."
    ),
)

CLIQ = ProviderDescriptor(
    kind=PaymentProviderKind.CLIQ,
    label="CliQ",
    flow=PaymentFlow.CREDIT_TRANSFER,
    countries=("JO",),
    fields=(
        CredentialField(
            "alias",
            "CliQ alias",
            help_text="The alias customers send to. Shown to them with the payment reference.",
        ),
        CredentialField(
            "alias_type",
            "Alias type",
            choices=("ALIAS", "MOBILE", "IBAN"),
            required=False,
        ),
        CredentialField("account_name", "Account name", required=False),
        CredentialField("iban", "IBAN", required=False),
        CredentialField("bank_name", "Bank", required=False),
        CredentialField(
            "reference_prefix",
            "Payment reference prefix",
            required=False,
            help_text=(
                "Prefixed to each invoice's payment reference so incoming "
                "transfers can be matched back to the right bill."
            ),
        ),
    ),
    has_adapter=False,
    pending_note=(
        "CliQ has no merchant API: the alias and reference are shown to the "
        "customer, and incoming transfers are confirmed by finance until a "
        "bank feed is connected."
    ),
    description=(
        "Instant bank transfer. The customer pushes the money to your alias "
        "quoting a reference — there is no checkout page to redirect to."
    ),
)

MEPS = ProviderDescriptor(
    kind=PaymentProviderKind.MEPS,
    label="MEPS",
    flow=PaymentFlow.REDIRECT,
    countries=("JO",),
    fields=(
        CredentialField("merchant_id", "Merchant ID"),
        CredentialField("terminal_id", "Terminal ID", required=False),
        CredentialField("api_base_url", "API base URL"),
        CredentialField("api_username", "API username"),
        CredentialField("api_password", "API password", secret=True),
        _SANDBOX,
    ),
    has_adapter=False,
    pending_note=(
        "Credentials are stored, but no checkout is offered yet: the acquirer's "
        "integration guide is not in this codebase."
    ),
    description="Card checkout through the Jordanian acquirer.",
)

NETWORK_INTERNATIONAL = ProviderDescriptor(
    kind=PaymentProviderKind.NETWORK_INTERNATIONAL,
    label="Network International",
    flow=PaymentFlow.REDIRECT,
    countries=(),
    fields=(
        CredentialField("outlet_reference", "Outlet reference"),
        CredentialField("api_key", "API key", secret=True),
        CredentialField("api_base_url", "API base URL", required=False),
        _SANDBOX,
    ),
    has_adapter=False,
    pending_note=(
        "Credentials are stored, but no checkout is offered yet: no adapter "
        "has been written against the N-Genius API."
    ),
    description="Card checkout through Network International (N-Genius).",
)


PROVIDERS: Final[tuple[ProviderDescriptor, ...]] = (
    MANUAL,
    CLIQ,
    EFAWATEERCOM,
    MEPS,
    NETWORK_INTERNATIONAL,
    PAYPAL,
)

_BY_KIND: Final[dict[str, ProviderDescriptor]] = {p.kind.value: p for p in PROVIDERS}

#: The settings group these live in — one encrypted row, like the mail relay.
PAYMENT_PROVIDERS_KEY: Final[str] = "payment_providers"


def descriptor_for(kind: str) -> ProviderDescriptor:
    try:
        return _BY_KIND[kind]
    except KeyError:
        raise UnknownProviderKindError(kind) from None


def providers_for_country(country_code: str | None) -> tuple[ProviderDescriptor, ...]:
    """What could serve a customer in this country, configured or not."""
    return tuple(p for p in PROVIDERS if p.serves(country_code))


class UnknownProviderKindError(KeyError):
    """A configuration names a provider this build does not know."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class ProviderView:
    """One provider as the console sees it: never a secret, always the truth
    about which secrets exist."""

    kind: str
    enabled: bool
    #: Everything that is not a secret.
    values: dict[str, Any]
    #: Which secrets have a value — not the values.
    secret_set: dict[str, bool]
    readiness: ProviderReadiness
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """One provider's stored settings."""

    kind: str
    enabled: bool = False
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        value = self.values.get(name, default)
        return default if value in ("", None) else value

    @property
    def sandbox(self) -> bool:
        return bool(self.values.get("sandbox", True))

    def missing_required(self) -> tuple[str, ...]:
        """Required fields with nothing in them.

        What makes ``NOT_CONFIGURED`` a fact rather than a guess, and what
        stops a half-filled provider being switched on.
        """
        descriptor = descriptor_for(self.kind)
        return tuple(f.name for f in descriptor.fields if f.required and not self.get(f.name))

    def readiness(self) -> ProviderReadiness:
        descriptor = descriptor_for(self.kind)
        if not descriptor.has_adapter:
            return ProviderReadiness.AWAITING_INTEGRATION
        if self.missing_required() or not self.enabled:
            return ProviderReadiness.NOT_CONFIGURED
        return ProviderReadiness.ACTIVE

    def view(self) -> ProviderView:
        """What the console is allowed to see.

        A separate type rather than a redacted ``ProviderConfig``, because
        the two facts the console needs — the non-secret values, and *which*
        secrets exist — cannot both survive redaction. Stripping the secrets
        first and then asking "is the password set?" answers no for every
        provider on the installation: the screen reports nothing configured
        while the credentials sit safely in the database.

        That was a real bug in this module, caught by a test that saved a
        secret and read it back. The shape is the fix — with one type there
        is no order of calls that leaks, and none that lies.
        """
        descriptor = descriptor_for(self.kind)
        secrets = set(descriptor.secret_fields)
        return ProviderView(
            kind=self.kind,
            enabled=self.enabled,
            values={k: v for k, v in self.values.items() if k not in secrets},
            secret_set={name: bool(self.get(name)) for name in sorted(secrets)},
            readiness=self.readiness(),
            missing=self.missing_required(),
        )


def apply(current: ProviderConfig, incoming: dict[str, Any]) -> ProviderConfig:
    """Layers a submitted form over what is stored.

    A secret that is **absent** means "unchanged", not "cleared" — the API
    never sends secrets back, so a round-trip of the form would otherwise
    erase every credential the operator did not retype. Clearing is done by
    sending an empty string, which is unambiguous. Same rule as the mail
    relay's password, for the same reason.
    """
    descriptor = descriptor_for(current.kind)
    known = {f.name for f in descriptor.fields}
    secrets = set(descriptor.secret_fields)

    values = dict(current.values)
    for name, value in incoming.items():
        if name not in known:
            # Ignored rather than rejected: a console one release ahead of
            # this build must not be unable to save the fields that do exist.
            continue
        if name in secrets and value is None:
            continue
        values[name] = value

    return ProviderConfig(kind=current.kind, enabled=current.enabled, values=values)


def from_stored(stored: dict[str, Any] | None) -> dict[str, ProviderConfig]:
    """Every provider's configuration, including the ones never touched.

    Absent providers come back as empty configurations rather than being
    missing, so a caller never has to distinguish "not configured" from "not
    present in the row", and a provider added in a later release appears
    immediately on installations whose row predates it.
    """
    stored = stored or {}
    configs: dict[str, ProviderConfig] = {}
    for descriptor in PROVIDERS:
        raw = stored.get(descriptor.kind.value) or {}
        values = raw.get("values") if isinstance(raw.get("values"), dict) else {}
        configs[descriptor.kind.value] = ProviderConfig(
            kind=descriptor.kind.value,
            enabled=bool(raw.get("enabled", False)),
            values=dict(values or {}),
        )
    return configs


def to_stored(configs: dict[str, ProviderConfig]) -> dict[str, Any]:
    return {
        kind: {"enabled": config.enabled, "values": config.values}
        for kind, config in configs.items()
    }


__all__ = [
    "PAYMENT_PROVIDERS_KEY",
    "PROVIDERS",
    "CredentialField",
    "PaymentFlow",
    "ProviderConfig",
    "ProviderDescriptor",
    "ProviderView",
    "ProviderReadiness",
    "UnknownProviderKindError",
    "apply",
    "descriptor_for",
    "from_stored",
    "providers_for_country",
    "to_stored",
]
