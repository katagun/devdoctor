from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

MemoryPressure = Literal["ok", "warn", "critical", "unknown"]
MemoryConsumerKind = Literal["app", "process", "browser", "electron", "docker", "llm", "other"]
MemoryActionKind = Literal[
    "inspect_browser",
    "discard_tabs",
    "stop_container",
    "stop_service",
    "quit_app",
    "terminate_process",
]
MemoryActionRisk = Literal["safe", "reclaimable", "dangerous"]
MemorySuggestionConfidence = Literal["low", "medium", "high"]
MemoryWorkloadKind = Literal["llm", "docker", "browser", "developer", "custom"]


@dataclass(frozen=True)
class SystemMemory:
    total_bytes: int
    available_bytes: int
    used_bytes: int
    swap_used_bytes: int | None
    compressed_bytes: int | None
    pressure: MemoryPressure


@dataclass(frozen=True)
class MemoryConsumer:
    id: str
    pid: int | None
    parent_pid: int | None
    name: str
    kind: MemoryConsumerKind
    rss_bytes: int
    private_bytes: int | None
    command: str | None
    children: list[MemoryConsumer] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryReport:
    scanned_at: datetime
    hostname: str
    platform: str
    system: SystemMemory
    consumers: list[MemoryConsumer]


@dataclass(frozen=True)
class MemoryAction:
    id: str
    kind: MemoryActionKind
    label: str
    target_id: str
    estimated_bytes: int | None
    risk: MemoryActionRisk


@dataclass(frozen=True)
class MemorySuggestion:
    id: str
    title: str
    reason: str
    estimated_bytes: int | None
    confidence: MemorySuggestionConfidence
    actions: list[MemoryAction] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryWorkload:
    id: str
    label: str
    kind: MemoryWorkloadKind
    required_bytes: int
    description: str


@dataclass(frozen=True)
class MemoryPlanAction:
    suggestion_id: str
    action_id: str
    label: str
    estimated_bytes: int | None
    risk: MemoryActionRisk
    confidence: MemorySuggestionConfidence


@dataclass(frozen=True)
class MemoryPlan:
    workload: MemoryWorkload
    fits_now: bool
    required_bytes: int
    available_bytes: int
    os_reserve_bytes: int
    safety_margin_bytes: int
    usable_bytes: int
    deficit_bytes: int
    planned_reclaim_bytes: int
    remaining_deficit_bytes: int
    actions: list[MemoryPlanAction] = field(default_factory=list)
