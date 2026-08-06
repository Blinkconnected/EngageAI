"""Retention deletes the old rows and only the old rows.

Two tables grew without a bound: ``scheduler_runs``, one row per sweep
per schedule forever, and ``event_outbox``, whose dispatched rows were
never removed. Pruning them is easy; pruning them *correctly* is the part
worth a test, because both ways of getting it wrong are quiet.

Delete too little and the tables keep growing, which is the bug being
fixed. Delete too much and the platform loses an event it still owed —
and the outbox exists precisely so that cannot happen. An undispatched
row has no age at which it becomes safe to drop.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun
from blinkengage.infrastructure.tasks.operational_retention_task import (
    _prune_outbox,
    _prune_scheduler_runs,
)

NOW = datetime.now(UTC)


@pytest.fixture
def session_factory(app):
    return app.state.container.session_factory()


async def _count(session_factory, model) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count(model.id)))).scalar_one()


class TestSchedulerRunRetention:
    async def test_deletes_only_runs_older_than_the_cutoff(self, session_factory) -> None:
        async with session_factory() as session:
            session.add_all(
                [
                    SchedulerRun(task_name="old", started_at=NOW - timedelta(days=40)),
                    SchedulerRun(task_name="also-old", started_at=NOW - timedelta(days=31)),
                    SchedulerRun(task_name="recent", started_at=NOW - timedelta(days=29)),
                    SchedulerRun(task_name="today", started_at=NOW),
                ]
            )
            await session.commit()

        removed = await _prune_scheduler_runs(
            session_factory, cutoff=NOW - timedelta(days=30), batch_size=100
        )

        assert removed == 2
        async with session_factory() as session:
            remaining = set((await session.execute(select(SchedulerRun.task_name))).scalars().all())
        assert remaining == {"recent", "today"}

    async def test_is_a_no_op_when_nothing_is_old_enough(self, session_factory) -> None:
        async with session_factory() as session:
            session.add(SchedulerRun(task_name="fresh", started_at=NOW))
            await session.commit()

        removed = await _prune_scheduler_runs(
            session_factory, cutoff=NOW - timedelta(days=30), batch_size=100
        )

        assert removed == 0
        assert await _count(session_factory, SchedulerRun) == 1

    async def test_deletes_more_than_one_batch(self, session_factory) -> None:
        """The batch size is a lock-duration limit, not a delete limit.

        Batching exists so a single statement does not hold a long lock on
        a table other queries need. If the loop stopped after one batch,
        a table that had grown past the batch size would never catch up
        and the retention would quietly do nothing useful.
        """
        async with session_factory() as session:
            session.add_all(
                SchedulerRun(task_name=f"old-{n}", started_at=NOW - timedelta(days=60))
                for n in range(25)
            )
            await session.commit()

        removed = await _prune_scheduler_runs(
            session_factory, cutoff=NOW - timedelta(days=30), batch_size=10
        )

        assert removed == 25
        assert await _count(session_factory, SchedulerRun) == 0


class TestOutboxRetention:
    async def test_never_deletes_an_undispatched_event(self, session_factory) -> None:
        """The one that matters.

        An undispatched row is an event the platform still owes a
        consumer. Age is not evidence it was delivered — it is evidence
        the relay has been stuck for a long time, which is when deleting
        it would do the most damage.
        """
        async with session_factory() as session:
            session.add_all(
                [
                    EventOutbox(
                        event_type="ancient.undispatched",
                        aggregate_type="conversation",
                        occurred_at=NOW,
                        payload={},
                        created_at=NOW - timedelta(days=365),
                        dispatched_at=None,
                    ),
                    EventOutbox(
                        event_type="old.dispatched",
                        aggregate_type="conversation",
                        occurred_at=NOW,
                        payload={},
                        created_at=NOW - timedelta(days=30),
                        dispatched_at=NOW - timedelta(days=30),
                    ),
                ]
            )
            await session.commit()

        removed = await _prune_outbox(
            session_factory, cutoff=NOW - timedelta(days=7), batch_size=100
        )

        assert removed == 1
        async with session_factory() as session:
            remaining = (await session.execute(select(EventOutbox.event_type))).scalars().all()
        assert remaining == ["ancient.undispatched"]

    async def test_keeps_recently_dispatched_events(self, session_factory) -> None:
        # The window is there so a replay or an investigation shortly
        # after dispatch still has something to read.
        async with session_factory() as session:
            session.add(
                EventOutbox(
                    event_type="just.dispatched",
                    aggregate_type="conversation",
                    occurred_at=NOW,
                    payload={},
                    created_at=NOW - timedelta(days=1),
                    dispatched_at=NOW - timedelta(days=1),
                )
            )
            await session.commit()

        removed = await _prune_outbox(
            session_factory, cutoff=NOW - timedelta(days=7), batch_size=100
        )

        assert removed == 0
        assert await _count(session_factory, EventOutbox) == 1
