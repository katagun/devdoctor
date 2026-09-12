from __future__ import annotations

import os
import stat as stat_mod
import threading
from collections.abc import Iterable
from pathlib import Path

from devdoctor.ports import Shell
from devdoctor.providers._walk import (
    PROJECT_MARKER_FILES,
    PROJECT_ROOTS,
    PRUNE_DIR_NAMES,
    DepthBudget,
)
from devdoctor.providers.base import Provider, _stat_kwargs
from devdoctor.sizer import size_path_detailed
from devdoctor.types import AdviceAction, DeletePathAction, DiskUsage, Entry, Risk

_PROJECT_ROOTS = PROJECT_ROOTS

# Pruning policy lives in _walk.PRUNE_DIR_NAMES; dot-directories are not
# skipped as a class so agent and git worktrees stay visible. ``.tox``/``.nox``
# are pruned there and still discovered here, because artifacts are resolved by
# direct lstat rather than by walking into them.
_PRUNE_DIRS = PRUNE_DIR_NAMES

_LOCKFILES = (
    "bun.lock",
    "bun.lockb",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
)
_PROJECT_QUERIES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "node": (frozenset({"package.json"}), frozenset({"node_modules"})),
    "cargo": (frozenset({"Cargo.toml"}), frozenset({"target"})),
    "android": (
        frozenset({"build.gradle", "build.gradle.kts"}),
        frozenset({"build"}),
    ),
    "tox-nox": (
        frozenset({"tox.ini", "noxfile.py", "pyproject.toml"}),
        frozenset({".tox", ".nox"}),
    ),
}
_ALL_ARTIFACT_NAMES = frozenset(
    artifact for _markers, artifacts in _PROJECT_QUERIES.values() for artifact in artifacts
)


def _roots() -> list[Path]:
    configured = os.environ.get("DEVDOCTOR_PROJECT_ROOTS")
    raw_roots = configured.split(os.pathsep) if configured else _PROJECT_ROOTS
    roots: list[Path] = []
    seen: set[tuple[int, int]] = set()
    for raw in raw_roots:
        root = Path(os.path.expanduser(raw))
        try:
            stat = root.lstat()
        except OSError:
            continue
        if not root.is_dir() or (stat.st_dev, stat.st_ino) in seen:
            continue
        seen.add((stat.st_dev, stat.st_ino))
        roots.append(root)
    return roots


class ProjectArtifactIndex:
    """One bounded filesystem index shared by all project providers in a scan."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._matches: dict[str, tuple[tuple[Path, Path], ...]] | None = None

    def candidates(self, query: str) -> tuple[tuple[Path, Path], ...]:
        with self._lock:
            if self._matches is None:
                self._matches = _index_projects()
            return self._matches[query]


def _index_projects() -> dict[str, tuple[tuple[Path, Path], ...]]:
    matches: dict[str, list[tuple[Path, Path]]] = {query: [] for query in _PROJECT_QUERIES}
    seen_artifacts: set[tuple[int, int]] = set()
    for root in _roots():
        try:
            root_dev = root.lstat().st_dev
        except OSError:
            continue
        budget = DepthBudget(root)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            project = Path(dirpath)
            if not budget.allows(dirpath, len(project.parts)):
                dirnames[:] = []
                continue

            names = set(filenames)
            for query, (marker_names, artifact_names) in _PROJECT_QUERIES.items():
                if marker_names & names:
                    for artifact, key in _artifact_dirs(project, artifact_names):
                        if key not in seen_artifacts:
                            seen_artifacts.add(key)
                            matches[query].append((project, artifact))

            dirnames[:] = [
                name
                for name in dirnames
                if _walkable_child(project, name, _ALL_ARTIFACT_NAMES, root_dev)
            ]
            budget.descend(dirpath, dirnames, reset=bool(PROJECT_MARKER_FILES & names))
    return {query: tuple(rows) for query, rows in matches.items()}


def _artifact_dirs(
    project: Path,
    artifact_names: frozenset[str],
) -> Iterable[tuple[Path, tuple[int, int]]]:
    for artifact_name in artifact_names:
        artifact = project / artifact_name
        try:
            metadata = artifact.lstat()
        except OSError:
            continue
        if stat_mod.S_ISDIR(metadata.st_mode):
            yield artifact, (metadata.st_dev, metadata.st_ino)


def _walkable_child(
    project: Path,
    name: str,
    artifact_names: frozenset[str],
    root_dev: int,
) -> bool:
    if name in _PRUNE_DIRS or name in artifact_names:
        return False
    try:
        metadata = (project / name).lstat()
    except OSError:
        return False
    return metadata.st_dev == root_dev and stat_mod.S_ISDIR(metadata.st_mode)


def _sized_entry(
    provider: Provider,
    project: Path,
    artifact: Path,
    *,
    risk: Risk,
    action: DeletePathAction | AdviceAction,
) -> Entry | None:
    sizing = size_path_detailed(artifact)
    provider._note_skipped(list(sizing.skipped_paths))
    size = sizing.allocated_bytes
    if size <= 0:
        return None
    try:
        mtime: float | None = artifact.lstat().st_mtime
    except OSError:
        mtime = None
    reclaimable = size if isinstance(action, DeletePathAction) else None
    return Entry(
        provider=provider.name,
        id=str(artifact),
        path=artifact,
        label=f"{project.name}/{artifact.name}",
        size_bytes=size,
        mtime=mtime,
        risk=risk,
        recipe=[],
        usage=DiskUsage(size, reclaimable),
        actions=(action,),
        hardlinks=sizing.hardlinks,
        **_stat_kwargs(artifact),
    )


class NodeModulesProvider(Provider):
    name = "node-project-dependencies"
    family = "javascript"
    description = "Project node_modules directories under common code roots"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    details = (
        "Finds node_modules next to package.json under bounded project roots. "
        "Lockfile-backed trees are removable; trees without a lockfile are advice-only."
    )

    def __init__(self, shell: Shell, *, index: ProjectArtifactIndex | None = None) -> None:
        super().__init__(shell)
        self._index = index or ProjectArtifactIndex()

    def discover(self) -> list[Entry]:
        entries: list[Entry] = []
        for project, artifact in self._index.candidates("node"):
            has_lockfile = any((project / name).is_file() for name in _LOCKFILES)
            action: DeletePathAction | AdviceAction
            risk: Risk
            if has_lockfile:
                action = DeletePathAction(artifact)
                risk = Risk.RECLAIMABLE
            else:
                action = AdviceAction(
                    f"{artifact} has no recognized lockfile. Review package.json and "
                    "confirm dependencies can be reproduced before deleting it."
                )
                risk = Risk.DANGEROUS
            entry = _sized_entry(self, project, artifact, risk=risk, action=action)
            if entry is not None:
                entries.append(entry)
        return entries


class CargoTargetsProvider(NodeModulesProvider):
    name = "cargo-targets"
    family = "rust"
    description = "Cargo workspace target build directories"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    details = "Finds target directories next to Cargo.toml under bounded project roots."

    def discover(self) -> list[Entry]:
        return self._entries(self._index.candidates("cargo"))

    def _entries(self, candidates: Iterable[tuple[Path, Path]]) -> list[Entry]:
        entries: list[Entry] = []
        for project, artifact in candidates:
            entry = _sized_entry(
                self,
                project,
                artifact,
                risk=self.risk,
                action=DeletePathAction(artifact),
            )
            if entry is not None:
                entries.append(entry)
        return entries


class AndroidBuildProvider(CargoTargetsProvider):
    name = "android-project-builds"
    family = "android"
    description = "Generated Android and Gradle project build directories"
    details = (
        "Finds build directories next to build.gradle or build.gradle.kts under "
        "bounded project roots."
    )

    def discover(self) -> list[Entry]:
        return self._entries(self._index.candidates("android"))


class ToxNoxProvider(CargoTargetsProvider):
    name = "tox-nox-environments"
    family = "python"
    description = "Generated tox and nox test environments"
    risk = Risk.SAFE
    details = "Finds .tox and .nox directories in configured/common project roots."

    def discover(self) -> list[Entry]:
        return self._entries(self._index.candidates("tox-nox"))
