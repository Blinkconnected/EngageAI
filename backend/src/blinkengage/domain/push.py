"""The push-notification contract: what a message is, and what happened
to it. See ``docs/architecture/notifications.md``.

Framework-free — no SQLAlchemy, no FastAPI, no HTTP client — like
``domain/rbac.py``, ``domain/money.py`` and ``domain/channel_provider.py``,
so the dispatch sweep, the sender implementations and the tests share one
definition without a dependency cycle.

**The outcome is the interesting part of this module.** A push either
arrived, or failed in one of two fundamentally different ways, and
treating them alike is how a push transport becomes either a silent
black hole or an infinite retry loop:

- ``DELIVERED`` — the provider accepted it. That is all any push
  transport can ever promise; nothing downstream can tell you whether a
  phone actually lit up.
- ``RETRY`` — a transient fault (provider 5xx, throttling, a network
  blip). The notification stays unmarked and the next sweep tries again.
- ``DEVICE_GONE`` — the provider says this token is dead: the app was
  uninstalled, the token rotated, or it was never valid. Retrying it will
  fail identically forever, so the token is deleted rather than kept.

A sender returns one of these per device. It never raises for an expected
provider rejection — a rejection is an answer, not a fault — and never
decides what to do about it, which is the sweep's job.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum


class DevicePlatform(StrEnum):
    """What kind of device a token belongs to.

    Recorded even though FCM's HTTP v1 API does not need it to route a
    message: the per-platform blocks of an FCM payload differ (``android``
    priority versus ``apns`` headers), a support conversation starts with
    "which platform", and a second transport added later — APNs directly,
    say — routes on exactly this.
    """

    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class PushOutcome(StrEnum):
    DELIVERED = "delivered"
    RETRY = "retry"
    DEVICE_GONE = "device_gone"


@dataclass(frozen=True, slots=True)
class PushMessage:
    """One notification, addressed to one device.

    ``data`` is deep-linking material — ``{"conversation_id": "..."}`` —
    and every value is a string. That is not this module being fussy: FCM
    rejects a data payload whose values are not strings, so the
    conversion belongs at the boundary where the dict is built rather
    than in each sender.
    """

    token: str
    platform: DevicePlatform
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        non_strings = sorted(k for k, v in self.data.items() if not isinstance(v, str))
        if non_strings:
            raise ValueError(
                f"PushMessage.data values must be strings; {non_strings} are not. "
                "Stringify at the call site — a provider rejecting the whole "
                "payload for one stray integer is a silent delivery failure."
            )


@dataclass(frozen=True, slots=True)
class PushResult:
    outcome: PushOutcome
    #: Provider-side detail for the log line — an FCM error code, an HTTP
    #: status. Never shown to a user; a push failing is not their problem
    #: to solve.
    detail: str | None = None

    @property
    def is_delivered(self) -> bool:
        return self.outcome is PushOutcome.DELIVERED


class PushSender(ABC):
    """The plugin contract every push transport satisfies.

    An ABC rather than a ``Protocol``, matching ``ChannelProvider``: the
    dispatch sweep resolves "the configured sender" from settings rather
    than holding a reference to a concrete class, and a shared base is
    where the "never raise for a provider rejection" rule is stated once.

    Implementations are constructed with plain, already-resolved
    credentials — never a settings object or an ORM row — so this stays a
    pure contract and the factory in ``infrastructure.push`` is the only
    thing that knows where credentials come from.
    """

    #: Registry key, e.g. ``"fcm"``. Appears in log lines, so an operator
    #: reading them can tell which transport answered.
    transport: str

    @abstractmethod
    async def send(self, message: PushMessage) -> PushResult:
        """Deliver one message, returning what happened.

        Must not raise for anything the provider can be expected to say —
        a dead token, a throttle, a 5xx. Those are ``PushResult`` values.
        An exception escaping here means something genuinely unexpected,
        and the sweep treats it as ``RETRY``.
        """

    async def aclose(self) -> None:
        """Release any transport-level resource (an HTTP connection pool).

        A default no-op so a sender with nothing to release — a fake in a
        test — does not have to implement it.
        """
        return None


__all__ = [
    "DevicePlatform",
    "PushMessage",
    "PushOutcome",
    "PushResult",
    "PushSender",
]
