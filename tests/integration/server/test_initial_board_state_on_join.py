"""Real, end-to-end integration tests for the join-time initial-board-
state fix (server/game_server.py) - a real server, real websockets
clients, no mocking, mirroring this project's own established
tests/integration/server/ convention exactly
(test_protocol_wiring.py's own helper is not imported from here - each
test file in this project stays self-contained, per established
precedent - but its shape is deliberately identical).

THE GAP THIS FIXES: GameServer's broadcaster only ever reacts to real
game EVENTS (MoveAccepted/MoveRejected/PieceArrived/GameOver) via its
event_bus subscription - there was no broadcast at CONNECTION time, so
a freshly-joined client received only its own "assigned_color:..."
message and then silence until somebody (possibly not even them) made
the very first move anywhere in the game. These tests prove a
just-joined client now also receives the CURRENT board state
immediately after its assigned_color message, before any move has ever
happened.

UPDATED for Stage B7's real wire-format events (see
server/game_server.py's own "STAGE B7 - REAL WIRE-FORMAT EVENTS"
docstring section): _on_game_event now broadcasts an extra,
structured wire-format message immediately before the existing
board-text broadcast for MoveAccepted/PieceArrived - this test file's
own event-driven-broadcast test drains one more message per such event
than before Stage B7; final assertions on board-text content are
unchanged.

UPDATED AGAIN for the server-score-moveslog-timer-broadcast stage (see
server/game_server.py's own "SCORE / MOVE-LOG / TIMER BROADCAST"
docstring section): _broadcast_event now sends one more message (the
score/move-log/elapsed-clock snapshot) immediately after the existing
wire-event + board-text pair for MoveAccepted/JumpAccepted/PieceArrived
- this test file's own event-driven-broadcast test drains one more
message per such event again; final assertions on board-text content
are unchanged.

UPDATED AGAIN for Stage D2's real auth handshake (feature/home-screen-
d2-auth-protocol, see server/application/game_server.py's own "STAGE D2
- REAL AUTH HANDSHAKE" docstring section): every client below must now
send a real "AUTH:<username>:<password>" command as its own very first
message before it can ever receive assigned_color - the still-rejected
THIRD/server_full client needs no change (that rejection happens before
the server ever reads anything it sent). _RECV_TIMEOUT_S is widened
from 5.0 to accommodate real, accepted PBKDF2 authentication latency
(see test_protocol_wiring.py's own identical note for the full
reasoning).

UPDATED AGAIN for Stage E1's real matchmaking (feature/matchmaking-elo-
queue-e1, see game_server.py's own "STAGE E1" docstring section): after
AUTH succeeds, a connection now receives searching_for_opponent FIRST,
then only later (once a rating-compatible opponent also joins) does it
receive assigned_color+board-state - an extra message to drain per
client, and every scenario that needs two clients to match EACH OTHER
must now connect them CONCURRENTLY (sequential connects would deadlock
- the first one's own recv() would block forever waiting for an
opponent that hasn't connected yet). `test_third_connection_is_still_
rejected_with_server_full_and_receives_no_board_state` is REMOVED, not
rewritten: the fixed-two-connection "server_full" cap this test proved
no longer exists at all under real matchmaking (see game_server.py's
own "WHY 'server_full' IS REMOVED ENTIRELY" docstring section) - there
is no replacement behavior to test in its place, only its own absence
(a third, fourth, etc. connection now simply joins the matchmaking
queue like any other).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import websockets

from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.notation.auth_command_format import format_auth_command
from server.application.game_server import GameServer
from server.application.game_session import GameSession

_STARTING_BOARD_TEXT = BoardPrinter().print(GameSession().engine.board)
_RECV_TIMEOUT_S = 20.0


@asynccontextmanager
async def _running_game_server(start_tick_loop: bool = False):
    game_server = GameServer(user_repository_db_path=":memory:")
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


async def _authenticate_and_await_welcome(client, username: str, password: str) -> str:
    """Sends AUTH, drains the real searching_for_opponent message, and
    returns the eventual assigned_color welcome - see module docstring's
    "UPDATED AGAIN for Stage E1" section. Caller is responsible for
    running this concurrently (asyncio.gather) with a rating-compatible
    opponent's own call - awaiting it alone would block forever with no
    opponent."""

    await client.send(format_auth_command(username, password))
    searching = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    assert searching == "searching_for_opponent"
    return await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)


def test_first_client_receives_the_starting_board_state_right_after_assigned_color():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            async with websockets.connect(uri) as client, websockets.connect(uri) as dummy:
                welcome, _dummy_welcome = await asyncio.gather(
                    _authenticate_and_await_welcome(client, "alice", "password"),
                    _authenticate_and_await_welcome(dummy, "alice_dummy_opponent", "dummy password"),
                )
                board_state = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)

        assert welcome.split(":")[1] in ("white", "black")
        assert board_state == _STARTING_BOARD_TEXT

    asyncio.run(scenario())


def test_second_client_also_receives_its_own_correct_starting_board_independently():
    async def scenario():
        async with _running_game_server() as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                _welcome1, welcome2 = await asyncio.gather(
                    _authenticate_and_await_welcome(client1, "client1", "password1"),
                    _authenticate_and_await_welcome(client2, "client2", "password2"),
                )
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # board state
                board_state2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

        assert welcome2.split(":")[1] in ("white", "black")
        assert board_state2 == _STARTING_BOARD_TEXT

    asyncio.run(scenario())


def test_existing_event_driven_broadcasts_still_work_after_the_join_time_board_state_is_added():
    async def scenario():
        async with _running_game_server(start_tick_loop=True) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                welcome1, welcome2 = await asyncio.gather(
                    _authenticate_and_await_welcome(client1, "client1", "password1"),
                    _authenticate_and_await_welcome(client2, "client2", "password2"),
                )
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # join-time board state
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)  # join-time board state

                # Color assignment is queue-order-driven, not connection-
                # order-driven (Stage E1), so the WHITE pawn move below
                # must be sent from whichever of client1/client2 actually
                # ended up WHITE - not assumed to be client1.
                white_client = client1 if welcome1.split(":")[1] == "white" else client2
                await white_client.send("WPe2e4")

                # Same six-broadcast-per-client pattern already
                # established by tests/integration/server/
                # test_protocol_wiring.py's own test_legal_move_from_
                # correct_color_client_is_accepted_and_broadcast_to_both_
                # clients: MoveAccepted fires immediately (wire event +
                # pre-move board text + state snapshot), then
                # PieceArrived fires once the tick loop's real elapsed
                # time completes the motion (wire event + post-move
                # board text + state snapshot) - the first four are
                # drained here, the fifth is asserted on.
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
        lines = board_after_1.splitlines()
        assert lines[6].split()[4] == "."
        assert lines[4].split()[4] == "wP"

    asyncio.run(scenario())
