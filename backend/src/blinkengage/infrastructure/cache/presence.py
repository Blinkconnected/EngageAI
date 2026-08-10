"""Agent presence, tracked across connections rather than per socket.

See ``docs/architecture/realtime.md``.

The gateway used to flip ``Agent.status`` to ``OFFLINE`` the instant a
WebSocket closed. That is defensible for a desktop browser tab and wrong
for everything else, in two distinct ways:

1. **A phone disconnects constantly.** Backgrounding the app closes the
   socket, so an agent who locked their screen went offline — and the
   assignment engine stopped routing them work — several times an hour.
2. **A second tab used to end the first one's presence.** Closing one of
   two open connections marked the agent offline while they were still
   sitting in front of the other.

Both disappear if presence is derived from *how many connections an agent
has* rather than from the most recent one to close, and if losing the last
one is treated as "gone, unless they are back within the grace period".

Two facts live here, both in Redis because both are shared by every API
worker and by the sweep that acts on them — a process-local timer would
not survive a deploy, and the worker that sees the disconnect is usually
not the one that sees the reconnect:

* **The live set** — one member per open socket, per agent.
* **The pending-offline set** — a sorted set scored by the deadline,
  drained by ``blinkengage.agents.sweep_presence_offline``.

Nothing here writes to the database. The store records what is true about
connections; the sweep is the only thing that turns that into a status,
which is what keeps the decision in one place.
"""

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from redis.asyncio import Redis

#: The sorted set of agents due to be marked offline, scored by the epoch
#: second at which their grace period runs out. One key for the whole
#: deployment: the sweep wants "everyone due now" across every company,
#: and a key per company would turn that into a scan.
_PENDING_KEY = "presence:pending_offline"


def _live_key(company_id: UUID, agent_id: UUID) -> str:
    return f"presence:live:{company_id}:{agent_id}"


def _member(company_id: UUID, agent_id: UUID) -> str:
    return f"{company_id}:{agent_id}"


@dataclass(frozen=True, slots=True)
class PendingOffline:
    company_id: UUID
    agent_id: UUID


def _parse_member(raw: str) -> PendingOffline | None:
    """A member this module did not write is ignored rather than raised on.

    The sweep drains a shared key. A malformed member — a hand-edited key,
    a leftover from an older format — should cost that one agent's
    transition, not every other agent's.
    """
    company, _, agent = raw.partition(":")
    try:
        return PendingOffline(company_id=UUID(company), agent_id=UUID(agent))
    except ValueError:
        return None


class PresenceStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def connected(
        self,
        *,
        company_id: UUID,
        agent_id: UUID,
        connection_id: str,
        ttl: timedelta,
    ) -> None:
        """Record an open socket and cancel any pending offline.

        The TTL is a leak backstop, not a lifetime. A worker killed with
        ``SIGKILL`` never runs its disconnect path, and the member it left
        behind would otherwise pin the agent online forever — the failure
        being invisible, because a stuck-online agent looks exactly like a
        working one until work is routed to nobody. Re-applied on every
        connect, so it expires a fixed time after the *last* connection,
        not the first.
        """
        key = _live_key(company_id, agent_id)
        pipeline = self._redis.pipeline()
        pipeline.sadd(key, connection_id)
        pipeline.expire(key, int(ttl.total_seconds()))
        pipeline.zrem(_PENDING_KEY, _member(company_id, agent_id))
        await pipeline.execute()

    async def disconnected(
        self,
        *,
        company_id: UUID,
        agent_id: UUID,
        connection_id: str,
        offline_at: datetime,
    ) -> bool:
        """Drop a socket. Returns whether that was the agent's last one.

        Only the last one schedules anything: an agent still holding a
        connection somewhere is present, whatever this particular socket
        just did.
        """
        key = _live_key(company_id, agent_id)
        pipeline = self._redis.pipeline()
        pipeline.srem(key, connection_id)
        pipeline.scard(key)
        _, remaining = await pipeline.execute()
        if remaining:
            return False
        await self._redis.zadd(
            _PENDING_KEY, {_member(company_id, agent_id): offline_at.timestamp()}
        )
        return True

    async def due(self, *, now: datetime, limit: int) -> list[PendingOffline]:
        """Agents whose grace period has run out, soonest deadline first."""
        raw = await self._redis.zrangebyscore(
            _PENDING_KEY, min=0, max=now.timestamp(), start=0, num=limit
        )
        return [parsed for parsed in (_parse_member(item) for item in raw) if parsed is not None]

    async def claim(self, *, company_id: UUID, agent_id: UUID) -> bool:
        """Take responsibility for one transition. Returns False if
        somebody else already did.

        Two sweeps can overlap, and a reconnect removes the member too —
        so the removal is the claim, and only the caller whose ``ZREM``
        actually removed something goes on to write a status.
        """
        removed = await self._redis.zrem(_PENDING_KEY, _member(company_id, agent_id))
        return bool(removed)

    async def is_connected(self, *, company_id: UUID, agent_id: UUID) -> bool:
        # ``scard`` is typed ``Awaitable[int] | int`` because redis-py's
        # stubs cover the sync and async clients with one signature; this
        # client is always async.
        live = cast(Awaitable[int], self._redis.scard(_live_key(company_id, agent_id)))
        return bool(await live)

    async def clear(self, *, company_id: UUID, agent_id: UUID) -> None:
        """Forget an agent entirely — used when the sweep finds an agent
        that no longer exists, so a deleted agent's member cannot sit in
        the pending set being retried forever."""
        pipeline = self._redis.pipeline()
        pipeline.delete(_live_key(company_id, agent_id))
        pipeline.zrem(_PENDING_KEY, _member(company_id, agent_id))
        await pipeline.execute()
