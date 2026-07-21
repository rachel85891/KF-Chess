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
1. SPRITE ANIMATION, BUT NOT PIXEL-POSITION INTERPOLATION (Stage B6's
   original "NO SMOOTH ANIMATION" gap, PARTIALLY closed by Stage B7 -
   see "STAGE B7 - REAL EVENT-DRIVEN ANIMATION" below for the full
   reasoning on exactly what changed and, just as importantly, what
   deliberately did NOT): a real PieceAnimatorRegistry now runs in
   network mode, reacting to real, translated MoveAccepted/JumpAccepted/
   PieceArrived events - a piece's SPRITE now genuinely transitions
   idle -> move/jump -> idle, the same live per-frame walk-cycle
   GameLoopRunner's own local play already shows. What this stage does
   NOT add: PIXEL-position interpolation (a piece visibly sliding,
   pixel-by-pixel, between two cells while its motion is in flight) -
   that is build_snapshot's own SEPARATE mechanism (kungfu_chess/view/
   renderer.py), driven by a local GameEngine's RealTimeArbiter.
   active_motions()/engine.state.clock_ms, neither of which this class
   has or is permitted to add this stage (see "Do NOT modify
   PieceAnimatorRegistry, PieceAnimator, GameLoopRunner, or Controller"
   in this stage's own task, which - by naming only NetworkGameLoopRunner
   and the server's broadcaster as gaining new capability - implicitly
   also excludes renderer.py/build_snapshot_from_board from this
   stage's scope). Net effect: a piece's on-screen POSITION still
   updates in one discrete jump, exactly when the next board-text
   resync (or, more precisely now, the next successfully-translated
   PieceArrived - see "STAGE B7" below) updates its logical cell -
   but for the FULL DURATION of that motion, its SPRITE already shows
   real move/jump animation frames, not a frozen idle pose. This is a
   real, honest, deliberately-scoped gap, not an oversight - closing it
   fully would require either giving NetworkGameLoopRunner its own
   client-side Motion-interpolation mechanism (duplicating
   RealTimeArbiter's own job) or extending build_snapshot_from_board
   itself (out of this stage's own explicit scope) - left to a future
   stage.
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

RESIZABLE WINDOW (bugfix, applied identically to GameLoopRunner - see
that class's own module docstring's "RESIZABLE WINDOW" section for the
full reasoning, which applies here unchanged): `cv2.namedWindow(...)`
now passes `cv2.WINDOW_NORMAL` (was the default WINDOW_AUTOSIZE, which
disables user resizing outright), and every non-headless frame
re-queries the window's real current size
(cv2.getWindowImageRect), computes a real scale/origin via
kungfu_chess.client.input.window_fit.compute_fit_scale_and_origin (the
same new, shared, pure module GameLoopRunner uses - not duplicated
math, per this fix's own DRY requirement), rebuilds ScreenToImageMapper
from those real values, and resizes+letterboxes the rendered canvas to
match before showing it. Exactly like GameLoopRunner: headless mode
skips this whole block entirely (the construction-time
window_scale=1.0 mapper is used unchanged), and a degenerate/minimized
window size skips the mapper refresh for that frame, reusing the last
known-good mapper. ScreenToImageMapper/MouseAdapter/
NetworkClickController are all completely untouched by this fix - the
mapper is refreshed by direct reassignment of
`self.mouse_adapter._mapper`, the same mechanism GameLoopRunner uses,
for the same reason (MouseAdapter re-reads `self._mapper` fresh on
every click, so no setter method needs to be added to it).

BUGFIX (fix/resizable-window-click-mapping-bug): the above was never
actually run against a real window/real clicks when first written -
doing so (against GameLoopRunner first, then re-verified against this
class identically) revealed the per-frame mapper rebuild was silently
dropping `self._board_origin_x`/`self._board_origin_y` (the board's
own offset within the canvas, past the left panel/label margin) - see
game_loop.py's own "RESIZABLE WINDOW - CLICK MAPPING BUGFIX" docstring
section for the full real, logged evidence. Fixed identically here:
the board's own offset, scaled by this frame's real scale factor, is
now composed on top of the canvas's own letterbox origin before
building the mapper.

STAGE B7 - REAL EVENT-DRIVEN ANIMATION: server/game_server.py now
broadcasts a structured wire-format message (kungfu_chess/notation/
game_event_wire_format.py) for MoveAccepted/JumpAccepted/PieceArrived,
alongside (not instead of) its existing board-text snapshot broadcast.
This class now parses those wire messages back into real event
objects and feeds them into a real PieceAnimatorRegistry via on_event -
the exact same method GameLoopRunner's own local publisher subscription
calls it with - so PieceAnimator's own state-machine logic is entirely
unaware its caller changed. Two real design problems had to be solved
to make this work correctly, neither anticipated by "just forward the
event" alone:

PROBLEM 1 - SERVER piece_id IS NOT PORTABLE TO THIS PROCESS:
kungfu_chess.model.piece.Piece.id is assigned from a process-global
counter (re-verified directly in piece.py) - the SERVER's own
piece_id (baked into every wire event) was assigned in the SERVER's
own process and has no relationship to any id this CLIENT process has
ever assigned to its own, separately-constructed Piece objects (this
class's own `self.board` is built via a completely independent
BoardParser.parse() call, in this process, with its own independent
id counter). Feeding a raw server piece_id straight into
piece_animator_registry.on_event would almost always silently
resolve to the WRONG PieceAnimator (or none at all) - not a crash, but
silent, wrong, or entirely absent animation. THE FIX: a per-connection
translation cache, `self._server_piece_cache: Dict[int, Piece]`,
mapping a server piece_id to the actual CLIENT-LOCAL Piece OBJECT it
refers to (not just its id - see _translate_piece's own docstring for
why the object itself, not merely its id, is cached). Populated
lazily, the first time a MoveAccepted/JumpAccepted for that
server_piece_id is ever seen by THIS client: only MoveAccepted/
JumpAccepted carry a `from_cell`, letting this class resolve
`self.board.piece_at(from_cell)` - reliable specifically because a
MoveAccepted's own accompanying board-text broadcast (still sent,
per the scope decision below) always reflects the board's PRE-this-
move state (nothing has moved yet at the instant MoveAccepted fires -
docs/spec.md's own "board changes only after arrival" rule), so
`from_cell` is guaranteed still occupied by the right piece at
translation time. A later PieceArrived for the SAME server_piece_id
(which carries no from_cell at all) is then translated via a pure
cache lookup, no board lookup needed. A client that only ever
observes a PieceArrived for a piece it never saw move (e.g. it joined
mid-motion, after that piece's own MoveAccepted had already been
broadcast to earlier-joined clients) is a real, but narrow and
honestly documented, gap: translation fails, and that specific
event's own animation transition is skipped - see _translate_piece and
_handle_piece_arrived's own docstrings for the exact fallback
behavior, and the RECONCILIATION POLICY below for why `self.board`
itself does not silently drift wrong forever because of it.

PROBLEM 2 - BoardParser ASSIGNS A FRESH id TO EVERY PIECE ON EVERY
PARSE, WHICH BREAKS PIECE IDENTITY ACROSS SUCCESSIVE BOARD-TEXT
BROADCASTS: before Stage B7, `_apply_broadcast` replaced
`self.board` WHOLESALE on every single broadcast (re-parsing the
entire board from scratch each time) - harmless before this stage,
since nothing needed piece IDENTITY to survive across broadcasts (only
occupancy, read fresh each frame). Now that a real
PieceAnimatorRegistry exists, keyed by piece_id and built ONCE (see
below), a wholesale re-parse on every later broadcast would silently
assign brand-new ids to every piece, permanently orphaning
piece_animator_registry's own id -> PieceAnimator mapping (every piece
drawn after the second broadcast would raise UnknownPieceIdError) and
invalidating `self._server_piece_cache` itself. THE FIX -
RECONCILIATION POLICY (the exact policy this stage's own task asked
for, decided and justified here): `self.board` is now set from a
freshly-parsed Board exactly ONCE - the first board-text broadcast
this client ever receives (SCOPE DECISION 4 below) - and
`self.piece_animator_registry` is built from that SAME, ONE Board via
PieceAnimatorRegistry.from_board at that same moment. Every
subsequent board-text broadcast is treated purely as a read-only
SANITY CHECK, never a replacement: `_log_resync_mismatch` compares its
occupancy (kind+color per cell) against `self.board`'s own current
occupancy and only ever PRINTS a diagnostic message on a genuine
disagreement - it never mutates `self.board`, never replaces any
Piece object, and never calls piece_animator_registry.on_event. All
REAL position changes to `self.board` after the first broadcast
happen exclusively through `_handle_piece_arrived`'s own direct,
in-place `Board.move_piece`/`remove_piece` calls, driven by real,
successfully-translated PieceArrived events - this preserves every
Piece object's identity/id for the rest of the session (Piece is
already documented, in kungfu_chess/model/piece.py, as a mutable
entity for exactly this reason: "state and cell change in place...
without every holder of a reference needing to swap to a freshly-
replaced instance"). WHY THIS SATISFIES "NEVER FORCE-RESET AN
ANIMATOR MID-MOTION": an animator's own visual/sprite state is driven
ONLY by real events reaching piece_animator_registry.on_event - a
resync's own mismatch-logging path never calls on_event at all (it
has no event to synthesize one from - a raw occupancy diff is not an
event), so it structurally CANNOT disrupt an in-flight animation,
regardless of what it finds. The one honestly-accepted consequence
(see PROBLEM 1's own "narrow gap" paragraph above): a piece whose
arrival could never be translated (the rare mid-motion-join case) has
its OWN specific position error only ever surfaced via
_log_resync_mismatch's diagnostic print, never silently and never
auto-corrected - the same category of "documented, accepted gap for a
genuinely rare edge case" this codebase already applies elsewhere
(e.g. SCOPE DECISION 4's own pre-existing "no initial state on join"
gap, before that was separately fixed at the protocol level).
"""

from __future__ import annotations

import os
import time
from typing import Dict, Optional, Union

import cv2

from kungfu_chess.client.animation.piece_animator_registry import PieceAnimatorRegistry
from kungfu_chess.client.events.game_events import JumpAccepted, MoveAccepted, PieceArrived
from kungfu_chess.client.events.observers import MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.client.input.mouse_adapter import MouseAdapter
from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.client.input.window_fit import compute_fit_scale_and_origin
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
from kungfu_chess.model.piece import Piece
from kungfu_chess.model.position import Position
from kungfu_chess.notation.game_event_wire_format import (
    EVENT_MESSAGE_PREFIX,
    MalformedGameEventWireFormatError,
    parse_game_event,
)
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import Renderer, build_snapshot_from_board

DEFAULT_WINDOW_NAME = "Kung Fu Chess (network)"
QUIT_KEY = "q"
CANVAS_BACKGROUND_COLOR = (0, 0, 0)

# TEMPORARY debug instrumentation - see game_loop.py's own identical
# flag/docstring note; applied identically here per this fix's own
# requirement to fix both runners the same way.
_DEBUG_CLICKS = bool(os.environ.get("KF_CHESS_DEBUG_CLICKS"))

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

        # Stage B7 - see module docstring's "STAGE B7 - REAL EVENT-
        # DRIVEN ANIMATION" section for the full reasoning behind both:
        # piece_animator_registry is built once, from the FIRST real
        # board this client ever receives (_apply_broadcast); until
        # then it stays None, and ImgSurface (see _run_one_frame) falls
        # back to its own existing no-registry static-idle rendering.
        # _server_piece_cache maps a SERVER piece_id to the actual
        # CLIENT-LOCAL Piece object it refers to (see _translate_piece)
        # - process-local ids are not portable between the server and
        # this client process, so every wire event's own piece_id must
        # be translated through this cache before being fed to
        # piece_animator_registry.on_event.
        self.piece_animator_registry: Optional[PieceAnimatorRegistry] = None
        self._server_piece_cache: Dict[int, Piece] = {}

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
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        mapper = ScreenToImageMapper(window_origin=(self._board_origin_x, self._board_origin_y), window_scale=1.0)
        # NetworkClickController duck-types Controller's `click(x, y)`
        # method - see module docstring's "REUSING MouseAdapter" note.
        self.mouse_adapter = MouseAdapter(mapper, self.click_controller)
        if not headless:
            self.mouse_adapter.attach(window_name)
            if _DEBUG_CLICKS:
                self._attach_debug_mouse_callback(window_name)

    def _attach_debug_mouse_callback(self, window_name: str) -> None:
        """TEMPORARY debug instrumentation (KF_CHESS_DEBUG_CLICKS) -
        identical mechanism to GameLoopRunner's own (see that class's
        own docstring for the full reasoning)."""

        def debug_mouse_event(event, x, y, flags, param) -> None:
            self.mouse_adapter.on_mouse_event(event, x, y, flags, param)
            if event == cv2.EVENT_LBUTTONDOWN:
                mapper = self.mouse_adapter._mapper
                image_position = mapper.to_image(x, y)
                print(
                    f"[KF_DEBUG click] raw_screen=({x},{y}) "
                    f"mapper_origin={mapper.window_origin} mapper_scale={mapper.window_scale:.6f} "
                    f"image_position=({image_position.x:.2f},{image_position.y:.2f}) "
                    f"selected_cell={self.click_controller.selected}"
                )

        cv2.setMouseCallback(window_name, debug_mouse_event)

    def _apply_broadcast(self, text: str) -> None:
        """Parse one raw board-text broadcast - the reuse point for the
        existing BoardParser (per this stage's own requirement to reuse
        it, not write a new parser). See module docstring's "PROBLEM 2"
        /"RECONCILIATION POLICY" section for the full reasoning behind
        the branch below: the FIRST board this client ever receives
        establishes `self.board`/`self.click_controller.board`/
        `self.piece_animator_registry` for the rest of the session;
        every later one is a read-only sanity check only, never a
        replacement.

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

        if self.board is None:
            self.board = board
            self.click_controller.board = board
            self.piece_animator_registry = PieceAnimatorRegistry.from_board(board)
            return

        self._log_resync_mismatch(board)

    def _log_resync_mismatch(self, resync_board: Board) -> None:
        """Compare `resync_board` (freshly parsed from a LATER
        board-text broadcast) against this runner's own, long-lived
        `self.board`, cell by cell, and print a diagnostic for any
        genuine disagreement - see module docstring's "RECONCILIATION
        POLICY" section for why this NEVER mutates `self.board`,
        replaces a Piece, or touches piece_animator_registry.

        Args:
            resync_board: The freshly-parsed Board from a board-text
                broadcast that arrived after `self.board` was already
                established.

        Returns:
            None.

        Compares (kind, color) per cell, never raw Piece identity/id -
        `resync_board`'s own pieces were assigned entirely new ids by
        this same process's BoardParser call, so comparing ids would
        always disagree even when the two boards genuinely agree about
        what is actually on the board.
        """

        assert self.board is not None

        for row in range(self.board.height):
            for col in range(self.board.width):
                cell = Position(row=row, col=col)
                own_piece = self.board.piece_at(cell)
                resync_piece = resync_board.piece_at(cell) if resync_board.in_bounds(cell) else None

                own_key = None if own_piece is None else (own_piece.kind, own_piece.color)
                resync_key = None if resync_piece is None else (resync_piece.kind, resync_piece.color)

                if own_key != resync_key:
                    print(
                        f"[NetworkGameLoopRunner] resync mismatch at {cell}: "
                        f"locally tracked={own_key}, server broadcast={resync_key}"
                    )

    def _translate_piece(self, server_piece_id: int, from_cell: Optional[Position]) -> Optional[Piece]:
        """Resolve a wire event's SERVER piece_id to the actual
        CLIENT-LOCAL Piece object it refers to - see module docstring's
        "PROBLEM 1" section for the full reasoning behind why this
        translation is necessary at all, and why the Piece OBJECT
        itself (not merely its id) is what gets cached: this method's
        own callers need both the object's `.id` (to build a translated
        event for piece_animator_registry) AND its live `.cell` (kept
        correctly up to date by Board itself on every move/removal -
        see kungfu_chess/model/board.py) - caching the object once
        gives both for free, with no separate position-tracking of its
        own to keep in sync.

        Args:
            server_piece_id: The piece_id carried by the wire event.
            from_cell: The event's own from_cell, if it has one
                (MoveAccepted/JumpAccepted only) - used to resolve a
                server_piece_id this cache has never seen before, via
                `self.board.piece_at(from_cell)`. None for PieceArrived
                (which carries no from_cell at all - see module
                docstring) - only a cache hit can resolve those.

        Returns:
            The client-local Piece, or None if it cannot be resolved
            (an unpopulated cache entry with no from_cell to fall back
            on, or self.board is still None) - see module docstring's
            "PROBLEM 1" section for why this is a real, but narrow and
            honestly accepted, gap rather than an error.
        """

        piece = self._server_piece_cache.get(server_piece_id)
        if piece is not None:
            return piece

        if from_cell is None or self.board is None:
            return None

        piece = self.board.piece_at(from_cell)
        if piece is None:
            return None

        self._server_piece_cache[server_piece_id] = piece
        return piece

    def _apply_wire_event(self, text: str) -> None:
        """Parse one wire-format event message (kungfu_chess/notation/
        game_event_wire_format.py) and dispatch it to the matching
        handler.

        Args:
            text: The raw message text - already confirmed by the
                caller (poll_and_process) to start with
                EVENT_MESSAGE_PREFIX.

        Returns:
            None.

        A malformed/unrecognized message is silently ignored -
        MalformedGameEventWireFormatError is caught here, matching this
        project's "malformed input never crashes the process"
        convention (see _apply_broadcast's own identical policy for
        board-text messages, and server/game_server.py's own
        malformed-command handling).
        """

        try:
            event = parse_game_event(text)
        except MalformedGameEventWireFormatError:
            return

        if isinstance(event, (MoveAccepted, JumpAccepted)):
            self._handle_move_or_jump_accepted(event)
        elif isinstance(event, PieceArrived):
            self._handle_piece_arrived(event)

    def _handle_move_or_jump_accepted(self, event: Union[MoveAccepted, JumpAccepted]) -> None:
        """Translate a real MoveAccepted/JumpAccepted's server piece_id
        and forward a reconstructed, client-local copy of it to
        piece_animator_registry.on_event - the exact same method
        GameLoopRunner's own local publisher subscription calls it
        with (see module docstring's "STAGE B7" section).

        Args:
            event: The real, wire-parsed MoveAccepted or JumpAccepted.

        Returns:
            None.

        Does NOT mutate self.board - per docs/spec.md's own "board
        changes only after a piece has actually reached its
        destination" rule, a piece logically stays at its from_cell
        until its own later PieceArrived (see _handle_piece_arrived).
        A translation failure (see _translate_piece) or no
        piece_animator_registry yet (self.board itself still None) is
        a safe, silent no-op - this event's own animation transition is
        simply skipped (module docstring's own documented, narrow gap).
        """

        piece = self._translate_piece(event.piece_id, event.from_cell)
        if piece is None or self.piece_animator_registry is None:
            return

        translated = type(event)(
            piece_id=piece.id, from_cell=event.from_cell, to_cell=event.to_cell, duration_ms=event.duration_ms
        )
        self.piece_animator_registry.on_event(translated)

    def _handle_piece_arrived(self, event: PieceArrived) -> None:
        """Translate a real PieceArrived's server piece_id, apply its
        real position change directly onto self.board (in place,
        preserving every Piece's identity/id - see module docstring's
        "PROBLEM 2"/"RECONCILIATION POLICY" section), and forward a
        reconstructed, client-local copy of the event to
        piece_animator_registry.on_event.

        Args:
            event: The real, wire-parsed PieceArrived.

        Returns:
            None.

        A translation failure (see _translate_piece - the documented,
        narrow "joined mid-motion" gap) or self.board still being None
        is a safe, silent no-op: neither self.board nor
        piece_animator_registry is touched for this event at all -
        that specific piece's position will only ever be caught by a
        later _log_resync_mismatch diagnostic, never silently
        auto-corrected (see module docstring for why this is an
        accepted trade-off, not an oversight).

        captured_piece_id translation is best-effort only: if the
        captured piece's own server_piece_id was never itself observed
        via a translated MoveAccepted/JumpAccepted, it is passed
        through as None rather than blocking this arrival's own
        translation - PieceAnimator never reads captured_piece_id at
        all (re-verified directly against piece_animator.py), so this
        never affects animation correctness.
        """

        piece = self._translate_piece(event.piece_id, from_cell=None)
        if piece is None or self.board is None:
            return

        if self.board.piece_at(event.cell) is not None:
            self.board.remove_piece(event.cell)
        self.board.move_piece(piece.cell, event.cell)

        captured_piece = None if event.captured_piece_id is None else self._server_piece_cache.get(event.captured_piece_id)
        translated = PieceArrived(
            piece_id=piece.id,
            cell=event.cell,
            captured_piece_id=(captured_piece.id if captured_piece is not None else None),
        )
        if self.piece_animator_registry is not None:
            self.piece_animator_registry.on_event(translated)

    def poll_and_process(self) -> None:
        """Drain every new broadcast since the last call and apply each
        one, in arrival order - the per-frame network-polling step (see
        module docstring: NetworkGameClient.poll_incoming is non-
        blocking by design, exactly so a per-frame caller like this one
        never stalls waiting on network activity).

        Returns:
            None.

        Dispatches each raw message by its own distinct prefix (Stage
        B7 - see kungfu_chess/notation/game_event_wire_format.py's own
        docstring for why a wire-format event message can never be
        confused with a board-text broadcast, or vice versa): a wire
        event goes to _apply_wire_event, everything else to the
        pre-existing _apply_broadcast.
        """

        for text in self.network_client.poll_incoming():
            if text.startswith(EVENT_MESSAGE_PREFIX):
                self._apply_wire_event(text)
            else:
                self._apply_broadcast(text)

    def run(self) -> None:
        """Run the real-time loop until one of this class's exit
        conditions is met (see _should_exit's own docstring - narrower
        than GameLoopRunner's own three, per module docstring's SCOPE
        DECISION 3), then clean up.

        Returns:
            None.

        Measures real wall-clock delta_ms exactly like GameLoopRunner's
        own run() (time.perf_counter() before/after each iteration) -
        Stage B7 needs this real value to drive
        piece_animator_registry.advance_all in _run_one_frame; before
        Stage B7 no per-frame timing was needed at all in network mode.
        """

        last_time = time.perf_counter()
        while not self._should_exit():
            now = time.perf_counter()
            delta_ms = int((now - last_time) * 1000)
            last_time = now
            self._run_one_frame(delta_ms)

        self.close()

    def _run_one_frame(self, delta_ms: int = 0) -> None:
        """Run exactly one iteration: poll+apply new broadcasts, advance
        every live PieceAnimator by delta_ms, build a snapshot from
        whatever board is currently known (or an empty one if none has
        arrived yet - see module docstring's SCOPE DECISION 4), and
        render - mirrors GameLoopRunner's own `_run_one_frame`
        structure (poll -> wait/advance -> snapshot -> render ->
        display), with the steps that class performs via a local
        engine/publisher removed, since neither exists here.

        Args:
            delta_ms: Milliseconds of logical/wall-clock time since the
                previous frame, forwarded to
                piece_animator_registry.advance_all - see run()'s own
                docstring for how real callers measure this. Defaults
                to 0 (a harmless no-op advance) so existing direct
                callers (this class's own pre-Stage-B7 tests, which
                call `runner._run_one_frame()` with no delta at all)
                keep working unchanged - advance_all(0) still runs, it
                simply advances no animation time for that one call.

        Returns:
            None.
        """

        self.poll_and_process()

        if self.piece_animator_registry is not None:
            self.piece_animator_registry.advance_all(delta_ms)

        board_canvas = Img.blank_canvas(self._board_pixel_width, self._board_pixel_height)
        # Stage B7 - piece_animator_registry is passed through exactly
        # like GameLoopRunner already does (None until the first real
        # board arrives, per SCOPE DECISION 1 - ImgSurface's own
        # existing no-registry static-idle fallback path covers that
        # brief window, unchanged).
        surface = ImgSurface(board_canvas, self.asset_cache, self.piece_animator_registry)

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

        # Resizable-window fix - see module docstring's "RESIZABLE
        # WINDOW" section (identical mechanism to GameLoopRunner's own,
        # see that class's own docstring for the full reasoning).
        _actual_x, _actual_y, actual_width, actual_height = cv2.getWindowImageRect(self._window_name)
        scale, origin_x, origin_y = compute_fit_scale_and_origin(
            self._total_canvas_width, self._total_canvas_height, actual_width, actual_height
        )
        if _DEBUG_CLICKS:
            print(
                f"[KF_DEBUG frame] window_rect=({_actual_x},{_actual_y},{actual_width},{actual_height}) "
                f"canvas=({self._total_canvas_width},{self._total_canvas_height}) "
                f"scale={scale:.6f} origin=({origin_x:.3f},{origin_y:.3f})"
            )
        if scale > 0:
            # BUGFIX - see game_loop.py's own "RESIZABLE WINDOW - CLICK
            # MAPPING BUGFIX" docstring section for the full reasoning
            # (identical bug, found via the same real, logged evidence
            # against this class too): origin_x/origin_y is only the
            # CANVAS's own letterbox offset within the window - the
            # board's own offset WITHIN that canvas
            # (self._board_origin_x/_y) must be composed on top,
            # scaled by this frame's real scale factor, or every click
            # resolves board_origin_x/_y pixels too far right/down.
            board_window_origin_x = origin_x + self._board_origin_x * scale
            board_window_origin_y = origin_y + self._board_origin_y * scale
            self.mouse_adapter._mapper = ScreenToImageMapper(
                window_origin=(round(board_window_origin_x), round(board_window_origin_y)), window_scale=scale
            )
            resized = main_canvas.resize(round(self._total_canvas_width * scale), round(self._total_canvas_height * scale))
            display_canvas = Img.blank_canvas(actual_width, actual_height, background_color=CANVAS_BACKGROUND_COLOR)
            display_canvas.paste(resized, round(origin_x), round(origin_y))
        else:
            # Degenerate/minimized window - skip the mapper refresh
            # (the last known-good one stays on self.mouse_adapter) and
            # show main_canvas at its own native size, unscaled.
            display_canvas = main_canvas

        display_canvas.show(self._window_name)

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
