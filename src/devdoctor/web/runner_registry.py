from __future__ import annotations

from collections.abc import Callable


class RunnerRegistry[T]:
    """Holds at most one active runner. Second `create()` while active raises."""

    def __init__(self) -> None:
        self._active: T | None = None

    def create(self, factory: Callable[[], T]) -> T:
        if self._active is not None:
            raise RuntimeError("a cleanup job is already in progress")
        self._active = factory()
        return self._active

    def active(self) -> T | None:
        return self._active

    def release(self, runner: T) -> None:
        if self._active is runner:
            self._active = None
