"""PieceTypeRegistry: the set of piece types playable in a game session,
and the single place every piece-identity constant lives - letters,
names, which letters are royal, what promotes into what, and the two
function dictionaries that drive movement legality. Business-logic
modules (domain/services) never contain a piece-letter string; they
only ever receive a PieceType/Piece object or call through this
registry.

standard_chess() assembles the 6 default piece types from MOVE_RULES /
REQUIRES_CLEAR_PATH. A custom game builds an alternate registry the same
way - its own dicts of letter -> function - and passes it wherever a
registry is expected (the codec, the engine); no other code changes.
"""

from __future__ import annotations

from kungfu_chess.domain.color import Color
from kungfu_chess.domain.movement.rules import (
    is_bishop_move,
    is_king_move,
    is_knight_move,
    is_pawn_move,
    is_queen_move,
    is_rook_move,
)
from kungfu_chess.domain.piece import PieceType

# Shape-legality dispatch, keyed by letter - the same "function
# dictionary" idiom the original codebase used, just relocated here
# since the letters themselves are configuration data, not something a
# domain movement-rule module should hardcode.
MOVE_RULES = {
    "K": is_king_move,
    "Q": is_queen_move,
    "R": is_rook_move,
    "B": is_bishop_move,
    "N": is_knight_move,
    "P": is_pawn_move,
}

# Mirrors MOVE_RULES' shape: does a legal move of this shape need every
# intervening cell checked for blockers? King/knight never do; the
# sliding pieces always do; a pawn only does for its 2-cell opening
# move. Kept as a dict of functions (not a bare SLIDING_PIECES set) so
# no piece-letter set has to be hardcoded into the legality service.
REQUIRES_CLEAR_PATH = {
    "K": lambda dr, dc: False,
    "Q": lambda dr, dc: True,
    "R": lambda dr, dc: True,
    "B": lambda dr, dc: True,
    "N": lambda dr, dc: False,
    "P": lambda dr, dc: abs(dr) == 2,
}

PIECE_NAMES = {
    "K": "King",
    "Q": "Queen",
    "R": "Rook",
    "B": "Bishop",
    "N": "Knight",
    "P": "Pawn",
}

# Capturing a royal piece ends the game (see RoyalCaptureWinCondition).
ROYAL_LETTERS = {"K"}

# letter -> letter it promotes into, on reaching the far row.
PROMOTIONS = {"P": "Q"}


class PieceTypeRegistry:
    def __init__(self, piece_types: dict[str, PieceType]):
        self._piece_types = dict(piece_types)
        # The full set of valid tokens (e.g. "wK", "bQ") for this
        # registry, generated once via a loop over every color crossed
        # with every known letter - not reconstructed by combining a
        # color check and a letter check each time a token is parsed.
        self.valid_tokens: frozenset[str] = frozenset(
            f"{color.value}{letter}" for color in Color for letter in self._piece_types
        )

    def get(self, letter: str) -> PieceType | None:
        return self._piece_types.get(letter)

    def has_letter(self, letter: str) -> bool:
        return letter in self._piece_types

    @classmethod
    def standard_chess(cls) -> "PieceTypeRegistry":
        piece_types: dict[str, PieceType] = {}
        for letter in MOVE_RULES:
            piece_types[letter] = PieceType(
                letter=letter,
                name=PIECE_NAMES[letter],
                movement_rule=MOVE_RULES[letter],
                requires_clear_path=REQUIRES_CLEAR_PATH[letter],
                is_royal=letter in ROYAL_LETTERS,
            )

        for from_letter, to_letter in PROMOTIONS.items():
            piece_types[from_letter] = PieceType(
                letter=piece_types[from_letter].letter,
                name=piece_types[from_letter].name,
                movement_rule=piece_types[from_letter].movement_rule,
                requires_clear_path=piece_types[from_letter].requires_clear_path,
                is_royal=piece_types[from_letter].is_royal,
                promotes_to=piece_types[to_letter],
            )

        return cls(piece_types)
