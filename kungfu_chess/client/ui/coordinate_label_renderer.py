"""CoordinateLabelRenderer: draws file (a, b, c...) and rank (1, 2,
3...) labels around a board's edge onto an Img canvas - the algebraic-
notation labels a reference chess UI screenshot shows around the
board, which nothing in this codebase draws yet (Stage 13a).

SRP: this class only turns a board's dimensions into text calls - it
never draws the board/pieces/highlights (ImgSurface's job), the HUD
(HudRenderer's job), or cooldown bars (CooldownOverlayRenderer's job),
and it has no knowledge of PieceSnapshot/Board/model types at all -
just two integer dimensions and one integer origin.

CANVAS MARGIN (for Stage 13c, which owns real canvas sizing - NOT
touched by this stage, see below): this renderer needs LABEL_MARGIN
(30px) of empty canvas reserved on the LEFT of the board (for rank
numbers) and LABEL_MARGIN (30px) reserved BELOW the board (for file
letters). Nothing is drawn above or to the right of the board, so no
margin is needed on those two sides. render() takes board_origin_x/
board_origin_y explicitly (where the board's own pixel (0, 0) actually
starts on the canvas) rather than assuming the board starts at the
canvas's own (0, 0) - this is what lets Stage 13c decide the real
canvas layout (e.g. shift the whole board right by LABEL_MARGIN to
make room for rank numbers) without this class needing to change; this
stage deliberately does not touch GameLoopRunner's canvas construction
or size itself, per the task's own scope boundary.

ORIENTATION: files run left-to-right as 'a'..'z' starting at column 0
(board_width capped at 26 by this scheme); ranks are numbered
bottom-to-top - row (board_height - 1) is rank 1, row 0 is rank
board_height - matching the standard chess board convention (rank 1 on
the side closer to White's starting position) rather than a raw
top-to-bottom row index, since this is what a chess player expects a
labeled board to show.
"""

from __future__ import annotations

from kungfu_chess.client.surface.img import Img
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE

LABEL_MARGIN = 30
LABEL_FONT_SCALE = 0.5
LABEL_COLOR = (0, 0, 0)
LABEL_THICKNESS = 1

# cv2.getTextSize("a", FONT_HERSHEY_SIMPLEX, LABEL_FONT_SCALE, LABEL_THICKNESS)
# measures roughly (10, 12) px (+ baseline ~5px) for a single character
# at this font scale - used below to approximate-center each label
# within its cell (files) or within the margin band (ranks), the same
# "approximate, not pixel-perfect text-metrics centering" tradeoff
# img_surface.py's draw_game_over_message already makes, for the same
# reason (Img exposes draw_text, not a text-measurement method - see
# img.py's own SOLID boundary: cv2 usage stays inside img.py only).
APPROX_HALF_CHAR_WIDTH = 5
APPROX_HALF_CHAR_HEIGHT = 6


class CoordinateLabelRenderer:
    """Draws algebraic file/rank labels around a board's edge."""

    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as HudRenderer/CooldownOverlayRenderer/ImgSurface's own
        canvas injection."""

        self._canvas = canvas

    def render(self, board_width: int, board_height: int, board_origin_x: int, board_origin_y: int) -> None:
        """Draw every file label (below the board) and rank label (left
        of the board).

        Args:
            board_width: Board width, in cells.
            board_height: Board height, in cells.
            board_origin_x: The pixel x where the board's own column 0
                starts on this renderer's canvas (see module docstring
                - deliberately not assumed to be 0, so Stage 13c can
                position the board anywhere it decides on the real
                canvas without this class changing).
            board_origin_y: The pixel y where the board's own row 0
                starts on this renderer's canvas.

        Returns:
            None.

        No new exception type is introduced, and none is needed - the
        same reasoning as CooldownOverlayRenderer's own (Stage 12):
        Img.draw_text never raises for any position, and every position
        this method computes is derived from caller-supplied
        dimensions/origin with plain arithmetic, with no failure mode
        to guard against.
        """

        self._draw_file_labels(board_width, board_height, board_origin_x, board_origin_y)
        self._draw_rank_labels(board_height, board_origin_x, board_origin_y)

    def _draw_file_labels(self, board_width: int, board_height: int, board_origin_x: int, board_origin_y: int) -> None:
        """Draws 'a', 'b', 'c'... left-to-right, in the margin band
        directly below the board - see module docstring's ORIENTATION
        note."""

        label_y = board_origin_y + board_height * CELL_SIZE + LABEL_MARGIN // 2 + APPROX_HALF_CHAR_HEIGHT
        for col in range(board_width):
            letter = chr(ord("a") + col)
            label_x = board_origin_x + col * CELL_SIZE + CELL_SIZE // 2 - APPROX_HALF_CHAR_WIDTH
            self._canvas.draw_text(
                letter, label_x, label_y, color=LABEL_COLOR, font_scale=LABEL_FONT_SCALE, thickness=LABEL_THICKNESS
            )

    def _draw_rank_labels(self, board_height: int, board_origin_x: int, board_origin_y: int) -> None:
        """Draws '1'..board_height bottom-to-top, in the margin band
        directly left of the board - see module docstring's
        ORIENTATION note for why rank 1 is the bottom row, not row 0."""

        label_x = board_origin_x - LABEL_MARGIN + APPROX_HALF_CHAR_WIDTH
        for row in range(board_height):
            rank_number = board_height - row
            label_y = board_origin_y + row * CELL_SIZE + CELL_SIZE // 2 + APPROX_HALF_CHAR_HEIGHT
            self._canvas.draw_text(
                str(rank_number), label_x, label_y, color=LABEL_COLOR, font_scale=LABEL_FONT_SCALE,
                thickness=LABEL_THICKNESS,
            )
