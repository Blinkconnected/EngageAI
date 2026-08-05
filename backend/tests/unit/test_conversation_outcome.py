"""One definition of how a conversation ended.

**O2, O4 and E2 from the architecture freeze review.** Outcome was about
to have two implementations — Reporting's and Learning's — which is the
shape of the A3 defect that produced zero SLA clocks platform-wide. These
tests pin the single definition, including the two properties the freeze
review added: *who* resolved it, and whether the answer is final yet.
"""

from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.domain.conversation_outcome import (
    DEFAULT_SETTLE_HOURS,
    OutcomeInputs,
    ResolvedBy,
    derive,
    is_settled,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
STARTED = NOW - timedelta(hours=6)
ENDED = NOW - timedelta(hours=5)


def _inputs(**overrides: object) -> OutcomeInputs:
    base: dict[str, object] = {
        "status": "resolved",
        "started_at": STARTED,
        "ended_at": ENDED,
        "now": NOW,
        "resolved_by": ResolvedBy.HUMAN,
        "inbound_message_count": 1,
        "outbound_message_count": 1,
    }
    base.update(overrides)
    return OutcomeInputs(**base)  # type: ignore[arg-type]


class TestWhoResolvedItIsPartOfTheOutcome:
    """O4 — a workflow auto-close read as `resolved`, so anything learning
    from outcomes would conclude that whatever preceded it worked. That is
    a feedback loop the AI-provenance mitigation does not touch, because a
    workflow is not AI."""

    def test_a_human_resolution_is_attributable(self) -> None:
        assert derive(_inputs(resolved_by=ResolvedBy.HUMAN)).attributable

    def test_a_workflow_auto_close_is_not_attributable(self) -> None:
        outcome = derive(_inputs(resolved_by=ResolvedBy.WORKFLOW))

        assert outcome.resolved is True
        assert outcome.attributable is False

    def test_a_timeout_close_is_not_attributable(self) -> None:
        """Nobody decided anything, which is the weakest possible evidence
        that something worked."""
        assert not derive(_inputs(resolved_by=ResolvedBy.TIMEOUT)).attributable

    def test_an_ai_resolution_is_not_attributable(self) -> None:
        assert not derive(_inputs(resolved_by=ResolvedBy.AI)).attributable

    def test_an_unknown_resolver_is_not_guessed_at(self) -> None:
        outcome = derive(_inputs(resolved_by=ResolvedBy.UNKNOWN))

        assert outcome.resolved_by is ResolvedBy.UNKNOWN
        assert outcome.attributable is False


class TestQualityIsNeverInvented:
    def test_csat_dominates_where_it_exists(self) -> None:
        """A customer saying so beats any inference."""
        assert derive(_inputs(csat_score=5)).quality == pytest.approx(1.0)
        assert derive(_inputs(csat_score=1)).quality == pytest.approx(0.0)
        assert derive(_inputs(csat_score=3)).quality == pytest.approx(0.5)

    def test_unmeasured_is_none_not_zero(self) -> None:
        """Most conversations have no CSAT. Treating unmeasured as bad
        would mean only the surveyed minority could ever be believed."""
        assert derive(_inputs(csat_score=None)).quality is None

    def test_a_reopen_is_structural_evidence_without_a_survey(self) -> None:
        outcome = derive(_inputs(csat_score=None, reopened_at=ENDED + timedelta(hours=2)))

        assert outcome.reopened is True
        assert outcome.quality == pytest.approx(0.25)

    def test_an_escalation_is_structural_evidence_too(self) -> None:
        assert derive(_inputs(csat_score=None, escalated=True)).quality == pytest.approx(0.25)

    def test_an_unresolved_conversation_has_no_quality(self) -> None:
        assert derive(_inputs(status="open", ended_at=None)).quality is None


class TestFirstContactResolution:
    def test_one_inbound_turn_with_no_escalation_qualifies(self) -> None:
        assert derive(_inputs(inbound_message_count=1)).first_contact_resolution

    def test_a_transfer_disqualifies_it(self) -> None:
        """Counting only messages would call a conversation transferred
        twice and answered once 'first contact', which is the reading that
        makes the metric flattering and useless."""
        assert not derive(_inputs(transferred_count=1)).first_contact_resolution

    def test_an_escalation_disqualifies_it(self) -> None:
        assert not derive(_inputs(escalated=True)).first_contact_resolution

    def test_a_reopen_disqualifies_it(self) -> None:
        outcome = derive(_inputs(reopened_at=ENDED + timedelta(hours=1)))
        assert not outcome.first_contact_resolution

    def test_several_inbound_turns_disqualify_it(self) -> None:
        assert not derive(_inputs(inbound_message_count=4)).first_contact_resolution


class TestReopenWindow:
    def test_a_prompt_reopen_counts_against_the_resolution(self) -> None:
        assert derive(_inputs(reopened_at=ENDED + timedelta(hours=2))).reopened

    def test_a_much_later_reopen_is_a_new_problem(self) -> None:
        outcome = derive(_inputs(reopened_at=ENDED + timedelta(days=30)))

        assert outcome.reopened is False


class TestSettlement:
    """E2 — nothing prevented cluster evaluation consuming a conversation
    whose CSAT had not landed, which enters confidence as neutral quality
    for conversations that were in fact rated badly."""

    def test_a_just_ended_conversation_is_not_settled(self) -> None:
        assert not is_settled(_inputs(ended_at=NOW - timedelta(hours=1)))

    def test_it_settles_after_the_window(self) -> None:
        assert is_settled(_inputs(ended_at=NOW - timedelta(hours=DEFAULT_SETTLE_HOURS + 1)))

    def test_csat_settles_it_immediately(self) -> None:
        """The thing the window was waiting for has arrived; waiting
        further would delay learning for no gain."""
        assert is_settled(_inputs(ended_at=NOW - timedelta(minutes=5), csat_score=4))

    def test_an_open_conversation_is_never_settled(self) -> None:
        assert not is_settled(_inputs(status="open", ended_at=None))

    def test_the_outcome_carries_its_own_settledness(self) -> None:
        """So a consumer cannot forget to ask — an unsettled outcome is
        provisional, not wrong, and anything learning from it must wait."""
        provisional = derive(_inputs(ended_at=NOW - timedelta(hours=1)))
        final = derive(_inputs(ended_at=NOW - timedelta(hours=DEFAULT_SETTLE_HOURS + 1)))

        assert provisional.settled is False
        assert final.settled is True


class TestHandlingTime:
    def test_it_is_the_span_from_start_to_end(self) -> None:
        assert derive(_inputs()).handling_seconds == 3600

    def test_an_unfinished_conversation_has_none(self) -> None:
        assert derive(_inputs(status="open", ended_at=None)).handling_seconds is None

    def test_an_end_before_the_start_is_refused_rather_than_negative(self) -> None:
        """Clock skew and bad imports exist; a negative handling time would
        travel into every average that reads it."""
        assert derive(_inputs(ended_at=STARTED - timedelta(hours=1))).handling_seconds is None
