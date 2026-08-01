"""How mature a connector is, what version it is, and what it can carry.

Three declarations that all answer the same underlying question — *should I
rely on this?* — and that the console must be able to render without knowing
which connector it is looking at.

**Two axes, one badge.** The eight lifecycle states a customer sees are
produced by two independent facts, and keeping them separate is what makes
the answer correct on every installation:

- **Maturity** is a property of the connector's *code*. Preview, Beta,
  Production, Deprecated, End of Life. Declared in the manifest, shipped with
  the connector, identical everywhere.
- **Availability** is a property of *this installation, right now*. An
  operator turned it off; a provider is having an outage. Set at runtime,
  different on every deployment, and nothing to do with how good the code is.

Collapsing them would mean a connector in maintenance forgets it is
production-grade, and a deprecated one cannot be temporarily disabled without
losing the deprecation. So both are declared and ``effective_state`` resolves
them into the single badge the console draws — availability wins when it says
anything, because "we have turned this off" is more urgent than "this is
mature".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Maturity(StrEnum):
    """How far along the connector's own code is.

    Ordered from least to most trustworthy, then past it. Declared by the
    connector author and shipped with the connector, so it means the same
    thing on every installation.
    """

    #: Under active development. Interfaces may change, data may be lost.
    PREVIEW = "preview"
    #: Feature-complete and being proven. Safe to try, not yet promised.
    BETA = "beta"
    #: Supported, and changes to it are backwards-compatible.
    PRODUCTION = "production"
    #: Still works, will be removed. Existing channels keep running; the
    #: badge exists so nobody connects a *new* one without knowing.
    DEPRECATED = "deprecated"
    #: Removed in all but name. Existing channels may already have stopped
    #: working, and connecting a new one is refused.
    END_OF_LIFE = "end_of_life"


class Availability(StrEnum):
    """Whether this installation is offering it at all, right now."""

    #: Nothing in the way.
    AVAILABLE = "available"
    #: Temporarily not working — a provider outage, a migration in progress.
    #: Existing channels are left alone; new connections are refused, because
    #: a connection made during an outage fails in a way the customer will
    #: blame on themselves.
    MAINTENANCE = "maintenance"
    #: Switched off deliberately, by whoever runs this installation.
    DISABLED = "disabled"


class LifecycleState(StrEnum):
    """The single state the console badges.

    The union of both axes, because a customer does not care which of our
    internal distinctions produced the warning they are reading. This is what
    crosses the wire.
    """

    AVAILABLE = "available"
    PREVIEW = "preview"
    BETA = "beta"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"
    MAINTENANCE = "maintenance"
    END_OF_LIFE = "end_of_life"


#: States that refuse a *new* connection. Existing channels are deliberately
#: untouched by all of them: withdrawing a channel somebody is already
#: receiving customer messages on is a decision for an operator to take
#: explicitly, never a side effect of a status change.
BLOCKS_NEW_CONNECTIONS: frozenset[LifecycleState] = frozenset(
    {
        LifecycleState.DISABLED,
        LifecycleState.MAINTENANCE,
        LifecycleState.END_OF_LIFE,
    }
)

#: States the console warns about while still allowing the connection.
WARNS: frozenset[LifecycleState] = frozenset(
    {
        LifecycleState.PREVIEW,
        LifecycleState.BETA,
        LifecycleState.DEPRECATED,
    }
)


def effective_state(maturity: Maturity, availability: Availability) -> LifecycleState:
    """The one state to show.

    Availability wins whenever it has something to say. "We have turned this
    off" and "this is broken today" are both more urgent and more actionable
    than "this code is mature", and showing the maturity badge on a connector
    nobody can use would be answering a question the customer did not ask.
    """
    if availability is Availability.DISABLED:
        return LifecycleState.DISABLED
    if availability is Availability.MAINTENANCE:
        return LifecycleState.MAINTENANCE
    return LifecycleState(maturity.value)


@dataclass(frozen=True, slots=True)
class Version:
    """A semantic version, comparable.

    Small and local rather than a dependency: the only comparison the
    platform needs is "is this at least that", and a connector SDK that
    dragged in a version library would be imposing one on every third-party
    connector author too.

    Pre-release suffixes are parsed and then ignored for ordering. Blink
    Engage's own version is ``1.0.0-beta.5``, and a connector requiring
    ``1.0.0`` should be satisfied by it — refusing would mean no connector
    could declare a minimum until the first stable release.
    """

    major: int
    minor: int
    patch: int
    #: Kept for display. Never compared, for the reason above.
    prerelease: str = ""

    @classmethod
    def parse(cls, text: str) -> Version:
        core, _, prerelease = text.strip().partition("-")
        parts = core.split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise ValueError(f"'{text}' is not a semantic version.")
        major, minor, patch = (int(part) for part in parts)
        return cls(major=major, minor=minor, patch=patch, prerelease=prerelease)

    def satisfies(self, minimum: Version) -> bool:
        return (self.major, self.minor, self.patch) >= (
            minimum.major,
            minimum.minor,
            minimum.patch,
        )

    def __str__(self) -> str:
        core = f"{self.major}.{self.minor}.{self.patch}"
        return f"{core}-{self.prerelease}" if self.prerelease else core


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """What version of what a connector is, and what it needs.

    Three different versions that people routinely conflate, so each says
    plainly what it is:

    - ``connector`` is the connector's *own* code. It moves when the
      connector changes and nothing else does.
    - ``api`` is the **provider's** API this connector talks to — Graph
      ``v21.0``, the Bot API, whatever the provider calls its own contract.
      A customer whose provider deprecates a version needs to know this one.
    - ``minimum_platform`` is the oldest Blink Engage this connector will
      work on. It exists so a connector shipped out of band refuses to
      appear on a platform that predates what it needs, rather than failing
      halfway through a customer's flow.
    """

    connector: str = "1.0.0"
    api: str = ""
    minimum_platform: str = "1.0.0"

    def supported_by(self, platform_version: str) -> bool:
        """Whether this platform is new enough to run this connector.

        An unparseable version on either side answers ``True``. A connector
        that vanished because somebody's build stamped a non-semver string is
        a worse failure than one that appears and is never used, and the
        parse error surfaces in the upgrade warning instead.
        """
        try:
            return Version.parse(platform_version).satisfies(Version.parse(self.minimum_platform))
        except ValueError:
            return True


class ChannelFeature(StrEnum):
    """What a channel can actually carry.

    A closed set rather than free strings, so the console renders a feature
    matrix without a lookup table and two connectors cannot name the same
    capability differently. Previously these were arbitrary strings — one
    connector said ``"images"`` and another ``"media"``, and a matrix built
    from that is a matrix that lies.

    Adding a member is deliberate work: the enum, copy in both locale files,
    and every connector that has it saying so. That friction is what keeps
    the matrix meaningful.
    """

    SEND_MESSAGES = "send_messages"
    RECEIVE_MESSAGES = "receive_messages"
    MEDIA = "media"
    REACTIONS = "reactions"
    READ_RECEIPTS = "read_receipts"
    TYPING_INDICATORS = "typing_indicators"
    TEMPLATES = "templates"
    BROADCASTS = "broadcasts"
    INTERACTIVE_MESSAGES = "interactive_messages"
    VOICE_CALLS = "voice_calls"
    VIDEO_CALLS = "video_calls"
    #: Editing or deleting a message after it was sent.
    EDIT_MESSAGES = "edit_messages"
    DELETE_MESSAGES = "delete_messages"
    #: Replying to a specific earlier message, visibly.
    THREADING = "threading"


class Direction(StrEnum):
    """Which way a feature works.

    The distinction that makes a feature matrix honest. SMS *receives* media
    and cannot send it; a matrix with one tick against "Media" would be wrong
    in whichever direction the reader assumed.
    """

    BOTH = "both"
    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass(frozen=True, slots=True)
class FeatureSupport:
    """One row of the feature matrix."""

    feature: ChannelFeature
    direction: Direction = Direction.BOTH
    #: Set when support is real but qualified — "one attachment per message",
    #: "templates must be pre-approved". A translation key, like everything
    #: else a customer reads.
    note_key: str | None = None


__all__ = [
    "BLOCKS_NEW_CONNECTIONS",
    "WARNS",
    "Availability",
    "ChannelFeature",
    "Direction",
    "FeatureSupport",
    "LifecycleState",
    "Maturity",
    "Version",
    "VersionInfo",
    "effective_state",
]
