"""A small synchronous publish/subscribe bus for domain events.

This is deliberately minimal - no threading, no async, no wildcard
subscriptions. Its only job is to let post-move effects (promotion, win
detection, and whatever a custom game wants to add later) register as
independent reactors instead of being hardcoded into MoveResolver.
"""

from collections import defaultdict
from typing import Callable, TypeVar

T = TypeVar("T")


class EventBus:
    def __init__(self):
        self._subscribers: dict[type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type[T], handler: Callable[[T], None]) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event: object) -> None:
        for handler in self._subscribers[type(event)]:
            handler(event)
