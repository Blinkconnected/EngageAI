"""Correlation IDs: one identifier tying together everything that
happened because of a single action.

See ``docs/architecture/billing.md``.

Allocating a payment writes a payment-allocated event *and* an invoice
state transition. Issuing a credit note writes the credit note *and*
settles the invoice. When somebody investigates a disputed charge, the
question is never "what happened to this row" but "what happened when
this was done" — and without a shared identifier the answer has to be
reconstructed from timestamps, which stops working the moment two
operators act in the same second.

A ``ContextVar`` rather than a parameter threaded through every call:
the correlation ID is ambient to the operation, and passing it by hand
through service, repository and event-publisher signatures would mean
every new code path silently defaults to "no correlation" the moment
somebody forgets an argument.

Outside a request — a Celery task, an event consumer — there is no
inbound identifier, so one is generated per operation. That is correct:
those are still single logical actions, they simply begin here.
"""

import uuid
from contextvars import ContextVar

#: Set per request by the middleware, or per operation by a background
#: worker. ``None`` means nobody has started an operation yet.
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

#: The header a caller may supply to tie their own trace to ours. Named
#: for the widely-used convention rather than something bespoke, so an
#: existing gateway or client library already sends it.
CORRELATION_HEADER = "X-Correlation-ID"

#: Guards against a caller supplying something enormous or malicious —
#: this value ends up in a database column and in log lines.
_MAX_LENGTH = 64


def set_correlation_id(value: str | None) -> str:
    """Starts an operation, returning the id in force.

    A supplied value is trusted but bounded; anything absent or
    unreasonable gets a fresh UUID rather than being rejected, because
    failing a request over a malformed trace header would be a worse
    outcome than losing the trace.
    """
    candidate = (value or "").strip()
    if not candidate or len(candidate) > _MAX_LENGTH:
        candidate = str(uuid.uuid4())
    _correlation_id.set(candidate)
    return candidate


def get_correlation_id() -> str:
    """The current operation's id, generating one if none is set.

    Never returns ``None``: an audit event without a correlation ID is
    an audit event that cannot be joined to its siblings, which is the
    one thing this exists to prevent.
    """
    current = _correlation_id.get()
    if current is None:
        current = str(uuid.uuid4())
        _correlation_id.set(current)
    return current


def reset_correlation_id() -> None:
    _correlation_id.set(None)
