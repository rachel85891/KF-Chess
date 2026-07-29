"""Stage H1: SqliteUserRepository must structurally satisfy the new
UserRepository Protocol (server/persistence/user_repository_protocol.py)."""

from __future__ import annotations

from server.persistence.user_repository import SqliteUserRepository
from server.persistence.user_repository_protocol import UserRepository


def test_sqlite_user_repository_is_a_user_repository():
    repo = SqliteUserRepository(db_path=":memory:")

    assert isinstance(repo, UserRepository)
