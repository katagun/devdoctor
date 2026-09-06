from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from devdoctor.storage.base import (
    DiskDashboardEntry,
    DiskDashboardProviderTotal,
    DiskDashboardSummary,
)
from devdoctor.types import (
    Entry,
    Report,
    Risk,
    estimated_reclaimable_bytes,
    unique_footprint_bytes,
    unique_shared_bytes,
)

MAX_DISK_DASHBOARD_ENTRIES = 64
DiskRiskValue = Literal["safe", "reclaimable", "dangerous"]


def build_disk_dashboard_summary(
    report: Report,
    *,
    max_entries: int = MAX_DISK_DASHBOARD_ENTRIES,
) -> DiskDashboardSummary:
    entries = [entry for entry in report.entries if entry.risk != Risk.DANGEROUS]
    entries.sort(key=lambda entry: entry.display_bytes, reverse=True)
    return DiskDashboardSummary(
        scanned_at=report.scanned_at.isoformat(),
        hostname=report.hostname,
        platform=report.platform,
        total_bytes=sum(entry.display_bytes for entry in entries),
        entry_count=len(entries),
        entries=[_entry_to_summary(entry) for entry in entries[:max_entries]],
        provider_totals=_provider_totals(entries),
        total_footprint_bytes=unique_footprint_bytes(entries),
        total_reclaimable_bytes=estimated_reclaimable_bytes(entries),
        total_shared_bytes=unique_shared_bytes(entries),
        unknown_reclaimable_entries=sum(entry.reclaimable_bytes is None for entry in entries),
    )


def filter_disk_dashboard_summary(
    summary: DiskDashboardSummary,
    providers: frozenset[str] | None,
) -> DiskDashboardSummary:
    if providers is None:
        return summary
    entries = [entry for entry in summary.entries if entry.provider in providers]
    totals = [total for total in summary.provider_totals if total.provider in providers]
    return DiskDashboardSummary(
        scanned_at=summary.scanned_at,
        hostname=summary.hostname,
        platform=summary.platform,
        total_bytes=sum(total.bytes for total in totals),
        entry_count=sum(total.count for total in totals),
        entries=entries,
        provider_totals=totals,
        total_footprint_bytes=sum(total.footprint_bytes or 0 for total in totals),
        total_reclaimable_bytes=sum(total.reclaimable_bytes or 0 for total in totals),
        total_shared_bytes=sum(total.shared_bytes for total in totals),
        unknown_reclaimable_entries=sum(entry.reclaimable_bytes is None for entry in entries),
    )


def disk_dashboard_summary_to_dict(summary: DiskDashboardSummary) -> dict[str, object]:
    return {
        "scanned_at": summary.scanned_at,
        "hostname": summary.hostname,
        "platform": summary.platform,
        "total_bytes": summary.total_bytes,
        "entry_count": summary.entry_count,
        "total_footprint_bytes": summary.total_footprint_bytes,
        "total_reclaimable_bytes": summary.total_reclaimable_bytes,
        "total_shared_bytes": summary.total_shared_bytes,
        "unknown_reclaimable_entries": summary.unknown_reclaimable_entries,
        "entries": [
            {
                "id": entry.id,
                "provider": entry.provider,
                "label": entry.label,
                "size_bytes": entry.size_bytes,
                "footprint_bytes": entry.footprint_bytes,
                "reclaimable_bytes": entry.reclaimable_bytes,
                "shared_bytes": entry.shared_bytes,
                "risk": entry.risk,
            }
            for entry in summary.entries
        ],
        "provider_totals": [
            {
                "provider": total.provider,
                "bytes": total.bytes,
                "count": total.count,
                "footprint_bytes": total.footprint_bytes,
                "reclaimable_bytes": total.reclaimable_bytes,
                "shared_bytes": total.shared_bytes,
            }
            for total in summary.provider_totals
        ],
    }


def disk_dashboard_summary_from_dict(payload: dict[str, object]) -> DiskDashboardSummary:
    return DiskDashboardSummary(
        scanned_at=str(payload["scanned_at"]),
        hostname=str(payload["hostname"]),
        platform=str(payload["platform"]),
        total_bytes=_int_value(payload["total_bytes"]),
        entry_count=_int_value(payload["entry_count"]),
        entries=[
            DiskDashboardEntry(
                id=str(row["id"]),
                provider=str(row["provider"]),
                label=str(row["label"]),
                size_bytes=_int_value(row["size_bytes"]),
                footprint_bytes=_optional_int(row.get("footprint_bytes")),
                reclaimable_bytes=_optional_int(row.get("reclaimable_bytes")),
                shared_bytes=_int_value(row.get("shared_bytes", 0)),
                risk=_risk_value(row["risk"]),
            )
            for row in _dict_rows(payload.get("entries"))
        ],
        provider_totals=[
            DiskDashboardProviderTotal(
                provider=str(row["provider"]),
                bytes=_int_value(row["bytes"]),
                count=_int_value(row["count"]),
                footprint_bytes=_optional_int(row.get("footprint_bytes")),
                reclaimable_bytes=_optional_int(row.get("reclaimable_bytes")),
                shared_bytes=_int_value(row.get("shared_bytes", 0)),
            )
            for row in _dict_rows(payload.get("provider_totals"))
        ],
        total_footprint_bytes=_optional_int(payload.get("total_footprint_bytes")),
        total_reclaimable_bytes=_optional_int(payload.get("total_reclaimable_bytes")),
        total_shared_bytes=_int_value(payload.get("total_shared_bytes", 0)),
        unknown_reclaimable_entries=_int_value(payload.get("unknown_reclaimable_entries", 0)),
    )


def _entry_to_summary(entry: Entry) -> DiskDashboardEntry:
    return DiskDashboardEntry(
        id=entry.id,
        provider=entry.provider,
        label=entry.label,
        size_bytes=entry.display_bytes,
        footprint_bytes=entry.footprint_bytes,
        reclaimable_bytes=entry.reclaimable_bytes,
        shared_bytes=entry.shared_bytes,
        risk=entry.risk.value,
    )


def _provider_totals(entries: Iterable[Entry]) -> list[DiskDashboardProviderTotal]:
    entries = list(entries)
    totals: dict[str, DiskDashboardProviderTotal] = {}
    for entry in entries:
        current = totals.get(entry.provider)
        if current is None:
            totals[entry.provider] = DiskDashboardProviderTotal(
                provider=entry.provider,
                bytes=entry.display_bytes,
                count=1,
                footprint_bytes=entry.footprint_bytes,
                reclaimable_bytes=entry.reclaimable_bytes,
                shared_bytes=entry.shared_bytes,
            )
        else:
            totals[entry.provider] = DiskDashboardProviderTotal(
                provider=entry.provider,
                bytes=current.bytes + entry.display_bytes,
                count=current.count + 1,
                footprint_bytes=(current.footprint_bytes or 0) + (entry.footprint_bytes or 0),
                reclaimable_bytes=(current.reclaimable_bytes or 0) + (entry.reclaimable_bytes or 0),
                shared_bytes=current.shared_bytes + entry.shared_bytes,
            )
    for provider, current in list(totals.items()):
        provider_entries = [entry for entry in entries if entry.provider == provider]
        totals[provider] = DiskDashboardProviderTotal(
            provider=current.provider,
            bytes=current.bytes,
            count=current.count,
            footprint_bytes=unique_footprint_bytes(provider_entries),
            reclaimable_bytes=estimated_reclaimable_bytes(provider_entries),
            shared_bytes=unique_shared_bytes(provider_entries),
        )
    return sorted(totals.values(), key=lambda total: total.bytes, reverse=True)


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _risk_value(value: object) -> DiskRiskValue:
    if value in ("safe", "reclaimable", "dangerous"):
        return value
    raise ValueError(f"unsupported disk dashboard risk: {value!r}")


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid integer value")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise ValueError(f"unsupported integer value: {value!r}")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int_value(value)
