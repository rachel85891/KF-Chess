from __future__ import annotations

from pathlib import Path

import kungfu_chess.client.audio.audio_player as audio_player_module
from kungfu_chess.client.audio.audio_player import AudioPlayer


class FakeWinsound:
    """A spy standing in for the real winsound module - real winsound
    calls a real OS-level audio backend, which this suite must never
    touch (the same "never touch a real OS-level backend in tests"
    convention Stage 10c's headless cv2 approach already established
    for this codebase)."""

    SND_ASYNC = 1
    SND_FILENAME = 131072
    SND_NODEFAULT = 2

    def __init__(self):
        self.calls: list[tuple] = []

    def PlaySound(self, sound, flags):
        self.calls.append((sound, flags))


def test_play_calls_winsound_playsound_with_async_filename_and_nodefault_flags(monkeypatch):
    fake = FakeWinsound()
    monkeypatch.setattr(audio_player_module, "_winsound", fake)
    player = AudioPlayer()

    player.play(Path("some/sound.wav"))

    assert len(fake.calls) == 1
    sound, flags = fake.calls[0]
    assert sound == str(Path("some/sound.wav"))
    # SND_ASYNC is critical (non-blocking - see module docstring's own
    # verification of this), SND_FILENAME says `sound` is a path (not
    # raw audio data or a registry alias), SND_NODEFAULT suppresses the
    # Windows default-beep fallback for a missing file (see module
    # docstring's own reasoning for why).
    assert flags == fake.SND_ASYNC | fake.SND_FILENAME | fake.SND_NODEFAULT


def test_play_is_a_no_op_when_disabled(monkeypatch):
    fake = FakeWinsound()
    monkeypatch.setattr(audio_player_module, "_winsound", fake)
    player = AudioPlayer(enabled=False)

    player.play(Path("some/sound.wav"))

    assert fake.calls == []


def test_play_degrades_safely_when_winsound_is_unavailable(monkeypatch):
    # Simulates the real non-Windows condition directly: `_winsound`
    # module-level name is None exactly when `import winsound` raised
    # ImportError at module load (see audio_player.py's own try/except).
    monkeypatch.setattr(audio_player_module, "_winsound", None)
    player = AudioPlayer()

    player.play(Path("some/sound.wav"))  # no exception == success


def test_play_with_winsound_unavailable_and_disabled_is_still_a_no_op(monkeypatch):
    monkeypatch.setattr(audio_player_module, "_winsound", None)
    player = AudioPlayer(enabled=False)

    player.play(Path("some/sound.wav"))  # no exception == success
