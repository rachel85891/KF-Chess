"""Real, end-to-end integration tests for Stage B1's WebSocket server
skeleton (server/connection_manager.py, server/main.py) - a REAL
asyncio server is started on an OS-assigned free port (port=0) and a
REAL websockets client connects to it for every test below. Mocking
the network layer here would defeat this stage's whole purpose (see
server/main.py's own module docstring): proving the communication
layer works in genuine isolation from any chess logic, which a mock of
`websockets` itself could never actually prove.

No pytest-asyncio dependency added for this: each test is a plain
synchronous `def test_...()` that drives its own async scenario via a
single `asyncio.run(...)` call, keeping this project's already
established "minimal, dependency-light" testing convention
(docs/spec.md §1) intact rather than adding a new pytest plugin and
its own configuration (asyncio_mode, etc.) for one new test file.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import websockets

from server.main import build_handler, echo_message
from server.presentation.connection_manager import ConnectionManager


@asynccontextmanager
async def _running_server():
    """Start a REAL server, using server/main.py's own build_handler +
    a real ConnectionManager - exactly as main() constructs them, just
    with an ephemeral OS-assigned port (0) instead of the fixed default
    one, so tests never collide with each other or a real running
    instance - and tear it down cleanly afterward.

    Yields:
        (uri, manager): `uri` to connect real clients to; `manager` to
        make real, non-mocked assertions about tracked connections.
    """

    manager = ConnectionManager()
    server = await websockets.serve(build_handler(manager), "localhost", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", manager
    finally:
        server.close()
        await server.wait_closed()


def test_a_client_can_connect_to_the_server():
    async def scenario():
        async with _running_server() as (uri, _manager):
            async with websockets.connect(uri):
                pass  # connecting without raising IS the assertion

    asyncio.run(scenario())


def test_a_message_sent_by_a_connected_client_is_echoed_back_unmodified():
    async def scenario():
        async with _running_server() as (uri, _manager):
            async with websockets.connect(uri) as client:
                await client.send("hello, server")
                reply = await client.recv()

        assert reply == "hello, server"

    asyncio.run(scenario())


def test_two_simultaneous_clients_do_not_cross_talk():
    async def scenario():
        async with _running_server() as (uri, _manager):
            async with websockets.connect(uri) as client_a, websockets.connect(uri) as client_b:
                await client_a.send("from A")
                await client_b.send("from B")

                reply_a = await client_a.recv()
                reply_b = await client_b.recv()

        assert reply_a == "from A"
        assert reply_b == "from B"

    asyncio.run(scenario())


def test_connection_count_increases_on_connect_and_decreases_on_graceful_disconnect():
    async def scenario():
        async with _running_server() as (uri, manager):
            assert manager.connection_count == 0

            async with websockets.connect(uri) as client:
                await client.send("x")
                await client.recv()
                # Give the server's per-connection handler (a separate
                # asyncio Task, not guaranteed to have run synchronously
                # with connect()/send()/recv() returning) a tick to
                # actually execute manager.add() before asserting.
                await asyncio.sleep(0.05)
                assert manager.connection_count == 1

            # Client-initiated graceful close (the `async with` block
            # above exiting) - give the server's handler task a tick to
            # react and call manager.remove().
            await asyncio.sleep(0.05)
            assert manager.connection_count == 0

    asyncio.run(scenario())


def test_connection_count_decreases_on_abrupt_disconnect_without_crashing_the_server():
    async def scenario():
        async with _running_server() as (uri, manager):
            client = await websockets.connect(uri)
            await client.send("x")
            await client.recv()
            await asyncio.sleep(0.05)
            assert manager.connection_count == 1

            # Abrupt/abnormal disconnect: close the underlying transport
            # directly instead of performing the real WebSocket closing
            # handshake client.close() would perform - the server sees
            # this as a genuine ConnectionClosedError, not a graceful
            # ConnectionClosedOK (re-verified directly against the
            # installed websockets version before writing this test).
            client.transport.close()
            await asyncio.sleep(0.05)

            assert manager.connection_count == 0

            # The server process itself must not have crashed - proven
            # by it still accepting a brand new connection afterward.
            async with websockets.connect(uri) as new_client:
                await new_client.send("still alive")
                assert await new_client.recv() == "still alive"

    asyncio.run(scenario())


def test_sending_on_an_already_closed_connection_does_not_raise():
    """Proves server/main.py's own documented "ALREADY-CLOSED-
    CONNECTION POLICY" (see its module docstring): if
    connection.send() is attempted after the connection has already
    closed - a genuine race under real network conditions, not
    something artificially mocked here - echo_message swallows the
    resulting ConnectionClosed rather than letting it propagate and
    crash the handler/server."""

    async def scenario():
        async with _running_server() as (uri, manager):
            async with websockets.connect(uri) as client:
                await client.send("x")
                await client.recv()
                await asyncio.sleep(0.05)
                (connection,) = manager.connections()
            # The `async with` block above already closed `client`
            # gracefully - `connection` (the SAME real object the
            # server-side handler holds) is genuinely closed by now.
            await asyncio.sleep(0.05)

            await echo_message(connection, "too late")  # must not raise

    asyncio.run(scenario())
