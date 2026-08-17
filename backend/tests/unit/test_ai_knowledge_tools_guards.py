"""The read-only knowledge tools, and the shape that keeps them read-only.

Phase 4G-1 Step 2 gives a model the ability to *look* at company knowledge.
The security property is not that the handlers decline to write — it is that
they hold nothing that could. These tests assert that structurally, for the
same reason the memory single-writer guard is structural: a behavioural test
covers the write somebody thought to attempt, and this covers the one nobody
has written yet.

Three guards are about a boundary rather than a file. The admin tools exist
for an authenticated administrator; the customer-facing path (Autopilot) and
the ingestion path (4E) answer to *senders*, not to administrators, and an
import from either into this registry would put a tool behind a principal
that was never authenticated. Those are the two directions this could
plausibly be built wrong.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.application.ai_tools.knowledge_tools import (
    GetKnowledgeRecordArgs,
    SearchKnowledgeArgs,
    _admin_can_see,
    _visibility_view,
)
from blinkengage.application.ai_tools.registry import RESERVED_ARGUMENT_NAMES
from blinkengage.domain.brain.retrieval_policy import CrossTenantAccessError
from blinkengage.domain.brain.subject_matching import match_subjects, rank_subjects
from blinkengage.domain.knowledge_records import (
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
TOOLS = SRC / "application" / "ai_tools" / "knowledge_tools.py"

#: Everything on ``KnowledgeRecordService`` that changes a record. Named
#: rather than inferred: the guard has to fail when somebody adds a call to
#: one of these, and a heuristic that looked for "write-ish" names would
#: quietly stop covering the next one.
WRITE_METHODS = frozenset({"create_draft", "publish", "supersede", "archive"})


def _called_attributes(path: pathlib.Path) -> set[str]:
    """Every attribute *invoked* in a module — ``a.b.c()`` yields ``c``.

    Attributes rather than source text, deliberately. A substring search
    trips on this module's own prose about the methods it must not call, and
    a guard that has to be worded around is a guard that gets deleted.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


# --- 1 & 2: neither handler can write ---------------------------------


def test_the_knowledge_tools_never_call_a_write_method() -> None:
    """Covers both handlers at once — they live in one module so that this
    guard can be a property of a file rather than of two functions somebody
    might later move apart."""
    offenders = sorted(_called_attributes(TOOLS) & WRITE_METHODS)
    assert offenders == [], f"knowledge_tools.py calls {offenders}"


def test_the_knowledge_tools_hold_no_repository_or_session() -> None:
    """A handler receives services. Reaching a repository or a session
    directly would bypass every rule the service enforces — and would be the
    only way either of these could mutate anything."""
    forbidden = ("repositories", "sqlalchemy", "database.session")
    imported = _imported_modules(TOOLS)
    offenders = [
        module
        for module in sorted(imported)
        for needle in forbidden
        if needle in module
        # The ORM row is imported for the visibility adapter's type. It is a
        # mapped class, not a way to reach the database: without a session
        # nothing on it can be flushed.
        and "models.knowledge_record" not in module
    ]
    assert offenders == [], f"knowledge_tools.py imports {offenders}"


def test_both_tools_are_declared_non_mutating_and_need_no_confirmation() -> None:
    from blinkengage.application.ai_tools import DEFAULT_REGISTRY
    from blinkengage.application.ai_tools.spec import ConfirmationPolicy

    for name in ("search_knowledge", "get_knowledge_record"):
        spec = DEFAULT_REGISTRY.get(name)
        assert spec is not None, f"{name} is not registered"
        assert spec.mutating is False
        assert spec.confirmation is ConfirmationPolicy.NONE
        assert spec.permission == "knowledge_records.read"
        # No state reader: that machinery exists to price up a change, and
        # a read has no before and after.
        assert spec.state_reader is None


def test_the_knowledge_tool_set_is_exactly_what_was_authorised() -> None:
    """4G-2 moved this boundary deliberately, so the assertion moved with it.

    Step 2 shipped retrieval only and this test pinned the set to two. Phase
    4G-2 authorises four mutating tools, so the pin is now the larger set —
    still an exact equality, because the value of this test is that a tool
    nobody authorised cannot appear quietly. What has *not* changed is the
    rule underneath: publishing is a confirmed human act, asserted in
    ``test_every_mutating_knowledge_tool_is_a_draft_or_needs_confirmation``.
    """
    from blinkengage.application.ai_tools import DEFAULT_REGISTRY

    names = DEFAULT_REGISTRY.names()
    # Still absent: nothing grants restricted access, and nothing publishes
    # without going through the confirmation path.
    for forbidden in ("approve_restricted", "grant_permission", "publish_all"):
        assert forbidden not in names

    assert sorted(name for name in names if "knowledge" in name) == [
        "archive_knowledge_record",
        "get_knowledge_record",
        "propose_knowledge_update",
        "publish_knowledge_record",
        "search_knowledge",
        "supersede_knowledge_record",
    ]


def test_every_mutating_knowledge_tool_is_a_draft_or_needs_confirmation() -> None:
    """The rule Step 2's narrower assertion was really protecting.

    A knowledge tool may change something without a human only if what it
    creates is a DRAFT — unapproved, answering nobody. Anything that makes a
    record authoritative, replaces one, or withdraws one parks as a
    ``PendingAiAction`` and waits.
    """
    from blinkengage.application.ai_tools import DEFAULT_REGISTRY
    from blinkengage.application.ai_tools.spec import ConfirmationPolicy

    for spec in DEFAULT_REGISTRY.all():
        if "knowledge" not in spec.name or not spec.mutating:
            continue
        if spec.name == "propose_knowledge_update":
            assert spec.confirmation is ConfirmationPolicy.NONE
            continue
        assert (
            spec.confirmation is ConfirmationPolicy.REQUIRED
        ), f"{spec.name} changes authoritative knowledge without a human"
        assert (
            spec.state_reader is not None
        ), f"{spec.name} has no before-state, so a stale approval cannot be detected"


# --- 3 & 4: the boundary between principals ---------------------------


@pytest.mark.parametrize(
    "package",
    [
        pytest.param(SRC / "application" / "brain", id="brain"),
        pytest.param(SRC / "domain" / "brain", id="domain-brain"),
    ],
)
def test_the_customer_and_ingestion_paths_cannot_reach_the_tool_registry(
    package: pathlib.Path,
) -> None:
    """Autopilot answers a customer and 4E reads a stranger's document.

    Neither has an authenticated administrator behind it, so neither may
    hold a tool whose authorization comes from one. ``application/brain``
    contains 4E's extraction and the bridge; ``domain/brain`` contains the
    rules. An import of ``ai_tools`` from either is the failure.
    """
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        for module in _imported_modules(path):
            if "ai_tools" in module:
                offenders.append(f"{path.name}: imports {module}")

    assert offenders == [], "\n".join(offenders)


def test_autopilot_does_not_import_the_tool_registry() -> None:
    autopilot = SRC / "application" / "services" / "autopilot_service.py"
    assert autopilot.is_file()
    offenders = [module for module in _imported_modules(autopilot) if "ai_tools" in module]
    assert offenders == [], f"autopilot_service imports {offenders}"


# --- 5, 6, 7: nothing was duplicated ----------------------------------


def test_there_is_exactly_one_tool_registry() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("ToolRegistry"):
                offenders.append(f"{path.relative_to(SRC)}: {node.name}")

    assert offenders == ["application/ai_tools/registry.py: ToolRegistry"]


def test_search_reuses_the_existing_subject_matcher() -> None:
    """No second retrieval implementation.

    ``rank_subjects`` lives in ``domain/brain/subject_matching`` beside
    ``match_subjects`` and is built from the same tokens, so "what is a
    subject" is decided in one place. The tool imports it; it does not
    reimplement it.
    """
    imported = _imported_modules(TOOLS)
    assert "blinkengage.domain.brain.subject_matching" in imported

    source = TOOLS.read_text()
    for reimplementation in ("def rank_", "def matches", "def query_tokens", "cosine", "embed"):
        assert reimplementation not in source, f"knowledge_tools.py defines {reimplementation!r}"


def test_no_second_vector_store_or_embedding_path_was_introduced() -> None:
    imported = _imported_modules(TOOLS)
    offenders = [
        module
        for module in sorted(imported)
        if "vector" in module or "embedding" in module or "faiss" in module or "pgvector" in module
    ]
    assert offenders == [], f"knowledge_tools.py imports {offenders}"


def test_no_second_agent_runtime_was_introduced() -> None:
    """Step 2 adds tools, not a loop that calls them. The executor stays the
    only thing that runs a tool."""
    source = TOOLS.read_text()
    for needle in ("complete_with_tools", "ToolExecutor", "AiProvider", "while True"):
        assert needle not in source, f"knowledge_tools.py contains {needle!r}"


# --- identity is not an argument --------------------------------------


@pytest.mark.parametrize("model", [SearchKnowledgeArgs, GetKnowledgeRecordArgs])
def test_no_tool_argument_names_an_identity(model: type) -> None:
    """The registry refuses these at registration. Asserted here too so the
    reason is visible at the tool rather than only in the registry: a model
    that can name a company is a model that can be asked to name a different
    one."""
    declared = set(model.model_fields)
    assert declared & RESERVED_ARGUMENT_NAMES == set()
    assert model.model_config["extra"] == "forbid"


# --- the visibility predicate -----------------------------------------


class _Row:
    """Enough of a record for the visibility adapter."""

    def __init__(
        self,
        *,
        company_id: uuid.UUID,
        lifecycle_state: str = "ACTIVE",
        access_level: str = "PUBLIC_TO_AI",
        effective_from: datetime | None = None,
        effective_until: datetime | None = None,
    ) -> None:
        self.company_id = company_id
        self.lifecycle_state = lifecycle_state
        self.access_level = access_level
        self.effective_from = effective_from or datetime.now(UTC) - timedelta(days=1)
        self.effective_until = effective_until


def test_a_foreign_record_raises_rather_than_being_filtered_out() -> None:
    """The one case that must not be a quiet ``False``.

    A row from another company arriving here is a bug in whatever fetched
    it. ``CrossTenantAccessError`` is not a ``DomainError``, so the executor
    re-raises it instead of handing the model a sentence to explain — a
    tenant leak reported as assistant prose is a leak nobody investigates.
    """
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(CrossTenantAccessError):
        _admin_can_see(_Row(company_id=theirs), company_id=mine, at=datetime.now(UTC))  # type: ignore[arg-type]


def test_the_admin_audience_sees_drafts_and_restricted_but_not_archived() -> None:
    company = uuid.uuid4()
    now = datetime.now(UTC)

    def visible(**kwargs: object) -> bool:
        return _admin_can_see(_Row(company_id=company, **kwargs), company_id=company, at=now)  # type: ignore[arg-type]

    assert visible(lifecycle_state="DRAFT") is True
    assert visible(access_level="RESTRICTED") is True
    assert visible(access_level="INTERNAL") is True
    # Withdrawn. Its period is deliberately left intact for the audit trail,
    # so admitting it would let it overlap a later active record.
    assert visible(lifecycle_state="ARCHIVED") is False
    # SUPERSEDED is resolvable, but only inside its own period.
    assert visible(lifecycle_state="SUPERSEDED") is True
    assert visible(lifecycle_state="SUPERSEDED", effective_until=now - timedelta(hours=1)) is False


def test_the_visibility_view_lifts_enums_off_the_row() -> None:
    company = uuid.uuid4()
    view = _visibility_view(_Row(company_id=company, lifecycle_state="DRAFT"))  # type: ignore[arg-type]
    assert view.lifecycle_state is KnowledgeLifecycleState.DRAFT
    assert view.access_level is KnowledgeAccessLevel.PUBLIC_TO_AI
    assert view.company_id == company


# --- ranking ----------------------------------------------------------


def test_ranking_puts_a_named_subject_above_a_partial_overlap() -> None:
    keys = ("dia-200-mbps", "dia-500-mbps")
    ranked = rank_subjects("how much is DIA 500 Mbps", keys)
    assert ranked[0] == "dia-500-mbps"
    assert set(ranked) == set(keys), "the 200 row still surfaces as a partial hit"


def test_ranking_finds_a_subject_a_customer_query_would_not() -> None:
    """The difference between browsing and quoting.

    ``match_subjects`` declines "dia" because the key was never spelled out —
    correct when a price is about to be quoted, useless when an
    administrator is looking for the record to talk about.
    """
    keys = ("dia-500-mbps",)
    assert match_subjects("dia", keys) == ()
    assert rank_subjects("dia", keys) == ("dia-500-mbps",)


def test_ranking_returns_nothing_for_an_unmatchable_query() -> None:
    assert rank_subjects("???", ("dia-500-mbps",)) == ()
    assert rank_subjects("firewall", ("dia-500-mbps",)) == ()


def test_ranking_is_deterministic() -> None:
    """A ranking that differs between runs quotes a different record on
    Tuesday — the same argument the canonicaliser is built on."""
    keys = ["dia-500-mbps", "dia-200-mbps", "sla-uptime"]
    first = rank_subjects("dia uptime", keys)
    assert first == rank_subjects("dia uptime", list(reversed(keys)))
