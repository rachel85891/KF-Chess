"""Integration-style test proving the PieceAnimator PieceArrived->IDLE
bugfix (kungfu_chess/client/animation/piece_animator.py) works through
the REAL PieceAnimatorRegistry routing path, not just in isolated
PieceAnimator unit tests - a real from_board-built registry, receiving
a real MoveAccepted then a real PieceArrived, both carrying the same
real piece_id.

New, separate test file (tests/unit/client/test_piece_animator_registry.py
itself stays untouched, per this fix's own zero-test-file-edits
requirement) - confirms PieceAnimatorRegistry.on_event's routing (by
piece_id alone, no branching on event type - re-verified directly
against that file's own docstring/code before writing this) already
delivers PieceArrived to the right animator with no registry-level
change needed at all.
"""

from __future__ import annotations

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.animation.piece_animator_registry import PieceAnimatorRegistry
from kungfu_chess.client.events.game_events import MoveAccepted, PieceArrived
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def test_a_real_move_accepted_then_piece_arrived_returns_the_animator_to_idle_through_the_real_registry():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    registry = PieceAnimatorRegistry.from_board(board)

    registry.on_event(
        MoveAccepted(piece_id=rook.id, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=2), duration_ms=2000)
    )
    assert registry.animator_for(rook.id).current_state == AnimationState.MOVE

    registry.on_event(PieceArrived(piece_id=rook.id, cell=Position(row=0, col=2), captured_piece_id=None))

    assert registry.animator_for(rook.id).current_state == AnimationState.IDLE
