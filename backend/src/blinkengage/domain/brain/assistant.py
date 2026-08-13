"""The admin says something true; the platform turns it into a proposal.

"We changed enterprise pricing to 15 JOD from September" is a sentence. A
``KnowledgeRecord`` is a typed row with a subject key, a schema-validated
attribute set, an effective period and a named approver. The assistant's job is
the distance between those two, and its output is always a **proposal** —
never a publication.

The asymmetry that makes this usable: proposing is cheap, publishing is
confirmed. The admin's conversation stays fluid, and the moment anything would
become official a human says yes. There is no configuration, trust level or
confidence tier that collapses the two.

No ``knowledge_proposals`` table. ``DRAFT`` already carries exactly these
semantics — created, not authoritative, never answers a question — and a second
store for the same state would mean two places to ask whether something is
official.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from blinkengage.domain.brain.conflicts import ConflictVerdict
from blinkengage.domain.brain.vocabulary import KnowledgeAuthority
from blinkengage.domain.knowledge_records import KnowledgeAccessLevel, KnowledgeRecordType


@dataclass(frozen=True, slots=True)
class KnowledgeProposal:
    """What the assistant produced, and what it still does not know.

    ``missing_fields`` is why this is a proposal rather than a draft record: an
    assistant that silently defaulted an effective date would produce a
    publishable row from an incomplete sentence. Listing what is missing is
    what lets the assistant ask the one useful question — "from which date?" —
    instead of guessing or refusing.
    """

    company_id: uuid.UUID
    record_type: KnowledgeRecordType
    subject_label: str
    attributes: Mapping[str, str] = field(default_factory=dict)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    access_level: KnowledgeAccessLevel = KnowledgeAccessLevel.PUBLIC_TO_AI
    #: Who said it, and where. Carried from the turn that produced it.
    provenance: str | None = None
    #: Fields the assistant could not fill from what the admin said.
    missing_fields: tuple[str, ...] = ()
    #: Result of comparing this against current knowledge.
    conflict: ConflictVerdict = ConflictVerdict.NO_CONFLICT

    @property
    def authority(self) -> KnowledgeAuthority:
        """Always ``PROPOSAL``.

        A property rather than a field so no construction path can set it to
        anything else. Authority is earned at ``publication_gate``, and an
        object that could claim it on the way in would make the gate advisory.
        """
        return KnowledgeAuthority.PROPOSAL

    @property
    def is_complete(self) -> bool:
        """Nothing left to ask the admin about."""
        return not self.missing_fields


def proposal_requires_approval(proposal: KnowledgeProposal) -> bool:
    """Always true.

    Stated as a function, and tested, because "obviously the AI cannot publish
    on its own" is exactly the kind of obvious thing that acquires an exception
    for a low-risk type on a busy afternoon. There is no argument that makes
    this false, so the signature does not offer one.
    """
    return True


__all__ = ["KnowledgeProposal", "proposal_requires_approval"]
