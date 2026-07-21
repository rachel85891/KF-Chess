"""NetworkClickController: click interpretation and selected-cell state
for network mode - Stage B6 of the server track. The direct
counterpart of kungfu_chess/input/controller.py's Controller, but for
a client that has no local, authoritative GameEngine at all - in
network mode, the server is the sole source of truth (matching every
other network-track stage's own design: B2's GameSession, B3's
GameServer), so a confirmed move is sent over the network
(NetworkGameClient.send_move) instead of being validated/executed by a
direct GameEngine.request_move call.

WHY THIS IS ITS OWN CLASS, NOT A MODIFICATION OF Controller: Controller
is constructed around a real GameEngine (`self.game_engine =
game_engine`) and calls `self.game_engine.request_move(...)` directly
- there is no game_engine to hold in network mode, and this stage must
not touch Controller's existing constructor/behavior at all (every
existing local-play test depends on it staying exactly as it is). The
two classes' interaction MODEL is otherwise the same shape (select,
then click a target) - re-derived here against the same real Board
data (self.board, kept in sync by NetworkGameLoopRunner from the most
recently parsed server broadcast) rather than against a live
GameEngine's board.

THE ONE REAL BEHAVIORAL DIFFERENCE FROM Controller: only a piece
belonging to THIS client's own `assigned_color` may ever be selected in
the first place - Controller (local, hotseat-style single-process play)
allows selecting either side's pieces, since one process/keyboard
controls both. In network mode, this client can only ever legally move
its own color's pieces (the server would reject anything else with
"rejected:wrong_color" anyway - see server/game_server.py's own
MOVE COMMAND REJECTION SCHEME) - so a click on the opponent's piece (or
an empty cell) with nothing currently selected is a plain no-op here,
per this stage's own explicit requirement, rather than sending a
request the server would only reject.

NO VISUAL/AUDIO FEEDBACK FOR AN IGNORED CLICK (documented decision):
GameLoopRunner's local play has a real SoundManager reacting to a real
MoveRejected event from a real GameEventPublisher - no such event
stream exists here for a click this class itself declines to act on
(the click never reaches the network at all, so no server-side
rejection event will ever fire for it either). Adding a NEW, separate
feedback mechanism just for "you clicked something you can't move" is
new scope Stage B6 was not asked to build, and the game remains fully
playable without it (a player very quickly learns which pieces are
theirs) - deferred to a future polish stage, not fixed here.

`board` is a plain, publicly settable attribute (not constructor-
injected once) rather than a live engine reference, because this
class has no engine of its own to read a `.board` property from -
NetworkGameLoopRunner assigns it directly instead. As of Stage B7
(kungfu_chess/client/loop/network_game_loop_runner.py's own "STAGE B7"
docstring section), NetworkGameLoopRunner assigns this attribute only
ONCE per connection - the first board this client ever receives -
and mutates that SAME Board object in place from then on (to preserve
piece identity for its own PieceAnimatorRegistry), rather than
replacing it wholesale on every later broadcast the way it used to
before Stage B7. This class's own `click()` method is unaffected
either way: it only ever reads `self.board.piece_at(...)` fresh at
call time, which reflects the current state correctly whether the
object was replaced or mutated in place.

GAME-OVER INPUT FREEZE (fix/network-gameover-and-king-interception):
`game_over` is a plain, publicly settable bool attribute (defaults to
False), checked at the very start of both click() and request_jump() -
the single guard point for BOTH input paths, since both eventually
reach this class (see MouseAdapter's own left/right-click routing).
NetworkGameLoopRunner sets it to True once it parses a real GameOver
wire message (kungfu_chess/notation/game_event_wire_format.py) - see
that class's own docstring for the chosen freeze-and-display end-of-
game UX. Placed here, on this class, rather than as a check inside
NetworkGameLoopRunner's own click-dispatch wiring: this class is
already the single place BOTH gestures funnel through and already owns
every other "is this input allowed right now" decision (ownership,
bounds, board-not-yet-parsed) - adding a second, parallel gate
elsewhere would split one concern across two classes for no benefit.
"""

from __future__ import annotations

from typing import Optional

from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.position import Position


class NetworkClickController:
    """Network-mode click interpretation - see module docstring."""

    def __init__(self, assigned_color: Color, network_client) -> None:
        """Construct a NetworkClickController.

        Args:
            assigned_color: This client's own color, as returned by
                NetworkGameClient.connect() - only pieces of this color
                may ever be selected (see module docstring).
            network_client: Anything exposing
                `send_move(color, piece_kind, from_cell, to_cell) ->
                None` - a real NetworkGameClient in production, or a
                plain recording test double in this class's own unit
                tests (see tests/unit/client/
                test_network_click_controller.py) - duck-typed, not
                type-checked at runtime, the same "depend on the
                methods actually used, not a concrete class" principle
                MouseAdapter itself already applies to the object it
                calls `.click(x, y)` on.
        """

        self.assigned_color = assigned_color
        self._network_client = network_client
        self.board: Optional[Board] = None
        self.selected: Optional[Position] = None
        self.game_over = False
        self._board_mapper = BoardMapper()

    def click(self, x: int, y: int) -> None:
        """Interpret one click at image-pixel (x, y) - same signature
        and calling convention as Controller.click, so MouseAdapter can
        be reused as-is (see kungfu_chess/client/loop/
        network_game_loop_runner.py for the actual wiring).

        Args:
            x: Image-pixel x coordinate.
            y: Image-pixel y coordinate.

        Returns:
            None.

        Safe to call before any board has ever been parsed
        (self.board is None) - a plain no-op, matching this stage's own
        documented "no initial-state broadcast" gap (there is nothing
        yet to click against).

        Also a safe no-op once self.game_over is True (fix/network-
        gameover-and-king-interception) - see this module's own
        docstring's "GAME-OVER INPUT FREEZE" section for why this flag
        lives here rather than in NetworkGameLoopRunner itself.
        """

        if self.board is None or self.game_over:
            return

        cell = self._board_mapper.pixel_to_cell(x, y)
        board = self.board

        if not board.in_bounds(cell):
            self.selected = None
            return

        if self.selected is not None and board.piece_at(self.selected) is None:
            self.selected = None

        if self.selected is None:
            piece = board.piece_at(cell)
            if piece is not None and piece.color is self.assigned_color:
                self.selected = cell
            return

        selected_piece = board.piece_at(self.selected)
        target_piece = board.piece_at(cell)

        if target_piece is not None and target_piece.color == selected_piece.color:
            self.selected = cell
            return

        self._network_client.send_move(self.assigned_color, selected_piece.kind, self.selected, cell)
        self.selected = None

    def request_jump(self, cell: Position) -> None:
        """Request a JUMP for whichever piece occupies `cell` - the
        network-mode counterpart of GameLoopRunner's own _request_jump
        (kungfu_chess/client/loop/game_loop.py), called from
        NetworkGameLoopRunner's own on_jump_requested wiring (see that
        class's own docstring).

        Its own distinct method, not folded into click() (SRP - a jump
        is a single-click, no-selection gesture with no shared
        select-then-target state machine to reuse, exactly matching
        MouseAdapter's own reasoning for why right-click is routed to
        a completely separate callback rather than through
        Controller/NetworkClickController.click at all). Deliberately
        does not read or mutate self.selected - a jump never
        participates in the move selection state machine.

        Args:
            cell: The cell the piece to jump currently occupies (a
                single cell, not a from/to pair - matches
                ExtraEngine.request_jump's own single-cell contract,
                re-verified directly).

        Returns:
            None.

        Mirrors click()'s own ownership check (see this module's own
        docstring's "THE ONE REAL BEHAVIORAL DIFFERENCE FROM
        Controller" section): only a piece belonging to this client's
        own assigned_color may ever be requested to jump - a
        right-click on the opponent's piece, an empty cell, or before
        any board has been parsed yet (self.board is None) is a safe,
        silent no-op, for the identical reason a left-click on any of
        those is (the server would reject anything else anyway - see
        server/game_server.py's own jump rejection scheme). Also mirrors
        click()'s own self.game_over guard (see this module's own
        docstring's "GAME-OVER INPUT FREEZE" section) for the identical
        reason: once the game has ended, no further request of any kind
        should leave this client.
        """

        if self.board is None or self.game_over:
            return

        piece = self.board.piece_at(cell)
        if piece is None or piece.color is not self.assigned_color:
            return

        self._network_client.send_jump(self.assigned_color, piece.kind, cell)
