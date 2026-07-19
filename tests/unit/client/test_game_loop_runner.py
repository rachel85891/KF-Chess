from __future__ import annotations

import os
import sys

import cv2
import pytest

from kungfu_chess.client.animation.animation_state import AnimationState
from kungfu_chess.client.audio.audio_player import AudioPlayer
from kungfu_chess.client.audio.sound_manager import SOUND_PATHS
from kungfu_chess.client.loop.game_loop import GameLoopRunner
from kungfu_chess.client.ui.coordinate_label_renderer import LABEL_MARGIN
from kungfu_chess.client.ui.side_panel_renderer import PANEL_WIDTH
from kungfu_chess.model.board import Board
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import Piece, PieceKind
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import CELL_SIZE, MS_PER_SQUARE

# A full real-time loop with a live cv2 window (the blocking while-loop
# in run(), real mouse events, real window-close detection) is not
# something this suite attempts to automate - matching the same
# precedent already established for this project's loop/window-heavy
# code (e.g. scripts/demo_stage6_render_board.py is a manual, human-run
# check, not a pytest target). What CAN be verified without a real
# window loop - the wiring, the event-driven game-over flag, and one
# isolated frame of _run_one_frame - is what these tests cover.
#
# Every test below except the last constructs GameLoopRunner with
# headless=True: cv2.namedWindow/imshow/waitKey/getWindowProperty all
# require a real GUI backend, and on a machine with no display (this
# project's own CI/sandbox environment, confirmed directly) calling
# any of them ABORTS THE WHOLE PROCESS rather than raising a catchable
# exception - so constructing a non-headless GameLoopRunner here would
# crash the entire pytest run, not just fail one test. headless=True
# still exercises every real wiring/event/rendering/animation-
# advancement behavior this class provides (see game_loop.py's own
# module docstring) - it only skips the calls that actually touch
# cv2's GUI layer, which these tests were never testing in the first
# place. No cv2.destroyAllWindows() cleanup is needed in these tests
# either, for the same reason: headless mode never creates a window.


def _empty_grid(rows: int, cols: int) -> list[list[None]]:
    return [[None for _ in range(cols)] for _ in range(rows)]


def _piece(color: Color, kind: PieceKind, cell: Position) -> Piece:
    return Piece(color=color, kind=kind, cell=cell)


def _display_available() -> bool:
    """Best-effort heuristic for whether a real GUI backend is likely
    usable here. Cannot be a perfect check - cv2's failure mode on a
    truly headless machine is a hard process abort, not a catchable
    exception, so this can only reduce the chance of hitting one, not
    eliminate it (the real, non-headless test below still wraps
    construction in a try/except cv2.error as a second line of
    defense for platforms where cv2 does raise a catchable error
    instead of aborting)."""

    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def test_construction_wires_all_three_observers_to_real_published_events():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    pawn = _piece(Color.BLACK, PieceKind.PAWN, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = pawn
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestWiring", headless=True)

    result = runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    assert result.is_accepted is True

    # PieceAnimatorRegistry subscription: the rook's own animator
    # really transitioned to MOVE in reaction to the real event.
    assert runner.piece_animator_registry.animator_for(rook.id).current_state == AnimationState.MOVE

    runner.publisher.wait(MS_PER_SQUARE)

    # ScoreObserver subscription: white really gained the pawn's
    # real PIECE_VALUES score (1), not just "subscribe() was called".
    score = runner.score_observer.snapshot()
    assert score.score_by_color[Color.WHITE] == 1

    # MovesLogObserver subscription: a real move entry and a real
    # capture entry were both actually recorded.
    entries = runner.moves_log_observer.snapshot().entries
    assert len(entries) == 2


def test_game_over_listener_sets_the_flag_on_a_real_game_over_event():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    king = _piece(Color.BLACK, PieceKind.KING, Position(row=0, col=1))
    grid[0][0] = rook
    grid[0][1] = king
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestGameOver", headless=True)
    assert runner._game_over is False

    runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    runner.publisher.wait(MS_PER_SQUARE)

    assert runner._game_over is True


def test_run_one_frame_does_not_raise_and_advances_a_moving_pieces_animation():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestOneFrame", headless=True)

    runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=2))
    animator = runner.piece_animator_registry.animator_for(rook.id)
    assert animator.current_state == AnimationState.MOVE
    assert animator.elapsed_ms_in_state == 0

    runner._run_one_frame(50)  # no exception == success

    assert animator.elapsed_ms_in_state > 0


def test_cooldown_tracker_is_subscribed_and_reflects_a_real_piece_arrived():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestCooldown", headless=True)
    assert runner.cooldown_tracker.remaining_ratio(rook.id, current_clock_ms=0) == 0.0

    # _run_one_frame is what actually tells cooldown_tracker the
    # correct clock_ms before driving publisher.wait() - see
    # game_loop.py's own "COOLDOWN TIMER" docstring section.
    runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    runner._run_one_frame(MS_PER_SQUARE)

    ratio = runner.cooldown_tracker.remaining_ratio(rook.id, current_clock_ms=runner.engine.state.clock_ms)
    assert ratio == 1.0


def test_request_jump_transitions_the_targeted_pieces_animator_to_jump():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestJump", headless=True)

    # _request_jump is MouseAdapter's on_jump_requested callback,
    # invoked exactly as a real right-click would - see mouse_adapter's
    # own tests for the click -> cell mapping itself.
    runner._request_jump(Position(row=0, col=0))

    assert runner.piece_animator_registry.animator_for(rook.id).current_state == AnimationState.JUMP


def test_canvas_layout_matches_the_documented_stage_13c_formula():
    grid = _empty_grid(8, 8)
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestLayout", headless=True)

    assert runner._board_pixel_width == 8 * CELL_SIZE
    assert runner._board_pixel_height == 8 * CELL_SIZE
    assert runner._board_origin_x == PANEL_WIDTH + LABEL_MARGIN
    assert runner._board_origin_y == 0
    assert runner._total_canvas_width == runner._board_origin_x + runner._board_pixel_width + PANEL_WIDTH
    assert runner._total_canvas_height == runner._board_pixel_height + LABEL_MARGIN


def test_run_one_frame_does_not_raise_with_pieces_at_all_four_board_corners():
    # A real regression check for the new board_canvas -> main_canvas
    # paste(): a wrong total_canvas_width/height or a wrong
    # board_origin_x/y would surface here as a real
    # PasteOutOfBoundsError, the same failure mode the asset-swap
    # sprite-sizing fix (assets/README.md) was originally caught by.
    grid = _empty_grid(8, 8)
    grid[0][0] = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][7] = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=7))
    grid[7][0] = _piece(Color.BLACK, PieceKind.ROOK, Position(row=7, col=0))
    grid[7][7] = _piece(Color.BLACK, PieceKind.ROOK, Position(row=7, col=7))
    board = Board(grid)
    runner = GameLoopRunner(board, window_name="TestCorners", headless=True)

    runner._run_one_frame(16)  # no exception == success


def test_left_click_correctly_selects_the_piece_under_the_cursor_despite_the_panel_offset():
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    runner = GameLoopRunner(board, window_name="TestClickOffset", headless=True)

    # A raw window-pixel click inside cell (0, 0) - only correct once
    # board_origin_x/y is applied via the mapper's window_origin (see
    # module docstring's "CLICK OFFSET" section).
    window_x = runner._board_origin_x + CELL_SIZE // 2
    window_y = runner._board_origin_y + CELL_SIZE // 2
    runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, window_x, window_y, 0, None)

    assert runner.controller.selected == Position(row=0, col=0)


def test_left_click_at_the_pre_13c_raw_origin_no_longer_hits_the_board():
    # Demonstrates the offset fix actually matters: a click at the OLD
    # (pre-Stage-13c) identity-mapping position now lands inside the
    # left panel/label margin, not on the board at all.
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    runner = GameLoopRunner(board, window_name="TestClickOffsetRegression", headless=True)

    runner.mouse_adapter.on_mouse_event(cv2.EVENT_LBUTTONDOWN, CELL_SIZE // 2, CELL_SIZE // 2, 0, None)

    assert runner.controller.selected is None


def test_right_click_jump_request_also_respects_the_board_origin_offset():
    # The right-click/jump path shares the SAME injected
    # ScreenToImageMapper as the left-click path (see module
    # docstring's "CLICK OFFSET" section) - verified here through the
    # real on_mouse_event chain, not by calling _request_jump directly.
    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    runner = GameLoopRunner(board, window_name="TestJumpOffset", headless=True)

    window_x = runner._board_origin_x + CELL_SIZE // 2
    window_y = runner._board_origin_y + CELL_SIZE // 2
    runner.mouse_adapter.on_mouse_event(cv2.EVENT_RBUTTONDOWN, window_x, window_y, 0, None)

    assert runner.piece_animator_registry.animator_for(rook.id).current_state == AnimationState.JUMP


def test_sound_manager_is_subscribed_and_reacts_to_a_real_move_accepted_event(monkeypatch):
    # AudioPlayer.play is patched at the CLASS level (not an instance
    # attribute) so it intercepts every AudioPlayer instance -
    # including the one GameLoopRunner constructs internally - without
    # ever reaching the real winsound call underneath (see
    # test_audio_player.py for that layer's own, separate coverage).
    # This deliberately bypasses `enabled` entirely: this test verifies
    # SoundManager's real dispatch logic actually fires, independent of
    # whether headless mode would have suppressed real playback.
    played: list = []
    monkeypatch.setattr(AudioPlayer, "play", lambda self, path: played.append(path))

    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    runner = GameLoopRunner(board, window_name="TestSound", headless=True)
    played.clear()  # discard the game_start call already made at construction

    runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))

    assert played == [SOUND_PATHS["move"]]


def test_game_start_sound_plays_exactly_once_at_construction_not_per_frame(monkeypatch):
    played: list = []
    monkeypatch.setattr(AudioPlayer, "play", lambda self, path: played.append(path))

    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)

    runner = GameLoopRunner(board, window_name="TestGameStart", headless=True)

    assert played == [SOUND_PATHS["game_start"]]

    runner._run_one_frame(16)
    runner._run_one_frame(16)
    runner._run_one_frame(16)

    assert played.count(SOUND_PATHS["game_start"]) == 1  # still exactly once, not once per frame


def test_audio_player_is_disabled_in_headless_mode_so_no_real_playback_is_attempted(monkeypatch):
    # Unlike the two tests above (which patch AudioPlayer.play itself
    # to bypass `enabled`), this one verifies the `enabled` wiring
    # directly: headless=True must produce an AudioPlayer that would
    # decline to call winsound at all, even for a real event.
    import kungfu_chess.client.audio.audio_player as audio_player_module

    class _FailIfCalled:
        def PlaySound(self, *args, **kwargs):
            raise AssertionError("real winsound.PlaySound must never be called in headless mode")

    monkeypatch.setattr(audio_player_module, "_winsound", _FailIfCalled())

    grid = _empty_grid(3, 3)
    rook = _piece(Color.WHITE, PieceKind.ROOK, Position(row=0, col=0))
    grid[0][0] = rook
    board = Board(grid)
    runner = GameLoopRunner(board, window_name="TestHeadlessAudio", headless=True)

    runner.publisher.request_move(Position(row=0, col=0), Position(row=0, col=1))
    runner._run_one_frame(16)  # no AssertionError raised == success


def test_non_headless_construction_creates_a_real_window_when_a_display_is_available():
    # The one test that exercises the REAL, non-headless path (window
    # creation, mouse-callback attachment) at least once on a machine
    # that actually has a display - skipped rather than run on a
    # likely-headless one, per _display_available's own docstring.
    if not _display_available():
        pytest.skip("no display available in this environment")

    grid = _empty_grid(2, 2)
    king = _piece(Color.WHITE, PieceKind.KING, Position(row=0, col=0))
    grid[0][0] = king
    board = Board(grid)

    try:
        runner = GameLoopRunner(board, window_name="TestRealWindow", headless=False)
    except cv2.error as exc:
        pytest.skip(f"cv2 GUI backend unavailable in this environment: {exc}")

    try:
        assert runner._headless is False
        runner._run_one_frame(16)
    finally:
        cv2.destroyAllWindows()
