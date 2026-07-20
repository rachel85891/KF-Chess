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
"""

from __future__ import annotations

import asyncio
import logging

import websockets
from websockets.asyncio.server import Server, ServerConnection
from websockets.exceptions import ConnectionClosed

from server.connection_manager import ConnectionManager

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765

logger = logging.getLogger(__name__)


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


async def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Server:
    """Start the real WebSocket server and return the live, listening
    Server handle.

    Args:
        host: Interface to bind to. Defaults to localhost (Stage B1 is
            a local, single-machine skeleton - no external-facing
            deployment concern exists yet at this stage).
        port: TCP port to bind to. Defaults to DEFAULT_PORT (8765) -
            pass 0 to let the OS assign a free ephemeral port instead
            (used by this module's own tests, so parallel test runs
            never collide with each other or with a real running
            instance on the default port).

    Returns:
        The live websockets Server object (already listening) - the
        caller decides how long to keep it running and how to shut it
        down (see main(), below, for the real, run-until-killed case).

    A fresh ConnectionManager is constructed here, not injected: this
    function (via main()) is the actual composition root for the
    server process, the same role GameLoopRunner plays for the client
    process (kungfu_chess/client/loop/game_loop.py) - one real place
    that builds the real thing, exactly once.
    """

    manager = ConnectionManager()
    server = await websockets.serve(build_handler(manager), host, port)
    logger.info("KF-Chess WS skeleton listening on %s:%s", host, port)
    return server


def main() -> None:
    """Real entry point: run the server until the process is killed
    (Ctrl+C / SIGTERM) - see the module-level `if __name__ ==
    "__main__"` guard, below, and this file's own docstring for how to
    run this by hand."""

    logging.basicConfig(level=logging.INFO)

    async def _serve_forever() -> None:
        server = await run_server()
        async with server:
            await server.serve_forever()

    asyncio.run(_serve_forever())


if __name__ == "__main__":
    main()
