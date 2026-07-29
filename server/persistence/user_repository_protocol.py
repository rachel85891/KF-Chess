"""user_repository_protocol.py: Stage H1 - the `UserRepository` interface
contract, split out from server/persistence/user_repository.py (whose own
260-line module docstring is entirely about SQLite/PBKDF2/salt
implementation details, not the interface shape) so a future
PostgresUserRepository (Stage I1, not this stage) can implement this same
Protocol without touching any calling code or importing anything
SQLite-specific.

`@runtime_checkable` is used specifically so tests can assert structural
conformance via `isinstance` directly, rather than requiring a separate
mypy/pyright invocation this project doesn't otherwise run.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class UserRepository(Protocol):
    def create_account(self, username: str, password: str) -> bool: ...

    def verify_login(self, username: str, password: str) -> bool: ...

    def get_rating(self, username: str) -> int: ...

    def update_rating(self, username: str, new_rating: int) -> None: ...
