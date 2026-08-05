"""conftest.py: shared, real-infra-connectivity helpers for
tests/unit/server/ - Stage I1's Postgres helpers and Stage I2's Redis
helpers, combined here since both stages independently added a
conftest.py at this same path in parallel (see each stage's own section
below for its own full reasoning).

===== STAGE I1 (PostgreSQL) =====
Shared, real-Postgres-connectivity helpers used by both
`test_user_repository_contract.py` (the parameterized "same contract,
two backends" suite) and `test_postgres_user_repository.py` (the
Postgres-side equivalents of `test_user_repository.py`'s own two
`_connection`-reaching tests) - factored out here, rather than
duplicated in both files, since both need the exact same "attempt one
real connection, pytest.skip(...) cleanly (not an error) if
unreachable" behavior.

No real Postgres is guaranteed reachable in every environment this
suite runs in (Stage I0 itself found the Docker daemon unavailable in
at least one real sandbox) - see pytest.ini's own `requires_postgres`
marker registration for the project-wide precedent this mirrors (the
existing `slow` marker).

===== STAGE I2 (Redis) =====
Shared, real-Redis-connectivity helper used by both
`test_session_coordinator_contract.py` (the parameterized "same
contract, two backends" suite) and `test_redis_pubsub.py` - factored
out here, rather than duplicated in both files, since both need the
exact same "attempt one real connection, pytest.skip(...) cleanly (not
an error) if unreachable" behavior.

No real Redis is guaranteed reachable in every environment this suite
runs in (Stage I0 itself found the Docker daemon unavailable in at
least one real sandbox, re-confirmed directly in this one too) - see
pytest.ini's own `requires_redis` marker registration for the
project-wide precedent this mirrors (the existing `slow` marker, and
Stage I1's own `requires_postgres` marker for the identical reasoning
applied to Postgres).
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import pytest
import redis

# ===== STAGE I1 (PostgreSQL) =====

# Overridable via the TEST_POSTGRES_DSN env var (e.g. a real CI runner
# with its own Postgres service container) - defaults to the same
# credentials/db name deploy/docker-compose.yml's own `postgres`
# service already establishes, just against `localhost` rather than
# the `postgres` service-name-as-DNS Compose provides between
# containers, since these tests run directly on the host, not inside
# the `server` container.
TEST_POSTGRES_DSN = os.environ.get(
    "TEST_POSTGRES_DSN", "postgresql://kfchess:kfchess@localhost:5432/kfchess_test"
)


async def _drop_users_table(dsn: str) -> None:
    """Connect once and drop `users` if it exists - this both PROVES
    real connectivity (a failed connect propagates directly) and
    resets state for test isolation, in a single real round trip.
    `PostgresUserRepository`'s own constructor recreates the table
    (`CREATE TABLE IF NOT EXISTS`) immediately afterward.

    `timeout=2` (test-probe-only, not applied to
    PostgresUserRepository's own real connections): verified directly
    on this dev machine, a refused connection to an unreachable
    localhost:5432 otherwise takes ~4 real wall-clock seconds to raise
    (some OS-level dual-stack IPv6-then-IPv4 fallback delay) - with a
    dozen-plus requires_postgres tests each independently probing
    connectivity, that adds well over a minute to every "no real
    Postgres here" run. A short, test-only timeout keeps the whole
    suite's own "skip cleanly and fast when infra is absent" property
    actually fast, without changing anything about how the real
    PostgresUserRepository class itself connects.
    """

    connection = await asyncpg.connect(dsn, timeout=2)
    try:
        await connection.execute("DROP TABLE IF EXISTS users")
    finally:
        await connection.close()


def reset_postgres_users_table_or_skip(dsn: str = TEST_POSTGRES_DSN) -> None:
    """Attempt one real, throwaway connection to `dsn` and drop the
    `users` table if present; `pytest.skip(...)` (not an error) if no
    real Postgres is reachable at all - the one place this "real
    infra may not exist here" check is actually made, per this
    module's own docstring."""

    try:
        asyncio.run(_drop_users_table(dsn))
    except Exception as exc:  # noqa: BLE001 - deliberately broad:
        # any connection failure at all (refused, DNS, auth,
        # timeout, ...) means "no real Postgres reachable here", not
        # "this specific exception type means that".
        pytest.skip(f"no real Postgres reachable at {dsn!r}: {exc!r}")


# ===== STAGE I2 (Redis) =====

# Overridable via the TEST_REDIS_URL env var (e.g. a real CI runner
# with its own Redis service container) - defaults to the same
# host/port deploy/docker-compose.yml's own `redis` service already
# establishes, just against `localhost` rather than the `redis`
# service-name-as-DNS Compose provides between containers, since
# these tests run directly on the host, not inside the `server`
# container. DB index 0 - same as docker-compose.yml's own
# REDIS_URL - test data is namespaced by a unique per-test key
# prefix (see test files) rather than a separate DB index, so tests
# never need a destructive FLUSHDB against whatever else might
# already be using this same real Redis instance.
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")


def _real_redis_client_or_skip(url: str = TEST_REDIS_URL) -> redis.Redis:
    """Attempt one real, throwaway PING against `url` and return a
    connected client if it succeeds; `pytest.skip(...)` (not an
    error) if no real Redis is reachable at all - the one place
    this "real infra may not exist here" check is actually made,
    per this module's own docstring."""

    # A short, explicit connect timeout - without one, an
    # unreachable host can take several real seconds (OS-level TCP
    # timeout) to fail rather than refuse immediately, making every
    # `requires_redis` test slow to SKIP in exactly the "no real
    # Redis here" environment this marker exists for in the first
    # place.
    client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.2)
    try:
        client.ping()
    except Exception as exc:  # noqa: BLE001 - deliberately broad:
        # any connection failure at all (refused, DNS, timeout, ...)
        # means "no real Redis reachable here", not "this specific
        # exception type means that".
        pytest.skip(f"no real Redis reachable at {url!r}: {exc!r}")
    return client


@pytest.fixture
def redis_client_or_skip():
    """A FACTORY fixture (returns a callable, not a client
    directly) - a test that needs more than one independent real
    connection (e.g. test_redis_pubsub.py's own "publish on one
    connection, receive on another" proof) calls the returned
    factory as many times as it needs separate clients. Exposed as
    a fixture (not a plain importable function) so every test file
    under tests/unit/server/ gets it for free via pytest's own
    conftest.py discovery, with no cross-test-file import needed
    (this project's test directories are deliberately not packages
    - no `__init__.py` - so a plain `from tests...import` would be
    fragile here)."""

    return _real_redis_client_or_skip
