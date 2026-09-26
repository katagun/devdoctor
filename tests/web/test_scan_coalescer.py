"""Two identical scans at once share the sizer's workers and slow each other about 5x."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from devdoctor.web.scan_coalescer import ScanCoalescer


def _held(started: threading.Event, release: threading.Event, calls: list[int], value):
    def scan():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return value

    return scan


def test_concurrent_requests_for_one_key_share_one_scan():
    coalescer: ScanCoalescer[object] = ScanCoalescer()
    started, release, calls, report = threading.Event(), threading.Event(), [], object()
    scan = _held(started, release, calls, report)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coalescer.run, "k", scan)
        assert started.wait(5)
        second = pool.submit(coalescer.run, "k", scan)
        # The second request waits for the running scan instead of finishing on its own.
        with pytest.raises(TimeoutError):
            second.result(timeout=0.3)
        release.set()
        assert first.result(5) is report
        assert second.result(5) is report
    assert calls == [1]


def test_a_scan_of_other_filters_does_not_wait():
    coalescer: ScanCoalescer[str] = ScanCoalescer()
    started, release = threading.Event(), threading.Event()
    with ThreadPoolExecutor(1) as pool:
        held = pool.submit(coalescer.run, "a", _held(started, release, [], "a"))
        assert started.wait(5)
        assert coalescer.run("b", lambda: "b") == "b"
        release.set()
        assert held.result(5) == "a"


def test_a_failed_scan_fails_every_waiter_and_the_next_request_scans_again():
    coalescer: ScanCoalescer[str] = ScanCoalescer()
    started, release = threading.Event(), threading.Event()

    def failing():
        started.set()
        assert release.wait(5)
        raise OSError("the volume went away")

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(coalescer.run, "k", failing)
        assert started.wait(5)
        second = pool.submit(coalescer.run, "k", failing)
        with pytest.raises(TimeoutError):
            second.result(timeout=0.3)
        release.set()
        for request in (first, second):
            with pytest.raises(OSError, match="the volume went away"):
                request.result(5)
    assert coalescer.run("k", lambda: "fresh") == "fresh"


def test_a_request_after_the_scan_finished_starts_a_new_one():
    coalescer: ScanCoalescer[int] = ScanCoalescer()
    calls: list[int] = []

    def scan() -> int:
        calls.append(1)
        return len(calls)

    assert coalescer.run("k", scan) == 1
    assert coalescer.run("k", scan) == 2
