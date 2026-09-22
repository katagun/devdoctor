import dataclasses
import threading
from datetime import UTC, datetime
from pathlib import Path

from devdoctor import discovery
from devdoctor.cleanup import run
from devdoctor.discovery import scan
from devdoctor.providers.base import Provider
from devdoctor.types import (
    CleanupOpts,
    CommandAction,
    DiskUsage,
    Entry,
    Risk,
    ScanFilters,
    ShellResult,
    SnapshotKind,
)
from tests.conftest import FakeShell


class _Stub(Provider):
    def __init__(self, shell, name, entries, *, available=True):
        super().__init__(shell)
        self.name = name
        self.description = ""
        self.platforms = ("darwin", "linux")
        self.risk = Risk.SAFE
        self._entries = entries
        self._available = available

    def available(self) -> bool:
        return self._available

    def discover(self) -> list[Entry]:
        return self._entries


def _e(provider, id_, size, risk=Risk.SAFE) -> Entry:
    return Entry(
        provider, id_, Path(f"/{id_}"), f"{provider}/{id_}", size, None, risk, [f"rm -rf /{id_}"]
    )


def test_scan_iterates_providers_and_collects_entries():
    p1 = _Stub(FakeShell(), "a", [_e("a", "1", 100)])
    p2 = _Stub(FakeShell(), "b", [_e("b", "1", 200)])
    r = scan([p1, p2], ScanFilters(), datetime(2026, 4, 18, tzinfo=UTC))
    assert {e.provider for e in r.entries} == {"a", "b"}
    assert r.total_bytes() == 300


def test_scan_namespaces_ids_to_avoid_cross_provider_collision():
    """Roadmap #12: two providers may emit the same provider-local id (docker
    uses "images", ollama a model name, PathProviders a path). scan namespaces
    each id into a globally-unique "{provider}:{id}" so web selection and
    prompt/confirm routing — which key on the bare id — can never cross-route
    between providers. The pre-fix behaviour would have produced two entries
    with the identical id "images"."""
    docker = _Stub(FakeShell(), "docker", [_e("docker", "images", 100)])
    ollama = _Stub(FakeShell(), "ollama", [_e("ollama", "images", 200)])
    r = scan([docker, ollama], ScanFilters(), datetime(2026, 4, 18, tzinfo=UTC))

    ids = {e.id for e in r.entries}
    assert ids == {"docker:images", "ollama:images"}  # globally unique
    assert len(ids) == len(r.entries)  # no collision
    # Provider-local id is recoverable and the human-facing label is untouched.
    by_provider = {e.provider: e for e in r.entries}
    assert by_provider["docker"].label == "docker/images"
    assert by_provider["ollama"].label == "ollama/images"


class _Counting(_Stub):
    """A stub that records whether discovery ever ran."""

    def __init__(self, shell, name, entries):
        super().__init__(shell, name, entries)
        self.discover_calls = 0
        self.available_calls = 0

    def available(self) -> bool:
        self.available_calls += 1
        return True

    def discover(self) -> list[Entry]:
        self.discover_calls += 1
        return super().discover()


def test_a_provider_filter_runs_only_the_named_providers():
    """#92: the filter used to apply after every provider had already run."""
    wanted = _Counting(FakeShell(), "a", [_e("a", "1", 100)])
    other = _Counting(FakeShell(), "b", [_e("b", "1", 200)])
    events, on_progress = _collect_progress()

    r = scan(
        [wanted, other],
        ScanFilters(providers=frozenset({"a"})),
        datetime(2026, 4, 18, tzinfo=UTC),
        on_progress=on_progress,
    )

    assert (wanted.discover_calls, other.discover_calls) == (1, 0)
    assert other.available_calls == 0  # availability can shell out; skip that too
    assert [e.provider for e in r.entries] == ["a"]
    assert [pt.name for pt in r.per_provider] == ["a"]
    assert events[0] == discovery.ScanStarted(providers=("a",))


def test_a_skipped_provider_contributes_no_diagnostics():
    class _Noisy(_Stub):
        def discover(self) -> list[Entry]:
            self.diagnostics.append("b: something irrelevant to this view")
            return super().discover()

    wanted = _Stub(FakeShell(), "a", [_e("a", "1", 100)])
    noisy = _Noisy(FakeShell(), "b", [_e("b", "1", 200)])
    r = scan(
        [wanted, noisy], ScanFilters(providers=frozenset({"a"})), datetime(2026, 4, 18, tzinfo=UTC)
    )
    assert r.diagnostics == []


def test_risk_and_size_filters_still_run_every_provider():
    a = _Counting(FakeShell(), "a", [_e("a", "1", 100)])
    b = _Counting(FakeShell(), "b", [_e("b", "1", 200, risk=Risk.DANGEROUS)])
    scan([a, b], ScanFilters(risks=frozenset({Risk.SAFE})), datetime(2026, 4, 18, tzinfo=UTC))
    assert (a.discover_calls, b.discover_calls) == (1, 1)


def test_scan_skips_unavailable_providers():
    p1 = _Stub(FakeShell(), "a", [_e("a", "1", 100)])
    p2 = _Stub(FakeShell(), "b", [_e("b", "1", 200)], available=False)
    r = scan([p1, p2], ScanFilters(), datetime(2026, 4, 18, tzinfo=UTC))
    assert {e.provider for e in r.entries} == {"a"}


def test_scan_sorts_entries_desc_by_size():
    p = _Stub(FakeShell(), "a", [_e("a", "1", 100), _e("a", "2", 500), _e("a", "3", 200)])
    r = scan([p], ScanFilters(), datetime(2026, 4, 18, tzinfo=UTC))
    assert [e.size_bytes for e in r.entries] == [500, 200, 100]


def test_scan_applies_filters():
    p = _Stub(
        FakeShell(),
        "a",
        [_e("a", "1", 100, Risk.SAFE), _e("a", "2", 500, Risk.DANGEROUS)],
    )
    r = scan(
        [p],
        ScanFilters(risks=frozenset({Risk.SAFE})),
        datetime(2026, 4, 18, tzinfo=UTC),
    )
    # scan namespaces provider-local ids into globally-unique "{provider}:{id}".
    assert [e.id for e in r.entries] == ["a:1"]


def test_scan_populates_metadata():
    p = _Stub(FakeShell(), "a", [])
    now = datetime(2026, 4, 18, tzinfo=UTC)
    r = scan([p], ScanFilters(), now)
    assert r.scanned_at is not None  # now determined internally via datetime.now(UTC)
    assert r.hostname  # something populated
    assert r.platform in {"darwin", "linux"}


def test_platform_linux_branch(monkeypatch):
    monkeypatch.setattr(discovery.sys, "platform", "linux2")
    assert discovery._platform() == "linux"


def test_platform_other_fallthrough(monkeypatch):
    monkeypatch.setattr(discovery.sys, "platform", "freebsd13")
    assert discovery._platform() == "freebsd13"


# New tests for Task 2: Timing instrumentation


class _FakeProvider(Provider):
    """Minimal Provider that returns a fixed list of Entries."""

    name = "fake"
    description = "fake"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = None

    def __init__(self, shell=None, entries=None, name: str = "fake") -> None:
        super().__init__(shell)
        self._entries = entries or []
        self.name = name  # type: ignore[misc]

    def available(self) -> bool:
        return True

    def discover(self) -> list[Entry]:
        return list(self._entries)


def _fe(provider: str = "fake", size: int = 100) -> Entry:
    return Entry(
        provider=provider,
        id=f"{provider}-1",
        path=Path("/tmp/x"),
        label="/tmp/x",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=[],
    )


def test_scan_returns_timing_fields() -> None:
    p = _FakeProvider(entries=[_fe(size=100)])
    report = discovery.scan([p], ScanFilters(), datetime.now(UTC))
    assert report.started_at is not None
    assert report.duration_ms is not None
    assert report.duration_ms >= 0
    assert report.kind == SnapshotKind.MANUAL  # discovery.scan defaults to manual


def test_scan_per_provider_row_per_available_provider() -> None:
    p1 = _FakeProvider(name="a", entries=[_fe(provider="a", size=100), _fe(provider="a", size=200)])
    p2 = _FakeProvider(name="b", entries=[_fe(provider="b", size=500)])
    report = discovery.scan([p1, p2], ScanFilters(), datetime.now(UTC))
    names = [pt.name for pt in report.per_provider]
    assert set(names) == {"a", "b"}
    timings = {pt.name: pt for pt in report.per_provider}
    assert timings["a"].bytes == 300
    assert timings["a"].entries == 2
    assert timings["a"].duration_ms >= 0
    assert timings["b"].bytes == 500
    assert timings["b"].entries == 1


def test_scan_drops_zero_byte_entries() -> None:
    """0B entries — most commonly cloud-hosted ollama models that show up in
    `ollama list` with size `-` — represent nothing reclaimable. They must
    not appear in the scan results or skew per-provider counts."""
    p = _FakeProvider(
        name="ollama",
        entries=[
            _fe(provider="ollama", size=1_400_000_000),  # local model
            _fe(provider="ollama", size=0),  # cloud model
        ],
    )
    report = discovery.scan([p], ScanFilters(), datetime.now(UTC))
    assert [e.size_bytes for e in report.entries] == [1_400_000_000]
    [timing] = [pt for pt in report.per_provider if pt.name == "ollama"]
    assert timing.entries == 1
    assert timing.bytes == 1_400_000_000


def test_scan_skips_unavailable_providers_in_timings() -> None:
    class _Unavailable(_FakeProvider):
        def available(self) -> bool:
            return False

    avail = _FakeProvider(name="a", entries=[_fe(provider="a")])
    unavail = _Unavailable(name="b", entries=[_fe(provider="b")])
    report = discovery.scan([avail, unavail], ScanFilters(), datetime.now(UTC))
    names = [pt.name for pt in report.per_provider]
    assert names == ["a"]


# Parallelization (roadmap issue #9): providers now discover concurrently in a
# thread pool. These tests pin the invariants that make the parallel scan
# byte-for-byte identical to the old serial one, plus the error isolation.


class _Raising(Provider):
    """Provider whose discover() raises, to exercise per-provider isolation."""

    def __init__(self, shell, name: str, exc: Exception) -> None:
        super().__init__(shell)
        self.name = name  # type: ignore[misc]
        self.description = ""  # type: ignore[misc]
        self.platforms = ("darwin", "linux")  # type: ignore[misc]
        self.risk = Risk.SAFE  # type: ignore[misc]
        self._exc = exc

    def available(self) -> bool:
        return True

    def discover(self) -> list[Entry]:
        raise self._exc


def test_scan_isolates_provider_that_raises() -> None:
    """A provider raising in discover() must not abort the scan: the healthy
    providers still contribute their entries and a diagnostic surfaces the
    failure."""
    good_a = _Stub(FakeShell(), "a", [_e("a", "1", 100)])
    boom = _Raising(FakeShell(), "boom", RuntimeError("disk gremlins"))
    good_b = _Stub(FakeShell(), "b", [_e("b", "1", 200)])

    report = discovery.scan([good_a, boom, good_b], ScanFilters(), datetime.now(UTC))

    assert {e.provider for e in report.entries} == {"a", "b"}
    assert report.total_bytes() == 300
    # The failing provider is surfaced as a diagnostic, not swallowed.
    assert any("boom" in d and "disk gremlins" in d for d in report.diagnostics)
    # It still gets a (zero) timing row and contributes no entries.
    boom_timing = {pt.name: pt for pt in report.per_provider}["boom"]
    assert boom_timing.entries == 0
    assert boom_timing.bytes == 0


def test_scan_preserves_diagnostics_recorded_before_a_raise() -> None:
    """Notes the provider accumulated before it blew up are not lost."""

    class _NotesThenRaises(_Raising):
        def discover(self) -> list[Entry]:
            self.diagnostics.append("boom: skipped 1 path(s)")
            raise self._exc

    p = _NotesThenRaises(FakeShell(), "boom", RuntimeError("kaboom"))
    report = discovery.scan([p], ScanFilters(), datetime.now(UTC))
    assert "boom: skipped 1 path(s)" in report.diagnostics
    assert any("kaboom" in d for d in report.diagnostics)


def test_scan_ordering_is_deterministic_across_providers() -> None:
    """Entries, per_provider, and diagnostics keep a stable, provider-then-
    discover order regardless of which worker thread finishes first. Ties in
    size (200 appears twice) must keep provider order (a before c)."""
    pa = _Stub(FakeShell(), "a", [_e("a", "1", 200), _e("a", "2", 100)])
    pb = _Stub(FakeShell(), "b", [_e("b", "1", 500)])
    pc = _Stub(FakeShell(), "c", [_e("c", "1", 200)])
    providers = [pa, pb, pc]

    # Run several times; a correct implementation is identical every time.
    first = discovery.scan(providers, ScanFilters(), datetime.now(UTC))
    # ids are namespaced "{provider}:{id}" by scan; ordering is unaffected.
    baseline = [(e.provider, e.id, e.size_bytes) for e in first.entries]
    assert baseline == [
        ("b", "b:1", 500),
        ("a", "a:1", 200),
        ("c", "c:1", 200),
        ("a", "a:2", 100),
    ]
    assert [pt.name for pt in first.per_provider] == ["a", "b", "c"]
    for _ in range(20):
        r = discovery.scan(providers, ScanFilters(), datetime.now(UTC))
        assert [(e.provider, e.id, e.size_bytes) for e in r.entries] == baseline
        assert [pt.name for pt in r.per_provider] == ["a", "b", "c"]


def test_scan_parallel_matches_serial_reference() -> None:
    """The parallel scan reproduces exactly what an equivalent serial pass over
    the same available providers would produce."""
    providers = [
        _Stub(FakeShell(), name, [_e(name, str(i), (i + 1) * 111) for i in range(3)])
        for name in ("p0", "p1", "p2", "p3", "p4")
    ]
    report = discovery.scan(providers, ScanFilters(), datetime.now(UTC))

    # Serial reference: same collect-then-stable-sort, no threads. Mirror the
    # provider-namespacing scan applies so the two are compared like-for-like.
    ref: list[Entry] = []
    for p in providers:
        ref.extend(e for e in p.discover() if e.size_bytes > 0)
    ref.sort(key=lambda e: e.size_bytes, reverse=True)

    assert [(e.provider, e.id, e.size_bytes) for e in report.entries] == [
        (e.provider, f"{e.provider}:{e.id}", e.size_bytes) for e in ref
    ]


def test_scan_shares_shell_safely_across_concurrent_providers() -> None:
    """A single shell instance shared by many providers is exercised
    concurrently; the FakeShell lock keeps its call log consistent and every
    provider's entries come through."""
    shell = FakeShell()

    class _ShellCaller(_FakeProvider):
        def discover(self) -> list[Entry]:
            for _ in range(50):
                shell.which("git")  # touch shared shell state under threads
            return list(self._entries)

    providers = [
        _ShellCaller(shell=shell, name=f"s{i}", entries=[_fe(provider=f"s{i}", size=100 + i)])
        for i in range(12)
    ]
    report = discovery.scan(providers, ScanFilters(), datetime.now(UTC))
    assert {e.provider for e in report.entries} == {f"s{i}" for i in range(12)}
    assert len(report.per_provider) == 12


def test_scan_keeps_unmeasured_entries_but_drops_measured_zero() -> None:
    unmeasured = dataclasses.replace(
        _fe(provider="git-worktrees", size=0), id="advice", usage=DiskUsage(None, None)
    )
    measured_zero = dataclasses.replace(
        _fe(provider="git-worktrees", size=0), id="empty", usage=DiskUsage(0, 0)
    )
    p = _FakeProvider(name="git-worktrees", entries=[unmeasured, measured_zero])
    report = discovery.scan([p], ScanFilters(), datetime.now(UTC))
    assert [e.id for e in report.entries] == ["git-worktrees:advice"]
    [timing] = report.per_provider
    assert (timing.entries, timing.bytes) == (1, 0)


def test_scan_min_size_hides_unmeasured_entries() -> None:
    unmeasured = dataclasses.replace(_fe(size=0), usage=DiskUsage(None, None))
    p = _FakeProvider(entries=[unmeasured, _fe(size=500)])
    report = discovery.scan([p], ScanFilters(min_size_bytes=1), datetime.now(UTC))
    assert [e.size_bytes for e in report.entries] == [500]


def _at(provider: str, path: str, size: int, risk: Risk = Risk.RECLAIMABLE) -> Entry:
    return dataclasses.replace(
        _fe(provider=provider, size=size),
        id=path,
        path=Path(path),
        label=path,
        risk=risk,
        usage=DiskUsage(size, size),
    )


def _worktree_scan(filters: ScanFilters | None = None, **kwargs):
    worktrees = _FakeProvider(
        name="git-worktrees", entries=[_at("git-worktrees", "/p/wt/feature", 1_000)]
    )
    node = _FakeProvider(
        name="node-project-dependencies",
        entries=[
            _at("node-project-dependencies", "/p/wt/feature/node_modules", 600),
            _at("node-project-dependencies", "/p/app/node_modules", 300),
            _at("node-project-dependencies", "/p/wt/feature/web/node_modules", 50, Risk.DANGEROUS),
        ],
    )
    return discovery.scan([worktrees, node], filters or ScanFilters(), datetime.now(UTC), **kwargs)


def test_scan_contains_entries_inside_a_reclaimable_worktree() -> None:
    report = _worktree_scan()
    assert sorted(str(e.path) for e in report.entries) == ["/p/app/node_modules", "/p/wt/feature"]
    timings = {pt.name: pt for pt in report.per_provider}
    assert (
        timings["node-project-dependencies"].bytes,
        timings["node-project-dependencies"].entries,
    ) == (300, 1)
    assert timings["node-project-dependencies"].footprint_bytes == 300
    assert (timings["git-worktrees"].bytes, timings["git-worktrees"].entries) == (1_000, 1)
    assert sum(pt.bytes for pt in report.per_provider) == report.total_bytes() == 1_300


def test_scan_without_containment_keeps_every_entry() -> None:
    report = _worktree_scan(contain=False)
    assert len(report.entries) == 4
    timings = {pt.name: pt for pt in report.per_provider}
    assert timings["node-project-dependencies"].entries == 3


def test_scan_keeps_contents_when_the_filters_hide_the_worktree() -> None:
    report = _worktree_scan(ScanFilters(risks=frozenset({Risk.DANGEROUS})))
    assert [str(e.path) for e in report.entries] == ["/p/wt/feature/web/node_modules"]


def test_scan_with_a_provider_filter_excluding_worktrees_contains_nothing() -> None:
    report = _worktree_scan(ScanFilters(providers=frozenset({"node-project-dependencies"})))
    assert len(report.entries) == 3


def test_provider_totals_ignore_the_view_filters() -> None:
    unfiltered = {pt.name: pt.bytes for pt in _worktree_scan().per_provider}
    report = _worktree_scan(ScanFilters(risks=frozenset({Risk.DANGEROUS})))
    assert {pt.name: pt.bytes for pt in report.per_provider} == unfiltered
    assert sum(pt.bytes for pt in report.per_provider) == 1_300


def _collect_progress() -> tuple[list[discovery.ScanProgressEvent], discovery.ScanProgressCallback]:
    """A thread-safe sink for progress events (providers report from worker threads)."""
    events: list[discovery.ScanProgressEvent] = []
    lock = threading.Lock()

    def on_progress(event: discovery.ScanProgressEvent) -> None:
        with lock:
            events.append(event)

    return events, on_progress


def _index_of(events, predicate) -> int:
    return next(i for i, e in enumerate(events) if predicate(e))


def test_scan_reports_progress_per_available_provider() -> None:
    events, on_progress = _collect_progress()
    a = _FakeProvider(name="a", entries=[_fe(provider="a", size=100), _fe(provider="a", size=200)])
    off = _Stub(FakeShell(), "off", [], available=False)
    b = _FakeProvider(name="b", entries=[_fe(provider="b", size=500)])

    discovery.scan([a, off, b], ScanFilters(), datetime.now(UTC), on_progress=on_progress)

    # ScanStarted first, naming only the available providers, in provider order.
    assert events[0] == discovery.ScanStarted(providers=("a", "b"))
    started = sorted(e.name for e in events if isinstance(e, discovery.ProviderStarted))
    assert started == ["a", "b"]
    finished = {
        e.timing.name: e.timing for e in events if isinstance(e, discovery.ProviderFinished)
    }
    assert set(finished) == {"a", "b"}
    assert (finished["a"].entries, finished["a"].bytes) == (2, 300)
    assert (finished["b"].entries, finished["b"].bytes) == (1, 500)
    # Each provider starts before it finishes, whatever the thread interleaving.
    for name in ("a", "b"):
        i_started = _index_of(
            events,
            lambda e, n=name: isinstance(e, discovery.ProviderStarted) and e.name == n,
        )
        i_finished = _index_of(
            events,
            lambda e, n=name: isinstance(e, discovery.ProviderFinished) and e.timing.name == n,
        )
        assert i_started < i_finished


def test_scan_reports_a_failed_provider_as_finished_with_zero_figures() -> None:
    events, on_progress = _collect_progress()
    boom = _Raising(FakeShell(), "boom", RuntimeError("disk gremlins"))

    discovery.scan([boom], ScanFilters(), datetime.now(UTC), on_progress=on_progress)

    finished = [e for e in events if isinstance(e, discovery.ProviderFinished)]
    assert [(e.timing.name, e.timing.entries, e.timing.bytes) for e in finished] == [("boom", 0, 0)]


def test_scan_with_no_available_providers_reports_only_scan_started() -> None:
    events, on_progress = _collect_progress()
    off = _Stub(FakeShell(), "off", [], available=False)

    discovery.scan([off], ScanFilters(), datetime.now(UTC), on_progress=on_progress)

    assert events == [discovery.ScanStarted(providers=())]


class _RecordingLogger:
    """Records `.warning(msg, *args)` calls the way `discovery.logger` does.

    A real logger under caplog only works when the `devdoctor` logger tree
    still propagates to the root handler caplog installs; CLI tests
    (`test_cli.py`) invoke `configure_logging`, which sets
    `propagate = False` on the `devdoctor` logger for the rest of the
    process, so this test would fail whenever it runs after one of those
    (order-dependent, and it does in the full suite). Monkeypatching
    `discovery.logger` with this recorder sidesteps the logging tree
    entirely, so the test needs no assumption about what ran before it.
    """

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        self.warnings.append(msg % args if args else msg)


def test_scan_survives_a_raising_progress_callback(monkeypatch) -> None:
    """A broken consumer is logged once per event and never changes the scan."""
    a = _FakeProvider(name="a", entries=[_fe(provider="a", size=100)])
    reference = discovery.scan([a], ScanFilters(), datetime.now(UTC))

    def bad(event: discovery.ScanProgressEvent) -> None:
        raise ValueError("consumer bug")

    fake_logger = _RecordingLogger()
    monkeypatch.setattr(discovery, "logger", fake_logger)
    report = discovery.scan([a], ScanFilters(), datetime.now(UTC), on_progress=bad)

    assert [e.id for e in report.entries] == [e.id for e in reference.entries]
    assert report.total_bytes() == reference.total_bytes()
    assert [pt.name for pt in report.per_provider] == ["a"]
    # ScanStarted + ProviderStarted + ProviderFinished, each logged once.
    assert len(fake_logger.warnings) == 3
    assert {"ScanStarted", "ProviderStarted", "ProviderFinished"} == {
        msg.split()[-1] for msg in fake_logger.warnings
    }


def _tm_entries() -> list[Entry]:
    """Bundle plus two snapshots with provider-local ids, as discover() emits."""
    provider = "time-machine-local-snapshots"
    snaps = [
        Entry(
            provider=provider,
            id=f"snapshot-{ts}",
            path=None,
            label=f"Time Machine local snapshot {ts}",
            size_bytes=0,
            mtime=None,
            risk=Risk.RECLAIMABLE,
            recipe=[f"tmutil deletelocalsnapshots {ts}"],
            usage=DiskUsage(None, None),
            actions=(CommandAction(("tmutil", "deletelocalsnapshots", ts)),),
        )
        for ts in ("2026-09-01-000001", "2026-09-02-000001")
    ]
    bundle = Entry(
        provider=provider,
        id="all-but-newest",
        path=None,
        label="Time Machine local snapshots, all but the newest",
        size_bytes=0,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=["tmutil deletelocalsnapshots 2026-09-01-000001"],
        usage=DiskUsage(None, None),
        actions=(CommandAction(("tmutil", "deletelocalsnapshots", "2026-09-01-000001")),),
        covers=tuple(s.id for s in snaps),
    )
    return [*snaps, bundle]


def test_scan_namespaces_covers_with_ids():
    """_globally_unique must namespace covers alongside id: the covers rule
    matches entry.id against coverer.covers, so bare covers against namespaced
    ids would silently disable the rule in every real scan."""
    p = _Stub(FakeShell(), "time-machine-local-snapshots", _tm_entries())
    report = scan([p], ScanFilters(), datetime(2026, 9, 19, tzinfo=UTC))
    by_id = {e.id: e for e in report.entries}
    bundle = by_id["time-machine-local-snapshots:all-but-newest"]
    assert bundle.covers == (
        "time-machine-local-snapshots:snapshot-2026-09-01-000001",
        "time-machine-local-snapshots:snapshot-2026-09-02-000001",
    )


def test_scanned_bundle_approval_skips_covered_snapshots():
    """End to end over a real scan: approving the bundle prompts nothing else
    and executes only the bundle's commands (no double delete)."""
    p = _Stub(FakeShell(), "time-machine-local-snapshots", _tm_entries())
    report = scan([p], ScanFilters(), datetime(2026, 9, 19, tzinfo=UTC))
    seen: list[str] = []
    shell = FakeShell(
        responses={
            ("tmutil", "deletelocalsnapshots", "2026-09-01-000001"): ShellResult(0, "", ""),
        }
    )
    results = run(
        report,
        shell=shell,
        prompt_choice=lambda entry: (seen.append(entry.id), "y")[1],
        confirm=lambda message: True,
        opts=CleanupOpts(execute=True),
    )
    assert seen == ["time-machine-local-snapshots:all-but-newest"]
    by_id = {r.entry_id: r for r in results}
    assert by_id["time-machine-local-snapshots:all-but-newest"].status == "ok"
    for snap_id in (
        "time-machine-local-snapshots:snapshot-2026-09-01-000001",
        "time-machine-local-snapshots:snapshot-2026-09-02-000001",
    ):
        assert by_id[snap_id].status == "skipped"
        assert by_id[snap_id].message.startswith("covered by ")
    assert shell.calls == [("tmutil", "deletelocalsnapshots", "2026-09-01-000001")]


def test_a_provider_filter_still_discounts_bytes_shared_with_a_provider_that_did_not_run():
    """pnpm hard-links node_modules into its store. With only one of the two providers
    running, the entry still sees fewer paths than the file has links, so the shared
    bytes are still taken off its reclaimable estimate."""
    from devdoctor.types import HardlinkRecord

    linked = dataclasses.replace(
        _e("node", "1", 1_000),
        usage=DiskUsage(1_000, 1_000),
        hardlinks=(
            HardlinkRecord(
                device=1, inode=7, allocated_bytes=400, link_count=2, paths=("/1/pkg/index.js",)
            ),
        ),
    )
    node = _Stub(FakeShell(), "node", [linked])
    store = _Stub(FakeShell(), "pnpm-store", [_e("pnpm-store", "s", 5_000)])

    report = scan(
        [node, store], ScanFilters(providers=frozenset({"node"})), datetime(2026, 4, 18, tzinfo=UTC)
    )
    (entry,) = report.entries
    assert (entry.shared_bytes, entry.reclaimable_bytes) == (400, 600)
