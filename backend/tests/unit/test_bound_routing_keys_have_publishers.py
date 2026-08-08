"""Every routing key a consumer binds must have a publisher.

The defect this exists to catch, in full, because the shape matters more
than the instance:

``learning-signals-consumer`` bound ``conversation.reopened`` from the day
it was written. Its own module docstring called that key *"the one that
matters most: it invalidates a resolution outright"*. **Nothing in the
platform ever published it.** ``ConversationService`` emitted
``f"conversation.{status.value}"`` and only for the two *terminal*
statuses, and the other reopen path — a customer writing back, in
``conversation_ingest_consumer`` — flipped the status to ``WAITING`` and
published nothing at all.

The consumer's handler was covered by tests. Every one of them fabricated
the event dict and called the handler directly, so the binding looked
tested while the routing key had no producer anywhere. That is the same
blind spot that let the outbox relay publish nothing for months while
every consumer test passed: **a test that exercises a handler is not a
test that exercises the pipeline.**

A behavioural test cannot cover this. It would have to already know the
key was orphaned. So the check is static, like
``test_ownership_is_the_only_writer.py``,
``test_memory_manager_is_the_only_writer.py`` and
``test_learning_writes_only_its_own_tables.py`` — it covers the bindings
nobody has written yet.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from pathlib import Path

import blinkengage
from blinkengage.infrastructure.events import consumers as consumers_package

_SRC_ROOT = Path(blinkengage.__file__).resolve().parent
_CONSUMERS_ROOT = Path(consumers_package.__file__).resolve().parent


def _consumer_modules() -> list[str]:
    return sorted(
        f"{consumers_package.__name__}.{info.name}"
        for info in pkgutil.iter_modules([str(_CONSUMERS_ROOT)])
        if not info.ispkg
    )


def _bindings() -> dict[str, tuple[str, ...]]:
    """Each consumer module's declared ``ROUTING_KEYS``.

    Imported rather than parsed, deliberately: ``notification_consumer``
    computes its keys from ``NotificationRuleRegistry`` at import time, so
    a source-level read would see a function call instead of the keys a
    running consumer actually binds — which is precisely the set that has
    to have publishers.
    """
    bindings: dict[str, tuple[str, ...]] = {}
    for module_name in _consumer_modules():
        module = importlib.import_module(module_name)
        keys = getattr(module, "ROUTING_KEYS", None)
        if keys is None:
            continue
        bindings[module_name] = tuple(keys)
    return bindings


def _string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _literals_by_module() -> dict[str, set[str]]:
    """Every string literal in the package, keyed by dotted module name.

    Docstrings are excluded — a routing key *named* in prose is exactly
    what ``conversation.reopened`` had, and counting it would have made
    this guard pass on the bug it exists to catch.
    """
    literals: dict[str, set[str]] = {}
    for path in _SRC_ROOT.rglob("*.py"):
        relative = path.relative_to(_SRC_ROOT).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        module_name = ".".join(["blinkengage", *parts])
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            ast.get_docstring(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        literals[module_name] = _string_literals(path) - {d for d in docstrings if d is not None}
    return literals


def _is_wildcard(routing_key: str) -> bool:
    """RabbitMQ topic wildcards match by pattern, not by name.

    ``#`` (the audit log and the workflow engine) and ``*`` patterns are
    deliberately unresolvable to a specific publisher, so they are out of
    scope here rather than exempted case by case.
    """
    return "#" in routing_key or "*" in routing_key


def test_every_bound_routing_key_is_published_by_some_other_module() -> None:
    literals = _literals_by_module()

    orphans: list[str] = []
    for module_name, keys in _bindings().items():
        for key in keys:
            if _is_wildcard(key):
                continue
            publishers = [
                candidate
                for candidate, strings in literals.items()
                if candidate != module_name and key in strings
            ]
            if not publishers:
                orphans.append(f"{key!r} (bound by {module_name})")

    assert not orphans, (
        "These routing keys are bound by a consumer and produced by nothing:\n  "
        + "\n  ".join(sorted(orphans))
        + "\n\nA binding with no publisher is a feature that silently never runs. "
        "Either publish the event, or remove the binding."
    )


def test_the_guard_catches_an_orphaned_binding() -> None:
    """A guard nobody has watched fail is a guard nobody knows works.

    Modelled on ``test_learning_writes_only_its_own_tables.py``'s own
    self-check. Rather than plant a real binding in a real module, this
    reproduces the guard's decision on a key that is genuinely published
    nowhere, so a refactor that made the search accidentally match
    everything would fail here rather than passing quietly forever.
    """
    literals = _literals_by_module()
    fabricated = "conversation.definitely_not_published_anywhere"

    publishers = [name for name, strings in literals.items() if fabricated in strings]

    assert publishers == []


def test_at_least_one_real_consumer_binding_is_checked() -> None:
    """Coverage of the guard itself.

    If ``_bindings()`` silently returned nothing — an import failure
    swallowed, a package rename, a refactor that moved ``ROUTING_KEYS`` —
    the primary test above would pass by having nothing to check, which
    reads exactly like coverage.
    """
    bindings = _bindings()

    assert len(bindings) >= 10, f"expected every consumer to declare ROUTING_KEYS, got {bindings}"

    checked = [key for keys in bindings.values() for key in keys if not _is_wildcard(key)]
    assert "conversation.reopened" in checked
    assert "message.persisted" in checked
