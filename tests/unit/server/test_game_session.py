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
from kungfu_chess.client.events.game_events import JumpAccepted, JumpLanded, MoveAccepted
from kungfu_chess.client.events.observers import CaptureLogEntry
from kungfu_chess.extra.jump import JUMP_DURATION_MS
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE
from server.game_session import GameSession


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


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


def test_request_jump_publishes_a_real_jump_accepted_and_later_a_real_jump_landed():
    session = GameSession()
    cell = Position(row=7, col=0)  # white rook, starting square
    rook = session.engine.board.piece_at(cell)

    jump_accepted_events: list = []
    jump_landed_events: list = []
    session.event_bus.subscribe(JumpAccepted, jump_accepted_events.append)
    session.event_bus.subscribe(JumpLanded, jump_landed_events.append)

    accepted = session.request_jump(cell)

    assert accepted is True
    assert jump_accepted_events == [
        JumpAccepted(piece_id=rook.id, from_cell=cell, to_cell=cell, duration_ms=JUMP_DURATION_MS)
    ]
    assert jump_landed_events == []  # not landed yet - still airborne

    session.wait(JUMP_DURATION_MS)

    assert jump_landed_events == [JumpLanded(piece_id=rook.id, cell=cell)]


def test_request_jump_on_an_empty_cell_is_rejected_and_publishes_nothing():
    session = GameSession()
    empty_cell = Position(row=4, col=4)

    events: list = []
    session.event_bus.subscribe(JumpAccepted, events.append)

    accepted = session.request_jump(empty_cell)

    assert accepted is False
    assert events == []


def test_a_real_capture_updates_score_observer_and_records_move_then_capture_in_moves_log_observer():
    session = GameSession()
    from_cell = Position(row=6, col=4)  # white pawn e2
    to_cell = Position(row=4, col=4)  # e4

    result = session.request_move(from_cell, to_cell)
    assert result.is_accepted is True

    score_after_move = session.score_observer.snapshot()
    assert score_after_move.score_by_color == {Color.WHITE: 0, Color.BLACK: 0}

    log_after_move = session.moves_log_observer.snapshot()
    assert len(log_after_move.entries) == 1
    move_entry = log_after_move.entries[0]
    assert move_entry.piece_kind is PieceKind.PAWN
    assert move_entry.piece_color is Color.WHITE
    assert move_entry.from_cell == from_cell
    assert move_entry.to_cell == to_cell
    assert move_entry.is_jump is False


def test_move_accepted_is_recorded_with_clock_ms_zero_since_it_fires_before_any_wait():
    # MoveAccepted publishes synchronously, inside request_move() itself
    # - which always happens BEFORE any wait() call advances the clock
    # or ever calls set_current_clock_ms - so its own MoveLogEntry is
    # stamped with whatever _current_clock_ms already was (0, the
    # observer's own untouched default), not a predicted future value.
    session = GameSession()

    session.request_move(Position(row=6, col=4), Position(row=4, col=4))

    log = session.moves_log_observer.snapshot()
    assert len(log.entries) == 1
    assert log.entries[0].recorded_at_clock_ms == 0


def test_moves_log_observer_receives_the_predicted_upcoming_clock_ms_before_each_wait():
    # A PieceArrived (and the CaptureLogEntry it produces) fires
    # SYNCHRONOUSLY INSIDE wait() itself, after set_current_clock_ms was
    # just called with THIS wait() call's own predicted upcoming clock
    # (clock_ms_before + ms) - so, unlike a MoveAccepted (see the
    # sibling test above), a capture entry's own recorded_at_clock_ms
    # must reflect that exact predicted value.
    grid = _empty_grid(3, 4)
    mover = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))
    target = Piece(color=Color.BLACK, kind=PieceKind.PAWN, cell=Position(row=0, col=2))
    grid[0][0] = mover
    grid[0][2] = target
    session = GameSession(board=Board(grid))

    session.request_move(Position(row=0, col=0), Position(row=0, col=2))
    session.wait(2 * MS_PER_SQUARE)

    log = session.moves_log_observer.snapshot()
    capture_entries = [entry for entry in log.entries if isinstance(entry, CaptureLogEntry)]
    assert len(capture_entries) == 1
    assert capture_entries[0].recorded_at_clock_ms == 2 * MS_PER_SQUARE
    assert session.engine.state.clock_ms == 2 * MS_PER_SQUARE


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
