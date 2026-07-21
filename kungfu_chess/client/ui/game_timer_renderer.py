"""GameTimerRenderer: draws the server-authoritative elapsed game time
(mm:ss) at the top of the canvas - kungfu_chess/client/loop/
network_game_loop_runner.py's own new consumer of the server-score-
moveslog-timer-broadcast stage's "STATE:" wire message (kungfu_chess/
notation/game_state_snapshot_wire_format.py), whose clock_ms field IS
GameEngine.state.clock_ms - real elapsed logical game time, re-verified
directly in that module's own docstring.

SRP/DIP, mirroring SidePanelRenderer's own conventions exactly: a pure
function of an already-computed clock_ms integer - no engine/board/
network reference, no clock computation of its own (that decision -
static last-known-value vs. client-side interpolation between
broadcasts - is the CALLER's job; see
kungfu_chess/client/loop/network_game_loop_runner.py's own docstring
for the full reasoning behind why it interpolates before calling this
class, mirroring Stage B7.5's established "client-local timing between
authoritative updates" pattern for the identical reason pixel-sliding
needed it: refreshed only on every new event, a raw last-known value
would visibly stall between broadcasts, but a real running clock a
player is watching must never visibly freeze).

WHY ITS OWN SMALL MODULE, NOT INLINED INTO NetworkGameLoopRunner OR
FOLDED INTO GameLoopRunner: this class is independently unit-testable
without driving the whole render pipeline (the same reason every other
UI piece in this package already is its own module - CooldownOverlayRenderer,
CoordinateLabelRenderer, SidePanelRenderer). NOT added to
GameLoopRunner/game_loop.py at all - out of this stage's own explicit
scope (requirement 5): local play has its own live
GameEngine.state.clock_ms directly available already, but wiring a
local timer display was not asked for here, and doing so would touch
GameLoopRunner, which this stage's own requirement 5 explicitly
forbids modifying.

WHY ITS OWN mm:ss FORMATTER, NOT A SHARED IMPORT FROM
side_panel_renderer.py's own _format_clock_ms: that function is a
private, underscore-prefixed helper - importing it would create a
fragile cross-module coupling to another module's own private
implementation detail, and this stage's own requirement 5 forbids
modifying SidePanelRenderer's own module to promote it to a public,
shared helper. A tiny, obviously-correct 3-line duplicate is the
better trade-off than either of those - matching this codebase's own
established judgment elsewhere (e.g. CoordinateLabelRenderer already
redefines LABEL_COLOR rather than importing SidePanelRenderer's own
near-identical TABLE_TEXT_COLOR, precisely to stay decoupled, per that
module's own docstring).
"""

from __future__ import annotations

from kungfu_chess.client.surface.img import Img

TIMER_STRIP_HEIGHT = 36
TIMER_TEXT_Y = 26
TIMER_TEXT_COLOR = (255, 255, 255)
TIMER_FONT_SCALE = 0.8


def _format_clock_ms(clock_ms: int) -> str:
    """mm:ss - a running game clock reading is more meaningful to a
    player glancing at the top of the window than a raw millisecond
    count, the same reasoning side_panel_renderer.py's own identically-
    named (but not shared - see module docstring) helper already
    applies to its own Time column."""

    total_seconds = max(0, clock_ms) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


class GameTimerRenderer:
    """Draws "Time: mm:ss" at the top of the canvas - see module
    docstring for the full reasoning."""

    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as every other renderer's own canvas injection in this
        package."""

        self._canvas = canvas

    def render(self, clock_ms: int, x: int) -> None:
        """Draw the elapsed-time text at (x, TIMER_TEXT_Y).

        Args:
            clock_ms: The elapsed game time to display, in
                milliseconds - already clamped/interpolated by the
                caller (see module docstring); this method only ever
                formats and draws whatever value it is given.
            x: Left pixel edge of the text - the caller decides
                horizontal placement (mirrors SidePanelRenderer's own
                `x` parameter), e.g. centered over the board region.

        Returns:
            None.

        No new exception type is introduced, and none is needed - the
        same reasoning as every other small text-drawing renderer in
        this package (CoordinateLabelRenderer, CooldownOverlayRenderer):
        Img.draw_text never raises for any position, and a negative
        clock_ms (should one somehow occur) is simply clamped to 0
        rather than producing a nonsensical negative time reading.
        """

        text = f"Time: {_format_clock_ms(clock_ms)}"
        self._canvas.draw_text(text, x, TIMER_TEXT_Y, color=TIMER_TEXT_COLOR, font_scale=TIMER_FONT_SCALE)
