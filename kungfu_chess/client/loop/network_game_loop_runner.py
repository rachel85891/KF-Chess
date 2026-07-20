"""NetworkGameLoopRunner: the network-mode composition root - Stage B6
of the server track. Wires a real NetworkGameClient (Stage B5) into a
real, runnable GUI window, using the SAME cv2/rendering mechanics
GameLoopRunner already established locally, but with a fundamentally
different data source: the SERVER is the sole source of truth here,
never a local GameEngine.

THE CONCEPTUAL SHIFT FROM GameLoopRunner: GameLoopRunner always OWNS an
authoritative GameEngine - every click is synchronous and immediate
(Controller.click -> GameEngine.request_move, an instant local call).
NetworkGameLoopRunner owns no GameEngine at all - a click on the local
player's own piece is translated into a NetworkGameClient.send_move
call (fire-and-forget, per Stage B5's own design); a click on a piece
that isn't the local player's own color is simply ignored (there is no
local engine to even validate it against - see NetworkClickController's
own docstring). What gets DRAWN on screen comes only from board-state
broadcasts received via NetworkGameClient.poll_incoming(), parsed via
the existing BoardParser - never from any local engine state, because
none exists.

SHARED-VS-SEPARATE CLASS STRUCTURE DECISION (explicit, per this stage's
own requirement): this is a FULLY SEPARATE class, not a subclass of or
composed around a shared base with GameLoopRunner, and
GameLoopRunner's own file is not touched by this stage AT ALL (re-
verified via diff before committing) - every one of its existing
tests/behavior stays byte-for-byte unchanged. The two classes' control
flow is fundamentally different in exactly the way the task's own
background section predicts: GameLoopRunner's per-frame loop drives a
local GameEventPublisher.wait(delta_ms), advances live
PieceAnimatorRegistry/CooldownTracker state, and reacts to a rich local
Observer event stream (Score/MovesLog/Sound); this class's per-frame
loop instead polls a raw text queue and re-parses a whole Board on
each new message, with NONE of animation/cooldown/score/moves-log/
sound existing at all in network mode (see SCOPE DECISIONS below). The
only genuinely shared, safely-extractable pieces already ARE shared,
via composition/reuse, not duplicated:
- Img/AssetCache/ImgSurface/Renderer (kungfu_chess/client/surface/,
  kungfu_chess/view/) - used exactly as GameLoopRunner uses them,
  unmodified.
- CoordinateLabelRenderer/SidePanelRenderer (kungfu_chess/client/ui/) -
  used exactly as GameLoopRunner uses them, unmodified (with empty/
  placeholder score+log data - see SCOPE DECISIONS below).
- ScreenToImageMapper/MouseAdapter (kungfu_chess/client/input/) - used
  exactly as GameLoopRunner uses them, unmodified (see "REUSING
  MouseAdapter" below for how, given MouseAdapter's own Controller-
  typed constructor parameter).
- build_snapshot_from_board (kungfu_chess/view/renderer.py, added
  fresh alongside the existing build_snapshot, this same stage) - the
  one genuinely new "shared, safely-extractable piece" this stage
  needed and didn't already have; see that function's own docstring.
Forcing an ACTUAL shared base class/composition layer between this
class and GameLoopRunner (e.g. a common "CV2WindowRunner" superclass)
was judged NOT worth it: the amount of code that would genuinely move
into such a base is small (cv2.namedWindow/waitKey/getWindowProperty/
destroyAllWindows plumbing, maybe a dozen lines) relative to how much
of each class's own per-frame body is NOT shared at all (the entire
data-source/event-handling half) - an awkward shared abstraction for a
dozen lines of cv2 plumbing would cost more in indirection than it
would save in duplication, especially since GameLoopRunner must not be
touched by this stage regardless.

REUSING MouseAdapter (kungfu_chess/client/input/mouse_adapter.py) AS-IS
- a duck-typing note: MouseAdapter's constructor type-hints its second
parameter as `controller: Controller`, and calls
`self._controller.click(x, y)` - nothing else. Python does not enforce
that type hint at runtime, and NetworkClickController
(kungfu_chess/client/network/network_click_controller.py, this same
stage) exposes the exact same `click(self, x: int, y: int) -> None`
method signature/name - so passing a NetworkClickController into
MouseAdapter's constructor works identically to passing a real
Controller, with zero changes to MouseAdapter itself. This is
structural substitution (the same principle this codebase's own
Surface Protocol already applies via structural typing, not nominal
inheritance), not a hack.

SCOPE DECISIONS (Stage B6, explicit and accepted - do not
relitigate; each is documented again at its own point of use below):
1. NO SMOOTH ANIMATION: the server's existing broadcast (Stage B3)
   sends a full board-as-text snapshot at two points per move
   (MoveAccepted = pre-move, PieceArrived = post-move), not the rich,
   continuous animation-frame event stream PieceAnimatorRegistry
   expects locally. Each new broadcast is parsed into a real Board
   (BoardParser) and pieces are redrawn STATICALLY at their new
   positions - no interpolation, no animation frames (ImgSurface is
   constructed with NO PieceAnimatorRegistry at all, using its
   already-existing, already-tested "no-registry static-idle
   fallback" path - see ImgSurface's own module docstring), no
   cooldown overlay (no CooldownTracker exists in network mode either -
   CooldownOverlayRenderer is simply never called). Smooth
   cross-network animation is explicitly OUT OF SCOPE for this stage
   and left to a separate future stage.
2. NO SCORE/MOVES-LOG TRACKING: SidePanelRenderer is still reused (per
   this stage's own "reuse existing rendering pieces" requirement), but
   fed a permanently-empty ScoreSnapshot (0-0) and MovesLogSnapshot (no
   entries) - there is no local ScoreObserver/MovesLogObserver to feed
   it real data (both are Observers of a local GameEventPublisher's own
   event stream, which does not exist in network mode). A future stage
   could reconstruct real score/log data by diffing successive parsed
   Boards, or by extending the wire protocol with structured event
   metadata instead of plain board text; out of scope here.
3. NO GAME-OVER DETECTION: raw board-state broadcast text carries no
   explicit game-over signal (see build_snapshot_from_board's own
   docstring) - GameSnapshot.game_over is always False in network
   mode. Exit conditions are therefore narrower than GameLoopRunner's
   own three (no GameOver-driven exit is possible here at all) - see
   _should_exit's own docstring.
4. NO INITIAL-STATE BROADCAST (a real, pre-existing protocol gap, not
   introduced by this stage): the server's own protocol (Stage B3)
   never sends a board-state broadcast on join - only in reaction to a
   real move event. `self.board` therefore starts as None and stays
   None until somebody (either player) makes the very first move of
   the game - at which point the very first broadcast (from
   MoveAccepted) already reflects the complete, correct starting
   position (nothing has moved yet at that instant). Until then, this
   class renders an empty board grid with no pieces at all - a
   correct, honest rendering of "no board is known yet," not a crash
   or a guess. Fixing this at the protocol level (e.g. an explicit
   "current state" message sent immediately on join) is a reasonable
   future improvement but is server-side work, out of THIS stage's own
   scope (which only wires the CLIENT).
5. NO VISUAL/AUDIO FEEDBACK FOR AN IGNORED CLICK: see
   NetworkClickController's own docstring - a deliberate, documented
   simplification, not an oversight.
6. ASSUMED INITIAL CANVAS SIZE (8x8, mirroring the ONLY board size
   GameSession has ever produced, kungfu_chess/notation/
   algebraic_notation.py's own identical BOARD_SIZE=8 assumption): the
   real canvas layout (board pixel size, panel positions) must be
   computed at CONSTRUCTION time, before any real board is known at
   all (see SCOPE DECISION 4) - there is no board to read
   width/height from yet. This assumption is never revisited after
   construction, exactly like GameLoopRunner itself never resizes its
   own canvas after construction either.
"""

from __future__ import annotations

from typing import Optional

import cv2

from kungfu_chess.client.events.observers import MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.client.input.mouse_adapter import MouseAdapter
from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.client.network.network_click_controller import NetworkClickController
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img import Img
from kungfu_chess.client.surface.img_surface import ImgSurface
from kungfu_chess.client.ui.coordinate_label_renderer import LABEL_MARGIN, CoordinateLabelRenderer
from kungfu_chess.client.ui.side_panel_renderer import PANEL_WIDTH, SidePanelRenderer
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import Renderer, build_snapshot_from_board

DEFAULT_WINDOW_NAME = "Kung Fu Chess (network)"
QUIT_KEY = "q"
CANVAS_BACKGROUND_COLOR = (0, 0, 0)

# See module docstring's SCOPE DECISION 6 - the only board size
# GameSession has ever produced, used purely to size the canvas before
# any real board is known.
_ASSUMED_BOARD_SIZE = 8

# See module docstring's SCOPE DECISION 2 - permanently empty, never
# updated; shared across every frame (nothing ever mutates these).
_EMPTY_SCORE = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
_EMPTY_LOG = MovesLogSnapshot(entries=())


class NetworkGameLoopRunnerError(Exception):
    """Base class for NetworkGameLoopRunner's own errors."""


class ConnectionRejectedError(NetworkGameLoopRunnerError):
    """Raised at construction if the server rejected this connection
    outright ("server_full" - see server/game_server.py's own
    third-plus-connection policy, and NetworkGameClient.connect's own
    None return for this exact case)."""


class NetworkGameLoopRunner:
    """The network-mode composition root - see module docstring for
    the full reasoning behind every decision below."""

    def __init__(self, uri: str, window_name: str = DEFAULT_WINDOW_NAME, headless: bool = False) -> None:
        """Connect to `uri`, learn this client's assigned color, and
        wire every reused rendering/input component around it - see
        module docstring for the full reasoning.

        Args:
            uri: The WebSocket server URI to connect to (e.g.
                "ws://localhost:8765") - never hardcoded in this class,
                matching NetworkGameClient's own convention.
            window_name: The OpenCV window title.
            headless: If True, skip real window creation and mouse-
                callback attachment - identical contract to
                GameLoopRunner's own `headless` parameter (see that
                class's own docstring for the full reasoning, which
                applies here unchanged: cv2 GUI calls abort the whole
                process on a display-less machine).

        Returns:
            None.

        Raises:
            ConnectionRejectedError: If the server responded
                "server_full" (see module docstring).
        """

        self._headless = headless
        self._window_name = window_name
        self._quit_requested = False

        self.network_client = NetworkGameClient()
        self.assigned_color = self.network_client.connect(uri)
        if self.assigned_color is None:
            self.network_client.close()
            raise ConnectionRejectedError(f"server rejected this connection (server_full): {uri}")

        self.board: Optional[Board] = None
        self.click_controller = NetworkClickController(
            assigned_color=self.assigned_color, network_client=self.network_client
        )

        self.asset_cache = AssetCache()

        # See module docstring's SCOPE DECISION 6 - computed once, from
        # an assumed board size, since no real board is known yet.
        self._board_pixel_width = _ASSUMED_BOARD_SIZE * CELL_SIZE
        self._board_pixel_height = _ASSUMED_BOARD_SIZE * CELL_SIZE
        self._board_origin_x = PANEL_WIDTH + LABEL_MARGIN
        self._board_origin_y = LABEL_MARGIN
        self._total_canvas_width = self._board_origin_x + self._board_pixel_width + LABEL_MARGIN + PANEL_WIDTH
        self._total_canvas_height = self._board_pixel_height + LABEL_MARGIN + LABEL_MARGIN

        if not headless:
            cv2.namedWindow(window_name)

        mapper = ScreenToImageMapper(window_origin=(self._board_origin_x, self._board_origin_y), window_scale=1.0)
        # NetworkClickController duck-types Controller's `click(x, y)`
        # method - see module docstring's "REUSING MouseAdapter" note.
        self.mouse_adapter = MouseAdapter(mapper, self.click_controller)
        if not headless:
            self.mouse_adapter.attach(window_name)

    def _apply_broadcast(self, text: str) -> None:
        """Parse one raw board-state broadcast and update both this
        runner's own `board` and the click controller's - the reuse
        point for the existing BoardParser (per this stage's own
        requirement to reuse it, not write a new parser).

        Args:
            text: The raw broadcast text (BoardPrinter's own format,
                the same textual convention BoardParser already
                consumes for constructing starting positions).

        Returns:
            None.

        A malformed broadcast (BoardParser returns an error) is
        silently ignored - a real, running server (this class's only
        real message source) never actually produces malformed board
        text; the check exists so a corrupted/truncated message could
        never crash this class, matching this project's broader
        "malformed input never crashes the process" convention
        (server/game_server.py's own malformed-command handling).
        """

        board, error = BoardParser().parse(text.splitlines())
        if error is not None:
            return

        self.board = board
        self.click_controller.board = board

    def poll_and_process(self) -> None:
        """Drain every new broadcast since the last call and apply each
        one, in arrival order - the per-frame network-polling step (see
        module docstring: NetworkGameClient.poll_incoming is non-
        blocking by design, exactly so a per-frame caller like this one
        never stalls waiting on network activity).

        Returns:
            None.
        """

        for text in self.network_client.poll_incoming():
            self._apply_broadcast(text)

    def run(self) -> None:
        """Run the real-time loop until one of this class's exit
        conditions is met (see _should_exit's own docstring - narrower
        than GameLoopRunner's own three, per module docstring's SCOPE
        DECISION 3), then clean up.

        Returns:
            None.
        """

        while not self._should_exit():
            self._run_one_frame()

        self.close()

    def _run_one_frame(self) -> None:
        """Run exactly one iteration: poll+apply new broadcasts, build
        a snapshot from whatever board is currently known (or an empty
        one if none has arrived yet - see module docstring's SCOPE
        DECISION 4), and render - mirrors GameLoopRunner's own
        `_run_one_frame` structure (poll -> snapshot -> render ->
        display), with every step that class performs via a local
        engine/publisher/registries removed, since none exist here.

        Returns:
            None.
        """

        self.poll_and_process()

        board_canvas = Img.blank_canvas(self._board_pixel_width, self._board_pixel_height)
        # No PieceAnimatorRegistry passed - ImgSurface's own existing
        # no-registry static-idle fallback path draws every piece at
        # its <KIND><COLOR>'s idle frame, exactly per SCOPE DECISION 1.
        surface = ImgSurface(board_canvas, self.asset_cache)

        if self.board is not None:
            snapshot = build_snapshot_from_board(self.board, selected=self.click_controller.selected)
            Renderer(surface).render(snapshot)
        else:
            # No board known yet at all (SCOPE DECISION 4) - draw an
            # empty grid using the same assumed board size the canvas
            # itself was already sized around, rather than nothing.
            surface.draw_grid(_ASSUMED_BOARD_SIZE, _ASSUMED_BOARD_SIZE)

        main_canvas = Img.blank_canvas(
            self._total_canvas_width, self._total_canvas_height, background_color=CANVAS_BACKGROUND_COLOR
        )
        main_canvas.paste(board_canvas, self._board_origin_x, self._board_origin_y)

        board_width = self.board.width if self.board is not None else _ASSUMED_BOARD_SIZE
        board_height = self.board.height if self.board is not None else _ASSUMED_BOARD_SIZE
        CoordinateLabelRenderer(main_canvas).render(board_width, board_height, self._board_origin_x, self._board_origin_y)

        # Empty placeholder score/log - see module docstring's SCOPE
        # DECISION 2.
        SidePanelRenderer(main_canvas).render(
            x=0, width=PANEL_WIDTH, color=Color.WHITE, score=_EMPTY_SCORE, log=_EMPTY_LOG
        )
        SidePanelRenderer(main_canvas).render(
            x=self._total_canvas_width - PANEL_WIDTH,
            width=PANEL_WIDTH,
            color=Color.BLACK,
            score=_EMPTY_SCORE,
            log=_EMPTY_LOG,
        )

        if self._headless:
            return

        main_canvas.show(self._window_name)

        key = cv2.waitKey(1)
        if key & 0xFF == ord(QUIT_KEY):
            self._quit_requested = True

    def _should_exit(self) -> bool:
        """True if either of this class's two real exit conditions
        currently holds - narrower than GameLoopRunner's own three
        (see module docstring's SCOPE DECISION 3: no GameOver-driven
        exit is possible in network mode, since this class can never
        detect one)."""

        if self._quit_requested:
            return True

        if self._headless:
            return False

        return cv2.getWindowProperty(self._window_name, cv2.WND_PROP_VISIBLE) < 1

    def close(self) -> None:
        """Cleanly shut down the network connection and (if not
        headless) the real window - safe to call more than once (both
        NetworkGameClient.close() and cv2.destroyWindow are themselves
        safe to call redundantly).

        Returns:
            None.
        """

        self.network_client.close()
        if not self._headless:
            cv2.destroyWindow(self._window_name)
