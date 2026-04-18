from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.discovery import scan
from diskdoctor.providers.base import Provider
from diskdoctor.types import Entry, Risk, ScanFilters
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
    return Entry(provider, id_, Path(f"/{id_}"), f"{provider}/{id_}", size, None, risk, [f"rm -rf /{id_}"])


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
    assert r.scanned_at == now
    assert r.hostname  # something populated
    assert r.platform in {"darwin", "linux"}
