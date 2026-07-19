"""HudRenderer: draws score + a recent-moves log onto an Img canvas,
per client_spec.md §3 (corrected: depends on Img directly, not the
Surface Protocol - see that section's footnote for why).

DEPRECATED (Stage 13b): the reference image's visual redesign replaces
this fixed-corner-overlay HUD with bordered per-player side panels -
see kungfu_chess/client/ui/side_panel_renderer.py's SidePanelRenderer,
which is the intended long-term replacement for this whole class. This
file is KEPT, not deleted, in Stage 13b specifically because
GameLoopRunner._run_one_frame still calls HudRenderer(canvas).
render(...) every real frame, and Stage 13b's own scope deliberately
excludes touching that wiring or the canvas sizing SidePanelRenderer's
two-panels-plus-board layout needs (see SidePanelRenderer's own module
docstring's LAYOUT CONTRACT) - deleting this class now would break a
currently-working, currently-tested render path with nothing wired in
to replace it. Stage 13c (expected to own GameLoopRunner's canvas/
render-pipeline wiring) is the right place to swap the
HudRenderer(canvas).render(...) call for two SidePanelRenderer(canvas)
.render(...) calls and then delete this file outright - there is no
third, in-between state intended for this class beyond "still wired,
now superseded."

SRP: this class only turns ScoreSnapshot/MovesLogSnapshot into text on
a canvas - it never computes score or maintains a log itself (Stage
8's ScoreObserver/MovesLogObserver own that), and never draws the
board/pieces (ImgSurface's job).

DIP: depends only on Img's public drawing methods and the two snapshot
types, both passed in - never constructs GameEventPublisher, the
Observers, or GameEngine itself.

OWNERSHIP BOUNDARY (read this before wiring Stage 10's GameLoopRunner):
render() never clears the canvas - it only draws HUD text on top of
whatever is already there. HudRenderer holds no state of its own
besides the injected canvas reference, so render() is a pure function
of the snapshots it's given each call: calling it twice with the same
snapshots draws the same text in the same place both times (idempotent
in that sense), but it will NOT erase stale HUD text from a previous,
different snapshot if the canvas itself was never redrawn in between.
The composition root MUST draw the board fresh (a new/cleared canvas,
or ImgSurface.draw_grid + draw_piece overwriting the previous frame)
BEFORE calling HudRenderer.render() each frame - exactly the order
client_spec.md §4 already describes (Renderer.render, then
HudRenderer). Getting this order backwards, or skipping the board
redraw, leaves old HUD text visibly smeared under new HUD text.

ERROR HANDLING: no new exception type is introduced here, and none is
needed. Checked directly (not assumed): Img.draw_text (Stage 6) wraps
cv2.putText, which never raises for an out-of-canvas text position -
it silently clips instead, matching cv2's own drawing-primitive
convention elsewhere in this class (draw_rectangle behaves the same
way). This class's own text positions (SCORE_TEXT_POSITION,
LOG_FIRST_LINE_POSITION, LOG_LINE_HEIGHT) are all fixed module-level
constants it chose itself, not derived from external/unbounded input,
so "out of bounds" isn't a condition this class can even construct for
itself. The two name lookups (_COLOR_NAMES, _KIND_NAMES) are populated
exhaustively over Color's and PieceKind's full, closed enum membership
- every real ScoreSnapshot/MovesLogSnapshot entry's piece_color/kind is
necessarily one of those members (the type system guarantees it), so
neither lookup can KeyError given a well-formed snapshot. render() is
therefore safe by construction, not defensively guarded.
"""

from __future__ import annotations

from kungfu_chess.client.events.observers import CaptureLogEntry, MoveLogEntry, MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.client.surface.img import Img
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind

SCORE_TEXT_POSITION = (10, 25)
LOG_FIRST_LINE_POSITION = (10, 55)
LOG_LINE_HEIGHT = 25
LOG_DISPLAYED_ENTRIES = 5
HUD_TEXT_COLOR = (0, 0, 0)
HUD_FONT_SCALE = 0.6

_COLOR_NAMES = {Color.WHITE: "White", Color.BLACK: "Black"}
_KIND_NAMES = {
    PieceKind.PAWN: "Pawn",
    PieceKind.KNIGHT: "Knight",
    PieceKind.BISHOP: "Bishop",
    PieceKind.ROOK: "Rook",
    PieceKind.QUEEN: "Queen",
    PieceKind.KING: "King",
}


def _format_move_entry(entry: MoveLogEntry) -> str:
    """"(jump)" is appended only for a JumpAccepted-sourced entry -
    everything else about the two wordings is identical, so a reader
    scanning the log can tell a jump from an ordinary move at a glance
    without the two looking like unrelated formats."""

    color = _COLOR_NAMES[entry.piece_color]
    kind = _KIND_NAMES[entry.piece_kind]
    jump_suffix = " (jump)" if entry.is_jump else ""
    return (
        f"{color} {kind}{jump_suffix}: ({entry.from_cell.row},{entry.from_cell.col})"
        f"->({entry.to_cell.row},{entry.to_cell.col})"
    )


def _format_capture_entry(entry: CaptureLogEntry) -> str:
    """Deliberately worded differently from a plain move ("captured...at"
    vs. "->") rather than reusing arrow notation - a capture is a
    materially different, more important event for a player skimming
    the log, and should read as visibly distinct text, not just a
    move with an extra clause."""

    color = _COLOR_NAMES[entry.piece_color]
    kind = _KIND_NAMES[entry.piece_kind]
    captured_color = _COLOR_NAMES[entry.captured_piece_color]
    captured_kind = _KIND_NAMES[entry.captured_piece_kind]
    return f"{color} {kind} captured {captured_color} {captured_kind} at ({entry.cell.row},{entry.cell.col})"


class HudRenderer:
    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - Stage
        10's composition root decides its size/lifetime, exactly as
        ImgSurface's own canvas is injected rather than self-created."""

        self._canvas = canvas

    def render(self, score: ScoreSnapshot, log: MovesLogSnapshot) -> None:
        """Draw current score and the most recent LOG_DISPLAYED_ENTRIES
        log lines onto the canvas (see this module's docstring for the
        redraw/no-clear ownership boundary this method relies on).

        Args:
            score: The current ScoreSnapshot (Stage 8's ScoreObserver).
            log: The current MovesLogSnapshot (Stage 8's
                MovesLogObserver).

        Returns:
            None.

        Screen region: both are anchored near the canvas's own
        top-left corner (SCORE_TEXT_POSITION, LOG_FIRST_LINE_POSITION)
        - the conventional corner for a HUD overlay in most games, and
        the only corner choice this class can make without knowing
        the board's own pixel footprint (ImgSurface, not HudRenderer,
        owns CELL_SIZE/board-size knowledge - SRP). Whether that
        happens to overlap the board is a canvas-sizing/composition
        decision that belongs to Stage 10's composition root, not to
        this class.

        Log cap: only the LAST LOG_DISPLAYED_ENTRIES entries are drawn
        (log.entries[-LOG_DISPLAYED_ENTRIES:]), not the whole log. A
        MovesLogSnapshot grows for the entire game, but this method
        draws a fixed vertical stack of text lines starting at a fixed
        y - an uncapped log would eventually draw past the bottom of
        any fixed-size canvas (or off top of a widening board) the
        longer a game runs. 5 lines is a deliberately small, safe
        default: 5 * LOG_LINE_HEIGHT = 125px comfortably fits under
        the score line even on a modestly-sized canvas, without this
        class needing to know the canvas's actual height to compute
        how many lines would fit.
        """

        self._render_score(score)
        self._render_log(log)

    def _render_score(self, score: ScoreSnapshot) -> None:
        """Draws one "White: N  Black: N" line - both colors on one
        line rather than two separate draw_text calls, since a score
        line is short enough that splitting it would only cost an
        extra call for no readability gain."""

        white_score = score.score_by_color.get(Color.WHITE, 0)
        black_score = score.score_by_color.get(Color.BLACK, 0)
        text = f"White: {white_score}  Black: {black_score}"
        x, y = SCORE_TEXT_POSITION
        self._canvas.draw_text(text, x, y, color=HUD_TEXT_COLOR, font_scale=HUD_FONT_SCALE)

    def _render_log(self, log: MovesLogSnapshot) -> None:
        """Draws each of the capped recent entries as its own line,
        oldest of the visible window first - so the log reads
        top-to-bottom in chronological order, matching how a reader
        would expect a running log to be ordered."""

        recent_entries = log.entries[-LOG_DISPLAYED_ENTRIES:]
        x, first_y = LOG_FIRST_LINE_POSITION

        for line_index, entry in enumerate(recent_entries):
            text = _format_capture_entry(entry) if isinstance(entry, CaptureLogEntry) else _format_move_entry(entry)
            y = first_y + line_index * LOG_LINE_HEIGHT
            self._canvas.draw_text(text, x, y, color=HUD_TEXT_COLOR, font_scale=HUD_FONT_SCALE)
