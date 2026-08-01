"""Diagnosing a channel without reading logs.

The support engineer has a customer on the phone. This assembles, in one
call, what would otherwise be a database query, a log search and a guess.

Two contributors, merged:

- **The connector** asks the provider. Only it can answer whether the token
  still works, whether the webhook is registered *at the provider*, which
  scopes are granted. Live measurements, and they cost a round trip.
- **This service** reads what the platform already recorded — the channel's
  last health check, its connection log, when something last succeeded and
  last failed. No connector has to implement anything for this half, so every
  channel has a useful report from the day it is written.

A real measurement beats a remembered one, so the connector's answer wins for
any key both can produce. Everything nobody answered comes back ``UNKNOWN``
rather than absent: a missing row and a row saying "not measured" look the
same in a screenshot and mean completely different things.
"""

from __future__ import annotations

import statistics

from blinkengage.domain.connector import DeploymentContext
from blinkengage.domain.connector_diagnostics import (
    Diagnostic,
    DiagnosticKey,
    DiagnosticReport,
    DiagnosticStatus,
    complete,
    merge,
)
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.channel_connection_log import (
    ChannelConnectionLog,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)

#: How many log entries to reason over. Enough for an average that means
#: something, few enough that the query stays cheap on a busy channel.
WINDOW = 50

#: A connector gets this long to answer before the report is assembled
#: without it. A diagnostics panel that hangs on an unreachable provider is a
#: panel that fails exactly when the provider being unreachable is the thing
#: the engineer is trying to find out.
CONNECTOR_TIMEOUT = 12.0


class ChannelDiagnosticsService:
    """One report per channel, from everything available."""

    def __init__(self, *, logs: ChannelConnectionLogRepository, context: DeploymentContext) -> None:
        self._logs = logs
        self._context = context

    async def report(self, channel: ChannelConfig) -> DiagnosticReport:
        """Ask the connector, read what we know, merge, fill the gaps."""
        from_connector = await self._ask_connector(channel)
        from_platform = await self._from_platform(channel)
        return complete(merge(from_connector, from_platform))

    # --- The connector's half -----------------------------------------

    async def _ask_connector(self, channel: ChannelConfig) -> DiagnosticReport:
        connector = ConnectorRegistry.get(channel.channel_type)
        if connector is None:
            return DiagnosticReport(channel_type=channel.channel_type)
        try:
            return await connector.diagnose(
                credentials=dict(channel.credentials), context=self._context
            )
        except Exception:  # noqa: BLE001 - a report never fails to be produced
            # A connector that raised despite the contract must not take the
            # whole panel with it. The platform's half is still worth showing,
            # and the missing keys come back UNKNOWN, which is the truth.
            return DiagnosticReport(channel_type=channel.channel_type)

    # --- What the platform already knows ------------------------------

    async def _from_platform(self, channel: ChannelConfig) -> DiagnosticReport:
        entries, _total = await self._logs.list_for_channel(
            channel_config_id=channel.id, offset=0, limit=WINDOW
        )
        items: list[Diagnostic] = [self._health(channel)]

        successes = [e for e in entries if e.level not in {"error", "warning"}]
        failures = [e for e in entries if e.level == "error"]

        if successes:
            items.append(
                Diagnostic(
                    key=DiagnosticKey.LAST_SUCCESSFUL_SYNC,
                    status=DiagnosticStatus.OK,
                    value=successes[0].created_at.isoformat(),
                    measured_at=successes[0].created_at,
                )
            )
        if failures:
            newest = failures[0]
            items.append(
                Diagnostic(
                    key=DiagnosticKey.LAST_FAILED_REQUEST,
                    status=(
                        # Only a *recent* failure is a warning. An error from
                        # three weeks ago on a channel that has worked since
                        # is history, and flagging it sends an engineer
                        # chasing something already fixed.
                        DiagnosticStatus.WARN
                        if not successes or newest.created_at > successes[0].created_at
                        else DiagnosticStatus.OK
                    ),
                    value=newest.created_at.isoformat(),
                    detail_key="diagnostics.lastFailure",
                    params={"event": str(newest.event_type)},
                    measured_at=newest.created_at,
                )
            )

        average = self._average_response_ms(entries)
        if average is not None:
            items.append(
                Diagnostic(
                    key=DiagnosticKey.AVERAGE_RESPONSE_TIME,
                    # No threshold: what counts as slow differs per provider,
                    # and a number an engineer can read beats a verdict the
                    # platform is not qualified to give.
                    status=DiagnosticStatus.OK,
                    value=str(round(average)),
                    params={"unit": "ms", "samples": str(len(entries))},
                )
            )

        return DiagnosticReport(channel_type=channel.channel_type, items=tuple(items))

    def _health(self, channel: ChannelConfig) -> Diagnostic:
        """The overall verdict, from the health sweep that already runs.

        Never invented: a channel nobody has checked reports ``UNKNOWN``
        rather than ``OK``, because a green tick on an unverified channel is
        the one thing that would make this panel worse than no panel.
        """
        if channel.last_health_status is None:
            return Diagnostic(
                key=DiagnosticKey.CONNECTION_HEALTH,
                status=DiagnosticStatus.UNKNOWN,
                detail_key="diagnostics.neverChecked",
            )
        healthy = channel.last_health_status == "healthy"
        return Diagnostic(
            key=DiagnosticKey.CONNECTION_HEALTH,
            status=DiagnosticStatus.OK if healthy else DiagnosticStatus.FAIL,
            value=channel.last_health_status,
            detail_key=(
                None
                if healthy
                # The origin says *whose* problem it is — the provider's
                # servers, our configuration, the network — which is the
                # first thing a support engineer needs to know.
                else f"diagnostics.unhealthy.{channel.last_health_origin or 'unknown'}"
            ),
            params=({} if healthy else {"detail": str(channel.last_health_detail or "")}),
            measured_at=channel.last_health_checked_at,
        )

    @staticmethod
    def _average_response_ms(entries: list[ChannelConnectionLog]) -> float | None:
        """Mean provider latency, where the log happened to record it.

        Opportunistic on purpose. Connection logs carry a metadata blob and
        some events record a duration; nothing yet records it consistently,
        so this reports an average when there is one and stays silent
        otherwise. Silence is honest; a mean of two samples presented as a
        performance figure is not.
        """
        samples = [
            float(entry.log_metadata["duration_ms"])
            for entry in entries
            if isinstance(getattr(entry, "log_metadata", None), dict)
            and isinstance(entry.log_metadata.get("duration_ms"), int | float)
        ]
        return statistics.fmean(samples) if len(samples) >= 3 else None


__all__ = ["CONNECTOR_TIMEOUT", "WINDOW", "ChannelDiagnosticsService"]
