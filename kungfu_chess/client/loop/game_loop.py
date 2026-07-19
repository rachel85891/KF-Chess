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
behavior it provides, using REAL Renderer/ImgSurface/
CoordinateLabelRenderer/SidePanelRenderer drawing onto a REAL
in-memory Img canvas, without ever calling into
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

COOLDOWN TIMER (Stage 12) / MOVES LOG TIMESTAMPS (Stage 13b): a
CooldownTracker is subscribed exactly like the other three Observers.
Its set_current_clock_ms() must be called with the clock value the
upcoming publisher.wait(delta_ms) call will produce -
engine.state.clock_ms + delta_ms, computed BEFORE that call, since
wait()'s only clock mutation is a plain += ms (see CooldownTracker's
own docstring for the full reasoning on why this ordering is
required, not just convenient). moves_log_observer.set_current_clock_ms()
is called with that exact same precomputed value, right alongside it -
Stage 13b's SidePanelRenderer needs a per-entry timestamp
(MoveLogEntry/CaptureLogEntry's new recorded_at_clock_ms field) for
the same reason CooldownTracker needs "what time is it", so this
reuses the identical mechanism/value rather than computing it twice or
inventing a second way to thread a clock value in. A fresh
CooldownOverlayRenderer is constructed every frame in _run_one_frame,
exactly mirroring every other per-frame renderer's own construction
pattern - all are stateless wrappers around whatever canvas is current
this frame, so rebuilding any of them costs nothing real.

Render order (Stage 13c): board+pieces (Renderer/ImgSurface) -> cooldown
bars (CooldownOverlayRenderer) -> [pasted onto main_canvas] -> board
coordinate labels (CoordinateLabelRenderer) -> both side panels
(SidePanelRenderer). Cooldown bars are drawn onto the board's OWN
sub-canvas, before it is pasted, not after: a bar is semantically part
of the BOARD layer (it sits on a specific piece's cell, tied to board
geometry, the same as a selection highlight would be), so it must be
baked into board_canvas itself and travel with it as one pasted unit -
if it were instead drawn onto main_canvas separately, it would need
its own (board_origin_x, board_origin_y) offset threaded through
CooldownOverlayRenderer, duplicating logic paste() already provides
for free. Coordinate labels and side panels are drawn AFTER the paste,
directly onto main_canvas at their own real, final positions, since
neither is part of the board's own sub-canvas content (both are
Stage 13a/13b components that already take an explicit position/origin
of their own, per each one's own LAYOUT CONTRACT).

VISUAL LAYOUT (Stage 13c - assembles 13a's CoordinateLabelRenderer and
13b's SidePanelRenderer around the board for the first time):

- board_origin_x = PANEL_WIDTH + LABEL_MARGIN (left panel, then the
  rank-number label margin, then the board starts). board_origin_y = 0
  - re-confirmed directly against both CoordinateLabelRenderer's own
  "CANVAS MARGIN" docstring (Stage 13a: LABEL_MARGIN needed on the
  LEFT and BELOW only, nothing above) and SidePanelRenderer's own
  "LAYOUT CONTRACT" docstring (Stage 13b: panels run the canvas's full
  height starting at y=0, no top margin of their own) - the two agree
  with each other and with board_origin_y = 0; there is no conflict to
  reconcile here.
- total_canvas_width = board_origin_x + board_pixel_width + PANEL_WIDTH
  - the board's own width, plus a panel on each side. The RIGHT panel
  needs no additional label margin: CoordinateLabelRenderer's own
  docstring is explicit that "[n]othing is drawn above or to the right
  of the board," so PANEL_WIDTH alone (not PANEL_WIDTH + LABEL_MARGIN)
  is correct on that side.
- total_canvas_height = board_pixel_height + LABEL_MARGIN (room for the
  file-letter row below the board). SidePanelRenderer's own panels run
  the FULL canvas height (self._canvas.height, read directly by that
  class) - so each panel ends up board_pixel_height + LABEL_MARGIN
  tall, a few pixels TALLER than the board sub-canvas alone. This is
  the deliberate, documented reconciliation the task called for: a
  panel's bottom edge is allowed to run past the board's own bottom
  edge, down to the same y the file-label row's bottom sits at - which
  reads as entirely natural (the panel simply spans the same total
  vertical extent everything else on the canvas does), not a mismatch
  to paper over, since panels are drawn straight onto main_canvas, not
  onto the board's own sub-canvas (see "Render order" above) - there is
  no shared sub-canvas whose size the two would need to literally
  agree on.
- CANVAS_BACKGROUND_COLOR: a dark navy-brown BGR tuple, deliberately
  darker than SidePanelRenderer's own PANEL_BACKGROUND_COLOR on every
  channel (see this module's own constant definition, near the top of
  this file, for the exact value and that specific reasoning) - so the
  board and both panels read as distinct elements layered on top of
  the backdrop, matching the reference image's own layered look, not a
  flat single-color scene.
- White panel on the LEFT (x=0), Black panel on the RIGHT
  (x=total_canvas_width - PANEL_WIDTH): the reference image does not
  specify a side, so this follows the broader convention already
  implicit elsewhere in this codebase of listing/treating White first
  (e.g. HudRenderer's own now-retired score line always read
  "White: N  Black: N", White first) - a reasonable default, not a
  requirement from any spec section.

CLICK OFFSET (Stage 13c - a REAL, necessary fix, not cosmetic): once
the board's own pixel (0, 0) sits at window-pixel
(board_origin_x, board_origin_y) instead of the window's own (0, 0),
every raw mouse click MouseAdapter receives is still reported in
*window*-pixel space (cv2's own coordinate system, unaware of this
class's canvas layout) - unless corrected, a click would be
interpreted board_origin_x/board_origin_y pixels off from the piece
actually under the cursor, silently selecting/moving the wrong cell
entirely near the top-left of the board and missing it altogether
along the board's other edges.

Re-checked the real chain directly before deciding where to fix this
(MouseAdapter.on_mouse_event, kungfu_chess/client/input/mouse_adapter.py;
ScreenToImageMapper.to_image, kungfu_chess/client/input/screen_mapper.py;
Controller.click and BoardMapper.pixel_to_cell,
kungfu_chess/input/controller.py and board_mapper.py): BOTH the
left-click path (-> Controller.click) and the right-click/jump path
(-> MouseAdapter's own internal BoardMapper) already call
`self._mapper.to_image(x, y)` FIRST, before either ever reaches
BoardMapper's pixel_to_cell floor-division - and Controller.click/
BoardMapper.pixel_to_cell both already assume the x/y they receive are
board-relative, 0-origin pixels (pixel_to_cell does a bare
`x // CELL_SIZE`, with no offset concept of its own, and was not
changed here). ScreenToImageMapper's own `window_origin` field is
already documented (Stage 2, unchanged) as exactly the value that
"corresponds to image-pixel (0, 0)" - i.e. exactly the abstraction this
problem needs, already sitting at the correct layer in the pipeline
(between the raw cv2 pixel and the board-relative one), for both click
paths at once, since both paths share the SAME injected mapper
instance. The single correct fix is therefore NOT a new parameter, a
new class, or a change to Controller/BoardMapper/MouseAdapter at all -
it is constructing GameLoopRunner's own ScreenToImageMapper with
`window_origin=(self._board_origin_x, self._board_origin_y)` instead
of the old `(0, 0)` (see __init__, below) - a one-line change to an
already-existing constructor call, using the abstraction Stage 2
already built for precisely this kind of "screen space differs from
image space" problem, rather than bolting a second, redundant offset
concept onto a class further down the chain.

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

from kungfu_chess.client.events.cooldown_tracker import CooldownTracker
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
from kungfu_chess.client.ui.coordinate_label_renderer import LABEL_MARGIN, CoordinateLabelRenderer
from kungfu_chess.client.ui.cooldown_overlay_renderer import CooldownOverlayRenderer
from kungfu_chess.client.ui.side_panel_renderer import PANEL_WIDTH, SidePanelRenderer
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.extra.extra_engine import ExtraEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import Renderer, build_snapshot

DEFAULT_WINDOW_NAME = "Kung Fu Chess"
QUIT_KEY = "q"

# Dark navy-brown backdrop for the reference image's redesigned layout
# (Stage 13c) - noticeably darker than SidePanelRenderer's own
# PANEL_BACKGROUND_COLOR (48, 33, 20) on every channel, deliberately:
# the panels (and the board itself) should read as distinct, layered
# elements sitting ON TOP of this backdrop, not blend into it.
CANVAS_BACKGROUND_COLOR = (24, 16, 10)


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
        self.cooldown_tracker = CooldownTracker()

        self.publisher.subscribe(self.piece_animator_registry)
        self.publisher.subscribe(self.score_observer)
        self.publisher.subscribe(self.moves_log_observer)
        self.publisher.subscribe(self.cooldown_tracker)

        self._game_over = False
        self._quit_requested = False
        self.publisher.subscribe(_GameOverListener(self._mark_game_over))

        self.controller = Controller(self.publisher)

        # Built once, outside the frame loop - see module docstring's
        # "fresh ImgSurface per frame is cheap" note for why this is
        # the one piece of per-frame state that must NOT be rebuilt.
        self.asset_cache = AssetCache()

        # Stage 13c's full canvas layout - see module docstring's
        # "VISUAL LAYOUT" section for the complete reasoning behind
        # every one of these numbers.
        self._board_pixel_width = board.width * CELL_SIZE
        self._board_pixel_height = board.height * CELL_SIZE
        self._board_origin_x = PANEL_WIDTH + LABEL_MARGIN
        self._board_origin_y = 0
        self._total_canvas_width = self._board_origin_x + self._board_pixel_width + PANEL_WIDTH
        self._total_canvas_height = self._board_pixel_height + LABEL_MARGIN

        self._window_name = window_name
        if not headless:
            cv2.namedWindow(window_name)

        # A freshly created OpenCV window (WINDOW_AUTOSIZE, the
        # default - never resized/dragged yet) has its client area's
        # top-left pixel at window-pixel (0, 0), and draws its content
        # at native resolution with no scaling applied - window_scale
        # is still 1.0, unchanged from before Stage 13c. window_origin
        # is NOT (0, 0) anymore, though: see module docstring's "CLICK
        # OFFSET" section for why it must now be
        # (self._board_origin_x, self._board_origin_y) - the board no
        # longer starts at the window's own top-left corner, now that
        # main_canvas has a left panel and a label margin before the
        # board even begins.
        mapper = ScreenToImageMapper(window_origin=(self._board_origin_x, self._board_origin_y), window_scale=1.0)
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
        ImgSurface/CoordinateLabelRenderer/SidePanelRenderer drawing
        onto real in-memory canvases - only the final on-screen display
        and key-poll are skipped, since those are the two calls that
        actually touch cv2's GUI backend.

        Args:
            delta_ms: Milliseconds of logical/wall-clock time since
                the previous frame.

        Returns:
            None.
        """

        # Told BEFORE wait() runs, not after - see module docstring's
        # "COOLDOWN TIMER" section for why this ordering is required.
        # moves_log_observer gets the exact same value for the exact
        # same reason (Stage 13b's "Time" column) - see
        # MovesLogObserver.set_current_clock_ms's own docstring for why
        # this reuses CooldownTracker's already-established mechanism
        # rather than inventing a second one.
        upcoming_clock_ms = self.engine.state.clock_ms + delta_ms
        self.cooldown_tracker.set_current_clock_ms(upcoming_clock_ms)
        self.moves_log_observer.set_current_clock_ms(upcoming_clock_ms)

        self.publisher.wait(delta_ms)
        self.piece_animator_registry.advance_all(delta_ms)

        # Board + pieces + cooldown bars are drawn onto their OWN
        # board-sized sub-canvas first, in that sub-canvas's own
        # (0, 0)-origin coordinate system - Renderer, ImgSurface, and
        # CooldownOverlayRenderer are completely unchanged from
        # pre-13c behavior (see module docstring's "VISUAL LAYOUT"
        # section for why none of the three needed to change). Only
        # the fully-rendered result is pasted onto the real,
        # full-size canvas afterward.
        board_canvas = Img.blank_canvas(self._board_pixel_width, self._board_pixel_height)
        surface = ImgSurface(board_canvas, self.asset_cache, self.piece_animator_registry)

        snapshot = build_snapshot(self.engine, self.controller)
        Renderer(surface).render(snapshot)
        CooldownOverlayRenderer(board_canvas).render(
            self.engine.board, self.cooldown_tracker, self.engine.state.clock_ms
        )

        main_canvas = Img.blank_canvas(
            self._total_canvas_width, self._total_canvas_height, background_color=CANVAS_BACKGROUND_COLOR
        )
        main_canvas.paste(board_canvas, self._board_origin_x, self._board_origin_y)

        CoordinateLabelRenderer(main_canvas).render(
            self.engine.board.width, self.engine.board.height, self._board_origin_x, self._board_origin_y
        )

        # White on the left, Black on the right - see module
        # docstring's "VISUAL LAYOUT" section for why this side
        # assignment, not the reverse.
        score = self.score_observer.snapshot()
        log = self.moves_log_observer.snapshot()
        SidePanelRenderer(main_canvas).render(x=0, width=PANEL_WIDTH, color=Color.WHITE, score=score, log=log)
        SidePanelRenderer(main_canvas).render(
            x=self._total_canvas_width - PANEL_WIDTH, width=PANEL_WIDTH, color=Color.BLACK, score=score, log=log
        )

        if self._headless:
            return

        main_canvas.show(self._window_name)

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
