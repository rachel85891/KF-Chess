from __future__ import annotations

from kungfu_chess.client.events.observers import CaptureLogEntry, MoveLogEntry, MovesLogSnapshot, ScoreSnapshot
from kungfu_chess.client.ui.hud_renderer import HudRenderer
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


class SpyImg:
    """A fake canvas recording draw_text calls only - HudRenderer never
    calls anything else on Img, so nothing more needs faking (same
    approach as Stage 6's test_img_surface.py)."""

    def __init__(self):
        self.text_calls: list[tuple] = []

    def draw_text(self, text, x, y, color=(0, 0, 0), font_scale=1.0, thickness=1):
        self.text_calls.append((text, x, y, color, font_scale, thickness))


def _move_entry(piece_color=Color.WHITE, piece_kind=PieceKind.ROOK, is_jump=False) -> MoveLogEntry:
    return MoveLogEntry(
        piece_kind=piece_kind,
        piece_color=piece_color,
        from_cell=Position(row=1, col=0),
        to_cell=Position(row=1, col=4),
        is_jump=is_jump,
    )


def _capture_entry() -> CaptureLogEntry:
    return CaptureLogEntry(
        piece_kind=PieceKind.ROOK,
        piece_color=Color.WHITE,
        cell=Position(row=1, col=4),
        captured_piece_kind=PieceKind.PAWN,
        captured_piece_color=Color.BLACK,
    )


def test_render_draws_score_text_with_both_colors():
    canvas = SpyImg()
    renderer = HudRenderer(canvas)
    score = ScoreSnapshot(score_by_color={Color.WHITE: 3, Color.BLACK: 5})

    renderer.render(score, MovesLogSnapshot(entries=()))

    score_calls = [call for call in canvas.text_calls if "White" in call[0] and "Black" in call[0]]
    assert len(score_calls) == 1
    assert score_calls[0][0] == "White: 3  Black: 5"


def test_render_move_log_entry_and_capture_log_entry_produce_distinct_text():
    canvas = SpyImg()
    renderer = HudRenderer(canvas)
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
    log = MovesLogSnapshot(entries=(_move_entry(), _capture_entry()))

    renderer.render(score, log)

    log_texts = [call[0] for call in canvas.text_calls if "White Rook" in call[0]]
    assert log_texts == [
        "White Rook: (1,0)->(1,4)",
        "White Rook captured Black Pawn at (1,4)",
    ]


def test_render_jump_entry_is_marked_distinctly_from_a_plain_move():
    canvas = SpyImg()
    renderer = HudRenderer(canvas)
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
    log = MovesLogSnapshot(entries=(_move_entry(is_jump=True),))

    renderer.render(score, log)

    log_texts = [call[0] for call in canvas.text_calls if "Rook" in call[0]]
    assert log_texts == ["White Rook (jump): (1,0)->(1,4)"]


def test_render_only_draws_the_most_recent_five_log_entries():
    canvas = SpyImg()
    renderer = HudRenderer(canvas)
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})
    entries = tuple(
        MoveLogEntry(
            piece_kind=PieceKind.PAWN,
            piece_color=Color.WHITE,
            from_cell=Position(row=0, col=i),
            to_cell=Position(row=1, col=i),
            is_jump=False,
        )
        for i in range(8)
    )
    log = MovesLogSnapshot(entries=entries)

    renderer.render(score, log)

    log_texts = [call[0] for call in canvas.text_calls if "Pawn" in call[0]]
    assert len(log_texts) == 5
    # entries 3..7 are the most recent 5 (not the oldest, not all 8)
    assert log_texts == [f"White Pawn: (0,{i})->(1,{i})" for i in range(3, 8)]


def test_render_does_not_raise_for_empty_log_and_zero_score():
    canvas = SpyImg()
    renderer = HudRenderer(canvas)
    score = ScoreSnapshot(score_by_color={Color.WHITE: 0, Color.BLACK: 0})

    renderer.render(score, MovesLogSnapshot(entries=()))  # no exception == success

    assert len(canvas.text_calls) == 1  # score line only, no log lines
