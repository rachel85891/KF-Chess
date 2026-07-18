"""CooldownOverlayRenderer: draws a small depleting bar over every
piece currently on cooldown, onto an Img canvas - per client_spec.md
§2's "Cooldown after a move" extension getting a visual treatment.

SRP: this class only turns CooldownTracker.remaining_ratio() values
into bars - it never computes cooldown state itself (CooldownTracker's
job, kungfu_chess/client/events/cooldown_tracker.py) and never draws
the board/pieces/HUD itself (ImgSurface's/HudRenderer's jobs).

DIP: depends only on Img's public drawing methods, Board's public
piece_at/width/height, and CooldownTracker's public remaining_ratio() -
never constructs any of them, and never touches cv2/numpy directly
(same boundary Img itself already enforces).

VISUAL TREATMENT: a thin, solid bar along the BOTTOM edge of a piece's
own cell, full cell-width at ratio 1.0 (cooldown just started),
shrinking left-to-right down to nothing at ratio 0.0 (matching a
depleting-resource-bar convention already familiar from most games'
health/cooldown UI - width directly proportional to remaining_ratio,
so a glance tells a player roughly how much longer a piece is
unavailable). The bottom edge (not top, center, or a border around the
whole cell) was chosen so the bar never overlaps the piece's own sprite
(drawn starting at the cell's top-left corner, per ImgSurface's own
pixel-position convention) - a thin strip at the very bottom stays
clear of the sprite artwork itself for any of the vendored piece
sprites (all well under a full cell in height, per Stage 1's assets).

ERROR HANDLING: no new exception type is introduced here, and none is
needed - the same reasoning as HudRenderer's own (Stage 9): Img.
draw_rectangle never raises for any position, and this class's own
bar geometry is always derived from a ratio CooldownTracker itself
already guarantees to be in [0.0, 1.0] and a real piece's own cell
(always in-bounds by construction, since it's read directly off the
Board being rendered).
"""

from __future__ import annotations

from kungfu_chess.client.events.cooldown_tracker import CooldownTracker
from kungfu_chess.client.surface.img import Img
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE

COOLDOWN_BAR_HEIGHT = 6
COOLDOWN_BAR_COLOR = (0, 140, 255)


class CooldownOverlayRenderer:
    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as HudRenderer/ImgSurface's own canvas injection."""

        self._canvas = canvas

    def render(self, board: Board, cooldown_tracker: CooldownTracker, current_clock_ms: int) -> None:
        """Draw a depleting bar for every piece currently on cooldown.

        Args:
            board: The Board to walk for pieces - the same
                enumeration idiom (board.piece_at over every (row,
                col)) already used by PieceRegistry.from_board and
                PieceAnimatorRegistry.from_board, so this doesn't
                invent a fourth way to walk a Board. board.width/
                board.height are read directly from `board` itself
                rather than being taken as separate parameters (a
                small simplification over a from/to-style signature
                that would otherwise just duplicate board.width/
                board.height redundantly).
            cooldown_tracker: The CooldownTracker to query per piece.
            current_clock_ms: The current logical clock, forwarded
                as-is to remaining_ratio() for every piece (see
                CooldownTracker's own docstring for why this class
                cannot supply it on its own).

        Returns:
            None.

        Same no-clear ownership boundary as HudRenderer (Stage 9): this
        only draws bars on top of whatever's already on the canvas -
        the composition root is responsible for having drawn the board/
        pieces fresh this frame first.
        """

        for row in range(board.height):
            for col in range(board.width):
                piece = board.piece_at(Position(row=row, col=col))
                if piece is None:
                    continue

                ratio = cooldown_tracker.remaining_ratio(piece.id, current_clock_ms)
                if ratio <= 0.0:
                    continue

                self._draw_bar(row, col, ratio)

    def _draw_bar(self, row: int, col: int, ratio: float) -> None:
        """Draws one piece's bar - see module docstring's "visual
        treatment" note for the bottom-edge, width-proportional-to-
        ratio design."""

        x = col * CELL_SIZE
        y = row * CELL_SIZE + CELL_SIZE - COOLDOWN_BAR_HEIGHT
        width = round(ratio * CELL_SIZE)

        self._canvas.draw_rectangle(x, y, width, COOLDOWN_BAR_HEIGHT, COOLDOWN_BAR_COLOR)
