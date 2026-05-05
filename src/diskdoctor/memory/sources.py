from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from diskdoctor.ports import Shell

MemorySourceStatus = Literal["available", "unavailable", "planned"]
MemorySourceKind = Literal["system", "process", "docker", "llm", "browser"]


@dataclass(frozen=True)
class MemorySource:
    id: str
    name: str
    kind: MemorySourceKind
    status: MemorySourceStatus
    description: str
    detail: str | None = None


def list_memory_sources(shell: Shell) -> list[MemorySource]:
    docker = shell.which("docker")
    ollama = shell.which("ollama")
    return [
        MemorySource(
            id="system-memory",
            name="System memory",
            kind="system",
            status="available",
            description="Total, available, compressed, swap, and pressure signals.",
        ),
        MemorySource(
            id="process-table",
            name="Process table",
            kind="process",
            status="available",
            description=(
                "RSS by process, grouped into browsers, Docker, local LLMs, "
                "apps, and other processes."
            ),
        ),
        MemorySource(
            id="docker",
            name="Docker",
            kind="docker",
            status="available" if docker else "unavailable",
            description="Container and Docker Desktop memory context.",
            detail=docker or "docker binary not found",
        ),
        MemorySource(
            id="ollama",
            name="Ollama",
            kind="llm",
            status="available" if ollama else "unavailable",
            description="Local model server memory context.",
            detail=ollama or "ollama binary not found",
        ),
        MemorySource(
            id="browser-bridge",
            name="Browser bridge",
            kind="browser",
            status="planned",
            description=(
                "Optional extension bridge for tab titles, URLs, discard state, and tab actions."
            ),
        ),
    ]
