"""Unit tests for ``ErpNextClient`` — HTTP calls mocked via
``httpx.MockTransport`` (same pattern as ``test_whatsapp_provider.py``/
``test_ai_providers.py``). See ``docs/architecture/erp-integration.md``.
"""

from typing import Any

import httpx
import orjson
import pytest

from blinkengage.infrastructure.erp.client import ErpNextClient

_RealAsyncClient = httpx.AsyncClient


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("blinkengage.infrastructure.erp.client.httpx.AsyncClient", factory)


@pytest.fixture
def client() -> ErpNextClient:
    return ErpNextClient(
        base_url="https://erp.acme.example", api_key="key123", api_secret="secret456"
    )


class TestCreateCustomer:
    async def test_posts_to_customer_resource_with_token_auth(
        self, client: ErpNextClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://erp.acme.example/api/resource/Customer"
            assert request.headers["authorization"] == "token key123:secret456"
            body = orjson.loads(request.content)
            assert body["customer_name"] == "Jane Doe"
            assert body["email_id"] == "jane@example.com"
            assert body["mobile_no"] == "+15550001111"
            return httpx.Response(200, json={"data": {"name": "CUST-0001"}})

        _mock_client(monkeypatch, handler)

        result = await client.create_customer(
            name="Jane Doe", email="jane@example.com", phone="+15550001111"
        )

        assert result == "CUST-0001"

    async def test_omits_optional_fields_when_absent(
        self, client: ErpNextClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = orjson.loads(request.content)
            assert "email_id" not in body
            assert "mobile_no" not in body
            return httpx.Response(200, json={"data": {"name": "CUST-0002"}})

        _mock_client(monkeypatch, handler)

        result = await client.create_customer(name="No Contact Info", email=None, phone=None)

        assert result == "CUST-0002"


class TestListRecords:
    async def test_filters_by_customer_field(
        self, client: ErpNextClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/resource/Sales Invoice"
            assert request.url.params["filters"] == '[["customer","=","CUST-0001"]]'
            return httpx.Response(200, json={"data": [{"name": "SINV-0001"}]})

        _mock_client(monkeypatch, handler)

        records = await client.list_records(doctype="Sales Invoice", customer_name="CUST-0001")

        assert records == [{"name": "SINV-0001"}]

    async def test_returns_empty_list_when_no_data_key(
        self, client: ErpNextClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, lambda request: httpx.Response(200, json={}))

        records = await client.list_records(doctype="Quotation", customer_name="CUST-0001")

        assert records == []


class TestHealthCheck:
    async def test_healthy_on_2xx(
        self, client: ErpNextClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"message": "admin"}))

        healthy, detail = await client.health_check()
        assert healthy is True
        assert detail is None

    async def test_unhealthy_on_error(
        self, client: ErpNextClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, lambda request: httpx.Response(403, json={"error": "forbidden"}))

        healthy, detail = await client.health_check()
        assert healthy is False
        assert detail is not None
