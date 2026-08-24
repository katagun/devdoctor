import shlex
from pathlib import Path

from diskdoctor.providers.large_files import LargeFilesProvider
from diskdoctor.types import Risk
from tests.conftest import FakeShell

_TEST_THRESHOLD = 1024 * 1024  # 1 MB — keeps file writes fast


def _mk_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"0" * size)


def test_surfaces_files_over_threshold(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("diskdoctor.providers.large_files._MIN_BYTES", _TEST_THRESHOLD)

    big = home / "Desktop" / "huge.iso"
    _mk_file(big, 2 * _TEST_THRESHOLD)  # above threshold

    small = home / "Documents" / "notes.txt"
    _mk_file(small, 100)  # below threshold

    entries = LargeFilesProvider(FakeShell()).discover()
    ids = {e.id for e in entries}
    assert str(big) in ids
    assert str(small) not in ids
    big_entry = next(e for e in entries if e.id == str(big))
    assert big_entry.risk == Risk.DANGEROUS
    # Advice-only recipe (wrapped in echo so nothing runs destructively).
    assert big_entry.recipe[0].startswith("echo '")
    assert big_entry.recipe[0].rstrip().endswith("'")


def test_prunes_library_and_hidden_dirs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("diskdoctor.providers.large_files._MIN_BYTES", _TEST_THRESHOLD)

    _mk_file(home / "Library" / "Caches" / "big.bin", 2 * _TEST_THRESHOLD)
    _mk_file(home / "Documents" / ".hidden" / "big.bin", 2 * _TEST_THRESHOLD)
    control = home / "Documents" / "visible.iso"
    _mk_file(control, 2 * _TEST_THRESHOLD)

    entries = LargeFilesProvider(FakeShell()).discover()
    ids = {e.id for e in entries}
    assert str(control) in ids
    assert not any("/Library/" in i for i in ids)
    assert not any("/.hidden/" in i for i in ids)


def test_recipe_survives_adversarial_filename(tmp_path, monkeypatch):
    """A filename with a quote / shell metacharacters must not break out of the
    echo recipe: the line stays a single, safely-quoted `echo` token list."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("diskdoctor.providers.large_files._MIN_BYTES", _TEST_THRESHOLD)

    evil = home / "Desktop" / "x'$(touch pwned)'.iso"
    _mk_file(evil, 2 * _TEST_THRESHOLD)

    entries = LargeFilesProvider(FakeShell()).discover()
    entry = next(e for e in entries if e.id == str(evil))
    line = entry.recipe[0]
    # shlex.split must succeed (no "No closing quotation") and yield exactly
    # `echo <one-message-arg>` — the metacharacters stay inert data.
    argv = shlex.split(line)
    assert argv[0] == "echo"
    assert len(argv) == 2
    assert "$(touch pwned)" in argv[1]  # present, but as a literal argument


def test_returns_empty_when_roots_missing(tmp_path, monkeypatch):
    home = tmp_path / "emptyhome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    assert LargeFilesProvider(FakeShell()).discover() == []
