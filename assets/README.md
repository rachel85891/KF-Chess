# Vendored Assets

Source: https://github.com/KamaTechOrg/CTD26.git
Commit: caef11a0bfa31f7dbb91b30188c03cc759c927c9

Only the `pieces2/` graphics set was imported (renamed here to
`pieces/`), not `pieces1/`: `pieces2` is ~2MB vs. ~6MB for `pieces1`,
and its `config.json` structure is the one already verified against
`docs/client_spec.md` §5/§11. No Java/C++/Python source or CTD26 docs
were copied — this directory holds static image/config data only, and
CTD26 itself is not a dependency of this project (no submodule, no
requirements entry).

Layout: `pieces/<KIND><COLOR>/states/<state>/{config.json, sprites/}`,
plus `board.png`.
