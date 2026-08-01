"""The billing scheduler monitor.

Billing is unattended and every one of its jobs is idempotent, and those two
together are what let it fail silently for months: a failed sweep leaves its
work for the next one, so nothing looks wrong from outside. Three of them did
exactly that, and the only evidence was stack traces nobody was reading.

The property that matters most here is that a *failed* run still leaves a
record. A monitor that only records successes is a monitor that goes quiet
precisely when something is wrong.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.scheduler import (
    BILLING_TASKS,
    RunSummary,
    ScheduledTask,
    SchedulerHealth,
    SchedulerRunStatus,
    TaskHealth,
    overall,
)
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun
from blinkengage.infrastructure.tasks.run_recorder import record_run
from tests.integration.test_pricing_engine import platform_headers

pytestmark = pytest.mark.asyncio


async def runs(app: Any, task_name: str) -> list[SchedulerRun]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        result = await session.execute(
            select(SchedulerRun)
            .where(SchedulerRun.task_name == task_name)
            .order_by(SchedulerRun.started_at)
        )
        return list(result.scalars().all())


class TestARunIsRecorded:
    async def test_a_successful_run_records_what_it_counted(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        name = f"probe.{uuid.uuid4().hex[:8]}"

        async with record_run(factory, task_name=name) as report:
            report.count("companies_processed", 12)
            report.count("invoices_generated", 3)

        [run] = await runs(app, name)
        assert run.status is SchedulerRunStatus.SUCCEEDED
        assert run.metrics == {"companies_processed": 12, "invoices_generated": 3}
        assert run.duration_ms is not None
        assert run.finished_at is not None

    async def test_a_failed_run_is_recorded_and_still_raises(self, app: Any) -> None:
        """The whole point. A monitor that records only successes goes quiet
        exactly when something is wrong — and the task must still fail, so
        Celery retries and alerting fires as before."""
        factory = app.state.container.session_factory()
        name = f"probe.{uuid.uuid4().hex[:8]}"

        with pytest.raises(RuntimeError, match="gateway refused"):
            async with record_run(factory, task_name=name) as report:
                report.count("companies_processed", 7)
                raise RuntimeError("gateway refused the connection")

        [run] = await runs(app, name)
        assert run.status is SchedulerRunStatus.FAILED
        assert run.error is not None
        assert "gateway refused" in run.error
        # The counters from before the failure survive: a run that got
        # part-way is more useful than a failure with no numbers at all.
        assert run.metrics == {"companies_processed": 7}

    async def test_items_that_failed_are_counted_separately(self, app: Any) -> None:
        """A sweep that billed thirty companies and could not bill one is a
        different problem from a sweep that never started. Calling both
        "failed" hides the first."""
        factory = app.state.container.session_factory()
        name = f"probe.{uuid.uuid4().hex[:8]}"

        async with record_run(factory, task_name=name) as report:
            report.count("companies_processed", 30)
            report.record_failure()

        [run] = await runs(app, name)
        assert run.status is SchedulerRunStatus.SUCCEEDED
        assert run.failures == 1

    async def test_a_row_exists_while_the_run_is_still_going(self, app: Any) -> None:
        """Written before the work, so a worker killed mid-sweep leaves a
        RUNNING row that ages visibly. Recording only on completion would
        leave nothing, and "no row" is indistinguishable from "never
        scheduled"."""
        factory = app.state.container.session_factory()
        name = f"probe.{uuid.uuid4().hex[:8]}"

        async with record_run(factory, task_name=name):
            mid_flight = await runs(app, name)

        assert len(mid_flight) == 1
        assert mid_flight[0].status is SchedulerRunStatus.RUNNING
        assert mid_flight[0].finished_at is None


class TestTheHealthApi:
    async def test_it_lists_every_billing_job(self, client: AsyncClient, app: Any) -> None:
        response = await client.get(
            "/api/v1/platform/health/scheduler",
            headers=await platform_headers(client, app),
        )

        assert response.status_code == 200
        names = {task["name"] for task in response.json()["tasks"]}
        assert names == {task.name for task in BILLING_TASKS}

    async def test_a_fresh_installation_says_never_run(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Correct and not alarming on day one. After a deploy it means the
        beat schedule is not reaching the worker — the outage that otherwise
        looks like nothing at all."""
        response = await client.get(
            "/api/v1/platform/health/scheduler",
            headers=await platform_headers(client, app),
        )

        body = response.json()
        assert body["health"] == "never_run"
        assert all(task["health"] == "never_run" for task in body["tasks"])

    async def test_a_recorded_run_surfaces_its_counters_with_labels(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Labels come from the backend so a counter added to a task appears
        with a proper name instead of a raw key."""
        factory = app.state.container.session_factory()
        async with record_run(
            factory, task_name="blinkengage.billing.generate_pending_invoices"
        ) as report:
            report.count("invoices_generated", 5)

        response = await client.get(
            "/api/v1/platform/health/scheduler",
            headers=await platform_headers(client, app),
        )

        invoice_run = next(
            task
            for task in response.json()["tasks"]
            if task["name"] == "blinkengage.billing.generate_pending_invoices"
        )
        assert invoice_run["health"] == "healthy"
        assert invoice_run["last_run"]["metrics"] == [
            {"key": "invoices_generated", "label": "Invoices generated", "value": 5}
        ]
        assert invoice_run["next_run_at"] is not None

    async def test_a_tenant_administrator_cannot_read_it(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Installation-level: whether *the product's* background work is
        running is not a tenant's business."""
        response = await client.get(
            "/api/v1/platform/health/scheduler", headers=owner_headers
        )

        assert response.status_code in (401, 403)


def a_task(seconds: int = 3600) -> ScheduledTask:
    return ScheduledTask(name="t", label="T", interval_seconds=seconds)


def a_run(*, status: SchedulerRunStatus, minutes_ago: int, failures: int = 0) -> RunSummary:
    started = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return RunSummary(
        status=status, started_at=started, finished_at=started, duration_ms=10, failures=failures
    )


class TestWhenATaskCountsAsFailing:
    def test_one_missed_run_is_not_an_alarm(self) -> None:
        """A deploy, a worker restart, a sweep that overran its slot. A
        monitor that cries after one is a monitor people learn to ignore."""
        now = datetime.now(UTC)
        health = TaskHealth(
            task=a_task(),
            last_run=a_run(status=SchedulerRunStatus.SUCCEEDED, minutes_ago=90),
            last_success=a_run(status=SchedulerRunStatus.SUCCEEDED, minutes_ago=90),
        )

        assert health.health(now=now) is SchedulerHealth.HEALTHY

    def test_no_success_within_three_intervals_is(self) -> None:
        """The one that would have caught the real bug. Every billing task is
        idempotent, so failures are survivable and invisible; what is not
        survivable is no successful run at all."""
        now = datetime.now(UTC)
        health = TaskHealth(
            task=a_task(),
            last_run=a_run(status=SchedulerRunStatus.SUCCEEDED, minutes_ago=400),
            last_success=a_run(status=SchedulerRunStatus.SUCCEEDED, minutes_ago=400),
        )

        assert health.health(now=now) is SchedulerHealth.FAILING

    def test_a_run_with_item_failures_is_degraded_not_failing(self) -> None:
        now = datetime.now(UTC)
        health = TaskHealth(
            task=a_task(),
            last_run=a_run(status=SchedulerRunStatus.SUCCEEDED, minutes_ago=5, failures=2),
            last_success=a_run(status=SchedulerRunStatus.SUCCEEDED, minutes_ago=5, failures=2),
        )

        assert health.health(now=now) is SchedulerHealth.DEGRADED

    def test_the_worst_task_decides_the_installation(self) -> None:
        """An installation whose invoice run has not succeeded in a day is
        not "mostly healthy" because the other three are fine."""
        assert (
            overall([SchedulerHealth.HEALTHY, SchedulerHealth.HEALTHY, SchedulerHealth.FAILING])
            is SchedulerHealth.FAILING
        )
        assert overall([SchedulerHealth.HEALTHY, SchedulerHealth.DEGRADED]) is (
            SchedulerHealth.DEGRADED
        )
