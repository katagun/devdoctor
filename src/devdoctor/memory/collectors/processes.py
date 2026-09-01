from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from devdoctor.memory.providers import consumer_kinds_for_provider_ids
from devdoctor.memory.types import MemoryConsumer, MemoryConsumerKind
from devdoctor.ports import Shell

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


def _compile_markers(markers: Sequence[str]) -> re.Pattern[str]:
    """Compile markers into a single word-boundary regex.

    Markers only match as whole words/phrases, so short generic markers such as
    ``arc`` or ``code`` no longer match when embedded in unrelated words (e.g.
    "se*arc*h", "x*code*build"). Multi-word and dotted markers (e.g.
    "google chrome", "com.docker") are matched literally via ``re.escape``.
    """
    alternation = "|".join(re.escape(marker) for marker in markers)
    return re.compile(rf"\b(?:{alternation})\b")


_BROWSER_PATTERN = _compile_markers(_BROWSER_MARKERS)
_DOCKER_PATTERN = _compile_markers(_DOCKER_MARKERS)
_LLM_PATTERN = _compile_markers(_LLM_MARKERS)
_ELECTRON_PATTERN = _compile_markers(_ELECTRON_MARKERS)


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
    if _BROWSER_PATTERN.search(lowered):
        return "browser"
    if _DOCKER_PATTERN.search(lowered):
        return "docker"
    if _LLM_PATTERN.search(lowered):
        return "llm"
    if _ELECTRON_PATTERN.search(lowered):
        return "electron"
    if "/applications/" in lowered or lowered.endswith(".app/contents/macos/"):
        return "app"
    return "other"
