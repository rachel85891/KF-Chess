"""SidePanelRenderer: draws ONE player's bordered side panel (color
name in a yellow-bordered title box, current score, and a Time/Move
table of that color's own recent moves) onto an Img canvas - the
reference-image layout Stage 13b's redesign targets, replacing
HudRenderer's fixed-corner-overlay approach (see "HUD_RENDERER'S FATE"
below).

SRP: this class only turns one color's ScoreSnapshot/MovesLogSnapshot
data into panel drawing calls - it never computes score or maintains a
log itself (Stage 8's ScoreObserver/MovesLogObserver own that), and
never draws the board/pieces/cooldown bars (ImgSurface's/
CooldownOverlayRenderer's jobs). It draws exactly ONE panel per call,
not both players' panels at once (client_spec.md's reference image
shows one panel per side, each independently positioned) - the caller
(Stage 13c's composition root) calls render() twice, once per color,
with two different (x, width, color) triples.

DIP: depends only on Img's public drawing methods, ScoreSnapshot,
MovesLogSnapshot, and Color - never constructs ScoreObserver,
MovesLogObserver, or GameEventPublisher itself, and never touches
cv2/numpy directly (all cv2 usage stays inside img.py, per Img's own
SOLID boundary).

LAYOUT CONTRACT (for Stage 13c, which owns real canvas sizing - NOT
wired here, see below): render() takes `x` and `width` as explicit
parameters rather than assuming a fixed screen corner, exactly like
CoordinateLabelRenderer's board_origin_x/board_origin_y (Stage 13a) -
this lets Stage 13c decide the final canvas layout (which side each
color's panel sits on, and where the board itself starts) once every
visual component's space needs are known, without this class changing.
This module's own recommendation for that space is PANEL_WIDTH (220px)
per panel - Stage 13c needs 2 * PANEL_WIDTH additional canvas width
beyond the board's own pixel footprint (one panel each side), plus
whatever CoordinateLabelRenderer's own LABEL_MARGIN needs. Panel
HEIGHT is not a parameter - it always fills the full canvas height
(self._canvas.height, read directly), matching the reference image's
panels running the board's full height, top to bottom (y=0 implicitly,
also not a parameter, for the same reason).

This stage deliberately does NOT touch GameLoopRunner's canvas
construction, does NOT wire this class into the per-frame render call,
and does NOT change the canvas's background color parameter - all
three are Stage 13c's job, once it has every component's real
space/position needs (this class's, CoordinateLabelRenderer's, and the
board's own) to lay out together. See PART 1 below for the one
already-existing capability (Img.blank_canvas's background_color
parameter) Stage 13c will need for the reference image's dark backdrop.

PART 1 - DARK BACKGROUND (confirmed, not implemented here): Img.
blank_canvas(width, height, background_color) already accepts an
arbitrary BGR background_color (Stage 6, re-checked directly in
img.py) - it defaults to white (255, 255, 255) only because no caller
has ever passed anything else. Stage 13c should pass a dark navy/black
BGR tuple there when it builds the per-frame canvas in
GameLoopRunner._run_one_frame, matching the reference image's dark
backdrop. No change to Img itself is needed or made here.

BORDER/HIGHLIGHT STYLING: two distinct rectangle outlines, not one -
- PANEL_BORDER_COLOR (light gray) frames the WHOLE panel region
  (x, 0, width, canvas.height), giving it the reference image's
  "distinct bordered panel" silhouette against the dark backdrop.
- TITLE_BOX_BORDER_COLOR (a golden yellow - the same BGR value as
  ImgSurface's own HIGHLIGHT_COLOR for selection highlights,
  redefined here rather than imported, to keep this module decoupled
  from ImgSurface's own constants per SRP) frames only the smaller
  title-box rectangle around the color/player-name label near the top
  of the panel, matching the reference image's yellow name-highlight
  specifically (not the whole panel).

FILTERING: MoveLogEntry and CaptureLogEntry (kungfu_chess/client/
events/observers.py, re-checked directly) both carry a `piece_color`
field naming the ACTING piece's color (the mover, not the captured
piece) - MovesLogEntry = Union[MoveLogEntry, CaptureLogEntry] shares
that field name across both variants, so this class filters
`entry.piece_color == color` directly with no isinstance check needed.
A panel therefore shows the moves/captures ITS color's own pieces
performed, not moves made against it - the natural reading of "that
color's entries" for a per-player panel.

"TIME" COLUMN: MoveLogEntry/CaptureLogEntry did not carry a timestamp
before this stage (re-checked Stage 8's observers.py directly) - both
gained a new `recorded_at_clock_ms: int = 0` field (Stage 13b, see
observers.py's own updated docstrings) to support this column,
populated by MovesLogObserver.set_current_clock_ms() using the exact
same clock-threading mechanism CooldownTracker already established
(Stage 12) - reused, not reinvented (see that method's own docstring
in observers.py, and GameLoopRunner's updated "COOLDOWN TIMER / MOVES
LOG TIMESTAMPS" docstring section). Displayed as mm:ss
(_format_clock_ms) - a running game clock reading is more meaningful
to a player glancing at the log than a raw millisecond count.

HUD_RENDERER'S FATE: hud_renderer.py (Stage 9/10c) is KEPT, not
removed, but is now DEPRECATED - see its own module docstring for the
full reasoning. In short: GameLoopRunner still calls it every frame
(Stage 13b deliberately does not touch that wiring, per this module's
own LAYOUT CONTRACT section above), so deleting it now would break a
currently-working, currently-tested code path with no replacement
wired in. Stage 13c is expected to swap GameLoopRunner's
HudRenderer(canvas).render(...) call for two SidePanelRenderer(canvas)
.render(...) calls (one per color) once it also resizes the canvas to
fit both panels - at which point hud_renderer.py's module docstring
already flags it as safe to delete outright, with no third,
in-between state.

MOVE/CAPTURE TEXT FORMAT: kept deliberately compact (single-letter
piece codes - P/N/B/R/Q/K, the same standard chess letters, Knight as
"N" - and "x" for a capture) rather than HudRenderer's fuller "Queen
captured Rook at (...)" wording: PANEL_WIDTH is narrow enough that a
full sentence per row would either wrap or overflow the panel's own
border. destination-cell-only for a plain move (not from AND to) for
the same width reason - a player who cares which piece moved already
has that from the row's own P/N/B/R/Q/K code and the panel's own
color; the piece's PREVIOUS cell is materially less useful in a
5-column-wide table than knowing where it must be looked for now.

ERROR HANDLING: no new exception type is introduced here, and none is
needed - the same reasoning as HudRenderer's own (Stage 9) and
CooldownOverlayRenderer's own (Stage 12): Img.draw_text/draw_rectangle
never raise for any position (checked directly, same as those two
files), _KIND_LETTERS is populated exhaustively over PieceKind's full,
closed enum membership (the type system guarantees any real entry's
piece_kind is one of those members, so it cannot KeyError), and an
empty filtered/capped entry list simply renders zero table rows rather
than failing.
"""

from __future__ import annotations

from typing import Sequence

from kungfu_chess.client.events.observers import (
    CaptureLogEntry,
    MoveLogEntry,
    MovesLogEntry,
    MovesLogSnapshot,
    ScoreSnapshot,
)
from kungfu_chess.client.surface.img import Img
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind

PANEL_WIDTH = 220
PANEL_PADDING = 12
PANEL_BACKGROUND_COLOR = (48, 33, 20)
PANEL_BORDER_COLOR = (200, 200, 200)
PANEL_BORDER_THICKNESS = 2

TITLE_BOX_Y = 10
TITLE_BOX_HEIGHT = 40
TITLE_BOX_BORDER_COLOR = (0, 215, 255)
TITLE_BOX_BORDER_THICKNESS = 3
TITLE_TEXT_Y = TITLE_BOX_Y + 27
TITLE_TEXT_COLOR = (255, 255, 255)
TITLE_FONT_SCALE = 0.7

SCORE_TEXT_Y = TITLE_BOX_Y + TITLE_BOX_HEIGHT + 25
SCORE_TEXT_COLOR = (255, 255, 255)
SCORE_FONT_SCALE = 0.6

TABLE_HEADER_Y = SCORE_TEXT_Y + 30
TABLE_ROW_HEIGHT = 22
TABLE_FIRST_ROW_Y = TABLE_HEADER_Y + TABLE_ROW_HEIGHT
TABLE_TEXT_COLOR = (220, 220, 220)
TABLE_HEADER_FONT_SCALE = 0.5
TABLE_ROW_FONT_SCALE = 0.45
TABLE_TIME_COLUMN_WIDTH = 55
PANEL_MAX_LOG_ROWS = 8

_COLOR_NAMES = {Color.WHITE: "White", Color.BLACK: "Black"}
_KIND_LETTERS = {
    PieceKind.PAWN: "P",
    PieceKind.KNIGHT: "N",
    PieceKind.BISHOP: "B",
    PieceKind.ROOK: "R",
    PieceKind.QUEEN: "Q",
    PieceKind.KING: "K",
}


def _format_clock_ms(clock_ms: int) -> str:
    """mm:ss - see module docstring's "TIME column" note for why this
    reading, not a raw millisecond count, is what a player wants."""

    total_seconds = clock_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _format_move_text(entry: MoveLogEntry) -> str:
    """See module docstring's "MOVE/CAPTURE TEXT FORMAT" note for why
    this is deliberately compact (destination cell only, single-letter
    piece code) rather than HudRenderer's fuller wording."""

    letter = _KIND_LETTERS[entry.piece_kind]
    jump_suffix = "*" if entry.is_jump else ""
    return f"{letter}{jump_suffix}->({entry.to_cell.row},{entry.to_cell.col})"


def _format_capture_text(entry: CaptureLogEntry) -> str:
    """"x" between the two piece letters mirrors standard chess
    capture notation (e.g. "NxB") - immediately readable as a capture,
    not just another move, even at this format's compact width."""

    letter = _KIND_LETTERS[entry.piece_kind]
    captured_letter = _KIND_LETTERS[entry.captured_piece_kind]
    return f"{letter}x{captured_letter} ({entry.cell.row},{entry.cell.col})"


def _format_entry_text(entry: MovesLogEntry) -> str:
    return _format_capture_text(entry) if isinstance(entry, CaptureLogEntry) else _format_move_text(entry)


class SidePanelRenderer:
    """Draws one player's bordered side panel - see module docstring
    for the full layout contract."""

    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as HudRenderer/CooldownOverlayRenderer/ImgSurface's own
        canvas injection."""

        self._canvas = canvas

    def render(self, x: int, width: int, color: Color, score: ScoreSnapshot, log: MovesLogSnapshot) -> None:
        """Draw `color`'s full panel at horizontal region [x, x+width),
        spanning the canvas's full height.

        Args:
            x: Left pixel edge of this panel's region on the canvas.
            width: This panel's pixel width (PANEL_WIDTH is this
                module's own recommendation, but the caller decides -
                see module docstring's LAYOUT CONTRACT).
            color: Which player's panel this is - selects both which
                MovesLogSnapshot entries are shown (see module
                docstring's FILTERING note) and which score is read
                from `score`.
            score: The current ScoreSnapshot (Stage 8's ScoreObserver).
            log: The current MovesLogSnapshot (Stage 8's
                MovesLogObserver).

        Returns:
            None.

        Ownership boundary: like HudRenderer/CooldownOverlayRenderer,
        this only draws within its own [x, x+width) region on top of
        whatever is already on the canvas - it never clears the whole
        canvas itself (PANEL_BACKGROUND_COLOR is a filled rectangle
        confined to this panel's own region, not a full-canvas clear).
        The composition root must still draw a fresh canvas each frame
        for the same "stale content smear" reason HudRenderer's own
        docstring documents.
        """

        self._render_panel_background(x, width)
        self._render_title_box(x, width, color)
        self._render_score(x, color, score)
        self._render_table(x, color, log)

    def _render_panel_background(self, x: int, width: int) -> None:
        """Filled background (PANEL_BACKGROUND_COLOR) then a light-gray
        outline (PANEL_BORDER_COLOR) around the whole panel region -
        see module docstring's BORDER/HIGHLIGHT STYLING note."""

        height = self._canvas.height
        self._canvas.draw_rectangle(x, 0, width, height, PANEL_BACKGROUND_COLOR)
        self._canvas.draw_rectangle(x, 0, width, height, PANEL_BORDER_COLOR, thickness=PANEL_BORDER_THICKNESS)

    def _render_title_box(self, x: int, width: int, color: Color) -> None:
        """The yellow-bordered color/player-name label - see module
        docstring's BORDER/HIGHLIGHT STYLING note for why this is a
        separate, smaller outline from the whole-panel border."""

        box_x = x + PANEL_PADDING
        box_width = width - 2 * PANEL_PADDING
        self._canvas.draw_rectangle(
            box_x, TITLE_BOX_Y, box_width, TITLE_BOX_HEIGHT, TITLE_BOX_BORDER_COLOR,
            thickness=TITLE_BOX_BORDER_THICKNESS,
        )
        self._canvas.draw_text(
            _COLOR_NAMES[color], box_x + 8, TITLE_TEXT_Y, color=TITLE_TEXT_COLOR, font_scale=TITLE_FONT_SCALE,
        )

    def _render_score(self, x: int, color: Color, score: ScoreSnapshot) -> None:
        text = f"Score: {score.score_by_color.get(color, 0)}"
        self._canvas.draw_text(
            text, x + PANEL_PADDING, SCORE_TEXT_Y, color=SCORE_TEXT_COLOR, font_scale=SCORE_FONT_SCALE,
        )

    def _render_table(self, x: int, color: Color, log: MovesLogSnapshot) -> None:
        """Time/Move column headers, then up to PANEL_MAX_LOG_ROWS of
        `color`'s own most recent entries (see module docstring's
        FILTERING note), oldest-of-the-visible-window first - matching
        HudRenderer's own chronological top-to-bottom log ordering."""

        time_x = x + PANEL_PADDING
        move_x = time_x + TABLE_TIME_COLUMN_WIDTH

        self._canvas.draw_text("Time", time_x, TABLE_HEADER_Y, color=TABLE_TEXT_COLOR, font_scale=TABLE_HEADER_FONT_SCALE)
        self._canvas.draw_text("Move", move_x, TABLE_HEADER_Y, color=TABLE_TEXT_COLOR, font_scale=TABLE_HEADER_FONT_SCALE)

        color_entries: Sequence[MovesLogEntry] = [entry for entry in log.entries if entry.piece_color == color]
        recent_entries = color_entries[-PANEL_MAX_LOG_ROWS:]

        for row_index, entry in enumerate(recent_entries):
            y = TABLE_FIRST_ROW_Y + row_index * TABLE_ROW_HEIGHT
            time_text = _format_clock_ms(entry.recorded_at_clock_ms)
            move_text = _format_entry_text(entry)
            self._canvas.draw_text(time_text, time_x, y, color=TABLE_TEXT_COLOR, font_scale=TABLE_ROW_FONT_SCALE)
            self._canvas.draw_text(move_text, move_x, y, color=TABLE_TEXT_COLOR, font_scale=TABLE_ROW_FONT_SCALE)
