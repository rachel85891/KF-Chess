from __future__ import annotations

from pathlib import Path

from kungfu_chess.client.audio.sound_manager import SOUND_PATHS, SoundManager
from kungfu_chess.client.events.game_events import (
    GameOver,
    JumpAccepted,
    MoveAccepted,
    MoveRejected,
    PieceArrived,
    PromotionEvent,
)
from kungfu_chess.model.color import Color
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.position import Position


class FakeAudioPlayer:
    """A fake standing in for AudioPlayer - records which paths were
    "played", with no real winsound/OS-backend call involved (SRP:
    this test suite verifies SoundManager's own event -> sound
    dispatch logic, not AudioPlayer's own playback mechanics, which
    test_audio_player.py already covers on its own)."""

    def __init__(self):
        self.played: list[Path] = []

    def play(self, path: Path) -> None:
        self.played.append(path)


def test_move_accepted_plays_the_move_sound():
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(
        MoveAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )

    assert audio.played == [SOUND_PATHS["move"]]


def test_jump_accepted_plays_the_jump_sound():
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(
        JumpAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=0), duration_ms=625)
    )

    assert audio.played == [SOUND_PATHS["jump"]]


def test_piece_arrived_with_a_capture_plays_the_capture_sound():
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(PieceArrived(piece_id=1, cell=Position(row=0, col=1), captured_piece_id=2))

    assert audio.played == [SOUND_PATHS["capture"]]


def test_piece_arrived_without_a_capture_plays_nothing():
    # See sound_manager.py's own "EVENT -> SOUND MAPPING" docstring:
    # MoveAccepted already covered "a move happened" when the move was
    # requested - a plain arrival with no capture is not new
    # information worth a second sound.
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(PieceArrived(piece_id=1, cell=Position(row=0, col=1), captured_piece_id=None))

    assert audio.played == []


def test_a_move_followed_by_its_own_capturing_arrival_plays_move_then_capture_not_a_second_move():
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(
        MoveAccepted(piece_id=1, from_cell=Position(row=0, col=0), to_cell=Position(row=0, col=1), duration_ms=1000)
    )
    manager.on_event(PieceArrived(piece_id=1, cell=Position(row=0, col=1), captured_piece_id=2))

    assert audio.played == [SOUND_PATHS["move"], SOUND_PATHS["capture"]]


def test_game_over_plays_the_game_over_sound():
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(GameOver(winner_color=Color.WHITE))

    assert audio.played == [SOUND_PATHS["game_over"]]


def test_promotion_event_plays_the_promotion_sound():
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(PromotionEvent(piece_id=1, cell=Position(row=0, col=0), new_kind=PieceKind.QUEEN))

    assert audio.played == [SOUND_PATHS["promotion"]]


def test_move_rejected_plays_the_illegal_move_sound():
    # Stage 15 - REVERSED from Stage 14's original "plays nothing"
    # behavior: see sound_manager.py's own updated docstring for why
    # (an illegal_move.wav asset now exists - that is what actually
    # changed, not the underlying reasoning).
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.on_event(MoveRejected(reason="cooldown_active"))

    assert audio.played == [SOUND_PATHS["illegal_move"]]


def test_play_game_start_plays_the_game_start_sound():
    audio = FakeAudioPlayer()
    manager = SoundManager(audio)

    manager.play_game_start()

    assert audio.played == [SOUND_PATHS["game_start"]]
