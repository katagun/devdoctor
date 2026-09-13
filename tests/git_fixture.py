"""Hermetic real-git repositories for tests (spec §8.3).

Request the ``git_fixture`` fixture from ``tests/conftest.py``: it isolates git from
the developer's configuration and from any enclosing repository first.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

# Every git call advances a shared clock by a minute, so no two commits share a
# timestamp. Commits replayed within the same second are byte-identical to the
# originals, which silently turns a rebase merge into a fast-forward.
_START_EPOCH = 1_700_000_000
_TICK_S = 60


class _Clock:
    def __init__(self) -> None:
        self.now = _START_EPOCH

    def tick(self) -> int:
        self.now += _TICK_S
        return self.now


class Checkout:
    """A working tree: a repository's primary worktree or one of its linked worktrees."""

    def __init__(self, path: Path, clock: _Clock) -> None:
        self.path = path
        self._clock = clock

    def git(self, *args: str) -> str:
        stamp = f"@{self._clock.tick()} +0000"
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed in {self.path}:\n{proc.stderr}")
        return proc.stdout.rstrip("\n")

    def commit(self, message: str, files: Mapping[str, str] | None = None) -> str:
        """Write ``files`` (relative path to content), commit everything, return the sha."""
        for name, content in (files or {}).items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.rev()

    def rev(self, revision: str = "HEAD") -> str:
        return self.git("rev-parse", "--verify", revision)

    def add_worktree(self, path: Path, branch: str, *, start: str = "main") -> Checkout:
        self.git("worktree", "add", "-q", "-b", branch, str(path), start)
        return Checkout(path, self._clock)

    def add_detached_worktree(self, path: Path, *, start: str = "main") -> Checkout:
        self.git("worktree", "add", "-q", "--detach", str(path), start)
        return Checkout(path, self._clock)

    def publish(self, branch: str = "main") -> None:
        """Point ``origin/<branch>`` and ``origin/HEAD`` at ``branch``, as a clone would."""
        self.git("update-ref", f"refs/remotes/origin/{branch}", branch)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")

    def object_counts(self) -> str:
        """``count-objects -v``: identical before and after anything write-free."""
        return self.git("count-objects", "-v")


class GitFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._clock = _Clock()

    def repository(self, path: Path) -> Checkout:
        """A new repository at ``path`` with one commit on ``main``."""
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "-c", "init.defaultBranch=main", "init", "-q", str(path)],
            capture_output=True,
            check=True,
        )
        checkout = Checkout(path, self._clock)
        checkout.commit("Initial commit", {"README": "base\n"})
        return checkout
