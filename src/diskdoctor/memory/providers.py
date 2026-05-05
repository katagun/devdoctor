from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from diskdoctor.memory.types import MemoryConsumerKind
from diskdoctor.ports import Shell
from diskdoctor.types import ShellResult

MemoryProviderStatus = Literal["available", "unavailable", "planned"]
MemoryProviderKind = Literal["browser", "electron", "docker", "llm", "app", "process"]


@dataclass(frozen=True)
class MemoryProvider:
    id: str
    name: str
    kind: MemoryProviderKind
    status: MemoryProviderStatus
    description: str
    detail: str | None = None
    consumer_kinds: tuple[MemoryConsumerKind, ...] = ()


def list_memory_providers(shell: Shell) -> list[MemoryProvider]:
    return _memory_providers(docker=shell.which("docker"), ollama=shell.which("ollama"))


def memory_provider_catalog() -> list[MemoryProvider]:
    return _memory_providers(docker=None, ollama=None)


def _memory_providers(*, docker: str | None, ollama: str | None) -> list[MemoryProvider]:
    return [
        MemoryProvider(
            id="browsers",
            name="Browsers",
            kind="browser",
            status="available",
            description="Firefox, Chrome, Arc, Brave, Safari, and renderer helper processes.",
            detail=(
                "Tab-level attribution still depends on browser task-manager or extension support."
            ),
            consumer_kinds=("browser",),
        ),
        MemoryProvider(
            id="electron-apps",
            name="Electron apps",
            kind="electron",
            status="available",
            description=(
                "Slack, Discord, Teams, Notion, Figma, VS Code, Cursor, and similar app shells."
            ),
            consumer_kinds=("electron",),
        ),
        MemoryProvider(
            id="docker",
            name="Docker",
            kind="docker",
            status="available",
            description="Docker Desktop, VM, daemon, and container helper processes.",
            detail=docker or "Docker CLI not found; process-table matching still works.",
            consumer_kinds=("docker",),
        ),
        MemoryProvider(
            id="local-llms",
            name="Local LLM runtimes",
            kind="llm",
            status="available",
            description="Ollama, LM Studio, llama.cpp-style workers, and model server processes.",
            detail=ollama
            or "Ollama CLI not found; LM Studio and process-table matching still work.",
            consumer_kinds=("llm",),
        ),
        MemoryProvider(
            id="native-apps",
            name="Native apps",
            kind="app",
            status="available",
            description=(
                "GUI apps that are not classified as browsers, Docker, LLMs, or Electron shells."
            ),
            consumer_kinds=("app",),
        ),
        MemoryProvider(
            id="other-processes",
            name="Other processes",
            kind="process",
            status="available",
            description=(
                "Command-line tools, services, and processes that do not match a richer provider."
            ),
            consumer_kinds=("process", "other"),
        ),
    ]


def memory_provider_ids() -> set[str]:
    return {provider.id for provider in memory_provider_catalog()}


def consumer_kinds_for_provider_ids(
    provider_ids: Iterable[str] | None,
) -> set[MemoryConsumerKind] | None:
    if provider_ids is None:
        return None
    selected = set(provider_ids)
    providers = memory_provider_catalog()
    kinds: set[MemoryConsumerKind] = set()
    for provider in providers:
        if provider.id in selected:
            kinds.update(provider.consumer_kinds)
    return kinds


class _NullShell:
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> ShellResult:
        return ShellResult(returncode=1, stdout="", stderr="")

    def which(self, name: str) -> str | None:
        return None
