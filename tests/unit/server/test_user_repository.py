"""Unit tests for Stage D1's standalone, server-side user store
(server/persistence/user_repository.py) - built and tested completely
in isolation from networking, mirroring this project's own established
"build and test a new capability in isolation before wiring it to the
protocol" pattern (Stage B2's GameSession before Stage B3's GameServer
wired it up). Every test uses an in-memory SQLite database
(db_path=":memory:") - never touches disk, per this stage's own
"support both a real file path and :memory: so tests never touch disk"
requirement.
"""

from __future__ import annotations

import sqlite3

import pytest

from server.persistence.user_repository import DEFAULT_STARTING_RATING, UserNotFoundError, UserRepository


def _repo() -> UserRepository:
    return UserRepository(db_path=":memory:")


def test_create_account_succeeds_for_a_new_username_with_the_default_starting_rating():
    repo = _repo()

    created = repo.create_account("alice", "correct horse battery staple")

    assert created is True
    assert repo.get_rating("alice") == DEFAULT_STARTING_RATING


def test_create_account_fails_for_a_duplicate_username_and_leaves_the_original_untouched():
    repo = _repo()
    repo.create_account("alice", "first-password")
    repo.update_rating("alice", 1350)  # give the original account distinguishable state

    created_again = repo.create_account("alice", "a-completely-different-password")

    assert created_again is False
    # The original account's password and rating are both untouched by
    # the failed duplicate attempt - not silently overwritten.
    assert repo.verify_login("alice", "first-password") is True
    assert repo.verify_login("alice", "a-completely-different-password") is False
    assert repo.get_rating("alice") == 1350


def test_verify_login_succeeds_with_the_correct_password():
    repo = _repo()
    repo.create_account("alice", "correct horse battery staple")

    assert repo.verify_login("alice", "correct horse battery staple") is True


def test_verify_login_fails_with_a_wrong_password():
    repo = _repo()
    repo.create_account("alice", "correct horse battery staple")

    assert repo.verify_login("alice", "wrong password") is False


def test_verify_login_fails_for_a_nonexistent_username_indistinguishably_from_a_wrong_password():
    repo = _repo()
    repo.create_account("alice", "correct horse battery staple")

    # Same return type/value (False) for "wrong password" and "username
    # never existed at all" - see module docstring's own "username-
    # enumeration-safety" section for why this must never differ.
    wrong_password_result = repo.verify_login("alice", "wrong password")
    nonexistent_user_result = repo.verify_login("someone-who-never-signed-up", "anything")

    assert wrong_password_result is False
    assert nonexistent_user_result is False
    assert type(wrong_password_result) is type(nonexistent_user_result)


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


def test_get_rating_and_update_rating_round_trip():
    repo = _repo()
    repo.create_account("alice", "correct horse battery staple")

    repo.update_rating("alice", 1450)

    assert repo.get_rating("alice") == 1450


def test_get_rating_for_a_nonexistent_username_raises_user_not_found_error():
    repo = _repo()

    with pytest.raises(UserNotFoundError):
        repo.get_rating("someone-who-never-signed-up")


def test_update_rating_for_a_nonexistent_username_raises_user_not_found_error():
    repo = _repo()

    with pytest.raises(UserNotFoundError):
        repo.update_rating("someone-who-never-signed-up", 1300)


def test_a_real_file_backed_database_path_also_works(tmp_path):
    # Proves this class also genuinely supports a real file path (not
    # just ":memory:") - constructed against a tmp_path fixture so this
    # test still never touches any REAL, persistent project file.
    db_path = str(tmp_path / "kf_chess_users_test.db")

    repo = UserRepository(db_path=db_path)
    repo.create_account("alice", "correct horse battery staple")

    # A second, independent connection to the SAME real file sees the
    # same, real, committed data - proving this isn't just an in-memory
    # illusion.
    repo_reopened = UserRepository(db_path=db_path)
    assert repo_reopened.verify_login("alice", "correct horse battery staple") is True
    assert repo_reopened.get_rating("alice") == DEFAULT_STARTING_RATING
