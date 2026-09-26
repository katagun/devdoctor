from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager


class JobInProgressError(RuntimeError):
    """The one job slot is taken: a job is active, or another start is preparing one."""


class RunnerRegistry[T]:
    """Holds at most one active runner. Second `create()` while active raises.

    Used from the event loop only, so the slot needs no lock.
    """

    def __init__(self) -> None:
        self._active: T | None = None
        self._claimed = False

    @contextmanager
    def claim(self) -> Iterator[None]:
        """Hold the slot while a job is prepared, so a second start is refused at once.

        Preparing a job re-scans the disk, which can take minutes. ``create`` inside
        the block fills the slot; leaving the block without it frees the slot.
        """
        if self._active is not None or self._claimed:
            raise JobInProgressError("a cleanup job is already in progress")
        self._claimed = True
        try:
            yield
        finally:
            self._claimed = False

    def create(self, factory: Callable[[], T]) -> T:
        if self._active is not None:
            raise JobInProgressError("a cleanup job is already in progress")
        self._active = factory()
        return self._active

    def active(self) -> T | None:
        return self._active

    def release(self, runner: T) -> None:
        if self._active is runner:
            self._active = None
