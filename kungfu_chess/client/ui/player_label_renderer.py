"""PlayerLabelRenderer: draws a small "who is this panel" label between
SidePanelRenderer's own Score line and its Time/Move table header -
distinguishing the LOCAL player's own panel from the opponent's in the
network GUI window.

WHY THIS GAP EXISTED: Stage C1's shell login (kungfu_chess/client/
home_screen.py's prompt_username) collects a real username, but it was
only ever shown once, in the terminal, at connect time - it never
reached the GUI at all, and SidePanelRenderer's own title box already
labels each side "White"/"Black" (see that module's own _COLOR_NAMES)
but has no notion of "which of these two panels is ME" versus "which is
my opponent". This module closes both gaps at once, without touching
SidePanelRenderer itself (per this stage's own explicit requirement).

DOES NOT MODIFY SidePanelRenderer IN ANY WAY: this is a second,
independent renderer drawn into the SAME [x, x+width) horizontal region
a caller's own SidePanelRenderer.render(...) call already used for that
color - mirrors kungfu_chess/client/ui/captured_pieces_renderer.py's
own established pattern exactly (a small, separate, SRP-focused
renderer, not folded into SidePanelRenderer's own render() method).

LAYOUT PLACEMENT - DERIVED FROM SidePanelRenderer's OWN PUBLIC
CONSTANTS, NOT A HARDCODED MAGIC NUMBER (mirrors
CapturedPiecesRenderer's own identical "reuse the panel's own layout
constants" convention): PLAYER_LABEL_Y is the midpoint between
SCORE_TEXT_Y (the panel's own score line) and TABLE_HEADER_Y (the
panel's own "Time | Move" table header) - the one genuinely free strip
of vertical space in the panel's existing layout that isn't already
occupied by the title box, the score line, or the table itself. Using
the midpoint (rather than a fixed offset from either constant) means
this label's own vertical position automatically re-centers itself in
whatever gap remains if SidePanelRenderer's own SCORE_TEXT_Y/
TABLE_HEADER_Y constants are ever adjusted, instead of silently drifting
out of that gap. This needs no new canvas space at all (unlike
GameTimerRenderer, kungfu_chess/client/ui/game_timer_renderer.py, which
does) - it fits entirely within the panel's own already-reserved
background rectangle (SidePanelRenderer's own panel already spans the
full canvas height).

DOES NOT LEARN OR RENDER THE OPPONENT'S REAL USERNAME - A DELIBERATE
SCOPE BOUNDARY, NOT A GAP: the wire protocol (server/application/
game_server.py) never transmits any player's username at this stage
(kungfu_chess/client/home_screen.py's own "SCOPE" docstring section -
the username collected by prompt_username is cosmetic-only, local to
its own process) - there is no real opponent username this class could
ever legitimately obtain. format_player_label therefore always shows a
fixed OPPONENT_LABEL_TEXT ("Opponent") for `is_local_player=False`,
regardless of what `username` argument is passed for that call - never
inventing, guessing, or otherwise fabricating a name the local process
was never told. Learning the opponent's real username would require a
wire-protocol change (transmitting it at join time, alongside color
assignment) - explicitly out of this stage's own scope.

WHY `username` CAN BE None FOR THE LOCAL PLAYER TOO (backward
compatibility, per this stage's own explicit requirement):
NetworkGameLoopRunner's own `username` constructor parameter defaults
to None (so any EXISTING construction - e.g. every already-passing
headless integration test that never passed a username - keeps working
unchanged). format_player_label's own local-player branch therefore
falls back to a generic "You" in that case, rather than rendering the
literal string "None" or raising - the same "correct, honest default
before real data exists" convention this codebase already applies
elsewhere (e.g. NetworkGameLoopRunner's own `self.board = None` until
the first broadcast arrives).

COLOR CHOICES REUSE SidePanelRenderer's OWN EXISTING BGR CONSTANTS, NOT
NEW ARBITRARY ONES: the local player's own label uses
SidePanelRenderer.TITLE_BOX_BORDER_COLOR (the same golden-yellow
already used to highlight each panel's own title box) - visually tying
"this is the highlighted/gold one" to "this is you", without inventing
a new accent color. The opponent's label uses
SidePanelRenderer.TABLE_TEXT_COLOR (the same neutral light gray the
Time/Move table's own rows already use) - a deliberately less emphatic
color, since this is the side that ISN'T the local player.
"""

from __future__ import annotations

from typing import Optional

from kungfu_chess.client.surface.img import Img
from kungfu_chess.client.ui.side_panel_renderer import (
    PANEL_PADDING,
    SCORE_TEXT_Y,
    TABLE_HEADER_Y,
    TABLE_TEXT_COLOR,
    TITLE_BOX_BORDER_COLOR,
)
from kungfu_chess.model.color import Color

# See module docstring's "LAYOUT PLACEMENT" section - the midpoint of
# the one free vertical strip already present in SidePanelRenderer's
# own existing layout, not a new, independently-drifting magic number.
PLAYER_LABEL_Y = SCORE_TEXT_Y + (TABLE_HEADER_Y - SCORE_TEXT_Y) // 2
PLAYER_LABEL_FONT_SCALE = 0.5

LOCAL_PLAYER_LABEL_COLOR = TITLE_BOX_BORDER_COLOR
OPPONENT_LABEL_COLOR = TABLE_TEXT_COLOR

OPPONENT_LABEL_TEXT = "Opponent"
_LOCAL_PLAYER_FALLBACK_NAME = "You"


def format_player_label(username: Optional[str], color: Color, is_local_player: bool) -> str:
    """The exact text shown for one side's panel - see module docstring
    for the full reasoning behind every branch below.

    Args:
        username: The LOCAL player's own cosmetic username
            (kungfu_chess.client.home_screen.prompt_username's return
            value), or None if none was ever collected/passed (backward
            compatibility - see module docstring). Only ever used when
            `is_local_player` is True - see "DOES NOT LEARN..." section
            for why a truthy `username` is always ignored for the
            opponent's own label.
        color: This panel's own Color (White or Black).
        is_local_player: Whether this panel belongs to the connection's
            own assigned color (True) or the opponent's (False).

    Returns:
        e.g. "Alice (You) - White" (local, named), "You - White"
        (local, no username collected), or "Opponent - Black" (the
        opponent's panel, always - see module docstring).
    """

    color_name = color.name.capitalize()

    if not is_local_player:
        return f"{OPPONENT_LABEL_TEXT} - {color_name}"

    display_name = username if username else _LOCAL_PLAYER_FALLBACK_NAME
    suffix = " (You)" if username else ""
    return f"{display_name}{suffix} - {color_name}"


class PlayerLabelRenderer:
    """Draws one panel's own "who is this" label - see module docstring
    for the full layout/wording reasoning."""

    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as SidePanelRenderer/CapturedPiecesRenderer's own canvas
        injection."""

        self._canvas = canvas

    def render(self, x: int, color: Color, username: Optional[str], is_local_player: bool) -> None:
        """Draw this panel's own label at horizontal region starting at
        `x` - the SAME `x` a caller's own SidePanelRenderer.render(x=x,
        ...) call already used for this color (see module docstring's
        "LAYOUT PLACEMENT" section).

        Args:
            x: Left pixel edge of this panel's region on the canvas -
                identical to the x already passed to SidePanelRenderer
                for this same color.
            color: This panel's own Color.
            username: See format_player_label.
            is_local_player: See format_player_label.

        Returns:
            None.
        """

        text = format_player_label(username, color, is_local_player)
        text_color = LOCAL_PLAYER_LABEL_COLOR if is_local_player else OPPONENT_LABEL_COLOR
        self._canvas.draw_text(
            text, x + PANEL_PADDING, PLAYER_LABEL_Y, color=text_color, font_scale=PLAYER_LABEL_FONT_SCALE,
        )
