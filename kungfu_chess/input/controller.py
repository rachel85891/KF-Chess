"""Controller: click interpretation and selected-cell state, per
spec.md §11. Converts pixel clicks to cells via BoardMapper, decides
what a click means given the current selection, and is the ONLY thing
that calls GameEngine.request_move - it never calls RuleEngine
directly and never moves pieces itself.

The friendly-piece-click-while-selected "replace selection" behavior,
and the enemy-piece-click-while-selected "move/capture request"
behavior, are sourced from
kungfu_chess.services.click_interpreter.interpret_click (the existing,
already-verified click-classification logic) - spec.md §11 itself
doesn't fully specify this nuance. That module's additional
pending-move/airborne selectability gating is deliberately NOT
mirrored here: any attempt to act on a piece that is itself already
mid-motion is already correctly rejected by GameEngine.request_move's
motion_in_progress guard (spec.md §2's "Simultaneous movement of
pieces" extension - the guard is scoped per-piece, not system-wide, so
two different pieces of any colors may now have concurrent motions),
so Controller has nothing extra to enforce at selection time.

Re-clicking the exact cell of the currently-selected piece is treated
the same as clicking any other friendly piece: it "replaces" the
selection with itself, a no-op in effect. This isn't spelled out by an
explicit click_interpreter.py test, but falls directly out of its
actual logic (a same-color target is always SELECT, with no special
case for target == selected) - the simplest reading, adopted as-is.

Defensive addition beyond click_interpreter.py (which has the same gap
and would crash on it): if the previously-selected cell no longer
holds a piece - e.g. it was captured by an unrelated in-flight motion
that resolved via GameEngine.wait() while selected - the click is
re-evaluated as if nothing were selected, rather than crashing on a
stale selection.
"""

from __future__ import annotations

from typing import Optional

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.model.position import Position


class Controller:
    def __init__(self, game_engine: GameEngine):
        self.game_engine = game_engine
        self.board_mapper = BoardMapper()
        self.selected: Optional[Position] = None

    def click(self, x: int, y: int) -> None:
        cell = self.board_mapper.pixel_to_cell(x, y)
        board = self.game_engine.board

        if not board.in_bounds(cell):
            self.selected = None
            return

        if self.selected is not None and board.piece_at(self.selected) is None:
            self.selected = None

        if self.selected is None:
            if board.piece_at(cell) is not None:
                self.selected = cell
            return

        selected_piece = board.piece_at(self.selected)
        target_piece = board.piece_at(cell)

        if target_piece is not None and target_piece.color == selected_piece.color:
            self.selected = cell
            return

        self.game_engine.request_move(self.selected, cell)
        self.selected = None
