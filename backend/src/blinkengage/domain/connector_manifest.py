"""The connector manifest — one declaration the whole UI is generated from.

A connector does not *implement* a wizard, it **describes itself**, and the
wizard renders the description. That inversion is the point: a developer
adding LINE or RCS writes a manifest, a validator and a repair handler, and
the console grows a fully-formed connection flow without a line of frontend
changing.

The rule this file exists to make true:

> A developer should be able to add a completely new connector without
> touching the wizard UI.

Which forces three things, and they are the design:

**Everything the UI needs is declared, not inferred.** The name it shows, the
icon, the category it sorts under, the credentials it asks for, the resources
it will discover, the checks it will run, the repairs it can offer. A UI that
has to infer any of these ends up with a lookup table keyed by channel, which
is the hardcoding this replaces.

**Nothing customer-facing is prose.** Every label, description and reason is a
translation key. A manifest that shipped English sentences would produce a
console that can only ever be English, and this product ships Arabic.

**Validation returns codes, not strings.** ``ValidationCode`` is a closed set
so the console can translate exhaustively, and so a connector cannot invent a
failure nobody has written copy for. A string would be untranslatable, and
untranslatable is the same as unusable for half the customers.

Manifests are static data. They are built at import time, hold no
credentials, and can be served to a browser whole — which is what makes the
wizard a renderer rather than a participant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from blinkengage.domain.connector_lifecycle import (
    ChannelFeature,
    FeatureSupport,
    Maturity,
    VersionInfo,
)
from blinkengage.domain.connectors import Capability, StepId, StepKind


class ConnectorCategory(StrEnum):
    """How the picker groups connectors.

    A category, not a channel list, because the picker sorts by what a
    customer is looking for — "the app my customers message me on" — and a
    new connector should land in the right group without the picker learning
    its name.
    """

    MESSAGING = "messaging"
    SOCIAL = "social"
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"
    EMBEDDED = "embedded"
    OTHER = "other"


class AuthMethod(StrEnum):
    """How a customer proves they own the thing being connected."""

    #: Redirected to the provider, consents, comes back.
    OAUTH = "oauth"
    #: Pastes a secret the provider issued them.
    CREDENTIALS = "credentials"
    #: Creates the underlying account during the flow.
    EMBEDDED_SIGNUP = "embedded_signup"
    #: Nothing to prove — the channel is ours to begin with.
    NONE = "none"


class ValidationCode(StrEnum):
    """What can be wrong, as a closed set.

    Codes rather than messages, and *these* codes rather than free-form ones,
    for two reasons that pull the same way. The console translates a code, so
    an Arabic customer reads Arabic. And a closed set means every failure a
    connector can report is a failure somebody has written copy for — a
    connector cannot surface a state the UI has no words for.

    Extending it is deliberate work: a new member, copy in both locale files,
    and a decision about whether it blocks. That friction is the feature.
    """

    #: Everything a connector could check, checked out.
    OK = "ok"
    #: A scope or permission the provider did not grant.
    MISSING_PERMISSION = "missing_permission"
    #: The credential is wrong, malformed, or the provider rejected it.
    INVALID_TOKEN = "invalid_token"
    #: The credential was right and no longer is.
    EXPIRED_CREDENTIALS = "expired_credentials"
    #: The provider is not delivering events to us.
    WEBHOOK_NOT_REGISTERED = "webhook_not_registered"
    #: We are asking for an API version the provider no longer serves.
    UNSUPPORTED_API_VERSION = "unsupported_api_version"
    #: The provider requires the customer's business to be verified.
    BUSINESS_VERIFICATION_REQUIRED = "business_verification_required"
    #: The resource exists but cannot be used for messaging.
    RESOURCE_NOT_ELIGIBLE = "resource_not_eligible"
    #: Nothing was chosen to connect.
    NO_RESOURCE_SELECTED = "no_resource_selected"
    #: A required credential was left blank.
    MISSING_CREDENTIAL = "missing_credential"
    #: The provider could not be reached at all.
    PROVIDER_UNREACHABLE = "provider_unreachable"
    #: We are being throttled.
    RATE_LIMITED = "rate_limited"
    #: True but not blocking — a quality rating, a send-only mailbox.
    ADVISORY = "advisory"


#: Which codes stop a connection. Declared here rather than decided per
#: connector, so "does this block?" has one answer everywhere and a customer
#: is never blocked by one channel for something another waves through.
BLOCKING_CODES: frozenset[ValidationCode] = frozenset(
    {
        ValidationCode.MISSING_PERMISSION,
        ValidationCode.INVALID_TOKEN,
        ValidationCode.EXPIRED_CREDENTIALS,
        ValidationCode.UNSUPPORTED_API_VERSION,
        ValidationCode.BUSINESS_VERIFICATION_REQUIRED,
        ValidationCode.RESOURCE_NOT_ELIGIBLE,
        ValidationCode.NO_RESOURCE_SELECTED,
        ValidationCode.MISSING_CREDENTIAL,
    }
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """One finding from ``validate()``.

    Structured throughout: a code the console translates, parameters to fill
    the copy, and the id of a declared repair that would fix it. Nothing here
    is a sentence, which is what lets the same finding render in English, in
    Arabic, and in a support tool that has never heard of this connector.
    """

    code: ValidationCode
    #: Which channel this concerns. Matters under a template, where one
    #: consent connects three and "message access is off" is useless without
    #: the word Instagram in front of it.
    channel_type: str = ""
    #: Fills the console's copy — a scope name, a phone number, a version.
    params: dict[str, str] = field(default_factory=dict)
    #: The ``RepairAction.id`` that would fix this, when one would.
    repair_action: str | None = None
    #: Step-by-step copy for something only the customer can change, in their
    #: provider's own app. The honest answer when there is no button.
    instructions_key: str | None = None

    @property
    def blocks(self) -> bool:
        return self.code in BLOCKING_CODES

    @property
    def ok(self) -> bool:
        return self.code is ValidationCode.OK


@dataclass(frozen=True, slots=True)
class RepairAction:
    """A one-click fix, declared so the console can render it.

    Declared rather than discovered, because a button the UI has to know
    about in advance is a button the UI has to be changed to add. Everything
    needed to render, confirm and invoke one is here.
    """

    id: str
    title_key: str
    description_key: str
    #: Whether to ask first. True for anything a customer could regret — a
    #: reconnect that costs them a consent screen, a secret regeneration that
    #: invalidates the old one immediately.
    confirm: bool = False
    confirm_key: str | None = None
    #: What the caller must hold. Checked server-side; the console uses it to
    #: hide a control the customer could never use.
    permission: str = "channels.manage"
    #: True when it can run before a channel exists — during the flow rather
    #: than from the channel list. Most repairs cannot: they need a row.
    available_during_setup: bool = False


@dataclass(frozen=True, slots=True)
class CredentialSpec:
    """One input the console renders without knowing what it means."""

    name: str
    kind: str
    label_key: str
    required: bool = True
    help_key: str | None = None
    placeholder: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    #: Text with a copy button beside it — a command to paste into a
    #: provider's bot, a URL for their dashboard. Present exactly when the
    #: customer must do something outside Blink Engage, which is the moment a
    #: wizard usually loses them.
    copyable: str | None = None
    #: True when this value belongs in the ``webhook_secret`` column rather
    #: than in the credentials blob. Without it a connector needing a signing
    #: secret has nowhere to put one, and every inbound message fails a
    #: signature check nobody can see failing.
    is_webhook_secret: bool = False


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    """A kind of thing discovery will find.

    Declared so the picker can describe what it is about to show — and say
    something useful when it finds nothing, which is the case a customer
    actually hits (a personal Instagram account that cannot be connected at
    all).
    """

    key: str
    title_key: str
    #: What the picker says when discovery returns nothing. The difference
    #: between a dead end and an explanation.
    empty_key: str
    #: Whether more than one may be chosen. A customer with four Pages
    #: usually wants all four.
    multiple: bool = False


@dataclass(frozen=True, slots=True)
class VerificationSpec:
    """A check the connector will run, declared in advance.

    Declared so the console can show the checklist *before* it has answers —
    a list of things being verified reads as progress, where a blank panel
    reads as a hang.
    """

    key: str
    title_key: str
    #: Codes this check can produce. Lets the console pre-resolve copy and
    #: lets a test assert that a connector never returns a code it never
    #: declared.
    codes: tuple[ValidationCode, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentationLink:
    """Somewhere to send a customer who is genuinely stuck.

    The goal is that nobody needs these. They exist for the case that
    survives every guided step — and a link with a translated label is better
    than a customer searching a provider's documentation themselves.
    """

    key: str
    url: str


@dataclass(frozen=True, slots=True)
class ConnectorManifest:
    """Everything the console needs to render a connector, and nothing else.

    Static, credential-free, serialisable whole. That is what makes the
    wizard a renderer: it receives this and has all it needs.
    """

    channel_type: str
    #: Copy keys, not names. Even the connector's own name is translated —
    #: "Web Chat" and "SMS" differ in Arabic, and a manifest that hardcoded
    #: the English would leak into every screen that shows a channel.
    name_key: str
    description_key: str
    category: ConnectorCategory
    #: An identifier the console maps to an asset. Never a URL: a manifest
    #: that carried image URLs would make the backend responsible for the
    #: console's asset pipeline.
    icon: str

    capabilities: frozenset[Capability] = frozenset()
    auth_methods: tuple[AuthMethod, ...] = ()
    #: Provider scopes this connector asks for, shown before consent so a
    #: customer can see what they are approving.
    required_permissions: tuple[str, ...] = ()
    required_credentials: tuple[CredentialSpec, ...] = ()
    required_resources: tuple[ResourceSpec, ...] = ()
    verification_steps: tuple[VerificationSpec, ...] = ()
    repair_actions: tuple[RepairAction, ...] = ()
    #: What this channel can carry once connected, as a structured matrix
    #: rather than free strings. The console renders it without a lookup
    #: table, and two connectors can no longer name one capability
    #: differently — which is what made the previous free-string version a
    #: matrix that lied.
    supported_features: tuple[FeatureSupport, ...] = ()
    documentation: tuple[DocumentationLink, ...] = ()
    #: How far along this connector's code is. A property of the code, the
    #: same on every installation — availability is the other axis and is
    #: resolved per deployment. See ``connector_lifecycle``.
    maturity: Maturity = Maturity.PRODUCTION

    #: Its own version, the provider API version it speaks, and the oldest
    #: platform it runs on. Three things people routinely conflate, so the
    #: manifest names each.
    versions: VersionInfo = field(default_factory=VersionInfo)
    #: An explicit flow, when the derived one is wrong. Almost always empty:
    #: deriving from capabilities means a connector cannot forget a step, and
    #: a connector that needs a different shape is saying something new about
    #: connecting to things — which is worth writing down here deliberately.
    steps: tuple[tuple[StepId, StepKind], ...] = ()

    @property
    def minimum_platform_version(self) -> str:
        """Kept as a shorthand for the field that moved into ``versions``."""
        return self.versions.minimum_platform

    def supports(self, feature: ChannelFeature) -> FeatureSupport | None:
        for support in self.supported_features:
            if support.feature is feature:
                return support
        return None

    def repair(self, action_id: str) -> RepairAction | None:
        for action in self.repair_actions:
            if action.id == action_id:
                return action
        return None

    @property
    def declared_codes(self) -> frozenset[ValidationCode]:
        """Every code this connector says it can produce.

        Used to hold a connector to its own manifest: returning a code it
        never declared means the console may have no copy for it, and the
        customer sees a raw slug at the worst possible moment.
        """
        return frozenset(code for step in self.verification_steps for code in step.codes)


def blocking(results: tuple[ValidationResult, ...]) -> tuple[ValidationResult, ...]:
    """The findings that must be fixed before connecting.

    Only blocking codes block. Everything else is worth saying and not worth
    stopping for — a checklist that blocked on advice would train customers
    to click past it, which is exactly how a real failure gets missed.
    """
    return tuple(result for result in results if result.blocks)


__all__ = [
    "BLOCKING_CODES",
    "AuthMethod",
    "ConnectorCategory",
    "ConnectorManifest",
    "CredentialSpec",
    "DocumentationLink",
    "RepairAction",
    "ResourceSpec",
    "ValidationCode",
    "ValidationResult",
    "VerificationSpec",
    "blocking",
]
