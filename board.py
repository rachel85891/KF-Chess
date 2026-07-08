"""
Board parsing, validation, and canonical text representation.

This module knows nothing about game rules, selection, or timing -
only how to turn raw fixture text into a validated grid of tokens
and back into canonical output.
"""

from constants import (
    VALID_PIECES,
    EMPTY_TOKEN,
    ERR_EMPTY_BOARD,
    ERR_ROW_WIDTH_MISMATCH,
    ERR_UNKNOWN_TOKEN,
)


def is_valid_token(token):
    if token == EMPTY_TOKEN:
        return True
    if len(token) == 2 and token[0] in ("w", "b") and token[1] in VALID_PIECES:
        return True
    return False


def parse_sections(lines):
    """
    Split raw input lines into (board_lines, command_lines) based on the
    'Board:' and 'Commands:' section headers.
    """
    board_lines = []
    command_lines = []
    section = None

    for line in lines:
        stripped = line.strip()
        if stripped == "Board:":
            section = "board"
            continue
        if stripped == "Commands:":
            section = "commands"
            continue
        if section == "board":
            if stripped == "":
                continue
            board_lines.append(stripped)
        elif section == "commands":
            if stripped == "":
                continue
            command_lines.append(stripped)

    return board_lines, command_lines


def tokenize_rows(board_lines):
    return [line.split() for line in board_lines]


def validate_board(rows):
    """
    Validate row width consistency first, then token validity.
    Returns None on success, or an error code string on failure.
    """
    if not rows:
        return ERR_EMPTY_BOARD

    width = len(rows[0])
    for row in rows:
        if len(row) != width:
            return ERR_ROW_WIDTH_MISMATCH

    for row in rows:
        for token in row:
            if not is_valid_token(token):
                return ERR_UNKNOWN_TOKEN

    return None


def canonical_board_string(rows):
    return "\n".join(" ".join(row) for row in rows)


class Board:
    """Thin wrapper around the token grid with basic geometry helpers."""

    def __init__(self, rows):
        self.rows = rows
        self.num_rows = len(rows)
        self.num_cols = len(rows[0]) if rows else 0

    @classmethod
    def from_lines(cls, board_lines):
        """
        Build and validate a Board from raw board-section lines.
        Returns (board, error_code). On failure, board is None.
        """
        rows = tokenize_rows(board_lines)
        error = validate_board(rows)
        if error is not None:
            return None, error
        return cls(rows), None

    def in_bounds(self, row, col):
        return 0 <= row < self.num_rows and 0 <= col < self.num_cols

    def get(self, row, col):
        return self.rows[row][col]

    def set(self, row, col, token):
        self.rows[row][col] = token

    def to_canonical_string(self):
        return canonical_board_string(self.rows)