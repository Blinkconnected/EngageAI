"""Ports the Memory Platform depends on but does not own.

Structural ``Protocol``s rather than imports of concrete classes, so the
memory bounded context does not depend on the semantic-retrieval one. An
erasure has to remove a fact's vectors, but *how* vectors are stored is
stage 1's business and may change — a direct import would make a change
there a change here.

``Protocol`` and not ABC, deliberately, and the opposite choice from
``EmbeddingProvider``/``AiProvider``: those are looked up by name from a
config string and need a registry, while this is a collaborator already in
scope at the call site. Structural typing is right when the caller holds
the object and wrong when it has to find it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class SupportsOwnerDeletion(Protocol):
    """Anything that can drop rows belonging to a deleted owner.

    Satisfied by ``EmbeddingRepository``. Named for the capability rather
    than the class so a second store with the same obligation — a future
    graph-edge table, say — can be handed to erasure without widening
    anything.
    """

    async def delete_for_owners(
        self, *, company_id: UUID, owner_type: str, owner_ids: Sequence[UUID]
    ) -> int: ...


@runtime_checkable
class SupportsFactRecompute(Protocol):
    """The Memory Manager, from erasure's point of view.

    Erasure needs exactly one thing from the Manager — recompute a fact
    whose evidence has changed underneath it — and asking for only that
    keeps the dependency honest: erasure cannot record, confirm, suppress
    or archive through this, because those methods are not on it.
    """

    # `Any` rather than the concrete row type: naming `MemoryFact` here
    # would make this domain module import an infrastructure one, which is
    # the dependency this port exists to avoid. Parameter types in a
    # Protocol are contravariant, so `object` would also refuse every real
    # implementation.
    async def recompute(self, *, fact: Any, now: Any | None = None) -> Any: ...


@runtime_checkable
class ErasureParticipant(Protocol):
    """A context that holds data about a subject and must clear it.

    Erasure was previously complete only because Memory was the only
    context holding subject data. The moment Learning exists it will hold
    observations, cluster memberships and candidates referencing the same
    customer, and an ``ErasureReport`` that did not include them would be
    a document asserting complete deletion while four tables still held
    the subject — the report is described as the thing somebody forwards
    to a regulator.

    So erasure is a **fan-out with acknowledgement**, and a participant
    that cannot confirm is a failure rather than a silence. Each context
    erases its own store, which is the same rule that keeps
    ``MemoryManager`` the only writer of memory.
    """

    #: Stable identifier used in the report, so a partial erasure names
    #: which context did not finish.
    participant_name: str

    async def erase_subject(
        self, *, company_id: UUID, subject_type: str, subject_id: UUID
    ) -> dict[str, int]:
        """Remove everything held about this subject. Returns counts."""
        ...


__all__ = ["ErasureParticipant", "SupportsFactRecompute", "SupportsOwnerDeletion"]
