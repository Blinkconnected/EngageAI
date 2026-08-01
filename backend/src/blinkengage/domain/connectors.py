"""What a connector can do, and the flow that follows from it.

Blink Engage is a messaging platform; a channel is a transport adapter. This
module is where that stops being a slogan. It defines a **capability
contract** every connector answers, and derives the connection flow from the
answers — so the wizard that connects WhatsApp is the same wizard, running the
same code, that connects Telegram, Slack or RCS.

The rule this exists to enforce: **nothing above this layer may branch on a
channel type.** No `if connector == "meta"`, in the wizard, in the API, or in
the console. A screen that asks "which channel is this?" has to be changed for
every channel added after it; a screen that asks "what can this connector do?"
does not. The nine channels on the roadmap — Teams, Slack, Discord, LinkedIn,
Apple Messages, RCS, Viber, LINE, WeChat — must each be a new
``Connector`` and nothing else.

Capabilities are resolved **per deployment**, not declared once. The same Meta
connector offers OAuth on a hosted installation that holds a Meta app, offers
it on a self-hosted one whose administrator supplied their own, and offers
only the guided manual path on one with neither. That is three rows in an
operator's mental model and one implementation here, which is the point.

Deliberately pure: no ORM, no HTTP, no settings object. It can be reasoned
about and tested without a database, and a connector author can read the whole
contract in one file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from blinkengage.domain.connector_lifecycle import (
    BLOCKS_NEW_CONNECTIONS,
    WARNS,
    LifecycleState,
)


class Capability(StrEnum):
    """One thing a connector may be able to do.

    A set rather than a fixed record of booleans: adding a capability must
    not require editing every connector that will never have it. A connector
    declares what it supports and stays silent about the rest.
    """

    #: The customer authenticates by being redirected to the provider and
    #: consenting, rather than by pasting a secret. The whole point of the
    #: milestone, and the reason the flow has an Authenticate step at all.
    OAUTH = "oauth"

    #: After authenticating, the connector can *list* what the customer owns
    #: — business accounts, pages, phone numbers, bots, workspaces — so they
    #: choose from a list instead of hunting for an id in a dashboard.
    AUTO_DISCOVERY = "auto_discovery"

    #: The provider delivers inbound events to a callback URL. Absent for a
    #: connector we poll (IMAP) or that has no inbound at all.
    WEBHOOKS = "webhooks"

    #: We can register that callback URL with the provider ourselves. Without
    #: it the customer has to paste a URL into somebody's dashboard, which is
    #: exactly the experience this milestone exists to delete.
    AUTOMATIC_WEBHOOK_REGISTRATION = "automatic_webhook_registration"

    #: Inbound events for every tenant arrive at one installation-wide URL
    #: and are fanned out by payload, rather than at a URL per channel.
    #: A property of the provider's app model, not a preference.
    SHARED_WEBHOOK = "shared_webhook"

    #: Credentials expire and can be renewed without the customer present.
    #: Decides whether "Token expires soon" is a warning or an action.
    TOKEN_REFRESH = "token_refresh"

    #: The connector can be asked, cheaply and on a timer, whether it still
    #: works.
    HEALTH_CHECKS = "health_checks"

    #: The customer can create the underlying account *during* the flow
    #: rather than needing one already (Meta's Embedded Signup creates a
    #: WhatsApp Business Account for somebody who has none).
    EMBEDDED_SIGNUP = "embedded_signup"

    #: Credentials can be entered by hand. Always kept alongside OAuth
    #: rather than replaced by it: it is the only path when no platform app
    #: is configured, the fallback when consent fails, and the one that
    #: works while a provider's app review is still pending.
    MANUAL_CONFIGURATION = "manual_configuration"


@dataclass(frozen=True, slots=True)
class CapabilityState:
    """Whether a capability is available *here*, and why not if it isn't.

    ``reason`` is a **code**, never a sentence. The console translates it, so
    an Arabic operator reads Arabic — and a reason that travels as English
    prose is a reason that can never be translated. See the same decision for
    billing status codes in ``docs/architecture/billing.md``.
    """

    capability: Capability
    available: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.available and self.reason is not None:
            raise ValueError("An available capability does not need a reason.")


class StepKind(StrEnum):
    """How a step is *rendered*, which is all the console needs to know.

    The console switches on this and never on the channel. Six renderers
    cover every connector that exists and every one on the roadmap; a
    connector that needed a seventh would be telling us something new about
    connecting to things, which is a good reason to add one and a bad thing
    to discover in a screen full of channel-specific branches.
    """

    #: Choose what to connect.
    SELECT = "select"
    #: Leave for the provider and come back consented.
    OAUTH_REDIRECT = "oauth_redirect"
    #: Fields the server describes; the console renders them without knowing
    #: what they mean.
    FORM = "form"
    #: Choose from what discovery found.
    RESOURCE_PICKER = "resource_picker"
    #: Checks that passed, warned or failed, each with its fix.
    CHECKLIST = "checklist"
    #: Confirm, and watch it happen.
    SUMMARY = "summary"


class StepId(StrEnum):
    """The five stages of the flow, as the customer experiences them.

    Stable across connectors so the progress indicator means the same thing
    everywhere: a customer who has connected one channel recognises the
    second. ``StepKind`` is how a stage is drawn; ``StepId`` is what it is
    for.
    """

    SELECT = "select"
    AUTHENTICATE = "authenticate"
    DISCOVER = "discover"
    VERIFY = "verify"
    CONNECT = "connect"


@dataclass(frozen=True, slots=True)
class Step:
    """One stage of a connection flow."""

    id: StepId
    kind: StepKind
    #: Copy lives in the console's translation files, keyed by this. The
    #: server sends a key, never a sentence — same reason as ``reason``.
    title_key: str
    #: True when the step exists only to tell the customer something and
    #: needs no input from them, so the console can pass straight through it.
    automatic: bool = False


@dataclass(frozen=True, slots=True)
class ConnectorProfile:
    """What one connector can do on *this* installation, right now.

    The thing the API returns and the console renders itself from. Two
    installations get different profiles from the same connector, and neither
    the API nor the console has to know why.
    """

    channel_type: str
    #: What this connector could ever do, deployment aside. Useful to show a
    #: customer what a channel is capable of before they have configured
    #: anything.
    declares: frozenset[Capability]
    #: What it can do here, with a reason for anything it cannot.
    states: tuple[CapabilityState, ...] = ()
    #: The single state the console badges, resolved from the connector's
    #: declared maturity and this installation's runtime availability.
    lifecycle: LifecycleState = LifecycleState.PRODUCTION
    #: False when this platform is older than the connector requires. Kept
    #: separate from ``lifecycle`` because "you need to upgrade Blink Engage"
    #: and "this connector is in beta" are different sentences with different
    #: audiences — one is for an administrator, the other for a customer.
    platform_supported: bool = True

    def supports(self, capability: Capability) -> bool:
        """Whether the capability is available on this installation."""
        for state in self.states:
            if state.capability is capability:
                return state.available
        return False

    def reason(self, capability: Capability) -> str | None:
        for state in self.states:
            if state.capability is capability:
                return state.reason
        return None

    @property
    def available(self) -> frozenset[Capability]:
        return frozenset(state.capability for state in self.states if state.available)

    @property
    def connectable(self) -> bool:
        """Whether a *new* channel can be connected here, right now.

        Three ways to answer no, and all three have to be checked in one
        place or each caller invents its own combination:

        - no way in at all — neither consent nor a form, so the flow has no
          first step;
        - a lifecycle state that refuses new connections — switched off, in
          maintenance, or past end of life;
        - a platform older than the connector needs.

        Existing channels are unaffected by the last two, deliberately.
        Withdrawing a channel a customer is already receiving messages on is
        a decision an operator takes explicitly, never a side effect of a
        status change.
        """
        if self.lifecycle in BLOCKS_NEW_CONNECTIONS or not self.platform_supported:
            return False
        return self.supports(Capability.OAUTH) or self.supports(Capability.MANUAL_CONFIGURATION)

    @property
    def warns(self) -> bool:
        """Whether the console should show a caution beside the badge."""
        return self.lifecycle in WARNS


def steps_for(
    profile: ConnectorProfile,
    *,
    using_oauth: bool | None = None,
    declared: tuple[tuple[StepId, StepKind], ...] = (),
) -> tuple[Step, ...]:
    """The flow, derived from what the connector can do.

    This function is the load-bearing one. Every branch below tests a
    *capability*; none of them tests a channel. Telegram gets a form and a
    verify step because it declares manual configuration and health checks;
    Meta on a configured installation gets a redirect, a picker and a longer
    checklist because it declares OAuth and discovery. Add a connector for
    Slack and its flow falls out of its capability set with nothing here to
    change.

    ``using_oauth`` is the customer's choice on a connector that offers both
    paths, and it genuinely changes the flow: consenting yields a token the
    connector can enumerate resources with, while pasting one credential
    identifies a single resource and there is nothing to discover. ``None``
    means "not chosen yet", and the answer is the flow the customer is most
    likely to get — OAuth where it is available, because that is the path
    worth designing for.
    """
    if declared:
        # A manifest that states its own flow wins. Almost none do — deriving
        # means a connector cannot forget a step — but a connector whose
        # shape is genuinely different is saying something new about
        # connecting to things, and it should be able to say it rather than
        # be bent into the default.
        return tuple(
            Step(step_id, kind, f"connect.step.{step_id.value}") for step_id, kind in declared
        )

    oauth = profile.supports(Capability.OAUTH) if using_oauth is None else using_oauth

    steps: list[Step] = [Step(StepId.SELECT, StepKind.SELECT, "connect.step.select")]

    if oauth:
        steps.append(Step(StepId.AUTHENTICATE, StepKind.OAUTH_REDIRECT, "connect.step.authorize"))
    elif profile.supports(Capability.MANUAL_CONFIGURATION):
        steps.append(Step(StepId.AUTHENTICATE, StepKind.FORM, "connect.step.credentials"))

    # Discovery needs something to enumerate *with*. A pasted credential
    # names one resource already, so there is no list to choose from — which
    # is why this tests the grant and not only the capability.
    if oauth and profile.supports(Capability.AUTO_DISCOVERY):
        steps.append(Step(StepId.DISCOVER, StepKind.RESOURCE_PICKER, "connect.step.choose"))

    # Worth a step whenever there is anything to check. A connector with no
    # health check and no webhooks has nothing to report, and a checklist of
    # nothing is a step that only wastes the customer's time.
    if profile.supports(Capability.HEALTH_CHECKS) or profile.supports(Capability.WEBHOOKS):
        steps.append(Step(StepId.VERIFY, StepKind.CHECKLIST, "connect.step.verify", automatic=True))

    steps.append(Step(StepId.CONNECT, StepKind.SUMMARY, "connect.step.connect"))
    return tuple(steps)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """One line of the Permissions Check, and how to fix it.

    Every field exists because of the promise that the customer never reads
    the provider's documentation. A raw API error fails that promise; a check
    that names what is wrong, how bad it is, and what to press does not.
    """

    #: Stable identifier — translated by the console, recorded in logs.
    code: str
    #: ``ok`` passed; ``warn`` will work but is worth saying; ``fail`` blocks
    #: connecting. Three levels rather than two, because "your Instagram
    #: account has message access turned off" must stop the flow while "your
    #: quality rating is yellow" must not.
    level: str
    #: Parameters for the console's copy — a phone number, a scope name.
    params: dict[str, str] = field(default_factory=dict)
    #: What to do about it. ``None`` when there is nothing to be done.
    fix: Fix | None = None


@dataclass(frozen=True, slots=True)
class Fix:
    """A repair the customer can actually perform.

    ``kind`` decides how it is offered: ``action`` is a button the connector
    handles itself; ``reauthorize`` sends them back through consent for a
    scope they declined; ``reenter`` sends them back to the credentials form;
    ``manual`` is the honest admission that something can only be changed in
    the provider's own app, in which case ``instructions_key`` had better be
    step by step.

    ``reenter`` exists because three connectors independently reached for
    ``reauthorize`` to mean "the value you typed is wrong" — which for a
    channel with no OAuth would have rendered a consent button that goes
    nowhere. For a pasted-secret channel a mistyped credential is *the*
    commonest failure, and the fix is one step back, not a trip to the
    provider's documentation.
    """

    kind: str
    #: The action to invoke, for ``kind="action"``.
    action_id: str | None = None
    instructions_key: str | None = None


#: The three levels a check can report, named so a connector cannot invent a
#: fourth by typo.
CHECK_OK = "ok"
CHECK_WARN = "warn"
CHECK_FAIL = "fail"

FIX_ACTION = "action"
FIX_REAUTHORIZE = "reauthorize"
#: Back to the credentials form. The commonest fix on any channel a customer
#: authenticates by pasting a secret into.
FIX_REENTER = "reenter"
FIX_MANUAL = "manual"


def blocks_connection(checks: tuple[CheckOutcome, ...]) -> bool:
    """Whether the Permissions Check should stop the customer.

    Only ``fail`` blocks. A warning that blocked would train customers to
    treat the checklist as noise to be clicked past, which is exactly how a
    real failure gets missed.
    """
    return any(check.level == CHECK_FAIL for check in checks)


__all__ = [
    "CHECK_FAIL",
    "CHECK_OK",
    "CHECK_WARN",
    "FIX_ACTION",
    "FIX_MANUAL",
    "FIX_REAUTHORIZE",
    "FIX_REENTER",
    "Capability",
    "CapabilityState",
    "CheckOutcome",
    "ConnectorProfile",
    "Fix",
    "Step",
    "StepId",
    "StepKind",
    "blocks_connection",
    "steps_for",
]
