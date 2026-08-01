"""Every Celery task that caches an engine must dispose its pool.

This is a structural test, not a behavioural one, and it exists because the
bug it guards against is invisible in every other kind of test.

A task module caches its engine at module level and runs its body inside
``asyncio.run()``. Each invocation therefore gets a *new* event loop while
reusing pooled asyncpg connections bound to the *previous* one — and the next
run dies with "Future attached to a different loop" the moment
``pool_pre_ping`` touches a stale connection.

It cannot be caught by running a task once, which is what a unit test does.
It cannot be caught by an integration test that spawns a fresh process. It
appears only on the *second* invocation inside one worker, so it reaches
production and stays there.

It reached production three times: `close_due_periods`, `collections_sweep`
and `refresh_daily_summaries` each ran for months failing roughly every other
sweep, and only their idempotency hid the damage — a failed run left the work
for the next successful one. The fix is one ``finally`` block, and the reason
it went missing three times is that nothing checked.

Now something checks.
"""

import ast
import pathlib

import pytest

TASK_DIRS = [
    pathlib.Path(__file__).parents[2] / "src" / "blinkengage" / "infrastructure" / "tasks",
    pathlib.Path(__file__).parents[2] / "src" / "blinkengage" / "infrastructure" / "events",
]


def _task_modules() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for directory in TASK_DIRS:
        for path in sorted(directory.glob("*.py")):
            if path.name == "__init__.py":
                continue
            source = path.read_text()
            # Only modules that do both things are at risk: cache an engine
            # across calls, and open a new loop per call.
            if "_engine: AsyncEngine | None" in source and "asyncio.run(" in source:
                found.append(path)
    return found


def test_the_scan_finds_the_task_modules() -> None:
    """Guards the guard. A glob that quietly matches nothing would make
    every assertion below vacuously true."""
    modules = _task_modules()

    assert len(modules) >= 8, [p.name for p in modules]
    assert any(p.name == "billing_period_close_task.py" for p in modules)


@pytest.mark.parametrize("path", _task_modules(), ids=lambda p: p.name)
def test_a_task_that_caches_an_engine_disposes_its_pool(path: pathlib.Path) -> None:
    """``await _engine.dispose()`` must appear inside a ``finally``.

    Inside a ``finally`` specifically, not merely somewhere in the module: a
    dispose on the happy path only is a dispose that does not happen when a
    sweep raises, which is exactly when the next run needs a clean pool
    most.
    """
    tree = ast.parse(path.read_text())

    disposed_in_finally = any(
        isinstance(node, ast.Try)
        and any(
            isinstance(inner, ast.Attribute) and inner.attr == "dispose"
            for handler in node.finalbody
            for inner in ast.walk(handler)
        )
        for node in ast.walk(tree)
    )

    assert disposed_in_finally, (
        f"{path.name} caches an engine across asyncio.run() calls but never disposes "
        "its pool in a finally block. Its second invocation in a worker process will "
        'fail with "Future attached to a different loop". See events/relay.py.'
    )
