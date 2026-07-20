"""Unit tests for EventBus (kungfu_chess/bus/event_bus.py), written
before the implementation exists, per docs/spec.md's TDD loop.

Event types here (_Foo/_Bar below) are minimal fixtures that exist
ONLY in this test file - EventBus itself must stay fully decoupled
from any specific event's shape or meaning (see EventBus's own module
docstring), so no real event dataclass belongs in production code for
this stage.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kungfu_chess.bus.event_bus import EventBus


@dataclass(frozen=True)
class _Foo:
    """Minimal fixture event type A - unrelated to any real domain."""

    value: int


@dataclass(frozen=True)
class _Bar:
    """Minimal fixture event type B - distinct from _Foo, used to
    prove EventBus does exact-type matching, not subclass matching."""

    label: str


def test_subscribe_then_publish_calls_handler_with_the_event():
    bus = EventBus()
    received: list[_Foo] = []

    bus.subscribe(_Foo, received.append)
    bus.publish(_Foo(value=1))

    assert received == [_Foo(value=1)]


def test_publish_with_no_subscribers_does_nothing():
    bus = EventBus()

    # No subscribe() call for _Foo at all - must not raise.
    bus.publish(_Foo(value=1))


def test_two_handlers_subscribed_to_the_same_type_both_receive_it():
    bus = EventBus()
    received_a: list[_Foo] = []
    received_b: list[_Foo] = []

    bus.subscribe(_Foo, received_a.append)
    bus.subscribe(_Foo, received_b.append)
    bus.publish(_Foo(value=7))

    assert received_a == [_Foo(value=7)]
    assert received_b == [_Foo(value=7)]


def test_handler_subscribed_to_one_type_is_not_called_for_a_different_type():
    bus = EventBus()
    received_foo: list[_Foo] = []
    received_bar: list[_Bar] = []

    bus.subscribe(_Foo, received_foo.append)
    bus.subscribe(_Bar, received_bar.append)
    bus.publish(_Bar(label="x"))

    assert received_bar == [_Bar(label="x")]
    assert received_foo == []


def test_unsubscribe_stops_the_handler_from_receiving_further_events():
    bus = EventBus()
    received: list[_Foo] = []

    def handler(event: _Foo) -> None:
        received.append(event)

    bus.subscribe(_Foo, handler)
    bus.publish(_Foo(value=1))
    bus.unsubscribe(_Foo, handler)
    bus.publish(_Foo(value=2))

    assert received == [_Foo(value=1)]


def test_unsubscribing_a_handler_that_was_never_subscribed_does_not_raise():
    bus = EventBus()

    def never_subscribed(event: object) -> None:
        pass

    # No prior subscribe() call for this handler or this type at all.
    bus.unsubscribe(_Foo, never_subscribed)


def test_unsubscribing_from_a_type_with_other_active_subscribers_does_not_raise():
    bus = EventBus()

    def handler_a(event: object) -> None:
        pass

    def handler_b(event: object) -> None:
        pass

    bus.subscribe(_Foo, handler_a)
    # handler_b was never subscribed to _Foo - must be a no-op, not KeyError/ValueError.
    bus.unsubscribe(_Foo, handler_b)


def test_publish_calls_handlers_in_subscription_order_fifo():
    bus = EventBus()
    call_order: list[str] = []

    bus.subscribe(_Foo, lambda event: call_order.append("first"))
    bus.subscribe(_Foo, lambda event: call_order.append("second"))
    bus.subscribe(_Foo, lambda event: call_order.append("third"))
    bus.publish(_Foo(value=1))

    # A reversed or arbitrary dispatch order would fail this exact
    # sequence check.
    assert call_order == ["first", "second", "third"]


def test_a_raising_handler_does_not_prevent_other_handlers_from_being_called():
    """Exception policy (see EventBus.publish's own docstring):
    isolate-and-continue, then re-raise after every handler has run.
    This half proves the "isolate" side - a later, healthy handler
    still receives the event even though an earlier one raised."""

    bus = EventBus()
    received: list[_Foo] = []

    def raising_handler(event: _Foo) -> None:
        raise RuntimeError("boom")

    bus.subscribe(_Foo, raising_handler)
    bus.subscribe(_Foo, received.append)

    with pytest.raises(RuntimeError, match="boom"):
        bus.publish(_Foo(value=1))

    assert received == [_Foo(value=1)]


def test_a_raising_handler_exception_still_propagates_to_the_publish_caller():
    """The other half of the same policy: the failure is never
    silently swallowed - publish() re-raises it to the caller, so a
    buggy handler is still loudly visible."""

    bus = EventBus()

    def raising_handler(event: _Foo) -> None:
        raise ValueError("bad handler")

    bus.subscribe(_Foo, raising_handler)

    with pytest.raises(ValueError, match="bad handler"):
        bus.publish(_Foo(value=1))


def test_only_the_first_of_several_raising_handlers_exceptions_propagates():
    """With multiple raising handlers, every one of them still runs
    (isolation), but publish() only ever raises the FIRST exception
    encountered - documented as the deterministic choice, since raising
    all of them at once would need inventing a multi-exception wrapper
    type this stage does not need."""

    bus = EventBus()
    calls: list[str] = []

    def first_raiser(event: _Foo) -> None:
        calls.append("first")
        raise RuntimeError("first failure")

    def second_raiser(event: _Foo) -> None:
        calls.append("second")
        raise RuntimeError("second failure")

    bus.subscribe(_Foo, first_raiser)
    bus.subscribe(_Foo, second_raiser)

    with pytest.raises(RuntimeError, match="first failure"):
        bus.publish(_Foo(value=1))

    assert calls == ["first", "second"]


def test_two_independent_eventbus_instances_share_no_state():
    bus_a = EventBus()
    bus_b = EventBus()
    received_a: list[_Foo] = []

    bus_a.subscribe(_Foo, received_a.append)
    bus_b.publish(_Foo(value=1))

    assert received_a == []
