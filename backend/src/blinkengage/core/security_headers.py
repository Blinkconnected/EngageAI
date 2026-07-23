"""Adds baseline OWASP-recommended security response headers to every
response. See ``docs/security/hardening.md``.

This is a pure JSON API (confirmed: no ``HTMLResponse``/template
rendering anywhere in this codebase), so a strict
``Content-Security-Policy: default-src 'none'`` is always correct for
API responses and never breaks anything an API client depends on. It's
only applied in production, though, because ``/docs``/``/redoc``
(Swagger UI/ReDoc — real HTML pages that load JS/CSS from a CDN) are
only ever served outside production (``main.py`` already sets
``docs_url=None``/``redoc_url=None`` when ``settings.is_production``) —
applying the strict policy in dev would break the very tool a developer
is using it for.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from blinkengage.core.config import Settings

_BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in _BASE_HEADERS.items():
            response.headers[name] = value
        if self._settings.is_production:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
