from __future__ import annotations

from fastapi import APIRouter, Query, Request

from devdoctor.dashboard import filter_disk_dashboard_summary
from devdoctor.storage.base import (
    DiskDashboardEntry,
    DiskDashboardProviderTotal,
    DiskDashboardSummary,
    StorageBackend,
)
from devdoctor.web.models import (
    DiskDashboardEntryInfo,
    DiskDashboardProviderTotalInfo,
    DiskDashboardSummaryInfo,
)

router = APIRouter(prefix="/api")

_NOTHING_ENABLED_PROVIDER = "__devdoctor_nothing_enabled__"


@router.get("/dashboard/disk-summary", response_model=DiskDashboardSummaryInfo | None)
def disk_dashboard_summary(
    request: Request,
    provider: str | None = Query(default=None),
) -> DiskDashboardSummaryInfo | None:
    storage: StorageBackend = request.app.state.storage
    summary = storage.load_disk_dashboard_summary()
    if summary is None:
        return None
    return _summary_to_info(filter_disk_dashboard_summary(summary, _parse_providers(provider)))


def _parse_providers(provider: str | None) -> frozenset[str] | None:
    if provider is None:
        return None
    if provider == _NOTHING_ENABLED_PROVIDER:
        return frozenset()
    return frozenset(part for part in provider.split(",") if part)


def _summary_to_info(summary: DiskDashboardSummary) -> DiskDashboardSummaryInfo:
    return DiskDashboardSummaryInfo(
        scanned_at=summary.scanned_at,
        hostname=summary.hostname,
        platform=summary.platform,
        total_bytes=summary.total_bytes,
        entry_count=summary.entry_count,
        entries=[_entry_to_info(entry) for entry in summary.entries],
        provider_totals=[_provider_total_to_info(total) for total in summary.provider_totals],
        # Without these the UI falls back to total_bytes and shows the footprint as
        # "estimated reclaimable" (#102).
        total_footprint_bytes=summary.total_footprint_bytes,
        total_reclaimable_bytes=summary.total_reclaimable_bytes,
        total_shared_bytes=summary.total_shared_bytes,
        unknown_reclaimable_entries=summary.unknown_reclaimable_entries,
    )


def _entry_to_info(entry: DiskDashboardEntry) -> DiskDashboardEntryInfo:
    return DiskDashboardEntryInfo(
        id=entry.id,
        provider=entry.provider,
        label=entry.label,
        size_bytes=entry.size_bytes,
        risk=entry.risk,
        footprint_bytes=entry.footprint_bytes,
        reclaimable_bytes=entry.reclaimable_bytes,
        shared_bytes=entry.shared_bytes,
    )


def _provider_total_to_info(
    total: DiskDashboardProviderTotal,
) -> DiskDashboardProviderTotalInfo:
    return DiskDashboardProviderTotalInfo(
        provider=total.provider,
        bytes=total.bytes,
        count=total.count,
        footprint_bytes=total.footprint_bytes,
        reclaimable_bytes=total.reclaimable_bytes,
        shared_bytes=total.shared_bytes,
    )
