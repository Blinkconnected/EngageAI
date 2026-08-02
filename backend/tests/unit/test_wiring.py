"""The guard that stops a half-wired service reaching production.

Four defects have had the same shape here: a service that works alone,
reached through an optional dependency production never passed, failing
*silently*. The guard turns that into a container that will not start.

Two things need testing, and the second is the one that matters. That the
guard fires — a guard nobody has seen fail is a guard nobody knows works. And
that the guard's own list has not fallen behind the code it guards, because
a check that silently stops covering something is worse than no check: it
reads like coverage.
"""

from typing import Any

import pytest

from blinkengage.core.wiring import (
    Collaborator,
    CriticalService,
    WiringError,
    critical_services,
    verify_wiring,
)


class _Fine:
    def __init__(self) -> None:
        self.collaborator = object()


class _HalfWired:
    def __init__(self) -> None:
        self.collaborator = None


def _guard(built: Any, *, path: str = "collaborator") -> None:
    """Runs the guard over one hand-made service."""
    service = CriticalService(
        name="Test service",
        build=lambda _session: built,
        collaborators=(
            Collaborator(path=path, name="Test collaborator", consequence="nothing would happen"),
        ),
    )
    import blinkengage.core.wiring as wiring

    original = wiring.critical_services
    wiring.critical_services = lambda: (service,)  # type: ignore[assignment]
    try:
        verify_wiring(lambda: None)  # type: ignore[arg-type,return-value]
    finally:
        wiring.critical_services = original  # type: ignore[assignment]


class TestTheGuardActuallyFires:
    def test_a_complete_service_boots(self) -> None:
        _guard(_Fine())

    def test_a_missing_collaborator_stops_the_boot(self) -> None:
        with pytest.raises(WiringError) as error:
            _guard(_HalfWired())

        message = str(error.value)
        assert "Test service" in message
        assert "Test collaborator" in message
        # The consequence, not just the name. An operator reading this at 3am
        # did not write the wiring and needs to know what stopped working.
        assert "nothing would happen" in message

    def test_a_service_that_cannot_be_built_is_reported_rather_than_raised_raw(self) -> None:
        """A factory that throws is a wiring problem too, and must arrive in
        the same message as every other one rather than as a bare traceback
        from somewhere inside the object graph."""

        def explode(_session: Any) -> Any:
            raise ValueError("no attachment store")

        service = CriticalService(
            name="Broken",
            build=explode,
            collaborators=(Collaborator(path="x", name="X", consequence="y"),),
        )
        import blinkengage.core.wiring as wiring

        original = wiring.critical_services
        wiring.critical_services = lambda: (service,)  # type: ignore[assignment]
        try:
            with pytest.raises(WiringError) as error:
                verify_wiring(lambda: None)  # type: ignore[arg-type,return-value]
        finally:
            wiring.critical_services = original  # type: ignore[assignment]

        assert "could not be built at all" in str(error.value)
        assert "no attachment store" in str(error.value)

    def test_every_problem_is_reported_at_once(self) -> None:
        """An operator who fixes one, restarts, and finds a second is an
        operator who stops trusting the message."""
        service = CriticalService(
            name="Test service",
            build=lambda _session: _HalfWired(),
            collaborators=(
                Collaborator(path="collaborator", name="First", consequence="a"),
                Collaborator(path="missing_entirely", name="Second", consequence="b"),
            ),
        )
        import blinkengage.core.wiring as wiring

        original = wiring.critical_services
        wiring.critical_services = lambda: (service,)  # type: ignore[assignment]
        try:
            with pytest.raises(WiringError) as error:
                verify_wiring(lambda: None)  # type: ignore[arg-type,return-value]
        finally:
            wiring.critical_services = original  # type: ignore[assignment]

        assert "First" in str(error.value)
        assert "Second" in str(error.value)


class TestTheGuardsListHasNotFallenBehind:
    """The failure mode of a guard: it keeps passing while covering less.

    Someone adds an optional collaborator to a guarded service, production
    forgets to pass it, and the guard says nothing — because nobody added it
    to the list. That is the original defect wearing the guard's clothes.
    """

    def test_every_optional_collaborator_of_a_guarded_service_is_named(self) -> None:
        import inspect

        from blinkengage.application.services.autopilot_service import AutopilotService
        from blinkengage.application.services.conversation_service import ConversationService

        #: Constructor parameters that default to ``None`` and are *not*
        #: behaviour-critical — transport-shaped things a request supplies and
        #: a background job legitimately does without.
        allowed_absent = {
            "attachment_store",
            "provider_factory",
            "events",
            "realtime",
            "settings",
            "billable",
        }

        guarded = {
            ConversationService: "Conversation lifecycle",
            AutopilotService: "AI queue worker",
        }
        listed = {service.name: service for service in critical_services()}

        for cls, service_name in guarded.items():
            assert service_name in listed, f"{cls.__name__} is no longer guarded"
            covered = {
                # ``_sla._engine`` covers the ``sla`` parameter, ``_ownership``
                # the ``ownership`` one: compare on the leading segment.
                collaborator.path.split(".")[0].lstrip("_")
                for collaborator in listed[service_name].collaborators
            }
            optional = {
                name
                for name, parameter in inspect.signature(cls.__init__).parameters.items()
                if parameter.default is None and name not in allowed_absent
            }
            missing = optional - covered
            assert not missing, (
                f"{cls.__name__} has optional collaborators the start-up guard does "
                f"not check: {sorted(missing)}. Either add them to "
                f"``critical_services()`` in core/wiring.py, or add them to "
                f"``allowed_absent`` here with a reason they are safe to omit."
            )


class TestTheRealApplicationIsFullyWired:
    def test_the_production_graph_passes_its_own_guard(self) -> None:
        """The check that would have caught all four shipped defects.

        Builds the real services through the real factories — not a copy of
        them, which would pass while production stayed broken.
        """
        from blinkengage.core.container import Container

        verify_wiring(Container().session_factory())
