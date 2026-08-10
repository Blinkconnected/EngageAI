"""Opaque keyset cursors for the two lists that change while being read.

See ``docs/api/mobile-integration-guide.md``.

Offset paging asks "skip the first N rows", and on a list that is actively
changing N means something different by the time page 2 arrives: a
conversation that moved while the client was reading is returned twice, or
never returned at all. The duplicate is recoverable — a client keying by id
can drop it. The row that is silently skipped is not, and on the
conversation list that row is somebody's unanswered customer.

A keyset cursor asks "the rows after *this specific row*" instead, which
does not move when the rows around it do.

**Opaque on purpose.** The encoding is base64url over a small JSON payload
with a version tag, and clients are told to treat it as a token they only
ever echo back. A client that parses it acquires a dependency on a sort
key we would otherwise be free to change.
"""

import base64
import binascii
from uuid import UUID

import orjson
from fastapi import HTTPException, status

from blinkengage.domain.pagination import Cursor

#: Bumped if the payload shape changes. An old cursor then fails cleanly
#: as invalid rather than being misread as a new one — a client holding a
#: stale cursor across a deploy restarts its paging, which is correct, and
#: does not silently receive the wrong window.
_VERSION = 1


class InvalidCursor(ValueError):
    """The cursor was not one we issued, or no longer means anything."""


#: The shared description for the ``cursor`` query parameter, so every
#: list that supports keyset paging documents it identically.
CURSOR_DESCRIPTION = (
    "Keyset cursor from a previous response's `next_cursor`. Echo it back "
    "verbatim — it is opaque, and parsing it couples the client to a sort "
    "key that may change. Preferred over `page` on lists that change while "
    "being read: offset paging can skip a row entirely, which keying by id "
    "cannot repair. Ignored when absent."
)


def encode(cursor: Cursor) -> str:
    payload = orjson.dumps({"v": _VERSION, "i": str(cursor.id)})
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def parse(raw: str | None) -> Cursor | None:
    """Decode a client-supplied cursor, or fail the request cleanly.

    A malformed cursor is a 422 rather than a silently ignored parameter:
    quietly serving page 1 to a client that asked for page 5 looks like
    the list restarted, and a paging loop that never advances is a far
    harder bug to see than an error.
    """
    if raw is None:
        return None
    try:
        return decode(raw)
    except InvalidCursor as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid or expired cursor. Restart paging without one.",
        ) from exc


def decode(raw: str) -> Cursor:
    try:
        # Padding is stripped when encoding (it survives URLs and logs
        # better) so it has to be put back before decoding.
        padded = raw + "=" * (-len(raw) % 4)
        payload = orjson.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, orjson.JSONDecodeError, ValueError) as exc:
        raise InvalidCursor(str(exc)) from exc

    if not isinstance(payload, dict) or payload.get("v") != _VERSION:
        raise InvalidCursor("unrecognised cursor version")

    try:
        return Cursor(id=UUID(payload["i"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCursor(str(exc)) from exc
