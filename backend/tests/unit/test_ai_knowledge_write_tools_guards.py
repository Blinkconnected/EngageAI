"""The mutating knowledge tools, and the shape that keeps a human in the loop.

4G-1 Step 2 gave a model the ability to look. This phase gives it the ability
to *ask for* a change — and the whole security argument is about what it
cannot do unaided: it cannot publish, it cannot name the person who approved,
and it cannot reach a repository to do either behind the executor's back.

These are structural for the reason the read-side guards are. A behavioural
test covers the publication somebody thought to attempt; this covers the one
nobody has written yet, including the tool that has not been added.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from blinkengage.application.ai_tools import DEFAULT_REGISTRY
from blinkengage.application.ai_tools.knowledge_write_tools import (
    ArchiveKnowledgeRecordArgs,
    ProposeKnowledgeUpdateArgs,
    PublishKnowledgeRecordArgs,
    SupersedeKnowledgeRecordArgs,
)
from blinkengage.application.ai_tools.registry import RESERVED_ARGUMENT_NAMES
from blinkengage.application.ai_tools.spec import ConfirmationPolicy

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
WRITE_TOOLS = SRC / "application" / "ai_tools" / "knowledge_write_tools.py"

#: Tools that make something authoritative or withdraw it. Every one parks.
CONFIRMED_TOOLS = (
    "publish_knowledge_record",
    "supersede_knowledge_record",
    "archive_knowledge_record",
)

#: Names that would mean "somebody approved this". A model that could fill
#: one of these in would be approving its own work.
APPROVER_FIELD_FRAGMENTS = ("approved", "approver", "confirmed_by", "authorised", "authorized")


def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _function(name: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(_tree(WRITE_TOOLS)):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in knowledge_write_tools.py")


def _calls_in(node: ast.AST) -> set[str]:
    return {
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    }


def _plain_calls_in(node: ast.AST) -> set[str]:
    """Bare function calls — ``publication_gate(...)`` rather than ``a.b()``."""
    return {
        child.func.id
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }


def _imported_modules(path: pathlib.Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


# --- the draft-only tool ----------------------------------------------


def test_the_proposal_tool_cannot_publish() -> None:
    """``propose_knowledge_update`` runs without a human, so what it creates
    must be unable to answer anyone. A draft is that; anything it could
    promote itself into is not."""
    calls = _calls_in(_function("_propose_knowledge_update"))
    assert "create_draft" in calls, "a proposal must actually create a draft"
    for promotion in ("publish", "supersede", "archive"):
        assert promotion not in calls, f"the proposal tool calls {promotion}"


def test_the_proposal_tool_needs_no_confirmation_because_it_grants_nothing() -> None:
    spec = DEFAULT_REGISTRY.get("propose_knowledge_update")
    assert spec is not None
    assert spec.confirmation is ConfirmationPolicy.NONE
    assert spec.mutating is True
    assert spec.permission == "knowledge_records.propose"


# --- the confirmed tools ----------------------------------------------


@pytest.mark.parametrize("name", CONFIRMED_TOOLS)
def test_authority_changing_tools_park_for_a_human(name: str) -> None:
    spec = DEFAULT_REGISTRY.get(name)
    assert spec is not None, f"{name} is not registered"
    assert spec.confirmation is ConfirmationPolicy.REQUIRED
    assert spec.mutating is True
    assert spec.permission == "knowledge_records.publish"
    # Without a before-state the executor's staleness check compares None to
    # None and always passes, so a human could approve a diff that stopped
    # describing reality while they were reading it.
    assert spec.state_reader is not None


def test_publish_and_supersede_run_the_publication_gate() -> None:
    """The gate had no caller before this phase. These two are it."""
    for handler in ("_publish_knowledge_record", "_supersede_knowledge_record"):
        called = _plain_calls_in(_function(handler))
        assert "_assert_publishable" in called, f"{handler} skips the gate"

    assert "publication_gate" in _plain_calls_in(_function("_assert_publishable"))


def test_archive_does_not_run_the_gate_and_that_is_deliberate() -> None:
    """The gate asks whether something may become authoritative. Withdrawal
    makes nothing authoritative, so running it there would be asserting a
    property that does not apply — and would refuse withdrawals for lack of
    provenance, which is exactly backwards."""
    called = _plain_calls_in(_function("_archive_knowledge_record"))
    assert "_assert_publishable" not in called
    assert "publication_gate" not in called
    # But it still parks for a human, asserted above.


def test_the_approver_is_taken_from_the_authenticated_context() -> None:
    """``approved_by_user_id`` must be ``ctx.actor_user_id`` — an attribute
    read off the request identity, never a value flowing in from arguments."""
    source = ast.get_source_segment(WRITE_TOOLS.read_text(), _function("_assert_publishable"))
    assert source is not None
    assert "approved_by_user_id=ctx.actor_user_id" in source
    assert "granted_permissions=ctx.auth.permissions" in source


@pytest.mark.parametrize(
    "model",
    [
        ProposeKnowledgeUpdateArgs,
        PublishKnowledgeRecordArgs,
        SupersedeKnowledgeRecordArgs,
        ArchiveKnowledgeRecordArgs,
    ],
)
def test_no_mutation_tool_accepts_an_identity_or_an_approver(model: type) -> None:
    declared = set(model.model_fields)
    assert declared & RESERVED_ARGUMENT_NAMES == set()
    for field_name in declared:
        for fragment in APPROVER_FIELD_FRAGMENTS:
            assert (
                fragment not in field_name.lower()
            ), f"{model.__name__}.{field_name} would let a model name the approver"
    assert model.model_config["extra"] == "forbid"


# --- no way round the executor ----------------------------------------


def test_the_handlers_hold_no_repository_or_session() -> None:
    """Every change goes through ``KnowledgeRecordService``, which enforces
    the lifecycle contract, the overlap rule and the audit trail. A handler
    that could reach a repository could skip all three."""
    forbidden = ("repositories", "sqlalchemy", "database.session", "database.models")
    offenders = [
        module
        for module in sorted(_imported_modules(WRITE_TOOLS))
        for needle in forbidden
        if needle in module
    ]
    assert offenders == [], f"knowledge_write_tools.py imports {offenders}"


def test_no_handler_commits_or_flushes_on_its_own() -> None:
    source = WRITE_TOOLS.read_text()
    for escape in (".commit(", ".flush(", ".add(", ".execute("):
        assert escape not in source, f"knowledge_write_tools.py contains {escape!r}"


def test_no_agent_runtime_or_model_call_lives_beside_the_mutations() -> None:
    """A tool that could call a model could ask one whether to publish.

    Checked on imports, call sites and loops rather than on source text: the
    module's own docstring names ``ToolExecutor.confirm`` while explaining
    that parking is the executor's job, and a guard that has to be worded
    around is a guard that eventually gets deleted.
    """
    tree = _tree(WRITE_TOOLS)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            imported_names.update(alias.name for alias in node.names)
    for forbidden in ("ToolExecutor", "AiProvider", "AiCompletion"):
        assert forbidden not in imported_names, f"knowledge_write_tools.py imports {forbidden}"

    called = {
        child.func.attr
        for child in ast.walk(tree)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    }
    for forbidden in ("complete_with_tools", "complete", "confirm", "execute"):
        assert forbidden not in called, f"knowledge_write_tools.py calls {forbidden}()"

    # No dispatch loop: this module declares tools, it does not run them.
    unbounded = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.While)
        and isinstance(node.test, ast.Constant)
        and node.test.value is True
    ]
    assert unbounded == [], "knowledge_write_tools.py contains an unbounded loop"


def test_the_customer_and_ingestion_paths_cannot_reach_the_mutation_tools() -> None:
    """Autopilot answers a customer; 4E reads a stranger's document. Neither
    has an authenticated administrator behind it, so neither may hold a tool
    that publishes."""
    offenders: list[str] = []
    targets = [
        *(SRC / "application" / "brain").rglob("*.py"),
        *(SRC / "domain" / "brain").rglob("*.py"),
        SRC / "application" / "services" / "autopilot_service.py",
    ]
    for path in sorted(targets):
        for module in _imported_modules(path):
            if "ai_tools" in module:
                offenders.append(f"{path.name}: imports {module}")

    assert offenders == [], "\n".join(offenders)


def test_the_registry_is_still_the_only_way_a_tool_is_reachable() -> None:
    """No handler is exported for direct call: everything goes through
    ``register_knowledge_write_tools`` and therefore through the executor."""
    import blinkengage.application.ai_tools.knowledge_write_tools as module

    exported = set(module.__all__)
    assert "register_knowledge_write_tools" in exported
    assert not any(name.startswith("_") for name in exported)
    for handler in (
        "_propose_knowledge_update",
        "_publish_knowledge_record",
        "_supersede_knowledge_record",
        "_archive_knowledge_record",
    ):
        assert handler not in exported
