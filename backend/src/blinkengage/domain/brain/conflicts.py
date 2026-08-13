"""Does this candidate contradict what the company already says?

Read-time contradiction is already handled: two overlapping ACTIVE records
raise ``OverlappingRecordError`` and resolution never picks between them. What
was missing is the question asked *before* anything is written — "the email
says 18 JOD, the record says 15" — because that is what makes an admin review a
decision rather than a diff discovered afterwards.

This module classifies. It never decides. A ``VALUE_CONFLICT`` is surfaced with
both values, both periods and both provenances, and a human resolves it;
silently choosing is how the platform's most auditable statement becomes its
least trustworthy.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from blinkengage.domain.knowledge_records import KnowledgeRecordType


class ConflictVerdict(StrEnum):
    """The relationship between a candidate and the current record."""

    #: Nothing authoritative covers this subject. A first statement.
    NO_CONFLICT = "NO_CONFLICT"
    #: Same subject, same period, same values. A restatement — publishing it
    #: again would create a version that changes nothing.
    IDENTICAL = "IDENTICAL"
    #: Same subject, overlapping period, different values. A human decides.
    VALUE_CONFLICT = "VALUE_CONFLICT"
    #: Same values, but the periods overlap in a way that would leave two
    #: records covering one instant. A data problem even without disagreement.
    PERIOD_CONFLICT = "PERIOD_CONFLICT"
    #: Strictly later than the current record. A clean scheduled change, which
    #: supersession already models.
    SUPERSEDES = "SUPERSEDES"


class CrossTenantComparisonError(Exception):
    """Two companies' knowledge was compared.

    Never a legitimate case, so it raises rather than returning a verdict. A
    comparison that silently answered ``NO_CONFLICT`` for a record belonging to
    another company would be a tenant leak wearing the costume of a valid
    result.
    """

    def __init__(self, left: uuid.UUID, right: uuid.UUID) -> None:
        super().__init__(f"cross-tenant knowledge comparison: {left} vs {right}")
        self.left = left
        self.right = right


@dataclass(frozen=True, slots=True)
class KnowledgeClaim:
    """A statement about one subject over one period.

    Deliberately not the ORM row. Conflict detection has to run on a candidate
    extracted from an email that has never been written anywhere, so the input
    cannot be a persisted record.

    ``attributes`` values are compared as given. Callers pass the *validated*
    attributes from ``validate_attributes`` so that ``"180"`` and ``"180.00"``
    have already been reconciled — comparing raw user input here would report
    a conflict between a price and itself.
    """

    company_id: uuid.UUID
    record_type: KnowledgeRecordType
    subject_key: str
    attributes: Mapping[str, str] = field(default_factory=dict)
    effective_from: datetime | None = None
    effective_until: datetime | None = None


def _overlaps(left: KnowledgeClaim, right: KnowledgeClaim) -> bool:
    """Do the two effective periods share any instant?

    Half-open ``[from, until)`` throughout, matching the knowledge records
    module: a record ending exactly where the next begins does not overlap it,
    which is what makes a scheduled change clean rather than a contradiction.
    ``None`` is unbounded in its direction.
    """
    left_from, left_until = left.effective_from, left.effective_until
    right_from, right_until = right.effective_from, right.effective_until

    if left_until is not None and right_from is not None and left_until <= right_from:
        return False
    return not (right_until is not None and left_from is not None and right_until <= left_from)


def detect_conflict(candidate: KnowledgeClaim, existing: KnowledgeClaim | None) -> ConflictVerdict:
    """Classify ``candidate`` against the record it would replace.

    ``existing`` is the currently-resolvable record for the same subject, or
    ``None`` when the company has never said anything about it.
    """
    if existing is None:
        return ConflictVerdict.NO_CONFLICT

    if candidate.company_id != existing.company_id:
        raise CrossTenantComparisonError(candidate.company_id, existing.company_id)

    if (
        candidate.record_type is not existing.record_type
        or candidate.subject_key != existing.subject_key
    ):
        return ConflictVerdict.NO_CONFLICT

    same_values = dict(candidate.attributes) == dict(existing.attributes)

    if not _overlaps(candidate, existing):
        # Disjoint periods. Later is a scheduled change; earlier is a
        # backfill, which supersession also models — the chain is ordered by
        # period, not by insertion.
        return ConflictVerdict.SUPERSEDES

    if same_values:
        # Overlapping and identical. Harmless as an assertion, but publishing
        # it would leave two rows covering one instant, which the resolution
        # contract treats as a contradiction.
        return (
            ConflictVerdict.IDENTICAL
            if candidate.effective_from == existing.effective_from
            and candidate.effective_until == existing.effective_until
            else ConflictVerdict.PERIOD_CONFLICT
        )

    return ConflictVerdict.VALUE_CONFLICT


#: Verdicts that must not reach publication without a human resolving them.
BLOCKING_VERDICTS: frozenset[ConflictVerdict] = frozenset(
    {ConflictVerdict.VALUE_CONFLICT, ConflictVerdict.PERIOD_CONFLICT}
)


__all__ = [
    "BLOCKING_VERDICTS",
    "ConflictVerdict",
    "CrossTenantComparisonError",
    "KnowledgeClaim",
    "detect_conflict",
]
