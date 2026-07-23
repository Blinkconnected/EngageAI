from datetime import timedelta
from uuid import uuid4

import pytest
from fakeredis import FakeAsyncRedis

from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_stored_token_is_valid(redis) -> None:
    store = RefreshTokenStore(redis)
    user_id = uuid4()
    await store.store(user_id=user_id, jti="jti-1", ttl=timedelta(days=1))

    assert await store.is_valid(user_id=user_id, jti="jti-1")


async def test_unknown_token_is_invalid(redis) -> None:
    store = RefreshTokenStore(redis)
    assert not await store.is_valid(user_id=uuid4(), jti="never-issued")


async def test_revoke_invalidates_token(redis) -> None:
    store = RefreshTokenStore(redis)
    user_id = uuid4()
    await store.store(user_id=user_id, jti="jti-1", ttl=timedelta(days=1))

    await store.revoke(user_id=user_id, jti="jti-1")

    assert not await store.is_valid(user_id=user_id, jti="jti-1")


async def test_revoke_all_for_user_clears_every_token(redis) -> None:
    store = RefreshTokenStore(redis)
    user_id = uuid4()
    await store.store(user_id=user_id, jti="jti-1", ttl=timedelta(days=1))
    await store.store(user_id=user_id, jti="jti-2", ttl=timedelta(days=1))

    await store.revoke_all_for_user(user_id=user_id)

    assert not await store.is_valid(user_id=user_id, jti="jti-1")
    assert not await store.is_valid(user_id=user_id, jti="jti-2")


async def test_revoking_one_user_does_not_affect_another(redis) -> None:
    store = RefreshTokenStore(redis)
    user_a, user_b = uuid4(), uuid4()
    await store.store(user_id=user_a, jti="jti-1", ttl=timedelta(days=1))
    await store.store(user_id=user_b, jti="jti-1", ttl=timedelta(days=1))

    await store.revoke_all_for_user(user_id=user_a)

    assert not await store.is_valid(user_id=user_a, jti="jti-1")
    assert await store.is_valid(user_id=user_b, jti="jti-1")
