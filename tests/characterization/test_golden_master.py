"""
Golden-master (characterization) tests.

Each fixture in tests/fixtures/*.txt is fed to main.py on stdin exactly as
the hidden grading platform would; stdout must match the corresponding
tests/golden/*.txt byte-for-byte. These goldens were captured from the
original, unrefactored implementation and must stay green through every
phase of the internal restructuring - they are the contract this project
is graded against, not a description of "intended" behavior.

Run with: py -m pytest tests/characterization -q
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"

FIXTURE_NAMES = sorted(p.stem for p in FIXTURES_DIR.glob("*.txt"))


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_matches_golden_output(name):
    fixture_path = FIXTURES_DIR / f"{name}.txt"
    golden_path = GOLDEN_DIR / f"{name}.txt"

    with fixture_path.open("rb") as stdin_file:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "main.py")],
            stdin=stdin_file,
            capture_output=True,
        )

    actual = result.stdout
    expected = golden_path.read_bytes()

    assert actual == expected, (
        f"stdout for fixture '{name}' diverged from the golden master.\n"
        f"--- expected ---\n{expected!r}\n--- actual ---\n{actual!r}"
    )
