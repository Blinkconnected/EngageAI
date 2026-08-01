"""Running the suite, and turning it into a score.

The runner owns every judgement a connector must not make about itself:
which scenarios apply, which are safe to execute here, how long each took,
and what the resulting number is. A connector demonstrates; it never grades.

That split is the point. A connector deciding its own scenario was
"not applicable" is a connector deciding its own denominator, and within a
release every score would be 100%.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, date, datetime
from typing import Any

from blinkengage.domain.connector import Connector, DeploymentContext
from blinkengage.domain.connector_certification import (
    EMITS_TO_A_CUSTOMER,
    MUTATES_THE_CHANNEL,
    CertificationReport,
    Compatibility,
    Outcome,
    ScenarioKind,
    ScenarioResult,
    certify,
    supports_scenario,
)
from blinkengage.domain.connector_lifecycle import ChannelFeature, Direction
from blinkengage.infrastructure.connectors.registry import ConnectorRegistry
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig

#: A scenario gets this long before the run moves on. A certification run is
#: watched by whoever started it, and eleven scenarios that could each hang
#: for thirty seconds is a screen nobody waits out.
SCENARIO_TIMEOUT = 20.0


class ConnectorCertificationService:
    """Executes a connector's scenarios against one live channel."""

    def __init__(self, *, context: DeploymentContext) -> None:
        self._context = context

    async def run(
        self,
        channel: ChannelConfig,
        *,
        target: str | None = None,
        include_mutating: bool = False,
        callback_url: str | None = None,
    ) -> CertificationReport:
        """Run everything that is safe to run, and score it.

        ``target`` is where a scenario that emits something should send it —
        a test number, a test conversation. Without one, every scenario that
        would put a message in front of a person is skipped rather than
        guessed at. A certification run must never be the reason a real
        customer receives a message, and defaulting to "the last person who
        wrote in" is exactly how that would happen.

        ``include_mutating`` is off by default for the same reason from the
        other direction: disconnect, reconnect and token refresh change the
        channel's state with the provider, and a run that left a working
        channel in whatever state it finished in would be a diagnostic worse
        than the problem.
        """
        connector = ConnectorRegistry.get(channel.channel_type)
        started = time.perf_counter()
        ran_at = datetime.now(UTC)

        if connector is None:
            return self._empty(channel, ran_at)

        declared = tuple(
            (support.feature, support.direction)
            for support in connector.manifest.supported_features
        )
        credentials = dict(channel.credentials)

        results: list[ScenarioResult] = []
        for kind in ScenarioKind:
            results.append(
                await self._one(
                    connector,
                    kind,
                    declared=declared,
                    credentials=credentials,
                    target=target,
                    include_mutating=include_mutating,
                    channel=channel,
                    callback_url=callback_url,
                )
            )

        return CertificationReport(
            channel_type=channel.channel_type,
            results=tuple(results),
            certification=certify(tuple(results)),
            compatibility=Compatibility(
                platform_version=self._context.platform_version,
                connector_version=connector.manifest.versions.connector,
                provider_api_version=connector.manifest.versions.api,
                last_verified=ran_at,
                supported_until=connector.supported_until(),
            ),
            ran_at=ran_at,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    async def _one(
        self,
        connector: Connector,
        kind: ScenarioKind,
        *,
        declared: tuple[tuple[ChannelFeature, Direction], ...],
        credentials: dict[str, Any],
        target: str | None,
        include_mutating: bool,
        channel: ChannelConfig,
        callback_url: str | None,
    ) -> ScenarioResult:
        """One scenario, with every guard applied before the connector runs.

        Order matters. "Not supported" is checked first because it is the
        only outcome that leaves the score untouched, and a connector that
        never claimed a behaviour must not be skipped *or* failed for it —
        both would put it in the denominator.
        """
        if not supports_scenario(kind, declared):
            return ScenarioResult(kind=kind, outcome=Outcome.NOT_SUPPORTED)

        if kind in EMITS_TO_A_CUSTOMER and not target:
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.SKIPPED,
                detail_key="certification.skipped.noTarget",
            )
        if kind in MUTATES_THE_CHANNEL and not include_mutating:
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.SKIPPED,
                detail_key="certification.skipped.wouldChangeTheChannel",
            )

        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                connector.run_scenario(
                    kind,
                    credentials=credentials,
                    context=self._context,
                    target=target,
                    # What ``repair`` already receives. Without these,
                    # disconnect and reconnect can only be executed by
                    # rotating a secret the channel's column would not have —
                    # which every connector correctly refused to do.
                    webhook_secret=channel.webhook_secret,
                    callback_url=callback_url,
                    external_id=getattr(channel, "external_id", None),
                    external_parent_id=getattr(channel, "external_parent_id", None),
                ),
                timeout=SCENARIO_TIMEOUT,
            )
        except TimeoutError:
            # The timeout was defined, documented and never applied — so one
            # connector hanging hung the whole suite, on a screen somebody is
            # watching. A scenario that ran out of time was not measured, so
            # it is skipped rather than failed.
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.SKIPPED,
                duration_ms=round((time.perf_counter() - started) * 1000),
                detail_key="certification.skipped.timedOut",
            )
        except Exception:  # noqa: BLE001 - a suite reports, it does not stop
            # A connector that raised despite the contract fails *that*
            # scenario and nothing else. Stopping the run would report the
            # connector as worse than it is and hide every scenario after it.
            return ScenarioResult(
                kind=kind,
                outcome=Outcome.FAIL,
                duration_ms=round((time.perf_counter() - started) * 1000),
                detail_key="certification.raised",
            )

        # Timed here rather than trusting the connector's own number: a
        # connector reporting its own duration is a connector reporting its
        # own performance.
        return ScenarioResult(
            kind=result.kind,
            outcome=result.outcome,
            duration_ms=round((time.perf_counter() - started) * 1000),
            detail_key=result.detail_key,
            params=result.params,
            diagnostics=result.diagnostics,
        )

    def _empty(self, channel: ChannelConfig, ran_at: datetime) -> CertificationReport:
        results = tuple(
            ScenarioResult(kind=kind, outcome=Outcome.NOT_SUPPORTED) for kind in ScenarioKind
        )
        return CertificationReport(
            channel_type=channel.channel_type,
            results=results,
            certification=certify(results),
            compatibility=Compatibility(
                platform_version=self._context.platform_version,
                connector_version="",
                provider_api_version="",
            ),
            ran_at=ran_at,
        )


def expiring_soon(report: CertificationReport, *, within_days: int = 90) -> bool:
    """Whether an administrator should be looking at this one.

    Ninety days because a provider API deprecation is a migration, not a
    patch — and finding out the week it happens is finding out too late.
    """
    return report.compatibility.expiring_within(within_days, today=date.today())


__all__ = ["SCENARIO_TIMEOUT", "ConnectorCertificationService", "expiring_soon"]
