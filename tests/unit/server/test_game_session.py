"""Direct, in-process unit tests for Stage B2's GameSession
(server/game_session.py) - no networking involved at all, matching
Stage B1's own tests/integration/server/ convention of keeping network
tests strictly separate from pure in-process class tests. These belong
under tests/unit/, not tests/integration/server/, since they exercise
exactly one class in isolation, the same way every other tests/unit/
suite in this project does.
"""

from __future__ import annotations

from kungfu_chess.bus.event_bus import EventBus
from kungfu_chess.client.events.game_events import MoveAccepted
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.game_session import GameSession


def test_constructing_a_game_session_produces_a_standard_starting_position():
    session = GameSession()

    board = session.engine.board

    white_king = board.piece_at(Position(row=7, col=4))
    black_king = board.piece_at(Position(row=0, col=4))
    white_rook_a = board.piece_at(Position(row=7, col=0))
    white_rook_h = board.piece_at(Position(row=7, col=7))
    black_rook_a = board.piece_at(Position(row=0, col=0))
    black_rook_h = board.piece_at(Position(row=0, col=7))

    assert white_king.color is Color.WHITE and white_king.kind is PieceKind.KING
    assert black_king.color is Color.BLACK and black_king.kind is PieceKind.KING
    assert white_rook_a.color is Color.WHITE and white_rook_a.kind is PieceKind.ROOK
    assert white_rook_h.color is Color.WHITE and white_rook_h.kind is PieceKind.ROOK
    assert black_rook_a.color is Color.BLACK and black_rook_a.kind is PieceKind.ROOK
    assert black_rook_h.color is Color.BLACK and black_rook_h.kind is PieceKind.ROOK

    # A real, full 32-piece standard position - not just the four
    # spot-checked corners/kings above.
    piece_count = sum(1 for row in range(board.height) for col in range(board.width) if board.piece_at(Position(row=row, col=col)) is not None)
    assert piece_count == 32


def test_request_move_with_a_legal_pawn_double_step_succeeds_and_is_reflected_after_wait():
    session = GameSession()
    from_cell = Position(row=6, col=4)  # white pawn, e-file, starting row (board.height - 2)
    to_cell = Position(row=4, col=4)  # two squares forward - a legal opening double-step

    result = session.request_move(from_cell, to_cell)
    assert result.is_accepted is True

    # 2 squares = 2 * MS_PER_SQUARE, per docs/spec.md §10's "N squares =
    # N*1000ms" rule (kungfu_chess/realtime/real_time_arbiter.py's own
    # MS_PER_SQUARE constant, not a newly-guessed number).
    session.wait(2 * MS_PER_SQUARE)

    board = session.engine.board
    assert board.piece_at(from_cell) is None
    moved_pawn = board.piece_at(to_cell)
    assert moved_pawn is not None
    assert moved_pawn.color is Color.WHITE and moved_pawn.kind is PieceKind.PAWN


def test_request_move_with_an_illegal_move_is_rejected_and_board_is_unchanged():
    session = GameSession()
    # White rook's own starting square to an adjacent square occupied by
    # the white knight - rejected as a friendly-occupied destination,
    # the same least-setup illegal-move case
    # tests/unit/client/test_event_publisher.py's own
    # test_request_move_rejected_publishes_move_rejected_with_real_reason
    # already uses.
    from_cell = Position(row=7, col=0)  # white rook
    to_cell = Position(row=7, col=1)  # white knight - friendly piece

    result = session.request_move(from_cell, to_cell)

    assert result.is_accepted is False
    board = session.engine.board
    assert board.piece_at(from_cell).kind is PieceKind.ROOK
    assert board.piece_at(to_cell).kind is PieceKind.KNIGHT


def test_event_bus_is_a_real_eventbus_and_receives_a_real_move_accepted():
    session = GameSession()
    assert isinstance(session.event_bus, EventBus)

    received: list = []
    session.event_bus.subscribe(MoveAccepted, received.append)

    from_cell = Position(row=6, col=4)
    to_cell = Position(row=4, col=4)
    pawn = session.engine.board.piece_at(from_cell)

    result = session.request_move(from_cell, to_cell)

    assert result.is_accepted is True
    assert received == [
        MoveAccepted(piece_id=pawn.id, from_cell=from_cell, to_cell=to_cell, duration_ms=2 * MS_PER_SQUARE)
    ]


def test_two_independent_game_sessions_do_not_share_state():
    session_a = GameSession()
    session_b = GameSession()

    from_cell = Position(row=6, col=4)
    to_cell = Position(row=4, col=4)
    result = session_a.request_move(from_cell, to_cell)
    assert result.is_accepted is True
    session_a.wait(2 * MS_PER_SQUARE)

    # session_a's board changed...
    assert session_a.engine.board.piece_at(from_cell) is None
    assert session_a.engine.board.piece_at(to_cell) is not None

    # ...but session_b's own board is a completely separate Board
    # instance, still in the untouched starting position.
    assert session_a.engine.board is not session_b.engine.board
    assert session_b.engine.board.piece_at(from_cell) is not None
    assert session_b.engine.board.piece_at(to_cell) is None

    # And session_b's own EventBus never saw session_a's real event.
    received_b: list = []
    session_b.event_bus.subscribe(MoveAccepted, received_b.append)
    assert received_b == []
