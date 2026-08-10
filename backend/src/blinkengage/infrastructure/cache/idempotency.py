"""Idempotent replay of creating requests, backed by Redis.

See ``docs/api/mobile-integration-guide.md``.

The problem is specific to unreliable networks and therefore specific to
mobile: a client sends a reply, the connection drops before the response
arrives, and the client cannot distinguish "the message was never sent"
from "the message was sent and the receipt was lost". Retrying risks the
customer receiving the same reply twice; not retrying risks it never
arriving. Neither is acceptable, so the client sends an ``Idempotency-Key``
and the server takes responsibility for the ambiguity.

**A reservation, then a result.** The first request to present a key takes
a short-lived reservation (``SET NX``); a concurrent second one sees it and
is told the work is in flight rather than being allowed to do it again.
When the first finishes, the reservation is replaced by the stored response
under a much longer TTL — the replay window. The two lifetimes are
different on purpose: a worker that dies mid-request must not hold a key
hostage for the whole replay window, and a client retrying an hour later
must still get its original answer rather than a second message.

**The fingerprint is part of the record.** A key replayed with a *different*
body is a client bug, and returning the first request's response to it
would hide that bug behind a plausible answer. It is refused instead.
"""

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import orjson
from redis.asyncio import Redis

_IN_FLIGHT = "in_flight"
_COMPLETED = "completed"


def _key(scope: str, idempotency_key: str) -> str:
    # The key is hashed rather than interpolated: it is client-supplied,
    # and a client that sends a 4KB key or one containing a newline should
    # produce a harmless Redis key, not a surprising one.
    digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
    return f"idempotency:{scope}:{digest}"


def fingerprint(payload: bytes) -> str:
    """A stable digest of a request body, used to catch a key reused for
    different content."""
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class Proceed:
    """Nobody has used this key. The caller owns the work."""


@dataclass(frozen=True, slots=True)
class Replay:
    """This key already produced a response. Return it verbatim."""

    status_code: int
    body: Any


@dataclass(frozen=True, slots=True)
class InFlight:
    """Another request is doing this work right now."""


@dataclass(frozen=True, slots=True)
class Mismatch:
    """This key was used for a different request body."""


Reservation = Proceed | Replay | InFlight | Mismatch


class IdempotencyStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def reserve(
        self,
        *,
        scope: str,
        idempotency_key: str,
        request_fingerprint: str,
        reservation_ttl: timedelta,
    ) -> Reservation:
        redis_key = _key(scope, idempotency_key)
        acquired = await self._redis.set(
            redis_key,
            orjson.dumps({"state": _IN_FLIGHT, "fingerprint": request_fingerprint}),
            nx=True,
            ex=int(reservation_ttl.total_seconds()),
        )
        if acquired:
            return Proceed()

        raw = await self._redis.get(redis_key)
        if raw is None:
            # The reservation expired between the SET and the GET. Rare,
            # and the safe reading is that nothing was recorded — so the
            # caller does the work, which is the same outcome as having
            # arrived a moment later.
            return Proceed()

        record = orjson.loads(raw)
        if record.get("fingerprint") != request_fingerprint:
            return Mismatch()
        if record.get("state") != _COMPLETED:
            return InFlight()
        return Replay(status_code=record["status_code"], body=record["body"])

    async def complete(
        self,
        *,
        scope: str,
        idempotency_key: str,
        request_fingerprint: str,
        status_code: int,
        body: Any,
        result_ttl: timedelta,
    ) -> None:
        await self._redis.set(
            _key(scope, idempotency_key),
            orjson.dumps(
                {
                    "state": _COMPLETED,
                    "fingerprint": request_fingerprint,
                    "status_code": status_code,
                    "body": body,
                }
            ),
            ex=int(result_ttl.total_seconds()),
        )

    async def release(self, *, scope: str, idempotency_key: str) -> None:
        """Drop a reservation whose work failed.

        A failed request must not leave its key claimed: the client will
        retry, and the retry is the whole point. Only reservations are
        released — a completed response is never withdrawn.
        """
        await self._redis.delete(_key(scope, idempotency_key))
