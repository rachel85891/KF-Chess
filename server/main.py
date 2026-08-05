"""server/main.py: Stage B1's minimal, standalone WebSocket server
SKELETON - connection handling only, ZERO chess/game logic.

WHY this exists, and why it stops exactly here: the project is moving
from a single-process app (kungfu_chess/client/loop/game_loop.py's
GameLoopRunner, running GameEngine and rendering in one process) to a
networked client-server model. Before wiring the real GameEngine into
a server process (a future stage, not this one), this stage proves the
communication layer works in complete isolation - accepting
connections, sending/receiving messages, handling disconnects cleanly
- with no chess-specific code anywhere in this file or
connection_manager.py. This deliberately keeps network-layer bugs and
future game-logic-integration bugs from ever being tangled together to
debug at the same time.

WHY `server/` is a sibling of `kungfu_chess/`, not nested inside it:
mirrors client_spec.md §11's already-established `assets/` convention
for exactly the same reason - this is infrastructure/process code (a
runnable server), not importable game logic, so it does not belong
inside the package that IS the game logic. This file and
connection_manager.py import nothing from kungfu_chess/ at all
(re-verified directly before writing this) - proving the network layer
is genuinely decoupled from the game logic package, not just
conventionally separated by directory.

SWAP POINT for a future stage (a documented seam, not something the
next stage has to reverse-engineer): `echo_message` below is the ONLY
function a future real-protocol stage needs to replace. Today it just
sends whatever text arrived straight back, unmodified - Stage B1's
"prove the pipe works end-to-end" behavior, explicitly NOT the real
game protocol (WQe2e5-style commands come in a later stage). A future
stage swaps this function's BODY for real command parsing and real
GameEngine/GameEventPublisher calls (and can rename it accordingly) -
`handle_connection` and ConnectionManager need NO change at all: from
ConnectionManager's perspective, a connection that carries chess moves
looks identical to one carrying today's echoed text, and it never
needs to know the difference (see connection_manager.py's own module
docstring).

ALREADY-CLOSED-CONNECTION POLICY: if the underlying connection closes
between receiving a message and sending its reply - a genuine race
under real network conditions, since a client can disconnect at any
instant - `connection.send` raises
websockets.exceptions.ConnectionClosed. Decided policy: SILENTLY
IGNORE this. There is no chess/game logic yet (Stage B1's whole point
is to have none) to meaningfully react to a failed send, and the
connection's own removal from ConnectionManager is already handled
unconditionally in handle_connection's own `finally` block regardless
of why its lifetime ended - so nothing is left in an inconsistent
state by ignoring a failed reply here. A future stage with real game
state to protect (e.g. a move that must not be silently lost) can
revisit this inside its own replacement for echo_message - this
policy is scoped to today's throwaway echo, not a permanent constraint
on the swap point.

WHY both graceful and abrupt disconnects are handled by one shared
`except ConnectionClosed` (not two separate branches): a graceful,
client-initiated close (ConnectionClosedOK, re-verified directly
against the installed websockets version) simply ends the `async for`
iteration in handle_connection with no exception at all, while an
abrupt/abnormal drop (ConnectionClosedError) raises DURING that same
iteration. Both are subclasses of the shared ConnectionClosed base -
catching that one base, rather than each subclass separately, means
both disconnect styles are guaranteed to reach the exact same
`finally: manager.remove(connection)` cleanup, which is the only thing
this stage's requirements actually need to guarantee (neither style may
crash the server or leave a stale entry) - there is no other behavior
difference this stage needs to react to differently between the two.

STAGE B3 UPDATE - what changed here, and what deliberately did NOT:
echo_message/handle_connection/build_handler/ConnectionManager above
are UNCHANGED - kept exactly as Stage B1 left them, because
tests/integration/server/test_ws_skeleton.py (Stage B1's own tests)
still imports and exercises them directly as their own real,
independently-tested unit, and this stage's own requirement is that the
full pre-existing suite keeps passing UNCHANGED (no test file edits).
What DID change is `run_server`/`main`, below - the actual composition
root for the real, running server process now wires the real Stage B3
protocol (server/game_server.py's GameServer) instead of this file's
own echo pair. This is Stage B1's own "swap point" being exercised for
real, at exactly the layer it was always meant to happen at (the
composition root's own choice of handler), without needing to delete or
rewrite the still-tested Stage B1 code the swap is replacing at the
application level.

NOTE: this means the module docstring's earlier claim of "no
chess-specific code anywhere in this file" is now historical, not
current, for the file AS A WHOLE - it still describes
echo_message/handle_connection/build_handler/ConnectionManager
accurately (none of them import or reference anything chess-related,
still true, still tested), but `run_server`/`main` now import and
construct GameServer deliberately, as this stage's own explicit,
intentional exception to that original Stage B1 design goal - not an
oversight or a quiet regression of it.

STAGE I0 - Docker Compose, and what Postgres/Redis do NOT do yet here:
this stage adds a real `docker-compose.yml` (Postgres + Redis + this
same server, unchanged) so the 3-container deployment topology can be
proven to come up and talk to itself, before Stage I1/I2 build the
real Postgres-backed `UserRepository`/Redis-backed
`SessionCoordinator` implementations that will actually use these two
stores. IMPORTANT, read this before assuming otherwise: as of THIS
stage, Postgres and Redis are present as infrastructure only -
nothing in this file, or anywhere else in this codebase, reads or
writes application data through either of them yet. Account data
still flows entirely through the existing `SqliteUserRepository`
(now optionally pointed at a Docker-mounted volume via
`SQLITE_DB_PATH`, below, so a container restart doesn't silently wipe
accounts) and matchmaking still flows entirely through the existing
`InMemorySessionCoordinator` - both completely unchanged by this
stage. The only things this stage adds are:
  - `SERVER_HOST`/`SQLITE_DB_PATH` environment-variable overrides
    (read in `main()`, below), so the same unmodified `run_server()`/
    `GameServer` composition root can be told to bind to `0.0.0.0`
    (required for Docker's own port-mapping to reach a process bound
    to `localhost` inside a container - see `deploy/docker-compose.yml`)
    and to persist its SQLite file to a mounted volume path, instead
    of only ever using `DEFAULT_HOST`/`SqliteUserRepository`'s own
    `DEFAULT_DB_PATH` as before. Neither variable set (e.g. every
    existing test, and any local non-Docker run) reproduces today's
    exact behavior - this is a strict superset, not a replacement.
  - A throwaway startup connectivity check (`_run_startup_connectivity_
    check`, below), run once before `run_server()`, that - only when
    both `POSTGRES_URL` and `REDIS_URL` are set - opens one real,
    trivial connection to each, logs success, and closes it
    immediately without retaining it or using it for anything else.
    This is the actual proof the Compose topology's container-to-
    container networking works end-to-end, not merely that the
    containers started; it deliberately does NOT construct or wire in
    a `PostgresUserRepository`/`RedisSessionCoordinator` (neither
    exists yet - that's Stage I1/I2's own job).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

import websockets
from websockets.asyncio.server import Server, ServerConnection
from websockets.exceptions import ConnectionClosed

from server.application.game_server import GameServer
from server.presentation.connection_manager import ConnectionManager

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765

logger = logging.getLogger(__name__)

# uvloop: drop-in asyncio event-loop replacement for the real server
# process only (this file's own main(), below), chosen for I/O-bound
# throughput per Server_Design.md §14. No Windows support - upstream
# publishes no Windows wheels and its own setup.py hard-fails the build
# there (verified directly on this dev machine). Production deployment
# targets Linux/Kubernetes (Agones) per Server_Design.md §14, where
# uvloop is installed and used; Windows dev machines fall back to
# asyncio's own default event loop instead - both are real, tested
# event-loop implementations, so this is a deliberate availability
# fallback, not a bug or a partial implementation.
if sys.platform != "win32":
    import uvloop

    _loop_factory = uvloop.new_event_loop
else:
    _loop_factory = None


async def echo_message(connection: ServerConnection, message: object) -> None:
    """THE swap point for a future real-protocol stage - see module
    docstring. Today: send `message` straight back to `connection`,
    unmodified.

    Args:
        connection: The real ServerConnection to reply on.
        message: The exact message (str or bytes) websockets delivered
            from that connection - forwarded as-is, never inspected or
            transformed (Stage B1 has no protocol to parse yet).

    Returns:
        None.
    """

    try:
        await connection.send(message)
    except ConnectionClosed:
        # See module docstring's "ALREADY-CLOSED-CONNECTION POLICY".
        pass


async def handle_connection(connection: ServerConnection, manager: ConnectionManager) -> None:
    """Track `connection` for its whole lifetime and echo every message
    it sends, until it disconnects - gracefully or abruptly, either way
    handled identically (see module docstring's own section on this).

    Args:
        connection: The real ServerConnection websockets.serve handed
            this coroutine for one accepted client.
        manager: The ConnectionManager to register/unregister this
            connection with. Passed explicitly (DIP) rather than this
            function reaching for a module-level ConnectionManager, so
            ConnectionManager stays instantiable per-server (mirroring
            kungfu_chess.bus.EventBus's own "no global singleton"
            decision, Stage A1) instead of becoming hidden global
            state.

    Returns:
        None.
    """

    manager.add(connection)
    try:
        async for message in connection:
            await echo_message(connection, message)
    except ConnectionClosed:
        pass
    finally:
        manager.remove(connection)


def build_handler(manager: ConnectionManager):
    """Bind `manager` into a plain single-argument coroutine function -
    the exact shape websockets.serve requires of its handler - via a
    closure, rather than making ConnectionManager reachable as
    module-level state.

    Args:
        manager: The ConnectionManager every accepted connection on the
            resulting handler will be registered with.

    Returns:
        An async callable taking one ServerConnection, suitable to pass
        directly as websockets.serve's `handler` argument.

    Kept as its own function (not inlined at the one call site inside
    run_server, below) so tests can build a handler bound to a
    ConnectionManager they hold a reference to and can make real
    assertions against, without going through run_server()/main() at
    all - see tests/integration/server/test_ws_skeleton.py.
    """

    async def handler(connection: ServerConnection) -> None:
        await handle_connection(connection, manager)

    return handler


async def run_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    user_repository_db_path: Optional[str] = None,
) -> tuple[Server, GameServer]:
    """Start the real WebSocket server, wired to the real Stage B3
    protocol (server/game_server.py's GameServer), and return both the
    live Server handle and the GameServer backing it.

    Args:
        host: Interface to bind to. Defaults to DEFAULT_HOST
            (localhost) - Stage I0's own SERVER_HOST env-var override
            is resolved by the caller (main(), below) and passed in
            here explicitly, so this function's own default stays
            exactly what it was before that stage (unaffected local/
            test usage that never sets the env var at all).
        port: TCP port to bind to. Defaults to DEFAULT_PORT (8765) -
            pass 0 to let the OS assign a free ephemeral port instead
            (used by this module's own tests, so parallel test runs
            never collide with each other or with a real running
            instance on the default port).
        user_repository_db_path: Forwarded as-is to
            `GameServer(user_repository_db_path=...)`. Defaults to
            None, which `GameServer.__init__` already treats
            identically to "use SqliteUserRepository's own
            DEFAULT_DB_PATH" - so this function's own default behavior
            is completely unchanged from before Stage I0. Stage I0's
            own SQLITE_DB_PATH env-var override is resolved by the
            caller (main(), below) and passed in here explicitly.

    Returns:
        (server, game_server): `server` is the live websockets Server
        object (already listening) - the caller decides how long to
        keep it running and how to shut it down (see main(), below).
        `game_server` is returned too so the caller can start its
        background tick loop (GameServer.run_tick_loop) - starting it
        HERE instead would tie this function's own lifetime to the
        tick task in a way that isn't obviously correct for every
        possible caller (e.g. a test that wants the server listening
        but the tick loop not yet running); the composition root
        (main(), below) is where that decision actually belongs.

    A fresh GameServer (and, inside it, a fresh GameSession/
    ConnectionManager) is constructed here, not injected: this function
    (via main()) is the actual composition root for the server process,
    the same role GameLoopRunner plays for the client process
    (kungfu_chess/client/loop/game_loop.py) - one real place that
    builds the real thing, exactly once. See this module's own
    docstring's "STAGE B3 UPDATE" section for why this no longer builds
    a bare ConnectionManager/build_handler pair the way it used to.
    """

    game_server = GameServer(user_repository_db_path=user_repository_db_path)
    # Stage G2 - pins the `permessage-deflate` extension explicitly.
    # Verified directly against the currently pinned `websockets`
    # version (requirements.txt: `websockets>=13`, installed 16.1.1):
    # `compression` already defaults to `"deflate"` in both
    # websockets.serve and websockets.connect, so this changes no
    # runtime behavior today - it exists so this project's own behavior
    # doesn't silently depend on a third-party default that a future
    # `websockets` major version could change without anyone noticing.
    server = await websockets.serve(game_server.handle_connection, host, port, compression="deflate")
    logger.info("KF-Chess server listening on %s:%s", host, port)
    return server, game_server


async def _check_infra_connectivity(postgres_url: str, redis_url: str) -> None:
    """Stage I0's own infrastructure proof: open one real, trivial
    connection to Postgres and to Redis, log success, and close each
    immediately - never retained, never used for anything else (see
    this module's own "STAGE I0" docstring section for why: neither
    backend has a real `UserRepository`/`SessionCoordinator`
    implementation yet, that's Stage I1/I2's own job).

    `asyncpg`/`redis` are imported HERE, not at module level, so that
    importing `server.main` itself (every existing test already does
    this) never requires either package to be installed unless this
    function actually runs - which only happens when both
    POSTGRES_URL and REDIS_URL are set (see `_run_startup_
    connectivity_check`, below).

    Args:
        postgres_url: A real `postgresql://...` DSN - connected to
            directly, not parsed or validated here (asyncpg does
            that).
        redis_url: A real `redis://...` URL - passed straight to
            `redis.asyncio.Redis.from_url`.

    Raises:
        Whatever the underlying client raises on a failed connection -
        deliberately not caught here; the caller (`_run_startup_
        connectivity_check`) is the one place that decides what a
        failure means for process startup.
    """

    import asyncpg

    connection = await asyncpg.connect(postgres_url)
    await connection.close()
    logger.info("Stage I0 startup check: Postgres connection succeeded.")

    import redis.asyncio as redis_asyncio

    client = redis_asyncio.Redis.from_url(redis_url)
    try:
        await client.ping()
    finally:
        await client.aclose()
    logger.info("Stage I0 startup check: Redis connection succeeded.")


def _run_startup_connectivity_check() -> None:
    """Synchronous entry point for `_check_infra_connectivity`, called
    once from `main()` before `run_server()` starts. Reads
    POSTGRES_URL/REDIS_URL from os.environ; if either is unset (e.g.
    every existing test, and any local non-Docker run), this is a
    complete no-op - Stage I0's own env-var-gated scope boundary (see
    this module's own "STAGE I0" docstring section).

    Runs its own throwaway `asyncio.run(...)` event loop rather than
    being folded into `main()`'s real `_serve_forever()` coroutine:
    this check must complete (and the process must exit if it fails)
    BEFORE the real server starts listening at all - a separate,
    short-lived event loop that begins and ends here keeps that
    ordering obvious, without tangling this one-shot startup check
    into the long-lived server loop's own lifecycle.
    """

    postgres_url = os.environ.get("POSTGRES_URL")
    redis_url = os.environ.get("REDIS_URL")
    if postgres_url is None or redis_url is None:
        return

    try:
        asyncio.run(_check_infra_connectivity(postgres_url, redis_url))
    except Exception:
        logger.exception(
            "Stage I0 startup connectivity check failed - could not reach "
            "Postgres and/or Redis. Refusing to start."
        )
        sys.exit(1)


def main() -> None:
    """Real entry point: run the server (and its background tick loop)
    until the process is killed (Ctrl+C / SIGTERM) - see the
    module-level `if __name__ == "__main__"` guard, below, and this
    file's own docstring for how to run this by hand."""

    logging.basicConfig(level=logging.INFO)

    # Stage I0: SERVER_HOST/SQLITE_DB_PATH env-var overrides, resolved
    # here (not inside run_server(), whose own default parameter
    # values stay exactly DEFAULT_HOST/None - see its own docstring)
    # so run_server() itself remains fully testable/callable exactly
    # as before, with zero Stage I0 awareness of its own. Neither var
    # set (every existing test, any local non-Docker run) resolves to
    # exactly today's pre-Stage-I0 values.
    host = os.environ.get("SERVER_HOST", DEFAULT_HOST)
    sqlite_db_path = os.environ.get("SQLITE_DB_PATH")

    # Stage I0: proves the Compose topology's networking works
    # end-to-end - see _run_startup_connectivity_check's own
    # docstring. Must run before the real server starts listening.
    _run_startup_connectivity_check()

    async def _serve_forever() -> None:
        server, game_server = await run_server(host=host, user_repository_db_path=sqlite_db_path)
        # Created and kept alive as a local variable in THIS coroutine
        # frame, which itself stays alive for the whole process
        # (suspended at `await server.serve_forever()` below) - the
        # standard asyncio pattern to prevent the task from being
        # garbage-collected mid-flight (a bare, un-referenced
        # asyncio.create_task(...) result is only weakly held by the
        # event loop internally, which can silently drop a task that
        # nothing else references).
        tick_task = asyncio.create_task(game_server.run_tick_loop())
        try:
            await server.serve_forever()
        finally:
            # See server/application/game_server.py's own "STAGE -
            # SERVER SHUTDOWN HANGS ON A PENDING DISCONNECT COUNTDOWN"
            # docstring section: this MUST run before server.close()/
            # wait_closed(), below - `async with server:` (this
            # function's own previous form) calls those exact two
            # calls from its own __aexit__, with no opportunity for
            # this instance to resolve a pending disconnect countdown
            # first, which is exactly what let this hang happen.
            await game_server.shutdown()
            server.close()
            await server.wait_closed()
            tick_task.cancel()

    # Pins the real server process's event loop to uvloop where available
    # (falls back to asyncio's own default loop on Windows - see the
    # sys.platform guard above) - not test code, not the client
    # (network_game_client.py's own background loop is a separate
    # concern and is untouched by this). Per Server_Design.md §14.
    asyncio.run(_serve_forever(), loop_factory=_loop_factory)


if __name__ == "__main__":
    main()
