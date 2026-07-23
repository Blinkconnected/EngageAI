from datetime import timedelta
from uuid import uuid4

import pytest
from fakeredis import FakeAsyncRedis

from blinkengage.infrastructure.cache.chat_session_store import ChatSessionData, ChatSessionStore


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=False)
    yield client
    await client.aclose()


async def test_create_and_get_round_trips(redis) -> None:
    store = ChatSessionStore(redis)
    data = ChatSessionData(customer_id=uuid4(), channel_config_id=uuid4(), company_id=uuid4())

    token = await store.create(data=data, ttl=timedelta(hours=1))
    fetched = await store.get(token)

    assert fetched == data


async def test_get_returns_none_for_unknown_token(redis) -> None:
    store = ChatSessionStore(redis)
    assert await store.get("not-a-real-token") is None


async def test_touch_extends_ttl(redis) -> None:
    store = ChatSessionStore(redis)
    data = ChatSessionData(customer_id=uuid4(), channel_config_id=uuid4(), company_id=uuid4())
    token = await store.create(data=data, ttl=timedelta(seconds=5))

    await store.touch(token, ttl=timedelta(hours=1))

    ttl = await redis.ttl(f"webchat_session:{token}")
    assert ttl > 5
