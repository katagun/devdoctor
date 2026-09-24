from __future__ import annotations

import os
import stat as stat_mod
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from devdoctor.ports import Shell
from devdoctor.providers._git import WorktreePointer, read_worktree_pointer
from devdoctor.providers._walk import (
    PROJECT_MARKER_FILES,
    PROJECT_ROOTS,
    PRUNE_DIR_NAMES,
    DepthBudget,
)
from devdoctor.providers.base import Provider, _stat_kwargs
from devdoctor.sizer import SizeResult, size_many
from devdoctor.types import AdviceAction, DeletePathAction, DiskUsage, Entry, Risk
from devdoctor.units import human_bytes

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
    # An initialised workspace always has the lock file (Terraform 0.14+); main.tf
    # catches one that was never initialised but has a stale .terraform anyway.
    "terraform": (frozenset({".terraform.lock.hcl", "main.tf"}), frozenset({".terraform"})),
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


@dataclass(frozen=True)
class GitCandidates:
    """Git locations the project walk observed, for the git worktree provider (spec §4.2)."""

    repositories: tuple[Path, ...]
    pointers: tuple[WorktreePointer, ...]
    folder_children: tuple[Path, ...]


@dataclass(frozen=True)
class _ProjectIndex:
    matches: dict[str, tuple[tuple[Path, Path], ...]]
    git: GitCandidates


class ProjectArtifactIndex:
    """One bounded filesystem index shared by all project providers in a scan."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._index: _ProjectIndex | None = None

    def candidates(self, query: str) -> tuple[tuple[Path, Path], ...]:
        return self._built().matches[query]

    def git_candidates(self) -> GitCandidates:
        return self._built().git

    def _built(self) -> _ProjectIndex:
        with self._lock:
            if self._index is None:
                self._index = _index_projects()
            return self._index


def _index_projects() -> _ProjectIndex:
    matches: dict[str, list[tuple[Path, Path]]] = {query: [] for query in _PROJECT_QUERIES}
    seen_artifacts: set[tuple[int, int]] = set()
    repositories: list[Path] = []
    pointers: list[WorktreePointer] = []
    folder_children: list[Path] = []
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
            # Observe git locations before pruning: `.git` itself is never descended into.
            if ".git" in dirnames and _is_real_dir(project / ".git"):
                repositories.append(project)
            if ".git" in names:
                pointer = read_worktree_pointer(project)
                if pointer is not None:
                    pointers.append(pointer)
            if _is_worktree_folder(project):
                folder_children.extend(
                    project / name for name in sorted(dirnames) if _is_real_dir(project / name)
                )
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
    return _ProjectIndex(
        matches={query: tuple(rows) for query, rows in matches.items()},
        git=GitCandidates(
            repositories=tuple(repositories),
            pointers=tuple(pointers),
            folder_children=tuple(folder_children),
        ),
    )


def _is_real_dir(path: Path) -> bool:
    try:
        return stat_mod.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _is_worktree_folder(directory: Path) -> bool:
    """``.worktrees``, or ``worktrees`` directly inside ``.claude`` (spec §4.2)."""
    return directory.name == ".worktrees" or (
        directory.name == "worktrees" and directory.parent.name == ".claude"
    )


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


@dataclass(frozen=True)
class _Candidate:
    """One artifact directory to size, and how it will be offered."""

    project: Path
    artifact: Path
    risk: Risk
    action: DeletePathAction | AdviceAction


def _sized_entries(provider: Provider, candidates: list[_Candidate]) -> list[Entry]:
    """Size every candidate together, then build the entries in candidate order.

    Sizing is nearly all of a scan's time, and these directories are independent,
    so they are walked a few at a time rather than one after another (#92).
    """
    sizings = size_many([candidate.artifact for candidate in candidates])
    entries: list[Entry] = []
    for candidate, sizing in zip(candidates, sizings, strict=True):
        entry = _sized_entry(provider, candidate, sizing)
        if entry is not None:
            entries.append(entry)
    return entries


def _sized_entry(provider: Provider, candidate: _Candidate, sizing: SizeResult) -> Entry | None:
    project, artifact, risk, action = (
        candidate.project,
        candidate.artifact,
        candidate.risk,
        candidate.action,
    )
    provider._note_skipped(list(sizing.skipped_paths))
    size = sizing.allocated_bytes
    if size <= 0:
        return None
    mtime = sizing.newest_mtime
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
        candidates: list[_Candidate] = []
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
            candidates.append(_Candidate(project, artifact, risk, action))
        return _sized_entries(self, candidates)


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
        return _sized_entries(
            self,
            [
                _Candidate(project, artifact, self.risk, DeletePathAction(artifact))
                for project, artifact in candidates
            ],
        )


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


class TerraformProvider(CargoTargetsProvider):
    name = "terraform-workspaces"
    family = "infra"
    description = "Per-workspace .terraform directories (provider plugins and modules)"
    risk = Risk.RECLAIMABLE
    details = (
        "Finds .terraform next to .terraform.lock.hcl or main.tf under bounded project "
        "roots; terraform init re-creates it. The plugin binaries under providers/ are "
        "byte-identical across workspaces, so the lasting fix is a shared plugin cache: "
        "set TF_PLUGIN_CACHE_DIR (or plugin_cache_dir in ~/.terraformrc) and Terraform "
        "keeps one copy and links each workspace to it. The scan measures the duplicate "
        "copies and says so."
    )

    def discover(self) -> list[Entry]:
        candidates = tuple(self._index.candidates("terraform"))
        entries = self._entries(candidates)
        self._note_duplicate_plugins([artifact for _project, artifact in candidates])
        return entries

    def _note_duplicate_plugins(self, dot_terraform_dirs: list[Path]) -> None:
        """Measure the provider plugin copies that a shared cache would collapse.

        A plugin lives at providers/<host>/<namespace>/<name>/<version>/<platform>;
        the same key in two workspaces is the same binary, so every copy after the
        first is duplicate space. One diagnostic line carries the figures.
        """
        copies = _plugin_copies(dot_terraform_dirs)
        if not copies:
            return
        by_key: dict[str, list[int]] = {}
        sizings = size_many([path for _key, path in copies])
        for (key, _path), sizing in zip(copies, sizings, strict=True):
            self._note_skipped(list(sizing.skipped_paths))
            by_key.setdefault(key, []).append(sizing.allocated_bytes)
        total = sum(sum(sizes) for sizes in by_key.values())
        duplicate = sum(sum(sizes) - max(sizes) for sizes in by_key.values())
        if duplicate <= 0:
            return
        workspaces = len(dot_terraform_dirs)
        self.diagnostics.append(
            f"{self.name}: {human_bytes(total)} of provider plugins across {workspaces} "
            f"workspaces, {human_bytes(duplicate)} of it duplicate copies of the same "
            "binaries. Set TF_PLUGIN_CACHE_DIR (or plugin_cache_dir in ~/.terraformrc) "
            "and Terraform keeps one copy and links each workspace to it."
        )


_PLUGIN_KEY_DEPTH = 5  # host / namespace / name / version / platform


def _plugin_copies(dot_terraform_dirs: list[Path]) -> list[tuple[str, Path]]:
    """Every installed plugin directory, keyed by its registry path."""
    copies: list[tuple[str, Path]] = []
    for dot_terraform in dot_terraform_dirs:
        providers = dot_terraform / "providers"
        for platform_dir in _dirs_at_depth(providers, _PLUGIN_KEY_DEPTH):
            copies.append((str(platform_dir.relative_to(providers)), platform_dir))
    return copies


def _dirs_at_depth(root: Path, depth: int) -> list[Path]:
    level = [root] if _is_real_dir(root) else []
    for _ in range(depth):
        level = [
            child for parent in level for child in sorted(_children(parent)) if _is_real_dir(child)
        ]
    return level


def _children(parent: Path) -> list[Path]:
    try:
        return list(parent.iterdir())
    except OSError:
        return []
