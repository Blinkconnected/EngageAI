from httpx import AsyncClient


async def test_liveness_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "blinkengage-api"}


async def test_readiness_endpoint_reports_database_and_redis_ok(client: AsyncClient) -> None:
    # No real RabbitMQ broker runs in the test process (broker connectivity
    # is always verified manually against the real docker-compose stack,
    # same bar as every other "real infra" check in this suite) — so this
    # also doubles as the "degraded" path test: database/redis are real
    # (SQLite/fakeredis), rabbitmq is genuinely unreachable here.
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"
    assert body["rabbitmq"] == "unreachable"


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
