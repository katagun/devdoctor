from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from diskdoctor.types import Risk

StorageBackendInfo = Literal["filesystem", "sqlite"]
MemoryConsumerKindInfo = Literal["app", "process", "browser", "electron", "docker", "llm", "other"]


class RecipeRequest(BaseModel):
    providers: list[str] | None = None


class RecipeResponse(BaseModel):
    script: str


class ProviderInfo(BaseModel):
    name: str
    description: str
    risk: Literal["safe", "reclaimable", "dangerous"]
    platforms: list[str]
    available: bool
    required_binary: str | None
    kind: Literal["class", "yaml"]
    reason_if_unavailable: str | None = None
    # Provider details — populated per kind. Class providers set `details`;
    # YAML (PathProvider) sets the three path/recipe fields.
    details: str | None = None
    raw_paths: list[str] | None = None
    resolved_paths: list[str] | None = None
    recipe_template: list[str] | None = None


class CleanJobCreate(BaseModel):
    entry_ids: list[str] = Field(min_length=1)
    yes_safe: bool = False
    allow_dangerous: bool = False


class CleanJobCreated(BaseModel):
    job_id: str


class PromptAnswer(BaseModel):
    entry_id: str
    choice: Literal["y", "n", "a", "s", "q"]


class ConfirmAnswer(BaseModel):
    confirmed: bool


class SnapshotCreate(BaseModel):
    note: str | None = None


class SnapshotMeta(BaseModel):
    name: str
    path: str
    scanned_at: str
    hostname: str
    platform: str
    note: str | None
    total_bytes: int
    # Telemetry fields. Optional so v1 snapshot files (no kind/timing data)
    # serve as manual with duration_ms=None and empty per_provider.
    kind: Literal["auto", "manual"] = "manual"
    duration_ms: int | None = None
    entry_count: int | None = None
    per_provider: list[dict[str, object]] | None = None


class DiskDashboardEntryInfo(BaseModel):
    id: str
    provider: str
    label: str
    size_bytes: int
    risk: Literal["safe", "reclaimable", "dangerous"]


class DiskDashboardProviderTotalInfo(BaseModel):
    provider: str
    bytes: int
    count: int


class DiskDashboardSummaryInfo(BaseModel):
    scanned_at: str
    hostname: str
    platform: str
    total_bytes: int
    entry_count: int
    entries: list[DiskDashboardEntryInfo] = Field(default_factory=list)
    provider_totals: list[DiskDashboardProviderTotalInfo] = Field(default_factory=list)


class SystemMemoryInfo(BaseModel):
    total_bytes: int
    available_bytes: int
    used_bytes: int
    swap_used_bytes: int | None
    compressed_bytes: int | None
    pressure: Literal["ok", "warn", "critical", "unknown"]


class MemoryConsumerInfo(BaseModel):
    id: str
    pid: int | None
    parent_pid: int | None
    name: str
    kind: MemoryConsumerKindInfo
    rss_bytes: int
    private_bytes: int | None
    command: str | None
    children: list[MemoryConsumerInfo] = Field(default_factory=list)


class MemoryActionInfo(BaseModel):
    id: str
    kind: Literal[
        "inspect_browser",
        "discard_tabs",
        "stop_container",
        "stop_service",
        "quit_app",
        "terminate_process",
    ]
    label: str
    target_id: str
    estimated_bytes: int | None
    risk: Literal["safe", "reclaimable", "dangerous"]


class MemoryActionExecuteRequest(BaseModel):
    id: str
    kind: Literal[
        "inspect_browser",
        "discard_tabs",
        "stop_container",
        "stop_service",
        "quit_app",
        "terminate_process",
    ]
    target_id: str
    label: str | None = None
    estimated_bytes: int | None = Field(default=None, ge=0)
    risk: Literal["safe", "reclaimable", "dangerous"] | None = None
    confirmed: bool = False


class MemoryActionExecuteResultInfo(BaseModel):
    action_id: str
    status: Literal["ok", "error", "unsupported"]
    message: str


class MemorySuggestionInfo(BaseModel):
    id: str
    title: str
    reason: str
    estimated_bytes: int | None
    confidence: Literal["low", "medium", "high"]
    actions: list[MemoryActionInfo] = Field(default_factory=list)


class MemoryProviderTotalInfo(BaseModel):
    id: str
    name: str
    kind: Literal["browser", "electron", "docker", "llm", "app", "process"]
    selected: bool
    rss_bytes: int
    consumer_count: int


class MemoryReportInfo(BaseModel):
    scanned_at: str
    hostname: str
    platform: str
    system: SystemMemoryInfo
    consumers: list[MemoryConsumerInfo]
    provider_totals: list[MemoryProviderTotalInfo] = Field(default_factory=list)
    suggestions: list[MemorySuggestionInfo] = Field(default_factory=list)


class MemoryObservationMetaInfo(BaseModel):
    id: str
    scanned_at: str
    pressure: Literal["ok", "warn", "critical", "unknown"]
    total_bytes: int
    available_bytes: int
    used_bytes: int
    swap_used_bytes: int | None
    compressed_bytes: int | None
    top_consumer_name: str | None
    top_consumer_kind: MemoryConsumerKindInfo | None
    top_consumer_rss_bytes: int | None
    suggestion_count: int


class MemoryHistoryInfo(BaseModel):
    observations: list[MemoryObservationMetaInfo]


class MemorySnapshotCreate(BaseModel):
    note: str | None = None


class MemorySnapshotMetaInfo(BaseModel):
    name: str
    created_at: str
    scanned_at: str
    note: str | None
    pressure: Literal["ok", "warn", "critical", "unknown"]
    total_bytes: int
    available_bytes: int
    used_bytes: int
    top_consumer_name: str | None
    top_consumer_kind: MemoryConsumerKindInfo | None
    top_consumer_rss_bytes: int | None


class MemorySnapshotInfo(BaseModel):
    name: str
    created_at: str
    note: str | None
    report: MemoryReportInfo


class MemorySnapshotDiffInfo(BaseModel):
    before: MemorySnapshotMetaInfo
    after: MemorySnapshotMetaInfo
    available_delta_bytes: int
    used_delta_bytes: int
    swap_delta_bytes: int | None
    compressed_delta_bytes: int | None
    top_consumer_deltas: list[dict[str, object]]
    added_suggestion_ids: list[str]
    removed_suggestion_ids: list[str]


class MemorySourceInfo(BaseModel):
    id: str
    name: str
    kind: Literal["system", "process", "docker", "llm", "browser"]
    status: Literal["available", "unavailable", "planned"]
    description: str
    detail: str | None = None


class MemoryProviderInfo(BaseModel):
    id: str
    name: str
    kind: Literal["browser", "electron", "docker", "llm", "app", "process"]
    status: Literal["available", "unavailable", "planned"]
    description: str
    detail: str | None = None
    consumer_kinds: list[MemoryConsumerKindInfo]


class MemoryWorkloadInfo(BaseModel):
    id: str
    label: str
    kind: Literal["llm", "docker", "browser", "developer", "custom"]
    required_bytes: int
    description: str


class MemoryPlanRequest(BaseModel):
    workload_id: str | None = None
    custom_label: str | None = None
    custom_required_bytes: int | None = Field(default=None, ge=1)
    safety_margin_bytes: int | None = Field(default=None, ge=0)
    providers: list[str] | None = None


class MemoryPlanActionInfo(BaseModel):
    suggestion_id: str
    action_id: str
    label: str
    estimated_bytes: int | None
    risk: Literal["safe", "reclaimable", "dangerous"]
    confidence: Literal["low", "medium", "high"]


class MemoryPlanInfo(BaseModel):
    workload: MemoryWorkloadInfo
    fits_now: bool
    required_bytes: int
    available_bytes: int
    os_reserve_bytes: int
    safety_margin_bytes: int
    usable_bytes: int
    deficit_bytes: int
    planned_reclaim_bytes: int
    remaining_deficit_bytes: int
    actions: list[MemoryPlanActionInfo]


class AppSettingsInfo(BaseModel):
    storage_backend: StorageBackendInfo
    data_dir: str
    sqlite_path: str
    available_backends: list[StorageBackendInfo]


class AppSettingsPatch(BaseModel):
    storage_backend: StorageBackendInfo | None = None
    data_dir: str | None = None
    sqlite_path: str | None = None


_RISK_VALUES: set[str] = {r.value for r in Risk}
