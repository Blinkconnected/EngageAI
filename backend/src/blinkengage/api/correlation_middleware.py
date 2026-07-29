"""Assigns a correlation ID to every request.

Reads ``X-Correlation-ID`` if the caller sent one — so a trace that
started in a gateway or a client SDK stays joined to ours — and echoes
it back on the response, so whoever made the call can quote it when
asking what happened.
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from blinkengage.core.correlation import CORRELATION_HEADER, set_correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = set_correlation_id(request.headers.get(CORRELATION_HEADER))
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        return response
