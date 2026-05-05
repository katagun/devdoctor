from __future__ import annotations

from collections import defaultdict

from diskdoctor.memory.types import (
    MemoryAction,
    MemoryConsumer,
    MemoryConsumerKind,
    MemoryReport,
    MemorySuggestion,
)

_ONE_GIB = 1024**3
_BROWSER_THRESHOLD_BYTES = 1 * _ONE_GIB
_ELECTRON_THRESHOLD_BYTES = 768 * 1024**2
_DOCKER_THRESHOLD_BYTES = 768 * 1024**2
_LLM_THRESHOLD_BYTES = 512 * 1024**2
_BIG_PROCESS_THRESHOLD_BYTES = 2 * _ONE_GIB
_SUGGESTION_LIMIT = 6


def advise(report: MemoryReport) -> list[MemorySuggestion]:
    suggestions: list[tuple[int, MemorySuggestion]] = []
    if report.system.pressure in {"warn", "critical"}:
        suggestions.append((100, _pressure_summary(report)))

    by_kind = _sum_by_kind(report.consumers)
    browser_total = by_kind.get("browser", 0)
    if browser_total >= _BROWSER_THRESHOLD_BYTES or (
        report.system.pressure in {"warn", "critical"} and browser_total > 0
    ):
        suggestions.append((90, _browser_suggestion(report, browser_total)))

    electron_total = by_kind.get("electron", 0)
    if electron_total >= _ELECTRON_THRESHOLD_BYTES or (
        report.system.pressure in {"warn", "critical"} and electron_total > 0
    ):
        suggestions.append((85, _electron_suggestion(report, electron_total)))

    docker_total = by_kind.get("docker", 0)
    if docker_total >= _DOCKER_THRESHOLD_BYTES:
        suggestions.append((80, _docker_suggestion(docker_total)))

    llm_total = by_kind.get("llm", 0)
    if llm_total >= _LLM_THRESHOLD_BYTES:
        suggestions.append((75, _llm_suggestion(llm_total)))

    big_other = [
        c
        for c in report.consumers
        if c.kind in {"app", "process", "electron", "other"}
        and c.rss_bytes >= _BIG_PROCESS_THRESHOLD_BYTES
    ]
    if big_other:
        suggestions.append((50, _big_process_suggestion(big_other[0])))

    suggestions.sort(key=lambda item: (item[0], item[1].estimated_bytes or 0), reverse=True)
    deduped: list[MemorySuggestion] = []
    seen: set[str] = set()
    for _score, suggestion in suggestions:
        if suggestion.id in seen:
            continue
        seen.add(suggestion.id)
        deduped.append(suggestion)
    return deduped[:_SUGGESTION_LIMIT]


def _sum_by_kind(consumers: list[MemoryConsumer]) -> dict[MemoryConsumerKind, int]:
    totals: defaultdict[MemoryConsumerKind, int] = defaultdict(int)
    for consumer in consumers:
        totals[consumer.kind] += consumer.rss_bytes
    return dict(totals)


def _pressure_summary(report: MemoryReport) -> MemorySuggestion:
    top = ", ".join(c.name for c in report.consumers[:3]) or "no large process"
    return MemorySuggestion(
        id="memory-pressure",
        title=f"Memory pressure is {report.system.pressure}",
        reason=(
            f"Available memory is low and swap/compression may be active. "
            f"The largest visible consumers are: {top}."
        ),
        estimated_bytes=None,
        confidence="high",
        actions=[],
    )


def _browser_suggestion(report: MemoryReport, total: int) -> MemorySuggestion:
    browser_names = {c.name.lower() for c in report.consumers if c.kind == "browser"}
    firefox = any("firefox" in name or "plugin-container" in name for name in browser_names)
    reason = (
        "Browsers are a major memory contributor. Review the browser task manager and unload "
        "inactive or heavy tabs before quitting the whole app."
    )
    label = "Review browser task manager and unload inactive tabs"
    if firefox:
        reason += (
            " Firefox does not expose reliable OS PID to tab mapping to DevDoctor; use "
            "about:processes or about:memory for exact attribution."
        )
        label = "Open Firefox about:processes/about:memory"
    return MemorySuggestion(
        id="browser-memory",
        title="Browser memory is high",
        reason=reason,
        estimated_bytes=total,
        confidence="medium",
        actions=[
            MemoryAction(
                id="inspect-browser",
                kind="inspect_browser",
                label=label,
                target_id="browser",
                estimated_bytes=None,
                risk="safe",
            )
        ],
    )


def _electron_suggestion(report: MemoryReport, total: int) -> MemorySuggestion:
    top = [c.name for c in report.consumers if c.kind == "electron"][:3]
    names = ", ".join(top) or "Electron apps"
    return MemorySuggestion(
        id="electron-memory",
        title="Electron apps are using memory",
        reason=(
            f"{names} are visible as large Electron-style app processes. Quit idle "
            "workspace apps before terminating helper processes directly."
        ),
        estimated_bytes=total,
        confidence="medium",
        actions=[
            MemoryAction(
                id="quit-electron-apps",
                kind="quit_app",
                label="Quit idle Electron apps",
                target_id="electron-apps",
                estimated_bytes=total,
                risk="reclaimable",
            )
        ],
    )


def _docker_suggestion(total: int) -> MemorySuggestion:
    return MemorySuggestion(
        id="docker-memory",
        title="Docker is holding memory",
        reason=(
            "Docker Desktop and container helper processes can keep a large VM resident. "
            "If no containers are actively needed, stopping Docker is usually lower risk than "
            "killing individual processes."
        ),
        estimated_bytes=total,
        confidence="medium",
        actions=[
            MemoryAction(
                id="stop-docker",
                kind="stop_service",
                label="Stop Docker if idle",
                target_id="docker",
                estimated_bytes=total,
                risk="reclaimable",
            )
        ],
    )


def _llm_suggestion(total: int) -> MemorySuggestion:
    return MemorySuggestion(
        id="llm-memory",
        title="Local LLM runtime is using memory",
        reason=(
            "Ollama, LM Studio, or llama.cpp-style processes can keep model weights resident. "
            "Unload or stop the runtime if you are not actively generating."
        ),
        estimated_bytes=total,
        confidence="medium",
        actions=[
            MemoryAction(
                id="stop-llm-runtime",
                kind="stop_service",
                label="Stop idle local LLM runtime",
                target_id="llm",
                estimated_bytes=total,
                risk="reclaimable",
            )
        ],
    )


def _big_process_suggestion(consumer: MemoryConsumer) -> MemorySuggestion:
    return MemorySuggestion(
        id=f"large-process:{consumer.id}",
        title=f"{consumer.name} is unusually large",
        reason=(
            "This process is large enough to matter under memory pressure. Check for unsaved "
            "work before quitting or restarting it."
        ),
        estimated_bytes=consumer.rss_bytes,
        confidence="low",
        actions=[
            MemoryAction(
                id=f"inspect:{consumer.id}",
                kind="quit_app" if consumer.kind in {"app", "electron"} else "terminate_process",
                label=f"Inspect {consumer.name}",
                target_id=consumer.id,
                estimated_bytes=consumer.rss_bytes,
                risk="dangerous",
            )
        ],
    )
