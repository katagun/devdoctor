"""One scan per filter set at a time, shared by every request that asks for it."""

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from concurrent.futures import Future


class ScanCoalescer[T]:
    """Runs at most one scan per key at a time.

    A request for a key whose scan is running waits for that scan and gets its
    result instead of starting another: two scans of the same filters share the
    sizer's walk workers and slow each other about 5x. Requests arrive on worker
    threads, hence the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[Hashable, Future[T]] = {}

    def run(self, key: Hashable, scan: Callable[[], T]) -> T:
        with self._lock:
            running = self._running.get(key)
            leader = running is None
            if running is None:
                running = Future()
                self._running[key] = running
        if not leader:
            return running.result()
        try:
            result = scan()
        except BaseException as exc:
            running.set_exception(exc)
            raise
        finally:
            with self._lock:
                del self._running[key]
        running.set_result(result)
        return result
