"""AssetCache: loads and caches sprite/image files from assets/, per
client_spec.md §3's component table ("AssetCache | Loads and caches
sprites/images from `assets/` | filesystem, `Img`").

SRP: this class only loads and caches Img instances by path - it has
no knowledge of Kung Fu Chess domain concepts (pieces, board, cells,
AnimationState). ImgSurface (img_surface.py) is the only consumer that
maps a domain concept (a piece's kind+color+state) to a Path before
ever calling get() here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from kungfu_chess.client.surface.img import Img


class AssetCache:
    """Path -> Img cache: the same sprite file is loaded from disk at
    most once per AssetCache instance's lifetime, no matter how many
    times get() is called for it (client_spec.md §4's ~30 FPS loop
    would otherwise re-read the same PNG bytes from disk dozens of
    times a second for every visible piece)."""

    def __init__(self) -> None:
        """Create an empty cache.

        Returns:
            None.
        """

        self._cache: Dict[str, Img] = {}

    def get(self, path: Path) -> Img:
        """Return the Img for `path`, loading and caching it on first
        request.

        Args:
            path: Filesystem path to an image file.

        Returns:
            The loaded Img - the SAME instance on every subsequent
            call for the same resolved path, so callers must treat it
            as read-only (Img.paste() never mutates its `sprite`
            argument, only the canvas it's called on, so this is safe
            for the intended "paste this cached sprite onto many
            different canvases/positions" usage).

        Raises:
            ImageLoadError: Propagated as-is from Img.load if `path`
                does not exist or cannot be decoded - not wrapped in a
                second, AssetCache-specific exception type, since
                Img.load's own message already names the exact path
                AssetCache was asked to load; wrapping it would only
                add a redundant type without adding information.

        Cached by the resolved (absolute) path string, not the raw
        Path as given - two different-looking but equivalent paths to
        the same file (e.g. relative vs. absolute) must share one
        cache entry, not silently load and hold the same bytes twice.
        """

        key = str(path.resolve())
        if key not in self._cache:
            self._cache[key] = Img.load(path)
        return self._cache[key]
