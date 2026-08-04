"""``assigned_agent_id`` may only be written as a consequence of ownership.

Conversation ownership had two systems of record. ``conversation_ownership``
is an append-only timeline of who is answerable; ``Conversation
.assigned_agent_id`` is a mutable column saying who is assigned. Both were
live, and they were written by overlapping but *not identical* sets of
callers — so they could disagree, and they did.

The defect that proved it: the ``assign_conversation`` workflow action set the
column and wrote no transition. A workflow that assigned a conversation left
the Inbox — the screen built to make responsibility obvious — showing the
queue as owner while the conversation was assigned to an agent. Nothing
reported the disagreement, because nothing was comparing them.

Fixing the two callers was an afternoon. Keeping them fixed is this file.
**Ownership is the source; the column is a projection of it** (see
``domain/ownership.assigned_agent`` and
``docs/architecture/ownership-consistency.md``), and the only way that stays
true is if adding a new writer of the column is something a person has to do
on purpose, in front of a reviewer, by editing the list below.

Static analysis rather than behaviour, deliberately. A behavioural test can
only cover the paths somebody thought to write; this covers the paths nobody
has written yet, which is where the next instance of this bug will be.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"

#: Every place allowed to write the column, and why it is allowed. Two
#: entries, and both are ownership machinery rather than business logic.
#:
#: Adding to this list is the reviewable act. If a change needs a third
#: entry, the question to answer first is why the transition cannot go
#: through ``OwnershipService.transfer`` like every other one — because that
#: is where the timeline, the projection and the reason are written together.
ALLOWED: dict[str, str] = {
    "infrastructure/repositories/ownership_repository.py::project_assignment": (
        "The projection itself: this *is* how ownership reaches the column, "
        "called only by OwnershipService.transfer."
    ),
    "infrastructure/repositories/conversation_repository.py::claim": (
        "The compare-and-set that decides which of two agents pressing Pick "
        "at the same moment wins. Its WHERE clause is the race, so it cannot "
        "be expressed as a transition — and ConversationService.pick() "
        "records the ownership transition immediately after a claim "
        "succeeds, which the companion test below verifies."
    ),
}


def _python_files() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


def _writes_assigned_agent(node: ast.AST) -> bool:
    """Both ways this codebase can write the column.

    Attribute assignment on an ORM instance, and passing it as a keyword to
    a Core ``update().values()``. A future third form — a raw ``text()``
    UPDATE, say — would slip past this, which is why the list above is
    phrased as an allow-list of *functions* and not of statements.
    """
    if isinstance(node, ast.Assign):
        return any(
            isinstance(target, ast.Attribute) and target.attr == "assigned_agent_id"
            for target in node.targets
        )
    if isinstance(node, ast.Call):
        func = node.func
        # ``.values(...)`` only — a SQLAlchemy Core update. Deliberately not
        # ``.update(...)``: that is ``ConversationService.update``, whose
        # ``assigned_agent_id`` argument is the *right* way to assign
        # somebody. Matching it would flag every legitimate caller and make
        # the allow-list a list of callers rather than of writers, which is
        # the distinction this whole file rests on.
        if isinstance(func, ast.Attribute) and func.attr == "values":
            return any(keyword.arg == "assigned_agent_id" for keyword in node.keywords)
    return False


def _writers() -> dict[str, int]:
    """``relative/path.py::function`` -> line, for every writer in ``src``."""
    found: dict[str, int] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if _writes_assigned_agent(node):
                    key = f"{path.relative_to(SRC).as_posix()}::{function.name}"
                    found.setdefault(key, node.lineno)
    return found


class TestNothingWritesAssignmentBehindOwnershipsBack:
    def test_every_writer_is_on_the_list(self) -> None:
        """The guard. A new code path that assigns without a transition
        fails here, naming itself."""
        unexpected = {where: line for where, line in _writers().items() if where not in ALLOWED}

        assert not unexpected, (
            "These write Conversation.assigned_agent_id without going through an "
            "ownership transition, so the timeline and the column can disagree:\n"
            + "\n".join(f"  {where}  (line {line})" for where, line in sorted(unexpected.items()))
            + "\n\nRoute the change through OwnershipService.transfer — which writes the "
            "timeline, the reason and the projection together — or, if it genuinely "
            "cannot be expressed as a transition, add it to ALLOWED in this file with "
            "the reason it cannot."
        )

    def test_the_list_has_not_gone_stale(self) -> None:
        """The other half, and the one that rots quietly.

        An allow-list entry for code that no longer exists is not harmless:
        it reads like the guard is covering something when it is covering
        nothing, and the next reader trusts it.
        """
        writers = _writers()
        vanished = sorted(where for where in ALLOWED if where not in writers)

        assert not vanished, (
            "ALLOWED names code that no longer writes the column — delete these "
            f"entries: {vanished}"
        )


class TestTheAllowedWritersAreStillHonest:
    """The two exemptions above are only safe while their claims hold."""

    def test_the_projection_is_only_called_by_the_ownership_service(self) -> None:
        """``project_assignment`` is the column's back door. It is safe
        because exactly one caller has the key."""
        callers = set()
        for path in _python_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "project_assignment"
                ):
                    callers.add(path.relative_to(SRC).as_posix())

        assert callers == {"application/services/ownership_service.py"}, (
            "Only OwnershipService may project ownership onto the column; "
            f"found callers in {sorted(callers)}"
        )

    def test_pick_records_ownership_after_claiming(self) -> None:
        """``claim`` is exempt because ``pick`` completes it. If that stops
        being true the exemption is a hole, and this is what notices."""
        service = SRC / "application" / "services" / "conversation_service.py"
        tree = ast.parse(service.read_text(), filename=str(service))
        pick = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "pick"
        )
        calls = {
            node.func.attr
            for node in ast.walk(pick)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        assert "claim" in calls, "pick() no longer claims — re-check the ALLOWED entry"
        assert "_record_ownership" in calls, (
            "pick() claims the conversation but no longer records the ownership "
            "transition, so a claimed conversation has no owner in the timeline"
        )


class TestTheGuardActuallyFires:
    """A guard nobody has watched fail is a guard nobody knows works.

    The two forms are checked separately because they are detected by
    different branches, and a regression in either would otherwise be
    invisible while the other kept the test green.
    """

    @pytest.mark.parametrize(
        ("label", "source"),
        [
            (
                "attribute assignment",
                "async def sneaky(conversation, agent_id):\n"
                "    conversation.assigned_agent_id = agent_id\n",
            ),
            (
                "update().values()",
                "async def sneaky(session, agent_id):\n"
                "    await session.execute(\n"
                "        update(Conversation).values(assigned_agent_id=agent_id)\n"
                "    )\n",
            ),
        ],
    )
    def test_a_planted_writer_is_detected(self, label: str, source: str) -> None:
        tree = ast.parse(source)
        function = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        )

        assert any(
            _writes_assigned_agent(node) for node in ast.walk(function)
        ), f"the guard would not have noticed a writer using {label}"

    def test_ordinary_code_is_not_flagged(self) -> None:
        """Reading the column, filtering on it and naming it in a signature
        are all fine — only writing it is the problem."""
        source = (
            "def innocent(conversation, query):\n"
            "    who = conversation.assigned_agent_id\n"
            "    return query.where(Conversation.assigned_agent_id.is_(None)), who\n"
        )
        tree = ast.parse(source)

        assert not any(_writes_assigned_agent(node) for node in ast.walk(tree))
