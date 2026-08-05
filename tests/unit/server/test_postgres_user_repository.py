"""test_postgres_user_repository.py: Stage I1 - dedicated tests for
PostgresUserRepository (server/persistence/postgres_user_repository.py)
that go beyond the shared Protocol contract already exercised by
test_user_repository_contract.py:

- The Postgres-side equivalents of test_user_repository.py's own two
  SQLite-internals tests (proving no-plaintext-storage and
  real-per-user-salting against Postgres's own raw stored row, via a
  throwaway direct asyncpg connection - the Postgres analog of
  reaching into SqliteUserRepository's own private `_connection`).
- The `read_replica_dsn` wiring itself (get_rating actually reads from
  the separately-injected replica DSN, not silently from the primary).

Every test in this file requires a real, reachable Postgres instance -
marked `requires_postgres` throughout, skipping cleanly (via
conftest.py's own `reset_postgres_users_table_or_skip`) when none is
reachable, exactly like the Postgres side of the contract suite.
"""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from server.persistence.postgres_user_repository import PostgresUserRepository
from server.persistence.user_repository import UserRepositoryError
from tests.unit.server.conftest import TEST_POSTGRES_DSN, reset_postgres_users_table_or_skip

pytestmark = pytest.mark.requires_postgres


async def _fetch_raw_row(dsn: str, username: str):
    connection = await asyncpg.connect(dsn)
    try:
        return await connection.fetchrow(
            "SELECT password_hash, salt FROM users WHERE username = $1", username
        )
    finally:
        await connection.close()


def _repo() -> PostgresUserRepository:
    reset_postgres_users_table_or_skip(TEST_POSTGRES_DSN)
    return PostgresUserRepository(dsn=TEST_POSTGRES_DSN)


def test_password_is_never_stored_in_plaintext_anywhere_in_the_stored_row():
    repo = _repo()
    plaintext_password = "correct horse battery staple"
    repo.create_account("alice", plaintext_password)

    # Reach into the real underlying Postgres row directly, via a
    # throwaway raw asyncpg connection - the Postgres analog of
    # test_user_repository.py's own `repo._connection.execute(...)` -
    # the only way to prove a NEGATIVE ("this raw stored data does not
    # contain the plaintext anywhere").
    row = asyncio.run(_fetch_raw_row(TEST_POSTGRES_DSN, "alice"))
    password_hash, salt = row["password_hash"], row["salt"]

    assert password_hash != plaintext_password
    assert plaintext_password not in password_hash
    assert plaintext_password not in salt


def test_two_users_with_the_same_password_get_different_stored_hashes():
    repo = _repo()
    shared_password = "correct horse battery staple"
    repo.create_account("alice", shared_password)
    repo.create_account("bob", shared_password)

    alice_row = asyncio.run(_fetch_raw_row(TEST_POSTGRES_DSN, "alice"))
    bob_row = asyncio.run(_fetch_raw_row(TEST_POSTGRES_DSN, "bob"))

    # Real, per-user salting - not a shared or absent salt - is what
    # makes this true: identical plaintext passwords must never produce
    # identical stored hashes, on Postgres exactly as on SQLite.
    assert alice_row["salt"] != bob_row["salt"]
    assert alice_row["password_hash"] != bob_row["password_hash"]

    # Both accounts still independently verify correctly despite the
    # different salts/hashes - proving the difference isn't a bug.
    assert repo.verify_login("alice", shared_password) is True
    assert repo.verify_login("bob", shared_password) is True


def test_get_rating_reads_from_the_injected_read_replica_dsn_not_the_primary():
    # A genuinely distinct (bogus, unreachable) read_replica_dsn,
    # separate from a real, working primary `dsn` - proves get_rating's
    # SQL round trip actually goes out over `read_replica_dsn`, not
    # silently falling back to the working `dsn` inside get_rating
    # itself: construction/create_account (routed to the real primary)
    # succeed, but get_rating (routed to the bogus replica) fails.
    reset_postgres_users_table_or_skip(TEST_POSTGRES_DSN)
    bogus_replica_dsn = "postgresql://kfchess:kfchess@localhost:1/kfchess_test"
    repo = PostgresUserRepository(dsn=TEST_POSTGRES_DSN, read_replica_dsn=bogus_replica_dsn)
    repo.create_account("alice", "correct horse battery staple")

    with pytest.raises(UserRepositoryError):
        repo.get_rating("alice")


def test_get_rating_reads_the_real_value_when_no_replica_dsn_is_injected():
    # The default (read_replica_dsn=None) falls back to the primary
    # `dsn` - the ordinary, single-instance case this stage's own
    # scope actually needs (see this class's own "READ-REPLICA
    # ELIGIBILITY" docstring section: no real replica exists yet).
    reset_postgres_users_table_or_skip(TEST_POSTGRES_DSN)
    repo = PostgresUserRepository(dsn=TEST_POSTGRES_DSN)
    repo.create_account("alice", "correct horse battery staple")

    assert repo.get_rating("alice") == 1200
