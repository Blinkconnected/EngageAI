"""Only the registered writer may write an owner type's vectors.

**O1 from the architecture freeze review.** ``embeddings`` is shared
indexing infrastructure — knowledge chunks, memory facts and later
Learning's cluster centroids all live in it — but it was informally
treated as the Knowledge context's table. That made the platform's central
invariant quietly false: "``MemoryManager`` is the only writer of memory"
did not hold for memory *vectors*, which a Knowledge-context service
wrote, and the exclusive-writer guard did not notice because it watches
memory repositories rather than this table.

Giving the table to a domain context is wrong in every direction, because
it is genuinely shared. So it is treated like the outbox: infrastructure,
with an explicit writer per owner type, enforced here.

Static rather than behavioural, for the reason
``test_ownership_is_the_only_writer.py`` already gives: a behavioural test
covers the paths somebody thought to write, and this covers the ones
nobody has written yet.
"""

import ast
import pathlib

import pytest

from blinkengage.domain.embedding_owners import is_registered, writer_for

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"

#: Methods that put a vector into, or take one out of, the shared table.
WRITE_METHODS: frozenset[str] = frozenset({"upsert", "delete_for_owners", "delete_stale_models"})

#: Modules allowed to call them, and why.
#:
#: Note this is a *smaller* list than the set of registered owner types:
#: ``MEMORY_FACT`` is registered so the intent is reviewable, but nothing
#: writes memory vectors yet. That asymmetry is deliberate — the registry
#: records who *may*, this records who *does*.
ALLOWED_CALLERS: dict[str, str] = {
    "application/services/embedding_service.py": (
        "The knowledge-chunk indexer. Writes KNOWLEDGE_CHUNK vectors only."
    ),
    "application/services/memory_erasure_service.py": (
        "Deletes a subject's vectors during erasure. Deletion is not "
        "authorship: erasure must be able to remove any owner type, or a "
        "deletion request would be answerable only for the contexts that "
        "happened to be wired."
    ),
}


def _python_files() -> list[pathlib.Path]:
    return sorted(SRC.rglob("*.py"))


def _writes_embeddings(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in WRITE_METHODS:
        return False
    target = ast.unparse(func.value).lower()
    return "embedding" in target


def _writers() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if _writes_embeddings(node):
                found.setdefault(path.relative_to(SRC).as_posix(), node.lineno)
    return found


class TestOnlyRegisteredWritersTouchTheSharedIndex:
    def test_every_writer_is_on_the_list(self) -> None:
        unexpected = {
            where: line for where, line in _writers().items() if where not in ALLOWED_CALLERS
        }

        assert not unexpected, (
            "These write the shared embeddings table without being registered:\n"
            + "\n".join(f"  {where}  (line {line})" for where, line in sorted(unexpected.items()))
            + "\n\nEmbeddings are shared infrastructure with one writer per owner type "
            "(domain/embedding_owners.py). Register the owner type and add the caller "
            "here, or route the write through the context that owns that owner type."
        )

    def test_the_list_has_not_gone_stale(self) -> None:
        writers = _writers()
        vanished = sorted(where for where in ALLOWED_CALLERS if where not in writers)

        assert (
            not vanished
        ), f"ALLOWED_CALLERS names modules that no longer write embeddings: {vanished}"


class TestTheRegistryIsHonest:
    def test_every_owner_type_used_in_code_is_registered(self) -> None:
        """An owner type written but not registered is a vector nobody
        owns — which is how memory vectors ended up authored by the
        Knowledge context in the first place."""
        from blinkengage.infrastructure.database.models.embedding import (
            OWNER_KNOWLEDGE_CHUNK,
        )
        from blinkengage.infrastructure.database.models.memory import OWNER_MEMORY_FACT

        for owner_type in (OWNER_KNOWLEDGE_CHUNK, OWNER_MEMORY_FACT):
            assert is_registered(owner_type), f"{owner_type} has no registered writer"

    def test_memory_vectors_are_the_memory_managers_to_write(self) -> None:
        """The specific invariant O1 restores: if memory facts gain
        vectors, the Memory Manager writes them — not the knowledge
        indexer that happens to own the table today."""
        assert writer_for("MEMORY_FACT") == "application/services/memory_manager.py"

    def test_knowledge_chunks_belong_to_the_indexer(self) -> None:
        assert writer_for("KNOWLEDGE_CHUNK") == "application/services/embedding_service.py"

    def test_an_unregistered_owner_type_has_no_writer(self) -> None:
        assert writer_for("CLUSTER_CENTROID") is None
        assert not is_registered("CLUSTER_CENTROID")


class TestTheGuardActuallyFires:
    @pytest.mark.parametrize(
        ("label", "source"),
        [
            (
                "a repository held on self",
                "async def sneaky(self):\n    await self._embeddings.upsert(company_id=1)\n",
            ),
            (
                "a locally constructed repository",
                "async def sneaky(session):\n"
                "    await EmbeddingRepository(session).delete_for_owners(company_id=1)\n",
            ),
        ],
    )
    def test_a_planted_writer_is_detected(self, label: str, source: str) -> None:
        tree = ast.parse(source)

        assert any(
            _writes_embeddings(node) for node in ast.walk(tree)
        ), f"the guard would not have noticed a writer using {label}"

    def test_reading_and_other_repositories_are_not_flagged(self) -> None:
        source = (
            "async def innocent(self):\n"
            "    await self._embeddings.coverage(company_id=1, model='m')\n"
            "    await self._facts.upsert(company_id=1)\n"
        )
        tree = ast.parse(source)

        assert not any(_writes_embeddings(node) for node in ast.walk(tree))
