"""Two gauges the alert rules need, and nothing else.

Operational instrumentation rather than a feature: without these, two of
the alerts that catch *silent* failures cannot fire, and a rule that
cannot fire is worse than no rule because it looks like coverage.

- ``blinkengage_outbox_undispatched`` — the transactional outbox is the
  only path events take out of the database. If the relay stops, every
  downstream consumer goes quiet and nothing else alerts: the queues are
  empty, which reads as healthy.
- ``blinkengage_scheduler_last_run_timestamp_seconds`` — a beat schedule
  that stopped firing produces no error and no backlog. Phase 1.5 found
  exactly this on a stack where beat had been up 41 hours with no entry
  for a newly-added sweep.

**Collected at scrape time, cached, and fail-safe.** Two indexed queries
every 30 seconds is cheap; doing them on every scrape would not be, and
letting them raise would turn a database blip into a metrics outage —
which is the moment metrics matter most.
"""

from __future__ import annotations

import time
from collections.abc import Collection, Iterable, Mapping

from prometheus_client import CollectorRegistry, Metric
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun

logger = get_logger(__name__)

#: How long a collected sample stays fresh. Comfortably under Prometheus's
#: default 15 s scrape so a scrape rarely blocks on the database, and short
#: enough that an alert on a 10-minute ``for`` clause is not reacting to
#: stale numbers.
CACHE_SECONDS = 30.0


class OperationalCollector:
    """A Prometheus collector backed by two cached queries.

    Synchronous by necessity — ``prometheus_client`` collectors are called
    from the scrape thread and cannot await. The values are refreshed by
    :meth:`refresh` from async context and merely *read* here, which keeps
    the scrape path free of database access entirely.
    """

    def __init__(
        self,
        scheduled_tasks: Collection[str] | None = None,
        expected_intervals: Mapping[str, float] | None = None,
    ) -> None:
        #: Which task names the staleness gauge reports on.
        #:
        #: ``scheduler_runs`` accumulates a row for anything that ever ran
        #: under ``record_run``, including one-off probes and tasks since
        #: removed from the beat schedule. Reporting those means the
        #: "sweep has stopped running" alert fires forever on a task that
        #: is not supposed to run at all — and an alert that cannot be
        #: cleared is one people learn to ignore. Found exactly this on a
        #: development stack: a `probe.failing.task` row from four days
        #: earlier holding the alert permanently pending.
        #:
        #: ``None`` means report everything, which is what the tests want.
        self._scheduled_tasks = set(scheduled_tasks) if scheduled_tasks is not None else None
        #: Each task's beat interval, exported so an alert can compare a
        #: task's silence against *its own* schedule.
        #:
        #: A single global staleness threshold cannot work here: the beat
        #: schedule spans five seconds (the outbox relay) to twenty-four
        #: hours (configuration drift). Any fixed number is either
        #: permanently breached by the daily tasks or blind to a
        #: five-second task that has been dead since yesterday.
        self._expected_intervals = dict(expected_intervals or {})
        self._undispatched: float | None = None
        self._last_run_epoch: dict[str, float] = {}
        self._collected_at = 0.0

    @property
    def is_stale(self) -> bool:
        return (time.monotonic() - self._collected_at) > CACHE_SECONDS

    async def refresh(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Re-read both values. Never raises.

        A failure leaves the previous sample in place and logs — the
        alternative is a metrics endpoint that fails during exactly the
        incident somebody is trying to diagnose.
        """
        try:
            async with session_factory() as session:
                undispatched = (
                    await session.execute(
                        select(func.count(EventOutbox.id)).where(
                            EventOutbox.dispatched_at.is_(None)
                        )
                    )
                ).scalar_one()
                rows = (
                    await session.execute(
                        select(SchedulerRun.task_name, func.max(SchedulerRun.started_at)).group_by(
                            SchedulerRun.task_name
                        )
                    )
                ).all()

            self._undispatched = float(undispatched or 0)
            self._last_run_epoch = {
                str(task): started.timestamp()
                for task, started in rows
                if started is not None
                and (self._scheduled_tasks is None or str(task) in self._scheduled_tasks)
            }
            self._collected_at = time.monotonic()
        except Exception:  # noqa: BLE001
            logger.exception("operational_metrics_refresh_failed")

    def collect(self) -> Iterable[Metric]:
        if self._undispatched is not None:
            gauge = GaugeMetricFamily(
                "blinkengage_outbox_undispatched",
                "Domain events written to the outbox and not yet published.",
            )
            gauge.add_metric([], self._undispatched)
            yield gauge

        if self._last_run_epoch:
            runs = GaugeMetricFamily(
                "blinkengage_scheduler_last_run_timestamp_seconds",
                "Unix timestamp of the most recent run of each scheduled task.",
                labels=["task"],
            )
            for task, epoch in sorted(self._last_run_epoch.items()):
                runs.add_metric([task], epoch)
            yield runs

        if self._expected_intervals:
            intervals = GaugeMetricFamily(
                "blinkengage_scheduler_expected_interval_seconds",
                "Configured beat interval for each scheduled task.",
                labels=["task"],
            )
            for task, seconds in sorted(self._expected_intervals.items()):
                intervals.add_metric([task], seconds)
            yield intervals


def register(registry: CollectorRegistry, collector: OperationalCollector) -> None:
    """Idempotent registration.

    Re-registering raises in ``prometheus_client``, and the test suite
    builds the app many times in one process — so a duplicate has to be a
    no-op rather than an error that only appears under test.

    Keyed on the collector *type*, not on a metric name. Name-based
    detection is unreliable here because ``prometheus_client`` learns a
    collector's names by calling ``collect()`` at registration time, and
    this collector emits nothing until its first refresh — so which names
    the registry has seen depends on when registration happened relative
    to that. Getting this wrong is silent until the second app in a
    process: the guard checks for a name that was never recorded, misses,
    registers again, and every subsequent test errors on a duplicate
    timeseries.
    """
    existing = getattr(registry, "_collector_to_names", {})
    if any(isinstance(registered, OperationalCollector) for registered in existing):
        return
    registry.register(collector)


__all__ = ["CACHE_SECONDS", "OperationalCollector", "register"]
