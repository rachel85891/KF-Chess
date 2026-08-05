"""Unit tests for Stage D1's standalone, server-side user store
(server/persistence/user_repository.py) - built and tested completely
in isolation from networking, mirroring this project's own established
"build and test a new capability in isolation before wiring it to the
protocol" pattern (Stage B2's GameSession before Stage B3's GameServer
wired it up). Every test uses an in-memory SQLite database
(db_path=":memory:") - never touches disk, per this stage's own
"support both a real file path and :memory: so tests never touch disk"
requirement.

STAGE I1 RE-SCOPE: this file originally held 11 tests. 9 of them used
only the four public UserRepository Protocol methods and have moved to
the new, genuinely backend-agnostic
tests/unit/server/test_user_repository_contract.py, parameterized over
both SqliteUserRepository and PostgresUserRepository - see that file's
own module docstring for the full split rationale. The 2 tests below
are the ones that stay HERE, specifically because they reach into
SqliteUserRepository's own private `_connection` attribute - a
SQLite-only shape a Postgres-backed class doesn't share - to prove a
real negative about the raw stored row (no plaintext storage, real
per-user salting). They are re-scoped, by this comment, as SQLite-
implementation-specific proofs of a PROPERTY that PostgresUserRepository
must satisfy too, just verified through Postgres's own equivalent raw-
row access instead - see
tests/unit/server/test_postgres_user_repository.py for those direct
Postgres-side equivalents.
"""

from __future__ import annotations

from server.persistence.user_repository import SqliteUserRepository


def _repo() -> SqliteUserRepository:
    return SqliteUserRepository(db_path=":memory:")


def test_password_is_never_stored_in_plaintext_anywhere_in_the_stored_row():
    repo = _repo()
    plaintext_password = "correct horse battery staple"
    repo.create_account("alice", plaintext_password)

    # Reach into the real underlying SQLite row directly - the only way
    # to prove a NEGATIVE ("this raw stored data does not contain the
    # plaintext anywhere"), which UserRepository's own public API
    # deliberately never exposes (there is no get_password_hash-style
    # method - exposing one would itself be a bad, unnecessary API).
    cursor = repo._connection.execute(
        "SELECT password_hash, salt FROM users WHERE username = ?", ("alice",)
    )
    password_hash, salt = cursor.fetchone()

    assert password_hash != plaintext_password
    assert plaintext_password not in password_hash
    assert plaintext_password not in salt


def test_two_users_with_the_same_password_get_different_stored_hashes():
    repo = _repo()
    shared_password = "correct horse battery staple"
    repo.create_account("alice", shared_password)
    repo.create_account("bob", shared_password)

    alice_hash, alice_salt = repo._connection.execute(
        "SELECT password_hash, salt FROM users WHERE username = ?", ("alice",)
    ).fetchone()
    bob_hash, bob_salt = repo._connection.execute(
        "SELECT password_hash, salt FROM users WHERE username = ?", ("bob",)
    ).fetchone()

    # Real, per-user salting - not a shared or absent salt - is what
    # makes this true: identical plaintext passwords must never produce
    # identical stored hashes.
    assert alice_salt != bob_salt
    assert alice_hash != bob_hash

    # Both accounts still independently verify correctly despite the
    # different salts/hashes - proving the difference isn't a bug.
    assert repo.verify_login("alice", shared_password) is True
    assert repo.verify_login("bob", shared_password) is True
