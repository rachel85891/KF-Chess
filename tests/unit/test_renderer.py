from __future__ import annotations

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.view.image_view import RecordingSurface
from kungfu_chess.view.renderer import GameSnapshot, PieceSnapshot, Renderer, build_snapshot


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def _snapshot(pieces=(), selected=None, game_over=False) -> GameSnapshot:
    return GameSnapshot(board_width=3, board_height=3, pieces=pieces, game_over=game_over, selected=selected)


def test_snapshot_reflects_board_dimensions_and_idle_piece_position():
    grid = _empty_grid(2, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=1, col=2))
    grid[1][2] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)

    snapshot = build_snapshot(engine, controller)

    assert snapshot.board_width == 3
    assert snapshot.board_height == 2
    assert len(snapshot.pieces) == 1

    piece_snapshot = snapshot.pieces[0]
    assert piece_snapshot.id == rook.id
    assert piece_snapshot.kind is PieceKind.ROOK
    assert piece_snapshot.color is Color.WHITE
    assert piece_snapshot.x == 200
    assert piece_snapshot.y == 100
    assert piece_snapshot.state is PieceState.IDLE
    assert snapshot.selected is None
    assert snapshot.game_over is False


def test_snapshot_selected_field_reflects_controller_selection():
    grid = _empty_grid(2, 2)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)

    snapshot = build_snapshot(engine, controller)

    assert snapshot.selected == Position(row=0, col=0)


def test_snapshot_game_over_flag_reflects_engine_state():
    engine = GameEngine(Board(_empty_grid(2, 2)))
    controller = Controller(engine)
    engine.state.game_over = True

    snapshot = build_snapshot(engine, controller)

    assert snapshot.game_over is True


def test_snapshot_piece_mid_motion_has_interpolated_position_between_source_and_destination():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)
    controller.click(200, 0)
    engine.wait(500)

    snapshot = build_snapshot(engine, controller)

    piece_snapshot = next(p for p in snapshot.pieces if p.id == rook.id)
    assert piece_snapshot.state is PieceState.MOVING
    assert 0 < piece_snapshot.x < 200
    assert piece_snapshot.y == 0


def test_renderer_calls_expected_surface_methods_for_idle_snapshot():
    piece_snapshot = PieceSnapshot(id=1, kind=PieceKind.ROOK, color=Color.WHITE, x=0, y=0, state=PieceState.IDLE)
    snapshot = _snapshot(pieces=(piece_snapshot,))
    surface = RecordingSurface()

    Renderer(surface).render(snapshot)

    kinds = [call[0] for call in surface.calls]
    assert kinds.count("draw_grid") == 1
    assert kinds.count("draw_piece") == 1
    assert "draw_selection_highlight" not in kinds
    assert "draw_game_over_message" not in kinds


def test_renderer_calls_draw_selection_highlight_when_selected():
    snapshot = _snapshot(selected=Position(row=1, col=1))
    surface = RecordingSurface()

    Renderer(surface).render(snapshot)

    kinds = [call[0] for call in surface.calls]
    assert kinds.count("draw_selection_highlight") == 1


def test_renderer_calls_draw_game_over_message_when_game_over():
    snapshot = _snapshot(game_over=True)
    surface = RecordingSurface()

    Renderer(surface).render(snapshot)

    kinds = [call[0] for call in surface.calls]
    assert kinds.count("draw_game_over_message") == 1
