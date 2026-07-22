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
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import websockets

from kungfu_chess.client.ui.score_table import PIECE_VALUES
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.game_state_snapshot_wire_format import (
    STATE_SNAPSHOT_MESSAGE_PREFIX,
    parse_game_state_snapshot,
)
from server.application.game_server import GameServer
from server.application.game_session import GameSession

_RECV_TIMEOUT_S = 5.0


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
    game_server = GameServer(session=session)
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
        server.close()
        await server.wait_closed()


def test_a_real_capture_broadcasts_the_correct_score_move_log_and_advancing_elapsed_clock():
    async def scenario():
        session = _capture_ready_session()
        async with _running_game_server(session) as (uri, _game_server):
            async with websockets.connect(uri) as client1, websockets.connect(uri) as client2:
                await client1.recv()  # assigned_color
                await client2.recv()
                await client1.recv()  # join-time board state
                await client2.recv()

                # a8 -> b8: a real, one-square, capturing rook move.
                await client1.send("WRa8b8")

                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted wire event
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted board text
                move_state_text = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # MoveAccepted state snapshot
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

                assert move_state_text.startswith(STATE_SNAPSHOT_MESSAGE_PREFIX)
                move_score, move_log, move_clock_ms = parse_game_state_snapshot(move_state_text)
                # Right after MoveAccepted (before arrival), nothing has
                # been captured yet - score is still 0-0, and the log
                # has exactly the one move entry (no capture entry yet).
                assert move_score.score_by_color == {Color.WHITE: 0, Color.BLACK: 0}
                assert len(move_log.entries) == 1
                assert move_log.entries[0].piece_kind is PieceKind.ROOK
                assert move_log.entries[0].piece_color is Color.WHITE

                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived wire event
                await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived board text
                arrival_state_text = await asyncio.wait_for(client1.recv(), timeout=_RECV_TIMEOUT_S)  # PieceArrived state snapshot
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)
                arrival_state_text_2 = await asyncio.wait_for(client2.recv(), timeout=_RECV_TIMEOUT_S)

        assert arrival_state_text == arrival_state_text_2  # both clients see the exact same broadcast state

        arrival_score, arrival_log, arrival_clock_ms = parse_game_state_snapshot(arrival_state_text)

        # White captured Black's pawn - White's score is now the
        # captured piece's real value, per standard chess scoring
        # (ScoreObserver's own established rule, re-verified directly).
        assert arrival_score.score_by_color[Color.WHITE] == PIECE_VALUES[PieceKind.PAWN]
        assert arrival_score.score_by_color[Color.BLACK] == 0

        # The move entry, then the capture entry, in that chronological
        # order - and the capture's own timestamp is never earlier than
        # the move's own, matching real chronology (the capture can only
        # happen strictly at or after the move that caused it).
        assert len(arrival_log.entries) == 2
        move_entry, capture_entry = arrival_log.entries
        assert move_entry.piece_kind is PieceKind.ROOK and move_entry.piece_color is Color.WHITE
        assert capture_entry.piece_kind is PieceKind.ROOK and capture_entry.piece_color is Color.WHITE
        assert capture_entry.captured_piece_kind is PieceKind.PAWN
        assert capture_entry.captured_piece_color is Color.BLACK
        assert capture_entry.recorded_at_clock_ms >= move_entry.recorded_at_clock_ms

        # The elapsed game clock has genuinely advanced between the two
        # snapshots - real time (via the real tick loop) actually
        # passed between MoveAccepted and PieceArrived.
        assert arrival_clock_ms > move_clock_ms

    asyncio.run(scenario())
