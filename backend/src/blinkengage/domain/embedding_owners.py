"""Who may write an embedding for which owner.

``embeddings`` is **shared indexing infrastructure**, not a table owned by
the Knowledge context. Three contexts put vectors in it — knowledge
chunks, memory facts, and later Learning's cluster centroids — and while
it was informally treated as Knowledge's, the platform's central invariant
was quietly false: "``MemoryManager`` is the only writer of memory" did
not hold for memory *vectors*, which a Knowledge-context service wrote.
The exclusive-writer guard did not catch it because it watches memory
repositories, not this table.

The fix is not to give the table to a domain context — every choice there
is wrong, because it is genuinely shared. It is to treat it like the
outbox: infrastructure with an explicit, enforced writer per owner type.

Adding an owner type here is the reviewable act, and a guard test asserts
that only the registered module writes each one.
"""

from __future__ import annotations

from types import MappingProxyType

#: ``owner_type`` -> the single module permitted to write it.
#:
#: Paths are relative to ``src/blinkengage`` so the guard can compare them
#: against what it finds by walking the tree.
EMBEDDING_WRITERS: MappingProxyType[str, str] = MappingProxyType(
    {
        "KNOWLEDGE_CHUNK": "application/services/embedding_service.py",
        # Declared and not yet written by anything. Listed so the intent is
        # reviewable now rather than improvised later: when memory facts
        # gain vectors, only the Memory context may write them.
        "MEMORY_FACT": "application/services/memory_manager.py",
    }
)


def writer_for(owner_type: str) -> str | None:
    return EMBEDDING_WRITERS.get(owner_type)


def is_registered(owner_type: str) -> bool:
    return owner_type in EMBEDDING_WRITERS


__all__ = ["EMBEDDING_WRITERS", "is_registered", "writer_for"]
