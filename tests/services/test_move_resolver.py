from kungfu_chess.config.piece_registry import PieceTypeRegistry
from kungfu_chess.domain.board import Board
from kungfu_chess.domain.color import Color
from kungfu_chess.domain.events import PieceCaptured, PieceIntercepted, PieceMoved
from kungfu_chess.domain.piece import Piece
from kungfu_chess.services.event_bus import EventBus
from kungfu_chess.services.move_resolver import (
    resolve_due_events,
    resolve_instant_royal_capture,
    resolve_landing,
    resolve_move,
)
from kungfu_chess.services.move_scheduler import MoveScheduler

REGISTRY = PieceTypeRegistry.standard_chess()


def _piece(letter, color):
    return Piece(color=color, piece_type=REGISTRY.get(letter))


def _bus_with_recorder():
    bus = EventBus()
    received = []
    for event_type in (PieceMoved, PieceCaptured, PieceIntercepted):
        bus.subscribe(event_type, received.append)
    return bus, received


def test_resolve_move_normal_capture_mutates_board_and_publishes_both_events():
    board = Board.from_grid([[_piece("R", Color.WHITE), _piece("R", Color.BLACK)]])
    scheduler = MoveScheduler()
    move = scheduler.schedule_move((0, 0), (0, 1), board.get_piece(0, 0), requested_at=0, arrival=1000)
    bus, received = _bus_with_recorder()

    resolve_move(move, board, scheduler, bus)

    assert board.get_piece(0, 0) is None
    assert board.get_piece(0, 1) is move.piece
    assert [type(e) for e in received] == [PieceCaptured, PieceMoved]


def test_resolve_move_non_capture_publishes_only_piece_moved():
    board = Board.from_grid([[_piece("R", Color.WHITE), None]])
    scheduler = MoveScheduler()
    move = scheduler.schedule_move((0, 0), (0, 1), board.get_piece(0, 0), requested_at=0, arrival=1000)
    bus, received = _bus_with_recorder()

    resolve_move(move, board, scheduler, bus)

    assert [type(e) for e in received] == [PieceMoved]


def test_resolve_move_silently_fails_if_no_longer_legal():
    board = Board.from_grid([[_piece("R", Color.WHITE), _piece("R", Color.WHITE)]])
    scheduler = MoveScheduler()
    # schedule as if target were still empty/enemy; board now holds a
    # friendly piece there by the time it settles
    move = scheduler.schedule_move((0, 0), (0, 1), board.get_piece(0, 0), requested_at=0, arrival=1000)
    bus, received = _bus_with_recorder()

    resolve_move(move, board, scheduler, bus)

    assert board.get_piece(0, 0) is move.piece  # mover stayed at origin
    assert received == []


def test_resolve_move_air_capture_destroys_arriver_and_publishes_nothing():
    """The original engine never treats an air-capture as a win-ending
    capture (even for a king) and never promotes the arriver - so no
    event may be published here, or a generic listener would react."""
    board = Board.from_grid([[_piece("R", Color.WHITE), _piece("K", Color.BLACK)]])
    scheduler = MoveScheduler()
    move = scheduler.schedule_move((0, 0), (0, 1), board.get_piece(0, 0), requested_at=0, arrival=1000)
    scheduler.schedule_landing((0, 1), board.get_piece(0, 1), start_time=0, land_time=2000)
    bus, received = _bus_with_recorder()

    resolve_move(move, board, scheduler, bus)

    assert board.get_piece(0, 0) is None  # arriving rook destroyed
    assert board.get_piece(0, 1) is not None  # defending king untouched
    assert received == []


def test_resolve_landing_intercepts_attacker_requested_while_airborne():
    board = Board.from_grid([[_piece("R", Color.WHITE), None, None, None, _piece("R", Color.BLACK)]])
    scheduler = MoveScheduler()
    landing = scheduler.schedule_landing((0, 4), board.get_piece(0, 4), start_time=0, land_time=1000)
    move = scheduler.schedule_move((0, 0), (0, 4), board.get_piece(0, 0), requested_at=0, arrival=4000)
    bus, received = _bus_with_recorder()

    resolve_landing(landing, board, scheduler, bus)

    assert board.get_piece(0, 0) is None  # attacker destroyed at origin
    assert scheduler.has_move(move) is False
    assert scheduler.is_airborne(0, 4) is False
    assert [type(e) for e in received] == [PieceIntercepted]


def test_resolve_landing_scans_full_pending_queue_not_just_due_events():
    """The attacker's own arrival (4000) is far beyond the landing time
    (1000) - interception must still find and destroy it right now."""
    board = Board.from_grid([[_piece("R", Color.WHITE), None, None, None, _piece("R", Color.BLACK)]])
    scheduler = MoveScheduler()
    landing = scheduler.schedule_landing((0, 4), board.get_piece(0, 4), start_time=0, land_time=1000)
    scheduler.schedule_move((0, 0), (0, 4), board.get_piece(0, 0), requested_at=0, arrival=4000)

    assert scheduler.due_events(1000) == [("land", landing)]  # move not due yet
    bus, _ = _bus_with_recorder()
    resolve_landing(landing, board, scheduler, bus)

    assert board.get_piece(0, 0) is None


def test_resolve_landing_ignores_moves_requested_before_jump_started():
    board = Board.from_grid([[_piece("R", Color.WHITE), None, None, None, _piece("R", Color.BLACK)]])
    scheduler = MoveScheduler()
    move = scheduler.schedule_move((0, 0), (0, 4), board.get_piece(0, 0), requested_at=0, arrival=4000)
    landing = scheduler.schedule_landing((0, 4), board.get_piece(0, 4), start_time=500, land_time=1500)
    bus, received = _bus_with_recorder()

    resolve_landing(landing, board, scheduler, bus)

    assert board.get_piece(0, 0) is move.piece  # attacker survives, requested before jump started
    assert received == []


def test_resolve_due_events_three_way_tie_moves_settle_before_landing_via_air_capture():
    """Reproduces the highest-risk scenario end to end: two same-color
    attackers and one landing all due at the same instant. Because moves
    process before landings, BOTH attackers self-destruct via air
    capture before the landing's interception ever gets a turn."""
    board = Board.from_grid([
        [None, None, None, _piece("R", Color.WHITE), _piece("R", Color.BLACK)],
        [None, None, None, _piece("B", Color.WHITE), None],
    ])
    scheduler = MoveScheduler()
    scheduler.schedule_landing((0, 4), board.get_piece(0, 4), start_time=0, land_time=1000)
    scheduler.schedule_move((0, 3), (0, 4), board.get_piece(0, 3), requested_at=0, arrival=1000)
    scheduler.schedule_move((1, 3), (0, 4), board.get_piece(1, 3), requested_at=0, arrival=1000)
    bus, received = _bus_with_recorder()

    resolve_due_events(scheduler, board, 1000, bus)

    assert board.get_piece(0, 3) is None
    assert board.get_piece(1, 3) is None
    assert board.get_piece(0, 4) is not None  # defender survived both
    assert received == []  # both settled via air-capture, which publishes nothing
    assert scheduler.due_events(1000) == []


def test_resolve_instant_royal_capture_mutates_board_and_publishes_only_capture():
    board = Board.from_grid([
        [_piece("K", Color.BLACK), None, None],
        [None, None, None],
        [_piece("R", Color.WHITE), None, None],
    ])
    mover = board.get_piece(2, 0)
    bus, received = _bus_with_recorder()

    resolve_instant_royal_capture(mover, (2, 0), (0, 0), board, bus)

    assert board.get_piece(0, 0) is mover
    assert board.get_piece(2, 0) is None
    assert [type(e) for e in received] == [PieceCaptured]
