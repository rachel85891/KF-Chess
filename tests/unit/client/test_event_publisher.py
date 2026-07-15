from __future__ import annotations

import pytest

from kungfu_chess.client.events.event_publisher import GameEventPublisher, MotionNotFoundError
from kungfu_chess.client.events.game_events import GameOver, MoveAccepted, MoveRejected, PieceArrived
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


class RecordingObserver:
    def __init__(self):
        self.events: list = []

    def on_event(self, event: object) -> None:
        self.events.append(event)


def test_all_subscribed_observers_receive_the_same_event():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    observer_a, observer_b = RecordingObserver(), RecordingObserver()
    publisher.subscribe(observer_a)
    publisher.subscribe(observer_b)

    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert observer_a.events == observer_b.events
    assert len(observer_a.events) == 1


def test_request_move_accepted_publishes_move_accepted_with_correct_fields():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    observer = RecordingObserver()
    publisher.subscribe(observer)

    result = publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is True
    assert observer.events == [
        MoveAccepted(
            piece_id=rook.id,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=1),
            duration_ms=MS_PER_SQUARE,
        )
    ]


def test_request_move_rejected_publishes_move_rejected_with_real_reason():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    friendly = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = friendly
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    observer = RecordingObserver()
    publisher.subscribe(observer)

    result = publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is False
    assert result.reason == "friendly_destination"
    assert observer.events == [MoveRejected(reason="friendly_destination")]


def test_wait_converts_multiple_arrival_events_to_piece_arrived_in_order():
    grid = _empty_grid(3, 3)
    near_rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    far_rook = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=0))
    grid[0][0] = near_rook
    grid[2][0] = far_rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    observer = RecordingObserver()
    publisher.subscribe(observer)
    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    publisher.request_move(Position(row=2, col=0), Position(row=2, col=1))
    observer.events.clear()

    events = publisher.wait(MS_PER_SQUARE)

    assert len(events) == 2
    assert observer.events == [
        PieceArrived(piece_id=near_rook.id, cell=Position(row=0, col=1), captured_piece_id=None),
        PieceArrived(piece_id=far_rook.id, cell=Position(row=2, col=1), captured_piece_id=None),
    ]


def test_wait_publishes_piece_arrived_with_captured_piece_id():
    grid = _empty_grid(3, 3)
    attacker = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    victim = _piece(Color.BLACK, PieceKind.ROOK, Position(row=0, col=1))
    grid[0][0] = attacker
    grid[0][1] = victim
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    observer = RecordingObserver()
    publisher.subscribe(observer)
    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    observer.events.clear()

    publisher.wait(MS_PER_SQUARE)

    assert observer.events == [
        PieceArrived(piece_id=attacker.id, cell=Position(row=0, col=1), captured_piece_id=victim.id)
    ]


def test_wait_publishes_game_over_after_piece_arrived_on_king_capture():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = king
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    observer = RecordingObserver()
    publisher.subscribe(observer)
    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    observer.events.clear()

    publisher.wait(MS_PER_SQUARE)

    assert observer.events == [
        PieceArrived(piece_id=rook.id, cell=Position(row=0, col=1), captured_piece_id=king.id),
        GameOver(winner_color=Color.WHITE),
    ]


def test_default_ordering_policy_preserves_engine_fifo_order():
    grid = _empty_grid(3, 3)
    near_rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    far_rook = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=0))
    grid[0][0] = near_rook
    grid[2][0] = far_rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    observer = RecordingObserver()
    publisher.subscribe(observer)
    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    publisher.request_move(Position(row=2, col=0), Position(row=2, col=1))
    observer.events.clear()

    publisher.wait(MS_PER_SQUARE)

    piece_ids_in_order = [event.piece_id for event in observer.events]
    assert piece_ids_in_order == [near_rook.id, far_rook.id]


def test_custom_ordering_policy_changes_publish_order_observably():
    grid = _empty_grid(3, 3)
    near_rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    far_rook = _piece(Color.BLACK, PieceKind.ROOK, Position(row=2, col=0))
    grid[0][0] = near_rook
    grid[2][0] = far_rook
    engine = GameEngine(Board(grid))
    reverse_policy = lambda events: list(reversed(events))  # noqa: E731
    publisher = GameEventPublisher(engine, ordering_policy=reverse_policy)
    observer = RecordingObserver()
    publisher.subscribe(observer)
    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    publisher.request_move(Position(row=2, col=0), Position(row=2, col=1))
    observer.events.clear()

    publisher.wait(MS_PER_SQUARE)

    piece_ids_in_order = [event.piece_id for event in observer.events]
    assert piece_ids_in_order == [far_rook.id, near_rook.id]


def test_request_move_return_value_is_the_original_move_result_unchanged():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)

    result = publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is True
    assert result.reason == "ok"


def test_wait_return_value_is_the_original_arrival_events_list_unchanged():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(engine)
    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    events = publisher.wait(MS_PER_SQUARE)

    assert len(events) == 1
    assert events[0].piece is rook
    assert events[0].destination == Position(row=0, col=1)


def test_request_move_raises_motion_not_found_error_when_no_matching_motion_exists():
    # Under normal operation GameEngine.request_move always calls
    # arbiter.start_motion for an accepted move, so this branch is
    # unreachable through the public API alone - it guards an
    # invariant, not a normal user-triggerable condition. Forced here
    # by monkeypatching active_motions() to simulate that invariant
    # being violated, without touching GameEngine/RealTimeArbiter
    # themselves.
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    engine.arbiter.active_motions = lambda: ()
    publisher = GameEventPublisher(engine)

    with pytest.raises(MotionNotFoundError) as exc_info:
        publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert f"piece_id={rook.id}" in str(exc_info.value)
