"""Unit tests for the two pure functions extracted from build_snapshot's
own in-flight-motion loop (Stage B7.5 - see kungfu_chess/view/renderer.py's
module docstring for the full reasoning behind the extraction and why
both functions are now shared between local play's build_snapshot and
network play's own client-side motion tracking):

- motion_progress(elapsed_ms, total_ms) -> float: the clamp(0, 1)
  fraction-of-duration-elapsed formula.
- interpolate_cell_pixel(from_cell, to_cell, progress) -> (x, y): the
  per-axis linear interpolation between two cells' own pixel positions.

Neither function depends on GameEngine/RealTimeArbiter/Board at all -
both are pure, deterministic, and testable with plain numbers/Positions.
"""

from __future__ import annotations

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.controller import Controller
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE
from kungfu_chess.view.renderer import build_snapshot, interpolate_cell_pixel, motion_progress


def test_motion_progress_is_zero_at_the_very_start():
    assert motion_progress(elapsed_ms=0, total_ms=1000) == 0.0


def test_motion_progress_is_one_at_exactly_full_duration():
    assert motion_progress(elapsed_ms=1000, total_ms=1000) == 1.0


def test_motion_progress_is_the_exact_fraction_partway_through():
    assert motion_progress(elapsed_ms=250, total_ms=1000) == 0.25


def test_motion_progress_clamps_at_one_when_elapsed_exceeds_total():
    assert motion_progress(elapsed_ms=5000, total_ms=1000) == 1.0


def test_motion_progress_clamps_at_zero_for_negative_elapsed():
    assert motion_progress(elapsed_ms=-100, total_ms=1000) == 0.0


def test_motion_progress_is_zero_for_a_non_positive_total_ms():
    # Matches build_snapshot's own pre-existing degenerate-duration
    # guard exactly (a motion with total_ms <= 0 has no meaningful
    # fraction to compute) - never raises, never divides by zero.
    assert motion_progress(elapsed_ms=500, total_ms=0) == 0.0
    assert motion_progress(elapsed_ms=500, total_ms=-10) == 0.0


def test_interpolate_cell_pixel_at_zero_progress_is_the_source_position():
    x, y = interpolate_cell_pixel(Position(row=2, col=3), Position(row=5, col=7), progress=0.0)
    assert (x, y) == (3 * CELL_SIZE, 2 * CELL_SIZE)


def test_interpolate_cell_pixel_at_full_progress_is_the_destination_position():
    x, y = interpolate_cell_pixel(Position(row=2, col=3), Position(row=5, col=7), progress=1.0)
    assert (x, y) == (7 * CELL_SIZE, 5 * CELL_SIZE)


def test_interpolate_cell_pixel_at_half_progress_is_the_exact_midpoint_horizontal_move():
    x, y = interpolate_cell_pixel(Position(row=0, col=0), Position(row=0, col=2), progress=0.5)
    assert (x, y) == (CELL_SIZE, 0)


def test_interpolate_cell_pixel_at_half_progress_is_the_exact_midpoint_diagonal_move():
    x, y = interpolate_cell_pixel(Position(row=0, col=0), Position(row=2, col=2), progress=0.5)
    assert (x, y) == (CELL_SIZE, CELL_SIZE)


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def test_build_snapshot_mid_motion_pixel_position_matches_the_pre_refactor_formula_exactly():
    """Regression test (Stage B7.5): proves build_snapshot's refactored
    in-flight-motion loop (now calling motion_progress +
    interpolate_cell_pixel instead of computing this inline) produces
    the EXACT SAME pixel position the original inline formula would -
    computed here independently, by hand, from the same real
    engine/motion values, NOT by re-calling the extracted functions
    themselves (that would only prove the extraction is internally
    consistent with itself, not that it matches the ORIGINAL, pre-
    refactor behavior). A 3-square horizontal rook move at a
    deliberately non-round elapsed time (700ms of a 3000ms motion) is
    used specifically so the expected pixel position is not a "nice"
    round number a coincidental bug could still accidentally satisfy.
    """

    grid = _empty_grid(1, 4)
    rook = Piece(color=Color.WHITE, kind=PieceKind.ROOK, cell=Position(row=0, col=0))
    grid[0][0] = rook
    engine = GameEngine(Board(grid))
    controller = Controller(engine)
    controller.click(0, 0)
    controller.click(3 * CELL_SIZE, 0)  # 3-square move -> 3000ms total (1000ms/square)
    engine.wait(700)

    snapshot = build_snapshot(engine, controller)
    piece_snapshot = next(p for p in snapshot.pieces if p.id == rook.id)

    # Independently hand-computed expected value - the ORIGINAL inline
    # formula, re-derived here rather than reused, on purpose.
    expected_progress = 700 / 3000
    expected_x = round(0 + (3 * CELL_SIZE - 0) * expected_progress)
    expected_y = 0

    assert (piece_snapshot.x, piece_snapshot.y) == (expected_x, expected_y)
