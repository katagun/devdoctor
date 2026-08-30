from __future__ import annotations

import dataclasses
import logging
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from diskdoctor.providers.base import Provider
from diskdoctor.types import Entry, ProviderTiming, Report, ScanFilters, SnapshotKind

logger = logging.getLogger(__name__)

# Upper bound on discovery threads. Providers are I/O-bound (filesystem walks
# and subprocesses), so a handful of threads overlaps the blocking waits without
# oversubscribing. The actual pool size is min(this, number of available
# providers), so scans with few providers spin up correspondingly few threads.
_MAX_WORKERS = 8


def _globally_unique(entry: Entry) -> Entry:
    """Namespace a provider-local id into a globally-unique one.

    ``Entry.id`` is only guaranteed unique *within* the provider that produced
    it (docker uses "images", PathProviders use the path, ollama uses the model
    name), so two providers can legitimately emit the same bare id. The web
    clean flow keys selection and interactive prompt/confirm routing on the bare
    id (``routes_clean`` selection, ``CleanupRunner._pending_prompts``), so a
    cross-provider id clash would cross-route between entries — selecting or
    answering one would silently hit the other, and the prompt-future dict would
    collide (second future overwrites first).

    Prefixing the id with the provider (``"{provider}:{id}"``) makes it globally
    unique, since the bare id is already unique within a provider. The id is an
    opaque routing/React key — never surfaced in the UI, which displays
    ``label``/``provider``/``path`` — so namespacing changes no human-facing
    output. Old snapshots keep their bare ids and still load (the field is
    opaque and derivable); the clean flow always re-scans, so every id it
    routes on is freshly namespaced and internally consistent.
    """
    return dataclasses.replace(entry, id=f"{entry.provider}:{entry.id}")


@dataclass
class _ProviderResult:
    """The isolated output of one provider's discovery.

    Each provider runs on its own thread and produces one of these; the results
    are re-assembled in the caller's (deterministic) provider order after the
    parallel phase, so parallelism never affects the final ordering.
    """

    entries: list[Entry]
    diagnostics: list[str]
    timing: ProviderTiming


def _discover_one(p: Provider) -> _ProviderResult:
    """Run a single provider's discover() and package its result.

    Runs on a worker thread. Times the call with time.monotonic() (immune to
    NTP adjustments) and, crucially, never propagates an exception: a provider
    that raises is turned into a diagnostic note and contributes no entries, so
    one broken provider can't abort the whole scan.
    """
    t0 = time.monotonic()
    try:
        # Drop zero-byte entries before they reach the table. They represent
        # "nothing to reclaim" — most commonly cloud-hosted ollama models
        # (`ollama list` reports `-` for size, which parses to 0), but also
        # empty cache directories. Surfacing them is noise that the user
        # can't act on.
        provider_entries = [e for e in p.discover() if e.size_bytes > 0]
    except Exception as exc:  # isolate one provider's failure from the scan
        dt_ms = int((time.monotonic() - t0) * 1000)
        msg = f"{p.name}: discovery failed: {exc}"
        logger.warning("%s", msg)
        # Preserve any notes the provider recorded before it raised, then append
        # the failure so it surfaces in Report.diagnostics instead of vanishing.
        diagnostics = [*p.diagnostics, msg]
        return _ProviderResult(
            entries=[],
            diagnostics=diagnostics,
            timing=ProviderTiming(name=p.name, bytes=0, entries=0, duration_ms=dt_ms),
        )
    dt_ms = int((time.monotonic() - t0) * 1000)
    return _ProviderResult(
        entries=provider_entries,
        # Drain anything the provider flagged during discover() (skipped paths,
        # failed commands) so it surfaces in the Report instead of vanishing.
        diagnostics=list(p.diagnostics),
        timing=ProviderTiming(
            name=p.name,
            bytes=sum(e.size_bytes for e in provider_entries),
            entries=len(provider_entries),
            duration_ms=dt_ms,
        ),
    )


def scan(
    providers: list[Provider],
    filters: ScanFilters,
    now: datetime,
) -> Report:
    """Run every available provider, collect entries, apply filters, sort.

    Providers' discover() calls run concurrently in a bounded thread pool —
    they are I/O-bound (filesystem walks and subprocesses), so overlapping the
    blocking waits is a real speedup on machines with large model/Docker caches.
    Results are re-assembled in the original provider order after the parallel
    phase, so the output is byte-for-byte identical to a serial scan: `entries`
    is stable-sorted by size (ties keep provider-then-discover order), and
    `per_provider` / `diagnostics` follow provider order.

    Records per-provider and total durations via time.monotonic() so the
    timings are immune to NTP adjustments mid-scan. The returned Report
    has kind=MANUAL by default; the API layer overrides to AUTO when it's
    about to write an auto-snapshot.
    """
    started_at = datetime.now(UTC)
    # Freeze the set (and order) of available providers up front; availability
    # is cheap and synchronous, and pinning it here keeps result reassembly
    # deterministic regardless of thread completion order.
    available = [p for p in providers if p.available()]

    entries: list[Entry] = []
    per_provider: list[ProviderTiming] = []
    diagnostics: list[str] = []

    if available:
        with ThreadPoolExecutor(max_workers=min(len(available), _MAX_WORKERS)) as executor:
            # executor.map preserves input order, so iterating the results
            # yields them in provider order no matter which thread finished
            # first. _discover_one swallows provider exceptions, so .result()
            # (inside map) never raises here.
            results = list(executor.map(_discover_one, available))
        for result in results:
            # Namespace each entry's provider-local id into a globally-unique
            # one so web selection and prompt/confirm routing can never cross
            # providers. Per-provider timings were computed pre-namespacing from
            # the same entries, so byte/count totals are unaffected.
            entries.extend(_globally_unique(e) for e in result.entries)
            diagnostics.extend(result.diagnostics)
            per_provider.append(result.timing)

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
