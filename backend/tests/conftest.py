from collections.abc import AsyncGenerator

import pytest
from dependency_injector import providers
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient

import blinkengage.infrastructure.database.models  # noqa: F401 - populates Base.metadata
from blinkengage.infrastructure.database.base import Base
from blinkengage.main import create_app


@pytest.fixture
def fake_redis():
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture
async def app(fake_redis):
    application = create_app()
    application.state.container.redis.override(providers.Object(fake_redis))

    engine = application.state.container.engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield application

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await fake_redis.aclose()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def registered_owner(client: AsyncClient) -> dict:
    payload = {
        "company_name": "Acme Corp",
        "owner_full_name": "Ada Owner",
        "owner_email": "ada@acme.example",
        "owner_password": "correct-horse-battery-9",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def owner_headers(registered_owner: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered_owner['tokens']['access_token']}"}
