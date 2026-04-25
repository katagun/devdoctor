from pathlib import Path

import pytest

from diskdoctor.providers.base import PathProvider
from diskdoctor.types import Risk
from tests.conftest import FakeShell


def _mkfile(p: Path, size: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)


def test_from_yaml_builds_with_expected_attrs():
    spec = {
        "name": "uv-cache",
        "description": "uv package cache",
        "risk": "safe",
        "platforms": ["darwin", "linux"],
        "paths": ["~/.cache/uv"],
        "recipe": "uv cache clean",
    }
    p = PathProvider.from_yaml(spec, FakeShell())
    assert p.name == "uv-cache"
    assert p.risk == Risk.SAFE
    assert p.platforms == ("darwin", "linux")
    assert p.raw_paths == ("~/.cache/uv",)
    assert p.recipe_template == ["uv cache clean"]


def test_from_yaml_accepts_recipe_list():
    spec = {
        "name": "two-step",
        "description": "two-step cleanup",
        "risk": "safe",
        "platforms": ["darwin"],
        "paths": ["~/tmp"],
        "recipe": ["echo 'cleaning {path}'", "rm -rf {path}"],
    }
    p = PathProvider.from_yaml(spec, FakeShell())
    assert p.recipe_template == ["echo 'cleaning {path}'", "rm -rf {path}"]


def test_from_yaml_rejects_unknown_risk():
    spec = {
        "name": "x",
        "description": "",
        "risk": "maybe",
        "platforms": ["darwin"],
        "paths": ["~/x"],
        "recipe": "rm -rf {path}",
    }
    with pytest.raises(ValueError, match="risk"):
        PathProvider.from_yaml(spec, FakeShell())


def test_from_yaml_rejects_unknown_platform():
    spec = {
        "name": "x",
        "description": "",
        "risk": "safe",
        "platforms": ["bsd"],
        "paths": ["~/x"],
        "recipe": "rm -rf {path}",
    }
    with pytest.raises(ValueError, match="platform"):
        PathProvider.from_yaml(spec, FakeShell())


def test_discover_expands_tilde_and_sizes(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    _mkfile(fake_home / ".cache" / "uv" / "f.bin", 300)
    spec = {
        "name": "uv-cache",
        "description": "uv",
        "risk": "safe",
        "platforms": ["darwin", "linux"],
        "paths": ["~/.cache/uv"],
        "recipe": "rm -rf {path}",
    }
    p = PathProvider.from_yaml(spec, FakeShell())
    entries = p.discover()
    assert len(entries) == 1
    e = entries[0]
    assert e.provider == "uv-cache"
    assert e.size_bytes == 300
    assert e.path == fake_home / ".cache" / "uv"
    # Path is shell-quoted in the recipe.
    assert str(e.path) in e.recipe[0]
    assert e.recipe[0].startswith("rm -rf ")


def test_discover_expands_globs_to_multiple_entries(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    for profile in ("Default", "Profile 1"):
        _mkfile(fake_home / "Library/Caches/Google/Chrome" / profile / "Cache" / "f.bin", 50)

    spec = {
        "name": "chrome-cache",
        "description": "chrome cache",
        "risk": "safe",
        "platforms": ["darwin"],
        "paths": ["~/Library/Caches/Google/Chrome/*/Cache"],
        "recipe": "rm -rf {path}",
    }
    p = PathProvider.from_yaml(spec, FakeShell())
    entries = p.discover()
    assert len(entries) == 2
    labels = sorted(e.label for e in entries)
    assert "Default" in labels[0] or "Default" in labels[1]


def test_discover_skips_nonexistent_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    spec = {
        "name": "ghost",
        "description": "",
        "risk": "safe",
        "platforms": ["darwin", "linux"],
        "paths": ["~/does/not/exist"],
        "recipe": "rm -rf {path}",
    }
    assert PathProvider.from_yaml(spec, FakeShell()).discover() == []


def test_discover_shell_quotes_paths_with_spaces(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "has space").mkdir()
    _mkfile(tmp_path / "has space" / "x", 10)
    spec = {
        "name": "spaced",
        "description": "",
        "risk": "safe",
        "platforms": ["darwin", "linux"],
        "paths": ["~/has space"],
        "recipe": "rm -rf {path}",
    }
    [e] = PathProvider.from_yaml(spec, FakeShell()).discover()
    # shlex.quote wraps paths with spaces in single quotes
    assert "'" in e.recipe[0]


def test_path_provider_entry_includes_stat_fields(tmp_path):
    """Discovered entries should carry owner/group/perms populated from the
    resolved path. Verifies the provider-base helper is wired up correctly."""
    import pwd
    import sys

    from diskdoctor.types import Risk

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "file.bin").write_bytes(b"payload")

    platform_tag = "darwin" if sys.platform == "darwin" else "linux"
    provider = PathProvider(
        shell=FakeShell(),
        name="test-cache",
        description="tmp cache",
        platforms=(platform_tag,),
        risk=Risk.SAFE,
        raw_paths=(str(cache_dir),),
        recipe_template=["rm -rf {path}"],
    )
    entries = provider.discover()
    assert len(entries) == 1
    e = entries[0]
    st = cache_dir.lstat()
    assert e.uid == st.st_uid
    assert e.gid == st.st_gid
    assert e.mode == st.st_mode
    assert e.owner == pwd.getpwuid(st.st_uid).pw_name
    assert e.perms is not None
    assert e.perms.startswith("d")  # directory
