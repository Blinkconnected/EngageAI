"""Where a conversation's SLA targets come from, and in what order.

This exists because the product had two answers and used the wrong one. The
SLA Builder wrote a policy, an administrator attached it to a queue, and the
engine read targets from the *service directory* only — so a company with no
services started no clocks at all, and `conversation_sla_clocks` held zero
rows across the entire installation. The Breached work queue was permanently
empty, SLA health was missing from Inbox ordering, and no conversation story
mentioned an SLA. Nothing reported a fault, because from the engine's side
nothing was wrong: it was never given a target.

The rule below is the same one already adopted for the AI confidence
threshold — the most specific configuration wins, and the broader one is the
fallback rather than the override.
"""

import pytest

from blinkengage.domain.service_context import SlaTargets
from blinkengage.domain.sla import (
    PLATFORM_DEFAULT_SLA_TARGETS,
    SlaTargetSource,
    resolve_sla_targets,
)


class TestTheMostSpecificConfigurationWins:
    def test_a_service_that_measures_something_is_used_whole(self) -> None:
        service = SlaTargets(first_response_minutes=5, resolution_minutes=60)
        queue = SlaTargets(first_response_minutes=999, resolution_minutes=999)

        resolved = resolve_sla_targets(service=service, queue=queue)

        assert resolved.value == service
        assert resolved.source is SlaTargetSource.SERVICE

    def test_the_queue_answers_when_the_service_does_not(self) -> None:
        queue = SlaTargets(first_response_minutes=3, resolution_minutes=15)

        resolved = resolve_sla_targets(service=None, queue=queue)

        assert resolved.value == queue
        assert resolved.source is SlaTargetSource.QUEUE

    def test_the_platform_answers_when_nobody_else_does(self) -> None:
        resolved = resolve_sla_targets(service=None, queue=None)

        assert resolved.value == PLATFORM_DEFAULT_SLA_TARGETS
        assert resolved.source is SlaTargetSource.PLATFORM_DEFAULT


class TestASourceIsChosenWholeOrNotAtAll:
    """The tiers do not blend.

    Taking first-response from a service and resolution from a queue would
    produce a pair of deadlines nobody authored — the same objection
    ``SlaTargets`` already makes about folding its four clocks into one. A
    supervisor asked "where did this deadline come from?" must have exactly
    one answer.
    """

    def test_a_service_measuring_one_clock_does_not_borrow_the_others(self) -> None:
        service = SlaTargets(first_response_minutes=5)
        queue = SlaTargets(first_response_minutes=99, resolution_minutes=60)

        resolved = resolve_sla_targets(service=service, queue=queue)

        assert resolved.value.first_response_minutes == 5
        assert resolved.value.resolution_minutes is None, "not borrowed from the queue"

    def test_a_source_measuring_nothing_is_not_a_source(self) -> None:
        """An empty ``SlaTargets`` is indistinguishable from no configuration.

        A service exists with every target left blank far more often than
        somebody means "measure nothing here, and ignore the queue's policy
        too" — and reading it as a choice would silently switch measurement
        off for the queue underneath it.
        """
        queue = SlaTargets(first_response_minutes=3)

        resolved = resolve_sla_targets(service=SlaTargets(), queue=queue)

        assert resolved.source is SlaTargetSource.QUEUE
        assert resolved.value == queue


class TestThePlatformDefaultIsConservative:
    def test_it_measures_a_first_response(self) -> None:
        """The one target every support desk recognises.

        Without it this tier would exist and change nothing, which is the
        state the whole fix is about.
        """
        assert PLATFORM_DEFAULT_SLA_TARGETS.first_response_minutes is not None
        assert PLATFORM_DEFAULT_SLA_TARGETS.measures_anything

    def test_it_does_not_invent_a_queue_deadline(self) -> None:
        """ "How long may this sit before somebody accepts it" is an
        operational promise a business makes, not one the platform may make
        on its behalf."""
        assert PLATFORM_DEFAULT_SLA_TARGETS.queue_minutes is None

    @pytest.mark.parametrize(
        "minutes",
        [
            PLATFORM_DEFAULT_SLA_TARGETS.first_response_minutes,
            PLATFORM_DEFAULT_SLA_TARGETS.resolution_minutes,
        ],
    )
    def test_every_default_it_does_set_is_generous(self, minutes: int | None) -> None:
        """Tight enough to be meaningful, loose enough that a company which
        never configured an SLA does not open the Inbox to a wall of red it
        did not agree to."""
        if minutes is not None:
            assert minutes >= 60
