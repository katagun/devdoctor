from __future__ import annotations

import dataclasses
import logging
import socket
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

from devdoctor.containment import contain_worktree_contents
from devdoctor.providers.base import Provider
from devdoctor.types import (
    DiskUsage,
    Entry,
    ProviderTiming,
    Report,
    ScanFilters,
    SnapshotKind,
    estimated_reclaimable_bytes,
    unique_footprint_bytes,
    unique_shared_bytes,
)

logger = logging.getLogger(__name__)

# Upper bound on discovery threads. Providers are I/O-bound (filesystem walks
# and subprocesses), so a handful of threads overlaps the blocking waits without
# oversubscribing. The actual pool size is min(this, number of available
# providers), so scans with few providers spin up correspondingly few threads.
_MAX_WORKERS = 8


@dataclass(frozen=True)
class ScanStarted:
    """Emitted once, before any provider runs; names the available providers in order."""

    providers: tuple[str, ...]


@dataclass(frozen=True)
class ProviderStarted:
    """Emitted from the worker thread when a provider's discover() begins."""

    name: str


@dataclass(frozen=True)
class ProviderFinished:
    """Emitted from the worker thread when a provider returns or fails.

    ``timing`` is what ``_discover_one`` computed: bytes and entries before
    reconciliation and containment. Right for "found so far"; the report's
    totals still come only from ``scan()``'s return value.
    """

    timing: ProviderTiming


ScanProgressEvent = ScanStarted | ProviderStarted | ProviderFinished
ScanProgressCallback = Callable[[ScanProgressEvent], None]


def _notify(on_progress: ScanProgressCallback | None, event: ScanProgressEvent) -> None:
    """Deliver one event; a consumer that raises is logged and can never alter a scan."""
    if on_progress is None:
        return
    try:
        on_progress(event)
    except Exception:
        logger.warning("scan progress callback failed on %s", type(event).__name__, exc_info=True)


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

    ``covers`` holds provider-local ids too, and the cleanup rule matches them
    against (namespaced) entry ids — so they are namespaced with the same
    prefix, keeping coverer and covered mutually consistent.
    """
    return dataclasses.replace(
        entry,
        id=f"{entry.provider}:{entry.id}",
        covers=tuple(f"{entry.provider}:{covered}" for covered in entry.covers),
    )


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


def _reconcile_shared_usage(entries: list[Entry]) -> list[Entry]:
    """Annotate hard-linked allocations after deterministic result assembly."""
    by_inode: dict[
        tuple[int, int],
        dict[int, tuple[int, set[str]]],
    ] = {}
    for index, entry in enumerate(entries):
        for record in entry.hardlinks:
            members = by_inode.setdefault(record.key, {})
            current = members.get(index)
            paths = set(record.paths)
            if current is None:
                members[index] = (record.link_count, paths)
            else:
                members[index] = (max(current[0], record.link_count), current[1] | paths)

    shared_by_entry = [0] * len(entries)
    for key, members in by_inode.items():
        records = [
            record for index in members for record in entries[index].hardlinks if record.key == key
        ]
        if not records:
            continue
        allocated = records[0].allocated_bytes
        for index, (link_count, paths) in members.items():
            if len(paths) < link_count:
                shared_by_entry[index] += allocated

    reconciled: list[Entry] = []
    for entry, discovered_shared in zip(entries, shared_by_entry, strict=True):
        usage = entry.usage or DiskUsage(entry.size_bytes, entry.size_bytes)
        shared = max(usage.shared_bytes, discovered_shared)
        reclaimable = usage.reclaimable_bytes
        additional_shared = max(0, discovered_shared - usage.shared_bytes)
        if reclaimable is not None and additional_shared:
            reclaimable = max(0, reclaimable - additional_shared)
        reconciled.append(
            dataclasses.replace(
                entry,
                usage=DiskUsage(
                    footprint_bytes=usage.footprint_bytes,
                    reclaimable_bytes=reclaimable,
                    shared_bytes=shared,
                ),
            )
        )
    return reconciled


def _discover_one(p: Provider, on_progress: ScanProgressCallback | None = None) -> _ProviderResult:
    """Run a single provider's discover() and package its result.

    Runs on a worker thread. Times the call with time.monotonic() (immune to
    NTP adjustments) and, crucially, never propagates an exception: a provider
    that raises is turned into a diagnostic note and contributes no entries, so
    one broken provider can't abort the whole scan.
    """
    _notify(on_progress, ProviderStarted(p.name))
    t0 = time.monotonic()
    try:
        # Drop zero-byte entries before they reach the table. They represent
        # "nothing to reclaim" — most commonly cloud-hosted ollama models
        # (`ollama list` reports `-` for size, which parses to 0), but also
        # empty cache directories. Surfacing them is noise that the user
        # can't act on. Entries a provider deliberately left unmeasured
        # (`DiskUsage(None, None)`, such as advice-only git worktrees) are kept:
        # their size is unknown, not zero.
        provider_entries = [e for e in p.discover() if e.display_bytes > 0 or e.is_unmeasured]
    except Exception as exc:  # isolate one provider's failure from the scan
        dt_ms = int((time.monotonic() - t0) * 1000)
        msg = f"{p.name}: discovery failed: {exc}"
        logger.warning("%s", msg)
        # Preserve any notes the provider recorded before it raised, then append
        # the failure so it surfaces in Report.diagnostics instead of vanishing.
        diagnostics = [*p.diagnostics, msg]
        result = _ProviderResult(
            entries=[],
            diagnostics=diagnostics,
            timing=ProviderTiming(name=p.name, bytes=0, entries=0, duration_ms=dt_ms),
        )
        _notify(on_progress, ProviderFinished(result.timing))
        return result
    dt_ms = int((time.monotonic() - t0) * 1000)
    result = _ProviderResult(
        entries=provider_entries,
        # Drain anything the provider flagged during discover() (skipped paths,
        # failed commands) so it surfaces in the Report instead of vanishing.
        diagnostics=list(p.diagnostics),
        timing=ProviderTiming(
            name=p.name,
            bytes=sum(e.size_bytes for e in provider_entries),
            entries=len(provider_entries),
            duration_ms=dt_ms,
            footprint_bytes=sum(e.footprint_bytes or 0 for e in provider_entries),
            reclaimable_bytes=sum(e.reclaimable_bytes or 0 for e in provider_entries),
            shared_bytes=sum(e.shared_bytes for e in provider_entries),
        ),
    )
    _notify(on_progress, ProviderFinished(result.timing))
    return result


def scan(
    providers: list[Provider],
    filters: ScanFilters,
    now: datetime,
    *,
    contain: bool = True,
    on_progress: ScanProgressCallback | None = None,
) -> Report:
    """Run every available provider the filters name, collect entries, filter, sort.

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

    With ``contain`` (the default), entries inside a reclaimable git worktree that
    the filtered view shows are removed, so their bytes count once, under
    ``git-worktrees``. Provider totals always use full containment, independent of
    the view's filters, so a filtered scan never counts a byte twice (spec §6.3).
    The web cleanup scan passes ``contain=False``: it establishes current state for
    a selection, not what to display (spec §6.4).

    ``on_progress`` receives ``ScanStarted`` once, then ``ProviderStarted``/
    ``ProviderFinished`` per available provider from the worker threads; a raising
    callback is logged and ignored (spec §3).
    """
    started_at = datetime.now(UTC)
    # Freeze the set (and order) of available providers up front; availability
    # is cheap and synchronous, and pinning it here keeps result reassembly
    # deterministic regardless of thread completion order.
    #
    # A provider filter is applied here, before anything runs (#92): a provider the
    # view will not show is never asked whether it is available, let alone walked.
    # Filtered scans are never stored or summarised (``ScanFilters.is_unfiltered``),
    # so their totals only ever describe the providers that ran. Risk and size
    # filters cannot be decided without the entries and still apply afterwards.
    wanted = [p for p in providers if filters.providers is None or p.name in filters.providers]
    available = [p for p in wanted if p.available()]

    _notify(on_progress, ScanStarted(providers=tuple(p.name for p in available)))

    entries: list[Entry] = []
    per_provider: list[ProviderTiming] = []
    diagnostics: list[str] = []

    if available:
        with ThreadPoolExecutor(max_workers=min(len(available), _MAX_WORKERS)) as executor:
            # executor.map preserves input order, so iterating the results
            # yields them in provider order no matter which thread finished
            # first. _discover_one swallows provider exceptions, so .result()
            # (inside map) never raises here.
            results = list(executor.map(partial(_discover_one, on_progress=on_progress), available))
        for result in results:
            # Namespace each entry's provider-local id into a globally-unique
            # one so web selection and prompt/confirm routing can never cross
            # providers. Per-provider timings were computed pre-namespacing from
            # the same entries, so byte/count totals are unaffected.
            entries.extend(_globally_unique(e) for e in result.entries)
            diagnostics.extend(result.diagnostics)
            per_provider.append(result.timing)

    entries = _reconcile_shared_usage(entries)
    if contain:
        # Totals are whole-scan totals: full containment, whatever the view shows (§6.3).
        per_provider = _recompute_provider_totals(
            per_provider, contain_worktree_contents(entries, ScanFilters())
        )
        entries = contain_worktree_contents(entries, filters)
    else:
        per_provider = _recompute_provider_totals(per_provider, entries)

    scanned_at = datetime.now(UTC)
    duration_ms = int((scanned_at - started_at).total_seconds() * 1000)

    entries.sort(key=lambda e: e.display_bytes, reverse=True)

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

    if not filters.is_unfiltered:
        report = report.filter(
            risks=filters.risks,
            min_size=filters.min_size_bytes,
            providers=filters.providers,
        )

    return report


def _recompute_provider_totals(
    per_provider: list[ProviderTiming], entries: list[Entry]
) -> list[ProviderTiming]:
    """Recompute every provider total from the reconciled, contained entry list.

    ``bytes`` and ``entries`` were first computed in ``_discover_one``, before
    containment; ``history.diff`` sums ``bytes``, so leaving them would count
    contained bytes twice (spec §6.3).
    """
    by_provider: dict[str, list[Entry]] = {}
    for entry in entries:
        by_provider.setdefault(entry.provider, []).append(entry)
    totals: list[ProviderTiming] = []
    for timing in per_provider:
        own = by_provider.get(timing.name, [])
        totals.append(
            dataclasses.replace(
                timing,
                bytes=sum(entry.size_bytes for entry in own),
                entries=len(own),
                footprint_bytes=unique_footprint_bytes(own),
                reclaimable_bytes=estimated_reclaimable_bytes(own),
                shared_bytes=unique_shared_bytes(own),
            )
        )
    return totals


def _platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform
