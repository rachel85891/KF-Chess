"""generate_sound_assets: a one-time, DEV-ONLY generator that
synthesizes assets/sounds/<name>.wav from scratch - pure stdlib (wave
+ struct + math), no external downloads, no copyright concerns (every
tone is a synthesized sine wave, not sourced audio).

NOT run automatically by any runtime path (re-check via `grep -r
generate_sound_assets kungfu_chess/client` before relying on this
claim - nothing under kungfu_chess/client/ imports this module).
Matches this project's own established "generate/vendor once, commit
the result" precedent from assets/README.md's own asset-vendoring
history: run this script once, by hand, commit the resulting .wav
files, and never run it again unless deliberately regenerating them.

Lives under kungfu_chess/tools/, not scripts/: this repo's scripts/
directory is documented (via its own existing contents,
scripts/demo_stage6_render_board.py etc.) as manual, human-run DEMOS
of runtime behavior - this is a one-shot BUILD-TIME asset generator
with no game-loop/rendering behavior to demo, a different kind of tool
entirely, so it gets its own new directory rather than being folded
into an existing one that means something else.

TONE DESIGN (per the project owner's own "a tone and color, not
something that takes over" requirement - kept short and quiet, not
alarming): every tone is a low-amplitude (AMPLITUDE below), short
(150-400ms) sine wave or short sequence of sine segments, each
generated with a linear fade-in/fade-out envelope (_ENVELOPE_MS) so no
segment starts or ends with an audible click (a raw, un-enveloped sine
wave beginning/ending mid-cycle produces a sharp waveform discontinuity
- an audible "pop" - a well-known synthesis artifact, avoided here by
ramping amplitude linearly up/down over the first/last few
milliseconds of every segment instead of jumping straight to/from full
volume).

- move: one short, mid-pitch tone (A4/440Hz) - the plainest, most
  neutral sound, for the single most frequent event.
- capture: one short tone, one octave LOWER than move (A3/220Hz) and
  enveloped with a much shorter fade (more percussive/"sharper"
  attack-decay than move's gentler fade) - distinguishable from a
  plain move by ear on pitch alone, with a punchier envelope shape
  reinforcing "something was taken", not just "something moved".
- jump: a rising frequency SWEEP (300Hz -> 700Hz), not a fixed tone -
  the one sound in this set that actually changes pitch DURING
  playback, so "rising" is literal, not just a higher fixed note than
  move.
- game_start: two short ascending notes back-to-back (C5 -> E5) - a
  brief "ready" cue, distinct in shape (two discrete notes) from every
  other single-tone/sweep sound here.
- game_over: three notes, descending then settling on the lowest/
  "home" note (E5 -> C5 -> C4) - a slightly longer, "resolving" cue:
  ending on a lower, stable note reads as a conclusion, the opposite
  shape from game_start's rising cue.
- promotion: three short ascending notes (C5 -> E5 -> G5, a major
  triad outline) - distinguishable from jump's smooth continuous sweep
  (discrete stepped notes, not a glide) and from game_start's two-note
  cue (three notes, different interval pattern) - a small "reward"
  flourish for the rarer, more special event.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import List, Tuple

SOUNDS_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "sounds"

SAMPLE_RATE_HZ = 44100
AMPLITUDE = 0.25 * 32767  # quiet, not alarming - see module docstring
_ENVELOPE_MS = 8  # gentle fade-in/fade-out, per segment, to avoid clicks

# Note frequencies (Hz) - standard equal-tempered pitches, named for
# readability in the per-sound definitions below.
C4, A3 = 261.63, 220.0
A4, C5, E5, G5 = 440.0, 523.25, 659.25, 783.99


def _tone_segment(frequency_hz: float, duration_ms: int, envelope_ms: int = _ENVELOPE_MS) -> List[int]:
    """One enveloped sine-wave segment, as signed 16-bit sample values.

    Args:
        frequency_hz: The (fixed) pitch of this segment.
        duration_ms: How long this segment lasts.
        envelope_ms: Fade-in/fade-out length in ms (see module
            docstring's "TONE DESIGN" note for why this exists at all -
            shorter here than the default for capture's punchier
            attack).

    Returns:
        A list of int sample values, one per audio frame at
        SAMPLE_RATE_HZ, ready to be packed into a WAV file.
    """

    total_samples = int(SAMPLE_RATE_HZ * duration_ms / 1000)
    envelope_samples = min(int(SAMPLE_RATE_HZ * envelope_ms / 1000), total_samples // 2)

    samples = []
    for i in range(total_samples):
        angle = 2 * math.pi * frequency_hz * (i / SAMPLE_RATE_HZ)
        value = math.sin(angle)

        if i < envelope_samples:
            value *= i / envelope_samples
        elif i >= total_samples - envelope_samples:
            value *= (total_samples - i) / envelope_samples

        samples.append(int(value * AMPLITUDE))
    return samples


def _sweep_segment(start_hz: float, end_hz: float, duration_ms: int, envelope_ms: int = _ENVELOPE_MS) -> List[int]:
    """One enveloped linear frequency sweep ("chirp") - jump.wav's own
    "rising pitch" is this, not a fixed tone (see module docstring).

    The instantaneous frequency changes linearly from start_hz to
    end_hz over the segment; the sample's phase is therefore the
    INTEGRAL of that linearly-changing frequency over time (a plain
    `sin(2*pi*f(t)*t)` would be mathematically wrong for a
    time-varying f - it would not actually produce a linear sweep),
    not a simple per-sample frequency substitution.
    """

    total_samples = int(SAMPLE_RATE_HZ * duration_ms / 1000)
    envelope_samples = min(int(SAMPLE_RATE_HZ * envelope_ms / 1000), total_samples // 2)
    duration_s = duration_ms / 1000
    slope_hz_per_s = (end_hz - start_hz) / duration_s

    samples = []
    for i in range(total_samples):
        t = i / SAMPLE_RATE_HZ
        instantaneous_phase = 2 * math.pi * (start_hz * t + 0.5 * slope_hz_per_s * t * t)
        value = math.sin(instantaneous_phase)

        if i < envelope_samples:
            value *= i / envelope_samples
        elif i >= total_samples - envelope_samples:
            value *= (total_samples - i) / envelope_samples

        samples.append(int(value * AMPLITUDE))
    return samples


def _write_wav(path: Path, samples: List[int]) -> None:
    """Write `samples` (signed 16-bit, mono) to `path` as a standard
    PCM WAV file, using only the stdlib `wave` module."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(SAMPLE_RATE_HZ)
        wav_file.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))


# name -> the sequence of (frequency_or_sweep, duration_ms) segments
# concatenated to build that sound - see module docstring's "TONE
# DESIGN" section for the reasoning behind every one of these choices.
_TONE_SOUNDS = {
    "move": [(A4, 150)],
    "capture": [(A3, 150)],
    "game_start": [(C5, 110), (E5, 140)],
    "game_over": [(E5, 130), (C5, 130), (C4, 140)],
    "promotion": [(C5, 80), (E5, 80), (G5, 90)],
}
_SWEEP_SOUNDS: dict[str, Tuple[float, float, int]] = {
    "jump": (300.0, 700.0, 200),
}


def generate_all() -> List[Path]:
    """Generate every sound in _TONE_SOUNDS/_SWEEP_SOUNDS to
    SOUNDS_DIR, overwriting any existing file of the same name.

    Returns:
        The list of Paths written, in a stable (sorted-by-name) order
        - useful for a caller (e.g. this module's own __main__ block)
        that wants to report exactly what was produced.
    """

    written: List[Path] = []

    for name, segments in _TONE_SOUNDS.items():
        # capture gets a shorter envelope than the rest (see module
        # docstring's "punchier attack" reasoning) - every other tone
        # segment uses the default.
        envelope_ms = 3 if name == "capture" else _ENVELOPE_MS
        samples: List[int] = []
        for frequency_hz, duration_ms in segments:
            samples.extend(_tone_segment(frequency_hz, duration_ms, envelope_ms))
        path = SOUNDS_DIR / f"{name}.wav"
        _write_wav(path, samples)
        written.append(path)

    for name, (start_hz, end_hz, duration_ms) in _SWEEP_SOUNDS.items():
        samples = _sweep_segment(start_hz, end_hz, duration_ms)
        path = SOUNDS_DIR / f"{name}.wav"
        _write_wav(path, samples)
        written.append(path)

    return sorted(written)


if __name__ == "__main__":
    for generated_path in generate_all():
        print(f"wrote {generated_path}")
