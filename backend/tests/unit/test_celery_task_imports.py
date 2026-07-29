"""Every Celery task module must import.

This exists because a wrong import path in a task module is invisible
until a worker starts: nothing in the API imports these modules, so the
test suite, ruff and mypy all passed while the worker crashed on boot
with ``ModuleNotFoundError`` — taking every scheduled job down with it,
not just the new one.

Importing each module is a weak assertion, and deliberately so. It is
the exact check that was missing, it costs milliseconds, and it fails
loudly at the moment the mistake is made rather than the next time
somebody looks at a worker log.
"""

import importlib

import pytest

from blinkengage.core.celery_app import celery_app

#: Taken from the app's own `include`, not from a directory listing:
#: this is precisely the list a worker imports at boot, so the test
#: fails on exactly what would crash the worker — including tasks that
#: live outside the tasks package, like the outbox relay.
WORKER_MODULES: tuple[str, ...] = tuple(celery_app.conf.include or ())


def test_there_are_worker_modules_to_check() -> None:
    """Guards the guard: if `include` were emptied, the parametrised
    test below would silently pass with nothing to check."""
    assert WORKER_MODULES, "celery_app.conf.include is empty"


@pytest.mark.parametrize("module_name", WORKER_MODULES)
def test_worker_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)


def test_every_scheduled_task_is_registered() -> None:
    """A beat entry naming a task that does not exist fails at runtime,
    once an hour, in a log nobody is reading."""
    for module_name in WORKER_MODULES:
        importlib.import_module(module_name)

    scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}
    missing = scheduled - set(celery_app.tasks)
    assert not missing, f"scheduled but not registered: {sorted(missing)}"
