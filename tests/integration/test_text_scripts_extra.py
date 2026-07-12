"""Drives tests/integration/scripts_extra/*.kfc through app_extra.py's
run_extra (core + JUMP + Promotion), same fixture format as
test_text_scripts.py. These 4 fixtures were migrated here from the
retired tests/characterization/test_golden_master.py's golden-master
suite (tests/fixtures/*.txt + tests/golden/*.txt, captured from the
original pre-refactor engine) - they need jump/promotion, which the
pure core DSL (tests/integration/scripts/*.kfc,
test_text_scripts.py) deliberately excludes, so they live in a
parallel extras suite instead of diluting the core one.

Two golden-master fixtures were deliberately NOT migrated:

- instant_king_capture.txt exercised the legacy engine's "instant royal
  capture" shortcut - a click-click pair that captured a king mutated
  the board immediately, with no transit delay, even with no `wait` in
  between. This directly contradicts spec.md §10 ("the board changes
  only after a moving piece has actually reached its destination") -
  the new RealTimeArbiter correctly refuses to reproduce it; a king
  capture always takes the full N*1000ms transit like any other move,
  in every part of the new architecture (core or extras). This is a
  deliberate, spec-mandated behavior change, not a coverage gap: the
  old shortcut was itself the spec violation.

- three_way_tie_moves_before_landings.txt depended on two SAME-COLOR
  pieces both having in-flight motions at once (a rook and a bishop,
  both white) - the new GameEngine's system-wide motion_in_progress
  guard (spec.md §2: only one motion at a time, no per-color
  exception - the same, already-approved behavior change from the
  GameEngine step) rejects the second piece's move outright, so it
  never has a motion to be intercepted in the first place. The
  fixture's own scenario is fundamentally unreproducible under the new
  engine, independent of anything about jump's own interception logic
  (which was verified separately, and correctly, via
  air_capture_before_landing.kfc).
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from app_extra import run_extra

SCRIPTS_DIR = Path(__file__).parent / "scripts_extra"
FIXTURE_PATHS = sorted(SCRIPTS_DIR.glob("*.kfc"))


def _split_fixture(text: str) -> tuple[list[str], str]:
    script_part, _, expected_part = text.partition("\nEXPECTED:\n")
    return script_part.splitlines(), expected_part.rstrip("\n")


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda p: p.name)
def test_extra_fixture_script_produces_expected_output(fixture_path):
    script_lines, expected_output = _split_fixture(fixture_path.read_text())

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        run_extra(script_lines)

    assert buffer.getvalue().rstrip("\n") == expected_output
