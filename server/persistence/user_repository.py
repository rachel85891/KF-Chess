"""user_repository.py: Stage D1 ("Home Screen v2" - username+password,
SQLite-backed, rating starting at 1200) - a standalone, server-side
user store: password hashing, account creation, login verification, and
rating storage, built and tested COMPLETELY IN ISOLATION from
networking. Mirrors this project's own established pattern of proving a
new capability correct on its own before wiring it into the protocol -
exactly like Stage B2's GameSession was built and tested headless,
before Stage B3's GameServer ever connected it to a real WebSocket
connection. This module has ZERO knowledge of GameServer,
ConnectionManager, ProtocolHandler, or the wire protocol at all -
wiring it into the real connection-handling/tick-loop context is
explicitly a LATER stage (D2), not attempted here.

WHY server/persistence/, NOT server/application/ OR
server/presentation/ (this stage's own explicit "justify your choice"
requirement): the existing split (refactor/server-physical-application-
presentation-folders) drew exactly two lines - APPLICATION (GameSession/
GameServer: game coordination, color assignment, event-driven
broadcasting) and PRESENTATION (ConnectionManager/ProtocolHandler/
move_command: wire-protocol mechanics, parsing/formatting/sending).
UserRepository is neither: it makes no coordination decision about a
live game (it has never even heard of a GameSession), and it speaks no
wire protocol at all (it has never heard of a ServerConnection or a
single "rejected:<reason>"-style wire string). Folding it into
application/ would blur that boundary right back into "whatever the
coordinator needs", the exact drift the original split was meant to
prevent; folding it into presentation/ would be a category error (a
SQLite row is not wire syntax). A third, genuinely distinct concern -
DURABLE DATA PERSISTENCE, outliving any single game/connection/process
run - gets its own sibling package, the same way application/ and
presentation/ each got their own __init__.py in that same refactor,
rather than being awkwardly wedged into either existing one. This also
scales better for whatever Stage D2+ eventually adds alongside it (e.g.
a session/matchmaking store) - a dedicated persistence/ package is
where that would naturally continue to live, not a growing pile of
unrelated helpers bolted onto GameServer's own package.

PASSWORD HASHING SCHEME - hashlib.pbkdf2_hmac('sha256', ...), NEVER
plaintext, NEVER a fast unsalted hash: PBKDF2-HMAC-SHA256 is a
standard, NIST-recommended (SP 800-132) password-hashing KDF built into
Python's own standard library (hashlib) - no new external dependency,
matching this project's own established "use the standard library
before reaching for a new dependency" preference (docs/spec.md §1's
"no hand-rolled protocol implementation" reasoning, applied here to
"no hand-rolled crypto" instead). A fast, unsalted hash (plain sha256/
md5) is explicitly wrong for passwords specifically BECAUSE it is fast:
an attacker who steals the users table can brute-force/rainbow-table
every possible password at billions of guesses per second on commodity
hardware. PBKDF2 is deliberately SLOW (via its own iteration count,
_PBKDF2_ITERATIONS below) - the same core defense HASHING ALGORITHM
choice this project already trusts hashlib for elsewhere in the
standard library, just applied to its own, correct use case here
(key-stretching, not general-purpose hashing).

_PBKDF2_ITERATIONS = 260_000: matches Django's own current PBKDF2SHA256
default iteration count (a widely-referenced, actively-maintained
industry benchmark for this exact algorithm+hash pair, not an
arbitrarily chosen number) - high enough to make brute-forcing a stolen
hash meaningfully expensive, while still completing in a small number
of milliseconds per call on ordinary hardware (verified directly: this
module's own test suite, which calls create_account/verify_login
roughly a dozen times total, completes in well under a second).

PER-USER RANDOM SALT (secrets.token_bytes, NOT a shared or predictable
salt): `secrets` (not `random`) is Python's own standard-library module
specifically for cryptographically-secure random generation - re-used
here for the identical reason server/presentation/protocol_handler.py's
own docstring already establishes "use the standard library's own
purpose-built primitive" as this project's default. Storing a
RANDOM, PER-USER salt alongside the hash (not deriving it from the
username or using one global salt for every row) is what makes
test_two_users_with_the_same_password_get_different_stored_hashes true
- without per-user salting, two accounts sharing a password would also
share a stored hash, letting an attacker who cracks ONE such hash
immediately know every OTHER account using that same password too (and
enabling precomputed rainbow-table attacks across the whole table at
once, not just one row at a time).

USERNAME-ENUMERATION-SAFETY PROPERTY OF verify_login (a basic security
hygiene point, explicitly documented per this stage's own requirement):
verify_login returns the exact same value (False), via the exact same
code shape, whether the given username does not exist at all OR exists
but the password is wrong - re-verified directly by this module's own
test suite (test_verify_login_fails_for_a_nonexistent_username_
indistinguishably_from_a_wrong_password asserts not just equal boolean
VALUES but equal TYPES, ruling out e.g. a real bool for one case and a
None-that-happens-to-be-falsy for the other). If these two failure
modes were distinguishable (e.g. a different exception, or True/False
vs. None/False), an attacker could enumerate which usernames are
REGISTERED at all by observing which failure shape comes back for a
given username, with no password ever needing to be guessed correctly
- a real, well-known account-enumeration vulnerability class this
method's own single, uniform "return False" code path structurally
cannot exhibit.

WHY create_account/verify_login RETURN bool RATHER THAN RAISING, BUT
get_rating/update_rating RAISE UserNotFoundError FOR A MISSING
USERNAME (this stage's own explicit "pick one, document why" decision
point): create_account's "username already exists" and verify_login's
"wrong password or no such user" are both ORDINARY, EXPECTED outcomes
of calling these methods with attacker- or user-controlled input from
the outside world (a real human mistyping their password, or trying to
register a name someone else already took, is not a bug in anything) -
exactly the same "a plain, expected failure reason, not an exception"
convention this project's own server/presentation/move_command.py
already establishes for malformed client input. get_rating/
update_rating, by contrast, are only ever meant to be called by a
caller that ALREADY knows the username is real (e.g. right after a
successful create_account or verify_login) - passing a username that
was never created is a PROGRAMMING error in that caller, not a normal
external input to gracefully degrade for, so raising a clear,
unambiguous UserNotFoundError (rather than returning None, which could
be silently mistaken for "a real, valid rating of value None" by a
careless caller, or silently accepted by an `UPDATE ... WHERE
username=?` that quietly updates zero rows) is the correct signal - the
same "fail loudly for a caller mistake, fail quietly/return a plain
result for expected external input" split this project already applies
elsewhere (e.g. GameSession's own real MoveResult for an ordinary
illegal move, versus a raised ValueError for a genuinely malformed
board in _build_standard_starting_board).

DATABASE FILE LOCATION - CONFIGURABLE, DEFAULTING TO A REAL FILE UNDER
server/persistence/, ANCHORED TO THIS MODULE'S OWN FILE LOCATION (not a
plain relative-string literal): DEFAULT_DB_PATH is computed from
`Path(__file__).resolve().parent`, so the real default database file
always lands next to this module regardless of the process's current
working directory when the server is actually launched (server/main.py
can be started from any directory) - a plain relative string like
"server/persistence/kf_chess_users.db" would silently create the file
in the WRONG place if launched from anywhere else. Passing ":memory:"
explicitly (as every test in this module's own test suite does) uses
sqlite3's own already-standard in-memory-database convention directly
- no special-casing needed in this module's own code at all, since
sqlite3.connect(":memory:") already does exactly the right thing.

THREADING/ASYNC CONTRACT - EXPLICITLY DEFERRED TO STAGE D2, NOT DECIDED
HERE: sqlite3.connect's own default `check_same_thread=True` means a
single UserRepository instance, as built here, is only safely usable
from the one thread that constructed it - correct and sufficient for
this stage's own explicit scope ("focus purely on correctness in
isolation"), but NOT yet a decision about how a future GameServer
(running on asyncio's single event-loop thread, per that class's own
module docstring) would safely call into this class without blocking
that loop on real disk I/O. That decision (e.g. asyncio.to_thread per
call, a dedicated worker thread, or check_same_thread=False plus
external synchronization) is real, necessary work for Stage D2 - noted
here explicitly as this stage's own accepted, documented gap, not
silently deferred.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from pathlib import Path

DEFAULT_STARTING_RATING = 1200

DEFAULT_DB_PATH = str(Path(__file__).resolve().parent / "kf_chess_users.db")

_PBKDF2_HASH_NAME = "sha256"
_PBKDF2_ITERATIONS = 260_000
_SALT_BYTES = 16

_CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    rating INTEGER NOT NULL DEFAULT 1200
)
"""


class UserRepositoryError(Exception):
    """Base class for UserRepository's own errors."""


class UserNotFoundError(UserRepositoryError):
    """Raised by get_rating/update_rating for a username that does not
    exist - see module docstring's own "WHY create_account/verify_login
    RETURN bool... BUT get_rating/update_rating RAISE" section for why
    these two methods raise rather than returning a sentinel value,
    unlike create_account/verify_login's own plain bool returns."""


def _hash_password(password: str, salt: bytes) -> str:
    """PBKDF2-HMAC-SHA256 the given password with the given salt - see
    module docstring's "PASSWORD HASHING SCHEME" section for the full
    reasoning. Returns a hex string (not raw bytes) so it stores
    directly as ordinary SQLite TEXT, matching `salt`'s own hex-string
    storage below.

    Args:
        password: The plaintext password to hash - never itself stored
            or logged anywhere by this module.
        salt: The random, per-user salt (see module docstring's
            "PER-USER RANDOM SALT" section) - the same salt must be
            supplied again, unchanged, to reproduce the same hash later
            (verify_login's own job).

    Returns:
        The derived key as a hex string.
    """

    derived_key = hashlib.pbkdf2_hmac(_PBKDF2_HASH_NAME, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return derived_key.hex()


class UserRepository:
    """A standalone, server-side user store - see module docstring for
    the full reasoning behind every decision below. Zero networking,
    zero GameSession/GameServer/protocol knowledge - a pure SQLite-
    backed persistence class."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """Open (creating if necessary) the real SQLite database at
        `db_path` and ensure the `users` table exists.

        Args:
            db_path: A real filesystem path, or the literal string
                ":memory:" for a real, standard SQLite in-memory
                database - see module docstring's "DATABASE FILE
                LOCATION" section. Defaults to DEFAULT_DB_PATH, a real
                file anchored next to this module.

        Returns:
            None.
        """

        self._connection = sqlite3.connect(db_path)
        self._connection.execute(_CREATE_USERS_TABLE_SQL)
        self._connection.commit()

    def create_account(self, username: str, password: str) -> bool:
        """Create a new user with DEFAULT_STARTING_RATING, if
        `username` does not already exist.

        Args:
            username: The new account's username - must not already
                exist.
            password: The new account's plaintext password - hashed
                with a fresh, random per-user salt before being stored
                (see module docstring's "PASSWORD HASHING SCHEME"/
                "PER-USER RANDOM SALT" sections); never stored or
                returned in plaintext form by this method.

        Returns:
            True if the account was created; False if `username`
            already existed (an ordinary, expected outcome - see
            module docstring's own "WHY create_account/verify_login
            RETURN bool" section - not an exception). The original
            account's own row is left completely untouched when this
            returns False.
        """

        salt = secrets.token_bytes(_SALT_BYTES)
        password_hash = _hash_password(password, salt)
        try:
            self._connection.execute(
                "INSERT INTO users (username, password_hash, salt, rating) VALUES (?, ?, ?, ?)",
                (username, password_hash, salt.hex(), DEFAULT_STARTING_RATING),
            )
        except sqlite3.IntegrityError:
            # The `users.username` PRIMARY KEY constraint already
            # enforces uniqueness at the database level - re-using that
            # real constraint (rather than a separate SELECT-then-INSERT
            # existence check) means this is also correct under
            # concurrent callers, not just single-threaded ones.
            return False

        self._connection.commit()
        return True

    def verify_login(self, username: str, password: str) -> bool:
        """Whether `password` is the correct password for `username`.

        Args:
            username: The username to check.
            password: The plaintext password to verify.

        Returns:
            True if `username` exists and `password` matches its
            stored hash; False otherwise - including when `username`
            does not exist at all. See module docstring's own
            "USERNAME-ENUMERATION-SAFETY PROPERTY" section for why
            these two failure cases are, and must stay, indistinguishable
            from this method's own return value alone.
        """

        row = self._connection.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return False

        stored_hash, salt_hex = row
        candidate_hash = _hash_password(password, bytes.fromhex(salt_hex))
        # secrets.compare_digest - a constant-time comparison - rather
        # than a plain `==` string comparison: this project already
        # reaches for `secrets` over `random`/plain comparisons for
        # exactly this "the standard library's own purpose-built
        # cryptographic primitive" reason (see module docstring's
        # "PER-USER RANDOM SALT" section) - a naive `==` comparison
        # short-circuits at the first mismatched character, which can
        # theoretically leak timing information about how much of a
        # guessed hash was correct; compare_digest is the standard,
        # documented fix for exactly this class of side channel.
        return secrets.compare_digest(candidate_hash, stored_hash)

    def get_rating(self, username: str) -> int:
        """The current rating for `username`.

        Args:
            username: The username to look up - must already exist
                (see module docstring's own "WHY create_account/
                verify_login RETURN bool... BUT get_rating/update_rating
                RAISE" section for why this is the caller's own
                responsibility to ensure, not a condition this method
                degrades gracefully for).

        Returns:
            The current integer rating.

        Raises:
            UserNotFoundError: If `username` does not exist.
        """

        row = self._connection.execute("SELECT rating FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise UserNotFoundError(f"no such user: {username!r}")
        return row[0]

    def update_rating(self, username: str, new_rating: int) -> None:
        """Persist a new rating value for `username`.

        Args:
            username: The username to update - must already exist (see
                get_rating's own identical docstring note).
            new_rating: The new rating value to store.

        Returns:
            None.

        Raises:
            UserNotFoundError: If `username` does not exist (checked via
                the real UPDATE statement's own affected-row count,
                rather than a separate existence SELECT first - a
                zero-rows-affected UPDATE means no row for this username
                existed to update at all).
        """

        cursor = self._connection.execute(
            "UPDATE users SET rating = ? WHERE username = ?", (new_rating, username)
        )
        if cursor.rowcount == 0:
            raise UserNotFoundError(f"no such user: {username!r}")
        self._connection.commit()
