"""CoordinateLabelRenderer: draws file (a, b, c...) and rank (1, 2,
3...) labels around a board's edge onto an Img canvas - the algebraic-
notation labels a reference chess UI screenshot shows around the
board, which nothing in this codebase draws yet (Stage 13a).

SRP: this class only turns a board's dimensions into text calls - it
never draws the board/pieces/highlights (ImgSurface's job), the HUD
(HudRenderer's job), or cooldown bars (CooldownOverlayRenderer's job),
and it has no knowledge of PieceSnapshot/Board/model types at all -
just two integer dimensions and one integer origin.

CANVAS MARGIN (for GameLoopRunner, which owns real canvas sizing - NOT
touched by this class, see below): this renderer needs LABEL_MARGIN
(30px) of empty canvas reserved on ALL FOUR sides of the board now
(Stage 15 - previously only the LEFT and BELOW, Stage 13a/13c; the
reference image shows rank numbers on both the left AND right, and
file letters on both the top AND bottom, matching a real chess board's
own common convention of being readable from either player's seat).
The same LABEL_MARGIN constant is reused symmetrically for all four
sides - no separate, asymmetric constant was needed: the reference
image's margins read as visually uniform on every side, and there is
no content-driven reason (e.g. wider text on one side) for them to
differ. render() takes board_origin_x/board_origin_y explicitly (where
the board's own pixel (0, 0) actually starts on the canvas) rather than
assuming the board starts at the canvas's own (0, 0) - this is what
lets GameLoopRunner decide the real canvas layout (shift the whole
board by LABEL_MARGIN on more than one side now, to make room for
labels on all four) without this class needing to change; this class
deliberately does not touch GameLoopRunner's canvas construction or
size itself.

ORIENTATION: files run left-to-right as 'a'..'z' starting at column 0
(board_width capped at 26 by this scheme); ranks are numbered
bottom-to-top - row (board_height - 1) is rank 1, row 0 is rank
board_height - matching the standard chess board convention (rank 1 on
the side closer to White's starting position) rather than a raw
top-to-bottom row index, since this is what a chess player expects a
labeled board to show. The SAME file letters are drawn both above and
below the board, and the SAME rank numbers both left and right (not a
mirrored/reversed second scheme) - a board only has one real
column-to-letter and row-to-number mapping; drawing it twice is purely
so it is readable from either side, not two different labelings.
"""

from __future__ import annotations

from kungfu_chess.client.surface.img import Img
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE

LABEL_MARGIN = 30
LABEL_FONT_SCALE = 0.5
# Light gray, not black: Stage 13c's dark navy/black canvas backdrop
# would swallow black text entirely. Matches SidePanelRenderer's own
# TABLE_TEXT_COLOR (kungfu_chess/client/ui/side_panel_renderer.py) -
# same value, redefined here rather than imported (keeping this module
# decoupled from SidePanelRenderer's own constants, per SRP - the same
# "redefined, not imported" choice SidePanelRenderer itself already
# made for its own TITLE_BOX_BORDER_COLOR/ImgSurface.HIGHLIGHT_COLOR
# pair) - chosen over SidePanelRenderer's brighter pure-white
# TITLE_TEXT_COLOR/SCORE_TEXT_COLOR because coordinate labels are the
# same kind of small, secondary, utility text as a panel's table rows,
# not a title, so the same visual weight is the more consistent match.
LABEL_COLOR = (220, 220, 220)
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
        """Draw every file label (above AND below the board) and rank
        label (left AND right of the board) - see module docstring's
        ORIENTATION note for why both sides get the same labels.

        Args:
            board_width: Board width, in cells.
            board_height: Board height, in cells.
            board_origin_x: The pixel x where the board's own column 0
                starts on this renderer's canvas (see module docstring
                - deliberately not assumed to be 0, so GameLoopRunner
                can position the board anywhere it decides on the real
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
        self._draw_rank_labels(board_width, board_height, board_origin_x, board_origin_y)

    def _draw_file_labels(self, board_width: int, board_height: int, board_origin_x: int, board_origin_y: int) -> None:
        """Draws 'a', 'b', 'c'... left-to-right, in the margin bands
        both directly below AND directly above the board (Stage 15 -
        previously below only) - see module docstring's ORIENTATION
        note. below_y/above_y mirror each other around the board: each
        is positioned at its own margin band's start edge (the bottom
        band starts where the board ends; the top band starts
        LABEL_MARGIN pixels before the board begins) plus the same
        `+ LABEL_MARGIN // 2 + APPROX_HALF_CHAR_HEIGHT` offset used to
        roughly vertically center text within a LABEL_MARGIN-tall band
        (see module-level APPROX_HALF_CHAR_HEIGHT's own comment)."""

        below_y = board_origin_y + board_height * CELL_SIZE + LABEL_MARGIN // 2 + APPROX_HALF_CHAR_HEIGHT
        above_y = board_origin_y - LABEL_MARGIN + LABEL_MARGIN // 2 + APPROX_HALF_CHAR_HEIGHT
        for col in range(board_width):
            letter = chr(ord("a") + col)
            label_x = board_origin_x + col * CELL_SIZE + CELL_SIZE // 2 - APPROX_HALF_CHAR_WIDTH
            self._canvas.draw_text(
                letter, label_x, below_y, color=LABEL_COLOR, font_scale=LABEL_FONT_SCALE, thickness=LABEL_THICKNESS
            )
            self._canvas.draw_text(
                letter, label_x, above_y, color=LABEL_COLOR, font_scale=LABEL_FONT_SCALE, thickness=LABEL_THICKNESS
            )

    def _draw_rank_labels(self, board_width: int, board_height: int, board_origin_x: int, board_origin_y: int) -> None:
        """Draws '1'..board_height bottom-to-top, in the margin bands
        both directly left of AND directly right of the board
        (Stage 15 - previously left only) - see module docstring's
        ORIENTATION note for why rank 1 is the bottom row, not row 0.
        left_x/right_x mirror each other the same way below_y/above_y
        do in _draw_file_labels: each sits at its own margin band's
        start edge (the left band starts LABEL_MARGIN pixels before
        the board; the right band starts where the board ends) plus
        the same small `+ APPROX_HALF_CHAR_WIDTH` left-padding within
        that band."""

        left_x = board_origin_x - LABEL_MARGIN + APPROX_HALF_CHAR_WIDTH
        right_x = board_origin_x + board_width * CELL_SIZE + APPROX_HALF_CHAR_WIDTH
        for row in range(board_height):
            rank_number = board_height - row
            label_y = board_origin_y + row * CELL_SIZE + CELL_SIZE // 2 + APPROX_HALF_CHAR_HEIGHT
            self._canvas.draw_text(
                str(rank_number), left_x, label_y, color=LABEL_COLOR, font_scale=LABEL_FONT_SCALE,
                thickness=LABEL_THICKNESS,
            )
            self._canvas.draw_text(
                str(rank_number), right_x, label_y, color=LABEL_COLOR, font_scale=LABEL_FONT_SCALE,
                thickness=LABEL_THICKNESS,
            )
