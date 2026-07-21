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

UPDATED for the initial-board-state-on-join fix (see
server/game_server.py's own "BUGFIX - INITIAL BOARD STATE ON JOIN"
docstring section): handle_connection now sends a second message - the
current board state - immediately after assigned_color, for every
accepted (non-rejected) connection. Every test below that previously
drained exactly one message after connecting now drains two, to
account for this - a real, intentional behavior addition these tests'
own assumptions needed to catch up to, not a scenario change (see
tests/integration/server/test_initial_board_state_on_join.py for the
fix's own dedicated coverage).

UPDATED AGAIN for Stage B7's real wire-format events (see
server/game_server.py's own "STAGE B7 - REAL WIRE-FORMAT EVENTS"
docstring section): _on_game_event now broadcasts an EXTRA,
structured wire-format message immediately before the existing
board-text broadcast for MoveAccepted/PieceArrived (MoveRejected gets
no such extra message - see that same docstring section for why). Any
test below that drains a move's resulting broadcasts now drains one
more message per accepted-move-related event than before Stage B7 -
again a real, intentional behavior addition, not a scenario change;
final assertions on the actual board-text content are unchanged.

UPDATED AGAIN for the server-score-moveslog-timer-broadcast stage (see
server/game_server.py's own "SCORE / MOVE-LOG / TIMER BROADCAST"
docstring section): _broadcast_event now sends ONE MORE message - the
score/move-log/elapsed-clock snapshot - immediately after the existing
wire-event + board-text pair, but ONLY for MoveAccepted/JumpAccepted/
PieceArrived (JumpLanded/MoveRejected/GameOver are unaffected - they
never change score/move-log state). Any test below that drains a
MoveAccepted's or JumpAccepted's own resulting broadcasts now drains
one more message per such event than before this stage - again a real,
intentional behavior addition, not a scenario change; final assertions
on the actual board-text/wire content are unchanged.
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
                await client1.recv()  # join-time board state (initial-board-state-on-join fix)
                await client2.recv()

                # White's e-pawn double-step opening move - 2 squares.
                await client1.send("WPe2e4")

                # Two GAME EVENTS fire per accepted move (MoveAccepted,
                # instantly - board still pre-move, since the board only
                # mutates on real arrival, docs/spec.md's own "board
                # changes only after a moving piece has actually reached
                # its destination" rule; then PieceArrived, once the
                # tick loop's real elapsed time completes the motion),
                # and each of those two events now broadcasts THREE
                # messages of its own (the wire-format event, the
                # board-text snapshot, then the score/move-log/clock
                # snapshot - the later stage's own addition) - six
                # messages total per client. The first four are drained
                # and discarded here (wire+board+state for MoveAccepted,
                # wire for PieceArrived); the fifth is the one that
                # reflects the actual, final post-move board state.
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted wire event
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted board text
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted state snapshot
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
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
                await client1.recv()  # join-time board state (initial-board-state-on-join fix)
                await client2.recv()

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


def test_move_command_for_a_square_not_matching_the_claimed_piece_is_rejected():
    # Safety-net characterization test, added before refactor/server-
    # application-presentation-split: this scenario (piece_mismatch for
    # a MOVE command specifically, not just a JUMP command) had no
    # existing coverage anywhere in this suite - only
    # test_jump_command_for_a_cell_not_matching_the_claimed_piece_is_
    # rejected (below) exercised this rejection reason, for JUMP only.
    # Mirrors that test's own scenario shape, applied to a MOVE command.
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()  # client1 is White
                await client2.recv()  # client2 is Black
                await client1.recv()  # join-time board state
                await client2.recv()

                # e2 really holds a Pawn, not a Queen - piece_mismatch.
                await client1.send("WQe2e4")
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)

                assert "piece_mismatch" in rejection

                # client2 must not have received anything - the bad
                # command never reached the engine, so no game
                # event/broadcast was ever produced.
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(client2.recv(), timeout=0.3)

    asyncio.run(scenario())


def test_move_rejected_by_the_real_engine_broadcasts_board_text_to_both_clients_with_no_wire_event():
    # Safety-net characterization test, added before refactor/server-
    # application-presentation-split: proves the real-engine-rejection
    # path the module docstring's own "MOVE COMMAND REJECTION SCHEME"
    # section describes (a move that parses fine and matches the real
    # board, but is still illegal per the real engine) - this path had
    # NO existing test coverage anywhere in this suite. A 3-square pawn
    # move from its own starting square is parseable and piece-matches
    # (e2 really is a white pawn) but illegal chess-piece-movement shape
    # - GameEventPublisher publishes a real MoveRejected event for this,
    # which only ever produces the ordinary board-text broadcast (no
    # wire-format event, no direct point-to-point rejection response -
    # unlike malformed/wrong_color/piece_mismatch, which never reach the
    # engine at all).
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()  # assigned_color
                await client2.recv()
                await client1.recv()  # join-time board state
                await client2.recv()

                await client1.send("WPe2e5")  # 3 squares - illegal pawn shape

                board_after_1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

        assert board_after_1 == board_after_2
        lines = board_after_1.splitlines()
        assert lines[6].split()[4] == "wP"  # e2 - the pawn never moved
        assert lines[3].split()[4] == "."  # e5 - still empty

    asyncio.run(scenario())


def test_malformed_command_does_not_crash_the_server_which_keeps_accepting_valid_commands():
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()
                await client2.recv()
                await client1.recv()  # join-time board state (initial-board-state-on-join fix)
                await client2.recv()

                await client1.send("not a real command")
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                assert "rejected" in rejection

                # The server process itself must still be healthy
                # afterward - proven by a real, subsequent legal move
                # still working normally.
                await client1.send("WPe2e4")
                # Drain the immediate MoveAccepted broadcasts (wire
                # event + pre-move board text + state snapshot) and
                # PieceArrived's own wire event, before the later, final
                # PieceArrived board text (see the sibling test above
                # for the full reasoning).
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted wire event
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted board text
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted state snapshot
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_1 = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                board_after_2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

        assert board_after_1 == board_after_2
        assert board_after_1.splitlines()[4].split()[4] == "wP"

    asyncio.run(scenario())


def test_legal_jump_from_correct_color_client_is_accepted_and_a_later_jump_landed_is_broadcast():
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()  # assigned_color
                await client2.recv()
                await client1.recv()  # join-time board state
                await client2.recv()

                # White's own a-file rook, its own starting square.
                await client1.send("JWRa1")

                # JumpAccepted's own wire event, board text, and (this
                # later stage's own addition) score/move-log/clock
                # state snapshot - JumpAccepted IS one of the three
                # event types that broadcast, even though a jump never
                # changes score/log itself; re-verified this is
                # consistent (an unaffected-content but still-broadcast
                # snapshot, exactly like a real move accepted with
                # nothing captured yet).
                jump_accepted_wire = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # board text
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # state snapshot
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # JumpAccepted wire
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # board text
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # state snapshot

                assert "JUMP" in jump_accepted_wire

                # Real wait for the tick loop to advance real time past
                # the jump's own real airborne duration - the landing's
                # own wire event, then its own board-text snapshot.
                # JumpLanded is NOT one of the three state-snapshot-
                # triggering event types (it never changes score/log),
                # so this stays at exactly two messages, unchanged.
                jump_landed_wire = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # board text
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # JumpLanded wire
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # board text

        assert "LANDED" in jump_landed_wire

    asyncio.run(scenario())


def test_jump_command_with_wrong_color_prefix_for_the_connection_is_rejected():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()  # client1 is White
                await client2.recv()  # client2 is Black
                await client1.recv()  # join-time board state
                await client2.recv()

                # client1 IS White, but claims to jump as Black here.
                await client1.send("JBRa8")
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)

                assert "wrong_color" in rejection

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(client2.recv(), timeout=0.3)

    asyncio.run(scenario())


def test_jump_command_for_a_cell_not_matching_the_claimed_piece_is_rejected():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()
                await client2.recv()
                await client1.recv()
                await client2.recv()

                # a1 is really a Rook, not a Queen - piece_mismatch.
                await client1.send("JWQa1")
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)

                assert "piece_mismatch" in rejection

    asyncio.run(scenario())


def test_malformed_jump_command_does_not_crash_the_server_which_keeps_accepting_valid_commands():
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()
                await client2.recv()
                await client1.recv()
                await client2.recv()

                await client1.send("J")  # far too short to be a real jump command
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                assert "rejected" in rejection

                # The server process itself must still be healthy
                # afterward - proven by a real, subsequent legal jump
                # still working normally.
                await client1.send("JWRa1")
                jump_accepted_wire = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # board text
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # state snapshot
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # state snapshot

        assert "JUMP" in jump_accepted_wire

    asyncio.run(scenario())


def test_jump_rejected_by_the_real_engine_gets_a_direct_jump_rejected_response():
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()
                await client2.recv()
                await client1.recv()
                await client2.recv()

                await client1.send("JWRa1")
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # JumpAccepted wire
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # board text
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # state snapshot
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # state snapshot

                # The SAME rook is still airborne - a second jump request
                # for it right now must be rejected by the real engine
                # (ExtraEngine.request_jump's own is_airborne guard) -
                # this specific outcome has no game event of its own (see
                # module docstring), so it needs this direct response.
                await client1.send("JWRa1")
                rejection = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)

                assert rejection == "rejected:jump_rejected"

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
                await client1.recv()  # join-time board state (initial-board-state-on-join fix)
                await client2.recv()

                started_at = time.perf_counter()
                await client1.send("WPe2e4")  # 2 squares = 2 * MS_PER_SQUARE of real motion time
                # MoveAccepted's own wire event + board text + state
                # snapshot arrive near-instantly (pre-move board) - all
                # drained, not timed. PieceArrived's own wire event
                # arrives next, also drained - only PieceArrived's
                # FINAL board text is produced once the tick loop's real
                # elapsed time actually covers the motion's full
                # duration; THAT one is what this test times (each
                # stage that added one more broadcast message per event
                # updated this drain count in turn; the thing actually
                # being timed is unchanged).
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted wire event
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted board text
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted state snapshot
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived board text
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
