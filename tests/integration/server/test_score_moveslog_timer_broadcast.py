"""Real, end-to-end integration tests for the server-score-moveslog-
timer-broadcast stage (server/game_server.py's own "SCORE / MOVE-LOG /
TIMER BROADCAST" docstring section, and server/game_session.py's own
"SCORE / MOVE-LOG / TIMER" docstring section) - a real server (a real
GameSession, seeded with a small, custom board so a real capture can
happen in the minimum number of moves, real background tick loop) and
real websockets clients, mirroring test_protocol_wiring.py's own "real
server, real client, no mocking" convention and raw-websocket testing
style exactly - the score/move-log/clock snapshot is server-broadcast
content, tested at the same raw-websocket level
test_protocol_wiring.py already uses for board-text/wire-event content.

WHY A CUSTOM, INJECTED GameSession/board, NOT the default standard
starting position: GameServer already accepts an optional `session`
parameter for exactly this kind of test injection (re-verified
directly in server/game_server.py's own __init__) - a small board with
an immediate, one-square capture available minimizes the real wall-
clock wait time this test needs versus arranging a capture from the
full 32-piece standard position.

SQUARE MATH NOTE: kungfu_chess/notation/algebraic_notation.py's own
BOARD_SIZE=8 is a fixed constant, independent of any particular real
Board's actual dimensions (re-verified directly in that module's own
docstring) - so algebraic squares for this test's small 3x3 board still
compute correctly via the same fixed rank=8-row/file=chr(col) formula,
exactly as they would against a full 8x8 board.

UPDATED for Stage D2's real auth handshake (feature/home-screen-d2-
auth-protocol, see server/application/game_server.py's own "STAGE D2 -
REAL AUTH HANDSHAKE" docstring section): both clients below now send a
real "AUTH:<username>:<password>" command as their own very first
message before receiving assigned_color. _RECV_TIMEOUT_S is widened
from 5.0 to accommodate real, accepted PBKDF2 authentication latency
(see test_protocol_wiring.py's own identical note for the full
reasoning).

UPDATED AGAIN for Stage E1's real matchmaking (feature/matchmaking-elo-
queue-e1): GameServer's old session= constructor param was replaced by
session_factory (see game_server.py's own "STAGE E1" docstring
section) - now supplied via session_factory=lambda: session. Both
clients now connect CONCURRENTLY via asyncio.gather (sequential
connects would deadlock waiting for a matchmaking opponent), draining
the extra searching_for_opponent message. Color assignment is queue-
order-driven, not connection-order-driven, so the WHITE-specific rook
move below is sent from whichever of client1/client2 actually ended up
WHITE, identified from the real welcome messages rather than assumed.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
import websockets

from kungfu_chess.client.ui.score_table import PIECE_VALUES
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.auth_command_format import format_auth_command
from kungfu_chess.notation.game_state_snapshot_wire_format import LOG_DELTA_MESSAGE_PREFIX, parse_log_delta
from server.application.game_server import GameServer
from server.application.game_session import GameSession

# Marked slow: this file constructs a real, background-threaded/tasked
# server and relies on real wall-clock waiting (asyncio.sleep/time.sleep,
# real tick-loop cadence, or real network round trips) - excluded from
# `pytest -m "not slow"` for fast, deterministic day-to-day runs; still
# run in full via the dedicated slow/real-time pass.
pytestmark = pytest.mark.slow

_RECV_TIMEOUT_S = 20.0


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _capture_ready_session() -> GameSession:
    """A white rook one square away from a black pawn - the minimum
    setup for a real, immediate, one-square capturing move."""

    grid = _empty_grid(3, 3)
    mover = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))  # a8
    target = Piece(color=Color.BLACK, kind=PieceKind.PAWN, cell=Position(row=0, col=1))  # b8
    grid[0][0] = mover
    grid[0][1] = target
    return GameSession(board=Board(grid))


@asynccontextmanager
async def _running_game_server(session: GameSession):
    game_server = GameServer(session_factory=lambda: session, user_repository_db_path=":memory:")
    server = await websockets.serve(game_server.handle_connection, "localhost", 0)
    tick_task = asyncio.create_task(game_server.run_tick_loop())
    try:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://localhost:{port}", game_server
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass
        # A brief, real moment for every just-disconnected connection's
        # own handle_connection coroutine to actually reach
        # _handle_active_match_disconnect and register its own pending
        # countdown (a genuine scheduling race when two clients close
        # back-to-back - re-verified directly) - mirrors this project's
        # own established _REACTION_DELAY_S convention.
        await asyncio.sleep(0.2)
        # See server/application/game_server.py's own "STAGE - SERVER
        # SHUTDOWN HANGS ON A PENDING DISCONNECT COUNTDOWN" docstring
        # section: resolves any pending disconnect countdown BEFORE
        # close()/wait_closed(), below, so a test ending with both
        # players of an active match disconnected doesn't hang here.
        await game_server.shutdown()
        server.close()
        await server.wait_closed()


async def _authenticate_and_drain_join(client, username: str, password: str) -> tuple[str, str]:
    """Sends AUTH, drains the real searching_for_opponent message, and
    returns (welcome, board_state) - mirrors test_protocol_wiring.py's
    own identically-named helper. Caller is responsible for running
    this CONCURRENTLY (asyncio.gather) with a rating-compatible
    opponent's own call - awaiting it alone would block forever with no
    opponent."""

    await client.send(format_auth_command(username, password))
    # Stage F4 - a real client now chooses a mode after AUTH; "PLAY"
    # reproduces this file's own pre-F4 behavior (unconditional
    # matchmaking) exactly.
    await client.send("PLAY")
    searching = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    assert searching == "searching_for_opponent"
    welcome = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    board_state = await asyncio.wait_for(client.recv(), timeout=_RECV_TIMEOUT_S)
    return welcome, board_state


def test_a_real_capture_broadcasts_the_correct_score_move_log_and_advancing_elapsed_clock():
    """UPDATED for Stage G4's lean wire protocol (feature/g4-lean-wire-
    protocol): the old per-event full "STATE:" snapshot (score + the
    WHOLE accumulated move log) is gone - server/application/
    game_server.py's own `_broadcast_event` now sends `LOG_DELTA` (score/
    clock scalars + exactly the ONE newest log entry) instead, and only
    when the log actually grew (see that module's own "STAGE G4"
    docstring section for why a non-capturing PieceArrived sends none at
    all). MoveAccepted's own board occupancy is unchanged (nothing has
    moved yet), so its BOARD_DELTA is empty and skipped entirely -
    MoveAccepted therefore broadcasts exactly TWO messages (wire event +
    LOG_DELTA), not three. PieceArrived's arrival genuinely changes
    occupancy AND (here, a capture) grows the log, so it broadcasts
    THREE (wire event + BOARD_DELTA + LOG_DELTA)."""

    async def scenario():
        session = _capture_ready_session()
        async with _running_game_server(session) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                (welcome1, _board1), (_welcome2, _board2) = await asyncio.gather(
                    _authenticate_and_drain_join(client1, "client1", "password1"),
                    _authenticate_and_drain_join(client2, "client2", "password2"),
                )
                white_client, black_client = (
                    (client1, client2) if "white" in welcome1.lower() else (client2, client1)
                )

                # a8 -> b8: a real, one-square, capturing rook move.
                await white_client.send("WRa8b8")

                await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted wire event
                move_log_delta_text = await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)  # LOG_DELTA
                await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)

                assert move_log_delta_text.startswith(LOG_DELTA_MESSAGE_PREFIX)
                move_seq, move_score, move_entry, move_clock_ms = parse_log_delta(move_log_delta_text)
                # Right after MoveAccepted (before arrival), nothing has
                # been captured yet - score is still 0-0, and the single
                # delta entry is the move itself (no capture entry yet).
                assert move_seq == 1
                assert move_score.score_by_color == {Color.WHITE: 0, Color.BLACK: 0}
                assert move_entry.piece_kind is PieceKind.ROOK
                assert move_entry.piece_color is Color.WHITE

                await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
                await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)  # BOARD_DELTA
                arrival_log_delta_text = await asyncio.wait_for(white_client.recv(), timeout=_RECV_TIMEOUT_S)  # LOG_DELTA
                await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)
                arrival_log_delta_text_2 = await asyncio.wait_for(black_client.recv(), timeout=_RECV_TIMEOUT_S)

        assert arrival_log_delta_text == arrival_log_delta_text_2  # both clients see the exact same broadcast

        arrival_seq, arrival_score, arrival_entry, arrival_clock_ms = parse_log_delta(arrival_log_delta_text)

        # White captured Black's pawn - White's score is now the
        # captured piece's real value, per standard chess scoring
        # (ScoreObserver's own established rule, re-verified directly).
        assert arrival_seq == 2
        assert arrival_score.score_by_color[Color.WHITE] == PIECE_VALUES[PieceKind.PAWN]
        assert arrival_score.score_by_color[Color.BLACK] == 0

        # The single delta entry at arrival is the CAPTURE entry (the
        # move entry was already sent, on its own, at MoveAccepted time
        # above - LOG_DELTA only ever carries the single newest entry,
        # never the whole accumulated log).
        assert arrival_entry.piece_kind is PieceKind.ROOK and arrival_entry.piece_color is Color.WHITE
        assert arrival_entry.captured_piece_kind is PieceKind.PAWN
        assert arrival_entry.captured_piece_color is Color.BLACK
        assert arrival_entry.recorded_at_clock_ms >= move_entry.recorded_at_clock_ms

        # The elapsed game clock has genuinely advanced between the two
        # deltas - real time (via the real tick loop) actually passed
        # between MoveAccepted and PieceArrived.
        assert arrival_clock_ms > move_clock_ms

    asyncio.run(scenario())
