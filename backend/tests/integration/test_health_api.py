from typing import Any

from httpx import AsyncClient

from blinkengage.api.deps import get_settings_dep
from blinkengage.core.config import get_settings


async def test_liveness_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "blinkengage-api"}


async def test_readiness_endpoint_reports_database_and_redis_ok(
    client: AsyncClient, app: Any
) -> None:
    # RabbitMQ reachability must be forced deterministically rather than
    # relied upon incidentally: database/redis are real-but-fake
    # (SQLite/fakeredis), but a real RabbitMQ broker genuinely is
    # reachable from this process whenever the test suite runs inside the
    # docker-compose network (e.g. `docker compose exec backend pytest`)
    # — only a bare host-level pytest run with no broker on the network
    # ever saw the "unreachable" branch this test exercises. Overriding
    # the URL to a closed local port makes the "degraded" path exercised
    # regardless of how/where the suite runs.
    unreachable_settings = get_settings().model_copy(
        update={"rabbitmq_url": "amqp://guest:guest@127.0.0.1:1/"}
    )
    app.dependency_overrides[get_settings_dep] = lambda: unreachable_settings
    try:
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"] == "ok"
        assert body["redis"] == "ok"
        assert body["rabbitmq"] == "unreachable"
    finally:
        del app.dependency_overrides[get_settings_dep]


async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Blink Engage"


async def test_metrics_endpoint_is_served(client: AsyncClient) -> None:
    # First request registers the route metrics; a follow-up call is needed
    # for the exposition to include them, but the endpoint must respond either way.
    await client.get("/api/v1/health")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert b"http_requests_total" in response.content or b"# HELP" in response.content
