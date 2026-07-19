from __future__ import annotations

from kungfu_chess.client.events.observers import CaptureLogEntry, MoveLogEntry, MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.client.ui.side_panel_renderer import (
    PANEL_BACKGROUND_COLOR,
    PANEL_BORDER_COLOR,
    PANEL_WIDTH,
    SidePanelRenderer,
    TITLE_BOX_BORDER_COLOR,
)
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


class SpyImg:
    """A fake canvas recording draw_rectangle/draw_text calls only -
    the same black-box-canvas approach as this suite's other renderer
    tests (test_cooldown_overlay_renderer.py/test_img_surface.py): no
    real cv2/window involved."""

    def __init__(self, height: int = 800):
        self._height = height
        self.rectangle_calls: list[tuple] = []
        self.text_calls: list[tuple] = []

    @property
    def height(self) -> int:
        return self._height

    def draw_rectangle(self, x, y, width, height, color, thickness=-1):
        self.rectangle_calls.append((x, y, width, height, color, thickness))

    def draw_text(self, text, x, y, color=(0, 0, 0), font_scale=1.0, thickness=1):
        self.text_calls.append((text, x, y, color, font_scale, thickness))


def _white_move_entry(to_col: int, recorded_at_clock_ms: int = 0) -> MoveLogEntry:
    return MoveLogEntry(
        piece_kind=PieceKind.QUEEN,
        piece_color=Color.WHITE,
        from_cell=Position(row=0, col=0),
        to_cell=Position(row=0, col=to_col),
        is_jump=False,
        recorded_at_clock_ms=recorded_at_clock_ms,
    )


def _black_capture_entry(recorded_at_clock_ms: int = 0) -> CaptureLogEntry:
    return CaptureLogEntry(
        piece_kind=PieceKind.ROOK,
        piece_color=Color.BLACK,
        cell=Position(row=3, col=3),
        captured_piece_kind=PieceKind.PAWN,
        captured_piece_color=Color.WHITE,
        recorded_at_clock_ms=recorded_at_clock_ms,
    )


def test_panel_only_shows_that_colors_log_entries():
    canvas = SpyImg()
    log = MovesLogSnapshot(entries=(_white_move_entry(to_col=3), _black_capture_entry()))
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 1})

    SidePanelRenderer(canvas).render(x=0, width=PANEL_WIDTH, color=Color.WHITE, score=score, log=log)

    move_row_texts = [call[0] for call in canvas.text_calls if "->(" in call[0]]
    capture_row_texts = [call[0] for call in canvas.text_calls if "x" in call[0] and "->(" not in call[0]]
    assert len(move_row_texts) == 1
    assert capture_row_texts == []


def test_panel_shows_blacks_entries_when_rendered_for_black():
    canvas = SpyImg()
    log = MovesLogSnapshot(entries=(_white_move_entry(to_col=3), _black_capture_entry()))
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 1})

    SidePanelRenderer(canvas).render(x=0, width=PANEL_WIDTH, color=Color.BLACK, score=score, log=log)

    move_row_texts = [call[0] for call in canvas.text_calls if "->(" in call[0]]
    capture_row_texts = [call[0] for call in canvas.text_calls if call[0].startswith("Rx")]
    assert move_row_texts == []
    assert len(capture_row_texts) == 1


def test_score_text_matches_score_snapshot():
    canvas = SpyImg()
    log = MovesLogSnapshot(entries=())
    score = ScoreSnapshot(score_by_color={Color.WHITE: 7, Color.BLACK: 2})

    SidePanelRenderer(canvas).render(x=0, width=PANEL_WIDTH, color=Color.WHITE, score=score, log=log)

    score_texts = [call[0] for call in canvas.text_calls if call[0].startswith("Score:")]
    assert score_texts == ["Score: 7"]


def test_border_and_background_are_drawn_for_the_whole_panel_and_the_title_box():
    canvas = SpyImg()
    log = MovesLogSnapshot(entries=())
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    SidePanelRenderer(canvas).render(x=0, width=PANEL_WIDTH, color=Color.WHITE, score=score, log=log)

    background_calls = [call for call in canvas.rectangle_calls if call[4] == PANEL_BACKGROUND_COLOR]
    border_calls = [call for call in canvas.rectangle_calls if call[4] == PANEL_BORDER_COLOR]
    title_box_calls = [call for call in canvas.rectangle_calls if call[4] == TITLE_BOX_BORDER_COLOR]
    assert len(background_calls) == 1
    assert len(border_calls) == 1
    assert len(title_box_calls) == 1
    assert border_calls[0][5] > 0  # outline, not filled
    assert title_box_calls[0][5] > 0


def test_panel_respects_its_given_x_and_width_region():
    canvas = SpyImg(height=640)
    log = MovesLogSnapshot(entries=())
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    SidePanelRenderer(canvas).render(x=580, width=PANEL_WIDTH, color=Color.WHITE, score=score, log=log)

    background_call = next(call for call in canvas.rectangle_calls if call[4] == PANEL_BACKGROUND_COLOR)
    x, y, width, height, _color, _thickness = background_call
    assert x == 580
    assert y == 0
    assert width == PANEL_WIDTH
    assert height == 640  # full canvas height, per the LAYOUT CONTRACT


def test_player_name_label_is_drawn_inside_the_title_box():
    canvas = SpyImg()
    log = MovesLogSnapshot(entries=())
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    SidePanelRenderer(canvas).render(x=0, width=PANEL_WIDTH, color=Color.BLACK, score=score, log=log)

    names = [call[0] for call in canvas.text_calls]
    assert "Black" in names


def test_table_rows_are_capped_at_panel_max_log_rows():
    canvas = SpyImg()
    entries = tuple(_white_move_entry(to_col=i % 8) for i in range(20))
    log = MovesLogSnapshot(entries=entries)
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    SidePanelRenderer(canvas).render(x=0, width=PANEL_WIDTH, color=Color.WHITE, score=score, log=log)

    move_row_texts = [call[0] for call in canvas.text_calls if "->(" in call[0]]
    assert len(move_row_texts) == 8  # PANEL_MAX_LOG_ROWS
