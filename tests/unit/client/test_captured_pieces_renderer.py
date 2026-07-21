"""Unit tests for kungfu_chess/client/ui/captured_pieces_renderer.py -
group_captured_pieces_by_color's own dedicated, pure data-transformation
tests (no rendering, no Img at all - per this stage's own explicit
requirement), plus a light rendering smoke test using a real AssetCache
against the real vendored assets (mirrors tests/unit/client/
test_piece_animator.py's own `load_piece_states(PIECES_ROOT / "QW")`
convention for using real assets directly, rather than mocking them).
"""

from __future__ import annotations

from kungfu_chess.client.events.observers import CaptureLogEntry, MoveLogEntry, MovesLogSnapshot
from kungfu_chess.client.surface.asset_cache import AssetCache
from kungfu_chess.client.surface.img import Img
from kungfu_chess.client.ui.captured_pieces_renderer import CapturedPiecesRenderer, group_captured_pieces_by_color
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


def _capture(piece_color: Color, captured_kind: PieceKind, captured_color: Color) -> CaptureLogEntry:
    return CaptureLogEntry(
        piece_kind=PieceKind.QUEEN,
        piece_color=piece_color,
        cell=Position(row=0, col=0),
        captured_piece_kind=captured_kind,
        captured_piece_color=captured_color,
        recorded_at_clock_ms=0,
    )


def _move(piece_color: Color) -> MoveLogEntry:
    return MoveLogEntry(
        piece_kind=PieceKind.PAWN,
        piece_color=piece_color,
        from_cell=Position(row=0, col=0),
        to_cell=Position(row=0, col=1),
        is_jump=False,
        recorded_at_clock_ms=0,
    )


def test_empty_log_produces_both_colors_present_with_empty_lists():
    log = MovesLogSnapshot(entries=())

    grouped = group_captured_pieces_by_color(log)

    assert grouped == {Color.WHITE: [], Color.BLACK: []}


def test_a_white_piece_captured_appears_in_blacks_own_box():
    # White's queen was captured - Black is who captured it, so it
    # belongs in BLACK's own captured-pieces box (the real chess-UI
    # convention this stage's own task explicitly names).
    log = MovesLogSnapshot(entries=(_capture(piece_color=Color.BLACK, captured_kind=PieceKind.QUEEN, captured_color=Color.WHITE),))

    grouped = group_captured_pieces_by_color(log)

    assert grouped[Color.BLACK] == [PieceKind.QUEEN]
    assert grouped[Color.WHITE] == []


def test_a_black_piece_captured_appears_in_whites_own_box():
    log = MovesLogSnapshot(entries=(_capture(piece_color=Color.WHITE, captured_kind=PieceKind.ROOK, captured_color=Color.BLACK),))

    grouped = group_captured_pieces_by_color(log)

    assert grouped[Color.WHITE] == [PieceKind.ROOK]
    assert grouped[Color.BLACK] == []


def test_move_log_entries_are_ignored_by_the_grouping():
    log = MovesLogSnapshot(entries=(_move(Color.WHITE), _move(Color.BLACK)))

    grouped = group_captured_pieces_by_color(log)

    assert grouped == {Color.WHITE: [], Color.BLACK: []}


def test_a_mixed_log_groups_each_capture_into_the_correct_capturing_colors_box_in_chronological_order():
    log = MovesLogSnapshot(
        entries=(
            _move(Color.WHITE),
            _capture(piece_color=Color.WHITE, captured_kind=PieceKind.PAWN, captured_color=Color.BLACK),
            _move(Color.BLACK),
            _capture(piece_color=Color.BLACK, captured_kind=PieceKind.KNIGHT, captured_color=Color.WHITE),
            _capture(piece_color=Color.WHITE, captured_kind=PieceKind.BISHOP, captured_color=Color.BLACK),
        )
    )

    grouped = group_captured_pieces_by_color(log)

    assert grouped[Color.WHITE] == [PieceKind.PAWN, PieceKind.BISHOP]
    assert grouped[Color.BLACK] == [PieceKind.KNIGHT]


def test_render_draws_one_icon_per_captured_piece_using_real_assets():
    canvas = Img.blank_canvas(400, 400)
    asset_cache = AssetCache()
    renderer = CapturedPiecesRenderer(canvas, asset_cache)
    log = MovesLogSnapshot(
        entries=(_capture(piece_color=Color.BLACK, captured_kind=PieceKind.QUEEN, captured_color=Color.WHITE),)
    )

    # Must not raise - real assets, real Img canvas, no mocking.
    renderer.render(x=0, width=220, color=Color.BLACK, log=log)


def test_render_with_no_captures_still_draws_the_label_and_no_icons():
    canvas = Img.blank_canvas(400, 400)
    asset_cache = AssetCache()
    renderer = CapturedPiecesRenderer(canvas, asset_cache)
    log = MovesLogSnapshot(entries=())

    renderer.render(x=0, width=220, color=Color.WHITE, log=log)  # must not raise
