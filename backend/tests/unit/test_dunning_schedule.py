"""The dunning schedule — pure date arithmetic, no database.

The whole point of ``domain/collections.py`` being framework-free is
that "the customer says they got two final notices" is answerable here,
in milliseconds, rather than by reading a production log.
"""

from datetime import date

from blinkengage.domain.collections import (
    DEFAULT_DUNNING_POLICY,
    BillingStatus,
    DunningStage,
    DunningStep,
    next_stage_date,
    stages_due,
    status_for,
)

DUE = date(2026, 6, 1)
NOTHING: frozenset[DunningStage] = frozenset()


class TestStagesDue:
    def test_the_first_notice_goes_out_before_the_due_date(self) -> None:
        """A customer warned three days early usually pays. One first
        contacted a week late has already lost the invoice in an inbox."""
        due = stages_due(due_date=DUE, today=date(2026, 5, 29), already_sent=NOTHING)
        assert [step.stage for step in due] == [DunningStage.UPCOMING]

    def test_nothing_is_owed_before_the_sequence_starts(self) -> None:
        assert stages_due(due_date=DUE, today=date(2026, 5, 20), already_sent=NOTHING) == []

    def test_a_stage_already_sent_is_never_sent_again(self) -> None:
        due = stages_due(
            due_date=DUE,
            today=date(2026, 6, 1),
            already_sent=frozenset({DunningStage.UPCOMING}),
        )
        assert [step.stage for step in due] == [DunningStage.DUE_TODAY]

    def test_a_missed_window_catches_up_rather_than_skipping(self) -> None:
        """If the sweep is down for a week, the notices it missed still
        go out. Skipping them would land the suspension at the end of
        the sequence with no warnings behind it — which is precisely the
        thing a customer would dispute, and would be right to."""
        due = stages_due(due_date=DUE, today=date(2026, 6, 10), already_sent=NOTHING)

        assert [step.stage for step in due] == [
            DunningStage.UPCOMING,
            DunningStage.DUE_TODAY,
            DunningStage.FIRST_NOTICE,
            DunningStage.SECOND_NOTICE,
        ]

    def test_catch_up_preserves_policy_order(self) -> None:
        """A caller sending them in the order returned tells a coherent
        story, even when catching up."""
        due = stages_due(due_date=DUE, today=date(2026, 7, 1), already_sent=NOTHING)
        offsets = [step.offset_days for step in due]
        assert offsets == sorted(offsets)

    def test_exactly_one_step_suspends_and_it_is_the_last(self) -> None:
        suspending = [step for step in DEFAULT_DUNNING_POLICY if step.suspends]
        assert len(suspending) == 1
        assert suspending[0] is DEFAULT_DUNNING_POLICY[-1]
        assert suspending[0].stage is DunningStage.SUSPENDED

    def test_suspension_never_precedes_the_net_21_window(self) -> None:
        """The invoice engine issues on Net 21. Suspending before the
        customer has had the full payment window would be suspending
        somebody who is not yet late."""
        step = next(s for s in DEFAULT_DUNNING_POLICY if s.suspends)
        assert step.offset_days >= 21

    def test_suspension_fires_only_on_its_day(self) -> None:
        before = stages_due(
            due_date=DUE,
            today=date(2026, 6, 21),
            already_sent=frozenset(DunningStage) - {DunningStage.SUSPENDED},
        )
        assert before == []
        on_the_day = stages_due(
            due_date=DUE,
            today=date(2026, 6, 22),
            already_sent=frozenset(DunningStage) - {DunningStage.SUSPENDED},
        )
        assert [step.stage for step in on_the_day] == [DunningStage.SUSPENDED]

    def test_a_custom_policy_is_honoured(self) -> None:
        aggressive = (
            DunningStep(DunningStage.DUE_TODAY, 0),
            DunningStep(DunningStage.SUSPENDED, 1, suspends=True),
        )
        due = stages_due(
            due_date=DUE, today=date(2026, 6, 2), already_sent=NOTHING, policy=aggressive
        )
        assert [step.stage for step in due] == [DunningStage.DUE_TODAY, DunningStage.SUSPENDED]


class TestNextStageDate:
    def test_reports_when_the_next_notice_is_owed(self) -> None:
        assert next_stage_date(due_date=DUE, already_sent=NOTHING) == date(2026, 5, 29)

    def test_reports_the_suspension_date_once_the_rest_are_sent(self) -> None:
        """What a billing dashboard shows as "suspends on ..." — the date
        a customer most wants and the one hardest to derive by hand."""
        sent = frozenset(DunningStage) - {DunningStage.SUSPENDED}
        assert next_stage_date(due_date=DUE, already_sent=sent) == date(2026, 6, 22)

    def test_returns_none_when_the_sequence_is_exhausted(self) -> None:
        assert next_stage_date(due_date=DUE, already_sent=frozenset(DunningStage)) is None


class TestStatusPrecedence:
    def test_suspension_outranks_everything(self) -> None:
        assert (
            status_for(has_overdue=False, has_open=False, suspended=True)
            is BillingStatus.PAYMENT_SUSPENDED
        )

    def test_overdue_outranks_merely_open(self) -> None:
        assert (
            status_for(has_overdue=True, has_open=True, suspended=False)
            is BillingStatus.PAYMENT_OVERDUE
        )

    def test_an_open_invoice_that_is_not_late_is_payment_due(self) -> None:
        assert (
            status_for(has_overdue=False, has_open=True, suspended=False)
            is BillingStatus.PAYMENT_DUE
        )

    def test_nothing_owed_is_active(self) -> None:
        assert (
            status_for(has_overdue=False, has_open=False, suspended=False) is BillingStatus.ACTIVE
        )
