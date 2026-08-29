from __future__ import annotations

import logging
import socket
import sys
import time
from datetime import UTC, datetime

from diskdoctor.providers.base import Provider
from diskdoctor.types import ProviderTiming, Report, ScanFilters, SnapshotKind

logger = logging.getLogger(__name__)


def scan(
    providers: list[Provider],
    filters: ScanFilters,
    now: datetime,
) -> Report:
    """Run every available provider, collect entries, apply filters, sort.

    Records per-provider and total durations via time.monotonic() so the
    timings are immune to NTP adjustments mid-scan. The returned Report
    has kind=MANUAL by default; the API layer overrides to AUTO when it's
    about to write an auto-snapshot.
    """
    started_at = datetime.now(UTC)
    entries = []
    per_provider: list[ProviderTiming] = []
    diagnostics: list[str] = []
    for p in providers:
        if not p.available():
            continue
        t0 = time.monotonic()
        # Drop zero-byte entries before they reach the table. They represent
        # "nothing to reclaim" — most commonly cloud-hosted ollama models
        # (`ollama list` reports `-` for size, which parses to 0), but also
        # empty cache directories. Surfacing them is noise that the user
        # can't act on.
        provider_entries = [e for e in p.discover() if e.size_bytes > 0]
        dt_ms = int((time.monotonic() - t0) * 1000)
        entries.extend(provider_entries)
        # Drain anything the provider flagged during discover() (skipped paths,
        # failed commands) so it surfaces in the Report instead of vanishing.
        diagnostics.extend(p.diagnostics)
        per_provider.append(
            ProviderTiming(
                name=p.name,
                bytes=sum(e.size_bytes for e in provider_entries),
                entries=len(provider_entries),
                duration_ms=dt_ms,
            )
        )
    scanned_at = datetime.now(UTC)
    duration_ms = int((scanned_at - started_at).total_seconds() * 1000)

    entries.sort(key=lambda e: e.size_bytes, reverse=True)

    if diagnostics:
        logger.info("scan completed with %d diagnostic note(s)", len(diagnostics))

    report = Report(
        entries=entries,
        scanned_at=scanned_at,
        hostname=socket.gethostname(),
        platform=_platform(),
        kind=SnapshotKind.MANUAL,
        started_at=started_at,
        duration_ms=duration_ms,
        per_provider=per_provider,
        diagnostics=diagnostics,
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
