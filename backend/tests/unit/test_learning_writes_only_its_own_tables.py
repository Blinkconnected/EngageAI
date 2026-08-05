"""Learning observes. It does not write anything it does not own.

This is invariant I-2 of the Learning Platform Charter, and it is the one
that makes the whole bounded context safe to run. Learning reads
conversations, messages, CSAT responses and customers; it must be able to
run at full speed against production data without any of those being able
to change underneath it. A single ``session.add(SomeOtherModel(...))``
inside a Learning consumer would turn an observer into a writer, and the
failure would not look like a bug — it would look like the platform
quietly editing operational data during a replay.

Replay is exactly why a behavioural test is not enough here. Phase 1 is
built to be re-runnable: bump ``PIPELINE_VERSION``, re-consume the
history, get a second observation per conversation. That is only safe
while Learning's writes are confined to four tables nobody else reads for
operational decisions. Re-running a pipeline that also touched
``conversations`` would replay side effects onto live rows.

The same static approach, for the same reason, as
``test_memory_manager_is_the_only_writer.py``: a behavioural test covers
the paths somebody thought to write, and this covers the paths nobody has
written yet — which is where the next instance of the problem will be.

Also guarded here:

* **I-4, the acyclic evidence graph.** Learning must not consume what it
  produces, directly or through Memory. A consumer bound to ``memory.*``
  would close the loop: memory writes an event, Learning observes it,
  Learning's output eventually strengthens that same memory, and
  confidence rises with no new human evidence anywhere in the cycle.
* **Phase 1's boundary.** Learning writes nothing to Memory at all yet.
  Phase 2 will propose candidates through the Memory Manager; until then
  the absence is enforced rather than assumed.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
MODELS = SRC / "infrastructure" / "database" / "models"

#: The tables Learning owns. Everything else in the database is somebody
#: else's, and Learning may only read it. Phase 2 added four.
LEARNING_MODELS: frozenset[str] = frozenset(
    {
        "LearningObservation",
        "LearningObservationFeature",
        "LearningObservationRef",
        "LearningRun",
        "LearningCluster",
        "LearningClusterMember",
        "LearningTrend",
        "LearningAnomaly",
    }
)

#: Modules that make up the Learning bounded context, matched by path.
#: Deliberately a prefix match rather than a hand-maintained list: a new
#: Learning module is picked up by this guard the moment it is added,
#: which is the point.
LEARNING_PATHS: tuple[str, ...] = (
    "domain/learning_",
    "application/services/learning_",
    "infrastructure/repositories/learning_repository.py",
    "infrastructure/repositories/learning_analysis_repository.py",
    "infrastructure/database/models/learning.py",
    "infrastructure/database/models/learning_analysis.py",
    "infrastructure/events/consumers/learning_",
    "infrastructure/tasks/learning_",
    "api/schemas/learning.py",
    "api/v1/endpoints/learning.py",
)

#: Non-Learning models a Learning module may construct, with the reason.
#: Empty, and expected to stay that way through phase 1 — phase 2's
#: candidates go through the Memory Manager, which is a service call, not
#: a model construction.
ALLOWED_FOREIGN_MODELS: dict[str, str] = {}

#: Memory writes, by the name of the thing that performs them. Phases 1
#: and 2 perform none: an observation is evidence *for* a future memory
#: fact, a cluster is a population, and neither is a fact.
MEMORY_WRITE_CALLS: frozenset[str] = frozenset(
    {
        "record_observation",
        "confirm",
        "contradict",
        "supersede",
        "suppress",
        "forget",
        "purge",
    }
)

#: Publishing, by the name of the thing that does it. **Phase 2 publishes
#: no findings**, and that is the phase's defining restraint rather than
#: an omission from it: candidates, suggestions, contradictions and
#: notifications are phases 3 and 4, and each one is a promise to a human
#: that phase 2 has not earned the right to make.
#:
#: The failure this guards against is specific and tempting. An anomaly
#: detector is one line away from a notification, and the line is easy to
#: add before anybody has measured whether the detector is right. Once
#: operators mute it, they mute it permanently — while the precision
#: problem gets fixed and nobody comes back.
PUBLISH_CALLS: frozenset[str] = frozenset({"publish", "send_task", "notify", "dispatch"})

#: Modules allowed to publish, and what they are allowed to publish.
#:
#: Adding an entry is the reviewable act — the same pattern
#: ``test_memory_manager_is_the_only_writer.py`` uses for memory writes.
#: The question to answer before adding one is not "is this event
#: harmless" but "does anything downstream *act* on it": an operator
#: action recorded for the audit trail is a different category from a
#: finding leaving Learning, and only the first is permitted here.
ALLOWED_PUBLISHERS: dict[str, str] = {
    "application/services/learning_settings_service.py": (
        "A threshold change is an operator action on configuration, not a "
        "finding. It is published so the audit-log consumer can record "
        "who changed what and why — required, because a threshold "
        "silently reshapes every cluster the platform will produce and "
        '"why did it stop finding anything in March" has to be '
        "answerable. Nothing acts on the event; the audit consumer writes "
        "a row and stops."
    ),
}

#: Substrings that make an event a *finding* rather than a record. Any of
#: these in a published event type is phase 3 arriving early, whatever
#: module it appears in.
FORBIDDEN_EVENT_FRAGMENTS: tuple[str, ...] = (
    "candidate",
    "suggestion",
    "contradiction",
    "trend_detected",
    "anomaly_detected",
    "gap_detected",
)

#: Contexts phase 2 must not reach into, by module path fragment. Reading
#: is not the concern — Learning reads conversations and messages by
#: design; *importing a writer* is.
FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "application.services.memory_manager",
    "application.services.knowledge_service",
    "application.services.ai_",
    "infrastructure.ai.",
)


def _model_names() -> frozenset[str]:
    """Every ORM model in the platform, by class name.

    Read from the source rather than from ``Base.registry`` so the guard
    does not depend on import order or on a metadata side effect — and so
    it keeps working if a model is added to a file nobody imported yet.
    """
    names: set[str] = set()
    for path in sorted(MODELS.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "Base" for base in node.bases
            ):
                names.add(node.name)
    return frozenset(names)


def _learning_files() -> list[tuple[str, pathlib.Path]]:
    found: list[tuple[str, pathlib.Path]] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative.startswith(LEARNING_PATHS):
            found.append((relative, path))
    return found


def _foreign_models_constructed(source: str, models: frozenset[str]) -> dict[str, int]:
    """``ModelName`` -> line, for every non-Learning model built here.

    Construction rather than ``session.add`` on purpose: an ORM object
    attached to a session is written at flush whether or not anybody
    called ``add``, so the construction is the moment the code becomes a
    writer.
    """
    found: dict[str, int] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in models
            and node.func.id not in LEARNING_MODELS
        ):
            found.setdefault(node.func.id, node.lineno)
    return found


def _foreign_write_statements(source: str, models: frozenset[str]) -> dict[str, int]:
    """``insert(X)`` / ``update(X)`` / ``delete(X)`` against a table
    Learning does not own.

    The Core-level escape hatch from the check above: a bulk UPDATE never
    constructs a model, so it would otherwise pass unseen.
    """
    found: dict[str, int] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"insert", "update", "delete"}
            and node.args
        ):
            target = node.args[0]
            name = target.id if isinstance(target, ast.Name) else None
            if name in models and name not in LEARNING_MODELS:
                found.setdefault(f"{node.func.id}({name})", node.lineno)
    return found


class TestLearningWritesOnlyItsOwnTables:
    def test_no_learning_module_constructs_a_foreign_model(self) -> None:
        models = _model_names()
        violations: dict[str, dict[str, int]] = {}
        for relative, path in _learning_files():
            offending = {
                name: line
                for name, line in _foreign_models_constructed(path.read_text(), models).items()
                if name not in ALLOWED_FOREIGN_MODELS
            }
            if offending:
                violations[relative] = offending

        assert not violations, (
            "Learning constructs models it does not own, which makes it a writer of "
            "operational data and makes replay unsafe:\n"
            + "\n".join(
                f"  {where}: "
                + ", ".join(f"{name} (line {line})" for name, line in sorted(v.items()))
                for where, v in sorted(violations.items())
            )
            + "\n\nLearning reads other contexts and writes only learning_*. If a write "
            "outside those four tables is genuinely required, it belongs behind that "
            "context's own service — not in a Learning module."
        )

    def test_no_learning_module_issues_a_foreign_write_statement(self) -> None:
        models = _model_names()
        violations: dict[str, dict[str, int]] = {}
        for relative, path in _learning_files():
            offending = _foreign_write_statements(path.read_text(), models)
            if offending:
                violations[relative] = offending

        assert not violations, (
            "Learning issues Core-level writes against tables it does not own:\n"
            + "\n".join(
                f"  {where}: "
                + ", ".join(f"{stmt} (line {line})" for stmt, line in sorted(v.items()))
                for where, v in sorted(violations.items())
            )
        )

    def test_learning_models_are_built_only_inside_learning(self) -> None:
        """The other direction.

        Learning owning its tables means nothing if another context can
        write an observation. An observation written by somebody else has
        no guarantee of evidence refs, no pipeline version anybody can
        replay, and no policy check.
        """
        learning_paths = {relative for relative, _ in _learning_files()}
        violations: dict[str, dict[str, int]] = {}
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(SRC).as_posix()
            if relative in learning_paths:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            offending = {
                node.func.id: node.lineno
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in LEARNING_MODELS
            }
            if offending:
                violations[relative] = offending

        assert not violations, (
            "These build Learning rows from outside the Learning context:\n"
            + "\n".join(
                f"  {where}: "
                + ", ".join(f"{name} (line {line})" for name, line in sorted(v.items()))
                for where, v in sorted(violations.items())
            )
            + "\n\nGo through LearningObservationService, which validates the "
            "observation, attaches its evidence refs and stamps the pipeline version."
        )

    def test_the_guard_actually_fires(self) -> None:
        """A guard nobody has watched fail is a guard nobody knows works."""
        models = _model_names()
        assert "Conversation" in models, "the model scan found nothing to guard against"

        assert _foreign_models_constructed(
            "def bad(session):\n    session.add(Conversation(id=1))\n", models
        ) == {"Conversation": 2}
        assert _foreign_write_statements(
            "def bad(session):\n    session.execute(update(Conversation).values(x=1))\n", models
        ) == {"update(Conversation)": 2}
        # And does not fire on the things Learning legitimately does.
        assert not _foreign_models_constructed(
            "def fine():\n    return LearningObservation(id=1)\n", models
        )
        assert not _foreign_write_statements(
            "def fine(session):\n    session.execute(select(Conversation))\n", models
        )


class TestLearningDoesNotWriteMemory:
    """Phase 1 boundary, and charter §9.

    An observation is evidence, not a fact. The distinction matters
    because a fact carries confidence and a confidence that can be written
    from two places is a confidence nobody can explain.
    """

    def test_no_learning_module_calls_a_memory_write(self) -> None:
        violations: dict[str, list[str]] = {}
        for relative, path in _learning_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            calls = sorted(
                {
                    f"{node.func.attr} (line {node.lineno})"
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in MEMORY_WRITE_CALLS
                }
            )
            if calls:
                violations[relative] = calls

        assert not violations, (
            "Phase 1 writes no memory — clustering, candidates and promotion are "
            "phase 2, and when they arrive they go through MemoryManager:\n"
            + "\n".join(
                f"  {where}: {', '.join(calls)}" for where, calls in sorted(violations.items())
            )
        )


class TestTheEvidenceGraphStaysAcyclic:
    """Invariant I-4.

    Learning may consume operational events. It may not consume Memory's
    events, and it may not consume its own: either would let confidence
    rise from output rather than from evidence, which is the failure the
    entire two-axis lifecycle exists to prevent.
    """

    @pytest.mark.parametrize(
        "module",
        [
            "learning_observation_consumer",
            "learning_signals_consumer",
        ],
    )
    def test_consumers_bind_no_memory_or_learning_events(self, module: str) -> None:
        path = SRC / "infrastructure" / "events" / "consumers" / f"{module}.py"
        tree = ast.parse(path.read_text(), filename=str(path))

        keys: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "ROUTING_KEYS"
                    for target in node.targets
                )
                and isinstance(node.value, ast.List)
            ):
                keys = [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                ]

        assert keys, f"{module} declares no ROUTING_KEYS — the guard has gone stale"
        cyclic = [key for key in keys if key.startswith(("memory.", "learning.", "intelligence."))]
        assert not cyclic, (
            f"{module} consumes {cyclic}, closing the evidence loop: Learning would "
            "observe its own output, and confidence could rise with no new human "
            "evidence anywhere in the cycle."
        )


class TestPhaseTwoStaysInsideItsPhase:
    """Phase 2 discovers. It proposes nothing and tells nobody.

    Every item here is on the charter's explicit "MUST NOT" list for this
    phase. They are guarded statically rather than behaviourally because
    each is an *absence*, and a behavioural test can only prove that the
    paths somebody wrote do not do it.
    """

    #: Learning modules allowed to publish, and why.
    #:
    #: The rule is about the **detector**: a finding must not reach anybody
    #: until its precision is known. An administrator changing a threshold is
    #: not the detector telling anybody anything — it is a human act on the
    #: platform, and every one of those is audited. Suppressing it would make
    #: Learning the single module where a configuration change leaves no
    #: trail, which is a worse outcome than the one this guard prevents.
    #:
    #: Narrow on purpose: the exemption is per file and per reason, so a
    #: detector that starts publishing still fails here.
    MAY_PUBLISH: dict[str, str] = {
        "application/services/learning_settings_service.py": (
            "publishes `learning.thresholds_changed` — the audit trail for an "
            "administrator's own edit, carrying the previous and current value. "
            "Not a finding, and not addressed to an operator."
        ),
    }

    def test_learning_publishes_nothing(self) -> None:
        violations: dict[str, list[str]] = {}
        for relative, path in _learning_files():
            if relative in self.MAY_PUBLISH:
                continue
            if relative in ALLOWED_PUBLISHERS:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            calls = sorted(
                {
                    f"{node.func.attr} (line {node.lineno})"
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in PUBLISH_CALLS
                }
            )
            if calls:
                violations[relative] = calls

        assert not violations, (
            "Phase 2 stores findings and notifies nobody. Candidate events, "
            "knowledge suggestions and notifications are phases 3 and 4:\n"
            + "\n".join(
                f"  {where}: {', '.join(calls)}" for where, calls in sorted(violations.items())
            )
            + "\n\nAn anomaly detector wired to alerting before its precision is "
            "known teaches operators to mute it, and the mute outlives the fix.\n"
            "If this module publishes an *audit* record of a human's own action "
            "rather than a finding, add it to MAY_PUBLISH with the reason."
        )

    def test_the_publish_exemptions_have_not_gone_stale(self) -> None:
        """An exemption for a module that no longer publishes reads like
        coverage and is not — the same rot every allow-list in this codebase
        is guarded against."""
        learning = dict(_learning_files())
        stale = []
        for relative in self.MAY_PUBLISH:
            path = learning.get(relative)
            if path is None:
                stale.append(f"{relative} (no longer a learning module)")
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            publishes = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in PUBLISH_CALLS
                for node in ast.walk(tree)
            )
            if not publishes:
                stale.append(f"{relative} (no longer publishes)")

        assert not stale, f"MAY_PUBLISH has drifted — remove these: {stale}"

    def test_no_finding_is_ever_published(self) -> None:
        """The rule the allow-list must not be able to weaken.

        A module on ``ALLOWED_PUBLISHERS`` may publish a *record* — who
        changed a threshold, and why. It may not publish a *finding*,
        because a finding leaving Learning is something downstream acts
        on, and that is phase 3. Checked by event name across every
        Learning module, allow-listed or not.
        """
        violations: dict[str, list[str]] = {}
        for relative, path in _learning_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            offending = sorted(
                {
                    f"{node.value} (line {node.lineno})"
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and any(
                        fragment in node.value.lower() for fragment in FORBIDDEN_EVENT_FRAGMENTS
                    )
                    # A docstring mentioning "candidate" is prose, not an
                    # event. Only strings that look like event types —
                    # dotted, lowercase, no spaces — are considered.
                    and "." in node.value
                    and " " not in node.value
                }
            )
            if offending:
                violations[relative] = offending

        assert not violations, (
            "Learning publishes something that reads as a finding. Candidates, "
            "suggestions and contradictions are phases 3 and 4:\n"
            + "\n".join(
                f"  {where}: {', '.join(events)}" for where, events in sorted(violations.items())
            )
        )

    def test_the_publisher_allow_list_has_not_gone_stale(self) -> None:
        """An entry for a module that no longer publishes reads like the
        guard covers something when it covers nothing."""
        publishing = set()
        for relative, path in _learning_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in PUBLISH_CALLS
                for node in ast.walk(tree)
            ):
                publishing.add(relative)

        vanished = sorted(set(ALLOWED_PUBLISHERS) - publishing)
        assert (
            not vanished
        ), f"ALLOWED_PUBLISHERS names modules that no longer publish — delete these: {vanished}"

    def test_learning_imports_no_other_context_s_writer(self) -> None:
        violations: dict[str, list[str]] = {}
        for relative, path in _learning_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            bad: list[str] = []
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = ",".join(alias.name for alias in node.names)
                if any(fragment in module for fragment in FORBIDDEN_IMPORTS):
                    bad.append(f"{module} (line {node.lineno})")
            if bad:
                violations[relative] = sorted(bad)

        assert not violations, (
            "Learning imports another context's writer, which is one call away "
            "from using it:\n"
            + "\n".join(f"  {where}: {', '.join(bad)}" for where, bad in sorted(violations.items()))
        )

    def test_no_model_is_called_anywhere_in_learning(self) -> None:
        """Charter phase 2: no LLM reasoning at all.

        Guarded by import rather than by call, because a model provider
        that is imported but not yet called is a change of mind away from
        being called, and the review that would catch it is the one that
        just approved the import.
        """
        violations: dict[str, list[str]] = {}
        for relative, path in _learning_files():
            source = path.read_text()
            hits = [
                fragment
                for fragment in ("AiProvider", "openai", "anthropic", "ollama", "completion(")
                if fragment in source
            ]
            if hits:
                violations[relative] = hits

        assert not violations, (
            "Phase 2 makes no model calls — clustering is lexical and the "
            "statistics are arithmetic:\n"
            + "\n".join(
                f"  {where}: {', '.join(hits)}" for where, hits in sorted(violations.items())
            )
        )
