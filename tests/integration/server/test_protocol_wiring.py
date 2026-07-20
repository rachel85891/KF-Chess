"""Real, end-to-end integration tests for Stage B3's protocol wiring
(server/game_server.py) - a REAL server (real GameSession, real
ConnectionManager, real background tick loop task) is started on an
OS-assigned free port, and REAL websockets clients connect to it, for
every scenario below - mirroring Stage B1's own
tests/integration/server/test_ws_skeleton.py "real server, real
client, no mocking" convention.

These tests genuinely take real wall-clock time (up to a few seconds
each): real-time piece motion is now driven by GameServer's own
background tick loop measuring REAL elapsed time
(time.perf_counter()), not simulated/injected time - per this stage's
own requirement to prove the tick loop actually works, using real
sleeps rather than pretending time passed.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.game_server import GameServer

_RECV_TIMEOUT_S = 5.0


@asynccontextmanager
async def _running_game_server(start_tick_loop: bool = False):
    """Start a REAL GameServer-backed server on an ephemeral port, and
    tear it down cleanly afterward (including cancelling the tick loop
    task, if one was started, so no test leaks a background task into
    the next one).

    Args:
        start_tick_loop: Whether to also start GameServer.run_tick_loop
            as a background asyncio task - only needed by tests that
            actually exercise real-time motion; tests that only check
            immediate rejection paths (wrong color, malformed command,
            join-order/server-full) don't need real time to advance at
            all, so they leave this off to stay fast and simple.

    Yields:
        (uri, game_server).
    """

    game_server = GameServer()
    server = await websockets.serve(game_server.handle_connection, "localhost", 0)
    tick_task = asyncio.create_task(game_server.run_tick_loop()) if start_tick_loop else None
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", game_server
    finally:
        if tick_task is not None:
            tick_task.cancel()
            try:
                await tick_task
            except asyncio.CancelledError:
                pass
        server.close()
        await server.wait_closed()


def test_first_client_is_white_second_is_black_third_is_rejected_and_closed():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                welcome1 = await client1.recv()
                welcome2 = await client2.recv()
                assert "white" in welcome1.lower()
                assert "black" in welcome2.lower()

                async with websockets.connect(uri) as client3:
                    rejection = await client3.recv()
                    assert rejection == "server_full"
                    with pytest.raises(ConnectionClosed):
                        await client3.recv()

    asyncio.run(scenario())


def test_legal_move_from_correct_color_client_is_accepted_and_broadcast_to_both_clients():
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()  # assigned_color welcome message
                await client2.recv()

                # White's e-pawn double-step opening move - 2 squares.
                await client1.send("WPe2e4")

                # Two broadcasts arrive per accepted move, not one:
                # MoveAccepted fires (and is broadcast) the instant the
                # motion STARTS - showing the board still in its
                # pre-move state, since the board only mutates on real
                # arrival (docs/spec.md's own "board changes only after
                # a moving piece has actually reached its destination"
                # rule) - then PieceArrived fires (and is broadcast)
                # once the tick loop has advanced enough real time for
                # the motion to complete. The first recv() per client is
                # therefore drained and discarded here; the SECOND is
                # the one that reflects the actual, final board state.
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

        assert board_after_1 == board_after_2  # both clients see the exact same broadcast state
        lines = board_after_1.splitlines()
        assert lines[6].split()[4] == "."  # e2 (row 6, col 4) is now empty
        assert lines[4].split()[4] == "wP"  # e4 (row 4, col 4) now holds the white pawn

    asyncio.run(scenario())


def test_move_command_with_wrong_color_prefix_for_the_connection_is_rejected():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()  # client1 is White
                await client2.recv()  # client2 is Black

                # client1 IS White, but claims to move as Black here.
                await client1.send("BPe7e5")
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)

                assert "wrong_color" in rejection

                # client2 must not have received anything at all - the
                # bad command never reached the engine, so no game
                # event/broadcast was ever produced.
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(client2.recv(), timeout=0.3)

    asyncio.run(scenario())


def test_malformed_command_does_not_crash_the_server_which_keeps_accepting_valid_commands():
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()
                await client2.recv()

                await client1.send("not a real command")
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                assert "rejected" in rejection

                # The server process itself must still be healthy
                # afterward - proven by a real, subsequent legal move
                # still working normally.
                await client1.send("WPe2e4")
                # Drain the immediate MoveAccepted broadcast (pre-move
                # board) before the later PieceArrived one (see the
                # sibling test above for the full reasoning).
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

        assert board_after_1 == board_after_2
        assert board_after_1.splitlines()[4].split()[4] == "wP"

    asyncio.run(scenario())


def test_tick_loop_advances_real_wallclock_time_for_an_in_flight_motion_with_no_further_activity():
    """Distinct from the "legal move is broadcast" test above: this one
    asserts on TIMING, not just final content - proving the broadcast
    only arrives after roughly the real amount of wall-clock time the
    move's motion actually takes (2 squares * MS_PER_SQUARE), driven
    purely by GameServer's background tick loop measuring real elapsed
    time, with the test doing nothing but wait in between (no second
    message, no manual wait()/simulated-time call of any kind)."""

    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()
                await client2.recv()

                started_at = time.perf_counter()
                await client1.send("WPe2e4")  # 2 squares = 2 * MS_PER_SQUARE of real motion time
                # First broadcast = MoveAccepted, near-instant (pre-move
                # board) - drained, not timed. Second = PieceArrived,
                # only produced once the tick loop's real elapsed time
                # actually covers the motion's full duration; THAT one
                # is what this test times.
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                elapsed_s = time.perf_counter() - started_at

        expected_s = (2 * MS_PER_SQUARE) / 1000
        # Real elapsed time must be at least MOST of the expected
        # motion duration (some slack for scheduling jitter/the tick
        # interval itself) - a broken tick loop that never advances
        # time would instead hang past _RECV_TIMEOUT_S entirely (a
        # test failure via TimeoutError above), while a (impossible,
        # but worth ruling out explicitly) instantly-resolving fake
        # would finish near-instantly, well under this floor.
        assert elapsed_s >= expected_s * 0.5

    asyncio.run(scenario())
