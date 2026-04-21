from pathlib import Path

from diskdoctor.providers.venv import VenvProvider
from diskdoctor.types import Risk
from tests.conftest import FakeShell


def _mk_venv(path: Path, *, payload_bytes: int = 4096) -> None:
    """Create a directory that looks like a PEP-405 venv."""
    path.mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/bin\n")
    site_packages = path / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "payload.bin").write_bytes(b"x" * payload_bytes)


def test_discovers_venvs_under_common_roots(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    _mk_venv(home / "projects" / "foo" / ".venv", payload_bytes=2048)
    _mk_venv(home / "Code" / "bar" / "venv", payload_bytes=4096)

    entries = VenvProvider(FakeShell()).discover()
    labels = {e.label for e in entries}
    assert "foo/.venv" in labels
    assert "bar/venv" in labels
    assert all(e.risk == Risk.RECLAIMABLE for e in entries)
    assert all(e.recipe[0].startswith("rm -rf ") for e in entries)


def test_dedupes_symlinked_venvs_to_same_target(tmp_path, monkeypatch):
    """Two projects symlinked to the same real venv emit a single entry."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    real_venv = home / "centralized" / "shared-venv"
    _mk_venv(real_venv, payload_bytes=2048)

    proj_a = home / "projects" / "alpha"
    proj_a.mkdir(parents=True)
    (proj_a / ".venv").symlink_to(real_venv, target_is_directory=True)

    proj_b = home / "projects" / "bravo"
    proj_b.mkdir(parents=True)
    (proj_b / ".venv").symlink_to(real_venv, target_is_directory=True)

    entries = VenvProvider(FakeShell()).discover()
    # Two distinct scan locations, both symlinks to the same real path → one entry.
    assert len(entries) == 1
    # The emitted path is the resolved target, not either symlink.
    assert entries[0].path == real_venv.resolve()


def test_skips_dirs_that_look_like_venvs_but_arent(tmp_path, monkeypatch):
    """A directory named .venv without a pyvenv.cfg isn't a real venv."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    # No pyvenv.cfg — this is someone's data dir that just happens to be named .venv
    fake = home / "projects" / "foo" / ".venv"
    fake.mkdir(parents=True)
    (fake / "some-other-file.txt").write_bytes(b"x" * 4096)

    assert VenvProvider(FakeShell()).discover() == []


def test_broken_symlink_is_skipped(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    proj = home / "projects" / "ghost"
    proj.mkdir(parents=True)
    (proj / ".venv").symlink_to(home / "definitely-does-not-exist", target_is_directory=True)

    # Broken symlink → discovery finishes without raising, no entry emitted.
    assert VenvProvider(FakeShell()).discover() == []


def test_no_project_roots_returns_empty(tmp_path, monkeypatch):
    home = tmp_path / "empty"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    assert VenvProvider(FakeShell()).discover() == []


def test_does_not_descend_into_venvs(tmp_path, monkeypatch):
    """Nested venv-shaped dirs inside a venv shouldn't be separate entries."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    outer = home / "projects" / "foo" / ".venv"
    _mk_venv(outer)
    # Some tools put a bootstrap venv inside lib/ — we should not rescan it.
    _mk_venv(outer / "lib" / "bootstrap" / ".venv")

    entries = VenvProvider(FakeShell()).discover()
    # Exactly one entry for the outer project; the nested one is pruned.
    assert len(entries) == 1
    assert entries[0].label == "foo/.venv"
