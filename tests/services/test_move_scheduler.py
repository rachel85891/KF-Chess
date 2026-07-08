from kungfu_chess.domain.color import Color
from kungfu_chess.domain.movement.rules import is_king_move
from kungfu_chess.domain.piece import Piece, PieceType
from kungfu_chess.services.move_scheduler import MoveScheduler

_ROOK_TYPE = PieceType(letter="R", name="Rook", movement_rule=is_king_move, requires_clear_path=lambda dr, dc: False)


def _piece(color=Color.WHITE):
    return Piece(color=color, piece_type=_ROOK_TYPE)


def test_schedule_move_is_visible_via_has_pending_move_from():
    scheduler = MoveScheduler()
    scheduler.schedule_move((0, 0), (0, 1), _piece(), requested_at=0, arrival=1000)

    assert scheduler.has_pending_move_from(0, 0) is True
    assert scheduler.has_pending_move_from(1, 1) is False


def test_has_pending_for_color_is_global_not_cell_scoped():
    scheduler = MoveScheduler()
    scheduler.schedule_move((0, 0), (5, 5), _piece(Color.WHITE), requested_at=0, arrival=1000)

    assert scheduler.has_pending_for_color(Color.WHITE) is True
    assert scheduler.has_pending_for_color(Color.BLACK) is False


def test_schedule_landing_marks_cell_airborne():
    scheduler = MoveScheduler()
    scheduler.schedule_landing((2, 2), _piece(), start_time=0, land_time=1000)

    assert scheduler.is_airborne(2, 2) is True
    assert scheduler.is_airborne(0, 0) is False


def test_due_events_excludes_not_yet_due_entries():
    scheduler = MoveScheduler()
    scheduler.schedule_move((0, 0), (0, 1), _piece(), requested_at=0, arrival=1000)
    scheduler.schedule_landing((3, 3), _piece(), start_time=0, land_time=1000)

    assert scheduler.due_events(999) == []
    events = scheduler.due_events(1000)
    assert len(events) == 2


def test_due_events_moves_before_landings_on_exact_tie():
    """Locks in the original engine's actual (not documented) tie-break:
    at equal timestamps, moves settle before landings."""
    scheduler = MoveScheduler()
    move = scheduler.schedule_move((0, 0), (0, 1), _piece(), requested_at=0, arrival=1000)
    landing = scheduler.schedule_landing((0, 1), _piece(), start_time=0, land_time=1000)

    kinds = [kind for kind, _obj in scheduler.due_events(1000)]
    assert kinds == ["move", "land"]
    objs = [obj for _kind, obj in scheduler.due_events(1000)]
    assert objs == [move, landing]


def test_due_events_same_kind_ties_break_by_insertion_order():
    scheduler = MoveScheduler()
    first = scheduler.schedule_move((0, 0), (0, 4), _piece(), requested_at=0, arrival=1000)
    second = scheduler.schedule_move((1, 3), (0, 4), _piece(), requested_at=0, arrival=1000)

    objs = [obj for _kind, obj in scheduler.due_events(1000)]
    assert objs == [first, second]


def test_remove_move_and_remove_landing():
    scheduler = MoveScheduler()
    move = scheduler.schedule_move((0, 0), (0, 1), _piece(), requested_at=0, arrival=1000)
    landing = scheduler.schedule_landing((2, 2), _piece(), start_time=0, land_time=1000)

    scheduler.remove_move(move)
    scheduler.remove_landing(landing)

    assert scheduler.has_move(move) is False
    assert scheduler.is_airborne(2, 2) is False


def test_pending_moves_includes_not_yet_due_moves():
    """MoveResolver's landing-interception scan needs every pending move,
    not just the ones due in the current batch."""
    scheduler = MoveScheduler()
    far_future_move = scheduler.schedule_move((0, 0), (0, 4), _piece(), requested_at=0, arrival=4000)

    assert far_future_move in scheduler.pending_moves()
    assert scheduler.due_events(1000) == []
