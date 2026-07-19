"""SoundManager: Observer protocol implementation (kungfu_chess/client/
events/event_publisher.py's Observer, Stage 3) that plays a short sound
for select published events - Stage 14.

SRP: this class only maps a received event to a sound key and calls
AudioPlayer.play() - it never decides game rules, computes score, or
maintains any log (those are ScoreObserver's/MovesLogObserver's own
jobs, kungfu_chess/client/events/observers.py) - the exact same
division of responsibility those two Observers already establish for
their own concerns.

DIP: constructed with an injected AudioPlayer (kungfu_chess/client/
audio/audio_player.py) - never constructs one itself, matching every
other Observer's own constructor-injection pattern in this codebase
(ScoreObserver/MovesLogObserver take an injected PieceRegistry;
CooldownTracker takes nothing extra because it needs nothing extra -
either way, DIP: never construct your own dependencies).

EVENT -> SOUND MAPPING (see SOUND_PATHS for the concrete key -> file
table):
- MoveAccepted -> "move"
- JumpAccepted -> "jump"
- PieceArrived WITH a real captured_piece_id -> "capture"
- PieceArrived WITHOUT a capture -> nothing. Deliberate: MoveAccepted
  already plays "move" the moment a move is REQUESTED and accepted -
  by the time the SAME piece's PieceArrived fires later (after its
  travel time), a second "move" sound for the identical logical move
  would just be a redundant echo of the same event, not new
  information. PieceArrived only adds a SECOND, DIFFERENT sound
  ("capture") on top, for the genuinely new fact a plain MoveAccepted
  could not have known yet (whether the destination cell had an enemy
  piece on it - the game only knows this at arrival, not at request
  time). Capture takes priority over "another move sound": a capture
  is a strictly more important event, so this class does not also
  separately play "move" again on the same PieceArrived.
- GameOver -> "game_over"
- PromotionEvent -> "promotion" (Stage 14 also adds this event itself,
  kungfu_chess/client/events/game_events.py - see that file's own
  docstring for why it did not exist before this stage).
- MoveRejected -> nothing. This project already established the
  "MoveRejected is not this Observer's concern" pattern for
  MovesLogObserver (kungfu_chess/client/events/observers.py's own
  docstring: "a rejected move never actually happened... there is
  nothing for a MOVE log to record") - the same reasoning applies
  identically here: nothing audible should happen for an action that
  never actually took place on the board, and a "rejection buzz" was
  not requested by this stage's own scope (client_spec.md's audio
  extension names successful actions and game-state changes, not
  input-validation feedback).

ERROR HANDLING: no new exception type is introduced here, and none is
needed - the same "match on the relevant types, ignore the rest"
isinstance pattern every other Observer in this codebase already uses
(OCP: a future event type this class has no reason to react to needs
zero changes here), and AudioPlayer.play() itself never raises (see
its own docstring) - there is no failure mode originating in this
class to guard against.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from kungfu_chess.client.animation.state_config import ASSETS_ROOT
from kungfu_chess.client.audio.audio_player import AudioPlayer
from kungfu_chess.client.events.game_events import (
    GameOver,
    JumpAccepted,
    MoveAccepted,
    PieceArrived,
    PromotionEvent,
)

SOUNDS_ROOT = ASSETS_ROOT / "sounds"

# name -> file path, the same "small, high-level constants table"
# pattern as score_table.py's PIECE_VALUES - not hardcoded inline in
# SoundManager itself.
SOUND_PATHS: Dict[str, Path] = {
    "move": SOUNDS_ROOT / "move.wav",
    "capture": SOUNDS_ROOT / "capture.wav",
    "jump": SOUNDS_ROOT / "jump.wav",
    "game_start": SOUNDS_ROOT / "game_start.wav",
    "game_over": SOUNDS_ROOT / "game_over.wav",
    "promotion": SOUNDS_ROOT / "promotion.wav",
}


class SoundManager:
    def __init__(self, audio_player: AudioPlayer) -> None:
        """audio_player is injected (DIP), not created or owned here -
        see module docstring."""

        self._audio_player = audio_player

    def on_event(self, event: object) -> None:
        """Play the sound, if any, for `event` - see module
        docstring's "EVENT -> SOUND MAPPING" section for the complete,
        documented table this implements.

        Args:
            event: Any published client-layer event.

        Returns:
            None.
        """

        if isinstance(event, MoveAccepted):
            self._play("move")
        elif isinstance(event, JumpAccepted):
            self._play("jump")
        elif isinstance(event, PieceArrived):
            if event.captured_piece_id is not None:
                self._play("capture")
        elif isinstance(event, GameOver):
            self._play("game_over")
        elif isinstance(event, PromotionEvent):
            self._play("promotion")

    def play_game_start(self) -> None:
        """Play the "game_start" cue - a public method, not routed
        through on_event, since game-start is not itself a published
        client-layer event (there is no GameStarted in game_events.py,
        and this stage does not add one - the composition root already
        knows unambiguously when a game starts, at its own
        construction, with no need for a whole event round-trip to
        learn a fact it already possesses). See GameLoopRunner's own
        docstring for exactly where and why this is called."""

        self._play("game_start")

    def _play(self, key: str) -> None:
        """Look up `key` in SOUND_PATHS and play it - the one place
        this class actually calls AudioPlayer.play(), so every
        dispatch method above shares the same lookup logic."""

        self._audio_player.play(SOUND_PATHS[key])
