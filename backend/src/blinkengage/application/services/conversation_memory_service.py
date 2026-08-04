"""Conversation Memory — the working-memory store.

See ``docs/architecture/memory-platform.md``.

**Redis with a TTL, not PostgreSQL.** This is the "fine to drop if nobody
is listening" tier that ``event-bus.md`` already distinguishes from
durable events, and a row per turn per conversation in PostgreSQL would
buy durability for something worthless once the conversation ends. The
platform already runs Redis, the tests already stand in ``fakeredis`` for
it, and the access pattern — read whole, write whole, expire — is exactly
what a key-value store is for.

The TTL is the design, not a detail. Working memory that outlived its
conversation would be a growing store of customer content with no
retention story and nothing that ever deletes it; a TTL means the default
outcome is deletion and remembering requires a deliberate act
(distillation into evidence-backed facts, which is a later stage).

**Tenant isolation is in the key.** ``company:{id}:conversation:{id}:``
is the same namespacing the realtime publisher already uses, and it means
a lookup for the wrong company cannot return another company's value even
if a conversation id were guessed — the company id is part of the key, not
a filter applied to the result.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

import orjson
from redis.asyncio import Redis

from blinkengage.domain.conversation_memory import (
    WorkingMemory,
    from_payload,
    to_payload,
)

logger = logging.getLogger(__name__)

#: How long working memory survives without a turn. Long enough that a
#: customer who steps away for lunch returns to a conversation that still
#: knows their order number; short enough that an abandoned conversation
#: is not held indefinitely.
DEFAULT_TTL_SECONDS = 60 * 60 * 12


def working_memory_key(*, company_id: UUID, conversation_id: UUID) -> str:
    return f"company:{company_id}:conversation:{conversation_id}:memory"


class ConversationMemoryService:
    """Reads and writes one conversation's working memory.

    Deliberately **not** routed through ``MemoryManager``. The Manager is
    the exclusive writer of *facts* — rows with evidence, confidence and a
    lifecycle — and working memory is none of those things. Forcing it
    through the same door would either weaken the fact contract or dress
    working state up as something it is not; the honest boundary is that
    these are two stores with two contracts, and the crossing between them
    is distillation.
    """

    def __init__(self, redis: Redis, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, *, company_id: UUID, conversation_id: UUID) -> WorkingMemory:
        """The conversation's working memory, or an empty one.

        Never ``None``. An absent key means a conversation that has not
        accumulated anything yet, which is the ordinary state at turn one —
        making every caller handle ``None`` would be making them handle the
        common case as an exception.
        """
        raw = await self._redis.get(
            working_memory_key(company_id=company_id, conversation_id=conversation_id)
        )
        if not raw:
            return WorkingMemory(conversation_id=conversation_id, company_id=company_id)

        try:
            payload = orjson.loads(raw)
            memory = from_payload(payload)
        except (orjson.JSONDecodeError, KeyError, ValueError, TypeError):
            # A corrupt or unreadable value must not take the conversation
            # down. Working memory is an optimisation; the conversation
            # works without it, slightly less informed.
            logger.warning(
                "conversation_working_memory_unreadable",
                extra={
                    "company_id": str(company_id),
                    "conversation_id": str(conversation_id),
                },
            )
            return WorkingMemory(conversation_id=conversation_id, company_id=company_id)

        if memory.company_id != company_id:
            # Defence in depth. The company is already in the key, so this
            # is unreachable through this service — but the value carries
            # its own tenant and disagreeing with the key is the signature
            # of a bug worth refusing rather than serving.
            logger.error(
                "conversation_working_memory_tenant_mismatch",
                extra={
                    "company_id": str(company_id),
                    "conversation_id": str(conversation_id),
                },
            )
            return WorkingMemory(conversation_id=conversation_id, company_id=company_id)

        return memory

    async def put(self, memory: WorkingMemory) -> WorkingMemory:
        """Stores working memory and refreshes its TTL.

        Written whole rather than field by field. The structure is small
        and bounded by construction, and a read-modify-write of the whole
        value is far easier to reason about than partial updates that can
        interleave — two agents with the same conversation open is a normal
        state here.
        """
        stamped = WorkingMemory(
            conversation_id=memory.conversation_id,
            company_id=memory.company_id,
            entities=memory.entities,
            open_questions=memory.open_questions,
            commitments=memory.commitments,
            stated_preferences=memory.stated_preferences,
            summary=memory.summary,
            turn_count=memory.turn_count,
            updated_at=datetime.now(UTC),
            schema_version=memory.schema_version,
        )
        await self._redis.set(
            working_memory_key(
                company_id=stamped.company_id, conversation_id=stamped.conversation_id
            ),
            orjson.dumps(to_payload(stamped)),
            ex=self._ttl,
        )
        return stamped

    async def clear(self, *, company_id: UUID, conversation_id: UUID) -> bool:
        """Drops working memory immediately.

        Called when a conversation closes, and by erasure. The TTL would
        get there eventually; a customer asking to be forgotten should not
        have to wait twelve hours for it.
        """
        removed = await self._redis.delete(
            working_memory_key(company_id=company_id, conversation_id=conversation_id)
        )
        return bool(removed)


__all__ = ["DEFAULT_TTL_SECONDS", "ConversationMemoryService", "working_memory_key"]
