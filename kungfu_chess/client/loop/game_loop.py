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

VISUAL LAYOUT (Stage 13c originally assembled 13a's
CoordinateLabelRenderer and 13b's SidePanelRenderer around the board;
Stage 15 extends the margin to all four sides, not just left+bottom -
every number below is the CURRENT, post-Stage-15 formula):

- board_origin_x = PANEL_WIDTH + LABEL_MARGIN (left panel, then the
  rank-number label margin, then the board starts) - UNCHANGED by
  Stage 15.
- board_origin_y = LABEL_MARGIN (Stage 15 - was 0): re-confirmed
  directly against CoordinateLabelRenderer's own updated "CANVAS
  MARGIN" docstring, which now reserves LABEL_MARGIN on all four sides
  (including above the board, for the new top row of file letters) -
  the board must now start LABEL_MARGIN pixels down from the canvas's
  own top edge to make room for that row, exactly mirroring
  board_origin_x's own left-side reasoning.
- total_canvas_width = board_origin_x + board_pixel_width +
  LABEL_MARGIN + PANEL_WIDTH (Stage 15 - gained one more LABEL_MARGIN
  term before the right panel starts; was just `+ PANEL_WIDTH`).
  CoordinateLabelRenderer's own docstring now reserves LABEL_MARGIN on
  the right too (for the new right-side rank numbers), so the right
  panel can no longer start immediately where the board ends - it must
  now start LABEL_MARGIN pixels further right, with the label margin
  band sitting between the board's own right edge and the right
  panel's own left edge.
- total_canvas_height = board_pixel_height + LABEL_MARGIN + LABEL_MARGIN
  (Stage 15 - gained one more LABEL_MARGIN term for the new top file
  row; was just `+ LABEL_MARGIN` for the bottom one alone).
  SidePanelRenderer's own panels still run the FULL canvas height
  (self._canvas.height, read directly by that class, unchanged) - so
  each panel is now board_pixel_height + 2*LABEL_MARGIN tall, taller
  than the board sub-canvas on BOTH ends now (top and bottom), not just
  the bottom - the exact same "panel simply spans the same total
  vertical extent everything else on the canvas does" reconciliation
  Stage 13c originally established, just with one more margin band
  included in it. No conflict between CoordinateLabelRenderer's now-
  four-sided margin and SidePanelRenderer's own top-margin-free
  LAYOUT CONTRACT: SidePanelRenderer never claimed exclusive use of
  y=0..LABEL_MARGIN, it only claimed it needs no margin OF ITS OWN
  there - CoordinateLabelRenderer's top file-letter row and each
  panel's own top edge coexist at the same y range on main_canvas
  without either needing to change because of the other.
- CANVAS_BACKGROUND_COLOR: pure black, (0, 0, 0) BGR (Stage 15 -
  previously a dark navy-brown tuple) - matches the reference image's
  own backdrop exactly, rather than only approximating it. Still
  visibly distinct from SidePanelRenderer's own, lighter
  PANEL_BACKGROUND_COLOR, so the board and both panels still read as
  layered elements sitting on top of the backdrop, not blending into
  it - the same reasoning Stage 13c originally established for this
  constant, just with a more precise target color now.
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

RE-VERIFIED, NOT JUST ASSUMED, AFTER STAGE 15 CHANGED board_origin_y
(0 -> LABEL_MARGIN): this fix's own correctness does not depend on
board_origin_y's specific VALUE at all - `window_origin` is read
directly from `self._board_origin_x`/`self._board_origin_y` (above),
never a hardcoded literal, so a changed board_origin_y is picked up
automatically with no code change needed here. Re-run/extended the
existing click-regression tests (test_game_loop_runner.py) with the
new value specifically to confirm this claim empirically, not just
reason about it from the code alone - see that file's own click-offset
tests for the concrete before/after-Stage-15 verification.

SOUND EFFECTS (Stage 14): SoundManager (kungfu_chess/client/audio/
sound_manager.py) is subscribed exactly like the other four Observers
- it reacts to MoveAccepted/JumpAccepted/PieceArrived/GameOver/
PromotionEvent entirely on its own, with no per-frame involvement from
this class. The one sound this class DOES trigger directly is
"game_start" - not itself a published event (see SoundManager.
play_game_start's own docstring for why not) - called exactly once, at
the very end of __init__ (after every other wire-up, so audio_player/
sound_manager already exist), not inside run() or _run_one_frame:
__init__ runs exactly once per GameLoopRunner instance, the same
"exactly once" cardinality game-start itself has, and (unlike run(),
an infinite real-time loop no test in this suite calls directly - see
this module's own "WHY headless" section above) __init__ is already
exercised by every existing headless test, making it both the
semantically obvious place (a game starts the moment its runner
finishes being built) and the only one this project's own established
testing convention can actually verify runs exactly once.

AudioPlayer is constructed with `enabled=not headless` - see
AudioPlayer's own docstring for the full reasoning, but in short: real
OS-level sound playback must not happen during a headless test run
(most of this suite triggers real events, which SoundManager reacts to
regardless of headless), while SoundManager's own event -> sound
dispatch LOGIC must still run and be verifiable either way - `enabled`
lives on AudioPlayer as a plain, headless-agnostic mute switch, with
GameLoopRunner (the one place that already knows what "headless"
means) deciding when to set it, matching Stage 10c's own established
"headless is a composition-root decision, not a concept sub-components
need to know about" pattern exactly.

EVENTBUS WIRING (Stage A3, server track): this class now constructs
one real kungfu_chess.bus.EventBus (Stage A1) and passes it into
GameEventPublisher's own `event_bus` constructor parameter (Stage A2),
which already accepts and optionally publishes onto one - see
event_publisher.py's own "EVENTBUS INTEGRATION" docstring section for
that half of the wiring. This class's own contribution is purely
compositional: construct one instance, hand it to the publisher,
expose it. Nothing new is subscribed to it here, and nothing about
this class's own logic changes - it is additive wiring only, proven
by the tests in test_game_loop_runner_bus_wiring.py rather than by any
new inline printer/logger "just to see it work."

WHY `self.event_bus` is a public attribute, not a private local
variable inside __init__: unlike every other object __init__
constructs (asset_cache, mouse_adapter, etc.), which this class is the
sole consumer of, event_bus's entire purpose is to be reached from
OUTSIDE this class by a future stage - a server-side WS layer that
will subscribe a broadcaster to it (e.g.
`runner.event_bus.subscribe(MoveAccepted, broadcaster.on_event)`) once
that layer exists. A local variable discarded at the end of __init__
could never serve that purpose; every other attribute this class
already exposes publicly (`publisher`, `engine`, `controller`, etc.)
follows the exact same "the composition root exposes what outside code
will need to reach" pattern, so this is not a new convention, just
this stage's own instance of it.

WHY no subscriber is attached to event_bus in this stage: this stage's
entire scope is proving the CONNECTION is real, not deciding what a
future consumer of it should look like. Adding even a minimal
logger/example handler here would bake in a first, throwaway design for
"what subscribes to this bus" that a future Stage B (the real WS
broadcaster) would then have to either keep, ignore, or actively
remove - none of which is this stage's decision to make. Leaving it at
"constructed, wired into the publisher, exposed, empty" is therefore
the correct stopping point: connected and provably alive (see this
module's own bus-wiring tests), but with zero opinions imposed on
whatever subscribes to it next.

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

RESIZABLE WINDOW (bugfix): `cv2.namedWindow(window_name)` used to
default to `cv2.WINDOW_AUTOSIZE`, which explicitly disables user
resizing outright (no resize handles at all) - now
`cv2.WINDOW_NORMAL`, which allows it. Enabling resizing alone would not
have been enough on its own, though: the ScreenToImageMapper built at
construction (below) used a hardcoded `window_scale=1.0`, correct only
for a window still at its native, never-resized size - the instant a
user resized the window, every click would map to the wrong cell,
silently. The fix therefore has two real parts, both per FRAME, not
just once at construction:
1. Query the window's real, CURRENT size via
   `cv2.getWindowImageRect(window_name)` (skipped entirely in headless
   mode - there is no real window to query, so the construction-time
   mapper with window_scale=1.0 is kept and used unchanged, exactly
   matching this class's pre-fix headless behavior byte-for-byte - see
   `_run_one_frame`'s own docstring).
2. Compute a real, this-frame scale/origin from that size via
   kungfu_chess.client.input.window_fit.compute_fit_scale_and_origin
   (a NEW, separate, pure module - see that module's own docstring for
   the full reasoning on why it exists as its own file rather than
   living inside screen_mapper.py, and why it uses `min()` of both
   axes' ratios rather than independently stretching each one).
   ScreenToImageMapper ITSELF is completely untouched by this fix - its
   own docstring already documents a single uniform `window_scale` as
   a deliberate design decision; this fix's whole job is to guarantee
   that assumption actually holds true as the window's real size
   changes, not to change what ScreenToImageMapper does once given a
   scale/origin.

A fresh ScreenToImageMapper is built every non-headless frame from that
real scale/origin, and assigned directly onto
`self.mouse_adapter._mapper` (MouseAdapter's own private attribute,
reassigned from here rather than adding a public setter method to
MouseAdapter itself - MouseAdapter's own on_mouse_event method already
reads `self._mapper` fresh on every call, so a plain attribute
reassignment from this composition root is picked up correctly on the
very next click, with zero changes to MouseAdapter's own file/logic).
The rendered main_canvas is then itself resized to that same scale and
pasted, centered, onto a canvas sized to the window's own actual
dimensions (solid CANVAS_BACKGROUND_COLOR fill for any letterboxed
margin) before being shown - so the DISPLAYED image and the click-
mapping math are built from the exact same scale/origin values every
single frame, and can never silently disagree with each other.

DEGENERATE WINDOW SIZE (e.g. minimized - a deliberate, defensive
choice, not an afterthought): compute_fit_scale_and_origin returns a
non-positive `scale` for a non-positive window width/height, rather
than raising. When that happens, this class skips the mapper
refresh entirely for that frame (the LAST known-good mapper stays in
place on `self.mouse_adapter`) and shows `main_canvas` at its own
native size, unscaled - there is no meaningful "fit into a
window of size zero" to compute, and reusing the last good mapper is
strictly safer than either crashing or building one around
nonsensical numbers.

NOT EMPIRICALLY VERIFIED IN THIS ENVIRONMENT (an honest, accepted gap,
not a claim of certainty): this sandboxed environment has no real
display, so the actual runtime behavior of a real
`cv2.getWindowImageRect` call against a real, human-resized window
could not be directly executed and observed here, unlike this
project's own usual "verified directly from source before writing
this" standard for cv2 APIs. The pure fit-math
(compute_fit_scale_and_origin) is thoroughly unit-tested in isolation;
the cv2-facing half of this fix relies on cv2's own documented
contract for `getWindowImageRect`/`WINDOW_NORMAL` and needs a human,
with a real display, to confirm empirically (see this module's own
final manual-verification instructions in the task this fix was
written for).
"""

from __future__ import annotations

import time

import cv2

from kungfu_chess.bus.event_bus import EventBus
from kungfu_chess.client.audio.audio_player import AudioPlayer
from kungfu_chess.client.audio.sound_manager import SoundManager
from kungfu_chess.client.events.cooldown_tracker import CooldownTracker
from kungfu_chess.client.events.event_publisher import GameEventPublisher
from kungfu_chess.client.events.game_events import GameOver
from kungfu_chess.client.events.observers import MovesLogObserver, ScoreObserver
from kungfu_chess.client.events.piece_registry import PieceRegistry
from kungfu_chess.client.animation.piece_animator_registry import PieceAnimatorRegistry
from kungfu_chess.client.input.mouse_adapter import MouseAdapter
from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.client.input.window_fit import compute_fit_scale_and_origin
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

# Pure black backdrop for the reference image's redesigned layout
# (Stage 15 - was a dark navy-brown approximation in Stage 13c; the
# reference image's own backdrop is exactly black, so this now matches
# it precisely instead of only approximating it). Still noticeably
# darker than SidePanelRenderer's own PANEL_BACKGROUND_COLOR
# (48, 33, 20) on every channel, so the panels (and the board itself)
# still read as distinct, layered elements sitting ON TOP of this
# backdrop, not blending into it.
CANVAS_BACKGROUND_COLOR = (0, 0, 0)


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

        # Stage A3 (server track) - see module docstring's "EVENTBUS
        # WIRING" section for the full reasoning: a public attribute
        # (not a private local variable) since a future server-side
        # stage must be able to reach this exact instance from OUTSIDE
        # this class to subscribe a WS broadcaster to it. Nothing is
        # subscribed to it here - this stage only proves the wiring is
        # real, deliberately leaving it an unused-but-connected bus for
        # that future stage to be the first real consumer of.
        self.event_bus = EventBus()
        self.publisher = GameEventPublisher(self.extra_engine, event_bus=self.event_bus)

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

        # enabled=not headless - see AudioPlayer's own docstring for
        # why this (not a "headless" concept inside AudioPlayer itself)
        # is the correct place to gate real OS-level playback: every
        # headless test that triggers a real event must not attempt a
        # real winsound call, while SoundManager's own event->sound
        # dispatch logic still runs and is still fully verifiable.
        self.audio_player = AudioPlayer(enabled=not headless)
        self.sound_manager = SoundManager(self.audio_player)

        self.publisher.subscribe(self.piece_animator_registry)
        self.publisher.subscribe(self.score_observer)
        self.publisher.subscribe(self.moves_log_observer)
        self.publisher.subscribe(self.cooldown_tracker)
        self.publisher.subscribe(self.sound_manager)

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
        self._board_origin_y = LABEL_MARGIN
        self._total_canvas_width = self._board_origin_x + self._board_pixel_width + LABEL_MARGIN + PANEL_WIDTH
        self._total_canvas_height = self._board_pixel_height + LABEL_MARGIN + LABEL_MARGIN

        self._window_name = window_name
        if not headless:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

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

        # Played exactly once, HERE - the end of __init__ - not inside
        # run() or _run_one_frame. See module docstring's "SOUND
        # EFFECTS" section for the full reasoning; in short: a game
        # starts the moment this class finishes wiring one up, and
        # __init__ (unlike run(), an infinite real-time loop this
        # project's own tests never call directly - see this module's
        # "WHY headless" section) is the one place already exercised by
        # every existing headless test, so this is both the
        # semantically correct AND the only practically testable place
        # for a true "exactly once, at construction" event.
        self.sound_manager.play_game_start()

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

        # Resizable-window fix - see module docstring's "RESIZABLE
        # WINDOW" section for the full reasoning. Refresh the mapper
        # AND resize/letterbox the displayed canvas from the SAME real,
        # this-frame scale/origin, every frame - never a stale one from
        # construction or an earlier frame.
        _actual_x, _actual_y, actual_width, actual_height = cv2.getWindowImageRect(self._window_name)
        scale, origin_x, origin_y = compute_fit_scale_and_origin(
            self._total_canvas_width, self._total_canvas_height, actual_width, actual_height
        )
        if scale > 0:
            self.mouse_adapter._mapper = ScreenToImageMapper(
                window_origin=(round(origin_x), round(origin_y)), window_scale=scale
            )
            resized = main_canvas.resize(round(self._total_canvas_width * scale), round(self._total_canvas_height * scale))
            display_canvas = Img.blank_canvas(actual_width, actual_height, background_color=CANVAS_BACKGROUND_COLOR)
            display_canvas.paste(resized, round(origin_x), round(origin_y))
        else:
            # Degenerate/minimized window - see module docstring's
            # "DEGENERATE WINDOW SIZE" section: skip the mapper refresh
            # (the last known-good one stays on self.mouse_adapter) and
            # show main_canvas at its own native size, unscaled.
            display_canvas = main_canvas

        display_canvas.show(self._window_name)

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
