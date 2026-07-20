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
injected once) rather than a live engine reference, because it
genuinely changes identity every time a new broadcast is parsed
(NetworkGameLoopRunner replaces it wholesale, the same way it replaces
`self.board` itself) - there is no single long-lived Board object to
hold a stable reference to in network mode, unlike Controller's
`self.game_engine.board`, which never changes identity for the
lifetime of one local game.
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
        """

        if self.board is None:
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
