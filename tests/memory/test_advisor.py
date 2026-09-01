from __future__ import annotations

from datetime import UTC, datetime

from devdoctor.memory.advisor import advise
from devdoctor.memory.types import MemoryConsumer, MemoryReport, SystemMemory


def _report(*consumers: MemoryConsumer, pressure: str = "ok") -> MemoryReport:
    return MemoryReport(
        scanned_at=datetime(2026, 5, 4, tzinfo=UTC),
        hostname="h",
        platform="darwin",
        system=SystemMemory(
            total_bytes=16 * 1024**3,
            available_bytes=4 * 1024**3 if pressure == "ok" else 512 * 1024**2,
            used_bytes=12 * 1024**3,
            swap_used_bytes=0 if pressure == "ok" else 5 * 1024**3,
            compressed_bytes=None,
            pressure=pressure,  # type: ignore[arg-type]
        ),
        consumers=list(consumers),
    )


def _consumer(name: str, kind: str, rss: int, pid: int = 100) -> MemoryConsumer:
    return MemoryConsumer(
        id=f"pid:{pid}",
        pid=pid,
        parent_pid=1,
        name=name,
        kind=kind,  # type: ignore[arg-type]
        rss_bytes=rss,
        private_bytes=None,
        command=name,
    )


def test_advisor_suggests_firefox_internal_tools_for_browser_memory() -> None:
    suggestions = advise(
        _report(
            _consumer("Firefox", "browser", 2 * 1024**3),
            pressure="warn",
        )
    )

    browser = next(s for s in suggestions if s.id == "browser-memory")
    assert browser.estimated_bytes == 2 * 1024**3
    assert "about:processes" in browser.reason
    assert browser.actions[0].kind == "inspect_browser"
    assert browser.actions[0].risk == "safe"


def test_advisor_suggests_stopping_docker_and_llm_runtime() -> None:
    suggestions = advise(
        _report(
            _consumer("Docker", "docker", 2 * 1024**3),
            _consumer("ollama", "llm", 1 * 1024**3),
        )
    )
    ids = {s.id for s in suggestions}

    assert "docker-memory" in ids
    assert "llm-memory" in ids


def test_advisor_summarizes_pressure_top_contributors() -> None:
    suggestions = advise(
        _report(
            _consumer("A", "other", 4 * 1024**3, pid=1),
            _consumer("B", "other", 3 * 1024**3, pid=2),
            pressure="critical",
        )
    )

    pressure = suggestions[0]
    assert pressure.id == "memory-pressure"
    assert pressure.confidence == "high"
    assert "A" in pressure.reason


def test_advisor_suggests_large_other_process_at_low_confidence() -> None:
    suggestions = advise(_report(_consumer("VirtualMachine", "other", 3 * 1024**3)))

    large = next(s for s in suggestions if s.id.startswith("large-process:"))
    assert large.confidence == "low"
    assert large.actions[0].risk == "dangerous"
