"""GameServer: the real protocol coordinator - Stage B3 of the server
track. This is the ONE component allowed to know about BOTH networking
(ConnectionManager, real ServerConnection objects) AND game hosting
(GameSession), exactly mirroring how
kungfu_chess/client/loop/game_loop.py's GameLoopRunner is the one
client-side class allowed to know about every client-layer piece at
once. Every other server/ module stays strictly single-purpose:
ConnectionManager (Stage B1) still only tracks connections and knows
nothing about chess; GameSession (Stage B2) still only hosts a headless
engine and knows nothing about networking; algebraic_notation.py and
move_command.py (this stage) are pure, network-agnostic parsers. This
class is where those four things actually meet, and it is the only
place they do.

THE APPLICATION/PRESENTATION BOUNDARY (refactor/server-application-
presentation-split): this file used to ALSO own every detail of how
the wire protocol is actually spoken - parsing raw text, formatting
every outgoing message, the literal connection.send calls - alongside
its own coordination decisions, in one 664-line file. That PRESENTATION
half is now server/protocol_handler.py's ProtocolHandler (see its own
module docstring for the full reasoning) - a stateless, ConnectionManager/
GameSession/EventBus-agnostic class this one holds via composition
(`self._protocol`, injected DIP, defaulting to a real ProtocolHandler).
This class (APPLICATION) keeps every decision about what a client
message MEANS for the game and who is allowed to send it: color/join-
order assignment, third-plus-connection policy, validating a parsed
command's color/ownership against the real board, deciding WHICH
GameSession method a valid command maps to, deciding WHICH broadcast
messages a given game event triggers and in what order, and the tick
loop. Neither class reaches into the other's internals - GameServer
never imports a wire-format module or BoardPrinter directly anymore
(re-verified: this file has no such import left), and ProtocolHandler
never imports GameSession/ConnectionManager/EventBus.

BORDERLINE JUDGMENT CALLS, decided and justified here (per this
refactor's own explicit invitation to document them):
  - Parsing raw text into a structured command (including the leading-
    character jump-vs-move dispatch that used to live directly inside
    `_handle_message`) is PRESENTATION, not APPLICATION - it is pure
    wire-grammar knowledge with no coordination decision in it (WHICH
    parser applies to a given message is a fact about the GRAMMAR, not
    about the game) - moved to ProtocolHandler.parse_incoming_command.
    But VALIDATING an already-parsed command (does its color match this
    connection's assigned color? does its claimed piece actually match
    what's on the board?) stays APPLICATION, in `_handle_move_command`/
    `_handle_jump_command`/`_piece_matches` - these decisions need
    GameSession/`self._colors` knowledge ProtocolHandler deliberately
    does not have.
  - Constructing the literal "rejected:<reason>"/"assigned_color:
    <color>" wire STRINGS is PRESENTATION (ProtocolHandler.
    format_rejection/format_assigned_color) - it's protocol syntax, the
    same category as format_game_event. But DECIDING which reason
    string applies (wrong_color vs. piece_mismatch vs. a parse failure
    vs. jump_rejected) stays APPLICATION - that decision requires
    knowing the connection's assigned color and the real board, neither
    of which ProtocolHandler has.
  - `_broadcast_event`'s own SEQUENCING logic (send the wire event if
    any, then board text, then conditionally the state snapshot, based
    on the event's own type) stays APPLICATION, in GameServer, even
    though it calls PRESENTATION methods to actually format/send each
    piece: which event types warrant a state-snapshot broadcast is a
    decision about GAME-EVENT SEMANTICS (only moves/jumps/arrivals ever
    change score/log state - see this module's own "SCORE / MOVE-LOG /
    TIMER BROADCAST" section), not wire-protocol mechanics - moving it
    into ProtocolHandler would give that class an opinion about what a
    MoveAccepted MEANS, which is exactly the knowledge this split is
    meant to keep out of it.
  - ConnectionManager itself stays owned by GameServer (APPLICATION),
    not ProtocolHandler: `self._connection_manager` is coordination
    state (who is currently connected), not wire-protocol mechanics.
    ProtocolHandler.broadcast takes a plain connections ITERABLE
    instead (GameServer passes `self._connection_manager.connections()`
    in) - this class's own decision, not something ProtocolHandler asks
    for by holding a ConnectionManager reference of its own.

WHY THIS IS THE "JOIN" STAGE: Stage B1 proved networking in isolation
(echo only). Stage B2 proved engine hosting in isolation (direct method
calls only). This class is what Stage B1's own echo_message docstring
already called "the swap point" for - `handle_connection` below
replaces server/main.py's old Stage-B1 echo handler entirely, but
ConnectionManager and GameSession themselves needed NO changes to make
this possible, exactly as both of their own Stage B1/B2 docstrings
predicted.

SINGLE SHARED GAME, NO ROOMS YET (per this stage's own scope): exactly
one GameSession and one ConnectionManager are constructed - by
default, fresh ones; both are still accepted as optional constructor
parameters (matching GameSession's own `board: Optional[Board] = None`
DIP pattern) purely for test injection, not because multiple real
games are supported yet. Basic spectator/viewer support and multiple
concurrent games/rooms are explicitly out of scope until a documented
future stage (F, Rooms) - see "SHAPE FOR A FUTURE ROOMS STAGE" below
for exactly how this class is expected to grow into that, without
building any of it now (YAGNI).

CONNECTION -> COLOR ASSIGNMENT (per slide 4, "first that joins is
White, second is Black"): tracked in `self._colors: Dict[ServerConnection,
Color]`, a small piece of state that belongs HERE, not on
ConnectionManager (which must stay protocol/game-agnostic per its own
Stage B1 docstring) and not on GameSession (which must stay
network-agnostic per its own Stage B2 docstring) - this is exactly the
kind of "knows about both" state only this coordinator is allowed to
hold.

WHY join-order assignment needs no lock, despite being a check-then-act
sequence: `handle_connection` reads `self._connection_manager.
connection_count` and later calls `.add(connection)` with no `await` in
between - under asyncio's single-threaded cooperative scheduling, a
coroutine only yields control at an `await` point, so nothing else can
run between that read and that write. Two connections arriving
"simultaneously" are still handled one after another by the event
loop, never truly concurrently, so this check-then-act is naturally
atomic without any explicit lock.

THIRD-PLUS CONNECTION POLICY (explicit product decision for this
stage, per the task): rejected immediately - sent the literal text
"server_full", then the connection is closed server-side, WITHOUT ever
calling `self._connection_manager.add(...)` for it. It is therefore
never tracked as a connection at all, not even transiently - no
partial/viewer capacity is granted, matching the explicit "do not build
any partial viewer mechanism here" instruction.

MOVE COMMAND REJECTION SCHEME (a plain-text response sent directly and
ONLY to the offending client - never broadcast, since these rejections
never reach GameSession/the event bus at all): a single "rejected:
<reason>" prefix, with `<reason>` one of:
  - "malformed:<detail>" - parse_move_command raised MalformedCommandError
    (see move_command.py's own docstring for every case this covers).
  - "wrong_color" - the command's own claimed color does not match the
    color this connection was assigned at join time.
  - "piece_mismatch" - the command's claimed piece kind/color doesn't
    match what is actually on the source square right now (see
    _handle_message's own docstring for why this check lives here, not
    in move_command.py).
A move that gets THIS FAR and is still rejected by the real engine
(illegal shape, blocked path, motion_in_progress, etc.) is NOT covered
by this scheme at all - GameEventPublisher already publishes a real
MoveRejected event for that case, which this class's own broadcaster
(below) turns into a normal board-state broadcast to BOTH clients, the
same as any other real game event - there is nothing this class needs
to additionally send for that case.

JUMP COMMAND ROUTING AND REJECTION SCHEME (later stage - jump-network-
wiring-and-cooldown-display): incoming messages are dispatched by
`_handle_message` based on a single, unambiguous leading-character
check - `message[:1].upper() == JUMP_COMMAND_PREFIX` ("J") means a jump
command (kungfu_chess/notation/jump_command.py's own "J<W|B><K|Q|R|
B|N|P><file><rank>" grammar), anything else is handled exactly as
before, as a move command. This can never misroute a genuine move
command: server/move_command.py's own grammar always starts with a
bare color letter ('W' or 'B'), never 'J' (re-verified directly against
that module). Jump rejection reuses the EXACT SAME three "rejected:
<reason>" tokens as moves - "malformed:<detail>" (now from
MalformedJumpCommandError instead), "wrong_color", "piece_mismatch" -
via a shared `_piece_matches` helper (refactored out of the old
move-only `_piece_matches_board`, so the same one real-board check
serves both commands rather than being duplicated) - PLUS one new
token, "jump_rejected", for the one case moves never needed a
direct-response token for: ExtraEngine.request_jump (re-verified
directly, kungfu_chess/extra/extra_engine.py) returns a bare bool with
NO reason string at all when it declines (already airborne, mid-motion,
still on cooldown) - unlike a move's own engine-level rejection, there
is no MoveRejected-style event GameEventPublisher publishes for a
declined jump to broadcast instead (see event_publisher.py's own
request_jump docstring: "there is nothing honest to put in a
MoveRejected.reason here without inventing text ExtraEngine itself
never produced"). Since no event exists for this class's own
broadcaster to react to, this is the one jump-rejection case that
genuinely needs its own direct, point-to-point response, exactly like
the three malformed/wrong_color/piece_mismatch cases above it, rather
than being left to the (nonexistent) event-driven path.

WHY THE BROADCASTER BRIDGES A SYNC CALLBACK INTO AN ASYNC SEND:
kungfu_chess.bus.EventBus.subscribe (Stage A1) requires a plain
synchronous callable - `Callable[[object], None]` - and GameSession.
request_move/wait call the whole GameEventPublisher._notify chain
synchronously, inline, with no `await` anywhere in that path. But
actually delivering a broadcast requires a real, awaited
`connection.send(...)`. The bridge: `_on_game_event` (the subscribed
handler) is itself a plain sync function - it satisfies EventBus's
contract - but its body does no real I/O itself; it only schedules
`asyncio.create_task(self._broadcast_event(event))`, which does the
real, awaited sends via self._protocol. This is safe specifically
because `_on_game_event` is ALWAYS invoked
from inside a call to `self._game_session.request_move(...)` or
`.wait(...)`, both of which are themselves always called from this
class's own async methods (`_handle_message`, `run_tick_loop`) - so a
real asyncio event loop is always already running whenever
`_on_game_event` fires, making `asyncio.create_task` always valid to
call from there.

TICK LOOP / TICK RATE: `run_tick_loop` mirrors
GameLoopRunner.run()'s own real-time delta measurement pattern
exactly (re-read that method directly before writing this) -
`time.perf_counter()` before/after each real sleep, `int((now -
last_time) * 1000)` as the elapsed ms, fed straight into
GameSession.wait(delta_ms). TICK_INTERVAL_S = 1/30 matches
client_spec.md §8's own ~30 FPS default - not because anything is
rendered here (nothing is), but so the server's own real-time
resolution is at least as fine-grained as what a real client already
assumes when it renders/interpolates motion locally: a much coarser
server tick would make simultaneous/real-time interactions (this
whole project's "Kung Fu" premise, spec.md §2) resolve in visibly
coarser, more delayed jumps than any client observing this server was
ever designed to expect. This loop runs independently of any client
message arriving (client_spec.md's/this stage's own requirement) -
`run_tick_loop` is started once as its own background asyncio task
(see server/main.py) and keeps calling `wait()` on a fixed real-time
cadence for as long as the process lives, entirely decoupled from
`_handle_message`.

STAGE B7 - REAL WIRE-FORMAT EVENTS, ALONGSIDE (NOT INSTEAD OF) BOARD
TEXT: `_on_game_event`'s broadcaster now also sends a structured,
single-line wire-format message (kungfu_chess/notation/
game_event_wire_format.py) for MoveAccepted/JumpAccepted/PieceArrived
(and, since the jump-network-wiring-and-cooldown-display stage,
JumpLanded too - see that module's own "JumpLanded ADDITION" docstring
section - and, since fix/interception-event-and-network-removal,
AttackerIntercepted - see that same module's "AttackerIntercepted
ADDITION" section), immediately before the existing board-text
snapshot for the same event - see `_broadcast_event`'s own docstring
for the exact ordering guarantee. Neither JumpLanded nor
AttackerIntercepted needed any changes to `_on_game_event`/
`_broadcast_event` themselves to start broadcasting correctly - only
_BROADCAST_EVENT_TYPES (below) gained one more subscribed type each
time, and format_game_event already returns real wire text for both -
exactly the same OCP-safe extension point PromotionEvent could have
used had it needed broadcasting too. AttackerIntercepted is
deliberately NOT one of the event types that also triggers the score/
move-log/clock snapshot broadcast below (see that section) - an
interception never changes score or the move log (ScoreObserver/
MovesLogObserver, re-verified directly, react only to PieceArrived-
with-capture and MoveAccepted/JumpAccepted; AttackerIntercepted is a
type neither of them has any reaction to at all). WHY ALONGSIDE, NOT REPLACING: the board-text broadcast is
this project's own established fallback/sanity-check safety net (every
existing client and test already depends on receiving it) - this stage
adds richer, structured per-motion data for a client that wants to
animate smoothly (kungfu_chess/client/loop/network_game_loop_runner.py),
without removing the guarantee a simpler/older client can still just
parse the board text alone and ignore the new message entirely. WHY
MoveRejected GETS NO WIRE-FORMAT MESSAGE: format_game_event returns
None for it (not an animatable motion - see that module's own
docstring) - `_broadcast_event` treats that None as "nothing extra to
send", so its broadcast stays byte-for-byte identical to before this
stage.

GameOver ADDITION (fix/network-gameover-and-king-interception): GameOver
was ALREADY in `_BROADCAST_EVENT_TYPES` below (added when GameOver
itself was first introduced) and `_on_game_event`/`_broadcast_event`
were therefore already firing for it - but format_game_event used to
return None for GameOver too (same reasoning as MoveRejected above),
so nothing beyond the existing board-text broadcast was ever actually
sent, and no connected client had any way to detect the game had
ended. Once format_game_event started returning a real "EVT:GAMEOVER:"
message for it (kungfu_chess/notation/game_event_wire_format.py's own
docstring), this class needed ZERO code changes to start sending it -
the exact same `wire_text = self._protocol.format_event(event); if
wire_text is not None: await self._protocol.broadcast(...)` line below
(originally `format_game_event`/`self._broadcast` directly, before
refactor/server-application-presentation-split relocated the actual
formatting/sending mechanics to ProtocolHandler - see this module's own
"THE APPLICATION/PRESENTATION BOUNDARY" section) now simply stops
producing None for this one event type. This is the intended, minimal
shape of that module's own None-return contract: a caller here never
needs to special-case which event types currently have wire support -
it only ever needs to ask format_event, once.

SCORE / MOVE-LOG / TIMER BROADCAST (later stage - server-score-
moveslog-timer-broadcast): `_broadcast_event` now sends ONE MORE
message - the real, structured score/move-log/elapsed-clock snapshot
(kungfu_chess/notation/game_state_snapshot_wire_format.py) - right
after the existing wire-event + board-text pair, but ONLY for
MoveAccepted/JumpAccepted/PieceArrived (re-checked directly: these are
the only three event types that can ever change
self._session.score_observer/moves_log_observer's own running state -
JumpLanded/MoveRejected/GameOver never do, and are therefore correctly
left byte-for-byte unchanged by this addition, matching this stage's
own explicit "do not touch MoveRejected/GameOver handling" scope).
score_observer/moves_log_observer themselves are NOT constructed or
subscribed here - they live on `self._session` (see
server/game_session.py's own "SCORE / MOVE-LOG / TIMER" docstring
section for why GameSession, not this class, is the correct
composition point) - this class only ever READS their already-current
snapshots (`self._session.score_observer.snapshot()`,
`self._session.moves_log_observer.snapshot()`) plus the current
`self._session.engine.state.clock_ms`, exactly mirroring how
`_current_board_text` already reads `self._session.engine.board`
directly rather than owning any board state itself. Reuses the exact
same `self._protocol.broadcast` call every other message in this class
already uses - no second broadcast path.

SHAPE FOR A FUTURE ROOMS STAGE (F) - noted explicitly, NOT built now
(YAGNI): today, `self._game_session`/`self._colors`/the four event-bus
subscriptions are each a SINGLE instance/mapping, because there is
exactly one shared game. A future Rooms stage would change this class
from "one session" to "a dict of room_id -> (GameSession, its own
per-room `_colors` mapping, its own four subscriptions)", with
`handle_connection` parsing/accepting a room identifier to select
which entry to use (or create one) before doing anything
color-assignment-related. That refactor is additive to THIS class's
own shape (all per-room state is already grouped together inside one
coordinator instance, rather than scattered across module-level
globals or split across ConnectionManager/GameSession) - it is not a
rewrite of ConnectionManager or GameSession, both of which already stay
completely agnostic to "how many games exist" today. This stage
deliberately does not build any dict-of-rooms/room-id parsing now -
there is exactly one real caller (this stage's own tests and
server/main.py) and no real second room to design against yet.

BUGFIX - INITIAL BOARD STATE ON JOIN: a real usability gap found during
manual testing, fixed here. WHY THE GAP EXISTED: `_on_game_event` (the
broadcaster) is only ever invoked by the event_bus in reaction to a
real game EVENT (MoveAccepted/MoveRejected/PieceArrived/GameOver) -
joining a connection is not itself one of those four events, so a
freshly-joined client received only its own `assigned_color:...`
message and then genuine silence until somebody (possibly not even
them) made the very first move anywhere in the game, with no way to
know where any piece was in the meantime. WHY THE FIX POINT IS HERE, IN
`handle_connection`: this is already the one place that both (a) knows
this is one specific, just-joined connection (not "broadcast to
everyone") and (b) already sends that connection a direct,
point-to-point message (`assigned_color:...` via `self._protocol.send`,
originally `_safe_send` before refactor/server-application-
presentation-split relocated it to ProtocolHandler unchanged) -
reusing that exact same single-connection send path for the current
board state, right after it, needed no new connection-tracking
mechanism at all. `_current_board_text()` is a tiny private helper -
delegates to `self._protocol.format_board_text(self._session.engine.
board)`, called from BOTH this method and `_broadcast_event`, so there
is still only ONE board-serialization CALL SITE in this class, not two.
This is a point-to-point send to the just-joined connection ONLY (a
plain `self._protocol.send` call, not `self._protocol.broadcast`) - an
already-connected opponent does not need or want a redundant duplicate
board state just because a second player joined.
The "server_full" rejection branch (above, in this same method) returns
before this new send is ever reached, so it is completely unaffected -
re-verified directly, and covered by
tests/integration/server/test_initial_board_state_on_join.py's own
dedicated rejection test.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from kungfu_chess.client.events.game_events import (
    AttackerIntercepted,
    GameOver,
    JumpAccepted,
    JumpLanded,
    MoveAccepted,
    MoveRejected,
    PieceArrived,
)
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.jump_command import MalformedJumpCommandError, ParsedJumpCommand
from server.connection_manager import ConnectionManager
from server.game_session import GameSession
from server.move_command import MalformedCommandError, ParsedMoveCommand
from server.protocol_handler import SERVER_FULL_MESSAGE, ProtocolHandler

TICK_INTERVAL_S = 1 / 30

_BROADCAST_EVENT_TYPES = (
    MoveAccepted,
    JumpAccepted,
    JumpLanded,
    AttackerIntercepted,
    MoveRejected,
    PieceArrived,
    GameOver,
)


class GameServer:
    """The APPLICATION half of the server track's APPLICATION/
    PRESENTATION split - coordinates one shared GameSession with real
    WebSocket connections, delegating every wire-parsing/formatting/send
    concern to a held ProtocolHandler (self._protocol). See module
    docstring for the full reasoning behind every decision below,
    including the explicit "THE APPLICATION/PRESENTATION BOUNDARY"
    section for the borderline judgment calls this split required."""

    def __init__(
        self,
        session: Optional[GameSession] = None,
        connection_manager: Optional[ConnectionManager] = None,
        protocol_handler: Optional[ProtocolHandler] = None,
    ) -> None:
        """Construct (or accept injected) GameSession/ConnectionManager/
        ProtocolHandler and subscribe this instance's own broadcaster to
        the session's event bus.

        Args:
            session: The GameSession to coordinate. Defaults to None,
                which constructs a fresh, real, standard-starting-
                position GameSession (the real production case) -
                injectable for tests.
            connection_manager: The ConnectionManager to coordinate.
                Defaults to None, which constructs a fresh, real,
                empty ConnectionManager - injectable for tests.
            protocol_handler: The ProtocolHandler (server/
                protocol_handler.py, refactor/server-application-
                presentation-split) this instance delegates every
                wire-parsing/formatting/send concern to. Defaults to
                None, which constructs a fresh, real, stateless
                ProtocolHandler (the real production case, and the only
                case any existing caller/test needs - re-verified
                directly, nothing constructs this class with a fake/mock
                ProtocolHandler today) - injectable (DIP) for the exact
                same reason session/connection_manager already are.

        Returns:
            None.
        """

        self._session = session if session is not None else GameSession()
        self._connection_manager = connection_manager if connection_manager is not None else ConnectionManager()
        self._protocol = protocol_handler if protocol_handler is not None else ProtocolHandler()
        self._colors: Dict[ServerConnection, Color] = {}

        for event_type in _BROADCAST_EVENT_TYPES:
            self._session.event_bus.subscribe(event_type, self._on_game_event)

    async def handle_connection(self, connection: ServerConnection) -> None:
        """websockets.serve's own per-connection handler - assigns a
        color by join order (or rejects outright if the server is
        already full - see module docstring's "THIRD-PLUS CONNECTION
        POLICY"), then reads move commands from this connection until
        it disconnects, gracefully or abruptly (mirrors Stage B1's own
        handle_connection's identical disconnect handling).

        Args:
            connection: The real ServerConnection websockets.serve
                handed this coroutine for one accepted client.

        Returns:
            None.
        """

        if self._connection_manager.connection_count >= 2:
            await self._protocol.send(connection, SERVER_FULL_MESSAGE)
            await connection.close()
            return

        color = Color.WHITE if self._connection_manager.connection_count == 0 else Color.BLACK
        self._colors[connection] = color
        self._connection_manager.add(connection)
        # Sent so a human tester (or any future client) actually knows
        # which command-color-prefix to use - there is no other way for
        # a connecting client to learn its own assigned color. Spelled
        # out ("white"/"black"), not the terse single-letter
        # Color.value ("w"/"b") the wire protocol itself uses - this
        # message is for a human/log to read, not parsed by anything.
        await self._protocol.send(connection, self._protocol.format_assigned_color(color))
        # See module docstring's "BUGFIX - INITIAL BOARD STATE ON
        # JOIN" - a direct, point-to-point send to THIS connection
        # only, not a broadcast to every connection.
        await self._protocol.send(connection, self._current_board_text())

        try:
            async for message in connection:
                await self._handle_message(connection, color, message)
        except ConnectionClosed:
            pass
        finally:
            self._connection_manager.remove(connection)
            self._colors.pop(connection, None)

    async def _handle_message(self, connection: ServerConnection, assigned_color: Color, message: object) -> None:
        """Parse one raw incoming message via self._protocol
        (server/protocol_handler.py's own leading-character dispatch -
        see module docstring's "JUMP COMMAND ROUTING AND REJECTION
        SCHEME" section for why this can never misroute a genuine move
        command) and dispatch the result to the matching handler.

        Args:
            connection: The connection `message` arrived on.
            assigned_color: The color this connection was assigned at
                join time (see handle_connection).
            message: The raw text (or bytes) websockets delivered.

        Returns:
            None.

        A parse failure (either MalformedCommandError or
        MalformedJumpCommandError - re-verified directly, both are the
        SAME parser calls self._protocol.parse_incoming_command used to
        make before this split, just relocated) produces the identical
        "rejected:malformed:<detail>" response either way, matching this
        method's own pre-split behavior exactly (both branches formatted
        this response identically, so unifying the except clause here
        changes nothing observable).
        """

        try:
            parsed = self._protocol.parse_incoming_command(message)
        except (MalformedCommandError, MalformedJumpCommandError) as exc:
            await self._protocol.send(connection, self._protocol.format_rejection(f"malformed:{exc}"))
            return

        if isinstance(parsed, ParsedJumpCommand):
            await self._handle_jump_command(connection, assigned_color, parsed)
        else:
            await self._handle_move_command(connection, assigned_color, parsed)

    async def _handle_move_command(
        self, connection: ServerConnection, assigned_color: Color, parsed: ParsedMoveCommand
    ) -> None:
        """Validate and dispatch one ALREADY-PARSED move command - see
        module docstring's "MOVE COMMAND REJECTION SCHEME" for the
        exact rejection responses this sends.

        Args:
            connection: The connection this command arrived on.
            assigned_color: The color this connection was assigned at
                join time.
            parsed: The already-parsed ParsedMoveCommand (see
                _handle_message - parsing itself now lives on
                self._protocol, not here; this method only ever
                validates and acts on an already-structured command).

        Returns:
            None.
        """

        if parsed.color is not assigned_color:
            await self._protocol.send(connection, self._protocol.format_rejection("wrong_color"))
            return

        if not self._piece_matches(parsed.color, parsed.piece_kind, parsed.from_cell):
            # See this method's own docstring reference in the module
            # docstring: this needs a real board to check against,
            # which move_command.py deliberately has none of - so the
            # check happens here, the one place that already holds both
            # the parsed command and the real session/board.
            await self._protocol.send(connection, self._protocol.format_rejection("piece_mismatch"))
            return

        # A legal (or engine-rejected) move from here on is entirely
        # handled by the real GameSession/GameEventPublisher/EventBus
        # chain - MoveAccepted/MoveRejected/PieceArrived/GameOver are
        # broadcast to both clients by self._on_game_event, subscribed
        # once in __init__. Nothing further is sent from here for
        # either outcome.
        self._session.request_move(parsed.from_cell, parsed.to_cell)

    async def _handle_jump_command(
        self, connection: ServerConnection, assigned_color: Color, parsed: ParsedJumpCommand
    ) -> None:
        """Validate and dispatch one ALREADY-PARSED jump command - see
        module docstring's "JUMP COMMAND ROUTING AND REJECTION SCHEME"
        for the exact rejection responses this sends, including the one
        new "jump_rejected" token moves never needed.

        Args:
            connection: The connection this command arrived on.
            assigned_color: The color this connection was assigned at
                join time.
            parsed: The already-parsed ParsedJumpCommand (see
                _handle_message).

        Returns:
            None.
        """

        if parsed.color is not assigned_color:
            await self._protocol.send(connection, self._protocol.format_rejection("wrong_color"))
            return

        if not self._piece_matches(parsed.color, parsed.piece_kind, parsed.cell):
            await self._protocol.send(connection, self._protocol.format_rejection("piece_mismatch"))
            return

        accepted = self._session.request_jump(parsed.cell)
        if not accepted:
            # See module docstring's own "JUMP COMMAND ROUTING AND
            # REJECTION SCHEME" section for why this is the one jump
            # rejection case that needs a direct response here, rather
            # than an event-driven broadcast like a move's own
            # MoveRejected: ExtraEngine.request_jump exposes no reason
            # string at all for this outcome.
            await self._protocol.send(connection, self._protocol.format_rejection("jump_rejected"))

    def _piece_matches(self, color: Color, piece_kind: PieceKind, cell: Position) -> bool:
        """Whether a claimed color/piece kind actually matches what's
        on `cell` right now - the real-board check both
        move_command.py's and jump_command.py's own docstrings defer
        to this class for (neither pure parser has, or needs, a real
        Board reference of its own).

        Args:
            color: The claimed color.
            piece_kind: The claimed piece kind.
            cell: The claimed source/own cell to check.

        Returns:
            True if a piece of the claimed color and kind occupies
            `cell` right now; False otherwise (including an empty
            cell, which also can't match any claimed piece).
        """

        piece = self._session.engine.board.piece_at(cell)
        if piece is None:
            return False
        return piece.color is color and piece.kind is piece_kind

    def _on_game_event(self, event: object) -> None:
        """The real EventBus subscriber (Stage A3/B2's own documented
        seam, finally used for real) - see module docstring's "WHY THE
        BROADCASTER BRIDGES A SYNC CALLBACK INTO AN ASYNC SEND" for why
        this stays synchronous and only SCHEDULES the real send.

        Args:
            event: Whatever GameEventPublisher published - only
                MoveAccepted/JumpAccepted/MoveRejected/PieceArrived/
                GameOver are subscribed to in __init__, so `event` is
                always one of those five here; no isinstance filtering
                is needed inside this method itself (self._protocol.
                format_event, called from _broadcast_event below, does
                its own isinstance check to decide whether an extra
                wire-format message is even applicable).

        Returns:
            None.
        """

        asyncio.create_task(self._broadcast_event(event))

    async def _broadcast_event(self, event: object) -> None:
        """Broadcast the real, structured wire-format event message for
        `event` (Stage B7 - see kungfu_chess/notation/
        game_event_wire_format.py's own docstring for the full wire-
        format reasoning), THEN the existing board-text snapshot -
        added alongside the pre-existing board-text broadcast, not in
        place of it (an explicit, accepted Stage B7 scope decision: the
        board-text broadcast remains the fallback/sanity-check safety
        net every existing test and client already depends on).

        Args:
            event: The real event _on_game_event received.

        Returns:
            None.

        This method decides WHICH messages to send and in what order
        for a given event (an APPLICATION/coordination decision about
        game-event semantics - see module docstring's "THE APPLICATION/
        PRESENTATION BOUNDARY" section for why this stays here rather
        than moving to ProtocolHandler) - the actual formatting/sending
        mechanics are all self._protocol's (refactor/server-
        application-presentation-split). Reuses self._protocol.
        broadcast for EVERY send (no duplicated connection-iteration
        logic, per this stage's own DRY requirement) - a MoveRejected
        produces no wire-format message (self._protocol.format_event
        returns None for it - not an animatable motion), so only the
        pre-existing board-text broadcast happens for that one event
        type, byte-for-byte unchanged from before this stage. GameOver
        DOES now produce a real wire-format message too (fix/network-
        gameover-and-king-interception - see module docstring's
        "GameOver ADDITION" section), so it follows the same wire-text-
        then-board-text order as MoveAccepted/JumpAccepted/PieceArrived/
        AttackerIntercepted/JumpLanded below, not MoveRejected's board-
        text-only path. Every send happens from within this SAME
        coroutine, in this fixed order, so a client's own message
        stream always sees this event's own wire message, then its own
        resulting board state, then (for MoveAccepted/JumpAccepted/
        PieceArrived only - see module docstring's "SCORE / MOVE-LOG /
        TIMER BROADCAST" section) its own resulting score/move-log/
        clock snapshot - never interleaved with a DIFFERENT event's own
        messages (this coroutine does not yield control between any of
        these `await self._protocol.broadcast(...)` calls to any other
        code that could send a message to the same connections in
        between).
        """

        wire_text = self._protocol.format_event(event)
        if wire_text is not None:
            await self._protocol.broadcast(self._connection_manager.connections(), wire_text)
        await self._protocol.broadcast(self._connection_manager.connections(), self._current_board_text())
        if isinstance(event, (MoveAccepted, JumpAccepted, PieceArrived)):
            await self._protocol.broadcast(
                self._connection_manager.connections(), self._current_state_snapshot_text()
            )

    def _current_state_snapshot_text(self) -> str:
        """The score/move-log/elapsed-clock snapshot broadcast added by
        this later stage - see module docstring's "SCORE / MOVE-LOG /
        TIMER BROADCAST" section for the full reasoning behind why
        this reads self._session's own observers/engine state directly
        rather than owning any of it here (an APPLICATION concern - the
        actual wire-text FORMATTING of that data is self._protocol's,
        per the module docstring's APPLICATION/PRESENTATION section).

        Returns:
            The current (ScoreSnapshot, MovesLogSnapshot,
            engine.state.clock_ms) triple, serialized via
            self._protocol.format_state_snapshot.
        """

        score = self._session.score_observer.snapshot()
        log = self._session.moves_log_observer.snapshot()
        clock_ms = self._session.engine.state.clock_ms
        return self._protocol.format_state_snapshot(score, log, clock_ms)

    def _current_board_text(self) -> str:
        """The exact board-serialization call used for both the
        event-driven broadcaster (above) and the join-time send (see
        handle_connection and module docstring's "BUGFIX - INITIAL
        BOARD STATE ON JOIN") - kept as the single place this class
        reads the current board and asks self._protocol to serialize
        it, so there is exactly one board-serialization CALL SITE in
        this class, not two (the actual serialization mechanics live on
        self._protocol.format_board_text - see module docstring's
        APPLICATION/PRESENTATION section).

        Returns:
            The current board, serialized via self._protocol.
            format_board_text - the same textual convention this
            project's tests already rely on for board assertions.
        """

        return self._protocol.format_board_text(self._session.engine.board)

    async def run_tick_loop(self) -> None:
        """Advance this server's one real GameSession by real, measured
        wall-clock time, forever - see module docstring's "TICK LOOP /
        TICK RATE" section for the full reasoning. Runs independently
        of any client message arriving; intended to be started exactly
        once, as its own background asyncio task, for the lifetime of
        the process (see server/main.py).

        Returns:
            Never returns under normal operation (an infinite loop) -
            ends only if cancelled (asyncio.CancelledError propagates
            out normally, the standard way to stop an asyncio task).
        """

        last_time = time.perf_counter()
        while True:
            await asyncio.sleep(TICK_INTERVAL_S)
            now = time.perf_counter()
            delta_ms = int((now - last_time) * 1000)
            last_time = now
            self._session.wait(delta_ms)
