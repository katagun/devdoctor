from __future__ import annotations

import json
import os
from pathlib import Path

from devdoctor.providers.base import Provider, _stat_kwargs
from devdoctor.sizer import size_path_detailed
from devdoctor.types import (
    AdviceAction,
    CleanupAction,
    CommandAction,
    DeletePathAction,
    DiskUsage,
    Entry,
    HardlinkRecord,
    Risk,
)


def _path_from_output(output: str) -> Path | None:
    for raw in reversed(output.splitlines()):
        value = raw.strip().strip('"')
        if not value or value.lower() in {"undefined", "null", "off"}:
            continue
        return Path(os.path.expandvars(os.path.expanduser(value)))
    return None


def _path_entry(
    provider: Provider,
    path: Path,
    *,
    id_: str,
    label: str,
    risk: Risk,
    actions: tuple[CleanupAction, ...],
    reclaimable: bool | None,
) -> Entry | None:
    if not path.exists():
        return None
    sizing = size_path_detailed(path)
    provider._note_skipped(list(sizing.skipped_paths))
    if sizing.allocated_bytes <= 0:
        return None
    try:
        mtime: float | None = path.lstat().st_mtime
    except OSError:
        mtime = None
    estimate = sizing.allocated_bytes if reclaimable is True else None
    return Entry(
        provider=provider.name,
        id=id_,
        path=path,
        label=label,
        size_bytes=sizing.allocated_bytes,
        mtime=mtime,
        risk=risk,
        recipe=[],
        usage=DiskUsage(sizing.allocated_bytes, estimate),
        actions=actions,
        hardlinks=sizing.hardlinks,
        **_stat_kwargs(path),
    )


class PnpmStoreProvider(Provider):
    name = "pnpm-store"
    family = "javascript"
    description = "pnpm content-addressable package store"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = "pnpm"
    details = (
        "Uses pnpm store path to find the active store. Cleanup runs pnpm store "
        "prune, which removes only unreferenced packages, so the reclaim estimate is unknown."
    )

    def discover(self) -> list[Entry]:
        result = self._shell.run(["pnpm", "store", "path"], check=False)
        path = _path_from_output(result.stdout) if result.returncode == 0 else None
        if path is None:
            self.diagnostics.append("pnpm-store: could not resolve the active store path")
            return []
        entry = _path_entry(
            self,
            path,
            id_=str(path),
            label=str(path),
            risk=self.risk,
            actions=(CommandAction(("pnpm", "store", "prune")),),
            reclaimable=None,
        )
        return [entry] if entry is not None else []


class BunCacheProvider(Provider):
    name = "bun-cache"
    family = "javascript"
    description = "Bun global package cache"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = "bun"
    details = "Uses bun pm cache to discover the cache and bun pm cache rm to clear it."

    def discover(self) -> list[Entry]:
        result = self._shell.run(["bun", "pm", "cache"], check=False)
        path = _path_from_output(result.stdout) if result.returncode == 0 else None
        if path is None:
            self.diagnostics.append("bun-cache: could not resolve the global cache path")
            return []
        entry = _path_entry(
            self,
            path,
            id_=str(path),
            label=str(path),
            risk=self.risk,
            actions=(CommandAction(("bun", "pm", "cache", "rm")),),
            reclaimable=True,
        )
        return [entry] if entry is not None else []


class YarnCacheProvider(Provider):
    name = "yarn-cache"
    family = "javascript"
    description = "Yarn shared or project package cache"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = "yarn"
    details = (
        "Discovers Yarn's configured cache. Project-local .yarn/cache stores are "
        "advice-only because they may be committed for Zero-Installs."
    )

    def discover(self) -> list[Entry]:
        path: Path | None = None
        for argv in (
            ["yarn", "config", "get", "cacheFolder"],
            ["yarn", "cache", "dir"],
        ):
            result = self._shell.run(argv, check=False)
            if result.returncode == 0:
                path = _path_from_output(result.stdout)
            if path is not None:
                break
        if path is None:
            self.diagnostics.append("yarn-cache: could not resolve a cache path")
            return []

        project_local = path.name == "cache" and path.parent.name == ".yarn"
        action: CleanupAction
        risk: Risk
        reclaimable: bool | None
        if project_local:
            action = AdviceAction(
                f"{path} is a project-local Yarn cache and may be committed for "
                "Zero-Installs. Review repository policy before removing it."
            )
            risk = Risk.DANGEROUS
            reclaimable = None
        else:
            action = CommandAction(("yarn", "cache", "clean"))
            risk = Risk.SAFE
            reclaimable = True
        entry = _path_entry(
            self,
            path,
            id_=str(path),
            label=str(path),
            risk=risk,
            actions=(action,),
            reclaimable=reclaimable,
        )
        return [entry] if entry is not None else []


class GoCachesProvider(Provider):
    name = "go-caches"
    family = "go"
    description = "Go build, test, fuzz, and downloaded-module caches"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = "go"
    details = "Uses go env for configured paths and official go clean cache commands."

    def discover(self) -> list[Entry]:
        result = self._shell.run(
            ["go", "env", "-json", "GOCACHE", "GOMODCACHE"],
            check=False,
        )
        if result.returncode != 0:
            self.diagnostics.append("go-caches: go env failed")
            return []
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.diagnostics.append("go-caches: go env returned invalid JSON")
            return []
        if not isinstance(payload, dict):
            return []

        specs = (
            (
                "build",
                "Go build, test, and fuzz cache",
                payload.get("GOCACHE"),
                CommandAction(("go", "clean", "-cache", "-testcache", "-fuzzcache")),
            ),
            (
                "modules",
                "Go downloaded module cache",
                payload.get("GOMODCACHE"),
                CommandAction(("go", "clean", "-modcache")),
            ),
        )
        entries: list[Entry] = []
        for id_, label, raw_path, action in specs:
            if not isinstance(raw_path, str):
                continue
            path = Path(os.path.expanduser(raw_path))
            entry = _path_entry(
                self,
                path,
                id_=id_,
                label=label,
                risk=self.risk,
                actions=(action,),
                reclaimable=True,
            )
            if entry is not None:
                entries.append(entry)
        return entries


class CargoCacheProvider(Provider):
    name = "cargo-dependency-cache"
    family = "rust"
    description = "Cargo registry archives/sources and git dependency checkouts"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    details = (
        "Scopes cleanup to registry and git dependency caches under CARGO_HOME; "
        "credentials, configuration, installed binaries, and rustup toolchains are excluded."
    )

    def discover(self) -> list[Entry]:
        home = Path(os.path.expanduser(os.environ.get("CARGO_HOME", "~/.cargo")))
        candidates = (
            home / "registry" / "cache",
            home / "registry" / "src",
            home / "git" / "db",
            home / "git" / "checkouts",
        )
        existing = [path for path in candidates if path.exists()]
        if not existing:
            return []
        total = 0
        hardlinks: list[HardlinkRecord] = []
        skipped: list[Path] = []
        for path in existing:
            sizing = size_path_detailed(path)
            total += sizing.allocated_bytes
            hardlinks.extend(sizing.hardlinks)
            skipped.extend(sizing.skipped_paths)
        self._note_skipped(skipped)
        if total <= 0:
            return []
        return [
            Entry(
                provider=self.name,
                id=str(home),
                path=home,
                label=str(home),
                size_bytes=total,
                mtime=None,
                risk=self.risk,
                recipe=[],
                usage=DiskUsage(total, total),
                actions=tuple(DeletePathAction(path) for path in existing),
                hardlinks=tuple(hardlinks),
                **_stat_kwargs(home),
            )
        ]


class NuGetCacheProvider(Provider):
    name = "nuget-caches"
    family = "dotnet"
    description = "NuGet global packages, HTTP, temp, and plugin caches"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = "dotnet"
    details = "Uses dotnet nuget locals all --list and clears each reported cache explicitly."

    def discover(self) -> list[Entry]:
        result = self._shell.run(
            ["dotnet", "nuget", "locals", "all", "--list"],
            check=False,
        )
        if result.returncode != 0:
            self.diagnostics.append("nuget-caches: dotnet nuget locals failed")
            return []
        entries: list[Entry] = []
        for line in result.stdout.splitlines():
            kind, separator, raw_path = line.partition(":")
            if not separator or not raw_path.strip():
                continue
            normalized = kind.strip().lower().replace(" ", "-")
            path = Path(os.path.expanduser(raw_path.strip()))
            entry = _path_entry(
                self,
                path,
                id_=normalized,
                label=f"NuGet {kind.strip()}",
                risk=self.risk,
                actions=(CommandAction(("dotnet", "nuget", "locals", kind.strip(), "--clear")),),
                reclaimable=True,
            )
            if entry is not None:
                entries.append(entry)
        return entries


class CondaCacheProvider(Provider):
    name = "conda-package-caches"
    family = "conda"
    description = "Conda package caches"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "conda"
    details = (
        "Discovers configured package directories from conda info. conda clean "
        "removes only eligible packages/tarballs, so the reclaim estimate is unknown."
    )

    def discover(self) -> list[Entry]:
        payload = self._conda_info()
        raw_paths = payload.get("pkgs_dirs") if payload is not None else None
        if not isinstance(raw_paths, list):
            return []
        paths = [
            Path(os.path.expanduser(raw_path))
            for raw_path in raw_paths
            if isinstance(raw_path, str) and Path(os.path.expanduser(raw_path)).exists()
        ]
        if not paths:
            return []
        total = 0
        hardlinks: list[HardlinkRecord] = []
        skipped: list[Path] = []
        for path in paths:
            sizing = size_path_detailed(path)
            total += sizing.allocated_bytes
            hardlinks.extend(sizing.hardlinks)
            skipped.extend(sizing.skipped_paths)
        self._note_skipped(skipped)
        if total <= 0:
            return []
        return [
            Entry(
                provider=self.name,
                id="packages",
                path=paths[0] if len(paths) == 1 else None,
                label=f"Conda package caches ({len(paths)} location(s))",
                size_bytes=total,
                mtime=None,
                risk=self.risk,
                recipe=[],
                usage=DiskUsage(total, None),
                actions=(CommandAction(("conda", "clean", "--packages", "--tarballs", "--yes")),),
                hardlinks=tuple(hardlinks),
            )
        ]

    def _conda_info(self) -> dict[str, object] | None:
        result = self._shell.run(["conda", "info", "--json"], check=False)
        if result.returncode != 0:
            self.diagnostics.append("conda-package-caches: conda info failed")
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.diagnostics.append("conda-package-caches: conda info returned invalid JSON")
            return None
        return payload if isinstance(payload, dict) else None


class CondaEnvironmentsProvider(CondaCacheProvider):
    name = "conda-environments"
    description = "Non-base Conda environments"
    risk = Risk.DANGEROUS
    details = (
        "Lists non-base environments individually; removal always requires dangerous approval."
    )

    def discover(self) -> list[Entry]:
        payload = self._conda_info()
        if payload is None:
            return []
        root_prefix = payload.get("root_prefix")
        raw_envs = payload.get("envs")
        if not isinstance(raw_envs, list):
            return []
        entries: list[Entry] = []
        for raw_path in raw_envs:
            if not isinstance(raw_path, str) or raw_path == root_prefix:
                continue
            path = Path(os.path.expanduser(raw_path))
            entry = _path_entry(
                self,
                path,
                id_=str(path),
                label=path.name,
                risk=self.risk,
                actions=(
                    CommandAction(("conda", "env", "remove", "--prefix", str(path), "--yes")),
                ),
                reclaimable=None,
            )
            if entry is not None:
                entries.append(entry)
        return entries
