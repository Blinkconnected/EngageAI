"""No subsystem reads raw configuration behind the resolver's back.

The platform resolves configuration down four tiers — Service, Queue, Company,
Platform — and the whole value of that chain is that there is **one** of it.
Before this guard there were nine fallbacks and they disagreed: SLA targets
resolved through one resolver, the AI confidence threshold through another, the
AI pickup delay through a hard-coded ``0`` in the ingest consumer, and whether
AI could engage at all through a Policy Engine call on one path and five inline
conditions on the other.

Each of those was reasonable where it was written. Together they meant a
company's configuration had no single answer, and which one a reader got
depended on which module they opened first.

This is the test that stops a tenth appearing. It is deliberately structural
rather than behavioural: a behavioural test can only cover the fallbacks
somebody thought to write, and the next one will be written by somebody who did
not know this chain existed.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"

#: Attribute reads that mean "I am consulting a configuration tier directly".
#: Reading these outside a resolver is how a second chain starts.
_TIER_ATTRIBUTES: dict[str, str] = {
    "pickup_delay_seconds": "AI pickup delay",
    "resume_delay_seconds": "AI resume delay",
    "confidence_threshold": "AI confidence threshold",
    "sla_policy_id": "the queue's SLA policy",
    "first_response_target_minutes": "the queue's legacy SLA target",
    "resolution_target_minutes": "the queue's legacy SLA target",
}

#: Where reading a tier directly is the *job*, not a shortcut.
#:
#: Three kinds of entry, and each is allowed for a different reason:
#:
#: - the resolvers themselves, which exist to read tiers;
#: - the domain rules they delegate to, which take tiers as values;
#: - the modules that *write* configuration, where reading the current value
#:   is part of editing it.
ALLOWED: dict[str, str] = {
    # --- the rules themselves, which take tiers as values ---------------
    "domain/ai_policy.py": "the AI resolution rule",
    "domain/policies.py": (
        "the Policy Engine reports the service's delay and threshold in its "
        "decision detail. It reads what it was handed to explain a decision, "
        "and never to resolve one — the values it prints came from the chain."
    ),
    # --- the one reader of the tiers ------------------------------------
    "application/services/configuration_resolver.py": "reads every tier; this is its job",
    # --- modules that *write* a tier, where reading is part of editing ---
    "application/services/auth_service.py": (
        "seeds the service tier when a company registers. It reads "
        "``AiPolicy()``'s own defaults to write them onto the new service — "
        "establishing a tier, never consulting one, and there is nothing to "
        "resolve because the company does not exist yet. Sourced from the "
        "dataclass rather than restated, so the 30-second pickup delay has "
        "one definition."
    ),
    "application/services/queue_service.py": "writes the queue tier",
    "application/services/sla_policy_service.py": "writes the queue tier's SLA policy",
    "api/v1/endpoints/sla.py": "edits the queue tier's SLA policy",
    "application/services/sla_monitor_service.py": (
        "the escalation sweep reads the policy rows it is sweeping, which is the "
        "tier's own storage rather than a second resolution"
    ),
    # --- consumers of an already-resolved value --------------------------
    "application/services/autopilot_service.py": (
        "takes the resolved threshold as an argument and reads it off that; the "
        "name happens to match a tier attribute, the source does not"
    ),
    "application/services/conversation_inspector.py": (
        "reports which tier answered. Reads for display, never to decide — the "
        "Inspector explains configuration and must never become a place that "
        "resolves it."
    ),
}


def _python_files() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


#: Names that mean "this is a configuration tier". Reading a configured value
#: *off one of these* is consulting a tier; reading the same attribute off a
#: ``ConversationConfiguration`` is consuming what the resolver already
#: decided, which is the whole point of having one.
_TIER_ROOTS: frozenset[str] = frozenset(
    {"service", "queue", "policy", "sla_policy", "company", "settings"}
)


def _root_name(node: ast.Attribute) -> str | None:
    """The name at the base of ``a.b.c`` — ``a``, or ``None`` if it is not a
    plain name (a call result, a subscript, ``self``-qualified, and so on)."""
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _tier_reads(tree: ast.AST) -> set[str]:
    """Configuration attributes read *off a tier* anywhere in this module.

    Deliberately keyed on the root of the attribute chain rather than on the
    attribute alone. ``service.ai.pickup_delay_seconds`` consults the service
    tier; ``configuration.ai.pickup_delay_seconds.value`` consumes the
    resolver's answer. An attribute-only check cannot tell those apart and
    would flag every legitimate consumer, which is how a guard stops being
    trusted and starts being suppressed.

    Construction is not a read: ``SlaTargets(first_response_minutes=…)``
    builds a tier's value rather than consulting one, so keywords are not
    inspected.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _TIER_ATTRIBUTES
            and _root_name(node) in _TIER_ROOTS
        ):
            found.add(node.attr)
    return found


class TestOnlyResolversReadTiers:
    def test_no_new_module_reads_configuration_directly(self) -> None:
        offenders: dict[str, set[str]] = {}
        for path in _python_files():
            relative = path.relative_to(SRC).as_posix()
            if relative in ALLOWED:
                continue
            reads = _tier_reads(ast.parse(path.read_text(), filename=str(path)))
            if reads:
                offenders[relative] = reads

        assert not offenders, (
            "These read a configuration tier without going through a resolver, so the "
            "platform would have more than one answer to what a company configured:\n"
            + "\n".join(
                f"  {where}: {', '.join(sorted(_TIER_ATTRIBUTES[a] for a in attrs))}"
                for where, attrs in sorted(offenders.items())
            )
            + "\n\nAsk ConfigurationResolver instead. If this module genuinely owns a "
            "tier — it writes one, or it *is* the rule — add it to ALLOWED with the "
            "reason."
        )

    def test_the_list_has_not_gone_stale(self) -> None:
        """An exemption for a module that no longer reads a tier is not
        harmless: it reads like coverage and is not."""
        vanished = []
        for relative, _ in ALLOWED.items():
            path = SRC / relative
            if not path.exists():
                vanished.append(f"{relative} (file is gone)")
                continue
            if not _tier_reads(ast.parse(path.read_text(), filename=str(path))):
                vanished.append(f"{relative} (no longer reads a tier)")

        assert not vanished, f"ALLOWED has drifted — remove these entries: {vanished}"


class TestTheChainIsWhatItClaims:
    def test_every_tier_is_reachable(self) -> None:
        """A tier nothing can produce is a tier that does not exist."""
        from blinkengage.domain.resolution import TIER_ORDER, ConfigurationSource

        assert TIER_ORDER == (
            ConfigurationSource.SERVICE,
            ConfigurationSource.QUEUE,
            ConfigurationSource.COMPANY,
            ConfigurationSource.PLATFORM_DEFAULT,
        ), "the documented order is Service, Queue, Company, Platform"
        assert set(TIER_ORDER) == set(
            ConfigurationSource
        ), "a source that is not in the order is one no resolver can consult"

    def test_sla_and_ai_report_tiers_from_the_same_vocabulary(self) -> None:
        """Two enums for one idea is how the answers start disagreeing."""
        from blinkengage.domain.resolution import ConfigurationSource
        from blinkengage.domain.sla import SlaTargetSource

        assert SlaTargetSource is ConfigurationSource


class TestTheGuardActuallyFires:
    @pytest.mark.parametrize(
        ("label", "source"),
        [
            (
                "a service tier read",
                "def sneaky(service):\n    return service.ai.pickup_delay_seconds\n",
            ),
            ("a queue tier read", "def sneaky(queue):\n    return queue.sla_policy_id\n"),
        ],
    )
    def test_a_planted_tier_read_is_detected(self, label: str, source: str) -> None:
        assert _tier_reads(ast.parse(source)), f"the guard would not have noticed {label}"

    def test_consuming_the_resolvers_answer_is_not_flagged(self) -> None:
        """The distinction the guard exists to make.

        Identical attribute, opposite meaning: one consults a tier, the other
        uses what the resolver decided. A guard that could not tell them apart
        would flag every legitimate consumer and be suppressed within a week.
        """
        source = (
            "def innocent(configuration):\n"
            "    return configuration.ai.pickup_delay_seconds.value\n"
        )
        assert not _tier_reads(ast.parse(source))

    def test_building_a_tiers_value_is_not_flagged(self) -> None:
        source = "def innocent():\n    return SlaTargets(first_response_minutes=5)\n"
        assert not _tier_reads(ast.parse(source))
