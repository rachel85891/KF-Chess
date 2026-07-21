"""GameSession: hosts a real, headless GameEngine on the server -
Stage B2 of the server track.

WHY this exists, and why it stays isolated from networking (mirrors
Stage B1's own reasoning, applied to the opposite half): Stage B1
proved the network layer works, with zero chess logic anywhere in
server/main.py or connection_manager.py. This stage proves the
opposite half in isolation - that the server PROCESS can correctly
host and drive a real GameEngine, headless, with none of the
client-only concerns (rendering, animation, sound, mouse input) that
kungfu_chess/client/loop/game_loop.py's GameLoopRunner also carries
locally. Keeping this stage isolated from the WebSocket protocol -
rather than wiring both networking and engine-hosting at once - means
that once a future stage (B3) connects real WQe2e5-style commands to
this class, a bug can be isolated to either the protocol wiring or the
engine hosting, never both tangled together at the same time.

EXACT WIRING REUSED FROM GameLoopRunner (re-read
kungfu_chess/client/loop/game_loop.py's __init__ directly before
writing this, per this stage's own requirement not to invent a
different composition): GameEngine(board) -> ExtraEngine(engine) ->
EventBus() -> GameEventPublisher(extra_engine, event_bus=event_bus), in
that exact order. GameLoopRunner additionally builds PieceRegistry,
PieceAnimatorRegistry, ScoreObserver, MovesLogObserver,
CooldownTracker, SoundManager, AssetCache, Controller, MouseAdapter,
and the whole cv2/Img rendering/canvas-layout machinery - none of that
belongs on a server (no display, no mouse, no speakers), so none of it
is constructed here EXCEPT PieceRegistry/ScoreObserver/
MovesLogObserver (see "SCORE / MOVE-LOG / TIMER" section below, a
later stage's addition): unlike PieceAnimatorRegistry/CooldownTracker/
SoundManager/the rendering machinery, these three are pure DATA
observers with no display/mouse/speaker dependency at all - reusing
them here is exactly as legitimate as GameLoopRunner's own reuse of
them, just for a different consumer (a future network broadcast
instead of a local HudRenderer/SidePanelRenderer). GameSession is
therefore a strict SUBSET of GameLoopRunner's own composition, not a
reimplementation of it - the same real GameEngine/ExtraEngine/
GameEventPublisher/EventBus/PieceRegistry/ScoreObserver/
MovesLogObserver classes, composed and subscribed the same way
GameLoopRunner already does, just without the client-only half.

SCORE / MOVE-LOG / TIMER (later stage - server-score-moveslog-timer-
broadcast): WHY CONSTRUCTED HERE, IN GameSession, NOT IN GameServer
(re-read both files' current constructors directly before deciding):
GameServer accepts an already-built GameSession (or builds a default
one with `GameSession()`, no board of its own) - it never sees the
initial `board` directly, only whatever GameSession already wrapped it
into. PieceRegistry.from_board(board) needs that ORIGINAL board at the
exact moment it's still a plain Board, before anything has moved -
GameSession.__init__ is the one and only place that already holds it at
that moment (the same reason GameLoopRunner itself builds
PieceRegistry.from_board(board) inside its own __init__, immediately
after receiving `board`, rather than deferring it to some later
composition step). Building it in GameServer instead would mean either
threading the original board through GameServer's own constructor
(duplicating GameSession's own "build or accept a board" responsibility
in a second place) or reaching into GameSession's own internals to
re-derive a board snapshot after the fact (fragile, and arguably WRONG
once even one move has already happened by the time GameServer got
around to it). GameSession is therefore the correct, and only genuinely
available, composition point for this - exactly the same reasoning
that already puts the engine/extra_engine/event_bus/publisher stack
here rather than in GameServer.

Subscribed via `self.publisher.subscribe(...)` - the SAME Observer-
protocol mechanism (kungfu_chess/client/events/event_publisher.py's
`_observers` list, Stage 3) GameLoopRunner already uses for these exact
two classes, NOT the EventBus's own per-type `subscribe(event_type,
callback)` mechanism GameServer's broadcaster uses for ITS OWN,
different purpose (bridging a sync callback into an async send - see
game_server.py's own docstring). Both classes already implement
Observer's single `on_event(event)` method; reusing that existing,
already-tested subscription path is the more DRY, zero-new-mechanism
choice, rather than reinventing a second, EventBus-shaped way to
deliver the same events to the same two classes.

wait()'s own new one-line addition - `self.moves_log_observer.
set_current_clock_ms(self.engine.state.clock_ms + ms)`, called BEFORE
`self.publisher.wait(ms)` - mirrors GameLoopRunner._run_one_frame's own
exact "told BEFORE wait() runs" ordering and clock-prediction formula
(`upcoming_clock_ms = self.engine.state.clock_ms + delta_ms`, re-read
directly) for the identical reason documented in
MovesLogObserver.set_current_clock_ms's own docstring: by the time
on_event fires (inside publisher.wait(), after the clock has already
advanced), the real clock has already moved - so the value must be
predicted and supplied beforehand. DELIBERATELY LIVES INSIDE
GameSession.wait() ITSELF, not duplicated in GameServer.run_tick_loop
(the literal call site GameLoopRunner's own equivalent lives in): this
class's own `wait()` is the SINGLE choke point every caller advancing
this session's clock already goes through (GameServer's tick loop, and
this module's own tests calling `session.wait(...)` directly) - baking
the invariant "moves_log_observer always reflects the correct clock
before an advance" directly into this one method guarantees it holds
for every caller automatically, rather than requiring every present
and future caller of `wait()` to separately remember to call
`set_current_clock_ms` first (which GameServer would otherwise need to
know MovesLogObserver even exists to do). This is a one-line,
purely-additive change - it does not alter wait()'s own return value or
any existing move/board-mutation behavior, so no pre-existing test
needed to change.

`self.event_bus` is public for the exact same reason
GameLoopRunner.event_bus is (see that class's own "EVENTBUS WIRING"
docstring section): a future stage (B3) needs to subscribe a WS
broadcaster to real game events from OUTSIDE this class. Nothing is
subscribed to it here, for the same reason nothing was subscribed to
GameLoopRunner's bus in Stage A3 - this stage only proves the engine
hosting and the bus wiring are both correct and already connected to
each other (see this module's own tests), leaving the choice of what
actually consumes it to whichever future stage introduces the real
broadcaster.

NO CLICK/PIXEL-COORDINATE HANDLING: GameLoopRunner's Controller and
BoardMapper exist to turn raw mouse pixel coordinates into board
Positions - a server has no mouse. A future protocol stage (parsing
WQe2e5-style text commands) will translate a parsed command directly
into two board Positions itself and call request_move with them
directly - there is no pixel step to adapt on the server side at all,
so Controller/BoardMapper are correctly absent here, not a gap left to
fill later.

HEADLESS BY CONSTRUCTION, NOT BY AN OPT-IN FLAG: GameLoopRunner takes a
`headless: bool` parameter because that class ALSO supports real
windowed play - `headless=True` is one of two real modes it can run in.
GameSession never renders anything, under any configuration - it has
no cv2/Img/MouseAdapter/AudioPlayer import at all (re-verified directly
against kungfu_chess/client/loop/game_loop.py's own imports before
writing this, to see exactly what NOT to reproduce here), so there is
no flag to add: this class simply cannot open a window, by
construction, not by a runtime switch that could be flipped the wrong
way.

STARTING POSITION: STANDARD_STARTING_POSITION_LINES (below) is a real,
standard 32-piece chess starting layout, in the exact textual notation
BoardParser (kungfu_chess/io/board_parser.py) already expects - one row
per line, tokens space-separated, "." for empty, "<color><KIND>" letter
pairs otherwise (re-verified directly against
tests/unit/test_board_parser.py and tests/integration/scripts/*.kfc
before writing this, rather than inventing a new format). Row/color
orientation matches the existing pawn-direction convention already
established by tests/integration/scripts/13_white_pawn_double_from_
start_valid.kfc and 14_black_pawn_double_from_start_valid.kfc (and
kungfu_chess/rules/piece_rules.py's own _pawn_start_row: white's pawn
start row is board.height - 2, black's is 1): White starts on the
HIGH-numbered rows and moves toward row 0; Black starts at row 0 and
moves toward higher rows - so White's back rank is row 7 here, Black's
is row 0, matching that same existing direction, not an arbitrarily
chosen orientation.

Constructing the default board via BoardParser (rather than building
Piece/Board objects directly in Python) is deliberate, not incidental:
it exercises the exact same real text->Board path every other entry
point in this project already uses (app.py/app_extra.py/
texttests/script_runner.py), so a typo in
STANDARD_STARTING_POSITION_LINES would fail the same validation
(ERR_ROW_WIDTH_MISMATCH/ERR_UNKNOWN_TOKEN) any other malformed board
text would, rather than silently producing a wrong board.

NO SINGLETON: GameSession is a plain, independently-instantiable class
- no module-level instance, no class-level shared state anywhere in
this file (mirrors kungfu_chess.bus.EventBus's and
server.connection_manager.ConnectionManager's own "no global state,
each instance independent" convention from earlier stages, for the
same forward-looking reason: a future multi-game/multi-room stage can
construct more than one GameSession without this class changing at
all). This stage's own tests and any wiring that uses this class today
only ever construct exactly one instance in practice - that is a usage
choice made OUTSIDE this class (by its callers/tests), not a
constraint this class enforces or assumes internally; nothing here
would break if two were constructed side by side (see
test_two_independent_game_sessions_do_not_share_state).
"""

from __future__ import annotations

from typing import List, Optional

from kungfu_chess.bus.event_bus import EventBus
from kungfu_chess.client.events.event_publisher import GameEventPublisher
from kungfu_chess.client.events.observers import MovesLogObserver, ScoreObserver
from kungfu_chess.client.events.piece_registry import PieceRegistry
from kungfu_chess.engine.game_engine import GameEngine, MoveResult
from kungfu_chess.extra.extra_engine import ExtraEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.model.board import Board
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.motion import ArrivalEvent

STANDARD_STARTING_POSITION_LINES = [
    "bR bN bB bQ bK bB bN bR",
    "bP bP bP bP bP bP bP bP",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    ". . . . . . . .",
    "wP wP wP wP wP wP wP wP",
    "wR wN wB wQ wK wB wN wR",
]


def _build_standard_starting_board() -> Board:
    """Parse STANDARD_STARTING_POSITION_LINES via the real BoardParser
    - see module docstring's "STARTING POSITION" section for why this
    goes through BoardParser rather than constructing Piece/Board
    objects directly in Python.

    Returns:
        A real, valid standard-starting-position Board.
    """

    board, error = BoardParser().parse(STANDARD_STARTING_POSITION_LINES)
    if error is not None:
        # Only reachable if STANDARD_STARTING_POSITION_LINES is ever
        # edited into something malformed - a bug in this file, not a
        # normal runtime condition any caller can trigger.
        raise ValueError(f"STANDARD_STARTING_POSITION_LINES is malformed: {error}")
    return board


class GameSession:
    """Hosts one real, headless game - see module docstring for the
    full reasoning behind every decision below."""

    def __init__(self, board: Optional[Board] = None) -> None:
        """Wire a real GameEngine/ExtraEngine/EventBus/GameEventPublisher
        stack around `board` - exactly the composition GameLoopRunner
        uses for the same four classes (see module docstring's "EXACT
        WIRING REUSED" section).

        Args:
            board: The Board to start this session on. Defaults to
                None, which builds a real standard starting position
                via BoardParser (see module docstring's "STARTING
                POSITION" section) - the common case for a real game;
                injectable (DIP) for tests or a future stage that needs
                a different starting layout, without this class ever
                needing to change.

        Returns:
            None.
        """

        if board is None:
            board = _build_standard_starting_board()

        self.engine = GameEngine(board)
        self.extra_engine = ExtraEngine(self.engine)
        self.event_bus = EventBus()
        self.publisher = GameEventPublisher(self.extra_engine, event_bus=self.event_bus)

        # See module docstring's "SCORE / MOVE-LOG / TIMER" section for
        # why these three are built and subscribed here, not in
        # GameServer. piece_registry is snapshotted from THIS board,
        # before anything has moved - the same "one-time snapshot at
        # game start" contract PieceRegistry.from_board's own docstring
        # documents, and the same moment GameLoopRunner itself builds
        # its own equivalent registry.
        self.piece_registry = PieceRegistry.from_board(board)
        self.score_observer = ScoreObserver(self.piece_registry)
        self.moves_log_observer = MovesLogObserver(self.piece_registry)
        self.publisher.subscribe(self.score_observer)
        self.publisher.subscribe(self.moves_log_observer)

    def request_move(self, from_cell: Position, to_cell: Position) -> MoveResult:
        """Thin pass-through to GameEventPublisher.request_move - see
        module docstring's "NO CLICK/PIXEL-COORDINATE HANDLING" section
        for why a future protocol stage calls this directly with
        already-parsed Positions, with no Controller/BoardMapper step
        in between.

        Args:
            from_cell: The Position the moving piece currently
                occupies.
            to_cell: The Position it is being requested to move to.

        Returns:
            The real MoveResult from GameEventPublisher.request_move,
            unchanged.
        """

        return self.publisher.request_move(from_cell, to_cell)

    def request_jump(self, cell: Position) -> bool:
        """Thin pass-through to GameEventPublisher.request_jump -
        mirrors request_move's own reasoning exactly (see module
        docstring's "NO CLICK/PIXEL-COORDINATE HANDLING" section).

        Deliberately NOT `self.extra_engine.request_jump(cell)`
        directly, even though that attribute already exists and
        already has a `request_jump` method of its own (re-verified
        directly in kungfu_chess/extra/extra_engine.py before writing
        this): only the PUBLISHER's own request_jump also publishes a
        real JumpAccepted (kungfu_chess/client/events/event_publisher.py,
        re-verified directly) - calling ExtraEngine directly would
        silently skip that publish step entirely, breaking the whole
        event-driven broadcast chain server/game_server.py's own
        _on_game_event subscriber depends on to ever learn a jump was
        accepted at all.

        Args:
            cell: The Position the jumping piece currently occupies -
                a single cell, not a from/to pair (ExtraEngine.
                request_jump's own contract).

        Returns:
            The real bool from GameEventPublisher.request_jump,
            unchanged.
        """

        return self.publisher.request_jump(cell)

    def wait(self, ms: int) -> List[ArrivalEvent]:
        """Advance this session's clock by ms - see module docstring's
        "SCORE / MOVE-LOG / TIMER" section for why this now also stamps
        moves_log_observer's own current clock BEFORE delegating to
        GameEventPublisher.wait, mirroring GameLoopRunner's own
        identical "told before wait()" ordering.

        Args:
            ms: Milliseconds of logical time to advance.

        Returns:
            The real list of ArrivalEvents from
            GameEventPublisher.wait, unchanged.
        """

        self.moves_log_observer.set_current_clock_ms(self.engine.state.clock_ms + ms)
        return self.publisher.wait(ms)
