"""Unit tests for ``SecurityHeadersMiddleware`` and the CORS
misconfiguration guard in ``main.py::create_app``. See
``docs/security/hardening.md``.
"""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from blinkengage.core.config import Settings
from blinkengage.core.security_headers import SecurityHeadersMiddleware


def _minimal_app(*, is_production: bool) -> Starlette:
    async def _endpoint(request):  # type: ignore[no-untyped-def]
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", _endpoint)])
    # A production Settings has to be a *valid* one. `Settings` refuses to
    # construct with `environment="production"` on development defaults —
    # MinIO's published credentials, localhost CORS — which is the point
    # of that validator and not something to work around here. The
    # overrides below are the smallest set that makes the object legal;
    # none of them affects the headers under test.
    overrides = (
        {
            "s3_access_key": "blinkengage",
            "s3_secret_key": "a-real-object-storage-secret",
            "cors_allow_origins": ["https://engage.example.com"],
            "jwt_secret_key": "Ky7pQz3XwR9tLmN4vB6hJ2cF8dS5aG1e",
            "credentials_encryption_key": "Zt4mW8xQ2rN6yB3vK9pL5cH7dJ1gS0fA",
        }
        if is_production
        else {}
    )
    settings = Settings(
        environment="production" if is_production else "development",
        **overrides,  # type: ignore[arg-type]
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    return app


class TestSecurityHeadersMiddleware:
    def test_base_headers_present_in_development(self) -> None:
        client = TestClient(_minimal_app(is_production=False))

        response = client.get("/")

        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "permissions-policy" in response.headers

    def test_csp_and_hsts_absent_outside_production(self) -> None:
        client = TestClient(_minimal_app(is_production=False))

        response = client.get("/")

        assert "content-security-policy" not in response.headers
        assert "strict-transport-security" not in response.headers

    def test_csp_and_hsts_present_in_production(self) -> None:
        client = TestClient(_minimal_app(is_production=True))

        response = client.get("/")

        assert (
            response.headers["content-security-policy"]
            == "default-src 'none'; frame-ancestors 'none'"
        )
        assert "max-age=63072000" in response.headers["strict-transport-security"]
        # Base headers still apply in production too.
        assert response.headers["x-content-type-options"] == "nosniff"


class TestCorsMisconfigurationGuard:
    def test_wildcard_origin_with_credentials_raises_at_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from blinkengage import main as main_module

        bad_settings = Settings(cors_allow_origins=["*"])
        monkeypatch.setattr(main_module, "get_settings", lambda: bad_settings)

        with pytest.raises(ValueError, match="cors_allow_origins"):
            main_module.create_app()

    def test_explicit_allowlist_boots_fine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from blinkengage import main as main_module

        good_settings = Settings(cors_allow_origins=["https://app.acme.example"])
        monkeypatch.setattr(main_module, "get_settings", lambda: good_settings)

        app = main_module.create_app()

        assert app is not None
