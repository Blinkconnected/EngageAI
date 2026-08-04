"""Memory is written by the Memory Manager, and by nothing else.

Every guarantee the Memory Platform makes rests on this. "Every fact has
evidence" is only a property of the store if there is one door: with two,
confidence gets set by hand somewhere, evidence gets skipped on the path
somebody was in a hurry on, lifecycle transitions happen outside the state
machine, and the audit trail acquires holes nobody can enumerate.

Fixing the writers once is an afternoon. Keeping them fixed is this file —
the same static approach, for the same reason, as
``test_ownership_is_the_only_writer.py``: a behavioural test can only
cover the paths somebody thought to write, and this covers the paths
nobody has written yet, which is where the next instance of the problem
will be.

The Memory Platform is consumed by the AI Engine, the Workflow Engine,
CRM, Reporting, the Customer Timeline and Analytics. Six future callers is
six chances for one of them to write a row directly because it was easier
that afternoon.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"

#: Repository methods that change memory. Reading is unrestricted; these
#: are the ones that must go through the Manager.
WRITE_METHODS: frozenset[str] = frozenset(
    {
        # MemoryFactRepository
        "add",
        "delete_by_ids",
        # MemoryEvidenceRepository
        "delete_for_customer",
        "delete_for_facts",
        "prune_for_fact",
        # MemoryConfidenceSampleRepository
        "prune_before",
    }
)

#: The repositories whose writes are restricted.
MEMORY_REPOSITORIES: frozenset[str] = frozenset(
    {
        "MemoryFactRepository",
        "MemoryEvidenceRepository",
        "MemoryConfidenceSampleRepository",
    }
)

#: Every module allowed to call a memory write, and why.
#:
#: Adding to this list is the reviewable act. If a change needs another
#: entry, the question to answer first is why the write cannot go through
#: ``MemoryManager`` — because that is where the evidence, the recomputed
#: confidence and the lifecycle transition are written together, in one
#: transaction.
ALLOWED: dict[str, str] = {
    "application/services/memory_manager.py": ("The Manager itself. This is the door."),
    "application/services/memory_erasure_service.py": (
        "Erasure deletes rather than writes, and must complete on demand "
        "even where no Manager is wired. It takes the Manager's recompute "
        "through a narrow port (SupportsFactRecompute) so it can weaken "
        "surviving facts without being able to record, confirm or suppress."
    ),
    "infrastructure/tasks/memory_decay_sweep_task.py": (
        "Purging rows the state machine already marked purged, and pruning "
        "confidence history to its window. Both are deletions of finished "
        "rows; every *recompute* in this sweep goes through the Manager."
    ),
}

#: Modules that legitimately construct a memory repository without writing
#: — the read path and the wiring. Listed so the constructor check below
#: does not have to be loosened into uselessness.
ALLOWED_CONSTRUCTORS: frozenset[str] = frozenset(
    {
        "application/services/memory_manager.py",
        "application/services/memory_erasure_service.py",
        "application/services/memory_query_service.py",
        "infrastructure/tasks/memory_decay_sweep_task.py",
        "api/deps.py",
    }
)


def _python_files() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


def _is_memory_repo_name(name: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(("self._facts", "self._evidence", "self._samples")) or any(
        repo.lower() in lowered for repo in MEMORY_REPOSITORIES
    )


def _writes_memory(node: ast.AST) -> bool:
    """``<something>.<write method>(...)`` where something looks like a
    memory repository.

    Deliberately name-based rather than type-based: this codebase has no
    type information at parse time, and the alternative — flagging every
    call to ``add`` anywhere — would flag every repository in the platform
    and make the allow-list a list of callers rather than of writers,
    which is the distinction the whole file rests on.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in WRITE_METHODS:
        return False
    return _is_memory_repo_name(ast.unparse(func.value))


def _writers() -> dict[str, int]:
    """``relative/path.py`` -> line, for every memory writer in ``src``."""
    found: dict[str, int] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if _writes_memory(node):
                found.setdefault(path.relative_to(SRC).as_posix(), node.lineno)
    return found


def _constructors() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in MEMORY_REPOSITORIES
            ):
                found.setdefault(path.relative_to(SRC).as_posix(), node.lineno)
    return found


class TestNothingWritesMemoryBehindTheManagersBack:
    def test_every_writer_is_on_the_list(self) -> None:
        unexpected = {where: line for where, line in _writers().items() if where not in ALLOWED}

        assert not unexpected, (
            "These write memory without going through MemoryManager, so a fact "
            "can exist without evidence, without a computed confidence, or with a "
            "lifecycle nothing transitioned:\n"
            + "\n".join(f"  {where}  (line {line})" for where, line in sorted(unexpected.items()))
            + "\n\nRoute the change through MemoryManager — which writes the fact, its "
            "evidence, its recomputed confidence and its lifecycle together — or, if "
            "it genuinely cannot go through the Manager, add it to ALLOWED in this "
            "file with the reason."
        )

    def test_the_list_has_not_gone_stale(self) -> None:
        """An allow-list entry for code that no longer writes is not
        harmless: it reads like the guard covers something when it covers
        nothing, and the next reader trusts it."""
        writers = _writers()
        vanished = sorted(where for where in ALLOWED if where not in writers)

        assert (
            not vanished
        ), f"ALLOWED names modules that no longer write memory — delete these: {vanished}"

    def test_only_known_modules_construct_a_memory_repository(self) -> None:
        """The weaker second ring.

        A module that builds a memory repository is a module one line away
        from writing through it, and catching that at construction is how
        the write guard above stays a guard rather than a race against
        somebody's refactor.
        """
        unexpected = {
            where: line
            for where, line in _constructors().items()
            if where not in ALLOWED_CONSTRUCTORS
        }

        assert not unexpected, (
            "These construct a memory repository directly. Reading memory goes "
            "through MemoryQueryService and writing goes through MemoryManager:\n"
            + "\n".join(f"  {where}  (line {line})" for where, line in sorted(unexpected.items()))
        )


class TestTheGuardActuallyFires:
    """A guard nobody has watched fail is a guard nobody knows works."""

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            (
                "a repository held on self",
                "async def sneaky(self, fact):\n    await self._facts.add(fact)\n",
            ),
            (
                "a locally constructed repository",
                "async def sneaky(session, ids):\n"
                "    await MemoryFactRepository(session).delete_by_ids("
                "company_id=1, fact_ids=ids)\n",
            ),
            (
                "evidence deletion",
                "async def sneaky(self, customer_id):\n"
                "    await self._evidence.delete_for_customer("
                "company_id=1, customer_id=customer_id)\n",
            ),
        ],
    )
    def test_a_planted_writer_is_detected(self, label: str, source: str) -> None:
        tree = ast.parse(source)

        assert any(
            _writes_memory(node) for node in ast.walk(tree)
        ), f"the guard would not have noticed a writer using {label}"

    def test_reading_memory_is_not_flagged(self) -> None:
        """Consumers read constantly. Only writing is restricted."""
        source = (
            "async def innocent(self, company_id, fact_id):\n"
            "    fact = await self._facts.get_by_id("
            "company_id=company_id, fact_id=fact_id)\n"
            "    rows = await self._evidence.list_for_fact(fact_id=fact_id)\n"
            "    return fact, rows\n"
        )
        tree = ast.parse(source)

        assert not any(_writes_memory(node) for node in ast.walk(tree))

    def test_other_repositories_add_is_not_flagged(self) -> None:
        """``add`` is the most common method name in this codebase. The
        guard must not flag every repository in the platform, or the
        allow-list becomes a list of callers and stops meaning anything."""
        source = (
            "async def innocent(self, article):\n"
            "    await self._articles.add(article)\n"
            "    await self._chunks.add(article)\n"
        )
        tree = ast.parse(source)

        assert not any(_writes_memory(node) for node in ast.walk(tree))
