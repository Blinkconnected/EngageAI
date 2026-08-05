"""When AI may take a conversation. No database, no clock.

See ``docs/architecture/ai-eligibility-model.md``.

The case that matters most is ``test_a_follow_up_message_becomes_eligible``:
it is the defect this whole model replaces. Engagement used to be decided once
at conversation creation, so a customer who wrote again an hour later never
became eligible — the conversation had already been judged. A real message sat
unanswered for over an hour on a queue with AI enabled and a provider
configured, and nothing anywhere reported a fault, because the platform was
not failing to answer. It was never asking.
"""

from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.domain.ai_eligibility import Decision, Facts, Ineligible, evaluate

NINE = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


def facts(**overrides: object) -> Facts:
    """An eligible conversation, so each test states only what it changes."""
    base: dict[str, object] = {
        "awaiting_reply_since": NINE,
        "last_customer_message_at": NINE,
        "conversation_is_finished": False,
        "a_human_owns_it": False,
        "policy_allows_it": True,
        "queue_opted_in": True,
        "pickup_delay": timedelta(seconds=30),
        "activity_window": timedelta(hours=1),
        "already_answered_latest": False,
    }
    base.update(overrides)
    return Facts(**base)  # type: ignore[arg-type]


def at(**kwargs: float) -> datetime:
    return NINE + timedelta(**kwargs)


class TestTheDefectThisReplaces:
    async def test_a_follow_up_message_becomes_eligible(self) -> None:
        """The bug, stated as a test.

        A conversation created hours ago, judged ineligible then, and left
        alone. The customer writes again. Under the old model nothing
        re-asked — the decision had been made at creation. Here the question
        is about *the customer's most recent unanswered message*, so the
        follow-up is eligible on its own merits.
        """
        follow_up = at(hours=3)

        decision = evaluate(
            facts(awaiting_reply_since=follow_up, last_customer_message_at=follow_up),
            now=follow_up + timedelta(minutes=1),
        )

        assert decision == Decision.yes()

    async def test_an_hour_of_silence_is_not_eligibility(self) -> None:
        """The other half. A message nobody answered for an hour is *out of
        window*, not eligible — a reply arriving an hour late reads as a
        system talking to itself, and the customer has gone."""
        decision = evaluate(facts(), now=at(hours=2))

        assert decision.reason is Ineligible.CUSTOMER_HAS_MOVED_ON


class TestTheHumanKeepsFirstRefusal:
    async def test_the_delay_is_respected(self) -> None:
        decision = evaluate(facts(), now=at(seconds=10))

        assert decision.reason is Ineligible.STILL_GIVING_A_HUMAN_FIRST_REFUSAL

    async def test_it_becomes_eligible_by_the_passage_of_time_alone(self) -> None:
        """Nothing has to happen for this to change, which is exactly why the
        sweep must re-ask rather than decide once."""
        waiting = facts()

        assert not evaluate(waiting, now=at(seconds=29)).eligible
        assert evaluate(waiting, now=at(seconds=30)).eligible

    async def test_the_boundary_is_inclusive(self) -> None:
        """At exactly the delay, the human has had their thirty seconds."""
        assert evaluate(facts(), now=at(seconds=30)).eligible

    async def test_a_zero_delay_answers_immediately(self) -> None:
        """Outside business hours the delay collapses to zero — there is no
        human to defer to at 03:00, and deliberate silence serves nobody."""
        assert evaluate(facts(pickup_delay=timedelta()), now=NINE).eligible

    async def test_a_human_owning_it_stops_ai_outright(self) -> None:
        """Read from ownership rather than a flag: a flag can disagree with
        the timeline, the timeline cannot disagree with itself."""
        decision = evaluate(facts(a_human_owns_it=True), now=at(minutes=5))

        assert decision.reason is Ineligible.A_HUMAN_OWNS_IT

    async def test_a_human_outranks_an_elapsed_delay(self) -> None:
        """Ordering matters. Reporting "the delay has not elapsed" for a
        conversation an agent is holding would send somebody to shorten a
        delay that was never the reason."""
        decision = evaluate(facts(a_human_owns_it=True), now=at(hours=99))

        assert decision.reason is Ineligible.A_HUMAN_OWNS_IT


class TestTheActivityWindow:
    async def test_inside_the_window_is_eligible(self) -> None:
        assert evaluate(facts(), now=at(minutes=59)).eligible

    async def test_the_window_boundary_is_inclusive(self) -> None:
        assert evaluate(facts(), now=at(minutes=60)).eligible

    async def test_past_the_window_the_customer_has_moved_on(self) -> None:
        decision = evaluate(facts(), now=at(minutes=61))

        assert decision.reason is Ineligible.CUSTOMER_HAS_MOVED_ON

    async def test_a_longer_window_keeps_it_answerable(self) -> None:
        """Outside business hours the window is twelve hours, because an
        overnight message is still worth answering at 07:00."""
        decision = evaluate(facts(activity_window=timedelta(hours=12)), now=at(hours=8))

        assert decision.eligible

    async def test_which_window_applies_is_a_property_of_now(self) -> None:
        """Decided at evaluation time, not frozen when the message arrived.
        An overnight message evaluated during working hours is measured
        against the *business-hours* window — otherwise it would stay
        answerable deep into a morning when humans were available and chose
        not to answer it."""
        overnight = facts(activity_window=timedelta(hours=1))

        assert not evaluate(overnight, now=at(hours=10)).eligible


class TestTheBurstCase:
    async def test_the_delay_runs_from_the_newest_message(self) -> None:
        """A customer who wrote at 09:00 and again at 09:04 has had a human's
        attention available for four minutes on the first — but the reply
        would answer the *second*, so the delay runs from there.

        Measuring from the oldest would give the customer who chased an
        instant reply and make the patient one wait, which is backwards.
        """
        burst = facts(awaiting_reply_since=NINE, last_customer_message_at=at(minutes=4))

        assert not evaluate(burst, now=at(minutes=4, seconds=10)).eligible
        assert evaluate(burst, now=at(minutes=4, seconds=30)).eligible

    async def test_the_window_also_runs_from_the_newest_message(self) -> None:
        """A conversation open for hours is still live if the customer spoke
        a minute ago. The wait is old; the customer is not gone."""
        long_running = facts(awaiting_reply_since=NINE, last_customer_message_at=at(hours=6))

        assert evaluate(long_running, now=at(hours=6, minutes=1)).eligible


class TestTheGates:
    async def test_nobody_waiting_is_the_resting_state(self) -> None:
        decision = evaluate(facts(awaiting_reply_since=None), now=at(minutes=5))

        assert decision.reason is Ineligible.NOBODY_IS_WAITING

    async def test_a_finished_conversation_is_not_answered_again(self) -> None:
        decision = evaluate(facts(conversation_is_finished=True), now=at(minutes=5))

        assert decision.reason is Ineligible.CONVERSATION_FINISHED

    async def test_a_refused_policy_stops_it(self) -> None:
        decision = evaluate(facts(policy_allows_it=False), now=at(minutes=5))

        assert decision.reason is Ineligible.POLICY_REFUSED

    async def test_a_queue_that_never_opted_in_stops_it(self) -> None:
        decision = evaluate(facts(queue_opted_in=False), now=at(minutes=5))

        assert decision.reason is Ineligible.QUEUE_HAS_NOT_OPTED_IN

    async def test_the_same_message_is_not_answered_twice(self) -> None:
        """Guards against two sweep runs overlapping — the customer hearing
        from AI twice is worse than hearing from it a sweep later."""
        decision = evaluate(facts(already_answered_latest=True), now=at(minutes=5))

        assert decision.reason is Ineligible.ALREADY_ANSWERED_THIS_MESSAGE


class TestEveryRefusalIsAnswerable:
    async def test_no_decision_refuses_without_a_reason(self) -> None:
        """A sweep that skips a conversation without saying why is the
        original defect wearing different clothes: it looks like nothing
        happened."""
        cases = [
            facts(awaiting_reply_since=None),
            facts(conversation_is_finished=True),
            facts(a_human_owns_it=True),
            facts(policy_allows_it=False),
            facts(queue_opted_in=False),
            facts(already_answered_latest=True),
            facts(),  # delay not elapsed at `now=NINE`
            facts(activity_window=timedelta(seconds=1)),
        ]

        for case in cases:
            decision = evaluate(case, now=NINE)
            assert decision.eligible or decision.reason is not None

    async def test_every_reason_is_reachable(self) -> None:
        """A vocabulary with an unreachable member is a vocabulary that has
        drifted from the rule — the member reads as a case somebody handled
        and nothing produces it."""
        produced = {
            evaluate(facts(awaiting_reply_since=None), now=NINE).reason,
            evaluate(facts(conversation_is_finished=True), now=NINE).reason,
            evaluate(facts(a_human_owns_it=True), now=NINE).reason,
            evaluate(facts(already_answered_latest=True), now=NINE).reason,
            evaluate(facts(queue_opted_in=False), now=NINE).reason,
            evaluate(facts(policy_allows_it=False), now=NINE).reason,
            evaluate(facts(), now=NINE).reason,
            evaluate(facts(), now=at(hours=2)).reason,
        }

        assert produced == set(Ineligible)


pytestmark = pytest.mark.asyncio
