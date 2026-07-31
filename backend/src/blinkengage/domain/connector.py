"""``Connector`` — the plugin contract for *getting connected*.

``ChannelProvider`` (see ``channel_provider.py``) is how we talk to a channel
once it works: send, receive, upload, health. This is the other half — how a
customer gets there in the first place: what the connector can do, how to
authenticate, what to discover, what to check, and what to write down.

Two contracts rather than one because they have different shapes and
different lifetimes. A provider is constructed per message with decrypted
credentials in hand; a connector is a singleton that knows how credentials
are *obtained*. Merging them would put OAuth machinery in the hot path of
every outbound message, and would mean a channel could not be connected
without instantiating its transport.

**A connector is the only place a channel's name may appear.** Everything
above — the wizard service, the API, the console — works from
``ConnectorProfile`` and the steps derived from it. That is what makes Slack,
Teams, RCS or LINE a new file here and nothing else anywhere.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from blinkengage.domain.connector_manifest import (
    ConnectorManifest,
    ValidationResult,
)
from blinkengage.domain.connectors import (
    Capability,
    CapabilityState,
    ConnectorProfile,
)


@dataclass(frozen=True, slots=True)
class DeploymentContext:
    """What this installation happens to have, when capabilities are resolved.

    Passed in rather than read from settings inside a connector, so resolving
    a profile stays a pure function of stated inputs and a test can describe
    a hosted installation, a self-hosted one with its own app, and one with
    neither, without patching a settings singleton.
    """

    #: Where this installation answers, for building redirect and callback
    #: URLs. Derived, never supplied by a caller — a client-supplied redirect
    #: URI is an open redirect and an open redirect is token theft.
    public_base_url: str
    #: Provider app credentials this installation holds, keyed by the
    #: connector's own ``app_key``. Present means OAuth is possible.
    configured_apps: frozenset[str] = frozenset()

    def has_app(self, key: str | None) -> bool:
        return key is not None and key in self.configured_apps


@dataclass(frozen=True, slots=True)
class Field:
    """One input on a ``FORM`` step, described by the server.

    The console renders these without knowing what any of them mean, which is
    what keeps credential shapes out of the frontend. A connector that needs
    a new field adds it here and the form grows.
    """

    name: str
    #: ``text`` | ``secret`` | ``number`` | ``boolean`` | ``select``
    kind: str
    label_key: str
    required: bool = True
    help_key: str | None = None
    placeholder: str | None = None
    #: For ``select``: the choices, as ``(value, label_key)``.
    options: tuple[tuple[str, str], ...] = ()
    #: Copyable text shown beside the field — a bot command to paste into
    #: BotFather, a webhook URL to paste into a dashboard. Present exactly
    #: when the customer has to do something outside Blink Engage, which is
    #: the moment a wizard usually abandons them.
    copyable: str | None = None


@dataclass(frozen=True, slots=True)
class Resource:
    """Something the customer owns, found by discovery.

    Deliberately shapeless beyond an id and a label: a WhatsApp number, a
    Facebook Page, a Slack workspace and a LINE channel have nothing in
    common except that the customer must pick one. ``detail`` carries
    whatever the picker should show underneath, already translated to
    key/value pairs the console renders verbatim.
    """

    id: str
    label: str
    #: Grouping header for a picker showing several kinds at once — the
    #: templates connect WhatsApp numbers, Pages and Instagram accounts from
    #: one consent and show them in one list.
    group_key: str | None = None
    detail: dict[str, str] = field(default_factory=dict)
    #: Set when the resource cannot be chosen — a Page the customer lacks
    #: messaging rights on. Shown, not hidden: a customer who cannot find
    #: their Page assumes the product is broken.
    unavailable_reason: str | None = None
    #: Opaque connector state carried to the connect step, so a second
    #: round trip to the provider is not needed to remember, say, which
    #: parent account a phone number belonged to.
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Attempt:
    """Everything gathered so far in one connection attempt.

    One object rather than a parameter list, because what a connector needs
    genuinely differs: an OAuth connector reads ``grant`` and ``selection``,
    a form-based one reads ``inputs``, and both need ``context`` to build a
    URL. Passing the whole attempt means a connector reads what applies to it
    and ignores the rest, instead of every method growing a parameter each
    time a connector needs something it was not given.
    """

    context: DeploymentContext
    #: What the customer typed, when the Authenticate step was a form. Empty
    #: for a connector that authenticates by consent.
    inputs: dict[str, Any] = field(default_factory=dict)
    #: What consent produced. Empty for a form-based connector — this is the
    #: distinction the first version of the contract blurred.
    grant: dict[str, Any] = field(default_factory=dict)
    #: What the customer chose on the picker, if there was one.
    selection: tuple[Resource, ...] = ()
    #: What the customer decided to call it.
    display_name: str = ""

    @property
    def credentials(self) -> dict[str, Any]:
        """The values a connector should treat as credentials.

        Consent material where there was consent, typed values otherwise —
        so a connector that only ever wants "the thing that authenticates
        this" does not have to know which step produced it.
        """
        return self.grant or self.inputs


@dataclass(frozen=True, slots=True)
class Repair:
    """What a repair produced, and what to persist.

    Not a bare credentials dict. Telegram's webhook secret lives in a
    *column* rather than in credentials, so a repair that re-registered the
    webhook and returned only credentials left the column stale and every
    inbound message failing signature verification — silently, because a
    stale secret looks exactly like a channel nobody has messaged. The one
    field that could not be returned was the one that had to be.
    """

    credentials: dict[str, Any] | None = None
    webhook_secret: str | None = None
    #: True when the repair believes it worked. A repair that could not fix
    #: anything must say so rather than returning unchanged values, which the
    #: console would render as success.
    repaired: bool = True
    #: Why not, as a translatable code.
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Connection:
    """What to write down once everything has passed.

    One per channel being connected — a template that connects three
    channels from one consent returns three of these.
    """

    channel_type: str
    display_name: str
    credentials: dict[str, Any]
    #: The provider's own id for this resource, so a shared webhook can route
    #: an inbound event back to the right channel without guessing.
    external_id: str | None = None
    #: Its parent, where there is one (a WhatsApp number's business account).
    external_parent_id: str | None = None
    #: Absent when the installation's shared app secret verifies inbound
    #: events instead — see ``Capability.SHARED_WEBHOOK``.
    webhook_secret: str | None = None


class Connector(ABC):
    """A channel's connection lifecycle.

    Two required members: a ``manifest`` describing the connector, and
    ``connect`` doing the work. Everything else has an honest default, so a
    connector that authenticates by form, discovers nothing and validates
    nothing is a manifest plus one method — which is the bar a new channel
    should have to clear.

    The manifest is the contract with the console. A connector *describes*
    itself and the wizard renders the description; nothing in the console is
    written per channel, which is what makes adding LINE or RCS a backend
    change and nothing else.
    """

    #: Registry key, and the ``ChannelConfig.channel_type`` written on
    #: connect. Matches the ``ChannelProvider`` of the same name.
    channel_type: str

    #: Which provider app this connector needs for OAuth, if any. Several
    #: connectors may share one — WhatsApp, Messenger and Instagram are all
    #: ``"meta"``, which is precisely why one consent can connect all three.
    app_key: str | None = None

    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest:
        """Everything the console needs to render this connector.

        Required, and required to be *static*: built at import time, holding
        no credentials, serialisable whole. A manifest that had to be
        computed per request would be one the console could not cache and one
        a test could not read without a running system.
        """

    @property
    def declares(self) -> frozenset[Capability]:
        """What this connector can do, from its manifest.

        Kept as a property rather than duplicated on the class: two places to
        state a capability is one place for them to disagree, and the
        disagreement would be invisible until a flow came out the wrong
        shape.
        """
        return self.manifest.capabilities

    def resolve(self, context: DeploymentContext) -> ConnectorProfile:
        """What this connector can do on this installation.

        The default is the honest one for every connector: anything declared
        is available, except OAuth-shaped capabilities when the installation
        holds no app for it. A connector needing different logic overrides —
        but most do not, and most should not have to.
        """
        needs_app = {
            Capability.OAUTH,
            Capability.AUTO_DISCOVERY,
            Capability.EMBEDDED_SIGNUP,
            Capability.TOKEN_REFRESH,
        }
        has_app = context.has_app(self.app_key)
        states = []
        for capability in sorted(self.declares, key=lambda c: c.value):
            if capability in needs_app and not has_app:
                states.append(
                    CapabilityState(
                        capability,
                        available=False,
                        # A code, not prose. The console explains it, and —
                        # only to a platform administrator — offers the link
                        # that fixes it.
                        reason="platform_app_not_configured",
                    )
                )
            else:
                states.append(CapabilityState(capability, available=True))
        return ConnectorProfile(
            channel_type=self.channel_type,
            declares=self.declares,
            states=tuple(states),
        )

    # --- Authenticate -------------------------------------------------

    def credential_fields(self) -> tuple[Field, ...]:
        """The manual form, from the manifest.

        Derived rather than declared twice. The manifest is what the console
        renders, so a connector whose form disagreed with its manifest would
        validate values the customer was never asked for.
        """
        return tuple(
            Field(
                name=spec.name,
                kind=spec.kind,
                label_key=spec.label_key,
                required=spec.required,
                help_key=spec.help_key,
                placeholder=spec.placeholder,
                options=spec.options,
                copyable=spec.copyable,
            )
            for spec in self.manifest.required_credentials
        )

    async def authorize_url(self, *, state: str, context: DeploymentContext) -> str:
        """Where to send the customer to consent."""
        raise NotImplementedError(f"{self.channel_type} does not support OAuth.")

    async def exchange(
        self, *, code: str, context: DeploymentContext
    ) -> dict[str, Any]:  # pragma: no cover - overridden by OAuth connectors
        """Turn an authorization code into stored grant material."""
        raise NotImplementedError(f"{self.channel_type} does not support OAuth.")

    # --- Discover -----------------------------------------------------

    async def discover(self, *, grant: dict[str, Any]) -> tuple[Resource, ...]:
        """What the customer owns that this connector could connect to."""
        return ()

    # --- Verify -------------------------------------------------------

    async def validate(self, attempt: Attempt) -> tuple[ValidationResult, ...]:
        """Everything worth telling the customer before connecting.

        Structured results, never strings. A ``ValidationCode`` is drawn from
        a closed set the console has copy for, so a finding renders in
        English, in Arabic, and in any tool that has never heard of this
        connector — where a sentence from the server could only ever be
        English.

        Takes the whole ``Attempt`` rather than a selection of its parts. An
        earlier version took ``grant`` and ``selection``, which read
        naturally for an OAuth connector and made no sense for one
        authenticated by form, where the "grant" is just what was typed. Four
        connectors were written against it and guessed four different ways.

        Returns findings and never raises — transport failures included. A
        validator that raised would collapse a list of five findings into
        whichever was evaluated first, in the one step whose entire job is
        explaining what is wrong.

        A connector must only return codes its manifest declared. The console
        pre-resolves copy from ``verification_steps``, so an undeclared code
        is a raw slug in front of a customer at the worst possible moment.
        """
        return ()

    # --- Connect ------------------------------------------------------

    @abstractmethod
    async def connect(
        self, *, company_id: UUID, attempt: Attempt
    ) -> tuple[Connection, ...]:
        """Do whatever the provider needs, and return what to store.

        Subscribing an app, generating secrets, claiming a resource — all of
        it is channel-specific and none of it belongs anywhere the wizard can
        see. Registering a *callback URL* is the exception, and it has its own
        hook below for a reason worth reading.
        """

    async def register_webhook(
        self, *, callback_url: str, credentials: dict[str, Any], context: DeploymentContext
    ) -> Repair:
        """Point the provider at a callback URL, once one exists.

        Separate from ``connect`` because of an ordering problem that has no
        clean answer inside it: for every connector whose callback is *per
        channel*, the URL contains the channel's id — and that id is assigned
        when the row is written, which is after ``connect`` returns. A
        connector asked to register a webhook during ``connect`` can only
        invent an id, and an invented id is a URL the provider will deliver to
        until somebody notices it has been answering 404 for a month.

        So this runs afterwards, with the real URL. It is why
        ``AUTOMATIC_WEBHOOK_REGISTRATION`` is a capability a connector can
        honestly declare rather than one it has to warn its way around.

        Connectors on a shared app do not implement it: their callback is
        configured once on the app, and there is nothing per channel to
        register.
        """
        return Repair(repaired=False, reason="not_supported")

    # --- Repair -------------------------------------------------------

    async def repair(
        self,
        *,
        action: str,
        credentials: dict[str, Any],
        webhook_secret: str | None = None,
        callback_url: str | None = None,
        context: DeploymentContext,
    ) -> Repair:
        """Perform a one-click fix.

        The actions a connector offers are named in the ``CheckOutcome``s and
        health states it produces, so this stays open-ended rather than an
        enum every connector has to share.

        Given the existing webhook secret and the real callback URL, because
        the two repairs customers reach for most — re-register the webhook,
        reconnect — both need them, and a connector that had to invent either
        would be repairing something into a state nothing else agrees with.
        """
        return Repair(repaired=False, reason="not_supported")


__all__ = ["Connection", "Connector", "DeploymentContext", "Field", "Resource"]
