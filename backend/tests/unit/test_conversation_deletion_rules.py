"""The rules that make a deletion accountable rather than merely possible.

Tested as rules, away from the database, because that is what they are:
each one exists to stop a specific bad outcome, and each of those
outcomes is nameable.
"""

from uuid import uuid4

import pytest

from blinkengage.domain.conversation_deletion import (
    MIN_REASON_LENGTH,
    DeletionRequestStatus,
    DeletionRuleViolation,
    ensure_decidable,
    ensure_not_self_approval,
    validate_reason,
)


class TestTheReason:
    def test_a_reason_survives_intact(self) -> None:
        assert validate_reason("Customer asked us to remove their data") == (
            "Customer asked us to remove their data"
        )

    def test_whitespace_is_collapsed_before_it_is_measured(self) -> None:
        """A field of spaces is an empty field.

        Measuring the raw string would let somebody past the minimum by
        holding down the space bar, and the reason is the only thing the
        approver will have to go on.
        """
        with pytest.raises(DeletionRuleViolation) as caught:
            validate_reason(" " * (MIN_REASON_LENGTH + 20))

        assert caught.value.code == "reason_too_short"

    def test_a_one_word_reason_is_refused(self) -> None:
        # "spam" and "delete" explain nothing to somebody reading this
        # next week, which is when it will be read.
        with pytest.raises(DeletionRuleViolation) as caught:
            validate_reason("spam")

        assert caught.value.code == "reason_too_short"

    def test_an_essay_is_refused_too(self) -> None:
        with pytest.raises(DeletionRuleViolation) as caught:
            validate_reason("x " * 3000)

        assert caught.value.code == "reason_too_long"

    def test_the_message_says_what_to_do_about_it(self) -> None:
        with pytest.raises(DeletionRuleViolation) as caught:
            validate_reason("no")

        # The person who hit this has to be able to fix it from the text
        # alone — they are looking at a form, not at logs.
        assert str(caught.value) != caught.value.code
        assert str(MIN_REASON_LENGTH) in str(caught.value)


class TestDecidingOnce:
    def test_a_pending_request_can_be_decided(self) -> None:
        ensure_decidable(DeletionRequestStatus.PENDING)

    @pytest.mark.parametrize(
        "status", [DeletionRequestStatus.APPROVED, DeletionRequestStatus.REJECTED]
    )
    def test_a_decided_request_cannot_be_decided_again(self, status: DeletionRequestStatus) -> None:
        """Two administrators open the same queue and both approve.

        Without this the second approval deletes an already-deleted
        conversation and writes a second audit entry — two records of one
        deletion, different timestamps, different names against it.
        """
        with pytest.raises(DeletionRuleViolation) as caught:
            ensure_decidable(status)

        assert caught.value.code == "already_decided"
        assert status.value in str(caught.value)


class TestWhoDecides:
    def test_somebody_else_may_decide(self) -> None:
        ensure_not_self_approval(requested_by_user_id=uuid4(), actor_user_id=uuid4())

    def test_the_requester_may_not_decide_their_own(self) -> None:
        """Not a security boundary — anybody who can approve can also
        delete outright, and this cannot stop them. It is about the
        record: an approval showing one name on both halves is ceremony.
        """
        same = uuid4()

        with pytest.raises(DeletionRuleViolation) as caught:
            ensure_not_self_approval(requested_by_user_id=same, actor_user_id=same)

        assert caught.value.code == "self_approval"

    def test_an_orphaned_request_is_still_decidable(self) -> None:
        """The requester's account was deleted, so the request has no
        author. It must not become permanently stuck: a `None == None`
        comparison would otherwise read as self-approval and leave a row
        nobody can ever clear."""
        ensure_not_self_approval(requested_by_user_id=None, actor_user_id=None)
