"""tests/unit/server/test_redis_pubsub.py: Stage I2 - proves
RedisPubSub's own publish/subscribe primitive (server/application/
redis_pubsub.py) actually works end-to-end against a real Redis
instance: a publish on ONE connection is received by a subscriber on
ANOTHER, real, independently-obtained connection - not merely that the
client library's own API was called without raising. Marked
`requires_redis` - skips cleanly (via conftest.py's own
`redis_client_or_skip` factory fixture) if no real Redis is reachable in
this environment (see pytest.ini's own marker registration).
"""

from __future__ import annotations

import uuid

import pytest

from server.application.redis_pubsub import RedisPubSub

pytestmark = pytest.mark.requires_redis


def test_a_publish_on_one_connection_is_received_by_a_subscriber_on_another(redis_client_or_skip):
    # Two SEPARATE real connections - the actual proof this is a
    # cross-connection relay, not just a call into the same client's
    # own local state.
    publisher = RedisPubSub(client=redis_client_or_skip())
    subscriber = RedisPubSub(client=redis_client_or_skip())

    channel = f"test-channel-{uuid.uuid4().hex}"
    pubsub = subscriber.subscribe(channel)
    try:
        # Redis sends its own "subscribe" confirmation message first -
        # not a real published message yet; consumed here so the next
        # get_message() call below sees the real one.
        confirmation = pubsub.get_message(timeout=5)
        assert confirmation is not None
        assert confirmation["type"] == "subscribe"

        received_count = publisher.publish(channel, "hello-from-i2")
        assert received_count == 1  # exactly this one real subscriber

        message = pubsub.get_message(timeout=5)
        assert message is not None
        assert message["type"] == "message"
        assert message["channel"] == channel
        assert message["data"] == "hello-from-i2"
    finally:
        pubsub.close()


def test_publish_with_no_subscribers_returns_zero_not_an_error(redis_client_or_skip):
    publisher = RedisPubSub(client=redis_client_or_skip())
    channel = f"test-channel-{uuid.uuid4().hex}"  # nobody has ever subscribed to this one

    assert publisher.publish(channel, "nobody is listening") == 0
