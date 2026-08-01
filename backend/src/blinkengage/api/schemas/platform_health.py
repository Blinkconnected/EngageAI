"""Wire shapes for Platform Health."""

from datetime import datetime

from pydantic import BaseModel


class MetricResponse(BaseModel):
    key: str
    #: The human name. Sent by the backend rather than mapped in the console,
    #: so a counter added to a task appears with a proper name immediately
    #: instead of as a raw key.
    label: str
    value: int


class RunResponse(BaseModel):
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    metrics: list[MetricResponse]
    #: Items this run could not process. Distinct from the run failing —
    #: thirty companies billed and one not is a different problem from a
    #: sweep that never started.
    failures: int
    error: str | None
    attempt: int


class TaskHealthResponse(BaseModel):
    name: str
    label: str
    description: str
    #: ``healthy`` / ``degraded`` / ``failing`` / ``never_run``.
    health: str
    interval_seconds: int
    last_run: RunResponse | None
    last_success: RunResponse | None
    #: Derived from the last run, not read from Celery — beat keeps that in
    #: its own scheduler file, which resets on restart. Approximate and
    #: honest beats precise and wrong.
    next_run_at: datetime | None
    consecutive_failures: int


class SchedulerHealthResponse(BaseModel):
    #: The worst of the tasks, because an installation whose invoice run has
    #: not succeeded in a day is not "mostly healthy".
    health: str
    tasks: list[TaskHealthResponse]
    #: When this was evaluated, so a page left open does not read as live.
    evaluated_at: datetime


__all__ = [
    "MetricResponse",
    "RunResponse",
    "SchedulerHealthResponse",
    "TaskHealthResponse",
]
