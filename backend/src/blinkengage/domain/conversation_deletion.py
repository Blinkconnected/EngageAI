"""Deleting a conversation is a request, not a command.

A conversation is the record of what a company said to a customer. It is
evidence in a dispute, the input to every report, and in regulated
industries something a company is obliged to keep. Letting whoever is
holding it remove it — quietly, alone, with no record of why — is the
one destructive action in this product that nobody should be able to
take by themselves.

So an agent *asks*. Somebody who can already delete conversations
decides. Both halves are recorded, both are audited, and the reason is
mandatory in each direction: a deletion nobody can explain later is
indistinguishable from a mistake or a cover-up.

Nothing here touches the database or the clock. The rules are here so
they can be read and tested as rules, and so the service that applies
them cannot quietly disagree with the API that documents them.
"""

from dataclasses import dataclass
from enum import StrEnum

#: Long enough that "delete" or "spam" does not pass, short enough not to
#: be a form somebody abandons. The reason is read by whoever approves,
#: often days later, and by whoever audits the deletion after that.
MIN_REASON_LENGTH = 10

MAX_REASON_LENGTH = 2000


class DeletionRequestStatus(StrEnum):
    """Terminal in two directions, and it never returns to pending.

    A rejected request is not reopened — the requester raises a new one,
    which keeps each decision attached to the reasoning it was made on
    rather than letting one row accumulate a history nobody can read.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DeletionRuleViolation(Exception):
    """A rule was broken. Carries a code the API maps to a status, and a
    sentence the person who broke it can act on."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def validate_reason(reason: str) -> str:
    """The reason, normalised — or a violation explaining what is wrong.

    Whitespace is stripped before measuring, so a field full of spaces is
    an empty field rather than a long one.
    """
    cleaned = " ".join(reason.split())
    if len(cleaned) < MIN_REASON_LENGTH:
        raise DeletionRuleViolation(
            code="reason_too_short",
            message=(
                f"Say why this conversation should be deleted, in at least "
                f"{MIN_REASON_LENGTH} characters. Whoever reviews this will only "
                f"have what you write here."
            ),
        )
    if len(cleaned) > MAX_REASON_LENGTH:
        raise DeletionRuleViolation(
            code="reason_too_long",
            message=f"Keep the reason under {MAX_REASON_LENGTH} characters.",
        )
    return cleaned


def ensure_decidable(status: DeletionRequestStatus) -> None:
    """A request can only be decided once.

    Without this, two administrators opening the same queue both approve,
    and the second approval deletes an already-deleted conversation while
    writing a second audit entry — two records of one deletion, with
    different timestamps and different names against it.
    """
    if status is not DeletionRequestStatus.PENDING:
        raise DeletionRuleViolation(
            code="already_decided",
            message=f"This request has already been {status.value}.",
        )


def ensure_not_self_approval(*, requested_by_user_id: object, actor_user_id: object) -> None:
    """The requester does not decide their own request.

    This is not a security boundary — anybody who can approve can also
    delete a conversation outright, and this rule cannot stop them. It is
    about the record: an approval is only worth keeping if it shows two
    people, and one name on both halves would make the whole step
    ceremony.

    Somebody who genuinely holds the authority and does not want a second
    opinion should delete the conversation directly and be recorded as
    having done exactly that.
    """
    if requested_by_user_id is not None and requested_by_user_id == actor_user_id:
        raise DeletionRuleViolation(
            code="self_approval",
            message=(
                "You cannot decide your own deletion request. Ask another "
                "administrator to review it, or delete the conversation "
                "directly if that is what you intend."
            ),
        )


__all__ = [
    "MAX_REASON_LENGTH",
    "MIN_REASON_LENGTH",
    "DeletionRequestStatus",
    "DeletionRuleViolation",
    "ensure_decidable",
    "ensure_not_self_approval",
    "validate_reason",
]
