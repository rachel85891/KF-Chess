"""Stage H1: SqliteUserRepository must structurally satisfy the new
UserRepository Protocol (server/persistence/user_repository_protocol.py).

Stage I1 adds the same isinstance assertion for PostgresUserRepository
- marked `requires_postgres` because, unlike a plain isinstance check
against duck-typed structure alone, actually CONSTRUCTING a
PostgresUserRepository requires a real, live Postgres connection right
away (its own __init__ ensures the `users` table exists immediately,
mirroring SqliteUserRepository's own "construction proves the backend
is reachable" behavior) - so this assertion skips cleanly, rather than
erroring, when no real Postgres is reachable."""

from __future__ import annotations

import pytest

from server.persistence.postgres_user_repository import PostgresUserRepository
from server.persistence.user_repository import SqliteUserRepository
from server.persistence.user_repository_protocol import UserRepository
from tests.unit.server.conftest import TEST_POSTGRES_DSN, reset_postgres_users_table_or_skip


def test_sqlite_user_repository_is_a_user_repository():
    repo = SqliteUserRepository(db_path=":memory:")

    assert isinstance(repo, UserRepository)


@pytest.mark.requires_postgres
def test_postgres_user_repository_is_a_user_repository():
    reset_postgres_users_table_or_skip(TEST_POSTGRES_DSN)
    repo = PostgresUserRepository(dsn=TEST_POSTGRES_DSN)

    assert isinstance(repo, UserRepository)
