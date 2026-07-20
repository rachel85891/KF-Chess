"""Tests for Stage A2: GameEventPublisher optionally also publishing
onto a kungfu_chess.bus.EventBus, per event_publisher.py's own new
docstring section on this. Kept in its own file, separate from
test_event_publisher.py (which is left completely untouched by this
stage - it already proves the pre-existing, event_bus=None behavior
in full, and continuing to pass unedited is itself part of this
stage's backward-compatibility proof).

Helper functions/classes below intentionally mirror
test_event_publisher.py's own (_empty_grid, _piece, RecordingObserver)
rather than importing them from that module - test modules in this
project are self-contained, and this stage must not create a new
import dependency between two sibling test files.
"""

from __future__ import annotations

from kungfu_chess.bus.event_bus import EventBus
from kungfu_chess.client.events.event_publisher import GameEventPublisher
from kungfu_chess.client.events.game_events import JumpAccepted, MoveAccepted, MoveRejected
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.extra.extra_engine import ExtraEngine
from kungfu_chess.extra.jump import JUMP_DURATION_MS
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


class RecordingBusHandler:
    """A plain EventBus handler (a callable taking one event) that
    just records what it received - the bus-side equivalent of
    RecordingObserver above, used to assert on what EventBus.publish
    actually delivered."""

    def __init__(self):
        self.events: list = []

    def __call__(self, event: object) -> None:
        self.events.append(event)


def test_move_accepted_is_published_on_the_injected_event_bus():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    bus = EventBus()
    publisher = GameEventPublisher(ExtraEngine(engine), event_bus=bus)
    handler = RecordingBusHandler()
    bus.subscribe(MoveAccepted, handler)

    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert handler.events == [
        MoveAccepted(
            piece_id=rook.id,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=1),
            duration_ms=MS_PER_SQUARE,
        )
    ]


def test_move_rejected_is_published_on_the_injected_event_bus():
    # Simplest second event type to trigger via the public API alone -
    # a rejected move needs no wait()/timing simulation at all, the
    # same "least setup" choice test_event_publisher.py's own
    # test_request_move_rejected_publishes_move_rejected_with_real_reason
    # already makes.
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    friendly = _piece(Color.WHITE, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = friendly
    engine = GameEngine(Board(grid))
    bus = EventBus()
    publisher = GameEventPublisher(ExtraEngine(engine), event_bus=bus)
    handler = RecordingBusHandler()
    bus.subscribe(MoveRejected, handler)

    result = publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is False
    assert handler.events == [MoveRejected(reason="friendly_destination")]


def test_jump_accepted_is_published_on_the_injected_event_bus():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    bus = EventBus()
    publisher = GameEventPublisher(ExtraEngine(engine), event_bus=bus)
    handler = RecordingBusHandler()
    bus.subscribe(JumpAccepted, handler)

    accepted = publisher.request_jump(Position(row=0, col=0))

    assert accepted is True
    assert handler.events == [
        JumpAccepted(
            piece_id=rook.id,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=0),
            duration_ms=JUMP_DURATION_MS,
        )
    ]


def test_both_the_observer_and_the_event_bus_receive_the_same_event():
    """Neither delivery mechanism replaces the other - both fire from
    the same real request_move call, given both an Observer and an
    EventBus at once."""

    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    bus = EventBus()
    publisher = GameEventPublisher(ExtraEngine(engine), event_bus=bus)
    observer = RecordingObserver()
    publisher.subscribe(observer)
    bus_handler = RecordingBusHandler()
    bus.subscribe(MoveAccepted, bus_handler)

    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    expected = [
        MoveAccepted(
            piece_id=rook.id,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=1),
            duration_ms=MS_PER_SQUARE,
        )
    ]
    assert observer.events == expected
    assert bus_handler.events == expected


def test_default_event_bus_none_leaves_observer_only_behavior_unchanged():
    """The default path (event_bus omitted entirely) must behave
    exactly as GameEventPublisher already did before this stage - no
    exception, no bus-related code path touched, Observer still the
    only delivery mechanism."""

    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(ExtraEngine(engine))  # event_bus omitted, defaults to None
    observer = RecordingObserver()
    publisher.subscribe(observer)

    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert observer.events == [
        MoveAccepted(
            piece_id=rook.id,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=1),
            duration_ms=MS_PER_SQUARE,
        )
    ]


def test_explicit_event_bus_none_behaves_identically_to_omitting_it():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    publisher = GameEventPublisher(ExtraEngine(engine), event_bus=None)
    observer = RecordingObserver()
    publisher.subscribe(observer)

    publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert observer.events == [
        MoveAccepted(
            piece_id=rook.id,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=1),
            duration_ms=MS_PER_SQUARE,
        )
    ]
