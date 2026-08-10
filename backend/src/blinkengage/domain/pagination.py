"""Where a page stopped, as a value.

A keyset position — "the row after this one" — is a property of an
ordering, not of HTTP, so it lives here rather than in the API layer that
happens to serialise it. Repositories take one; ``api.cursors`` is what
turns it into and back from the opaque token a client carries.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Cursor:
    """The last row of the previous page, identified by id alone.

    **The sort value is deliberately not carried here.** The obvious design
    — put the timestamp in the cursor and compare against it — makes the
    keyset depend on a value surviving a round trip through JSON, a
    timezone, and a bind parameter with the same precision it has in the
    database. It does not always survive. On SQLite a ``created_at``
    written by ``CURRENT_TIMESTAMP`` is stored without a fractional part
    while a bound datetime renders with one, so the two are compared *as
    strings* and every row in the same second looks strictly earlier than
    the cursor — a page that never advances, which is an infinite paging
    loop rather than a wrong answer.

    Naming the row instead makes the query compare a stored value with a
    stored value, in whatever representation the database uses, so there
    is no format to disagree about. The sort column is looked up from this
    id when the page is built.
    """

    id: UUID
