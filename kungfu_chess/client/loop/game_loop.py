"""GameLoopRunner: the composition root, per client_spec.md §2/§3 -
"the only high-level component that knows all the others." This is
the ONE place in the whole codebase allowed to construct every
concrete client-layer class directly (DIP's intended exception, not a
violation of it: every OTHER class in kungfu_chess/client/ depends on
injected abstractions; something has to be the place that actually
builds and wires the real ones together, exactly once).

WHY build_snapshot gets the real GameEngine, while Controller gets the
GameEventPublisher: these are two different needs, not a stray
inconsistency. Controller.click only ever reads `.board` and calls
`.request_move(...)` (kungfu_chess/input/controller.py, re-read fresh
before writing this) - both of which GameEventPublisher already
exposes (`.board`, added in this same stage's Part 0; `.request_move`,
already Stage 3's whole reason to exist) - and going through the
publisher is exactly the point, since that's what turns a real click
into published MoveAccepted/MoveRejected events every Observer reacts
to. build_snapshot (kungfu_chess/view/renderer.py), by contrast, reads
`.state.clock_ms` and `.arbiter.active_motions()` - GameEventPublisher
deliberately does NOT expose either (see Part 0's own docstring for
why: adding them would make the publisher a second GameEngine, unused
speculative surface area for the one caller - Controller - that
doesn't need them). So build_snapshot is simply given the real
`engine` reference this class already holds, directly - no need to
route a read-only snapshot-building call through the publisher at all,
since it publishes no events of its own.

WHY the game-over listener is event-driven, not polling
engine.state.game_over: this whole architecture is already built
around Observers reacting to a published event stream (Stage 3-10a) -
GameLoopRunner checking `engine.state.game_over` itself every single
frame would be a second, redundant way of learning the same fact
GameOver already announces, and would need to remember to check it at
exactly the right point in the frame (after wait(), before rendering)
rather than just reacting whenever it actually happens. Subscribing a
tiny Observer instead means "game over" is learned the same way score,
the moves log, and every PieceAnimator already learn everything else -
one consistent mechanism, not two.

WHY a fresh ImgSurface (and fresh Img canvas) is built every frame,
despite ImgSurface holding its own internal _piece_states_cache
(Stage 6/10b): that cache is only ever consulted on ImgSurface's
no-registry static-idle FALLBACK path (Stage 10b) - which this loop
never exercises, since it always constructs ImgSurface WITH a
piece_animator_registry. Rebuilding an empty, never-used cache dict
each frame therefore costs nothing real. The actually-expensive
resource - decoded sprite Img objects, loaded from disk - lives in
`asset_cache` (kungfu_chess/client/surface/asset_cache.py), which
IS built exactly once, before the frame loop starts, and reused by
every fresh ImgSurface across every frame (each new ImgSurface is
handed the SAME AssetCache instance) - so sprite loading is still
correctly cached across the whole run; only the empty, per-frame-
irrelevant _piece_states_cache is rebuilt, and rebuilding an empty
dict is free.

WHY all three loop-exit conditions exist, not just one: they are three
genuinely different real scenarios, not redundant checks on the same
underlying fact.
- GameOver (a king was captured): the GAME itself legitimately ended -
  the loop should stop even if the window and the user are both still
  there.
- The window's own visibility property drops (the user clicked the
  window's OS-level close button): nothing published a GameOver -
  the game state is still mid-play - but there is no window left to
  keep drawing into.
- The user pressed 'q': an explicit, deliberate "I want to quit" input
  distinct from either of the above - the window is still open and the
  game isn't over, but the user asked to stop anyway.
Any one of these can happen without either of the other two.

WHY `headless`: cv2.namedWindow/cv2.imshow/cv2.waitKey/
cv2.getWindowProperty all require a real GUI backend - on a machine
with no display (this project's own CI/sandbox environment, confirmed
directly), calling any of them doesn't raise a catchable Python
exception, it ABORTS THE WHOLE PROCESS. Every earlier stage already
established the pattern of testing real logic against a fake boundary
instead of a real window (Stage 6/9's fake/spy Img, Stage 7's stubbed
cv2.setMouseCallback) - GameLoopRunner needs the equivalent: a way to
exercise every real wiring/event/rendering/animation-advancement
behavior it provides, using REAL Renderer/ImgSurface/HudRenderer
drawing onto a REAL in-memory Img canvas, without ever calling into
cv2's GUI layer at all. `headless=True` skips exactly the calls that
touch that layer (window creation, mouse-callback attachment, on-
screen display, key polling, window-visibility polling) and nothing
else - every other line of __init__/_run_one_frame runs identically
either way. In headless mode, only ONE of the three exit conditions
above still applies: GameOver. The other two structurally cannot apply
without a real window - there is no window to close (so no visibility
check makes sense to run), and no keyboard events are ever polled (no
cv2.waitKey call happens), so `self._quit_requested` can never become
True in headless mode - it stays present in the code path (still a
real, checkable attribute) purely for symmetry/consistency, it's just
never set. This is not a workaround papering over the crash - it's the
same "test the real logic through a fake/skipped boundary" principle
every prior stage already used, applied to this one's own boundary
(cv2's GUI layer).

JUMP (Stage 11a): a real ExtraEngine (kungfu_chess/extra/extra_engine.py)
is now constructed here too, wrapping the same `engine`, and passed
into GameEventPublisher in place of the bare GameEngine it used to take
(see event_publisher.py's own docstring for the full reasoning - in
short, GameEventPublisher.wait() must now drive ExtraEngine.wait(), not
GameEngine.wait() directly, or a started jump would never land).
MouseAdapter's new on_jump_requested callback is wired to a tiny
private method (_request_jump) that calls
self.publisher.request_jump(cell) - kept as its own named method,
mirroring _mark_game_over's own reasoning, rather than a bare lambda,
so it has a name a debugger/traceback can show, and so it can freely
ignore request_jump's bool return value (MouseAdapter's callback type
is Callable[[Position], None] - a right-click has nowhere to display a
rejection reason even if there were one to show).

ERROR HANDLING: no new exception type is introduced in this file, and
none is needed. Every failure mode reachable through this class's own
code already has a more specific, existing exception raised by the
component that actually detects it: a malformed/invalid board fails
inside GameEngine/PieceRegistry.from_board/PieceAnimatorRegistry.
from_board construction with their own already-established errors; an
empty window_name fails inside MouseAdapter.attach's own
InvalidWindowNameError (kungfu_chess/client/input/mouse_adapter.py,
re-checked directly - Stage 7 already guards exactly this case, so
adding a second, redundant check here would just duplicate it).
GameLoopRunner's own job is pure orchestration - it has no validation
logic of its own to have a failure mode about.
"""

from __future__ import annotations

import time

import cv2

from kungfu_chess.client.events.event_publisher import GameEventPublisher
from kungfu_chess.client.events.game_events import GameOver
from kungfu_chess.client.events.observers import MovesLogObserver, ScoreObserver
from kungfu_chess.client.events.piece_registry import PieceRegistry
from kungfu_chess.client.animation.piece_animator_registry import PieceAnimatorRegistry
from kungfu_chess.client.input.mouse_adapter import MouseAdapter
from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img import Img
from kungfu_chess.client.surface.img_surface import ImgSurface
from kungfu_chess.client.ui.hud_renderer import HudRenderer
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.extra.extra_engine import ExtraEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import Renderer, build_snapshot

DEFAULT_WINDOW_NAME = "Kung Fu Chess"
QUIT_KEY = "q"


class _GameOverListener:
    """Observer (Stage 3 protocol) that calls back on a GameOver
    event - the mechanism behind GameLoopRunner's event-driven
    game-over detection (see this module's own docstring for why).
    Defined here, not in any other Stage's file, since it exists
    purely to serve this composition root's own internal bookkeeping,
    not as a reusable client-layer component."""

    def __init__(self, on_game_over) -> None:
        """on_game_over is injected as a plain callback (not a direct
        reference to the owning GameLoopRunner) so this listener only
        depends on the one thing it actually needs to do its job."""

        self._on_game_over = on_game_over

    def on_event(self, event: object) -> None:
        """Ignore every event except GameOver - the same "match on the
        one relevant type, ignore the rest" pattern every other
        Observer in this codebase already follows (OCP)."""

        if isinstance(event, GameOver):
            self._on_game_over()


class GameLoopRunner:
    """The composition root - see module docstring."""

    def __init__(self, board: Board, window_name: str = DEFAULT_WINDOW_NAME, headless: bool = False) -> None:
        """Wire every client-layer component together against one
        initial `board`, in the order client_spec.md §4 implies
        (engine -> publisher -> registries/observers -> subscriptions
        -> input). See this module's docstring for the reasoning
        behind the two non-obvious choices here: build_snapshot vs.
        Controller each getting a different object, and why the
        game-over listener is a subscribed Observer rather than a
        polled flag - and for `headless`, see the module docstring's
        own dedicated section.

        Args:
            board: The initial Board to play on.
            window_name: The OpenCV window title - also the identifier
                MouseAdapter.attach registers its callback against.
            headless: If True, skip real window creation and mouse-
                callback attachment entirely - defaults to False so
                real usage (client_spec.md §4's actual game loop) is
                completely unaffected.

        Returns:
            None.
        """

        self._headless = headless

        self.engine = GameEngine(board)
        self.extra_engine = ExtraEngine(self.engine)
        self.publisher = GameEventPublisher(self.extra_engine)

        # Two independent registries, snapshotting the SAME initial
        # board separately - Stage 8's PieceRegistry (kind/color
        # lookup for the Observers) and Stage 10a's
        # PieceAnimatorRegistry (live per-piece animation) serve
        # different consumers and were already designed not to be
        # merged or shared (see each one's own module docstring).
        self.piece_registry = PieceRegistry.from_board(board)
        self.piece_animator_registry = PieceAnimatorRegistry.from_board(board)

        self.score_observer = ScoreObserver(self.piece_registry)
        self.moves_log_observer = MovesLogObserver(self.piece_registry)

        self.publisher.subscribe(self.piece_animator_registry)
        self.publisher.subscribe(self.score_observer)
        self.publisher.subscribe(self.moves_log_observer)

        self._game_over = False
        self._quit_requested = False
        self.publisher.subscribe(_GameOverListener(self._mark_game_over))

        self.controller = Controller(self.publisher)

        # Built once, outside the frame loop - see module docstring's
        # "fresh ImgSurface per frame is cheap" note for why this is
        # the one piece of per-frame state that must NOT be rebuilt.
        self.asset_cache = AssetCache()

        # No extra HUD margin - client_spec.md §10's documented,
        # accepted cosmetic-only overlap (this stage's own Part 0.5).
        self._canvas_width = board.width * CELL_SIZE
        self._canvas_height = board.height * CELL_SIZE

        self._window_name = window_name
        if not headless:
            cv2.namedWindow(window_name)

        # A freshly created OpenCV window (WINDOW_AUTOSIZE, the
        # default - never resized/dragged yet) has its client area's
        # top-left pixel at window-pixel (0, 0), and draws its content
        # at native resolution with no scaling applied - exactly the
        # (window_origin, window_scale) pair ScreenToImageMapper's own
        # docstring (Stage 2) describes as the identity case: origin
        # (0, 0) maps window-pixel (0, 0) to image-pixel (0, 0), and
        # scale 1.0 means one window pixel is one image pixel.
        mapper = ScreenToImageMapper(window_origin=(0, 0), window_scale=1.0)
        self.mouse_adapter = MouseAdapter(mapper, self.controller, on_jump_requested=self._request_jump)
        if not headless:
            self.mouse_adapter.attach(window_name)

    def _mark_game_over(self) -> None:
        """The _GameOverListener's callback - kept as its own tiny
        method (rather than a bare lambda) so it has a name a
        debugger/traceback can show."""

        self._game_over = True

    def _request_jump(self, cell: Position) -> None:
        """MouseAdapter's on_jump_requested callback (see module
        docstring for why this is its own named method, not a
        lambda)."""

        self.publisher.request_jump(cell)

    def run(self) -> None:
        """Run the real-time loop until one of the three exit
        conditions is met (see module docstring), then close the
        window. In headless mode, only GameOver can end this loop
        (see module docstring's `headless` section) - and there is no
        window to close, so the closing call is skipped too.

        Returns:
            None.
        """

        last_time = time.perf_counter()
        while not self._should_exit():
            now = time.perf_counter()
            delta_ms = int((now - last_time) * 1000)
            last_time = now
            self._run_one_frame(delta_ms)

        if not self._headless:
            cv2.destroyAllWindows()

    def _run_one_frame(self, delta_ms: int) -> None:
        """Run exactly one iteration of client_spec.md §4's execution
        flow, using real wall-clock delta_ms (measured by the caller -
        run() - not assumed/fixed here, since a fixed delta would
        drift from the actual frame rate the moment rendering/OS
        scheduling takes longer or shorter than expected).

        Extracted as its own method (rather than inlined in run()'s
        while-loop) specifically so it can be called exactly once,
        directly, in a test - the same reasoning as every other Stage
        in this codebase that separates "the logic" from "the loop/
        window shell around it."

        In headless mode (see module docstring), every real step still
        runs - publisher.wait, advance_all, and real Renderer/
        ImgSurface/HudRenderer drawing onto a real in-memory canvas -
        only the final on-screen display and key-poll are skipped,
        since those are the two calls that actually touch cv2's GUI
        backend.

        Args:
            delta_ms: Milliseconds of logical/wall-clock time since
                the previous frame.

        Returns:
            None.
        """

        self.publisher.wait(delta_ms)
        self.piece_animator_registry.advance_all(delta_ms)

        canvas = Img.blank_canvas(self._canvas_width, self._canvas_height)
        surface = ImgSurface(canvas, self.asset_cache, self.piece_animator_registry)

        snapshot = build_snapshot(self.engine, self.controller)
        Renderer(surface).render(snapshot)

        HudRenderer(canvas).render(self.score_observer.snapshot(), self.moves_log_observer.snapshot())

        if self._headless:
            return

        canvas.show(self._window_name)

        # 1ms, not 0 (which blocks indefinitely waiting for a keypress
        # - the opposite of a real-time loop) and not a longer value
        # (which would needlessly cap the frame rate) - just enough
        # for OpenCV's HighGUI backend to actually pump window/mouse
        # events for this frame.
        key = cv2.waitKey(1)
        # Masked with 0xFF: cv2.waitKey's return value can have extra
        # platform-specific bits set above the low byte - the standard
        # OpenCV idiom for comparing it to an ASCII key code.
        if key & 0xFF == ord(QUIT_KEY):
            self._quit_requested = True

    def _should_exit(self) -> bool:
        """True if any of the three documented exit conditions (see
        module docstring) currently holds. In headless mode, only
        GameOver/quit_requested are even checkable - there is no real
        window, so no window-visibility check is made (see module
        docstring's `headless` section)."""

        if self._game_over or self._quit_requested:
            return True

        if self._headless:
            return False

        return cv2.getWindowProperty(self._window_name, cv2.WND_PROP_VISIBLE) < 1
