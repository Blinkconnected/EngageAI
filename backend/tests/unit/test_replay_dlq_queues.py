"""The replay tool knows about every consumer queue.

``scripts/replay_dlq.py`` hardcodes the queue list so it can run without
the backend package importable — an operator draining a dead-letter queue
is usually already dealing with something else, and a tool that needs a
working virtualenv to tell them what is quarantined is a tool that fails
when it is needed.

The cost of hardcoding is drift. A consumer added later gets a DLQ like
every other consumer, messages quarantine into it exactly as designed,
and nothing ever lists it — so nobody looks, and the alert that fires on
it points at a queue the replay tool cannot drain.

This is the guard that makes that impossible: adding a consumer without
adding it to the script fails the build instead.
"""

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONSUMERS = (
    REPO_ROOT / "backend" / "src" / "blinkengage" / "infrastructure" / "events" / "consumers"
)
REPLAY_SCRIPT = REPO_ROOT / "scripts" / "replay_dlq.py"


def _consumer_queue_names() -> set[str]:
    """Every ``QUEUE_NAME = "..."`` a consumer module declares.

    Parsed rather than imported: importing every consumer drags in the
    application container, and this test should fail for drift, not for
    an unrelated import error.
    """
    names: set[str] = set()
    for path in CONSUMERS.glob("*_consumer.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "QUEUE_NAME"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    names.add(node.value.value)
    return names


def _script_known_queues() -> set[str]:
    tree = ast.parse(REPLAY_SCRIPT.read_text(), filename=str(REPLAY_SCRIPT))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "KNOWN_QUEUES":
                return {
                    element.value
                    for element in node.value.elts  # type: ignore[attr-defined]
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                }
    raise AssertionError("KNOWN_QUEUES not found in scripts/replay_dlq.py")


def test_replay_tool_lists_every_consumer_queue() -> None:
    consumer_queues = _consumer_queue_names()
    assert consumer_queues, "no consumer QUEUE_NAME constants found — has the layout moved?"

    missing = consumer_queues - _script_known_queues()
    assert not missing, (
        "scripts/replay_dlq.py does not know about: " + ", ".join(sorted(missing)) + ". "
        "Add them to KNOWN_QUEUES, or their dead-letter queues will never be listed."
    )


def test_replay_tool_does_not_list_queues_that_no_longer_exist() -> None:
    # The other direction. A stale entry is less dangerous than a missing
    # one, but it makes `list` print queues that will never exist and
    # trains people to ignore what the tool says.
    stale = _script_known_queues() - _consumer_queue_names()
    assert not stale, "scripts/replay_dlq.py lists queues with no consumer: " + ", ".join(
        sorted(stale)
    )
