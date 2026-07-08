"""Project-wide constants."""

VALID_PIECES = set("KQRBNP")  # King, Queen, Rook, Bishop, Knight, Pawn
EMPTY_TOKEN = "."
CELL_SIZE = 100  # pixels per board cell

# Time (in ms) a move takes to "settle", PER CELL of distance traveled
# (confirmed by test evidence: a 1-cell move settles after 1000ms total
# wait, a 2-cell move needs 2000ms total wait).
MOVE_DURATION_PER_CELL_MS = 1000

# Time (in ms) a jump keeps a piece airborne before it lands.
JUMP_DURATION_MS = 1000

# Error codes printed as "ERROR <CODE>"
ERR_EMPTY_BOARD = "EMPTY_BOARD"
ERR_ROW_WIDTH_MISMATCH = "ROW_WIDTH_MISMATCH"
ERR_UNKNOWN_TOKEN = "UNKNOWN_TOKEN"