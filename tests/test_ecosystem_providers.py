from __future__ import annotations

import json
from pathlib import Path

from devdoctor.providers.mobile import AndroidSdkProvider, XcodeProvider
from devdoctor.providers.tool_caches import (
    BunCacheProvider,
    CargoCacheProvider,
    CondaCacheProvider,
    CondaEnvironmentsProvider,
    GoCachesProvider,
    NuGetCacheProvider,
    PnpmStoreProvider,
    YarnCacheProvider,
)
from devdoctor.types import AdviceAction, CommandAction, DeletePathAction, Risk, ShellResult
from tests.conftest import FakeShell


def _payload(path: Path, size: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_javascript_tool_caches_use_tool_discovery_and_typed_actions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pnpm = tmp_path / "pnpm"
    bun = tmp_path / "bun"
    yarn_project = tmp_path / "project"
    _payload(pnpm / "pkg")
    _payload(bun / "pkg")
    _payload(yarn_project / ".yarn" / "cache" / "pkg.zip")
    monkeypatch.chdir(yarn_project)
    shell = FakeShell(
        responses={
            ("pnpm", "store", "path"): ShellResult(0, f"{pnpm}\n", ""),
            ("bun", "pm", "cache"): ShellResult(0, f"{bun}\n", ""),
            ("yarn", "config", "get", "cacheFolder"): ShellResult(0, ".yarn/cache\n", ""),
        }
    )

    [pnpm_entry] = PnpmStoreProvider(shell).discover()
    [bun_entry] = BunCacheProvider(shell).discover()
    [yarn_entry] = YarnCacheProvider(shell).discover()

    assert pnpm_entry.reclaimable_bytes is None
    assert pnpm_entry.actions == (CommandAction(("pnpm", "store", "prune")),)
    assert bun_entry.reclaimable_bytes == bun_entry.footprint_bytes
    assert bun_entry.actions == (CommandAction(("bun", "pm", "cache", "rm")),)
    assert yarn_entry.risk == Risk.DANGEROUS
    assert isinstance(yarn_entry.actions[0], AdviceAction)


def test_go_caches_are_discovered_from_go_env(tmp_path: Path) -> None:
    build = tmp_path / "go-build"
    modules = tmp_path / "go-mod"
    _payload(build / "cache")
    _payload(modules / "module")
    shell = FakeShell(
        responses={
            ("go", "env", "-json", "GOCACHE", "GOMODCACHE"): ShellResult(
                0,
                json.dumps({"GOCACHE": str(build), "GOMODCACHE": str(modules)}),
                "",
            )
        }
    )

    entries = {entry.id: entry for entry in GoCachesProvider(shell).discover()}

    assert set(entries) == {"build", "modules"}
    assert entries["build"].actions == (
        CommandAction(("go", "clean", "-cache", "-testcache", "-fuzzcache")),
    )
    assert entries["modules"].actions == (CommandAction(("go", "clean", "-modcache")),)


def test_cargo_cache_excludes_config_credentials_and_binaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cargo_home = tmp_path / "cargo-home"
    monkeypatch.setenv("CARGO_HOME", str(cargo_home))
    _payload(cargo_home / "registry" / "cache" / "crate")
    _payload(cargo_home / "git" / "checkouts" / "repo")
    _payload(cargo_home / "bin" / "keep")
    _payload(cargo_home / "credentials.toml")

    [entry] = CargoCacheProvider(FakeShell()).discover()
    deleted = {action.path for action in entry.actions if isinstance(action, DeletePathAction)}

    assert deleted == {
        cargo_home / "registry" / "cache",
        cargo_home / "git" / "checkouts",
    }
    assert cargo_home / "bin" not in deleted
    assert cargo_home / "credentials.toml" not in deleted


def test_nuget_cache_paths_and_clear_commands(tmp_path: Path) -> None:
    global_packages = tmp_path / "packages"
    http_cache = tmp_path / "http"
    _payload(global_packages / "pkg")
    _payload(http_cache / "index")
    output = f"global-packages: {global_packages}\nhttp-cache: {http_cache}\n"
    shell = FakeShell(
        responses={("dotnet", "nuget", "locals", "all", "--list"): ShellResult(0, output, "")}
    )

    entries = {entry.id: entry for entry in NuGetCacheProvider(shell).discover()}

    assert set(entries) == {"global-packages", "http-cache"}
    assert entries["http-cache"].actions == (
        CommandAction(("dotnet", "nuget", "locals", "http-cache", "--clear")),
    )


def test_conda_cache_is_one_partial_cleanup_and_environments_are_dangerous(
    tmp_path: Path,
) -> None:
    base = tmp_path / "conda"
    cache_a = tmp_path / "pkgs-a"
    cache_b = tmp_path / "pkgs-b"
    env = base / "envs" / "science"
    for path in (cache_a / "a", cache_b / "b", base / "bin" / "conda", env / "bin" / "python"):
        _payload(path)
    info = json.dumps(
        {
            "root_prefix": str(base),
            "pkgs_dirs": [str(cache_a), str(cache_b)],
            "envs": [str(base), str(env)],
        }
    )
    shell = FakeShell(responses={("conda", "info", "--json"): ShellResult(0, info, "")})

    [cache] = CondaCacheProvider(shell).discover()
    [environment] = CondaEnvironmentsProvider(shell).discover()

    assert cache.id == "packages"
    assert cache.reclaimable_bytes is None
    assert cache.actions == (
        CommandAction(("conda", "clean", "--packages", "--tarballs", "--yes")),
    )
    assert environment.path == env
    assert environment.risk == Risk.DANGEROUS
    assert environment.reclaimable_bytes is None


def test_xcode_provider_keeps_archives_advice_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    derived = tmp_path / "Library" / "Developer" / "Xcode" / "DerivedData" / "App-123"
    archive = (
        tmp_path / "Library" / "Developer" / "Xcode" / "Archives" / "2026-09-05" / "App.xcarchive"
    )
    _payload(derived / "Build" / "product")
    _payload(archive / "Products" / "App")

    entries = XcodeProvider(FakeShell()).discover()
    by_path = {entry.path: entry for entry in entries}

    assert isinstance(by_path[derived].actions[0], DeletePathAction)
    assert by_path[archive].risk == Risk.DANGEROUS
    assert by_path[archive].reclaimable_bytes is None
    assert isinstance(by_path[archive].actions[0], AdviceAction)


def test_android_sdk_images_use_sdkmanager_but_avds_are_advice_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sdk = tmp_path / "sdk"
    manager = tmp_path / "bin" / "sdkmanager"
    image = sdk / "system-images" / "android-35" / "google_apis" / "arm64-v8a"
    avd = tmp_path / "avds" / "Pixel.avd"
    _payload(image / "package.xml")
    _payload(image / "system.img")
    _payload(avd / "userdata-qemu.img")
    monkeypatch.setenv("ANDROID_SDK_ROOT", str(sdk))
    monkeypatch.setenv("ANDROID_AVD_HOME", str(avd.parent))
    shell = FakeShell(which_table={"sdkmanager": str(manager)})

    entries = AndroidSdkProvider(shell).discover()
    by_path = {entry.path: entry for entry in entries}

    assert by_path[image].actions == (
        CommandAction(
            (
                str(manager),
                "--uninstall",
                "system-images;android-35;google_apis;arm64-v8a",
            )
        ),
    )
    assert by_path[avd].risk == Risk.DANGEROUS
    assert isinstance(by_path[avd].actions[0], AdviceAction)
