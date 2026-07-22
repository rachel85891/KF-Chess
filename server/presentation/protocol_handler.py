"""ProtocolHandler: the PRESENTATION half of the server track's
APPLICATION/PRESENTATION split (refactor/server-application-
presentation-split). Extracted out of server/game_server.py, which
had grown to mix two genuinely distinct responsibilities in one
664-line file: deciding what a client's message MEANS for the game
(color/ownership validation, which engine method to call) versus how
to SPEAK the wire protocol at all (parsing raw text into structured
commands, formatting outgoing messages via the existing
kungfu_chess/notation/*_wire_format.py modules, and the actual
connection.send calls). This class is the second half; GameServer
(the first half, APPLICATION) is documented at length in its own
module docstring, including the explicit list of borderline calls made
between the two.

ZERO GameSession/ConnectionManager/EventBus KNOWLEDGE, BY DESIGN: this
is the class's whole reason to exist as something separate from
GameServer. Every method here takes exactly the data it needs to
parse/format/send (a raw message, an already-fetched Board/
ScoreSnapshot/MovesLogSnapshot/clock_ms, a Color, a reason string, an
event object, a `ServerConnection` or iterable of them) - never a
GameSession or ConnectionManager reference. GameServer is the one that
reads `self._session.engine.board` / `self._session.score_observer.
snapshot()` / etc. and hands the RESULT to this class to format -
this class never reaches into a session itself. This is what makes the
SRP boundary real, not just nominal: a future stage could swap
GameSession for something else entirely, or add a second, differently-
shaped session, without this file changing by even one line, because
it has never had an opinion about where the data it formats comes from.

PARSING ("parse_incoming_command"): reproduces the ORIGINAL
`_handle_message`'s own leading-character dispatch
(`message[:1].upper() == JUMP_COMMAND_PREFIX` means a jump command,
anything else a move command) verbatim, then delegates to the
pre-existing, UNMODIFIED parse_move_command (server/move_command.py)
or parse_jump_command (kungfu_chess/notation/jump_command.py) - this
class does not re-implement or duplicate either grammar, it only owns
the ONE decision of which existing parser applies to a given raw
message, exactly the decision that already lived in game_server.py's
own `_handle_message` before this split, relocated verbatim rather
than rewritten. Raises whichever of MalformedCommandError/
MalformedJumpCommandError the underlying parser itself raises,
unchanged - GameServer's own except clause catches both types exactly
as it already did before this split (see that module's own docstring
for why GameServer, not this class, decides what a parse failure MEANS
for the connection - a wrong_color/piece_mismatch check on an
ALREADY-parsed command is a validation/coordination decision, this
class's job stops at "here is the structured command, or here is why I
couldn't produce one").

FORMATTING: thin, one-line wrappers around the existing wire-format
modules (format_game_event, format_game_state_snapshot, BoardPrinter)
plus two small, previously-inline literal-string conventions this
project's own protocol already used (`format_assigned_color`,
`format_rejection`) - moved here rather than left as ad-hoc f-strings
scattered across GameServer's own methods, so every piece of "what does
a message actually look like on the wire" knowledge lives in exactly
one file. None of these wrappers add behavior beyond what the module
they wrap already does - re-verified directly against
kungfu_chess/notation/game_event_wire_format.py and
kungfu_chess/notation/game_state_snapshot_wire_format.py before writing
this, rather than assumed.

SENDING (`send`/`broadcast`): the exact ConnectionClosed-swallowing
policy GameServer's own (now retired) `_safe_send`/`_broadcast` already
established, moved here unchanged - see server/main.py's own
"ALREADY-CLOSED-CONNECTION POLICY" docstring section for the original
reasoning this inherits: a client can disconnect between a message
being queued and actually sent, and there is nothing more useful to do
about a failed send than silently ignore it, since the connection's own
removal from ConnectionManager is already handled unconditionally
elsewhere regardless of why its lifetime ended. `broadcast` takes an
iterable of connections (a ConnectionManager.connections() snapshot,
per that class's own docstring) rather than a ConnectionManager itself
- this class has, and needs, no ConnectionManager reference of its own,
consistent with the "zero GameSession/ConnectionManager/EventBus
knowledge" principle above.

NO CONSTRUCTOR STATE: this class holds no instance data at all - every
method is a pure function of its own arguments (parsing/formatting) or
a thin async I/O wrapper (send/broadcast) with no state to initialize.
Kept as an instantiable class rather than a module of bare functions
anyway, matching GameSession/ConnectionManager's own established DIP
pattern (server/game_server.py accepts one as an optional constructor
parameter, injectable for tests) - a future stage could substitute an
alternate ProtocolHandler (e.g. one that logs every formatted message,
or speaks a second wire dialect) without GameServer changing at all.
"""

from __future__ import annotations

from typing import Iterable, Optional, Union

from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from kungfu_chess.client.events.observers import MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.notation.game_event_wire_format import format_game_event
from kungfu_chess.notation.game_state_snapshot_wire_format import format_game_state_snapshot
from kungfu_chess.notation.jump_command import JUMP_COMMAND_PREFIX, ParsedJumpCommand, parse_jump_command
from server.presentation.move_command import ParsedMoveCommand, parse_move_command

SERVER_FULL_MESSAGE = "server_full"
_REJECTION_PREFIX = "rejected:"


class ProtocolHandler:
    """The wire-protocol PRESENTATION layer - see module docstring for
    the full reasoning behind every method below."""

    def parse_incoming_command(self, message: object) -> Union[ParsedMoveCommand, ParsedJumpCommand]:
        """Parse one raw incoming message into a structured command,
        dispatching to the jump-command or move-command grammar based
        on a single, unambiguous leading-character check - the exact
        dispatch server/game_server.py's own `_handle_message` used to
        perform directly, relocated verbatim (see module docstring's
        "PARSING" section for why this can never misroute a genuine
        move command).

        Args:
            message: The raw text (or bytes) websockets delivered from
                a connection.

        Returns:
            A ParsedMoveCommand or ParsedJumpCommand.

        Raises:
            MalformedCommandError: From parse_move_command, for a
                message that isn't a jump command and doesn't parse as
                a valid move command either.
            MalformedJumpCommandError: From parse_jump_command, for a
                message identified as a jump command that doesn't
                parse validly.
        """

        if isinstance(message, str) and message[:1].upper() == JUMP_COMMAND_PREFIX:
            return parse_jump_command(message)
        return parse_move_command(message)

    def format_assigned_color(self, color: Color) -> str:
        """The join-time "assigned_color:<color>" message a connection
        receives exactly once, right after being accepted - spelled out
        ("white"/"black"), not the terse single-letter Color.value
        ("w"/"b") the rest of the wire protocol uses, since this
        specific message is for a human/log to read, never parsed by
        anything (re-verified directly: no test or client parses this
        message's own content, only checks it CONTAINS "white"/"black")."""

        return f"assigned_color:{color.name.lower()}"

    def format_rejection(self, reason: str) -> str:
        """The single "rejected:<reason>" wire convention every direct,
        point-to-point rejection response uses - malformed/wrong_color/
        piece_mismatch/jump_rejected all funnel through this one
        formatter, so the literal "rejected:" prefix exists in exactly
        one place rather than being repeated as an ad-hoc f-string at
        every call site."""

        return f"{_REJECTION_PREFIX}{reason}"

    def format_event(self, event: object) -> Optional[str]:
        """Format a real client-layer game event as wire text, or None
        if it isn't one of the event types kungfu_chess/notation/
        game_event_wire_format.py knows how to serialize - a thin,
        one-line delegation to that module's own format_game_event,
        kept here so GameServer never imports a wire-format module
        directly (see module docstring's "FORMATTING" section)."""

        return format_game_event(event)

    def format_board_text(self, board: Board) -> str:
        """The current board, serialized via the existing BoardPrinter
        - the same textual convention every board-state broadcast (and
        this project's own tests) already rely on. A thin delegation,
        not a new serialization path - kept here so GameServer never
        imports BoardPrinter directly."""

        return BoardPrinter().print(board)

    def format_state_snapshot(self, score: ScoreSnapshot, log: MovesLogSnapshot, clock_ms: int) -> str:
        """The score/move-log/elapsed-clock snapshot wire text - a thin
        delegation to kungfu_chess/notation/
        game_state_snapshot_wire_format.py's own format_game_state_
        snapshot, kept here so GameServer never imports that module
        directly either."""

        return format_game_state_snapshot(score, log, clock_ms)

    async def send(self, connection: ServerConnection, text: str) -> None:
        """Send `text` to `connection`, silently ignoring
        ConnectionClosed - see module docstring's "SENDING" section for
        the full reasoning (moved unchanged from GameServer's own,
        now-retired `_safe_send`).

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

    async def broadcast(self, connections: Iterable[ServerConnection], text: str) -> None:
        """Send `text` to every connection in `connections`.

        Args:
            connections: The connections to send to - a plain iterable
                (e.g. a ConnectionManager.connections() snapshot), not
                a ConnectionManager itself (see module docstring's "ZERO
                GameSession/ConnectionManager/EventBus KNOWLEDGE"
                section for why this class holds no such reference).
            text: The text to send to every connection.

        Returns:
            None.

        Reuses `send` for every individual connection (no duplicated
        ConnectionClosed-handling logic) - moved unchanged from
        GameServer's own, now-retired `_broadcast`.
        """

        for connection in connections:
            await self.send(connection, text)
