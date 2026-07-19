# Vendored Assets

Source: https://github.com/KamaTechOrg/CTD26.git
Commit: caef11a0bfa31f7dbb91b30188c03cc759c927c9

Originally, only the `pieces2/` graphics set was imported (renamed here
to `pieces/`), not `pieces1/`: `pieces2` is ~2MB vs. ~6MB for
`pieces1`, and its `config.json` structure is the one already verified
against `docs/client_spec.md` §5/§11. No Java/C++/Python source or
CTD26 docs were copied — this directory holds static image/config data
only, and CTD26 itself is not a dependency of this project (no
submodule, no requirements entry).

**Update:** `pieces/` was later replaced with a newer sprite set
(originally staged under `assets/new_pieces/`, never committed to git
under that name). Its `<KIND><COLOR>/states/<state>/{config.json,
sprites/}` layout and `config.json` schema already matched exactly, so
no structural changes were needed — but its sprite PNGs were 320x320,
more than 3x `CELL_SIZE` (100, `kungfu_chess/realtime/
real_time_arbiter.py`), which `Img.paste()` never resizes: pasted at
native resolution, this overflowed neighboring cells and raised
`PasteOutOfBoundsError` for any piece near the board edge. Every sprite
was resized in place to 64x64 (matching the original `pieces2` set's
own working size exactly, via `cv2.INTER_AREA` for the downscale) to
restore compatibility with the existing paste/positioning pipeline
before the swap.

Layout: `pieces/<KIND><COLOR>/states/<state>/{config.json, sprites/}`,
plus `board.png`.
