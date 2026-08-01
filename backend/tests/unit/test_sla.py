"""The four clocks, as customer experience rather than timers.

What is pinned here is mostly about *pausing*, because that is where SLA
engines go wrong in a way nobody notices: a clock that keeps running while a
customer has the ball reports the business as late for the customer's silence,
and a clock that pauses without saying why leaves a supervisor with a red row
and no idea whether to act.

Also the urgency banding, because it is what an agent actually sees. Four
bands rather than a percentage — a list sorted by a number still has to be
read one row at a time.
"""

from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.domain.routing_decisions import RoutingDecisionKind, RoutingDecisionReason
from blinkengage.domain.sla import (
    PAUSE_TEXT,
    QUESTION,
    RECORDED_AS,
    URGENCY_ORDER,
    Clock,
    PauseReason,
    SlaState,
    SlaTimer,
    Urgency,
    as_routing_decision,
    overall,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def a_clock(**kw) -> Clock:
    defaults = {
        "timer": SlaTimer.FIRST_RESPONSE,
        "state": SlaState.RUNNING,
        "target_minutes": 60,
        "running_since": NOW,
    }
    return Clock(**{**defaults, **kw})


class TestPausingIsTheWholePoint:
    def test_a_paused_clock_stops_counting(self) -> None:
        """Time a customer spends not replying is not time the business was
        late. A clock that kept running would report every slow customer as
        our failure."""
        paused = a_clock(
            state=SlaState.PAUSED,
            elapsed=timedelta(minutes=10),
            running_since=None,
            pause_reason=PauseReason.WAITING_FOR_CUSTOMER,
        )

        assert paused.counted(now=NOW + timedelta(hours=5)) == timedelta(minutes=10)

    def test_a_running_clock_counts_from_when_it_resumed(self) -> None:
        """Elapsed plus the current run — which is why the clock holds
        elapsed time rather than a start moment. A paused clock's elapsed
        does not move while wall-clock does."""
        running = a_clock(elapsed=timedelta(minutes=10), running_since=NOW)

        assert running.counted(now=NOW + timedelta(minutes=5)) == timedelta(minutes=15)

    def test_the_deadline_moves_while_paused(self) -> None:
        """Not a bug — the thing the Inspector has to explain. A deadline
        that did not move would make a pause meaningless."""
        paused = a_clock(
            state=SlaState.PAUSED,
            elapsed=timedelta(minutes=10),
            running_since=None,
            pause_reason=PauseReason.WAITING_FOR_CUSTOMER,
        )

        early = paused.deadline(now=NOW)
        later = paused.deadline(now=NOW + timedelta(hours=3))

        assert early is not None and later is not None
        assert later > early
        # And it always leaves the same amount of work-time remaining.
        assert later - (NOW + timedelta(hours=3)) == timedelta(minutes=50)

    def test_every_pause_reason_has_wording(self) -> None:
        """"The timer is paused" tells a supervisor nothing. "Paused,
        outside business hours" tells them there is nothing to do."""
        for reason in PauseReason:
            assert reason in PAUSE_TEXT
            assert PAUSE_TEXT[reason].strip()


class TestEachClockAnswersACustomerQuestion:
    def test_every_timer_states_its_question(self) -> None:
        """A timer labelled "first_response" explains nothing to somebody
        asking why a conversation is red."""
        for timer in SlaTimer:
            assert timer in QUESTION
            assert QUESTION[timer].endswith("?")

    def test_there_are_four(self) -> None:
        assert len(SlaTimer) == 4


class TestUrgencyIsWhatAnAgentSees:
    def test_a_breach_stays_breached(self) -> None:
        """A fact about what happened. A clock that could un-breach would
        let a late reply erase the lateness."""
        breached = a_clock(state=SlaState.BREACHED, settled_at=NOW)

        assert breached.urgency(now=NOW + timedelta(days=1)) is Urgency.BREACHED

    def test_eighty_percent_through_is_at_risk(self) -> None:
        clock = a_clock(elapsed=timedelta(minutes=48), running_since=None, state=SlaState.RUNNING)

        assert clock.urgency(now=NOW) is Urgency.AT_RISK

    def test_early_is_on_track(self) -> None:
        clock = a_clock(elapsed=timedelta(minutes=10), running_since=None)

        assert clock.urgency(now=NOW) is Urgency.ON_TRACK

    def test_a_paused_clock_can_safely_wait(self) -> None:
        """The band that lets an agent ignore something without wondering
        whether they should."""
        paused = a_clock(
            state=SlaState.PAUSED,
            elapsed=timedelta(minutes=59),
            running_since=None,
            pause_reason=PauseReason.WAITING_FOR_CUSTOMER,
        )

        assert paused.urgency(now=NOW) is Urgency.RESTING

    def test_an_unmeasured_clock_is_not_urgent(self) -> None:
        assert a_clock(target_minutes=None).urgency(now=NOW) is Urgency.RESTING

    def test_a_zero_target_is_late_immediately_and_does_not_divide(self) -> None:
        """A configuration an administrator is allowed to save. Reported
        rather than crashed on."""
        assert a_clock(target_minutes=0).urgency(now=NOW) is Urgency.BREACHED

    def test_the_worst_clock_decides_the_conversation(self) -> None:
        """Never an average. A conversation whose first response is twenty
        minutes overdue is not "mostly fine" because its resolution target
        is generous."""
        clocks = [
            a_clock(timer=SlaTimer.RESOLUTION, elapsed=timedelta(minutes=1), running_since=None),
            a_clock(timer=SlaTimer.FIRST_RESPONSE, state=SlaState.BREACHED),
        ]

        assert overall(clocks, now=NOW) is Urgency.BREACHED

    def test_nothing_measured_rests(self) -> None:
        assert overall([], now=NOW) is Urgency.RESTING

    def test_the_bands_are_ordered_worst_first(self) -> None:
        """Sorting an inbox by urgency is sorting by what needs doing."""
        assert URGENCY_ORDER == (
            Urgency.BREACHED,
            Urgency.AT_RISK,
            Urgency.ON_TRACK,
            Urgency.RESTING,
        )


class TestTheTimelineGoesInTheSameLog:
    def test_a_pause_records_its_reason_and_the_new_deadline(self) -> None:
        """"Why did this deadline change?" is answered by comparing two
        rows, which is why the deadline is on every one."""
        paused = a_clock(
            state=SlaState.PAUSED,
            elapsed=timedelta(minutes=10),
            running_since=None,
            pause_reason=PauseReason.WAITING_FOR_CUSTOMER,
        )
        kind, reason = RECORDED_AS[SlaState.PAUSED]

        decision = as_routing_decision(paused, kind=kind, reason=reason, now=NOW)

        assert decision.kind is RoutingDecisionKind.SLA_PAUSED
        assert decision.sla is not None
        assert decision.sla.pause_reason == "waiting_for_customer"
        assert decision.sla.pause_text == "waiting for the customer to reply"
        assert decision.sla.deadline == NOW + timedelta(minutes=50)
        assert decision.sla.elapsed_minutes == pytest.approx(10.0)

    def test_it_reads_as_a_sentence(self) -> None:
        paused = a_clock(
            state=SlaState.PAUSED,
            running_since=None,
            pause_reason=PauseReason.OUTSIDE_BUSINESS_HOURS,
        )
        kind, reason = RECORDED_AS[SlaState.PAUSED]

        decision = as_routing_decision(paused, kind=kind, reason=reason, now=NOW)

        assert decision.sentence == (
            "The first response clock paused: outside business hours."
        )

    def test_a_breach_reads_as_one(self) -> None:
        kind, reason = RECORDED_AS[SlaState.BREACHED]

        decision = as_routing_decision(
            a_clock(state=SlaState.BREACHED), kind=kind, reason=reason, now=NOW
        )

        assert decision.sentence == "The first response target was missed."

    def test_the_question_travels_with_the_row(self) -> None:
        """Frozen at the moment. A reader months later should not have to
        know what "next_response" meant in the release that wrote it."""
        kind, reason = RECORDED_AS[SlaState.RUNNING]

        decision = as_routing_decision(
            a_clock(timer=SlaTimer.NEXT_RESPONSE), kind=kind, reason=reason, now=NOW
        )

        assert decision.sla is not None
        assert decision.sla.question == QUESTION[SlaTimer.NEXT_RESPONSE]

    def test_every_state_that_can_happen_is_recorded(self) -> None:
        """A state with no recording is a transition the timeline would
        silently drop. ``NOT_MEASURED`` is absent on purpose — a clock that
        was never measured has no transitions."""
        recordable = {state for state in SlaState if state is not SlaState.NOT_MEASURED}

        assert set(RECORDED_AS) == recordable

    def test_stopped_is_not_achieved(self) -> None:
        """The conversation ended before this clock could be met or missed.
        Counting an abandoned conversation as a success is how a dashboard
        lies."""
        kind, reason = RECORDED_AS[SlaState.STOPPED]

        assert kind is RoutingDecisionKind.SLA_STOPPED
        assert reason is RoutingDecisionReason.SLA_CLOCK_STOPPED
