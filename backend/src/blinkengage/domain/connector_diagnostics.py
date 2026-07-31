"""What is actually wrong with this channel, without reading logs.

The audience is a support engineer with a customer on the phone, and the
measure of success is that they never open a log file. So this is a
*structured* report — codes, statuses and measurements the console renders as
a panel — rather than a text dump that has to be read to be understood.

Assembled from two sources, deliberately:

- **The platform** contributes what it knows about every channel regardless
  of type: when it was last healthy, when something last failed, how the
  connection log looks. No connector has to implement any of it, so every
  channel gets a baseline report on the day it is written.
- **The connector** contributes what only it can know: whether the provider
  still accepts its token, whether the webhook is registered *at the
  provider*, which permissions are actually granted, what the rate limit
  headroom is.

Neither can produce the other's half, which is why the report is merged
rather than owned by one side.

Everything here is a code plus parameters. A diagnostic that arrived as an
English sentence would be one a support engineer in Amman reads in English
and one no tooling can act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DiagnosticStatus(StrEnum):
    """How a single check came out.

    Four values rather than three: ``UNKNOWN`` is the honest answer for
    something nobody has measured yet, and collapsing it into ``OK`` would
    make a brand-new channel look verified when nothing has been checked.
    That distinction is the whole reason a support engineer trusts the panel.
    """

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    UNKNOWN = "unknown"


class DiagnosticKey(StrEnum):
    """The things worth knowing, as a closed set.

    Closed so the console can render a complete panel with fixed rows — a
    diagnostics screen whose sections depend on which connector you opened is
    a screen a support engineer has to re-learn per channel.

    A connector reports the subset it can answer; the platform fills the
    rest; anything nobody answered shows as ``UNKNOWN`` rather than being
    silently absent.
    """

    #: Does the stored credential still work?
    AUTHENTICATION = "authentication"
    #: Is the provider actually pointed at us?
    WEBHOOK_STATUS = "webhook_status"
    #: Which scopes are granted, versus which are needed.
    PERMISSIONS = "permissions"
    #: How close to the provider's throttle we are.
    RATE_LIMITS = "rate_limits"
    #: Which provider API version this channel is talking to.
    API_VERSION = "api_version"
    #: The last time something worked end to end.
    LAST_SUCCESSFUL_SYNC = "last_successful_sync"
    #: The last time something did not.
    LAST_FAILED_REQUEST = "last_failed_request"
    #: How slow the provider has been.
    AVERAGE_RESPONSE_TIME = "average_response_time"
    #: Work waiting to be retried.
    RETRY_QUEUE = "retry_queue"
    #: The overall verdict, for the badge at the top.
    CONNECTION_HEALTH = "connection_health"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One line of the report.

    ``value`` is the measurement as a string — a count, a duration in
    milliseconds, a version, an ISO timestamp — kept as text for the same
    reason money is: the console displays what the server measured rather
    than re-deriving it, and a number that crossed as JSON gets rounded by
    somebody's float.
    """

    key: DiagnosticKey
    status: DiagnosticStatus
    #: The measurement itself, when there is one.
    value: str | None = None
    #: A translation key describing the finding. Never a sentence.
    detail_key: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    #: When this was measured. ``None`` means "just now, as you asked".
    measured_at: datetime | None = None
    #: A ``RepairAction.id`` from the connector's manifest, when one would
    #: fix this. The console renders the button it already knows how to draw.
    repair_action: str | None = None

    @property
    def unknown(self) -> bool:
        return self.status is DiagnosticStatus.UNKNOWN


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """Everything known about one channel, right now."""

    channel_type: str
    items: tuple[Diagnostic, ...] = ()

    def get(self, key: DiagnosticKey) -> Diagnostic | None:
        for item in self.items:
            if item.key is key:
                return item
        return None

    @property
    def worst(self) -> DiagnosticStatus:
        """The overall verdict, for the badge.

        ``UNKNOWN`` deliberately does not outrank ``OK``: a channel that is
        demonstrably working but has one unmeasured line is working, and
        showing it as unknown would send a support engineer chasing a
        non-problem.
        """
        for status in (DiagnosticStatus.FAIL, DiagnosticStatus.WARN):
            if any(item.status is status for item in self.items):
                return status
        if any(item.status is DiagnosticStatus.OK for item in self.items):
            return DiagnosticStatus.OK
        return DiagnosticStatus.UNKNOWN


def complete(report: DiagnosticReport) -> DiagnosticReport:
    """Fill every unanswered key with ``UNKNOWN``.

    So the panel has the same rows for every channel. A missing row and a row
    saying "not measured" look identical in a screenshot but mean completely
    different things to whoever is reading it — one is a gap in the product,
    the other is a gap in the data.
    """
    answered = {item.key for item in report.items}
    return DiagnosticReport(
        channel_type=report.channel_type,
        items=(
            *report.items,
            *(
                Diagnostic(key=key, status=DiagnosticStatus.UNKNOWN)
                for key in DiagnosticKey
                if key not in answered
            ),
        ),
    )


def merge(*reports: DiagnosticReport) -> DiagnosticReport:
    """Combine reports, earlier ones winning.

    The connector goes first because it asked the provider; the platform's
    answer for the same key is an inference from stored state. A real
    measurement beats a remembered one.
    """
    if not reports:
        return DiagnosticReport(channel_type="")
    seen: dict[DiagnosticKey, Diagnostic] = {}
    for report in reports:
        for item in report.items:
            seen.setdefault(item.key, item)
    return DiagnosticReport(
        channel_type=reports[0].channel_type,
        items=tuple(seen[key] for key in DiagnosticKey if key in seen),
    )


__all__ = [
    "Diagnostic",
    "DiagnosticKey",
    "DiagnosticReport",
    "DiagnosticStatus",
    "complete",
    "merge",
]
