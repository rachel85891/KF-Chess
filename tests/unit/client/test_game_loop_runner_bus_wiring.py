"""Tests for Stage A3: GameLoopRunner constructing a real EventBus and
passing it into GameEventPublisher, per game_loop.py's own new
docstring section on this. Kept in its own file, separate from
test_game_loop_runner.py (which is left completely untouched by this
stage - it already proves every pre-A3 wiring/rendering/animation/
sound/click behavior in full, and continuing to pass unedited is part
of this stage's "no other behavior change" proof).

Same headless=True convention as test_game_loop_runner.py throughout -
see that file's own module-level comment for why (constructing a
real, non-headless window here would abort the whole pytest process on
a machine with no display).
"""

from __future__ import annotations

from kungfu_chess.bus.event_bus import EventBus
from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.events.game_events import MoveAccepted
from kungfu_chess.client.loop.game_loop import GameLoopRunner
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import MS_PER_SQUARE


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_event_bus_attribute_is_a_real_eventbus_instance():
    grid = _empty_grid(3, 3)
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestEventBusAttribute", headless=True)

    assert isinstance(runner.event_bus, EventBus)


def test_a_handler_subscribed_directly_on_runner_event_bus_receives_a_real_move_accepted():
    # The core proof this stage exists for: the SAME EventBus instance
    # exposed as runner.event_bus is the one actually wired into
    # GameEventPublisher's constructor - not just a stored, disconnected
    # object. Subscribing externally (exactly as a future Stage B WS
    # broadcaster would) and then driving a real move through
    # runner.publisher (the same least-setup trigger
    # test_game_loop_runner.py's own
    # test_construction_wires_all_three_observers_to_real_published_events
    # already uses) must reach this handler.
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    runner = GameLoopRunner(board, window_name="TestEventBusDelivery", headless=True)

    received: list = []
    runner.event_bus.subscribe(MoveAccepted, received.append)

    result = runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert result.is_accepted is True
    assert received == [
        MoveAccepted(
            piece_id=rook.id,
            from_cell=Position(row=0, col=0),
            to_cell=Position(row=0, col=1),
            duration_ms=MS_PER_SQUARE,
        )
    ]


def test_existing_observer_wiring_is_unaffected_by_the_now_connected_event_bus():
    # Spot-check against test_game_loop_runner.py's own
    # test_construction_wires_all_three_observers_to_real_published_events
    # scenario/assertions - identical setup and assertions, run again
    # here to prove the pre-existing Observer path (PieceAnimatorRegistry
    # in this case) is byte-for-byte unaffected now that event_bus is
    # connected, even with nothing subscribed to it.
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    pawn = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = pawn
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestEventBusNoSubscribersWiring", headless=True)

    result = runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    assert result.is_accepted is True

    assert runner.piece_animator_registry.animator_for(rook.id).current_state == AnimationState.MOVE


def test_run_one_frame_with_nothing_subscribed_to_event_bus_does_not_raise():
    # The real-world default state after this stage: event_bus is
    # connected but has zero subscribers. A full frame (publisher.wait +
    # animation advancement + real rendering onto an in-memory canvas)
    # must behave exactly as before this stage - no exception, no
    # behavior change - identical in spirit to
    # test_game_loop_runner.py's own
    # test_run_one_frame_does_not_raise_and_advances_a_moving_pieces_animation.
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestEventBusNoSubscribersFrame", headless=True)

    runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=2))

    animator = runner.piece_animator_registry.animator_for(rook.id)
    assert animator.current_state == AnimationState.MOVE
    assert animator.elapsed_ms_in_state == 0

    runner._run_one_frame(50)  # no exception == success

    assert animator.elapsed_ms_in_state > 0
