"""test_user_repository_contract.py: Stage I1 - the real, backend-
agnostic "same Protocol, two backends" proof Implementation_Plan.md's
own I1 acceptance criteria was actually asking for ("the exact same
UserRepository Protocol test suite from H1 ... passes unchanged").

No such parameterized suite existed before this stage - it was split
out of tests/unit/server/test_user_repository.py's original 11 tests
(see that file's own updated module docstring for the full
resolution): the 9 tests below use ONLY the four public Protocol
methods (create_account/verify_login/get_rating/update_rating), so
they run unchanged against BOTH SqliteUserRepository (always) and
PostgresUserRepository (marked `requires_postgres`, skipping cleanly
- see conftest.py's own `reset_postgres_users_table_or_skip` - when
no real Postgres is reachable). The other 2 of the original 11 reach
into SqliteUserRepository's own private `_connection` attribute to
prove a real negative about the raw stored row - a SQLite-only shape
a Postgres-backed class doesn't share - so those stayed in
test_user_repository.py, re-scoped by comment there, with their own
Postgres-side equivalents added to test_postgres_user_repository.py
instead.

Two fixtures, not one, because of one extra wrinkle: 8 of these 9
tests just need ONE ready-to-use repository instance per test. The
9th (test_a_second_independently_constructed_repository_instance_
sees_the_same_committed_data, the direct descendant of the original
suite's own "a real file-backed database path also works" test) needs
to construct a SECOND, independent instance pointed at the SAME
underlying durable store and see the SAME committed data - SQLite's
own ":memory:" convention is deliberately single-connection-only and
cannot prove that (a second ":memory:" connection is a completely
separate, empty database), so `repo_factory` uses a real tmp_path-
backed file for the SQLite side instead (Postgres's own dsn is
already "real" either way - a fresh `PostgresUserRepository(dsn=...)`
naturally sees whatever is already committed at that dsn).
"""

from __future__ import annotations

from typing import Callable

import pytest

from server.persistence.postgres_user_repository import PostgresUserRepository
from server.persistence.user_repository import DEFAULT_STARTING_RATING, SqliteUserRepository, UserNotFoundError
from server.persistence.user_repository_protocol import UserRepository
from tests.unit.server.conftest import TEST_POSTGRES_DSN, reset_postgres_users_table_or_skip

_BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.requires_postgres)]


@pytest.fixture(params=_BACKENDS)
def repo(request: pytest.FixtureRequest) -> UserRepository:
    """A single, ready-to-use UserRepository instance - either backend,
    always starting from a genuinely empty `users` store."""

    if request.param == "sqlite":
        return SqliteUserRepository(db_path=":memory:")

    reset_postgres_users_table_or_skip(TEST_POSTGRES_DSN)
    return PostgresUserRepository(dsn=TEST_POSTGRES_DSN)


@pytest.fixture(params=_BACKENDS)
def repo_factory(request: pytest.FixtureRequest, tmp_path) -> Callable[[], UserRepository]:
    """A zero-arg factory that builds a NEW UserRepository instance,
    every call, pointed at the SAME underlying durable store - see
    this module's own docstring for why this needs a real tmp_path
    file for the SQLite side rather than ":memory:"."""

    if request.param == "sqlite":
        db_path = str(tmp_path / "contract_durability_test.db")
        return lambda: SqliteUserRepository(db_path=db_path)

    reset_postgres_users_table_or_skip(TEST_POSTGRES_DSN)
    return lambda: PostgresUserRepository(dsn=TEST_POSTGRES_DSN)


def test_create_account_succeeds_for_a_new_username_with_the_default_starting_rating(repo: UserRepository):
    created = repo.create_account("alice", "correct horse battery staple")

    assert created is True
    assert repo.get_rating("alice") == DEFAULT_STARTING_RATING


def test_create_account_fails_for_a_duplicate_username_and_leaves_the_original_untouched(repo: UserRepository):
    repo.create_account("alice", "first-password")
    repo.update_rating("alice", 1350)  # give the original account distinguishable state

    created_again = repo.create_account("alice", "a-completely-different-password")

    assert created_again is False
    # The original account's own password and rating are both untouched
    # by the failed duplicate attempt - not silently overwritten.
    assert repo.verify_login("alice", "first-password") is True
    assert repo.verify_login("alice", "a-completely-different-password") is False
    assert repo.get_rating("alice") == 1350


def test_verify_login_succeeds_with_the_correct_password(repo: UserRepository):
    repo.create_account("alice", "correct horse battery staple")

    assert repo.verify_login("alice", "correct horse battery staple") is True


def test_verify_login_fails_with_a_wrong_password(repo: UserRepository):
    repo.create_account("alice", "correct horse battery staple")

    assert repo.verify_login("alice", "wrong password") is False


def test_verify_login_fails_for_a_nonexistent_username_indistinguishably_from_a_wrong_password(repo: UserRepository):
    repo.create_account("alice", "correct horse battery staple")

    # Same return type/value (False) for "wrong password" and
    # "username never existed at all" - see
    # server/persistence/user_repository.py's own "USERNAME-
    # ENUMERATION-SAFETY PROPERTY" docstring section for why this must
    # never differ, on EITHER backend.
    wrong_password_result = repo.verify_login("alice", "wrong password")
    nonexistent_user_result = repo.verify_login("someone-who-never-signed-up", "anything")

    assert wrong_password_result is False
    assert nonexistent_user_result is False
    assert type(wrong_password_result) is type(nonexistent_user_result)


def test_get_rating_and_update_rating_round_trip(repo: UserRepository):
    repo.create_account("alice", "correct horse battery staple")

    repo.update_rating("alice", 1450)

    assert repo.get_rating("alice") == 1450


def test_get_rating_for_a_nonexistent_username_raises_user_not_found_error(repo: UserRepository):
    with pytest.raises(UserNotFoundError):
        repo.get_rating("someone-who-never-signed-up")


def test_update_rating_for_a_nonexistent_username_raises_user_not_found_error(repo: UserRepository):
    with pytest.raises(UserNotFoundError):
        repo.update_rating("someone-who-never-signed-up", 1300)


def test_a_second_independently_constructed_repository_instance_sees_the_same_committed_data(
    repo_factory: Callable[[], UserRepository],
):
    repo = repo_factory()
    repo.create_account("alice", "correct horse battery staple")

    # A second, independent instance pointed at the SAME underlying
    # store sees the same, real, committed data - proving this isn't
    # just an in-process/single-connection illusion, on either backend.
    repo_reopened = repo_factory()
    assert repo_reopened.verify_login("alice", "correct horse battery staple") is True
    assert repo_reopened.get_rating("alice") == DEFAULT_STARTING_RATING
