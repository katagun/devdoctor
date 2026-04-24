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
    assert [e.id for e in r.entries] == ["1"]


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
        self._shell = shell
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


def test_scan_skips_unavailable_providers_in_timings() -> None:
    class _Unavailable(_FakeProvider):
        def available(self) -> bool:
            return False

    avail = _FakeProvider(name="a", entries=[_fe(provider="a")])
    unavail = _Unavailable(name="b", entries=[_fe(provider="b")])
    report = discovery.scan([avail, unavail], ScanFilters(), datetime.now(UTC))
    names = [pt.name for pt in report.per_provider]
    assert names == ["a"]
