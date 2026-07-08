"""WinCondition: decides whether a PieceCaptured event ends the game.

A Strategy, not a hardcoded "letter == K" check, so a custom game can
supply a different win condition (or none) without touching MoveResolver
or GameEngine - only which reactor is registered on the EventBus changes.
"""

from abc import ABC, abstractmethod

from kungfu_chess.domain.events import PieceCaptured


class WinCondition(ABC):
    @abstractmethod
    def ends_game(self, event: PieceCaptured) -> bool:
        raise NotImplementedError


class RoyalCaptureWinCondition(WinCondition):
    """The default rule: the game ends the instant a royal piece (the
    king, in standard chess) is captured."""

    def ends_game(self, event: PieceCaptured) -> bool:
        return event.captured_piece.is_royal
