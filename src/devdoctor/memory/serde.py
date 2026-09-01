from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from devdoctor.memory.types import (
    MemoryAction,
    MemoryActionKind,
    MemoryActionRisk,
    MemoryConsumer,
    MemoryConsumerKind,
    MemoryPressure,
    MemoryReport,
    MemorySuggestion,
    MemorySuggestionConfidence,
    SystemMemory,
)


def report_to_dict(report: MemoryReport) -> dict[str, object]:
    return {
        "scanned_at": report.scanned_at.isoformat(),
        "hostname": report.hostname,
        "platform": report.platform,
        "system": system_to_dict(report.system),
        "consumers": [consumer_to_dict(c) for c in report.consumers],
    }


def report_from_dict(data: dict[str, Any]) -> MemoryReport:
    return MemoryReport(
        scanned_at=datetime.fromisoformat(str(data["scanned_at"])),
        hostname=str(data["hostname"]),
        platform=str(data["platform"]),
        system=system_from_dict(cast(dict[str, Any], data["system"])),
        consumers=[
            consumer_from_dict(cast(dict[str, Any], c))
            for c in cast(list[object], data.get("consumers", []))
        ],
    )


def system_to_dict(system: SystemMemory) -> dict[str, object]:
    return {
        "total_bytes": system.total_bytes,
        "available_bytes": system.available_bytes,
        "used_bytes": system.used_bytes,
        "swap_used_bytes": system.swap_used_bytes,
        "compressed_bytes": system.compressed_bytes,
        "pressure": system.pressure,
    }


def system_from_dict(data: dict[str, Any]) -> SystemMemory:
    return SystemMemory(
        total_bytes=int(data["total_bytes"]),
        available_bytes=int(data["available_bytes"]),
        used_bytes=int(data["used_bytes"]),
        swap_used_bytes=_optional_int(data.get("swap_used_bytes")),
        compressed_bytes=_optional_int(data.get("compressed_bytes")),
        pressure=cast(MemoryPressure, data.get("pressure", "unknown")),
    )


def consumer_to_dict(consumer: MemoryConsumer) -> dict[str, object]:
    return {
        "id": consumer.id,
        "pid": consumer.pid,
        "parent_pid": consumer.parent_pid,
        "name": consumer.name,
        "kind": consumer.kind,
        "rss_bytes": consumer.rss_bytes,
        "private_bytes": consumer.private_bytes,
        "command": consumer.command,
        "children": [consumer_to_dict(c) for c in consumer.children],
    }


def consumer_from_dict(data: dict[str, Any]) -> MemoryConsumer:
    return MemoryConsumer(
        id=str(data["id"]),
        pid=_optional_int(data.get("pid")),
        parent_pid=_optional_int(data.get("parent_pid")),
        name=str(data["name"]),
        kind=cast(MemoryConsumerKind, data.get("kind", "other")),
        rss_bytes=int(data["rss_bytes"]),
        private_bytes=_optional_int(data.get("private_bytes")),
        command=None if data.get("command") is None else str(data["command"]),
        children=[
            consumer_from_dict(cast(dict[str, Any], c))
            for c in cast(list[object], data.get("children", []))
        ],
    )


def suggestions_to_list(suggestions: list[MemorySuggestion]) -> list[dict[str, object]]:
    return [suggestion_to_dict(s) for s in suggestions]


def suggestions_from_list(data: list[object]) -> list[MemorySuggestion]:
    return [suggestion_from_dict(cast(dict[str, Any], item)) for item in data]


def suggestion_to_dict(suggestion: MemorySuggestion) -> dict[str, object]:
    return {
        "id": suggestion.id,
        "title": suggestion.title,
        "reason": suggestion.reason,
        "estimated_bytes": suggestion.estimated_bytes,
        "confidence": suggestion.confidence,
        "actions": [action_to_dict(a) for a in suggestion.actions],
    }


def suggestion_from_dict(data: dict[str, Any]) -> MemorySuggestion:
    return MemorySuggestion(
        id=str(data["id"]),
        title=str(data["title"]),
        reason=str(data["reason"]),
        estimated_bytes=_optional_int(data.get("estimated_bytes")),
        confidence=cast(MemorySuggestionConfidence, data.get("confidence", "low")),
        actions=[
            action_from_dict(cast(dict[str, Any], a))
            for a in cast(list[object], data.get("actions", []))
        ],
    )


def action_to_dict(action: MemoryAction) -> dict[str, object]:
    return {
        "id": action.id,
        "kind": action.kind,
        "label": action.label,
        "target_id": action.target_id,
        "estimated_bytes": action.estimated_bytes,
        "risk": action.risk,
    }


def action_from_dict(data: dict[str, Any]) -> MemoryAction:
    return MemoryAction(
        id=str(data["id"]),
        kind=cast(MemoryActionKind, data["kind"]),
        label=str(data["label"]),
        target_id=str(data["target_id"]),
        estimated_bytes=_optional_int(data.get("estimated_bytes")),
        risk=cast(MemoryActionRisk, data["risk"]),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        return int(value)
    raise TypeError(f"expected int-compatible value, got {type(value).__name__}")
