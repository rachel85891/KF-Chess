"""OpponentDisconnectedRenderer: draws a real, visible disconnect-
countdown message - kungfu_chess/client/loop/network_game_loop_runner.py's
own new consumer of the server's real "opponent_disconnected:<seconds>"
wire message (server/presentation/protocol_handler.py, feature/
disconnect-countdown-autoresign-e2).

SRP/DIP, mirroring GameTimerRenderer's/GameOverOverlayRenderer's own
conventions exactly: a pure function of an already-computed remaining-
seconds value - no engine/board/network reference, no countdown
INTERPOLATION of its own (that decision - computing "how much of the
server's own one-shot countdown value is left, right now" from this
client's own wall clock - is the CALLER's job, mirroring Stage B7.5's
own established "client-local timing between authoritative updates"
pattern; see kungfu_chess/client/loop/network_game_loop_runner.py's own
docstring for the full reasoning this renderer deliberately has no
opinion about).

WHY ITS OWN SMALL MODULE, NOT INLINED INTO NetworkGameLoopRunner: the
same reason every other UI piece in this package already is its own
module (CooldownOverlayRenderer, GameTimerRenderer,
GameOverOverlayRenderer) - independently unit-testable without driving
the whole render pipeline.

WHY THE DISPLAYED NUMBER ROUNDS UP (math.ceil), NOT DOWN OR TO NEAREST:
a player watching this countdown expects it to keep reading a positive
number for as long as any real time is genuinely still left - rounding
down (or to nearest) would show "0s" while a fraction of a real second
still remains, a visibly premature and wrong signal for a value this
literal (the real resignation has not happened yet). Clamped at 0 for
any negative input (the real, authoritative end is always the
server's own later "opponent_reconnected"/GameOver message, never this
renderer's own arithmetic) - mirrors GameTimerRenderer's own identical
"never show a nonsensical negative reading" clamp.
"""

from __future__ import annotations

import math

from kungfu_chess.client.surface.img import Img

OPPONENT_DISCONNECTED_TEXT_Y = 60
OPPONENT_DISCONNECTED_TEXT_COLOR = (0, 165, 255)
OPPONENT_DISCONNECTED_FONT_SCALE = 0.8


class OpponentDisconnectedRenderer:
    """Draws "Opponent disconnected - resigning in Ns" - see module
    docstring for the full reasoning."""

    def __init__(self, canvas: Img) -> None:
        """canvas is injected (DIP), not created or owned here - same
        pattern as every other renderer's own canvas injection in this
        package."""

        self._canvas = canvas

    def render(self, remaining_seconds: float, x: int) -> None:
        """Draw the disconnect-countdown text at (x,
        OPPONENT_DISCONNECTED_TEXT_Y).

        Args:
            remaining_seconds: How much of the real disconnect
                countdown is left, right now - already computed/
                interpolated by the caller (see module docstring); this
                method only ever formats and draws whatever value it is
                given.
            x: Left pixel edge of the text - the caller decides
                horizontal placement (mirrors GameTimerRenderer's own
                `x` parameter).

        Returns:
            None.
        """

        whole_seconds = max(0, math.ceil(remaining_seconds))
        text = f"Opponent disconnected - resigning in {whole_seconds}s"
        self._canvas.draw_text(
            text, x, OPPONENT_DISCONNECTED_TEXT_Y, color=OPPONENT_DISCONNECTED_TEXT_COLOR,
            font_scale=OPPONENT_DISCONNECTED_FONT_SCALE,
        )
