"""Unit tests for NetworkClickController
(kungfu_chess/client/network/network_click_controller.py) - the
network-mode counterpart of kungfu_chess/input/controller.py's
Controller: same click-interpretation/selection-state responsibility,
but translates a confirmed move into a NetworkGameClient.send_move
call instead of a direct GameEngine.request_move call (there is no
local engine in network mode - the server is the sole source of
truth).

Pure, fast, no networking and no cv2 at all: a _RecordingNetworkClient
test double (mirroring this project's own established
RecordingObserver/RecordingBusHandler precedent, e.g.
tests/unit/client/test_event_publisher.py) stands in for a real
NetworkGameClient, since this class's entire responsibility is "did the
correct arguments reach send_move" - a real network connection would
prove nothing extra about THIS class's own logic (real end-to-end
network behavior is covered separately, under
tests/integration/client/, exactly like NetworkGameClient's own real
send/receive behavior was already proven in isolation at Stage B5).
"""

from __future__ import annotations

from kungfu_chess.client.network.network_click_controller import NetworkClickController
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def _pixel(cell: Position) -> tuple[int, int]:
    return cell.col * CELL_SIZE, cell.row * CELL_SIZE


class _RecordingNetworkClient:
    def __init__(self):
        self.sent_moves: list = []
        self.sent_jumps: list = []

    def send_move(self, color, piece_kind, from_cell, to_cell) -> None:
        self.sent_moves.append((color, piece_kind, from_cell, to_cell))

    def send_jump(self, color, piece_kind, cell) -> None:
        self.sent_jumps.append((color, piece_kind, cell))


def test_selecting_and_then_targeting_sends_a_real_move_with_correct_arguments():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board

    x, y = _pixel(Position(row=0, col=0))
    controller.click(x, y)  # select the own rook
    x, y = _pixel(Position(row=0, col=1))
    controller.click(x, y)  # empty destination

    assert network_client.sent_moves == [(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0), Position(row=0, col=1))]
    assert controller.selected is None


def test_clicking_the_opponents_piece_with_nothing_selected_does_not_select_or_send():
    grid = _empty_grid(3, 3)
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=0))
    grid[0][0] = enemy
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board

    x, y = _pixel(Position(row=0, col=0))
    controller.click(x, y)

    assert controller.selected is None
    assert network_client.sent_moves == []


def test_clicking_an_empty_cell_with_nothing_selected_does_not_select_or_send():
    board = Board(_empty_grid(3, 3))
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board

    controller.click(0, 0)

    assert controller.selected is None
    assert network_client.sent_moves == []


def test_clicking_before_any_board_has_been_parsed_is_a_safe_noop():
    # controller.board is still None - no broadcast has arrived yet
    # (Stage B6's own documented "no initial-state broadcast" gap).
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)

    controller.click(0, 0)  # must not raise

    assert controller.selected is None
    assert network_client.sent_moves == []


def test_clicking_outside_the_board_with_nothing_selected_is_ignored():
    board = Board(_empty_grid(3, 3))
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board

    controller.click(1000, 1000)

    assert controller.selected is None
    assert network_client.sent_moves == []


def test_clicking_outside_the_board_while_selected_cancels_selection_without_sending():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board
    controller.click(*_pixel(Position(row=0, col=0)))

    controller.click(1000, 1000)

    assert controller.selected is None
    assert network_client.sent_moves == []


def test_clicking_a_different_own_piece_while_selected_replaces_selection_without_sending():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    knight = _piece(Color.WHITE, PieceKind.KNIGHT, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = knight
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board
    controller.click(*_pixel(Position(row=0, col=0)))

    controller.click(*_pixel(Position(row=0, col=1)))

    assert controller.selected == Position(row=0, col=1)
    assert network_client.sent_moves == []


def test_targeting_the_opponents_piece_sends_a_move_as_a_capture_attempt():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=2))
    grid[0][0] = rook
    grid[0][2] = enemy
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board
    controller.click(*_pixel(Position(row=0, col=0)))

    controller.click(*_pixel(Position(row=0, col=2)))

    assert network_client.sent_moves == [(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0), Position(row=0, col=2))]
    assert controller.selected is None


def test_request_jump_for_own_piece_sends_a_real_jump_with_correct_arguments():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board

    controller.request_jump(Position(row=0, col=0))

    assert network_client.sent_jumps == [(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))]


def test_request_jump_does_not_touch_selection_state():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    knight = _piece(Color.WHITE, PieceKind.KNIGHT, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = knight
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board
    controller.click(*_pixel(Position(row=0, col=0)))
    assert controller.selected == Position(row=0, col=0)

    controller.request_jump(Position(row=0, col=1))

    # A jump has no select-then-target state machine of its own - the
    # pre-existing move selection is left completely untouched.
    assert controller.selected == Position(row=0, col=0)
    assert network_client.sent_jumps == [(Color.WHITE, PieceKind.KNIGHT, Position(row=0, col=1))]


def test_request_jump_for_the_opponents_piece_is_a_safe_noop():
    grid = _empty_grid(3, 3)
    enemy = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=0))
    grid[0][0] = enemy
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board

    controller.request_jump(Position(row=0, col=0))

    assert network_client.sent_jumps == []


def test_request_jump_on_an_empty_cell_is_a_safe_noop():
    board = Board(_empty_grid(3, 3))
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board

    controller.request_jump(Position(row=1, col=1))

    assert network_client.sent_jumps == []


def test_request_jump_before_any_board_has_been_parsed_is_a_safe_noop():
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)

    controller.request_jump(Position(row=0, col=0))  # must not raise

    assert network_client.sent_jumps == []


def test_stale_selection_is_cleared_gracefully_if_piece_no_longer_present():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    network_client = _RecordingNetworkClient()
    controller = NetworkClickController(assigned_color=Color.WHITE, network_client=network_client)
    controller.board = board
    controller.click(*_pixel(Position(row=0, col=0)))
    assert controller.selected == Position(row=0, col=0)

    # Simulate a new broadcast arriving where the piece is gone (moved
    # or captured elsewhere) - a fresh Board replaces the old one, the
    # same way NetworkGameLoopRunner replaces controller.board on every
    # new parsed broadcast.
    controller.board = Board(_empty_grid(3, 3))

    controller.click(*_pixel(Position(row=0, col=1)))

    assert controller.selected is None
    assert network_client.sent_moves == []
