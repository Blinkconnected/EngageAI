"""Parsing the HTTP ``Range`` header.

See ``docs/architecture/conversations.md``.

Only what a media element actually sends is supported: a single byte range,
open- or closed-ended. Multipart ranges are legal HTTP and no browser uses
them for ``<video>``/``<audio>``, so accepting them would mean building and
testing a multipart response nothing requests.

An unparseable or unsatisfiable header returns ``None``, which the caller
serves as a normal 200 with the whole body. That is what the spec says to
do, and it is also the kinder failure: a browser that sent something odd
still gets its file rather than an error it cannot act on.
"""

import re
from typing import Final

#: ``bytes=0-``, ``bytes=500-999``, ``bytes=-500`` (the final 500 bytes).
_RANGE_RE: Final[re.Pattern[str]] = re.compile(
    r"^bytes=(?P<start>\d*)-(?P<end>\d*)$", re.IGNORECASE
)


def parse_range_header(header: str | None, *, total_size: int) -> tuple[int, int] | None:
    """An inclusive ``(start, end)``, or ``None`` to serve the whole body."""
    if not header or total_size <= 0:
        return None

    match = _RANGE_RE.match(header.strip())
    if match is None:
        return None

    raw_start, raw_end = match.group("start"), match.group("end")

    if not raw_start and not raw_end:
        return None

    if not raw_start:
        # A suffix range: the last N bytes. Browsers use this to read the
        # moov atom at the end of an MP4 that was not written for
        # streaming — refusing it makes those files unplayable.
        length = int(raw_end)
        if length <= 0:
            return None
        start = max(0, total_size - length)
        return start, total_size - 1

    start = int(raw_start)
    if start >= total_size:
        # Unsatisfiable. Serving the whole body is more useful than a 416
        # for a media element that will simply retry.
        return None

    end = int(raw_end) if raw_end else total_size - 1
    end = min(end, total_size - 1)
    if end < start:
        return None
    return start, end


__all__ = ["parse_range_header"]
