"""The one place knowledge becomes authoritative.

A single chokepoint, pure, returning every reason it refused rather than the
first. An admin who fixes one problem and is told about the next one is an
admin who stops trusting the tool; and a gate that returns "no" without saying
what would make it "yes" gets worked around.

The rule that is not configurable: a sensitive type — price, SLA term, policy
parameter — always requires explicit human approval, whatever the source's
trust level and whatever an extraction's confidence. A trusted sender is a
statement about a mailbox, and mailboxes are compromised. Nothing may make this
looser; configuration may only make other types stricter.

This is the first consumer of ``SENSITIVE_RECORD_TYPES``, which has been a
declaration with no reader since M2A. Adding a record type now has a
consequence: an unclassified type is treated as low-risk.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from blinkengage.domain.brain.conflicts import BLOCKING_VERDICTS, ConflictVerdict
from blinkengage.domain.knowledge_records import (
    SENSITIVE_RECORD_TYPES,
    KnowledgeAccessLevel,
    KnowledgeRecordType,
)

#: Permission required to publish anything at all.
PUBLISH_PERMISSION = "knowledge_records.publish"
#: Additional permission for ``RESTRICTED`` material.
APPROVE_RESTRICTED_PERMISSION = "knowledge_records.approve_restricted"


class PublicationRefusal(StrEnum):
    """Why the gate said no. Every applicable reason is returned."""

    #: Nothing records where this came from. Provenance is not optional: a
    #: price nobody can trace is a price nobody can defend in an audit.
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    #: No named human accepted responsibility for it.
    MISSING_APPROVER = "MISSING_APPROVER"
    #: The caller lacks ``knowledge_records.publish``.
    MISSING_PERMISSION = "MISSING_PERMISSION"
    #: ``RESTRICTED`` needs its own permission on top.
    RESTRICTED_REQUIRES_APPROVAL_PERMISSION = "RESTRICTED_REQUIRES_APPROVAL_PERMISSION"
    #: A sensitive type reached the gate without human approval.
    SENSITIVE_REQUIRES_HUMAN_APPROVAL = "SENSITIVE_REQUIRES_HUMAN_APPROVAL"
    #: A contradiction with existing knowledge is unresolved.
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"


@dataclass(frozen=True, slots=True)
class PublicationCandidate:
    """A draft record proposed for publication, with its paperwork."""

    company_id: uuid.UUID
    record_type: KnowledgeRecordType
    access_level: KnowledgeAccessLevel
    #: Where this came from — an admin, an email, a document, an inference.
    #: Any non-empty origin satisfies the gate; the vocabulary lives in
    #: ``CreatedFrom`` and is not restated here.
    provenance: str | None = None
    #: The human who accepted responsibility. Not the AI, ever.
    approved_by_user_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    #: Result of :func:`detect_conflict` against current knowledge.
    conflict: ConflictVerdict = ConflictVerdict.NO_CONFLICT


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    """Whether it may be published, and everything wrong with it if not."""

    permitted: bool
    refusals: tuple[PublicationRefusal, ...] = ()


def publication_gate(
    candidate: PublicationCandidate,
    *,
    granted_permissions: frozenset[str],
) -> PublicationDecision:
    """May this become authoritative?

    Permissions are passed in from ``AuthContext`` rather than read from the
    candidate. Nothing about the material being published can grant the right
    to publish it — the same rule that keeps an ingested document from
    escalating its own privileges.
    """
    refusals: list[PublicationRefusal] = []

    if not (candidate.provenance or "").strip():
        refusals.append(PublicationRefusal.MISSING_PROVENANCE)

    approved_by_human = candidate.approved_by_user_id is not None
    if not approved_by_human or candidate.approved_at is None:
        refusals.append(PublicationRefusal.MISSING_APPROVER)

    if PUBLISH_PERMISSION not in granted_permissions:
        refusals.append(PublicationRefusal.MISSING_PERMISSION)

    if (
        candidate.access_level is KnowledgeAccessLevel.RESTRICTED
        and APPROVE_RESTRICTED_PERMISSION not in granted_permissions
    ):
        refusals.append(PublicationRefusal.RESTRICTED_REQUIRES_APPROVAL_PERMISSION)

    # Stated separately from MISSING_APPROVER even though the condition
    # overlaps: an operator reading the refusal for a price needs to know the
    # requirement is categorical, not that they forgot a field.
    if candidate.record_type in SENSITIVE_RECORD_TYPES and not approved_by_human:
        refusals.append(PublicationRefusal.SENSITIVE_REQUIRES_HUMAN_APPROVAL)

    if candidate.conflict in BLOCKING_VERDICTS:
        refusals.append(PublicationRefusal.UNRESOLVED_CONFLICT)

    return PublicationDecision(permitted=not refusals, refusals=tuple(refusals))


__all__ = [
    "APPROVE_RESTRICTED_PERMISSION",
    "PUBLISH_PERMISSION",
    "PublicationCandidate",
    "PublicationDecision",
    "PublicationRefusal",
    "publication_gate",
]
