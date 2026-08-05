"""redis_pubsub.py: Stage I2's own thin publish/subscribe primitive over
real Redis Pub/Sub (Server_Design.md §2.9) - proves the primitive itself
works, real client to real client, over a real Redis instance. Wiring
this into GameServer's own real match-found event flow is explicitly
Phase 4's job (the nine-service split), not this stage's - see
I2_prompt.md's own Requirement #2. This module has never heard of
GameServer, a match-found event's own shape, or any other
application-level concept - it is a bare publish/subscribe wrapper only,
mirroring session_coordinator.py's own "prove the new capability
correct on its own before wiring it into anything" established
convention (Stage E1/F1/F2's own precedent).

WHY REDIS PUB/SUB, NOT NATS (Server_Design.md §2.9's own flagged open
item, resolved here, not re-litigated): default to Redis Pub/Sub for
this stage's own scope - fewer moving parts, reuses this same Redis
deployment RedisSessionCoordinator (session_coordinator.py) already
targets - per Implementation_Plan.md's own explicit "unless a concrete
reason to add NATS emerges" wording. No such concrete reason surfaced
while implementing this (see this stage's own final report for the
restated reasoning).

SYNCHRONOUS `redis.Redis`, NOT `redis.asyncio.Redis` - mirrors
RedisSessionCoordinator's own identical reasoning in
session_coordinator.py's class docstring ("SYNCHRONOUS redis.Redis, NOT
redis.asyncio.Redis" section): kept plain and synchronous so this
primitive can be exercised directly in an ordinary synchronous test
(test_redis_pubsub.py) with no event loop of its own to manage. A
future Phase-4 caller wiring this into GameServer's own async event flow
can wrap these calls (e.g. via `asyncio.to_thread`) exactly the same way
it would wrap any other blocking I/O call - not this stage's own
concern to decide.
"""

from __future__ import annotations

from typing import Optional

import redis


class RedisPubSub:
    """A thin wrapper over one real Redis connection's own publish/
    subscribe API - see module docstring for the full reasoning behind
    every decision below. Deliberately does not interpret, serialize, or
    validate `message`/`channel` in any way - a future caller's own
    event-shape/encoding choice, not this primitive's concern."""

    def __init__(self, redis_url: Optional[str] = None, client: Optional["redis.Redis"] = None) -> None:
        """Create a publish/subscribe helper.

        Args:
            redis_url: A real `redis://...` URL (matching REDIS_URL's
                own shape from docker-compose.yml) - this instance
                constructs its own `redis.Redis.from_url(...)` client
                internally. Mutually exclusive with `client` (see
                RedisSessionCoordinator's own identical constructor
                shape/reasoning in session_coordinator.py).
            client: An already-constructed `redis.Redis` instance to use
                instead - injectable (DIP) purely for testability
                (mirrors RedisSessionCoordinator's own identical
                parameter), and so a test proving "two independent
                connections" can construct each `RedisPubSub` around a
                separately-obtained real client.

        Returns:
            None.

        Raises:
            ValueError: If neither `redis_url` nor `client` is given.
        """

        if client is not None:
            self._client = client
        elif redis_url is not None:
            self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        else:
            raise ValueError("RedisPubSub requires either redis_url or client")

    def publish(self, channel: str, message: str) -> int:
        """Publish `message` on `channel`.

        Args:
            channel: The channel name to publish on.
            message: The message payload - passed straight through,
                unmodified.

        Returns:
            The number of subscribers that received the message at the
            moment of publishing (Redis's own PUBLISH return value) - 0
            does not mean the publish failed, only that nobody was
            subscribed to `channel` at that exact instant (Redis
            Pub/Sub delivers only to subscribers already listening, with
            no persistence/replay of missed messages - a real,
            documented property of this mechanism, not a bug).
        """

        return self._client.publish(channel, message)

    def subscribe(self, channel: str) -> "redis.client.PubSub":
        """Subscribe to `channel` and return the live PubSub handle.

        Args:
            channel: The channel name to subscribe to.

        Returns:
            A real, already-subscribed `redis.client.PubSub` object -
            the caller reads messages off it directly (e.g. via
            `get_message(timeout=...)`), exactly the same object
            redis-py itself already provides; this method adds nothing
            on top beyond constructing it and calling
            `.subscribe(channel)`, deliberately not wrapping/hiding
            redis-py's own already-complete message-consuming API.
        """

        pubsub = self._client.pubsub()
        pubsub.subscribe(channel)
        return pubsub
