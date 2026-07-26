"""GameOverOverlayRenderer: draws a real, winner-naming end-of-game
message - kungfu_chess/client/loop/network_game_loop_runner.py's own
new consumer of a real, parsed GameOver wire event (kungfu_chess/
notation/game_event_wire_format.py, fix/network-gameover-and-king-
interception).

SRP/DIP, mirroring GameTimerRenderer's own conventions exactly: a pure
function of an already-known winner_color - no engine/board/network
reference, no game-over DETECTION of its own (that decision already
happened upstream, in ExtraEngine.wait/GameEventPublisher.wait - see
those modules' own docstrings - by the time this class is ever called
at all).

WHY "Game Over - <color> wins", NOT "Checkmate - <color> wins": this
project's own docs/spec.md §2 explicitly states checkmate is NOT
implemented ("The game does not implement check, checkmate, castling,
promotion (in the standard sense), or en passant. A king can be
captured. Capturing the opposing king ends the game.") - using
"Checkmate" here would name a win condition this project doesn't
actually have. "Game Over" is the accurate, spec-consistent term for
the one real win condition that does exist (a captured king).

WHY ITS OWN SMALL MODULE, NOT A MODIFICATION OF
kungfu_chess/client/surface/img_surface.py's own existing
draw_game_over_message: that method draws a generic "GAME OVER" string
with no winner information at all, and is scoped to LOCAL play's own
board sub-canvas (ImgSurface itself, injected with a
PieceAnimatorRegistry) - modifying it to also accept/display a winner
would change its signature for every existing local-play caller/test
that already depends on it taking no arguments. A new, independently
unit-testable class - the same "its own small module" reasoning
GameTimerRenderer's own docstring already gives - avoids that, at the
cost of one small, obviously-correct duplicate of ImgSurface's own
"approximate centering" convention (x = canvas.width // 4, y =
canvas.height // 2) reused here verbatim for visual consistency between
local and network play's own end-of-game treatments.

STAGE D3 - OPTIONAL `own_rating_change` PARAMETER (feature/elo-rating-
update-d3): server/application/game_server.py's own new ELO-update-on-
GameOver mechanism (see that class's own "STAGE D3" docstring section)
gives this client its own real (old_rating, new_rating) pair - this
class draws it as a SECOND line, directly below the existing "Game Over
- <color> wins" message, reusing the EXISTING GameOver client UX (this
stage's own explicit requirement) rather than inventing a second,
separate overlay. Defaults to None (draws nothing extra) - a strict,
backward-compatible no-op for every pre-existing caller that never
knew ratings existed (this class's own pre-D3 unit tests, unchanged,
still pass verbatim), matching this project's own established "new,
optional parameter defaulting to a no-op" convention (e.g.
GameEventPublisher's own `event_bus: Optional[EventBus] = None`).
"Your rating: <old> -> <new> (<+/-delta>)" - the exact wording this
stage's own task example specifies verbatim - is computed here, not
passed in pre-formatted, mirroring GameTimerRenderer's own "the caller
hands over already-computed VALUES, this class only ever formats and
draws them" boundary (the caller - NetworkGameLoopRunner - hands over
the raw (old, new) ints it parsed from the real "rating_update:<old>:
<new>" wire message, nothing more).
"""

from __future__ import annotations

from typing import Optional, Tuple

from kungfu_chess.client.surface.img import Img
from kungfu_chess.model.color import Color

MESSAGE_TEXT_COLOR = (255, 255, 255)
MESSAGE_FONT_SCALE = 1.2
RATING_CHANGE_TEXT_COLOR = (255, 255, 255)
RATING_CHANGE_FONT_SCALE = 0.9
RATING_CHANGE_LINE_SPACING = 40


class GameOverOverlayRenderer:
    """Draws "Game Over - <color> wins" roughly centered on the given
    canvas, and (Stage D3, optional) a second line naming this client's
    own real rating change - see module docstring for the full
    reasoning."""

    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as every other renderer's own canvas injection in this
        package."""

        self._canvas = canvas

    def render(self, winner_color: Color, own_rating_change: Optional[Tuple[int, int]] = None) -> None:
        """Draw the end-of-game message, and (if given) a real rating-
        change line beneath it.

        Args:
            winner_color: The Color whose king was NOT captured (see
                kungfu_chess/client/events/game_events.py's own
                GameOver docstring) - the side this message reports as
                having won.
            own_rating_change: (old_rating, new_rating) for THIS
                client's own account, if a real Stage D3 rating update
                has already arrived - see module docstring's "STAGE D3"
                section. Defaults to None (no second line drawn at
                all) - the correct, honest default before any such
                update has arrived yet, and the only behavior every
                pre-D3 caller of this method ever needs.

        Returns:
            None.

        Positioning mirrors ImgSurface.draw_game_over_message's own
        "approximate centering" convention exactly (x = canvas.width //
        4, y = canvas.height // 2, x floored at 10) - not pixel-perfect
        text-metrics centering, the same reasonable placeholder
        treatment that method's own docstring already accepts. The
        rating-change line (if any) shares the same x, RATING_CHANGE_
        LINE_SPACING pixels further down.
        """

        winner_name = "White" if winner_color is Color.WHITE else "Black"
        text = f"Game Over - {winner_name} wins"

        x = max(10, self._canvas.width // 4)
        y = self._canvas.height // 2
        self._canvas.draw_text(text, x, y, color=MESSAGE_TEXT_COLOR, font_scale=MESSAGE_FONT_SCALE)

        if own_rating_change is not None:
            old_rating, new_rating = own_rating_change
            delta = new_rating - old_rating
            sign = "+" if delta >= 0 else ""
            rating_text = f"Your rating: {old_rating} -> {new_rating} ({sign}{delta})"
            self._canvas.draw_text(
                rating_text, x, y + RATING_CHANGE_LINE_SPACING,
                color=RATING_CHANGE_TEXT_COLOR, font_scale=RATING_CHANGE_FONT_SCALE,
            )
