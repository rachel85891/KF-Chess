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
"""

from __future__ import annotations

from kungfu_chess.client.surface.img import Img
from kungfu_chess.model.color import Color

MESSAGE_TEXT_COLOR = (255, 255, 255)
MESSAGE_FONT_SCALE = 1.2


class GameOverOverlayRenderer:
    """Draws "Game Over - <color> wins" roughly centered on the given
    canvas - see module docstring for the full reasoning."""

    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as every other renderer's own canvas injection in this
        package."""

        self._canvas = canvas

    def render(self, winner_color: Color) -> None:
        """Draw the end-of-game message.

        Args:
            winner_color: The Color whose king was NOT captured (see
                kungfu_chess/client/events/game_events.py's own
                GameOver docstring) - the side this message reports as
                having won.

        Returns:
            None.

        Positioning mirrors ImgSurface.draw_game_over_message's own
        "approximate centering" convention exactly (x = canvas.width //
        4, y = canvas.height // 2, x floored at 10) - not pixel-perfect
        text-metrics centering, the same reasonable placeholder
        treatment that method's own docstring already accepts.
        """

        winner_name = "White" if winner_color is Color.WHITE else "Black"
        text = f"Game Over - {winner_name} wins"

        x = max(10, self._canvas.width // 4)
        y = self._canvas.height // 2
        self._canvas.draw_text(text, x, y, color=MESSAGE_TEXT_COLOR, font_scale=MESSAGE_FONT_SCALE)
