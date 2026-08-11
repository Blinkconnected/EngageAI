"""The ``Idempotency-Key`` contract, as endpoints see it.

See ``infrastructure.cache.idempotency`` for the storage rules and
``docs/api/mobile-integration-guide.md`` for why a mobile client needs
this at all.

Opt-in from both directions. An endpoint has to ask for the guard, and a
client has to send the header; a request without one behaves exactly as it
did before. That matters for a contract added to a live API — every
existing caller, including the web console, keeps working unchanged, and
the guarantee is available to the clients that need it.

**The commit moved into the endpoint, deliberately.** ``get_db_session``
commits during teardown, i.e. *after* the handler returns — so recording a
response before then would record work that a failing commit then threw
away, and the client's retry would be handed a receipt for a message that
was never sent. The guard therefore commits the work itself and records
only once it is durable. The session dependency's own commit afterwards is
a harmless no-op.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TypeVar

from fastapi import HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.cache.idempotency import (
    IdempotencyStore,
    InFlight,
    Mismatch,
    Replay,
    fingerprint,
)

logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

#: Set on a response served from the store rather than freshly produced.
#: A client cannot otherwise tell the two apart, and "did my retry actually
#: create a second message?" is exactly the question this feature exists to
#: answer.
REPLAY_HEADER = "Idempotent-Replay"


class IdempotencyGuard:
    def __init__(
        self,
        *,
        store: IdempotencyStore,
        session: AsyncSession,
        key: str | None,
        reservation_ttl: timedelta,
        result_ttl: timedelta,
    ) -> None:
        self._store = store
        self._session = session
        self._key = key
        self._reservation_ttl = reservation_ttl
        self._result_ttl = result_ttl

    async def run(
        self,
        *,
        scope: str,
        request: BaseModel,
        model: type[ModelT],
        produce: Callable[[], Awaitable[ModelT]],
        response: Response,
        status_code: int = status.HTTP_201_CREATED,
    ) -> ModelT:
        """Run ``produce`` at most once per key.

        ``scope`` narrows the key's meaning to one operation on one
        resource — the same key presented against a different conversation
        is a different request, and treating it otherwise would let a
        client's key collision silently return somebody else's message.
        """
        if self._key is None:
            return await produce()

        request_fingerprint = fingerprint(request.model_dump_json().encode())
        reservation = await self._store.reserve(
            scope=scope,
            idempotency_key=self._key,
            request_fingerprint=request_fingerprint,
            reservation_ttl=self._reservation_ttl,
        )

        if isinstance(reservation, Replay):
            response.status_code = reservation.status_code
            response.headers[REPLAY_HEADER] = "true"
            return model.model_validate(reservation.body)

        if isinstance(reservation, InFlight):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A request with this Idempotency-Key is still in progress. "
                    "Retry shortly; do not change the request body."
                ),
            )

        if isinstance(reservation, Mismatch):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "This Idempotency-Key was already used for a different request body. "
                    "Generate a new key for a new request."
                ),
            )

        try:
            result = await produce()
            # Durable before it is claimed to have happened — see the
            # module docstring.
            await self._session.commit()
        except Exception:
            # The work failed, so the key must not stay claimed: the
            # client will retry, and the retry has to be allowed to run.
            await self._store.release(scope=scope, idempotency_key=self._key)
            raise

        try:
            await self._store.complete(
                scope=scope,
                idempotency_key=self._key,
                request_fingerprint=request_fingerprint,
                status_code=status_code,
                body=result.model_dump(mode="json"),
                result_ttl=self._result_ttl,
            )
        except Exception:  # noqa: BLE001
            # The work is already committed and the caller is about to be
            # told so. Failing the request here would be a lie in the more
            # damaging direction — the message *was* sent — so this is
            # logged and swallowed, leaving a later retry to be treated as
            # a fresh request. Reachable only if Redis fails in the window
            # between the commit and this write.
            logger.exception("idempotency_result_not_recorded", scope=scope)

        return result
