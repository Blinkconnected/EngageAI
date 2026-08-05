"""Customer Activity has one writer, and this fails when it grows a second.

See ``docs/architecture/customer-activity.md`` §5.

Shaped exactly like ``test_ownership_is_the_only_writer.py``, because it
guards the same kind of thing: a set of columns that are a *projection* of
another table, correct only for as long as one piece of code maintains them.

The failure it prevents is quiet. A new message path that writes
``awaiting_reply_since`` itself does not crash, does not fail a test, and does
not look wrong in review — it simply produces a conversation whose stored wait
disagrees with its own messages, and the first anybody hears of it is a
customer who waited an hour while the Inbox showed four minutes.

The drift checker catches that *after* it happens. This catches it in review.
"""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"

#: The projection. Writing any of these outside the projector is the defect.
PROJECTED: frozenset[str] = frozenset(
    {
        "awaiting_reply_since",
        "last_customer_message_at",
        "last_customer_message_id",
        "last_agent_message_id",
        "last_ai_message_id",
        "unanswered_message_count",
        "last_wait_duration_seconds",
    }
)

#: The one writer, and why. Kept as a mapping rather than a set so an
#: exemption cannot be added without stating what it is for.
ALLOWED: dict[str, str] = {
    "application/services/customer_activity_projector.py": (
        "the projector — this is its whole job, and the reason the list "
        "above has exactly one entry"
    ),
}


def _writes(tree: ast.AST) -> set[str]:
    """Projected attributes assigned anywhere in this module.

    Assignment only. Reading ``conversation.awaiting_reply_since`` is what
    every consumer is *supposed* to do, and a guard that flagged reads would
    be a guard against using the feature.
    """
    written: set[str] = set()
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr in PROJECTED:
                written.add(target.attr)
    return written


def _modules() -> list[tuple[str, ast.AST]]:
    parsed = []
    for path in sorted(SRC.rglob("*.py")):
        relative = str(path.relative_to(SRC))
        parsed.append((relative, ast.parse(path.read_text(), filename=str(path))))
    return parsed


class TestOnlyTheProjectorWrites:
    def test_no_other_module_writes_the_projection(self) -> None:
        offenders = {
            relative: sorted(written)
            for relative, tree in _modules()
            if relative not in ALLOWED and (written := _writes(tree))
        }

        assert not offenders, (
            "These write Customer Activity without going through "
            "CustomerActivityProjector, so the stored facts can disagree with "
            f"the messages they are derived from:\n    {offenders}\n\n"
            "Call the projector instead. If this module genuinely is a second "
            "writer — it is not — add it to ALLOWED with the reason."
        )

    def test_the_exemption_has_not_gone_stale(self) -> None:
        """An allow-list entry for a module that no longer writes is not
        harmless: it reads like coverage and is not."""
        for relative in ALLOWED:
            path = SRC / relative
            assert path.exists(), f"{relative} is gone — remove its exemption"
            tree = ast.parse(path.read_text(), filename=str(path))
            assert _writes(tree), f"{relative} no longer writes — remove its exemption"

    def test_the_guard_notices_a_planted_write(self) -> None:
        """Proof the check works, rather than confidence that it does.

        A guard nobody has watched fail is a guard nobody knows the shape of.
        """
        planted = ast.parse("conversation.awaiting_reply_since = None")

        assert _writes(planted) == {"awaiting_reply_since"}

    def test_it_ignores_reads(self) -> None:
        """Consumers read these constantly — that is the entire point of the
        feature — and a guard that flagged reads would be a guard against
        using it."""
        reading = ast.parse("if conversation.awaiting_reply_since is not None: pass")

        assert _writes(reading) == set()
