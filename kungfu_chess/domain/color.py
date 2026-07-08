"""The two sides a piece can belong to."""

from enum import Enum


class Color(Enum):
    WHITE = "w"
    BLACK = "b"

    @property
    def opposite(self) -> "Color":
        return Color.BLACK if self is Color.WHITE else Color.WHITE
