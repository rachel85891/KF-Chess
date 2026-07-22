"""NetworkGameClient: the client-side networking core - Stage B5 of
the server track. Bridges two execution models that cannot be naively
merged: GameLoopRunner's frame loop (kungfu_chess/client/loop/
game_loop.py) is fully synchronous (cv2.waitKey/imshow, every click
currently gets an IMMEDIATE MoveResult back from a direct method call),
while real networking (asyncio's `websockets`, already used
server-side since Stage B1) is asynchronous - a sent command's real
outcome arrives LATER, as a separate broadcast message, not as that
call's return value.

THE BRIDGE: a background thread running its own private asyncio event
loop, holding the real WebSocket connection, communicating with the
calling (eventually: cv2/main) thread ONLY through a thread-safe
queue.Queue - never shared mutable state accessed directly from both
threads. This is the standard, correct pattern for combining a
synchronous caller with asyncio networking; this class exists
specifically to build and prove that bridge works correctly, entirely
isolated from cv2/GameLoopRunner/Controller (mirrored exactly on why
Stage B1's networking and Stage B2's engine hosting were each proven
alone before Stage B3 connected them) - grep confirms no cv2/Img/
GameLoopRunner/Controller import anywhere in this package.

WHY send_move USES asyncio.run_coroutine_threadsafe, NOT
asyncio.create_task OR an ad hoc queue-based mechanism:
asyncio.create_task assumes the CALLING thread IS the event loop's own
thread - calling it from a different thread (which the caller of
send_move always is, by this class's whole design) is undefined/unsafe
behavior, not merely discouraged. asyncio.run_coroutine_threadsafe is
the standard library's own purpose-built primitive for exactly this:
schedule a coroutine onto a specific, already-running event loop, safe
to call from any other thread, returning a concurrent.futures.Future
the caller may (but here, deliberately does not) block on.

WHY send_move IS FIRE-AND-FORGET (does not block, does not return a
MoveResult): the real outcome of a move is only known later, as a
future poll_incoming() broadcast - exactly the same design the SERVER
side already establishes (GameEventPublisher/EventBus: the published
event stream is the authoritative source of truth for what happened,
never a synchronous return value from request_move). Mirroring that
design on the client side means a future Stage B6 only ever needs to
learn game outcomes ONE way (poll a stream of messages), not two
(sometimes a return value, sometimes a broadcast) - one consistent
mechanism, matching this project's own already-established preference
(see kungfu_chess/client/loop/game_loop.py's own "WHY the game-over
listener is event-driven, not polling" reasoning, applied here at the
network layer instead of the in-process Observer layer). The
`run_coroutine_threadsafe` Future this creates is therefore
intentionally never awaited/`.result()`-ed by send_move itself - doing
so would block the calling thread on real network I/O, exactly the
blocking behavior this whole bridge exists to avoid. A ConnectionClosed
raised by the underlying send is swallowed via a done-callback (mirrors
server/game_server.py's own already-closed-connection policy - there is
nothing more useful to do with a failed send than what the server side
already decided) rather than being silently dropped as an unretrieved
future exception.

WHY poll_incoming IS NON-BLOCKING (drains a queue.Queue with
get_nowait() in a loop until Empty, rather than blocking on get()): a
future Stage B6 will call this once per rendered frame, mirroring how
GameLoopRunner already polls input/state once per frame today (see
game_loop.py's own _run_one_frame) - a blocking call here would stall
the entire render loop waiting for network activity that may never
arrive this frame, which is never acceptable for a real-time game loop
that must keep animating/rendering regardless of whether a new network
message has arrived. Backed by the standard library's queue.Queue
(inherently thread-safe) rather than a plain list/deque - the
background thread's own receive loop is the only producer, this
method (called from a different thread) is the only consumer, and
queue.Queue is exactly the primitive designed for that shape without
any additional locking.

WHY THE FIRST MESSAGE (assigned_color/server_full) IS HANDLED
SEPARATELY FROM poll_incoming's ORDINARY STREAM: the caller needs to
know its own color before doing anything else at all (a future Stage
B6 cannot even format an outgoing move command without knowing which
color it's allowed to claim - see
kungfu_chess.notation.move_command_format.format_move_command's own
`color` parameter) - this one piece of startup handshake is worth
making easy to get SYNCHRONOUSLY, unlike ordinary gameplay broadcasts,
which arrive at genuinely unpredictable times relative to the caller's
own frame loop and therefore MUST be polled, not awaited-for. connect()
itself performs the WebSocket handshake AND receives this one message,
inside the SAME `run_coroutine_threadsafe(...).result()` call - the
calling thread blocks only long enough to establish the connection and
learn its assigned color, per this stage's own "must not block the
calling thread beyond actually establishing the connection" - and this
message is never pushed onto the incoming-message queue, so
poll_incoming()'s stream contains only real gameplay broadcasts, never
this one-time handshake text.

WHAT THIS CLASS DELIBERATELY DOES NOT DO: it does not parse
board-state text into a GameSnapshot, and it does not feed any
Observer - poll_incoming() returns RAW received text, verbatim. Turning
that raw text into something Renderer/Observers can consume is
explicitly Stage B6's job, not this one - this stage's contract is
deliberately "dumb pipe in both directions," provable correct in
isolation without needing any of that later machinery to exist yet.

STAGE D2 - REAL AUTH HANDSHAKE (feature/home-screen-d2-auth-protocol):
connect() now requires real `username`/`password` arguments, and sends
them as the CONNECTION'S OWN VERY FIRST MESSAGE - a real
"AUTH:<username>:<password>" command
(kungfu_chess.notation.auth_command_format.format_auth_command), sent
immediately after the WebSocket handshake completes, BEFORE this class
ever reads anything back - replacing Stage C1's cosmetic-only username
(which this class never even knew about) with a REAL, server-verified
account. The server's own reply to THIS message is still the exact
same one first message connect() already read before this stage
(assigned_color/server_full) - only its own possible shapes grew (see
below) and its assigned_color case now also carries a real rating.

THE FIRST-MESSAGE RESPONSE NOW HAS THREE POSSIBLE SHAPES, NOT TWO:
alongside the pre-existing "assigned_color:<color>:<rating>" (now with
a trailing rating field - server/presentation/protocol_handler.py's own
format_assigned_color docstring) and the pre-existing bare
"server_full" literal, a THIRD shape is now possible - a
"rejected:<reason>" message (e.g. "rejected:wrong_password" for a real
login failure, or "rejected:malformed:<detail>" for a malformed AUTH
command this class itself should never actually produce, but is
defensively still recognized) - reusing GameServer's own existing
"rejected:<reason>" rejection vocabulary rather than inventing a
second, parallel one (see server/application/game_server.py's own
"WRONG-PASSWORD REJECTION REUSES..." docstring section). A
"rejected:..." message can ONLY ever mean an auth-time rejection when
it arrives as THIS connection's very first message (an ordinary
in-game "rejected:..." response - wrong_color/piece_mismatch/etc. -
only ever arrives AFTER this join sequence has already completed, via
poll_incoming(), never here).

self.rating/self.rejection_reason - NEW, PLAIN ATTRIBUTES, NOT A
CHANGE TO connect()'s OWN RETURN TYPE: connect() still returns
Optional[Color] exactly as before (None still means "rejected, for
whatever reason") - this keeps every existing caller's own "if
assigned_color is None: handle rejection" control flow completely
intact. The two new attributes carry the ADDITIONAL information this
stage introduces: `self.rating` (the account's real rating, set only
on success) and `self.rejection_reason` (one of "server_full",
"wrong_password", or a "malformed:..." string, set only on rejection) -
a caller that cares WHY it was rejected (kungfu_chess.client.loop.
network_game_loop_runner.NetworkGameLoopRunner, this same stage) reads
`self.rejection_reason` after seeing `self.assigned_color is None`,
exactly the same "read a plain attribute after the fact" pattern this
class's own pre-existing `self.assigned_color` already established.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from dataclasses import dataclass
from typing import List, Optional

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.notation.auth_command_format import format_auth_command
from kungfu_chess.notation.jump_command_format import format_jump_command
from kungfu_chess.notation.move_command_format import format_move_command

_ASSIGNED_COLOR_PREFIX = "assigned_color:"
_SERVER_FULL_MESSAGE = "server_full"
_REJECTION_PREFIX = "rejected:"

_THREAD_START_TIMEOUT_S = 5.0
_CLOSE_TIMEOUT_S = 5.0


class NetworkGameClientError(Exception):
    """Base class for NetworkGameClient's own errors."""


class UnexpectedJoinResponseError(NetworkGameClientError):
    """Raised by connect() if the server's very first message isn't one
    of the three documented forms ("assigned_color:<color>:<rating>",
    "server_full", or "rejected:<reason>" - see module docstring's
    "STAGE D2 - REAL AUTH HANDSHAKE" section) - an invariant violation
    (the server's own protocol changing out from under this class), not
    a normal, caller-triggerable condition."""


@dataclass(frozen=True)
class _JoinResponse:
    """The fully-parsed result of the server's very first message - see
    _parse_join_response's own docstring. Exactly one of
    (color and rating) or rejection_reason is populated, never both -
    color/rating are None on rejection, rejection_reason is None on
    success."""

    color: Optional[Color]
    rating: Optional[int]
    rejection_reason: Optional[str]


def _parse_join_response(message: str) -> _JoinResponse:
    """Parse the server's very first message into a _JoinResponse - see
    module docstring's "THE FIRST-MESSAGE RESPONSE NOW HAS THREE
    POSSIBLE SHAPES" section for the full reasoning behind each branch.

    Args:
        message: The raw first message from the server - expected to
            be "assigned_color:<color>:<rating>", "server_full", or
            "rejected:<reason>" (see server/application/game_server.py's
            own handle_connection, re-checked directly for these exact
            literal shapes before writing this).

    Returns:
        A _JoinResponse - success (color+rating) or rejection
        (rejection_reason), never both.

    Raises:
        UnexpectedJoinResponseError: If `message` matches none of the
            three documented forms.
    """

    if message == _SERVER_FULL_MESSAGE:
        return _JoinResponse(color=None, rating=None, rejection_reason=_SERVER_FULL_MESSAGE)

    if message.startswith(_REJECTION_PREFIX):
        reason = message[len(_REJECTION_PREFIX) :]
        return _JoinResponse(color=None, rating=None, rejection_reason=reason)

    if message.startswith(_ASSIGNED_COLOR_PREFIX):
        remainder = message[len(_ASSIGNED_COLOR_PREFIX) :]
        parts = remainder.split(":", 1)
        if len(parts) == 2:
            color_name, rating_text = parts
            try:
                color = Color[color_name.upper()]
                rating = int(rating_text)
                return _JoinResponse(color=color, rating=rating, rejection_reason=None)
            except (KeyError, ValueError):
                pass

    raise UnexpectedJoinResponseError(f"unrecognized join response from server: {message!r}")


class NetworkGameClient:
    """Client-side networking core - see module docstring for the full
    reasoning behind every decision below. No server URI is hardcoded
    anywhere in this class - connect() takes it as a parameter,
    matching server/main.py's own configurable-host/port convention.
    """

    def __init__(self) -> None:
        """Create a NetworkGameClient with no background thread/loop
        started yet - connect() starts both. Constructing this object
        has no side effects (no thread spawned, no network touched)
        until connect() is actually called.

        Returns:
            None.
        """

        self.assigned_color: Optional[Color] = None
        # Stage D2 - see module docstring's "self.rating/
        # self.rejection_reason" section: populated by connect(), read
        # after the fact by callers that need the account's real rating
        # (on success) or the real reason a connection was rejected.
        self.rating: Optional[int] = None
        self.rejection_reason: Optional[str] = None

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connection: Optional[ClientConnection] = None
        self._incoming: "queue.Queue[str]" = queue.Queue()

    def connect(self, uri: str, username: str, password: str) -> Optional[Color]:
        """Start this client's background thread + event loop, open a
        real WebSocket connection to `uri`, send the real AUTH command
        (Stage D2 - see module docstring's "STAGE D2 - REAL AUTH
        HANDSHAKE" section), and receive the server's one-time join
        response - see module docstring's "WHY THE FIRST MESSAGE... IS
        HANDLED SEPARATELY" section for why this method blocks the
        calling thread for exactly this much, and no more.

        Args:
            uri: The WebSocket URI to connect to (e.g.
                "ws://localhost:8765") - never hardcoded in this class.
            username: The account's username - sent to the server as
                part of the real AUTH command; also used server-side to
                sign up (if new) or log in (if it already exists).
            password: The account's plaintext password - sent to the
                server as part of the same AUTH command; never stored
                on this object beyond this one call.

        Returns:
            The Color this connection was assigned (also stored as
            self.assigned_color), or None if the server rejected this
            connection - either "server_full" (see
            server/application/game_server.py's own third-plus-
            connection policy) or a real login failure (self.
            rejection_reason distinguishes the two - see module
            docstring).

        Raises:
            UnexpectedJoinResponseError: See _parse_join_response.
        """

        self._start_background_loop()

        future = asyncio.run_coroutine_threadsafe(self._do_connect(uri, username, password), self._loop)
        self.assigned_color = future.result()
        return self.assigned_color

    def _start_background_loop(self) -> None:
        """Start the dedicated background thread and its own private
        asyncio event loop - see module docstring's "THE BRIDGE"
        section. Blocks the calling thread only until the loop is
        confirmed running (via a threading.Event), not for the
        connection itself.

        Returns:
            None.
        """

        loop_ready = threading.Event()

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            loop_ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        if not loop_ready.wait(timeout=_THREAD_START_TIMEOUT_S):
            raise NetworkGameClientError("background event loop failed to start in time")

    async def _do_connect(self, uri: str, username: str, password: str) -> Optional[Color]:
        """Runs ON the background loop's own thread (scheduled via
        run_coroutine_threadsafe by connect(), above): open the real
        connection, send the real AUTH command (Stage D2 - this
        connection's own very first message, before anything is ever
        read back), receive the one-time join response, and start the
        long-running receive loop as a plain task on this SAME loop
        (safe here - unlike send_move, this runs already inside the
        loop's own thread, so a bare asyncio task is the correct,
        simpler primitive; run_coroutine_threadsafe is only needed to
        get INTO this thread from another one in the first place).

        Args:
            uri: The WebSocket URI to connect to.
            username: See connect().
            password: See connect().

        Returns:
            The parsed join response's own color (see
            _parse_join_response) - self.rating/self.rejection_reason
            are set as a side effect before returning, mirroring how
            self.assigned_color is set by connect() itself, one level up.
        """

        self._connection = await websockets.connect(uri)
        await self._connection.send(format_auth_command(username, password))
        first_message = await self._connection.recv()
        asyncio.get_running_loop().create_task(self._receive_loop())

        parsed = _parse_join_response(first_message)
        self.rating = parsed.rating
        self.rejection_reason = parsed.rejection_reason
        return parsed.color

    async def _receive_loop(self) -> None:
        """Runs for the whole lifetime of the connection: push every
        raw message onto the thread-safe incoming queue, verbatim - see
        module docstring's "WHAT THIS CLASS DELIBERATELY DOES NOT DO"
        for why no parsing happens here. Ends quietly on disconnect,
        gracefully or abruptly (mirrors server/game_server.py's own
        identical ConnectionClosed handling) - poll_incoming() simply
        stops receiving anything new after that, rather than this
        method raising into the event loop's own task machinery.

        Returns:
            None.
        """

        try:
            async for message in self._connection:
                self._incoming.put(message)
        except ConnectionClosed:
            pass

    def send_move(self, color: Color, piece_kind: PieceKind, from_cell: Position, to_cell: Position) -> None:
        """Format and send a move command - fire-and-forget from the
        caller's perspective; see module docstring's "WHY send_move IS
        FIRE-AND-FORGET" and "WHY send_move USES
        asyncio.run_coroutine_threadsafe" sections for the full
        reasoning.

        Args:
            color: The mover's color.
            piece_kind: The moving piece's kind.
            from_cell: The Position the piece currently occupies.
            to_cell: The Position it is being moved to.

        Returns:
            None. Does not block waiting for any reply, and does not
            return a MoveResult - the real outcome is only ever known
            via a later poll_incoming() broadcast.
        """

        text = format_move_command(color=color, piece_kind=piece_kind, from_cell=from_cell, to_cell=to_cell)
        future = asyncio.run_coroutine_threadsafe(self._send_text(text), self._loop)
        future.add_done_callback(self._ignore_connection_closed)

    def send_jump(self, color: Color, piece_kind: PieceKind, cell: Position) -> None:
        """Format and send a jump command - fire-and-forget, exactly
        mirroring send_move's own reasoning and mechanism verbatim (see
        module docstring's "WHY send_move IS FIRE-AND-FORGET" and "WHY
        send_move USES asyncio.run_coroutine_threadsafe" sections,
        which apply identically here): the real outcome (accepted -> a
        later JumpAccepted broadcast, or rejected -> a direct
        "rejected:..." response, per server/game_server.py's own jump
        rejection scheme) is only ever known via a later
        poll_incoming() message, never this call's own return value.

        Args:
            color: The jumping piece's color.
            piece_kind: The jumping piece's kind.
            cell: The Position the jumping piece currently occupies (a
                single cell, not a from/to pair - matches
                format_jump_command's own contract).

        Returns:
            None. Does not block, does not return an accepted/rejected
            result.
        """

        text = format_jump_command(color=color, piece_kind=piece_kind, cell=cell)
        future = asyncio.run_coroutine_threadsafe(self._send_text(text), self._loop)
        future.add_done_callback(self._ignore_connection_closed)

    async def _send_text(self, text: str) -> None:
        """Runs on the background loop's own thread - the real,
        awaited send.

        Args:
            text: The already-formatted command text to send.

        Returns:
            None.
        """

        await self._connection.send(text)

    def _ignore_connection_closed(self, future: "asyncio.Future[None]") -> None:
        """send_move's done-callback: swallow a ConnectionClosed raised
        by the real send (see module docstring's "WHY send_move IS
        FIRE-AND-FORGET" for why this mirrors server/game_server.py's
        own already-closed-connection policy) - retrieves the future's
        exception (if any) so it isn't reported as an unretrieved
        asyncio exception, without re-raising it into the calling
        thread (which is never listening for it, by this method's own
        fire-and-forget design).

        Args:
            future: The completed run_coroutine_threadsafe future for
                one send_move call.

        Returns:
            None.
        """

        exc = future.exception()
        if exc is not None and not isinstance(exc, ConnectionClosed):
            raise exc

    def poll_incoming(self) -> List[str]:
        """Non-blocking: return every raw message received since the
        last call, in arrival order, then clear the internal buffer -
        see module docstring's "WHY poll_incoming IS NON-BLOCKING".

        Returns:
            A list of raw message strings (possibly empty) - never
            blocks, never raises for "nothing new arrived".
        """

        messages: List[str] = []
        while True:
            try:
                messages.append(self._incoming.get_nowait())
            except queue.Empty:
                break
        return messages

    def close(self) -> None:
        """Cleanly shut down the connection and stop the background
        thread/event loop - safe to call even if connect() was never
        called, or close() was already called.

        Returns:
            None.
        """

        if self._loop is None:
            return  # connect() was never called - nothing to shut down.

        if self._connection is not None:
            future = asyncio.run_coroutine_threadsafe(self._close_connection(), self._loop)
            future.result(timeout=_CLOSE_TIMEOUT_S)
            self._connection = None

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=_CLOSE_TIMEOUT_S)
        self._loop.close()
        self._loop = None

    async def _close_connection(self) -> None:
        """Runs on the background loop's own thread - closes the real
        connection, silently ignoring an already-closed one (the same
        already-closed-connection policy this whole module already
        applies elsewhere)."""

        try:
            await self._connection.close()
        except ConnectionClosed:
            pass
