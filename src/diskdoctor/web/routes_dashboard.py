from __future__ import annotations

from fastapi import APIRouter, Query, Request

from diskdoctor.dashboard import filter_disk_dashboard_summary
from diskdoctor.storage.base import (
    DiskDashboardEntry,
    DiskDashboardProviderTotal,
    DiskDashboardSummary,
    StorageBackend,
)
from diskdoctor.web.models import (
    DiskDashboardEntryInfo,
    DiskDashboardProviderTotalInfo,
    DiskDashboardSummaryInfo,
)

router = APIRouter(prefix="/api")

_NOTHING_ENABLED_PROVIDER = "__diskdoctor_nothing_enabled__"


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
    )


def _entry_to_info(entry: DiskDashboardEntry) -> DiskDashboardEntryInfo:
    return DiskDashboardEntryInfo(
        id=entry.id,
        provider=entry.provider,
        label=entry.label,
        size_bytes=entry.size_bytes,
        risk=entry.risk,
    )


def _provider_total_to_info(
    total: DiskDashboardProviderTotal,
) -> DiskDashboardProviderTotalInfo:
    return DiskDashboardProviderTotalInfo(
        provider=total.provider,
        bytes=total.bytes,
        count=total.count,
    )
