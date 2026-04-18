from __future__ import annotations

import socket
import sys
from datetime import datetime

from diskdoctor.providers.base import Provider
from diskdoctor.types import Report, ScanFilters


def scan(
    providers: list[Provider],
    filters: ScanFilters,
    now: datetime,
) -> Report:
    """Run every available provider, collect entries, apply filters, sort."""
    entries = []
    for p in providers:
        if not p.available():
            continue
        entries.extend(p.discover())

    entries.sort(key=lambda e: e.size_bytes, reverse=True)

    report = Report(
        entries=entries,
        scanned_at=now,
        hostname=socket.gethostname(),
        platform=_platform(),
    )

    if filters.min_size_bytes or filters.risks is not None or filters.providers is not None:
        report = report.filter(
            risks=filters.risks,
            min_size=filters.min_size_bytes,
            providers=filters.providers,
        )

    return report


def _platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform
