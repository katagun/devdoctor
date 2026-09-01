from __future__ import annotations

from devdoctor.memory.types import MemoryWorkload

_GIB = 1024**3


WORKLOAD_PRESETS: tuple[MemoryWorkload, ...] = (
    MemoryWorkload(
        id="llm-7b",
        label="Local LLM 7B",
        kind="llm",
        required_bytes=8 * _GIB,
        description="A quantized 7B model plus runtime overhead.",
    ),
    MemoryWorkload(
        id="llm-13b",
        label="Local LLM 13B",
        kind="llm",
        required_bytes=14 * _GIB,
        description="A larger local model with room for context and runtime overhead.",
    ),
    MemoryWorkload(
        id="docker-dev",
        label="Docker dev stack",
        kind="docker",
        required_bytes=4 * _GIB,
        description="A multi-container local development stack.",
    ),
    MemoryWorkload(
        id="browser-research",
        label="Browser research session",
        kind="browser",
        required_bytes=2 * _GIB,
        description="A heavy browser session with many active tabs.",
    ),
    MemoryWorkload(
        id="ide-build-test",
        label="IDE build/test run",
        kind="developer",
        required_bytes=3 * _GIB,
        description="Editor, language server, build tooling, and test runner headroom.",
    ),
)


def get_workload(workload_id: str) -> MemoryWorkload | None:
    return next((w for w in WORKLOAD_PRESETS if w.id == workload_id), None)
