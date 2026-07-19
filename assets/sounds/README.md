# Sound Assets

This directory's 7 `.wav` files have TWO different provenances - do
not treat them as a uniform set, and do not regenerate all of them
with `kungfu_chess/tools/generate_sound_assets.py` without noticing
the mismatch that would cause:

- **Generated (synthesized sine-wave tones)** - `jump.wav`,
  `game_start.wav`. Produced by `kungfu_chess/tools/
  generate_sound_assets.py` (Stage 14) - pure stdlib, no external
  source, no copyright concerns. Re-running that script regenerates
  ONLY these two (see its own `_TONE_SOUNDS`/`_SWEEP_SOUNDS` tables -
  it was never extended to cover the 5 below, and should not be,
  without first re-reading this note).
- **Person-provided (real recorded/produced audio)** - `move.wav`,
  `capture.wav`, `promotion.wav`, `game_over.wav`, `illegal_move.wav`.
  Supplied directly by the project owner (Stage 15), replacing Stage
  14's originally-generated tones for these same four names (plus
  `illegal_move.wav`, new - Stage 14 had no sound for a rejected move
  at all). All five: stereo, 44.1kHz, 16-bit PCM. Exact durations at
  the time they were vendored (Stage 15) - re-verify directly
  (`wave.open(path).getnframes() / getframerate()`) if this note and
  the actual files ever drift apart:
  - `move.wav` - 2000.0ms
  - `capture.wav` - 2000.0ms
  - `promotion.wav` - 1718.3ms
  - `game_over.wav` - 5375.4ms
  - `illegal_move.wav` - 2000.0ms

  **Flagged, not silently fixed (Stage 15):** `move.wav` is a full 2
  seconds, and a move is one of the most frequent events this project's
  real-time loop can trigger (potentially every accepted move, from
  either player, with no cooldown on the SOUND itself even though
  pieces have their own move cooldown). Two consecutive moves within
  that 2-second window would have their `move.wav` playback overlap,
  which could read as "always playing" - in tension with the project
  owner's own "a tone and color, not something that takes over" design
  goal for this whole feature (Stage 14). Not trimmed here since that
  would mean editing person-provided audio without being asked to -
  left as an explicit, flagged decision for the project owner to make
  as a deliberate follow-up, not something a future stage should
  silently "fix" either.

See `kungfu_chess/client/audio/sound_manager.py`'s own `SOUND_PATHS`
for the name -> file mapping, and that file's module docstring for the
full event -> sound trigger table.
