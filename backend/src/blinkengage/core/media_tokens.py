"""Short-lived, single-attachment URLs for inline media.

See ``docs/architecture/conversations.md``.

An ``<img src>`` cannot send an ``Authorization`` header, and a ``<video>``
needs HTTP range requests against a plain URL to let somebody drag the
scrubber. So inline media cannot go through the ordinary bearer-token
endpoint, and the two obvious alternatives are both worse:

- **Fetch to a blob URL.** Works for images, but the browser must download
  the *entire* file before showing anything, which throws away native
  progressive rendering and makes seeking a 50 MB video impossible without
  downloading all of it first.
- **Presigned object-storage URLs.** Correct in principle, but they hand a
  browser a direct URL to the storage layer, which in this deployment is
  not reachable from outside Docker — and doing it properly means the
  storage bucket's access policy becomes part of the tenant isolation
  story.

So: a signed token, scoped to **one attachment**, valid for **minutes**,
carried in the query string of our own endpoint. The endpoint re-checks
tenant ownership on every request regardless, so a leaked token is a leak
of one file for a few minutes rather than an authorization bypass.

Deliberately **not** a JWT. A JWT here would be a second kind of session
credential, and one whose leak surface is a URL that ends up in browser
history, server logs and referrer headers. A bare HMAC over
``(attachment_id, company_id, expiry)`` cannot be replayed against a
different attachment or a different tenant, carries no identity, and
grants nothing beyond reading those bytes.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from blinkengage.core.config import Settings

#: How long a media URL stays valid. Long enough to load a large video over
#: a slow connection and to scrub back and forth in it; short enough that a
#: URL pasted into a chat or captured in a log is useless by the time
#: anybody tries it.
DEFAULT_TTL_SECONDS: Final[int] = 15 * 60

#: Derived from the JWT secret rather than reusing it directly, so a media
#: signature can never be mistaken for — or used as — a session token, even
#: if a future refactor confuses the two.
_KEY_CONTEXT: Final[bytes] = b"blinkengage.media-url.v1"


class MediaTokenError(Exception):
    """A media URL that is not valid for what it is being used for.

    One exception for expired, malformed and wrong-attachment cases on
    purpose: the endpoint answers all three identically, because telling a
    caller *which* way their token was wrong is free help for somebody
    probing.
    """


def _signing_key(settings: Settings) -> bytes:
    return hmac.new(settings.jwt_secret_key.encode(), _KEY_CONTEXT, hashlib.sha256).digest()


@dataclass(frozen=True, slots=True)
class MediaToken:
    expires_at: int
    signature: str


def _payload(attachment_id: UUID, company_id: UUID, expires_at: int) -> bytes:
    # The company is part of what is signed, not merely checked later: a
    # token minted for one tenant must not verify for another even if an
    # attachment id were somehow guessed or reused.
    return f"{attachment_id}:{company_id}:{expires_at}".encode()


def sign(
    *,
    attachment_id: UUID,
    company_id: UUID,
    settings: Settings,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: int | None = None,
) -> MediaToken:
    expires_at = (now if now is not None else int(time.time())) + ttl_seconds
    signature = hmac.new(
        _signing_key(settings),
        _payload(attachment_id, company_id, expires_at),
        hashlib.sha256,
    ).hexdigest()
    return MediaToken(expires_at=expires_at, signature=signature)


def verify(
    *,
    attachment_id: UUID,
    company_id: UUID,
    expires_at: int,
    signature: str,
    settings: Settings,
    now: int | None = None,
) -> None:
    """Raises ``MediaTokenError`` unless the signature is valid and current."""
    moment = now if now is not None else int(time.time())
    if expires_at <= moment:
        raise MediaTokenError("This media link has expired.")

    expected = hmac.new(
        _signing_key(settings),
        _payload(attachment_id, company_id, expires_at),
        hashlib.sha256,
    ).hexdigest()
    # Constant-time: a byte-by-byte comparison leaks how much of a forged
    # signature was right, which is enough to construct one given patience.
    if not hmac.compare_digest(expected, signature):
        raise MediaTokenError("This media link is not valid.")


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MediaToken",
    "MediaTokenError",
    "sign",
    "verify",
]
