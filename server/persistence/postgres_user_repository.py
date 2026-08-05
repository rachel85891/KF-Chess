"""postgres_user_repository.py: Stage I1 - `PostgresUserRepository`, a
second concrete implementation of Stage H1's `UserRepository` Protocol
(server/persistence/user_repository_protocol.py), backed by real
PostgreSQL instead of SQLite - proving that Protocol's own refactor
was genuinely transparent to callers (Server_Design.md §1.3/§1.7/
§1.9/§5.4), the entire point of Stage H1.

SYNC-VS-ASYNC CLIENT CHOICE, AND WHY (this stage's own explicit
"decide and document which, and why" requirement): `asyncpg`,
wrapped per-call in `asyncio.run(...)` so every public method here
keeps the exact same synchronous signature the Protocol already fixes
(`create_account`/`verify_login`/`get_rating`/`update_rating` all
return a plain value, never a coroutine) - the Protocol's own method
shapes are fixed by Stage H1 and must not change. Why `asyncpg`
specifically, rather than a synchronous client like `psycopg2`/
`psycopg`: `asyncpg` is ALREADY this project's own established
Postgres client - it's in requirements.txt and already used by
server/main.py's own Stage I0 `_check_infra_connectivity` - reusing it
avoids adding a SECOND Postgres driver dependency for no reason, and
`asyncio.run(...)` wrapping a real async call from an otherwise-
synchronous call site is already this project's own precedent too
(server/main.py's `_run_startup_connectivity_check` does exactly this
around that same connectivity check). Each public method here opens
one fresh, short-lived connection, does its one operation, and closes
it - no connection pool is retained across calls; pooling is real,
future performance work explicitly out of scope for this stage's own
first correctness pass (see I1_prompt.md's own Background section for
this stage's other explicit scope boundaries).

PASSWORD HASHING: reuses server/persistence/user_repository.py's own
`_hash_password` helper directly (imported, not copy-pasted) - the
exact same PBKDF2-HMAC-SHA256 scheme, the same `_PBKDF2_ITERATIONS`,
the same per-user `secrets.token_bytes` salt approach. See that
module's own docstring for the full reasoning behind each of those
choices; not restated here.

ERRORS: `UserRepositoryError`/`UserNotFoundError` are imported from
server/persistence/user_repository.py, not redefined - `get_rating`/
`update_rating` raise `UserNotFoundError` for a missing username, with
the exact same meaning as `SqliteUserRepository`. A real connection
failure to Postgres itself (the instance is down/unreachable) is
wrapped as `UserRepositoryError` too (see `_connect`, below) - rather
than letting a raw `asyncpg` exception leak across this Protocol seam,
so every caller of a `UserRepository` only ever needs to know about
these two exception types, regardless of which concrete backend is
behind it.

READ-REPLICA ELIGIBILITY: `get_rating` is the one Protocol method
Server_Design.md (§1.7/§5.4) calls out as eligible to read from a
replica (an ordinary read, tolerant of brief replication lag) - the
other three methods either mutate or must observe their own
immediately-prior write, so they always go to the primary. No real
replica exists in this stage's own scope (see I1_prompt.md's own
Background section), so this is implemented as a distinct, separately
-injectable `read_replica_dsn` constructor parameter, defaulting to
the primary `dsn` when not given - purely so a later stage can wire a
real second DSN in without touching this class's method bodies again.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Optional

import asyncpg

from server.persistence.user_repository import (
    DEFAULT_STARTING_RATING,
    UserNotFoundError,
    UserRepositoryError,
    _SALT_BYTES,
    _hash_password,
)

# Mirrors SqliteUserRepository's own `_CREATE_USERS_TABLE_SQL` shape,
# adapted to Postgres's own SQL dialect. No id/SERIAL column: exactly
# like SqliteUserRepository's own schema, `username` alone is already
# the natural primary key - there is no other code anywhere that
# refers to a row by a separate numeric id, so adding one here would
# be pure, unused ceremony.
_CREATE_USERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    rating INTEGER NOT NULL DEFAULT 1200
)
"""


async def _connect(dsn: str) -> asyncpg.Connection:
    """Open one real asyncpg connection to `dsn`, wrapping any
    connection-level failure as `UserRepositoryError` - see this
    module's own "ERRORS" docstring section for why: a caller of this
    Protocol-conforming class should never see a raw `asyncpg`
    exception leak across the seam."""

    try:
        return await asyncpg.connect(dsn)
    except (OSError, asyncpg.PostgresError) as exc:
        raise UserRepositoryError(f"could not connect to Postgres at {dsn!r}: {exc!r}") from exc


class PostgresUserRepository:
    """A real, PostgreSQL-backed implementation of
    server/persistence/user_repository_protocol.py's `UserRepository`
    Protocol - see this module's own docstring for the full reasoning
    behind every design decision below.

    Wiring this into the real running server process (choosing this
    class over `SqliteUserRepository` at the composition root) is
    explicitly deferred to a later stage - see I1_prompt.md's own
    Requirements section. `GameServer.__init__`'s own signature is
    unchanged by this stage."""

    def __init__(self, dsn: str, read_replica_dsn: Optional[str] = None) -> None:
        """Ensure (creating if necessary) the real `users` table exists
        at `dsn`, real Postgres round trip and all - mirrors
        `SqliteUserRepository.__init__`'s own "connect and ensure the
        table exists immediately" behavior, so both classes share the
        same "construction itself proves the backend is reachable"
        property.

        Args:
            dsn: A real `postgresql://...` DSN for the primary,
                writable instance - matching `POSTGRES_URL`'s own
                shape from deploy/docker-compose.yml.
            read_replica_dsn: An optional, separately-injectable DSN
                for `get_rating` to read from instead - see this
                module's own "READ-REPLICA ELIGIBILITY" docstring
                section. Defaults to `dsn` (the primary) when not
                given, since no real replica exists in this stage's
                own scope.

        Returns:
            None.

        Raises:
            UserRepositoryError: If `dsn` cannot be reached at all.
        """

        self._dsn = dsn
        self._read_replica_dsn = read_replica_dsn if read_replica_dsn is not None else dsn
        asyncio.run(self._ensure_users_table())

    async def _ensure_users_table(self) -> None:
        connection = await _connect(self._dsn)
        try:
            await connection.execute(_CREATE_USERS_TABLE_SQL)
        finally:
            await connection.close()

    def create_account(self, username: str, password: str) -> bool:
        """See `UserRepository.create_account` - same contract as
        `SqliteUserRepository.create_account`, just against Postgres.
        See that method's own docstring for the full Args/Returns
        contract; not restated here."""

        return asyncio.run(self._create_account_async(username, password))

    async def _create_account_async(self, username: str, password: str) -> bool:
        salt = secrets.token_bytes(_SALT_BYTES)
        password_hash = _hash_password(password, salt)
        connection = await _connect(self._dsn)
        try:
            try:
                await connection.execute(
                    "INSERT INTO users (username, password_hash, salt, rating) VALUES ($1, $2, $3, $4)",
                    username,
                    password_hash,
                    salt.hex(),
                    DEFAULT_STARTING_RATING,
                )
            except asyncpg.UniqueViolationError:
                # The `users.username` PRIMARY KEY constraint already
                # enforces uniqueness at the database level - the same
                # "reuse the real constraint, don't SELECT-then-INSERT"
                # reasoning as SqliteUserRepository's own
                # sqlite3.IntegrityError catch, so this stays correct
                # under concurrent callers too.
                return False
        finally:
            await connection.close()

        return True

    def verify_login(self, username: str, password: str) -> bool:
        """See `UserRepository.verify_login` - same contract as
        `SqliteUserRepository.verify_login`, including the same
        username-enumeration-safety property (a nonexistent username
        and a wrong password both return plain `False`, indistinguishably)."""

        return asyncio.run(self._verify_login_async(username, password))

    async def _verify_login_async(self, username: str, password: str) -> bool:
        connection = await _connect(self._dsn)
        try:
            row = await connection.fetchrow("SELECT password_hash, salt FROM users WHERE username = $1", username)
        finally:
            await connection.close()

        if row is None:
            return False

        candidate_hash = _hash_password(password, bytes.fromhex(row["salt"]))
        # secrets.compare_digest - same constant-time-comparison
        # reasoning as SqliteUserRepository.verify_login's own
        # docstring.
        return secrets.compare_digest(candidate_hash, row["password_hash"])

    def get_rating(self, username: str) -> int:
        """See `UserRepository.get_rating` - reads from
        `read_replica_dsn` (the primary `dsn` itself, unless a real
        replica DSN was separately injected) rather than always
        `dsn`, since this is the one Protocol method
        Server_Design.md names as replica-eligible - see this
        module's own "READ-REPLICA ELIGIBILITY" docstring section.

        Raises:
            UserNotFoundError: If `username` does not exist.
        """

        return asyncio.run(self._get_rating_async(username))

    async def _get_rating_async(self, username: str) -> int:
        connection = await _connect(self._read_replica_dsn)
        try:
            row = await connection.fetchrow("SELECT rating FROM users WHERE username = $1", username)
        finally:
            await connection.close()

        if row is None:
            raise UserNotFoundError(f"no such user: {username!r}")
        return row["rating"]

    def update_rating(self, username: str, new_rating: int) -> None:
        """See `UserRepository.update_rating` - same contract as
        `SqliteUserRepository.update_rating`, always routed to the
        primary `dsn` (this mutates).

        Raises:
            UserNotFoundError: If `username` does not exist.
        """

        asyncio.run(self._update_rating_async(username, new_rating))

    async def _update_rating_async(self, username: str, new_rating: int) -> None:
        connection = await _connect(self._dsn)
        try:
            # asyncpg's Connection.execute returns a status string
            # like "UPDATE 0"/"UPDATE 1" - the same "check the real
            # affected-row count, don't SELECT first" reasoning as
            # SqliteUserRepository.update_rating's own cursor.rowcount
            # check, just via asyncpg's own status-string shape
            # instead of a rowcount attribute.
            status = await connection.execute("UPDATE users SET rating = $1 WHERE username = $2", new_rating, username)
        finally:
            await connection.close()

        affected_rows = int(status.split()[-1])
        if affected_rows == 0:
            raise UserNotFoundError(f"no such user: {username!r}")
