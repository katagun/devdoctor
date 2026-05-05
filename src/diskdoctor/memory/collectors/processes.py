from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from diskdoctor.memory.providers import consumer_kinds_for_provider_ids
from diskdoctor.memory.types import MemoryConsumer, MemoryConsumerKind
from diskdoctor.ports import Shell

_PS_ARGV = ["ps", "-axo", "pid=,ppid=,rss=,comm="]
_PS_MIN_PARTS = 4
_BROWSER_MARKERS = (
    "firefox",
    "google chrome",
    "chrome",
    "chromium",
    "arc",
    "brave browser",
    "safari",
    "webkit",
)
_DOCKER_MARKERS = ("docker", "com.docker")
_LLM_MARKERS = ("ollama", "lm studio", "lm-studio", "lmstudio", "llama", "gguf")
_ELECTRON_MARKERS = (
    "slack",
    "discord",
    "microsoft teams",
    "teams.app",
    "notion",
    "figma",
    "whatsapp",
    "signal.app",
    "signal helper",
    "visual studio code",
    "code helper",
    "cursor.app",
    "cursor helper",
    "postman",
    "linear.app",
    "electron",
)


def collect_process_memory(
    shell: Shell,
    *,
    limit: int = 40,
    provider_ids: Iterable[str] | None = None,
) -> list[MemoryConsumer]:
    result = shell.run(_PS_ARGV, check=False)
    if result.returncode != 0:
        return []
    return parse_ps_output(result.stdout, limit=limit, provider_ids=provider_ids)


def parse_ps_output(
    output: str,
    *,
    limit: int = 40,
    provider_ids: Iterable[str] | None = None,
) -> list[MemoryConsumer]:
    allowed_kinds = consumer_kinds_for_provider_ids(provider_ids)
    consumers: list[MemoryConsumer] = []
    for line in output.splitlines():
        parsed = _parse_ps_line(line)
        if parsed is None:
            continue
        pid, parent_pid, rss_kib, command = parsed
        rss = rss_kib * 1024
        if rss <= 0:
            continue
        kind = classify_process(command)
        if allowed_kinds is not None and kind not in allowed_kinds:
            continue
        name = _display_name(command)
        consumers.append(
            MemoryConsumer(
                id=f"pid:{pid}",
                pid=pid,
                parent_pid=parent_pid,
                name=name,
                kind=kind,
                rss_bytes=rss,
                private_bytes=None,
                command=command,
            )
        )
    consumers.sort(key=lambda c: c.rss_bytes, reverse=True)
    return consumers[:limit]


def _parse_ps_line(line: str) -> tuple[int, int, int, str] | None:
    parts = line.strip().split(None, 3)
    if len(parts) < _PS_MIN_PARTS:
        return None
    try:
        pid = int(parts[0])
        parent_pid = int(parts[1])
        rss_kib = int(parts[2])
    except ValueError:
        return None
    return pid, parent_pid, rss_kib, parts[3].strip()


def _display_name(command: str) -> str:
    name = Path(command).name or command
    if name in {"Google Chrome Helper", "Google Chrome Helper (Renderer)"}:
        return "Chrome Helper"
    if name in {"plugin-container", "firefox"}:
        return "Firefox"
    return name


def classify_process(command: str) -> MemoryConsumerKind:
    lowered = command.lower()
    if any(marker in lowered for marker in _BROWSER_MARKERS):
        return "browser"
    if any(marker in lowered for marker in _DOCKER_MARKERS):
        return "docker"
    if any(marker in lowered for marker in _LLM_MARKERS):
        return "llm"
    if any(marker in lowered for marker in _ELECTRON_MARKERS):
        return "electron"
    if "/applications/" in lowered or lowered.endswith(".app/contents/macos/"):
        return "app"
    return "other"
