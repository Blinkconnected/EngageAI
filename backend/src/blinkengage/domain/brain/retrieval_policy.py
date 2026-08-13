"""What this audience is allowed to have retrieved for it.

Enforced at retrieval, never at generation. Restricted text that reaches the
prompt is one instruction away from disclosure; text that was never fetched is
not. That distinction is the entire security value of this module, and it is
why the filter returns records rather than redacting them later.

Tenant isolation here is a **failure**, not a filter. A record belonging to
another company arriving at this function is a bug in whatever fetched it, and
quietly dropping it would leave that bug in place and unobserved. It raises.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable

from blinkengage.domain.brain.vocabulary import BrainAudience
from blinkengage.domain.knowledge_records import (
    RESOLVABLE_STATES,
    KnowledgeAccessLevel,
    KnowledgeLifecycleState,
)


class CrossTenantAccessError(Exception):
    """A record from another company reached the Brain's retrieval boundary."""

    def __init__(self, expected: uuid.UUID, found: uuid.UUID) -> None:
        super().__init__(f"cross-tenant knowledge access: expected {expected}, got {found}")
        self.expected = expected
        self.found = found


@runtime_checkable
class RetrievableRecord(Protocol):
    """The five fields visibility depends on.

    A structural protocol rather than the ORM model, so this module stays in
    the domain layer and the rules can be tested against a five-line stub
    instead of a database row. The shipped ``KnowledgeRecord`` satisfies it.
    """

    @property
    def company_id(self) -> uuid.UUID: ...

    @property
    def lifecycle_state(self) -> KnowledgeLifecycleState: ...

    @property
    def access_level(self) -> KnowledgeAccessLevel: ...

    @property
    def effective_from(self) -> datetime | None: ...

    @property
    def effective_until(self) -> datetime | None: ...


#: Which access levels each audience may have fetched.
#:
#: ``CUSTOMER`` gets exactly one level. Not "public plus internal where it is
#: only used as a constraint" — that distinction is real, but it belongs to the
#: verifier, which does not exist yet, and encoding it here would grant the
#: access now against an enforcement point that lands later.
AUDIENCE_ACCESS: Mapping[BrainAudience, frozenset[KnowledgeAccessLevel]] = {
    BrainAudience.CUSTOMER: frozenset({KnowledgeAccessLevel.PUBLIC_TO_AI}),
    BrainAudience.INTERNAL_AGENT: frozenset(
        {KnowledgeAccessLevel.PUBLIC_TO_AI, KnowledgeAccessLevel.INTERNAL}
    ),
    BrainAudience.COMPANY_ADMIN: frozenset(KnowledgeAccessLevel),
}

#: Audiences that may see unpublished work.
#:
#: Only the admin assistant, and only because discussing a draft is its whole
#: purpose. A draft was never true; it must not reach a customer or inform an
#: agent's reply to one.
DRAFT_VISIBLE_TO: frozenset[BrainAudience] = frozenset({BrainAudience.COMPANY_ADMIN})


def allowed_access_levels(audience: BrainAudience) -> frozenset[KnowledgeAccessLevel]:
    """The access levels this audience may have retrieved."""
    return AUDIENCE_ACCESS[audience]


def _covers(record: RetrievableRecord, at: datetime) -> bool:
    """Is ``at`` inside the record's half-open effective period?

    This is what actually stops stale knowledge answering as current — not the
    lifecycle state. ``SUPERSEDED`` is resolvable on purpose: publishing a
    price change effective next month supersedes today's record immediately,
    and excluding superseded rows would leave the subject unpriced until the
    change lands. Periods among resolvable states are disjoint by
    construction, because supersession closes the outgoing period exactly
    where the incoming one opens.
    """
    if record.effective_from is not None and at < record.effective_from:
        return False
    return not (record.effective_until is not None and at >= record.effective_until)


def is_visible(
    record: RetrievableRecord,
    *,
    company_id: uuid.UUID,
    audience: BrainAudience,
    at: datetime,
) -> bool:
    """May this audience have this record retrieved for it, at this moment?

    Raises :class:`CrossTenantAccessError` rather than returning ``False`` for
    another company's record: that is a caller bug, and a predicate that
    answers it politely hides one.
    """
    if record.company_id != company_id:
        raise CrossTenantAccessError(company_id, record.company_id)

    if record.access_level not in allowed_access_levels(audience):
        return False

    if record.lifecycle_state is KnowledgeLifecycleState.DRAFT:
        # Drafts ignore the period entirely — an unapproved record has no
        # period during which it was true.
        return audience in DRAFT_VISIBLE_TO

    if record.lifecycle_state not in RESOLVABLE_STATES:
        # ARCHIVED. Withdrawn, and its period is deliberately left intact for
        # the audit trail — so it *can* overlap a later active record, and
        # admitting it would reintroduce exactly the ambiguity the resolution
        # contract exists to prevent.
        return False

    return _covers(record, at)


def filter_visible[R: RetrievableRecord](
    records: Iterable[R],
    *,
    company_id: uuid.UUID,
    audience: BrainAudience,
    at: datetime,
) -> tuple[R, ...]:
    """Every record this audience may have, in the order given."""
    return tuple(
        record
        for record in records
        if is_visible(record, company_id=company_id, audience=audience, at=at)
    )


__all__ = [
    "AUDIENCE_ACCESS",
    "DRAFT_VISIBLE_TO",
    "CrossTenantAccessError",
    "RetrievableRecord",
    "allowed_access_levels",
    "filter_visible",
    "is_visible",
]
