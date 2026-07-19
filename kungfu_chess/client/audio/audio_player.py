"""AudioPlayer: plays a WAV file by path, per this project's Stage 14
sound-effects extension.

SRP: this class only knows how to play a sound file - it never decides
WHICH sound to play for which game event (SoundManager's job,
kungfu_chess/client/audio/sound_manager.py) and has no knowledge of
game/event logic at all, matching Img's own "generic primitive, no
domain knowledge" boundary (kungfu_chess/client/surface/img.py).

WINDOWS-ONLY, DEGRADES SAFELY ELSEWHERE: winsound is stdlib on Windows
only - `import winsound` raises ImportError on any other platform
(confirmed directly: Python's own winsound docs describe it as a
Windows-specific module; there is no cross-platform stdlib equivalent
this project could fall back to instead). Sound is an enhancement, not
core functionality - the same "degrade safely rather than crash the
whole application over an optional feature" precedent this codebase
already established for Img.draw_text/draw_rectangle silently clipping
out-of-bounds input rather than raising (img_surface.py's own
ERROR HANDLING sections, Stage 9/12). The import is attempted exactly
once, at module load, inside a try/except; if it fails, `_winsound`
stays None and play() becomes a documented no-op instead of ever
raising - the rest of the application keeps working identically on a
platform without winsound, just silently, with no sound.

ASYNC, NON-BLOCKING (critical for this class's real caller -
GameLoopRunner's real-time ~30 FPS loop; a BLOCKING play() call would
freeze rendering/input for as long as the sound lasts) - verified two
ways before relying on it, not assumed:
1. Documented: winsound's own module docstring (`import winsound;
   print(winsound.__doc__)`, re-checked directly) states plainly
   "SND_ASYNC - PlaySound returns immediately", as opposed to
   "SND_SYNC - Play the sound synchronously, default behavior."
2. Empirically: timed a real `PlaySound(path, SND_ASYNC |
   SND_FILENAME)` call against this project's own longest generated
   tone (assets/sounds/game_over.wav, 400ms, kungfu_chess/tools/
   generate_sound_assets.py) - the call returned in ~8ms, not ~400ms.
Both agree: SND_ASYNC does not block the calling thread for the
sound's own playback duration.
"""

from __future__ import annotations

from pathlib import Path

try:
    import winsound as _winsound
except ImportError:
    _winsound = None


class AudioPlayer:
    """Plays a WAV file asynchronously via winsound (Windows), or is a
    safe no-op everywhere else (see module docstring)."""

    def __init__(self, enabled: bool = True) -> None:
        """Args:
            enabled: If False, play() becomes a no-op regardless of
                platform - a general mute switch, defaulting to True
                (real playback). This class stays completely
                game/headless-agnostic on purpose: `enabled` is a
                plain, reusable on/off flag (independently useful for
                e.g. a future settings/mute-button feature too), not a
                "headless" concept baked into this class. GameLoopRunner
                is the one place that actually decides WHEN to pass
                False (constructing AudioPlayer(enabled=not headless)) -
                matching Stage 10c's established pattern of keeping
                "headless" itself a composition-root wiring decision
                that sub-components never need to know the meaning of
                (Img/ImgSurface never gained a headless concept either;
                GameLoopRunner simply skips calling their own
                screen-touching methods directly in headless mode). See
                GameLoopRunner's own docstring for exactly why this
                matters: without this, every headless test that
                triggers a real event (most of this suite) would
                attempt a real OS-level winsound call.

        Returns:
            None.
        """

        self._enabled = enabled

    def play(self, path: Path) -> None:
        """Play the WAV file at `path` without blocking the caller.

        Args:
            path: Filesystem path to a .wav file.

        Returns:
            None.

        A no-op (not an error) on any platform where winsound is
        unavailable (see module docstring's WINDOWS-ONLY section) -
        sound is an optional enhancement, and running on a different
        platform is not a caller mistake worth raising about.

        SND_NODEFAULT is included deliberately: without it, a missing
        or unreadable `path` makes winsound.PlaySound fall back to
        Windows's own default system beep/sound instead - re-verified
        directly (a real call with a nonexistent path, SND_NODEFAULT
        included, returned None with no exception and no sound at
        all). A jarring, unrelated fallback beep would be MORE
        noticeable/intrusive than the intended tone ever would have
        been - the opposite of this feature's own "a tone and color,
        not something that takes over" design goal - so a missing
        sound file is made to fail silently here, not audibly.
        """

        if not self._enabled or _winsound is None:
            return

        _winsound.PlaySound(str(path), _winsound.SND_ASYNC | _winsound.SND_FILENAME | _winsound.SND_NODEFAULT)
