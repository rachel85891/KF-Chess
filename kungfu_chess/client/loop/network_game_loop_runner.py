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
1. SPRITE ANIMATION, AND (as of Stage B7.5) PIXEL-POSITION
   INTERPOLATION TOO (Stage B6's original "NO SMOOTH ANIMATION" gap,
   closed in two parts - Stage B7 first, Stage B7.5 completing it -
   see "STAGE B7 - REAL EVENT-DRIVEN ANIMATION" and "STAGE B7.5 -
   CLIENT-SIDE PIXEL SLIDING" below for the full reasoning): a real
   PieceAnimatorRegistry runs in network mode, reacting to real,
   translated MoveAccepted/JumpAccepted/PieceArrived events - a
   piece's SPRITE genuinely transitions idle -> move/jump -> idle
   (Stage B7). As of Stage B7.5, a piece's on-screen POSITION also
   genuinely slides, pixel-by-pixel, between its from_cell and to_cell
   for the real duration of its motion - see "STAGE B7.5" below for
   how this is computed without a local GameEngine/RealTimeArbiter at
   all (this class still has neither, and still isn't permitted to
   gain one - Stage B7.5's own task is explicit that
   PieceAnimatorRegistry/PieceAnimator/GameLoopRunner/Controller stay
   completely untouched; only this class and kungfu_chess/view/
   renderer.py's build_snapshot_from_board gain new capability this
   stage).
2. NO SCORE/MOVES-LOG TRACKING (SUPERSEDED - see "SCORE / MOVE-LOG /
   CAPTURED-PIECES / TIMER OVER THE NETWORK" below, a later stage):
   SidePanelRenderer was originally fed a permanently-empty
   ScoreSnapshot (0-0) and MovesLogSnapshot (no entries) - there was no
   local ScoreObserver/MovesLogObserver to feed it real data (both are
   Observers of a local GameEventPublisher's own event stream, which
   does not exist in network mode). The server-score-moveslog-timer-
   broadcast stage closed exactly this gap at the protocol level (a new
   "STATE:" wire message carrying real score/log/elapsed-clock data);
   this later stage is the first to actually CONSUME it client-side -
   see that section below for the full reasoning. _EMPTY_SCORE/
   _EMPTY_LOG (below) are KEPT, not deleted: they are still the correct
   INITIAL value before this client's first "STATE:" broadcast ever
   arrives (the same "correct, honest default before real data exists"
   pattern `self.board = None` already establishes for SCOPE DECISION 4
   below).
3. NO GAME-OVER DETECTION (SUPERSEDED - see "GAME OVER OVER THE
   NETWORK" below, fix/network-gameover-and-king-interception): raw
   board-state broadcast text still carries no explicit game-over
   signal and GameSnapshot.game_over is still always False in network
   mode - but this class no longer relies on that channel at all for
   game-over detection. A real, dedicated GameOver wire event
   (kungfu_chess/notation/game_event_wire_format.py) now carries this
   signal instead, exactly like every other real game event
   (MoveAccepted/PieceArrived/etc.) already does - see that section
   below for the full reasoning. _should_exit's own three-vs-fewer
   exit-condition count is UNCHANGED by this (a deliberate UX choice,
   not a remaining limitation - see that section for why).
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

STAGE B7.5 - CLIENT-SIDE PIXEL SLIDING: Stage B7 above wired real
SPRITE-state animation but left a piece's on-screen POSITION snapping
in one discrete jump on arrival (see SCOPE DECISION 1). This stage
closes that gap using data Stage B7 ALREADY transmits over the wire
but previously discarded after only feeding it to
piece_animator_registry: every MoveAccepted/JumpAccepted already
carries from_cell/to_cell/duration_ms.

WHY THE CLIENT'S OWN REAL WALL-CLOCK TIME IS SUFFICIENT, WITH NO
SERVER CLOCK SYNCHRONIZATION NEEDED (the central design decision this
stage rests on): build_snapshot's own local-play interpolation
(kungfu_chess/view/renderer.py) computes progress from a SHARED
clock - one process's single GameEngine.state.clock_ms, read by both
the code that STARTED the motion and the code that later RENDERS it,
so there is only ever one clock in play. Network play has no shared
clock at all - but it doesn't need one: a linear slide only needs to
know two things, "where did it start, where does it end" (from_cell/
to_cell, transmitted exactly) and "how long should the whole slide
visually last" (duration_ms, transmitted exactly, computed
server-side from real board distance and PIECE_SPEED - docs/spec.md
§10). Given those, this class can independently measure its OWN
elapsed time since IT received the MoveAccepted/JumpAccepted (via
`self._clock()` - see below), and produce a progress fraction that
reaches exactly 1.0 after exactly duration_ms of THIS CLIENT'S OWN
real time has passed - visually indistinguishable from a
synchronized-clock computation, modulo one real, honestly-accepted
effect: the slide's own START is delayed by however long the
MoveAccepted message itself took to travel over the network (real,
typically single-digit-to-low-double-digit milliseconds on a LAN/
localhost) - the slide is a beat LATE, never desynchronized in
DURATION or DIRECTION. This is an accepted simplification, not a
compromise the task asks to remove: no server timestamp is
transmitted, and none is needed for a visually correct slide.

`self._clock` IS INJECTABLE (a `Callable[[], float]`, defaulting to
`time.perf_counter` - this project's own established real-elapsed-time
convention, e.g. GameLoopRunner.run/GameServer.run_tick_loop, used here
in place of the task's own example `time.monotonic()` for that
consistency) - purely so tests can supply a controllable, fake time
source (a plain object with a settable `.value` the test bumps
directly) instead of a real `time.sleep`, mirroring this codebase's
general "inject the thing that varies" convention (e.g.
GameEventPublisher's own `ordering_policy`, `event_bus` parameters) -
not a new pattern invented for this stage alone.

CLIENT-SIDE MOTION TRACKING (`self._active_motions: Dict[int,
_ClientMotion]`, keyed by CLIENT-LOCAL piece_id - the SAME id space
`self._server_piece_cache`/`piece_animator_registry` already use, per
Stage B7's own translation work): populated in
_handle_move_or_jump_accepted (right alongside the existing
piece_animator_registry.on_event forwarding - same translated piece,
same from_cell/to_cell/duration_ms, just also recorded for rendering
purposes), and removed in _handle_piece_arrived the moment that
piece's own arrival is processed - a piece with no entry renders
statically at its own board cell (build_snapshot_from_board's own
existing, unchanged default), exactly matching how a piece that just
arrived should look: parked at its real, final position.

SRP - THIS TRACKING DOES NOT DUPLICATE OR CONFLICT WITH
piece_animator_registry: the two run independently, side by side,
tracking entirely different data for entirely different consumers -
`_active_motions` holds ONLY timing/position data
(from_cell/to_cell/duration_ms/started_at), consumed once per frame by
_compute_motions_for_rendering to produce pixel positions for
ImgSurface/Renderer; piece_animator_registry holds ONLY sprite/
animation-state data (idle/move/jump/frame-index), consumed by
ImgSurface to pick which sprite image to draw. Neither reads the
other's data at all - exactly the same "two independent, side-by-side
mechanisms" shape build_snapshot/PieceAnimatorRegistry already have
for local play (re-verified directly: build_snapshot's own in-flight
interpolation and PieceAnimatorRegistry's own on_event/advance_all
share no data or calls between them there either).

_compute_motions_for_rendering is its own, separately-callable method
(not inlined into _run_one_frame) specifically so it can be unit-
tested directly, with an injected fake clock, without needing to
drive the whole render pipeline (cv2/Img/ImgSurface) at all - the same
"separate the logic from the loop/window shell around it" principle
this codebase already applies everywhere else (e.g. GameLoopRunner's
own _run_one_frame extracted from run() for the identical reason).

JUMP OVER THE NETWORK (later stage - jump-network-wiring-and-cooldown-
display): right-click was already routed through MouseAdapter's own
on_jump_requested callback slot (Stage 11a, local play) - this class
simply never PASSED that callback at all until now (re-verified
directly via grep before writing this: `MouseAdapter(mapper,
self.click_controller)`, no third argument). The fix mirrors
GameLoopRunner's own local wiring exactly: __init__ now passes
`on_jump_requested=self._request_jump`, and `_request_jump` is a tiny
named method (not a lambda, for the identical debuggability reason
GameLoopRunner's own _request_jump already gives) that forwards to
`self.click_controller.request_jump(cell)` - NetworkClickController's
own new method (kungfu_chess/client/network/network_click_controller.py),
which applies the same ownership check click() already does for moves
(only this client's own assigned_color may ever be requested to jump)
and sends a real jump command via NetworkGameClient.send_jump - the
network-mode counterpart of a local ExtraEngine.request_jump call, per
this whole class's own "the server is the sole source of truth"
design.

COOLDOWN DISPLAY OVER THE NETWORK (same later stage): this class had no
CooldownTracker/CooldownOverlayRenderer at all before this stage - B7/
B7.5 only wired sprite-state animation and pixel sliding, not cooldown.
The fix constructs a real CooldownTracker in __init__ (self.
cooldown_tracker) and a fresh CooldownOverlayRenderer per frame in
_run_one_frame, mirroring GameLoopRunner's own exact composition and
render order (board+pieces drawn first, THEN cooldown bars, onto the
SAME board sub-canvas, before it is pasted onto main_canvas) - not a
new rendering concept, purely reused as-is per this stage's own DRY
requirement.

The one genuine design question this raised: CooldownTracker's own
contract (kungfu_chess/client/events/cooldown_tracker.py) requires a
`current_clock_ms` value at both event-recording time
(set_current_clock_ms) and query time (remaining_ratio's own
parameter) - GameLoopRunner supplies this from its one shared
GameEngine.state.clock_ms, but this class has no local engine and no
shared clock with the server at all (the same premise Stage B7.5
already established for pixel sliding - see that section above). THE
ANSWER: reuse the exact same `self._clock` Stage B7.5 already
introduced (real time.perf_counter() by default, fake-clock-injectable
for tests) rather than inventing a second clock abstraction -
`_clock_ms()` (a tiny new private helper) just converts that same
float-seconds value to the integer milliseconds CooldownTracker's own
constants (COOLDOWN_MS/JUMP_COOLDOWN_MS) are expressed in. No server
clock synchronization is attempted or needed here either, for the
identical reason Stage B7.5 gives: a cooldown bar only needs to know
"how much of MY OWN duration has elapsed since I started", measured
entirely on this client's own clock from the moment it received the
real PieceArrived/JumpLanded that started it - visually correct
regardless of network latency, just like a pixel slide's own progress
fraction already is.

set_current_clock_ms is called immediately before on_event in BOTH
_handle_piece_arrived (now also feeding cooldown_tracker, alongside its
pre-existing piece_animator_registry forwarding) and the new
_handle_jump_landed - mirroring GameLoopRunner's own "told BEFORE
wait()/on_event runs" ordering exactly, just triggered by a real
received wire event instead of a local wait() call about to advance a
shared clock.

BUGFIX - AttackerIntercepted NEVER REMOVED THE ATTACKER FROM THIS
CLIENT'S OWN BOARD (fix/interception-event-and-network-removal): a real,
pre-existing bug, mostly invisible locally (the real engine's own
Board already reflects the removal there, so local rendering happened
to look right by accident) but a visible, confusing one over the
network - an intercepted attacker's motion is CANCELLED, never
completed, so it never received a PieceArrived at all; this class's
own Board copy and _active_motions tracking both only ever react to
PieceArrived (see _handle_piece_arrived above) - meaning the destroyed
attacker never disappeared from a connected client's own screen and
never stopped rendering mid-motion. THE FIX: AttackerIntercepted (a
new event - see kungfu_chess/client/events/game_events.py's own
docstring for the full shape/naming reasoning) is now handled by
_handle_attacker_intercepted, mirroring _handle_piece_arrived's/
_handle_jump_landed's own established shape exactly: translate the
attacker's own server piece_id via the SAME _translate_piece cache
(from_cell=None, since AttackerIntercepted carries none - the same
narrow, accepted "joined mid-motion" translation gap PROBLEM 1 already
documents applies here identically), then remove it from self.board at
its own CLIENT-TRACKED `piece.cell` - deliberately NOT `event.cell`
(re-verified directly against jump.py's own InterceptionEvent: `cell`
there is the DEFENDER's own airborne cell, the interception's own
location, not necessarily where the attacker itself currently sits on
the board - an attacker intercepted via jump.py's Trigger 1 is
destroyed at its OWN source cell, having never reached `cell` at all;
see AttackerIntercepted's own docstring for the identical warning).
This reuses Board.remove_piece verbatim - the exact same board-mutation
primitive _handle_piece_arrived already calls for an ordinary capture,
not a second, parallel removal mechanism. Also pops the attacker's own
_active_motions entry (Stage B7.5), for the identical reason
_handle_piece_arrived/_handle_jump_landed already do: an intercepted
attacker's own MoveAccepted/JumpAccepted DID populate one, and nothing
would otherwise ever clear it (no PieceArrived is coming for this
piece, ever). The translated event is still forwarded to
piece_animator_registry.on_event, for parity with local play (where
PieceAnimatorRegistry's already-generic, type-agnostic subscription
would receive this event regardless of anything this class does) -
see piece_animator.py's own "PART B DECISION" docstring section for why
PieceAnimator itself deliberately does nothing upon receiving it (the
piece's disappearance is achieved entirely by this method's own Board
removal, never by an AnimationState transition).

defender_piece_id translation is best-effort only, mirroring
_handle_piece_arrived's own identical captured_piece_id policy: the
defender's own server_piece_id should always already be cached by the
time any interception referencing it can arrive (its own earlier
JumpAccepted already populated the cache) - but in the same narrow,
accepted "joined mid-motion" case where it somehow wasn't, the raw,
untranslated server id is passed through rather than blocking this
event's own translation, since nothing today actually reads
defender_piece_id at all (PieceAnimator ignores this whole event) -
flagged explicitly rather than left as a silent surprise for whichever
future consumer first reads it.

SCORE / MOVE-LOG / CAPTURED-PIECES / TIMER OVER THE NETWORK (later
stage - feature/network-side-panel-captured-pieces-timer): the server-
score-moveslog-timer-broadcast stage (already on main) made
server/game_server.py broadcast a "STATE:" wire message (kungfu_chess/
notation/game_state_snapshot_wire_format.py) carrying a real
ScoreSnapshot, a real MovesLogSnapshot, and the real, elapsed
GameEngine.state.clock_ms - alongside (not instead of) the existing
"EVT:"/board-text broadcasts - but nothing here ever recognized or
parsed it: `poll_and_process`'s own dispatch only ever checked for
EVENT_MESSAGE_PREFIX, falling through everything else (including
"STATE:...") to `_apply_broadcast`, whose own BoardParser call fails
silently on it (re-verified directly: a "STATE:..." line is not valid
board text, so `error is not None` and it returns doing nothing) -
this stage's own real broadcast was therefore being received and
silently discarded, exactly the gap this stage closes.

THE FIX - `_apply_state_snapshot`: `poll_and_process` now also checks
`text.startswith(STATE_SNAPSHOT_MESSAGE_PREFIX)` (before falling
through to `_apply_broadcast`, mirroring the exact same
prefix-dispatch shape the existing EVENT_MESSAGE_PREFIX check already
uses) and parses it via the EXISTING, unmodified
parse_game_state_snapshot (no second parser is written - this stage's
own explicit requirement). ALWAYS REPLACES, NEVER MERGES: re-verified
directly against game_state_snapshot_wire_format.py and
server/game_server.py - `_current_state_snapshot_text` reads
`self._session.score_observer.snapshot()`/`moves_log_observer.
snapshot()` FRESH every time it's called, and both of those methods
already return the FULL current running score / FULL accumulated log
(never a delta) - so every "STATE:" message this client will ever
receive is already a complete, authoritative snapshot; `self.
_latest_score`/`_latest_log`/`_latest_clock_ms` are therefore simply
OVERWRITTEN on each new one, never merged/accumulated locally (there
is nothing to merge - merging would be actively wrong, since the new
snapshot already includes everything the old one did, plus more).

SidePanelRenderer ITSELF IS COMPLETELY UNCHANGED (per this stage's own
requirement 5) - `_run_one_frame` simply now passes `self._latest_score`/
`self._latest_log` where it used to pass the permanently-empty
_EMPTY_SCORE/_EMPTY_LOG module constants (still used as the correct
INITIAL value before the first "STATE:" broadcast ever arrives).

CAPTURED-PIECES DISPLAY (CapturedPiecesRenderer, kungfu_chess/client/
ui/captured_pieces_renderer.py): derived PURELY from the SAME
self._latest_log already being held for SidePanelRenderer - no new
server-side tracking, no new wire data, just a second, independent
consumer of data already present (see that module's own docstring for
the full grouping-logic/layout reasoning). Drawn onto main_canvas
immediately after each color's own SidePanelRenderer.render call, using
the identical (x, width, color) triple, so it lands in the exact same
panel region, below that panel's own Time/Move table.

GAME TIMER (GameTimerRenderer, kungfu_chess/client/ui/
game_timer_renderer.py): needs a NEW top strip of canvas space
(TIMER_STRIP_HEIGHT) that did not exist before this stage -
`self._board_origin_y` and `self._total_canvas_height` both grow by
that amount. This is safe and self-contained: re-verified directly
that CoordinateLabelRenderer/SidePanelRenderer already compute every
one of their own drawing positions relative to the board_origin_x/y
parameters/canvas height they are GIVEN (never a hardcoded absolute
offset) - CoordinateLabelRenderer's own file-letter row, in particular,
is positioned at `board_origin_y - LABEL_MARGIN + ...`, so it
automatically shifts down along with the board by exactly
TIMER_STRIP_HEIGHT, opening up precisely a TIMER_STRIP_HEIGHT-tall,
previously-nonexistent band at the very top of the canvas for the
timer to occupy, with zero changes needed to either of those two
existing renderers. GameLoopRunner/local play is NOT touched by this
(per requirement 5) - this canvas-layout change is local to THIS
class's own __init__/`_run_one_frame` only.

ELAPSED-TIME DISPLAY: INTERPOLATED, NOT STATIC, BETWEEN BROADCASTS
(mirrors Stage B7.5's own established "client-local timing between
authoritative updates" pattern, per this stage's own explicit
suggestion to do so if interpolating): a "STATE:" broadcast only
arrives when a MoveAccepted/JumpAccepted/PieceArrived fires (server/
game_server.py's own broadcast trigger, re-verified directly) - during
any real lull in play (both players thinking, no move for several
seconds), a raw last-known clock_ms value would visibly FREEZE, which
is wrong for a display a player expects to behave like a real running
stopwatch. `self._latest_clock_ms_received_at` (this client's own
`self._clock()` value at the moment the latest "STATE:" was parsed) is
recorded alongside `self._latest_clock_ms`, and `_displayed_clock_ms()`
adds however much of THIS CLIENT'S OWN real time has elapsed since then
- exactly the same "no server clock synchronization needed, only
elapsed-time measurement" principle Stage B7.5 already established for
pixel-sliding progress (both the server's own tick loop and this
client's own frame loop advance at real wall-clock speed, so the two
stay closely in sync with no drift-correction logic needed; each new,
real "STATE:" broadcast is itself the correction, simply overwriting
whatever small interpolation error may have accumulated). Before the
very first "STATE:" broadcast ever arrives, `self._latest_clock_ms_
received_at` is initialized at construction time (`self._clock()`), so
the displayed timer shows a harmless "00:00" ticking up from
CONNECTION time, not a crash or a None-guard - the same "correct,
honest default" treatment this class already gives `self.board = None`
before the first board-text broadcast.

GAME OVER OVER THE NETWORK (fix/network-gameover-and-king-interception):
before this fix, network play never actually ended for a connected
client at all - a real checkmate-equivalent (a captured King) only ever
produced a silent board-text refresh, and both windows kept running
forever (see server/game_server.py's own "GameOver ADDITION" docstring
section for the server-side half of this same fix: GameOver was already
subscribed to _BROADCAST_EVENT_TYPES, but format_game_event returned
None for it, so nothing beyond the board text was ever sent). THE FIX,
CLIENT SIDE: `_apply_wire_event` now also recognizes a parsed GameOver
and dispatches it to `_handle_game_over`, which (a) sets `self._game_over
= True` and `self._game_over_winner_color = event.winner_color` (this
class's own new, honest state - defaults to False/None at construction,
mirroring `self.board = None`'s own "correct default before real data
arrives" convention) and (b) sets `self.click_controller.game_over =
True` - the actual mechanism that stops further clicks/jumps from
leaving this client (see NetworkClickController's own "GAME-OVER INPUT
FREEZE" docstring section for why that guard lives on that class, not
here).

FREEZE-AND-DISPLAY, NOT AUTO-CLOSE OR EXIT (the chosen end-of-game UX,
decided and justified here): `_should_exit` is deliberately NOT changed
to react to `self._game_over` at all - the window stays open, still
rendering every frame (via the new `if self._game_over:
GameOverOverlayRenderer(...).render(...)` block in `_run_one_frame`),
until the human closes it or presses 'q' (both pre-existing exit paths,
completely unchanged). This project has no "back to menu"/rematch flow
today (re-verified - no such mechanism exists anywhere in this
codebase), so auto-closing the window the instant GameOver arrives
would just end the session abruptly with no next step to offer the
player, and would also make it impossible for a human tester to actually
SEE the end-of-game message before the window vanished. Freezing and
displaying the result, then waiting for a manual close, is the simplest
option that gives the player a real, readable outcome without inventing
UI flow this stage was never asked to build.

GameOverOverlayRenderer (kungfu_chess/client/ui/game_over_overlay_
renderer.py, new this stage) draws "Game Over - White wins" (or "Black
wins") - deliberately NOT "Checkmate - <color> wins", even though a
captured King is this game's own checkmate-equivalent: docs/spec.md §2
explicitly states checkmate itself is not implemented, so naming it
would claim a win condition this project doesn't have. Drawn onto
`main_canvas` (the full window canvas, including both side panels), not
just `board_canvas`, mirroring GameTimerRenderer's own choice to draw
onto the full canvas rather than the board sub-canvas alone, and drawn
every frame for as long as `self._game_over` stays True (it never
becomes False again - a game, once over, stays over for the rest of
this client's own session; there is no rematch/reset path to clear it).

NO piece_id TRANSLATION NEEDED for GameOver, unlike every other handler
above (_handle_piece_arrived/_handle_jump_landed/
_handle_attacker_intercepted all call _translate_piece first): GameOver
carries no piece_id at all (see kungfu_chess/client/events/
game_events.py's own GameOver docstring - winner_color is its only
field), so `_handle_game_over` has no PROBLEM-1-style translation gap to
account for and no self.board/self.piece_animator_registry guard to
check either - there is nothing board-position-related in this event
that could still be unresolved by the time it arrives.

USERNAME REACHES THE GUI (feature/display-username-and-local-player-
label): Stage C1's shell login (kungfu_chess/client/home_screen.py's
prompt_username) collected a real username, but it was previously only
ever shown once, in the terminal, at connect time - it never reached
this class, and there was no visual way for a player to tell which of
the two on-screen panels was their own versus the opponent's
(SidePanelRenderer's own title box already labels each side "White"/
"Black", but has no notion of "which one is ME"). THE FIX: a new,
optional `username: Optional[str] = None` constructor parameter,
stored verbatim as `self.username` - defaulting to None so every
EXISTING construction (every already-passing headless test/caller that
never passed one) keeps working completely unchanged, per this
feature's own explicit backward-compatibility requirement. This class
itself never inspects or validates `username` beyond storing it - it
remains exactly the cosmetic-only value home_screen.py's own docstring
already documents (never sent to the server, never used for anything
but local display); the actual rendering decision (what text to show,
for which of the two panels, in what color) is entirely
PlayerLabelRenderer's job (kungfu_chess/client/ui/
player_label_renderer.py, see that module's own docstring), called
once per color inside `_run_one_frame` alongside the existing
SidePanelRenderer/CapturedPiecesRenderer calls, with
`is_local_player=(color is self.assigned_color)` - the one piece of
information (which color THIS connection was assigned) only this class
already holds, and PlayerLabelRenderer itself is never told the
opponent's real username (there is none to tell it - see that module's
own docstring for why it always shows a fixed "Opponent" label
instead). SidePanelRenderer itself is not modified by this change, per
this feature's own explicit requirement.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Union

import cv2

from kungfu_chess.client.animation.piece_animator_registry import PieceAnimatorRegistry
from kungfu_chess.client.events.cooldown_tracker import CooldownTracker
from kungfu_chess.client.events.game_events import (
    AttackerIntercepted,
    GameOver,
    JumpAccepted,
    JumpLanded,
    MoveAccepted,
    PieceArrived,
)
from kungfu_chess.client.events.observers import MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.client.input.mouse_adapter import MouseAdapter
from kungfu_chess.client.input.screen_mapper import ScreenToImageMapper
from kungfu_chess.client.input.window_fit import compute_fit_scale_and_origin
from kungfu_chess.client.network.network_click_controller import NetworkClickController
from kungfu_chess.client.network.network_game_client import NetworkGameClient
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img import Img
from kungfu_chess.client.surface.img_surface import ImgSurface
from kungfu_chess.client.ui.captured_pieces_renderer import CapturedPiecesRenderer
from kungfu_chess.client.ui.coordinate_label_renderer import LABEL_MARGIN, CoordinateLabelRenderer
from kungfu_chess.client.ui.cooldown_overlay_renderer import CooldownOverlayRenderer
from kungfu_chess.client.ui.game_over_overlay_renderer import GameOverOverlayRenderer
from kungfu_chess.client.ui.game_timer_renderer import TIMER_STRIP_HEIGHT, GameTimerRenderer
from kungfu_chess.client.ui.player_label_renderer import PlayerLabelRenderer
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
from kungfu_chess.notation.game_state_snapshot_wire_format import (
    STATE_SNAPSHOT_MESSAGE_PREFIX,
    MalformedGameStateSnapshotWireFormatError,
    parse_game_state_snapshot,
)
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import InFlightMotion, Renderer, build_snapshot_from_board, motion_progress

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


@dataclass(frozen=True)
class _ClientMotion:
    """One piece's client-side-tracked in-flight motion - see module
    docstring's "STAGE B7.5 - CLIENT-SIDE PIXEL SLIDING" section for
    the full reasoning. Real wall-clock timing data recorded when this
    client's own MoveAccepted/JumpAccepted translation succeeds (see
    _handle_move_or_jump_accepted); consumed every frame by
    _compute_motions_for_rendering to produce a real, clamped progress
    fraction (via renderer.motion_progress) and, from that, a real
    interpolated pixel position (via renderer.interpolate_cell_pixel,
    inside build_snapshot_from_board). Removed the moment the matching
    PieceArrived is processed (see _handle_piece_arrived)."""

    from_cell: Position
    to_cell: Position
    duration_ms: int
    started_at: float


class NetworkGameLoopRunner:
    """The network-mode composition root - see module docstring for
    the full reasoning behind every decision below."""

    def __init__(
        self,
        uri: str,
        window_name: str = DEFAULT_WINDOW_NAME,
        headless: bool = False,
        clock: Callable[[], float] = time.perf_counter,
        username: Optional[str] = None,
    ) -> None:
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
            clock: Callable returning the current time as a float
                (Stage B7.5) - defaults to time.perf_counter (this
                project's own established real-elapsed-time
                convention). Injectable (DIP) purely so tests can
                supply a controllable, fake time source instead of a
                real sleep - see module docstring's "STAGE B7.5"
                section for the full reasoning. Only ever used for
                measuring ELAPSED time (a later self._clock() call
                minus an earlier one) - never compared against any
                absolute/wall-clock meaning, so any monotonically
                comparable float source works.
            username: The LOCAL player's own cosmetic username
                (kungfu_chess.client.home_screen.prompt_username's
                return value), or None (the default) if none was ever
                collected - see module docstring's "USERNAME REACHES
                THE GUI" section. Defaults to None purely for backward
                compatibility with any existing construction that never
                passed one; never validated or transmitted anywhere by
                this class itself, only stored and later read by
                _run_one_frame's own PlayerLabelRenderer calls.

        Returns:
            None.

        Raises:
            ConnectionRejectedError: If the server responded
                "server_full" (see module docstring).
        """

        self._headless = headless
        self._window_name = window_name
        self._quit_requested = False
        self._clock = clock
        self.username = username

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

        # Stage B7.5 - see module docstring's "STAGE B7.5 - CLIENT-SIDE
        # PIXEL SLIDING" section for the full reasoning. Keyed by
        # CLIENT-LOCAL piece_id, the same id space
        # piece_animator_registry/_server_piece_cache already use.
        self._active_motions: Dict[int, _ClientMotion] = {}

        # See module docstring's "COOLDOWN DISPLAY OVER THE NETWORK"
        # section - a real CooldownTracker, fed real, translated
        # PieceArrived/JumpLanded events exactly like local play's
        # GameLoopRunner does, just using this class's own client-local
        # clock (self._clock_ms(), below) instead of a shared engine
        # clock, since no such shared clock exists in network mode.
        self.cooldown_tracker = CooldownTracker()

        # See module docstring's "SCORE / MOVE-LOG / CAPTURED-PIECES /
        # TIMER OVER THE NETWORK" section - the correct, honest INITIAL
        # values before this client's first real "STATE:" broadcast
        # ever arrives (the exact same permanently-shared-until-real-
        # data-arrives constants this class already used as a
        # placeholder, now genuinely overwritten by _apply_state_
        # snapshot once real data exists).
        self._latest_score = _EMPTY_SCORE
        self._latest_log = _EMPTY_LOG
        self._latest_clock_ms = 0
        self._latest_clock_ms_received_at = self._clock()

        # See module docstring's "GAME OVER OVER THE NETWORK" section -
        # the correct, honest INITIAL values before this client's first
        # real GameOver wire event ever arrives (mirrors self.board's
        # own None-until-first-broadcast convention).
        self._game_over = False
        self._game_over_winner_color: Optional[Color] = None

        self.asset_cache = AssetCache()

        # See module docstring's SCOPE DECISION 6 - computed once, from
        # an assumed board size, since no real board is known yet.
        # board_origin_y/total_canvas_height both grow by
        # TIMER_STRIP_HEIGHT (see module docstring's "GAME TIMER"
        # section) - a new top strip of canvas space this stage
        # introduces, that did not exist before it.
        self._board_pixel_width = _ASSUMED_BOARD_SIZE * CELL_SIZE
        self._board_pixel_height = _ASSUMED_BOARD_SIZE * CELL_SIZE
        self._board_origin_x = PANEL_WIDTH + LABEL_MARGIN
        self._board_origin_y = LABEL_MARGIN + TIMER_STRIP_HEIGHT
        self._total_canvas_width = self._board_origin_x + self._board_pixel_width + LABEL_MARGIN + PANEL_WIDTH
        self._total_canvas_height = (
            self._board_pixel_height + LABEL_MARGIN + LABEL_MARGIN + TIMER_STRIP_HEIGHT
        )

        if not headless:
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

        mapper = ScreenToImageMapper(window_origin=(self._board_origin_x, self._board_origin_y), window_scale=1.0)
        # NetworkClickController duck-types Controller's `click(x, y)`
        # method - see module docstring's "REUSING MouseAdapter" note.
        # on_jump_requested=self._request_jump wires right-click the
        # same way GameLoopRunner's own identically-named method does
        # locally (see module docstring's "JUMP OVER THE NETWORK"
        # section) - previously never passed at all in network mode.
        self.mouse_adapter = MouseAdapter(mapper, self.click_controller, on_jump_requested=self._request_jump)
        if not headless:
            self.mouse_adapter.attach(window_name)
            if _DEBUG_CLICKS:
                self._attach_debug_mouse_callback(window_name)

    def _request_jump(self, cell: Position) -> None:
        """MouseAdapter's on_jump_requested callback - mirrors
        GameLoopRunner's own identically-named method exactly (see
        that class's own docstring), just calling through to
        NetworkClickController.request_jump (this class's own network-
        mode counterpart of a local GameEventPublisher.request_jump
        call) instead of a local engine call - see module docstring's
        "JUMP OVER THE NETWORK" section."""

        self.click_controller.request_jump(cell)

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

    def _apply_state_snapshot(self, text: str) -> None:
        """Parse one raw "STATE:" broadcast (kungfu_chess/notation/
        game_state_snapshot_wire_format.py) and REPLACE this runner's
        held score/log/elapsed-clock state with it wholesale - see
        module docstring's "SCORE / MOVE-LOG / CAPTURED-PIECES / TIMER
        OVER THE NETWORK" section for the full reasoning behind why
        this is always a replacement, never a merge (every "STATE:"
        message is already a complete, authoritative snapshot).

        Args:
            text: The raw broadcast text - already confirmed by the
                caller (poll_and_process) to start with
                STATE_SNAPSHOT_MESSAGE_PREFIX.

        Returns:
            None.

        A malformed message is silently ignored - matching this
        project's "malformed input never crashes the process"
        convention (see _apply_broadcast's/_apply_wire_event's own
        identical policy); a real, running server never actually
        produces one.
        """

        try:
            score, log, clock_ms = parse_game_state_snapshot(text)
        except MalformedGameStateSnapshotWireFormatError:
            return

        self._latest_score = score
        self._latest_log = log
        self._latest_clock_ms = clock_ms
        self._latest_clock_ms_received_at = self._clock()

    def _displayed_clock_ms(self) -> int:
        """The elapsed game time to actually SHOW right now - the last
        known server-authoritative value, plus however much of this
        CLIENT's OWN real time has elapsed since it was received - see
        module docstring's "ELAPSED-TIME DISPLAY" section for the full
        reasoning (mirrors Stage B7.5's own client-local-interpolation
        pattern, applied here to a running clock instead of a pixel
        slide).

        Returns:
            An int, always >= self._latest_clock_ms (real elapsed time
            can only ever move forward between broadcasts, never
            backward).
        """

        elapsed_since_received_ms = int((self._clock() - self._latest_clock_ms_received_at) * 1000)
        return self._latest_clock_ms + elapsed_since_received_ms

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
        elif isinstance(event, JumpLanded):
            self._handle_jump_landed(event)
        elif isinstance(event, AttackerIntercepted):
            self._handle_attacker_intercepted(event)
        elif isinstance(event, GameOver):
            self._handle_game_over(event)

    def _clock_ms(self) -> int:
        """Convert self._clock()'s own float (seconds - Stage B7.5's
        convention, see _ClientMotion.started_at) into the millisecond
        integer CooldownTracker's own set_current_clock_ms/
        remaining_ratio contract expects (kungfu_chess/client/events/
        cooldown_tracker.py's own COOLDOWN_MS/JUMP_COOLDOWN_MS
        constants are both expressed in ms).

        Returns:
            A purely LOCAL, client-side clock value in milliseconds -
            no server clock synchronization is attempted, exactly the
            same reasoning Stage B7.5 already applies to pixel-sliding
            motions (see module docstring's "STAGE B7.5" section),
            applied here to cooldown durations instead: a cooldown bar
            only needs to know "how much of my own duration has elapsed
            since I started", which this client can measure entirely on
            its own.
        """

        return int(self._clock() * 1000)

    def _handle_move_or_jump_accepted(self, event: Union[MoveAccepted, JumpAccepted]) -> None:
        """Translate a real MoveAccepted/JumpAccepted's server piece_id,
        forward a reconstructed, client-local copy of it to
        piece_animator_registry.on_event - the exact same method
        GameLoopRunner's own local publisher subscription calls it
        with (see module docstring's "STAGE B7" section) - and record
        it as an active client-side motion for pixel-position rendering
        (Stage B7.5 - see module docstring's "STAGE B7.5" section).

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
        a safe, silent no-op - this event's own animation transition
        (AND its own pixel-sliding motion) is simply skipped (module
        docstring's own documented, narrow gap).
        """

        piece = self._translate_piece(event.piece_id, event.from_cell)
        if piece is None or self.piece_animator_registry is None:
            return

        translated = type(event)(
            piece_id=piece.id, from_cell=event.from_cell, to_cell=event.to_cell, duration_ms=event.duration_ms
        )
        self.piece_animator_registry.on_event(translated)

        self._active_motions[piece.id] = _ClientMotion(
            from_cell=event.from_cell, to_cell=event.to_cell, duration_ms=event.duration_ms, started_at=self._clock()
        )

    def _handle_piece_arrived(self, event: PieceArrived) -> None:
        """Translate a real PieceArrived's server piece_id, apply its
        real position change directly onto self.board (in place,
        preserving every Piece's identity/id - see module docstring's
        "PROBLEM 2"/"RECONCILIATION POLICY" section), forward a
        reconstructed, client-local copy of the event to
        piece_animator_registry.on_event, and remove this piece's
        active client-side motion, if any (Stage B7.5 - see module
        docstring's "STAGE B7.5" section): this piece is no longer in
        flight, so it now renders statically at its own (just-updated)
        board cell again, exactly like every other non-moving piece.

        Args:
            event: The real, wire-parsed PieceArrived.

        Returns:
            None.

        A translation failure (see _translate_piece - the documented,
        narrow "joined mid-motion" gap) or self.board still being None
        is a safe, silent no-op: neither self.board nor
        piece_animator_registry nor self._active_motions is touched
        for this event at all - that specific piece's position will
        only ever be caught by a later _log_resync_mismatch
        diagnostic, never silently auto-corrected (see module
        docstring for why this is an accepted trade-off, not an
        oversight). A piece with no active motion entry at all (e.g.
        its own MoveAccepted was itself never successfully recorded)
        makes this removal a harmless no-op too (dict.pop's own
        default).

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

        self._active_motions.pop(piece.id, None)

        captured_piece = None if event.captured_piece_id is None else self._server_piece_cache.get(event.captured_piece_id)
        translated = PieceArrived(
            piece_id=piece.id,
            cell=event.cell,
            captured_piece_id=(captured_piece.id if captured_piece is not None else None),
        )
        if self.piece_animator_registry is not None:
            self.piece_animator_registry.on_event(translated)

        # See module docstring's "COOLDOWN DISPLAY OVER THE NETWORK"
        # section - set_current_clock_ms must be called before on_event
        # for the identical reason GameLoopRunner's own local wiring
        # calls it before publisher.wait(): CooldownTracker records
        # whatever clock value was most recently supplied, so it must
        # already reflect "now" by the time on_event actually fires.
        self.cooldown_tracker.set_current_clock_ms(self._clock_ms())
        self.cooldown_tracker.on_event(translated)

    def _handle_jump_landed(self, event: JumpLanded) -> None:
        """Translate a real JumpLanded's server piece_id, forward a
        reconstructed, client-local copy to piece_animator_registry.
        on_event (closes this stage's own Part E PieceAnimator gap -
        see that class's own module docstring for the parallel-to-
        PieceArrived reasoning) and to cooldown_tracker.on_event
        (starts a real cooldown bar for this landing, using
        JUMP_COOLDOWN_MS - the exact same mechanism local play's
        CooldownTracker already uses for PieceArrived, see module
        docstring's "COOLDOWN DISPLAY OVER THE NETWORK" section).

        Args:
            event: The real, wire-parsed JumpLanded.

        Returns:
            None.

        Unlike _handle_piece_arrived, this method never mutates
        self.board: a JUMP landing never moves the piece at all
        (extra/jump.py's own JumpTracker - a piece is airborne AT ITS
        OWN CELL the whole time, re-verified directly) - event.cell is
        always that same, unchanged cell, so there is nothing to
        move/remove-then-move on the board.

        A translation failure (see _translate_piece - the same narrow,
        accepted "joined mid-motion" gap PROBLEM 1 documents) is a
        safe, silent no-op, mirroring _handle_piece_arrived's identical
        policy - neither piece_animator_registry nor cooldown_tracker
        is touched for an untranslatable landing.
        """

        piece = self._translate_piece(event.piece_id, from_cell=None)
        if piece is None:
            return

        # A landed jump is no longer "in flight" for rendering purposes
        # either - mirrors _handle_piece_arrived's own identical
        # cleanup (a jump's own JumpAccepted DOES populate
        # _active_motions, from_cell == to_cell == its own cell, same
        # as _handle_move_or_jump_accepted already does uniformly for
        # both MoveAccepted and JumpAccepted).
        self._active_motions.pop(piece.id, None)

        translated = JumpLanded(piece_id=piece.id, cell=event.cell)
        if self.piece_animator_registry is not None:
            self.piece_animator_registry.on_event(translated)

        self.cooldown_tracker.set_current_clock_ms(self._clock_ms())
        self.cooldown_tracker.on_event(translated)

    def _handle_attacker_intercepted(self, event: AttackerIntercepted) -> None:
        """Translate a real AttackerIntercepted's server piece_id and
        remove the destroyed attacker from self.board and
        self._active_motions - see module docstring's "BUGFIX -
        AttackerIntercepted NEVER REMOVED THE ATTACKER FROM THIS
        CLIENT'S OWN BOARD" section for the full reasoning behind every
        decision below.

        Args:
            event: The real, wire-parsed AttackerIntercepted.

        Returns:
            None.

        Removes the attacker at its own CLIENT-TRACKED `piece.cell`,
        deliberately NOT `event.cell` (the interception's own location
        - the DEFENDER's airborne cell, per jump.py's own
        InterceptionEvent convention, re-verified directly - not
        necessarily where the attacker itself currently sits; see
        AttackerIntercepted's own docstring for the identical warning).
        Guarded by `self.board.piece_at(piece.cell) is piece` before
        removing, mirroring the same defensive precision
        _handle_piece_arrived's own board mutation already applies (via
        `is not None`) - never blindly assumes the cell still holds
        this exact piece.

        A translation failure (see _translate_piece - the same narrow,
        accepted "joined mid-motion" gap PROBLEM 1 documents) or
        self.board still being None is a safe, silent no-op, mirroring
        _handle_piece_arrived's/_handle_jump_landed's identical policy.
        """

        piece = self._translate_piece(event.piece_id, from_cell=None)
        if piece is None or self.board is None:
            return

        if self.board.piece_at(piece.cell) is piece:
            self.board.remove_piece(piece.cell)

        self._active_motions.pop(piece.id, None)

        # Best-effort only - see module docstring's own paragraph on
        # this for why an untranslatable defender_piece_id falls back
        # to the raw, untranslated server id rather than blocking this
        # event's own translation (nothing today reads this field at
        # all - PieceAnimator ignores this whole event, per
        # piece_animator.py's own "PART B DECISION" section).
        defender_piece = self._server_piece_cache.get(event.defender_piece_id)
        translated_defender_piece_id = defender_piece.id if defender_piece is not None else event.defender_piece_id

        translated = AttackerIntercepted(
            piece_id=piece.id, cell=event.cell, defender_piece_id=translated_defender_piece_id
        )
        if self.piece_animator_registry is not None:
            self.piece_animator_registry.on_event(translated)

    def _handle_game_over(self, event: GameOver) -> None:
        """Freeze this client's own input and record the real winner -
        see module docstring's "GAME OVER OVER THE NETWORK" section for
        the full reasoning behind the chosen freeze-and-display UX.

        Args:
            event: The real, wire-parsed GameOver.

        Returns:
            None.

        No piece_id to translate here (GameOver carries none - see its
        own docstring: winner_color is its only field) and no
        self.board/self.piece_animator_registry guard needed either,
        unlike every other handler above: this event carries no board
        position at all, so there is nothing that could still be
        unparsed/untranslatable by the time it arrives. Setting
        self.click_controller.game_over = True here (rather than
        leaving NetworkClickController to somehow discover this on its
        own) is what actually stops further clicks/jumps from leaving
        this client - see that class's own "GAME-OVER INPUT FREEZE"
        docstring section for why the guard lives there instead of
        being checked in this class's own click-dispatch wiring.
        """

        self._game_over = True
        self._game_over_winner_color = event.winner_color
        self.click_controller.game_over = True

    def poll_and_process(self) -> None:
        """Drain every new broadcast since the last call and apply each
        one, in arrival order - the per-frame network-polling step (see
        module docstring: NetworkGameClient.poll_incoming is non-
        blocking by design, exactly so a per-frame caller like this one
        never stalls waiting on network activity).

        Returns:
            None.

        Dispatches each raw message by its own distinct prefix (Stage
        B7 / server-score-moveslog-timer-broadcast - see
        kungfu_chess/notation/game_event_wire_format.py's and
        kungfu_chess/notation/game_state_snapshot_wire_format.py's own
        docstrings for why neither wire-format message can ever be
        confused with each other or with a board-text broadcast): a
        wire event goes to _apply_wire_event, a state snapshot goes to
        _apply_state_snapshot (this stage's own addition - see module
        docstring's "SCORE / MOVE-LOG / CAPTURED-PIECES / TIMER OVER
        THE NETWORK" section), everything else to the pre-existing
        _apply_broadcast.
        """

        for text in self.network_client.poll_incoming():
            if text.startswith(EVENT_MESSAGE_PREFIX):
                self._apply_wire_event(text)
            elif text.startswith(STATE_SNAPSHOT_MESSAGE_PREFIX):
                self._apply_state_snapshot(text)
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
        own run() (time.perf_counter() before/after each iteration,
        here via self._clock() - see __init__'s own docstring for why
        this is injectable) - Stage B7 needs this real value to drive
        piece_animator_registry.advance_all in _run_one_frame; before
        Stage B7 no per-frame timing was needed at all in network mode.
        """

        last_time = self._clock()
        while not self._should_exit():
            now = self._clock()
            delta_ms = int((now - last_time) * 1000)
            last_time = now
            self._run_one_frame(delta_ms)

        self.close()

    def _compute_motions_for_rendering(self) -> Dict[int, InFlightMotion]:
        """Compute a real, clamped progress fraction for every active
        client-side motion, from this client's own real elapsed time
        since it received that motion's own MoveAccepted/JumpAccepted
        (Stage B7.5 - see module docstring's "STAGE B7.5" section for
        the full reasoning, including why no server clock sync is
        needed).

        Returns:
            {piece_id: InFlightMotion(from_cell, to_cell, progress)}
            for every entry currently in self._active_motions - ready
            to pass directly as build_snapshot_from_board's own
            `active_motions` argument. Empty (not None) when no motion
            is active - build_snapshot_from_board already treats an
            empty dict identically to None (every piece renders
            statically), so this method never needs to special-case
            "nothing in flight" itself.

        Extracted as its own method (not inlined into _run_one_frame)
        specifically so it can be unit-tested directly, with an
        injected fake self._clock, without needing to drive the whole
        render pipeline (cv2/Img/ImgSurface) at all.
        """

        now = self._clock()
        motions: Dict[int, InFlightMotion] = {}
        for piece_id, motion in self._active_motions.items():
            elapsed_ms = int((now - motion.started_at) * 1000)
            progress = motion_progress(elapsed_ms, motion.duration_ms)
            motions[piece_id] = InFlightMotion(from_cell=motion.from_cell, to_cell=motion.to_cell, progress=progress)
        return motions

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
            snapshot = build_snapshot_from_board(
                self.board,
                selected=self.click_controller.selected,
                active_motions=self._compute_motions_for_rendering(),
            )
            Renderer(surface).render(snapshot)
            # See module docstring's "COOLDOWN DISPLAY OVER THE
            # NETWORK" section - mirrors GameLoopRunner's own exact
            # render order (board+pieces, THEN cooldown bars, onto the
            # same board sub-canvas, before it is pasted).
            CooldownOverlayRenderer(board_canvas).render(self.board, self.cooldown_tracker, self._clock_ms())
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

        # Real, server-authoritative score/log (see module docstring's
        # "SCORE / MOVE-LOG / CAPTURED-PIECES / TIMER OVER THE NETWORK"
        # section) - SidePanelRenderer itself is completely unchanged;
        # only the data fed to it changed, from the permanently-empty
        # placeholders to whatever the latest real "STATE:" broadcast
        # last set. CapturedPiecesRenderer draws immediately after each
        # color's own panel, in the exact same (x, width, color) region,
        # deriving its own display purely from the SAME self._latest_log.
        right_panel_x = self._total_canvas_width - PANEL_WIDTH
        SidePanelRenderer(main_canvas).render(
            x=0, width=PANEL_WIDTH, color=Color.WHITE, score=self._latest_score, log=self._latest_log
        )
        CapturedPiecesRenderer(main_canvas, self.asset_cache).render(
            x=0, width=PANEL_WIDTH, color=Color.WHITE, log=self._latest_log
        )
        SidePanelRenderer(main_canvas).render(
            x=right_panel_x, width=PANEL_WIDTH, color=Color.BLACK, score=self._latest_score, log=self._latest_log
        )
        CapturedPiecesRenderer(main_canvas, self.asset_cache).render(
            x=right_panel_x, width=PANEL_WIDTH, color=Color.BLACK, log=self._latest_log
        )

        # See module docstring's "USERNAME REACHES THE GUI" section -
        # one call per color, same (x, color) pair each panel already
        # used above; is_local_player is the one fact only this class
        # already holds (which color THIS connection was assigned).
        PlayerLabelRenderer(main_canvas).render(
            x=0, color=Color.WHITE, username=self.username, is_local_player=self.assigned_color is Color.WHITE
        )
        PlayerLabelRenderer(main_canvas).render(
            x=right_panel_x, color=Color.BLACK, username=self.username, is_local_player=self.assigned_color is Color.BLACK
        )

        # Real, server-authoritative elapsed game time (interpolated
        # between broadcasts - see module docstring's "ELAPSED-TIME
        # DISPLAY" section), centered above the board region.
        timer_x = self._board_origin_x + self._board_pixel_width // 2 - 40
        GameTimerRenderer(main_canvas).render(self._displayed_clock_ms(), x=timer_x)

        # See module docstring's "GAME OVER OVER THE NETWORK" section -
        # drawn onto main_canvas (not board_canvas), so the message is
        # never obscured by anything pasted on top of it afterward, and
        # spans the same full-window canvas ImgSurface.
        # draw_game_over_message centers itself on for local play.
        if self._game_over:
            GameOverOverlayRenderer(main_canvas).render(winner_color=self._game_over_winner_color)

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
        currently holds - narrower than GameLoopRunner's own three, and
        DELIBERATELY still not a third GameOver-driven one even though
        this class can now genuinely detect GameOver (see module
        docstring's "GAME OVER OVER THE NETWORK" section: freeze-and-
        display was chosen over auto-exit, so a game-over window stays
        open and keeps rendering - the human closes it manually via
        either of the two conditions actually checked below)."""

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
