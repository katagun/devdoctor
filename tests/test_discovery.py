from datetime import UTC, datetime
from pathlib import Path

from diskdoctor import discovery
from diskdoctor.discovery import scan
from diskdoctor.providers.base import Provider
from diskdoctor.types import Entry, Risk, ScanFilters, SnapshotKind
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
