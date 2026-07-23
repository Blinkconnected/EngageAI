import pytest
from fakeredis import FakeAsyncRedis

from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_publish_sends_json_payload_on_the_given_channel(redis) -> None:
    publisher = RealtimePublisher(redis)
    pubsub = redis.pubsub()
    await pubsub.subscribe("company:1:conversation:2:typing")

    await publisher.publish(
        "company:1:conversation:2:typing", {"agent_id": "abc", "is_typing": True}
    )

    # First message is the subscribe confirmation; second is the payload.
    await pubsub.get_message(timeout=1)
    message = await pubsub.get_message(timeout=1)
    assert message is not None
    assert message["data"] == '{"agent_id":"abc","is_typing":true}'

    await pubsub.aclose()
