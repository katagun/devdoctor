from __future__ import annotations

import contextlib
from collections.abc import Iterable
from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request

from diskdoctor.memory.actions import MemoryActionResult, execute_memory_action
from diskdoctor.memory.advisor import advise
from diskdoctor.memory.discovery import scan_memory
from diskdoctor.memory.planner import plan_workload
from diskdoctor.memory.providers import (
    MemoryProvider,
    list_memory_providers,
    memory_provider_catalog,
    memory_provider_ids,
)
from diskdoctor.memory.sources import MemorySource, list_memory_sources
from diskdoctor.memory.types import (
    MemoryAction,
    MemoryConsumer,
    MemoryPlan,
    MemoryPlanAction,
    MemoryReport,
    MemorySuggestion,
    MemoryWorkload,
    SystemMemory,
)
from diskdoctor.memory.workloads import WORKLOAD_PRESETS, get_workload
from diskdoctor.storage.base import (
    MemoryObservationMeta,
    MemorySnapshotMeta,
    StorageBackend,
    StoredMemorySnapshot,
)
from diskdoctor.web.models import (
    MemoryActionExecuteRequest,
    MemoryActionExecuteResultInfo,
    MemoryActionInfo,
    MemoryConsumerInfo,
    MemoryHistoryInfo,
    MemoryObservationMetaInfo,
    MemoryPlanActionInfo,
    MemoryPlanInfo,
    MemoryPlanRequest,
    MemoryProviderInfo,
    MemoryProviderTotalInfo,
    MemoryReportInfo,
    MemorySnapshotCreate,
    MemorySnapshotDiffInfo,
    MemorySnapshotInfo,
    MemorySnapshotMetaInfo,
    MemorySourceInfo,
    MemorySuggestionInfo,
    MemoryWorkloadInfo,
    SystemMemoryInfo,
)

router = APIRouter(prefix="/api")
_MEMORY_OBSERVATION_RETENTION = 2_000


@router.get("/memory", response_model=MemoryReportInfo)
def memory(
    request: Request,
    record: bool = Query(default=True),
    record_min_interval_ms: int | None = Query(default=10_000, ge=0),
    provider: str | None = Query(default=None),
) -> MemoryReportInfo:
    provider_ids = _parse_memory_provider_query(provider)
    report = scan_memory(request.app.state.shell, provider_ids=provider_ids)
    suggestions = advise(report)
    if record:
        storage = _storage(request)
        if _should_record_memory(storage, report, record_min_interval_ms):
            try:
                storage.write_memory_observation(report, suggestions)
                storage.prune_memory_observations(keep=_MEMORY_OBSERVATION_RETENTION)
            except OSError:
                pass
    return _report_to_info(report, suggestions, provider_ids=provider_ids)


@router.get("/memory/history", response_model=MemoryHistoryInfo)
def memory_history(
    request: Request,
    limit: int = Query(default=200, ge=1, le=2_000),
) -> MemoryHistoryInfo:
    return MemoryHistoryInfo(
        observations=[
            _observation_meta_to_info(meta)
            for meta in _storage(request).list_memory_observations(limit=limit)
        ]
    )


@router.get("/memory/snapshots", response_model=list[MemorySnapshotMetaInfo])
def list_memory_snapshots(
    request: Request,
    limit: int | None = Query(default=None, ge=1, le=1_000),
) -> list[MemorySnapshotMetaInfo]:
    return [
        _snapshot_meta_to_info(meta)
        for meta in _storage(request).list_memory_snapshots(limit=limit)
    ]


@router.post("/memory/snapshots", response_model=MemorySnapshotMetaInfo)
def create_memory_snapshot(
    body: MemorySnapshotCreate,
    request: Request,
    provider: str | None = Query(default=None),
) -> MemorySnapshotMetaInfo:
    provider_ids = _parse_memory_provider_query(provider)
    report = scan_memory(request.app.state.shell, provider_ids=provider_ids)
    suggestions = advise(report)
    meta = _storage(request).create_memory_snapshot(report, suggestions, note=body.note)
    return _snapshot_meta_to_info(meta)


@router.get("/memory/snapshots/diff", response_model=MemorySnapshotDiffInfo)
def diff_memory_snapshots(from_: str, to_: str, request: Request) -> MemorySnapshotDiffInfo:
    storage = _storage(request)
    try:
        before = storage.load_memory_snapshot(from_)
        after = storage.load_memory_snapshot(to_)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="memory snapshot not found") from exc
    return _memory_snapshot_diff(before, after)


@router.get("/memory/snapshots/{name}", response_model=MemorySnapshotInfo)
def get_memory_snapshot(name: str, request: Request) -> MemorySnapshotInfo:
    try:
        stored = _storage(request).load_memory_snapshot(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="memory snapshot not found") from exc
    return MemorySnapshotInfo(
        name=stored.name,
        created_at=stored.created_at,
        note=stored.note,
        report=_report_to_info(stored.report, stored.suggestions),
    )


@router.get("/memory/sources", response_model=list[MemorySourceInfo])
def memory_sources(request: Request) -> list[MemorySourceInfo]:
    return [_source_to_info(source) for source in list_memory_sources(request.app.state.shell)]


@router.get("/memory/providers", response_model=list[MemoryProviderInfo])
def memory_providers(request: Request) -> list[MemoryProviderInfo]:
    return [
        _provider_to_info(provider) for provider in list_memory_providers(request.app.state.shell)
    ]


@router.get("/memory/workloads", response_model=list[MemoryWorkloadInfo])
def memory_workloads() -> list[MemoryWorkloadInfo]:
    return [_workload_to_info(workload) for workload in WORKLOAD_PRESETS]


@router.post("/memory/plan", response_model=MemoryPlanInfo)
def memory_plan(body: MemoryPlanRequest, request: Request) -> MemoryPlanInfo:
    workload = _resolve_workload(body)
    provider_ids = _validate_memory_provider_ids(body.providers)
    report = scan_memory(request.app.state.shell, provider_ids=provider_ids)
    suggestions = advise(report)
    plan = plan_workload(
        report,
        workload,
        suggestions,
        safety_margin_bytes=body.safety_margin_bytes,
    )
    return _plan_to_info(plan)


@router.post("/memory/actions", response_model=MemoryActionExecuteResultInfo)
def memory_action(
    body: MemoryActionExecuteRequest,
    request: Request,
) -> MemoryActionExecuteResultInfo:
    result = execute_memory_action(
        request.app.state.shell,
        action_id=body.id,
        kind=body.kind,
        target_id=body.target_id,
        confirmed=body.confirmed,
    )
    if body.confirmed:
        with contextlib.suppress(OSError):
            _storage(request).append_audit_event(
                {
                    "type": "memory_action",
                    "action_id": body.id,
                    "action_kind": body.kind,
                    "target_id": body.target_id,
                    "label": body.label or body.id,
                    "estimated_bytes": body.estimated_bytes,
                    "risk": body.risk,
                    "status": result.status,
                    "message": result.message,
                }
            )
    return _action_result_to_info(result)


def _report_to_info(
    report: MemoryReport,
    suggestions: list[MemorySuggestion] | None = None,
    provider_ids: frozenset[str] | None = None,
) -> MemoryReportInfo:
    resolved_suggestions = suggestions if suggestions is not None else advise(report)
    return MemoryReportInfo(
        scanned_at=report.scanned_at.isoformat(),
        hostname=report.hostname,
        platform=report.platform,
        system=_system_to_info(report.system),
        consumers=[_consumer_to_info(c) for c in report.consumers],
        provider_totals=_provider_totals_to_info(report, provider_ids),
        suggestions=[_suggestion_to_info(s) for s in resolved_suggestions],
    )


def _system_to_info(system: SystemMemory) -> SystemMemoryInfo:
    return SystemMemoryInfo(
        total_bytes=system.total_bytes,
        available_bytes=system.available_bytes,
        used_bytes=system.used_bytes,
        swap_used_bytes=system.swap_used_bytes,
        compressed_bytes=system.compressed_bytes,
        pressure=system.pressure,
    )


def _consumer_to_info(consumer: MemoryConsumer) -> MemoryConsumerInfo:
    return MemoryConsumerInfo(
        id=consumer.id,
        pid=consumer.pid,
        parent_pid=consumer.parent_pid,
        name=consumer.name,
        kind=consumer.kind,
        rss_bytes=consumer.rss_bytes,
        private_bytes=consumer.private_bytes,
        command=consumer.command,
        children=[_consumer_to_info(c) for c in consumer.children],
    )


def _suggestion_to_info(suggestion: MemorySuggestion) -> MemorySuggestionInfo:
    return MemorySuggestionInfo(
        id=suggestion.id,
        title=suggestion.title,
        reason=suggestion.reason,
        estimated_bytes=suggestion.estimated_bytes,
        confidence=suggestion.confidence,
        actions=[_action_to_info(a) for a in suggestion.actions],
    )


def _action_to_info(action: MemoryAction) -> MemoryActionInfo:
    return MemoryActionInfo(
        id=action.id,
        kind=action.kind,
        label=action.label,
        target_id=action.target_id,
        estimated_bytes=action.estimated_bytes,
        risk=action.risk,
    )


def _action_result_to_info(result: MemoryActionResult) -> MemoryActionExecuteResultInfo:
    return MemoryActionExecuteResultInfo(
        action_id=result.action_id,
        status=result.status,
        message=result.message,
    )


def _storage(request: Request) -> StorageBackend:
    return cast(StorageBackend, request.app.state.storage)


def _parse_memory_provider_query(provider: str | None) -> frozenset[str] | None:
    if provider is None:
        return None
    return _validate_memory_provider_ids(provider.split(","))


def _validate_memory_provider_ids(provider_ids: Iterable[str] | None) -> frozenset[str] | None:
    if provider_ids is None:
        return None
    selected = frozenset(provider_id.strip() for provider_id in provider_ids if provider_id.strip())
    unknown = selected - memory_provider_ids()
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"unknown memory provider: {', '.join(sorted(unknown))}",
        )
    return selected


def _should_record_memory(
    storage: StorageBackend,
    report: MemoryReport,
    min_interval_ms: int | None,
) -> bool:
    latest = storage.list_memory_observations(limit=1)
    if not latest:
        return True
    previous = latest[0]
    if previous.pressure != report.system.pressure:
        return True
    if min_interval_ms is None or min_interval_ms <= 0:
        return True
    try:
        previous_at = datetime.fromisoformat(previous.scanned_at)
    except ValueError:
        return True
    age_ms = (report.scanned_at.timestamp() - previous_at.timestamp()) * 1000
    return age_ms >= min_interval_ms


def _observation_meta_to_info(meta: MemoryObservationMeta) -> MemoryObservationMetaInfo:
    return MemoryObservationMetaInfo(
        id=meta.id,
        scanned_at=meta.scanned_at,
        pressure=cast(Literal["ok", "warn", "critical", "unknown"], meta.pressure),
        total_bytes=meta.total_bytes,
        available_bytes=meta.available_bytes,
        used_bytes=meta.used_bytes,
        swap_used_bytes=meta.swap_used_bytes,
        compressed_bytes=meta.compressed_bytes,
        top_consumer_name=meta.top_consumer_name,
        top_consumer_kind=cast(
            Literal["app", "process", "browser", "electron", "docker", "llm", "other"] | None,
            meta.top_consumer_kind,
        ),
        top_consumer_rss_bytes=meta.top_consumer_rss_bytes,
        suggestion_count=meta.suggestion_count,
    )


def _snapshot_meta_to_info(meta: MemorySnapshotMeta) -> MemorySnapshotMetaInfo:
    return MemorySnapshotMetaInfo(
        name=meta.name,
        created_at=meta.created_at,
        scanned_at=meta.scanned_at,
        note=meta.note,
        pressure=cast(Literal["ok", "warn", "critical", "unknown"], meta.pressure),
        total_bytes=meta.total_bytes,
        available_bytes=meta.available_bytes,
        used_bytes=meta.used_bytes,
        top_consumer_name=meta.top_consumer_name,
        top_consumer_kind=cast(
            Literal["app", "process", "browser", "electron", "docker", "llm", "other"] | None,
            meta.top_consumer_kind,
        ),
        top_consumer_rss_bytes=meta.top_consumer_rss_bytes,
    )


def _source_to_info(source: MemorySource) -> MemorySourceInfo:
    return MemorySourceInfo(
        id=source.id,
        name=source.name,
        kind=source.kind,
        status=source.status,
        description=source.description,
        detail=source.detail,
    )


def _provider_to_info(provider: MemoryProvider) -> MemoryProviderInfo:
    return MemoryProviderInfo(
        id=provider.id,
        name=provider.name,
        kind=provider.kind,
        status=provider.status,
        description=provider.description,
        detail=provider.detail,
        consumer_kinds=list(provider.consumer_kinds),
    )


def _provider_totals_to_info(
    report: MemoryReport,
    provider_ids: frozenset[str] | None,
) -> list[MemoryProviderTotalInfo]:
    selected = None if provider_ids is None else set(provider_ids)
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    providers = memory_provider_catalog()
    for provider in providers:
        totals[provider.id] = 0
        counts[provider.id] = 0
    for consumer in report.consumers:
        for provider in providers:
            if consumer.kind in provider.consumer_kinds:
                totals[provider.id] += consumer.rss_bytes
                counts[provider.id] += 1
                break
    return [
        MemoryProviderTotalInfo(
            id=provider.id,
            name=provider.name,
            kind=provider.kind,
            selected=selected is None or provider.id in selected,
            rss_bytes=totals[provider.id],
            consumer_count=counts[provider.id],
        )
        for provider in providers
    ]


def _workload_to_info(workload: MemoryWorkload) -> MemoryWorkloadInfo:
    return MemoryWorkloadInfo(
        id=workload.id,
        label=workload.label,
        kind=workload.kind,
        required_bytes=workload.required_bytes,
        description=workload.description,
    )


def _resolve_workload(body: MemoryPlanRequest) -> MemoryWorkload:
    if body.workload_id:
        workload = get_workload(body.workload_id)
        if workload is None:
            raise HTTPException(status_code=404, detail="unknown workload")
        return workload
    if body.custom_required_bytes is None:
        raise HTTPException(status_code=422, detail="workload_id or custom_required_bytes required")
    return MemoryWorkload(
        id="custom",
        label=body.custom_label.strip() if body.custom_label else "Custom workload",
        kind="custom",
        required_bytes=body.custom_required_bytes,
        description="User-entered workload estimate.",
    )


def _plan_to_info(plan: MemoryPlan) -> MemoryPlanInfo:
    return MemoryPlanInfo(
        workload=_workload_to_info(plan.workload),
        fits_now=plan.fits_now,
        required_bytes=plan.required_bytes,
        available_bytes=plan.available_bytes,
        os_reserve_bytes=plan.os_reserve_bytes,
        safety_margin_bytes=plan.safety_margin_bytes,
        usable_bytes=plan.usable_bytes,
        deficit_bytes=plan.deficit_bytes,
        planned_reclaim_bytes=plan.planned_reclaim_bytes,
        remaining_deficit_bytes=plan.remaining_deficit_bytes,
        actions=[_plan_action_to_info(action) for action in plan.actions],
    )


def _plan_action_to_info(action: MemoryPlanAction) -> MemoryPlanActionInfo:
    return MemoryPlanActionInfo(
        suggestion_id=action.suggestion_id,
        action_id=action.action_id,
        label=action.label,
        estimated_bytes=action.estimated_bytes,
        risk=action.risk,
        confidence=action.confidence,
    )


def _memory_snapshot_diff(
    before: StoredMemorySnapshot,
    after: StoredMemorySnapshot,
) -> MemorySnapshotDiffInfo:
    before_meta = _snapshot_meta_to_info(_stored_snapshot_meta(before))
    after_meta = _snapshot_meta_to_info(_stored_snapshot_meta(after))
    before_swap = before.report.system.swap_used_bytes
    after_swap = after.report.system.swap_used_bytes
    before_compressed = before.report.system.compressed_bytes
    after_compressed = after.report.system.compressed_bytes
    before_suggestions = {s.id for s in before.suggestions}
    after_suggestions = {s.id for s in after.suggestions}
    return MemorySnapshotDiffInfo(
        before=before_meta,
        after=after_meta,
        available_delta_bytes=after.report.system.available_bytes
        - before.report.system.available_bytes,
        used_delta_bytes=after.report.system.used_bytes - before.report.system.used_bytes,
        swap_delta_bytes=None
        if before_swap is None or after_swap is None
        else after_swap - before_swap,
        compressed_delta_bytes=None
        if before_compressed is None or after_compressed is None
        else after_compressed - before_compressed,
        top_consumer_deltas=_consumer_deltas(before.report, after.report),
        added_suggestion_ids=sorted(after_suggestions - before_suggestions),
        removed_suggestion_ids=sorted(before_suggestions - after_suggestions),
    )


def _stored_snapshot_meta(stored: StoredMemorySnapshot) -> MemorySnapshotMeta:
    top = max(stored.report.consumers, key=lambda c: c.rss_bytes, default=None)
    return MemorySnapshotMeta(
        name=stored.name,
        created_at=stored.created_at,
        scanned_at=stored.report.scanned_at.isoformat(),
        note=stored.note,
        pressure=stored.report.system.pressure,
        total_bytes=stored.report.system.total_bytes,
        available_bytes=stored.report.system.available_bytes,
        used_bytes=stored.report.system.used_bytes,
        top_consumer_name=top.name if top else None,
        top_consumer_kind=top.kind if top else None,
        top_consumer_rss_bytes=top.rss_bytes if top else None,
    )


def _consumer_deltas(before: MemoryReport, after: MemoryReport) -> list[dict[str, object]]:
    before_by_key = {_consumer_key(c): c for c in before.consumers}
    after_by_key = {_consumer_key(c): c for c in after.consumers}
    rows: list[dict[str, object]] = []
    for key in sorted(set(before_by_key) | set(after_by_key)):
        before_consumer = before_by_key.get(key)
        after_consumer = after_by_key.get(key)
        before_bytes = before_consumer.rss_bytes if before_consumer else 0
        after_bytes = after_consumer.rss_bytes if after_consumer else 0
        sample = after_consumer or before_consumer
        if sample is None:
            continue
        delta = after_bytes - before_bytes
        if delta == 0:
            continue
        rows.append(
            {
                "id": key,
                "name": sample.name,
                "kind": sample.kind,
                "before_rss_bytes": before_bytes,
                "after_rss_bytes": after_bytes,
                "delta_rss_bytes": delta,
            }
        )
    rows.sort(key=lambda row: abs(cast(int, row["delta_rss_bytes"])), reverse=True)
    return rows[:10]


def _consumer_key(consumer: MemoryConsumer) -> str:
    if consumer.pid is not None:
        return f"pid:{consumer.pid}:{consumer.name}"
    return f"{consumer.kind}:{consumer.name}"
