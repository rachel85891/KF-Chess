"""Drives every fixture under tests/integration/scripts/*.kfc through
ScriptRunner and compares captured stdout against each fixture's
expected output. Each .kfc fixture is a plain text file: a
Board:/Commands: script (the exact stdin format ScriptRunner expects),
followed by an "EXPECTED:" marker line, followed by the exact expected
stdout.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

from kungfu_chess.texttests.script_runner import ScriptRunner

SCRIPTS_DIR = Path(__file__).parent / "scripts"
FIXTURE_PATHS = sorted(SCRIPTS_DIR.glob("*.kfc"))


def _split_fixture(text: str) -> tuple[list[str], str]:
    script_part, _, expected_part = text.partition("\nEXPECTED:\n")
    return script_part.splitlines(), expected_part.rstrip("\n")


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda p: p.name)
def test_fixture_script_produces_expected_output(fixture_path):
    script_lines, expected_output = _split_fixture(fixture_path.read_text())

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        ScriptRunner().run(script_lines)

    assert buffer.getvalue().rstrip("\n") == expected_output
