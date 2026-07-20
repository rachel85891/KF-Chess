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

WHY THE BROADCASTER BRIDGES A SYNC CALLBACK INTO AN ASYNC SEND:
kungfu_chess.bus.EventBus.subscribe (Stage A1) requires a plain
synchronous callable - `Callable[[object], None]` - and GameSession.
request_move/wait call the whole GameEventPublisher._notify chain
synchronously, inline, with no `await` anywhere in that path. But
actually delivering a broadcast requires a real, awaited
`connection.send(...)`. The bridge: `_on_game_event` (the subscribed
handler) is itself a plain sync function - it satisfies EventBus's
contract - but its body does no real I/O itself; it only computes the
board text and schedules `asyncio.create_task(self._broadcast(text))`.
This is safe specifically because `_on_game_event` is ALWAYS invoked
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
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from kungfu_chess.client.events.game_events import GameOver, MoveAccepted, MoveRejected, PieceArrived
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.color import Color
from server.connection_manager import ConnectionManager
from server.game_session import GameSession
from server.move_command import MalformedCommandError, ParsedMoveCommand, parse_move_command

TICK_INTERVAL_S = 1 / 30

_BROADCAST_EVENT_TYPES = (MoveAccepted, MoveRejected, PieceArrived, GameOver)


class GameServer:
    """Coordinates one shared GameSession with real WebSocket
    connections - see module docstring for the full reasoning behind
    every decision below."""

    def __init__(
        self, session: Optional[GameSession] = None, connection_manager: Optional[ConnectionManager] = None
    ) -> None:
        """Construct (or accept injected) GameSession/ConnectionManager
        and subscribe this instance's own broadcaster to the session's
        event bus.

        Args:
            session: The GameSession to coordinate. Defaults to None,
                which constructs a fresh, real, standard-starting-
                position GameSession (the real production case) -
                injectable for tests.
            connection_manager: The ConnectionManager to coordinate.
                Defaults to None, which constructs a fresh, real,
                empty ConnectionManager - injectable for tests.

        Returns:
            None.
        """

        self._session = session if session is not None else GameSession()
        self._connection_manager = connection_manager if connection_manager is not None else ConnectionManager()
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
            await self._safe_send(connection, "server_full")
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
        await self._safe_send(connection, f"assigned_color:{color.name.lower()}")

        try:
            async for message in connection:
                await self._handle_message(connection, color, message)
        except ConnectionClosed:
            pass
        finally:
            self._connection_manager.remove(connection)
            self._colors.pop(connection, None)

    async def _handle_message(self, connection: ServerConnection, assigned_color: Color, message: object) -> None:
        """Parse and dispatch one raw move-command message from
        `connection` - see module docstring's "MOVE COMMAND REJECTION
        SCHEME" for the exact rejection responses this sends.

        Args:
            connection: The connection `message` arrived on.
            assigned_color: The color this connection was assigned at
                join time (see handle_connection).
            message: The raw text (or bytes) websockets delivered.

        Returns:
            None.
        """

        try:
            parsed = parse_move_command(message)
        except MalformedCommandError as exc:
            await self._safe_send(connection, f"rejected:malformed:{exc}")
            return

        if parsed.color is not assigned_color:
            await self._safe_send(connection, "rejected:wrong_color")
            return

        if not self._piece_matches_board(parsed):
            # See this method's own docstring reference in the module
            # docstring: this needs a real board to check against,
            # which move_command.py deliberately has none of - so the
            # check happens here, the one place that already holds both
            # the parsed command and the real session/board.
            await self._safe_send(connection, "rejected:piece_mismatch")
            return

        # A legal (or engine-rejected) move from here on is entirely
        # handled by the real GameSession/GameEventPublisher/EventBus
        # chain - MoveAccepted/MoveRejected/PieceArrived/GameOver are
        # broadcast to both clients by self._on_game_event, subscribed
        # once in __init__. Nothing further is sent from here for
        # either outcome.
        self._session.request_move(parsed.from_cell, parsed.to_cell)

    def _piece_matches_board(self, parsed: ParsedMoveCommand) -> bool:
        """Whether `parsed`'s claimed color/piece kind actually matches
        what's on its own claimed source square right now - the
        real-board check move_command.py's own docstring defers to
        this class for.

        Args:
            parsed: The already-parsed command to check.

        Returns:
            True if a piece of the claimed color and kind occupies
            parsed.from_cell right now; False otherwise (including an
            empty source square, which also can't match any claimed
            piece).
        """

        piece = self._session.engine.board.piece_at(parsed.from_cell)
        if piece is None:
            return False
        return piece.color is parsed.color and piece.kind is parsed.piece_kind

    def _on_game_event(self, event: object) -> None:
        """The real EventBus subscriber (Stage A3/B2's own documented
        seam, finally used for real) - see module docstring's "WHY THE
        BROADCASTER BRIDGES A SYNC CALLBACK INTO AN ASYNC SEND" for why
        this stays synchronous and only SCHEDULES the real send.

        Args:
            event: Whatever GameEventPublisher published - only
                MoveAccepted/MoveRejected/PieceArrived/GameOver are
                subscribed to in __init__, so `event` is always one of
                those four here; no isinstance filtering is needed
                inside this method itself.

        Returns:
            None.
        """

        board_text = BoardPrinter().print(self._session.engine.board)
        asyncio.create_task(self._broadcast(board_text))

    async def _broadcast(self, text: str) -> None:
        """Send `text` to every currently-tracked connection.

        Args:
            text: The board-state text (BoardPrinter's own format) to
                send to both players.

        Returns:
            None.

        Iterates ConnectionManager.connections()'s own frozenset
        snapshot (no connection-tracking logic duplicated here) - a
        connection that closes mid-broadcast is handled by
        _safe_send's own ConnectionClosed guard, mirroring Stage B1's
        already-closed-connection policy (echo_message's own, now
        retired, docstring) rather than inventing a new one.
        """

        for connection in self._connection_manager.connections():
            await self._safe_send(connection, text)

    async def _safe_send(self, connection: ServerConnection, text: str) -> None:
        """Send `text` to `connection`, silently ignoring
        ConnectionClosed - see module docstring's "WHY THE BROADCASTER
        BRIDGES..." section and Stage B1's own already-closed-
        connection policy, applied identically here: there is nothing
        more useful to do with a failed send than what Stage B1 already
        decided for its own echo path.

        Args:
            connection: The connection to send to.
            text: The text to send.

        Returns:
            None.
        """

        try:
            await connection.send(text)
        except ConnectionClosed:
            pass

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
