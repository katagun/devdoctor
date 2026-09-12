# Git Worktree Provider, PR 1: Shell `env` and Git Plumbing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the `Shell` port an `env` parameter and add `providers/_git.py` — the git invocation contract, failure handling and porcelain parsers — with no user-visible behaviour change.

**Architecture:** `Shell.run` gains `env: Mapping[str, str] | None = None`, applied on top of the inherited environment, in all three implementations. A new private module, `src/devdoctor/providers/_git.py`, holds pure parsers (`git version`, `worktree list --porcelain`, `status --porcelain`) and a `GitRunner` that runs every git call as `git --no-optional-locks -C <dir> …` with offline environment guards and a 30 s timeout, returning failures as values. Nothing in `src` calls `_git.py` yet; PR 2 builds the provider on it.

**Tech Stack:** Python 3.12, pytest, ruff, mypy (strict), uv.

**Spec:** `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` — this plan implements §9 PR 1, using §4.1, §4.3, §4.4 and §8 (layers 1 and 2).

## Global Constraints

- Python `>=3.12`; ruff `line-length = 100`, rules `E, F, I, UP, B, SIM, PL, RUF`; `mypy --strict` over `src/devdoctor`.
- `Shell.run` gains `env: Mapping[str, str] | None = None`: variables set on top of the inherited environment. `RealShell` passes `{**os.environ, **env}` to `subprocess.run`; `_NullShell` (`memory/providers.py`) accepts and ignores it; the test `FakeShell` records it. The default preserves current behaviour, and no existing caller changes. (spec §4.1)
- Every git call runs as `git --no-optional-locks -C <dir> …` through the `Shell` port. (spec §4.3)
- Every git call sets `GIT_TERMINAL_PROMPT=0` and `GIT_NO_LAZY_FETCH=1`. (spec §4.3)
- Every git call has a 30 second timeout. `subprocess.TimeoutExpired` and non-zero exits are returned as results, never raised. (spec §4.3)
- `git merge-tree` additionally sets `GIT_OBJECT_DIRECTORY` to a temporary directory and `GIT_ALTERNATE_OBJECT_DIRECTORIES` to `<common git dir>/objects`; only merge-tree gets these variables. (spec §4.3)
- merge-tree requires git 2.38 (`--write-tree`); below that the provider falls back to `merge-base --is-ancestor`. (spec §4.4)
- Advice text for a git failure uses `<first stderr line, or "timed out after 30 s">`. (spec §5.2)
- No behaviour change in this PR: no `src` module imports `devdoctor.providers._git`, `registry.py` is untouched, and there is no CHANGELOG entry (the CHANGELOG ships in PR 3, spec §9).
- Tests never assert on list position of scan entries; select by provider, path or label. (spec §8)
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. PR descriptions end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

## Commands

Run everything from the repository root. These mirror CI (`.github/workflows/ci.yml`):

```bash
uv run --extra dev --extra web ruff check src tests
uv run --extra dev --extra web ruff format --check src tests
uv run --extra dev --extra web mypy
uv run --extra dev --extra web pytest
```

## Fixture provenance

The porcelain and status strings in Task 2 are real output, captured from git 2.50.1 in a throwaway repository, with the fixture's temporary path replaced by `/fx`. Notable shapes, all of which the parsers must handle:

- records are separated by a blank line, and the output ends with one;
- a path containing a space follows `worktree ` verbatim, unquoted;
- `locked` appears alone or followed by a reason; `prunable` is always followed by a reason;
- a bare repository's record has `bare` and **no** `HEAD` line;
- `status --porcelain` quotes a path containing a space (` M "file name"`) and lists an untracked directory once, with a trailing slash (`?? scratch/`).

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/devdoctor/ports.py` | modify | `Shell` protocol and `RealShell` gain `env` |
| `src/devdoctor/memory/providers.py` | modify | `_NullShell` accepts `env` |
| `tests/conftest.py` | modify | `FakeShell` records `env` in a new `envs` list; `calls` keeps its shape |
| `tests/test_ports.py` | modify | port tests for `env` in every implementation |
| `src/devdoctor/providers/_git.py` | create | parsers, environment builders, `GitResult`, `GitRunner` |
| `tests/test_git_plumbing.py` | create | unit tests for `_git.py`, plus one real-git smoke test |

---

### Task 1: `Shell.run` accepts `env`

**Files:**
- Modify: `src/devdoctor/ports.py:1-45`
- Modify: `src/devdoctor/memory/providers.py:3` and `src/devdoctor/memory/providers.py:117-128`
- Modify: `tests/conftest.py:1-9` and `tests/conftest.py:34-67`
- Test: `tests/test_ports.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `Shell.run(self, argv: list[str], *, check: bool = False, timeout: float | None = None, env: Mapping[str, str] | None = None) -> ShellResult`, implemented by `RealShell`, `_NullShell` and `FakeShell`.
  - `FakeShell.envs: list[dict[str, str] | None]` — one entry per call, index-aligned with `FakeShell.calls`; `None` when the call passed no `env`.

- [ ] **Step 1: Write the failing tests**

Replace the imports at the top of `tests/test_ports.py` (lines 1-2) with:

```python
import os
import subprocess

import pytest

from devdoctor.memory.providers import _NullShell
from devdoctor.ports import RealShell
from devdoctor.types import ShellResult
from tests.conftest import FakeShell
```

In `test_real_shell_timeout_raises` at the end of the file, delete the now-redundant local imports `import subprocess` and `import pytest`, leaving:

```python
def test_real_shell_timeout_raises():
    sh = RealShell()
    with pytest.raises(subprocess.TimeoutExpired):
        sh.run(["sh", "-c", "sleep 5"], timeout=0.2)
```

Append to `tests/test_ports.py`:

```python
def test_real_shell_env_adds_variables_on_top_of_the_inherited_environment(monkeypatch):
    monkeypatch.setenv("DEVDOCTOR_INHERITED_PROBE", "inherited")
    r = RealShell().run(
        ["sh", "-c", 'printf "%s|%s" "$DEVDOCTOR_ENV_PROBE" "$DEVDOCTOR_INHERITED_PROBE"'],
        env={"DEVDOCTOR_ENV_PROBE": "set"},
    )
    assert r.stdout == "set|inherited"


def test_real_shell_env_overrides_an_inherited_variable(monkeypatch):
    monkeypatch.setenv("DEVDOCTOR_ENV_PROBE", "inherited")
    r = RealShell().run(
        ["sh", "-c", 'printf "%s" "$DEVDOCTOR_ENV_PROBE"'],
        env={"DEVDOCTOR_ENV_PROBE": "override"},
    )
    assert r.stdout == "override"


def test_real_shell_env_does_not_leak_into_this_process(monkeypatch):
    monkeypatch.delenv("DEVDOCTOR_ENV_PROBE", raising=False)
    RealShell().run(["true"], env={"DEVDOCTOR_ENV_PROBE": "set"})
    assert "DEVDOCTOR_ENV_PROBE" not in os.environ


def test_real_shell_without_env_inherits_the_environment(monkeypatch):
    # Regression guard: this already passes before the change, and must keep passing.
    monkeypatch.setenv("DEVDOCTOR_INHERITED_PROBE", "inherited")
    r = RealShell().run(["sh", "-c", 'printf "%s" "$DEVDOCTOR_INHERITED_PROBE"'])
    assert r.stdout == "inherited"


def test_null_shell_accepts_env():
    r = _NullShell().run(["true"], env={"DEVDOCTOR_ENV_PROBE": "set"})
    assert r == ShellResult(returncode=1, stdout="", stderr="")


def test_fake_shell_records_env_alongside_calls():
    ok = ShellResult(returncode=0, stdout="", stderr="")
    shell = FakeShell(responses={("git", "status"): ok, ("ls",): ok})
    shell.run(["git", "status"], env={"GIT_TERMINAL_PROMPT": "0"})
    shell.run(["ls"])
    assert shell.calls == [("git", "status"), ("ls",)]
    assert shell.envs == [{"GIT_TERMINAL_PROMPT": "0"}, None]


def test_fake_shell_env_record_is_a_snapshot():
    ok = ShellResult(returncode=0, stdout="", stderr="")
    shell = FakeShell(responses={("x",): ok})
    env = {"A": "1"}
    shell.run(["x"], env=env)
    env["A"] = "2"
    assert shell.envs == [{"A": "1"}]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_ports.py -v`

Expected: `test_real_shell_without_env_inherits_the_environment` and the five original tests PASS. The other six FAIL with `TypeError: ... run() got an unexpected keyword argument 'env'`.

- [ ] **Step 3: Implement `env` in the port and `RealShell`**

Replace the whole of `src/devdoctor/ports.py` with:

```python
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from typing import Protocol

from devdoctor.types import ShellResult


class Shell(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...


class RealShell:
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShellResult:
        proc = subprocess.run(
            argv,
            capture_output=True,
            check=check,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            # `env` adds to the inherited environment instead of replacing it, so a
            # caller setting one variable never loses PATH or HOME.
            env=None if env is None else {**os.environ, **env},
        )
        return ShellResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)
```

- [ ] **Step 4: Implement `env` in `_NullShell`**

In `src/devdoctor/memory/providers.py`, change line 3 from:

```python
from collections.abc import Iterable
```

to:

```python
from collections.abc import Iterable, Mapping
```

and replace `_NullShell` (lines 117-128) with:

```python
class _NullShell:
    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShellResult:
        return ShellResult(returncode=1, stdout="", stderr="")

    def which(self, name: str) -> str | None:
        return None
```

- [ ] **Step 5: Record `env` in `FakeShell`**

In `tests/conftest.py`, add after `import threading` (line 3):

```python
from collections.abc import Mapping
```

Then replace the `FakeShell` class (lines 34-67) with:

```python
@dataclass
class FakeShell:
    """Argv-keyed fake. Matches full argv tuple exactly.

    Unconfigured calls raise so tests surface unexpected commands.
    """

    responses: dict[tuple[str, ...], ShellResult] = field(default_factory=dict)
    which_table: dict[str, str | None] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    # The environment passed with each call, index-aligned with `calls` (None when
    # a call passed no env). Kept separate so assertions on `calls` keep their shape.
    envs: list[dict[str, str] | None] = field(default_factory=list)
    # Discovery runs providers concurrently (devdoctor.discovery.scan), and a
    # single shell instance can be shared across those providers, so record
    # calls under a lock to keep `calls` consistent under concurrent run().
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def run(
        self,
        argv: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ShellResult:
        # `check` and `timeout` are accepted for Protocol conformance but
        # not enforced by the fake — tests configure their responses explicitly.
        del check, timeout
        key = tuple(argv)
        with self._lock:
            self.calls.append(key)
            self.envs.append(None if env is None else dict(env))
        if key not in self.responses:
            raise AssertionError(f"FakeShell: unexpected call: {argv}")
        return self.responses[key]

    def which(self, binary: str) -> str | None:
        return self.which_table.get(binary)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_ports.py -v`
Expected: all 12 tests PASS.

Then run the full suite, lint and types, since the port is shared:

Run: `uv run --extra dev --extra web pytest -q && uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: all tests pass; `All checks passed!`; `already formatted`; `Success: no issues found`.

- [ ] **Step 7: Commit**

```bash
git add src/devdoctor/ports.py src/devdoctor/memory/providers.py tests/conftest.py tests/test_ports.py
git commit -m "feat: let Shell.run set environment variables" -m "Shell.run gains an optional env mapping, applied on top of the inherited environment, in RealShell, _NullShell and the test FakeShell. FakeShell records it in a separate envs list so existing assertions on calls keep their shape. No caller passes env yet; the git worktree provider will." -m "Refs #79" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Git output parsers

**Files:**
- Create: `src/devdoctor/providers/_git.py`
- Test: `tests/test_git_plumbing.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `MERGE_TREE_MIN_VERSION: tuple[int, int, int] = (2, 38, 0)`
  - `parse_git_version(output: str) -> tuple[int, int, int] | None`
  - `supports_merge_tree_write_tree(version: tuple[int, int, int] | None) -> bool`
  - `@dataclass(frozen=True) class WorktreeRecord` with fields `path: Path`, `head: str | None`, `branch: str | None` (short name, `refs/heads/` removed), `detached: bool = False`, `bare: bool = False`, `locked: bool = False`, `lock_reason: str | None = None`, `prunable: bool = False`, `prunable_reason: str | None = None`
  - `parse_worktree_porcelain(output: str) -> list[WorktreeRecord]` (git's order; the first record is the primary worktree)
  - `@dataclass(frozen=True) class StatusCounts` with fields `modified: int`, `untracked: int` and property `is_clean: bool`
  - `parse_status_porcelain(output: str) -> StatusCounts`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_git_plumbing.py`:

```python
from pathlib import Path

import pytest

from devdoctor.providers._git import (
    MERGE_TREE_MIN_VERSION,
    StatusCounts,
    WorktreeRecord,
    parse_git_version,
    parse_status_porcelain,
    parse_worktree_porcelain,
    supports_merge_tree_write_tree,
)

SHA = "39014f227ec96b48d94c59dd54e6a5dc15566be4"

# Real `git worktree list --porcelain` output (git 2.50.1), fixture path replaced by /fx.
PORCELAIN = (
    "worktree /fx/repo\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/main\n"
    "\n"
    "worktree /fx/wt/detached\n"
    f"HEAD {SHA}\n"
    "detached\n"
    "\n"
    "worktree /fx/wt/feature branch\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/feature\n"
    "\n"
    "worktree /fx/wt/gone\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/gone\n"
    "prunable gitdir file points to non-existent location\n"
    "\n"
    "worktree /fx/wt/locked-plain\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/lp\n"
    "locked\n"
    "\n"
    "worktree /fx/wt/locked-reason\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/lr\n"
    "locked agent running\n"
    "\n"
)

# Real porcelain output from a bare repository with one linked worktree.
BARE_PORCELAIN = (
    "worktree /fx/bare.git\n"
    "bare\n"
    "\n"
    "worktree /fx/wt/from-bare\n"
    f"HEAD {SHA}\n"
    "branch refs/heads/main\n"
    "\n"
)

# Real `git status --porcelain --untracked-files=normal` output.
DIRTY_STATUS = ' M a\nR  b -> b2\nA  c\n M "file name"\n?? notes.txt\n?? scratch/\n'


def test_parse_worktree_porcelain_keeps_git_order_with_primary_first():
    paths = [record.path for record in parse_worktree_porcelain(PORCELAIN)]
    assert paths == [
        Path("/fx/repo"),
        Path("/fx/wt/detached"),
        Path("/fx/wt/feature branch"),
        Path("/fx/wt/gone"),
        Path("/fx/wt/locked-plain"),
        Path("/fx/wt/locked-reason"),
    ]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param(
            "/fx/repo",
            WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
            id="on-branch",
        ),
        pytest.param(
            "/fx/wt/detached",
            WorktreeRecord(path=Path("/fx/wt/detached"), head=SHA, branch=None, detached=True),
            id="detached",
        ),
        pytest.param(
            "/fx/wt/feature branch",
            WorktreeRecord(path=Path("/fx/wt/feature branch"), head=SHA, branch="feature"),
            id="path-with-space",
        ),
        pytest.param(
            "/fx/wt/gone",
            WorktreeRecord(
                path=Path("/fx/wt/gone"),
                head=SHA,
                branch="gone",
                prunable=True,
                prunable_reason="gitdir file points to non-existent location",
            ),
            id="prunable-with-reason",
        ),
        pytest.param(
            "/fx/wt/locked-plain",
            WorktreeRecord(path=Path("/fx/wt/locked-plain"), head=SHA, branch="lp", locked=True),
            id="locked-without-reason",
        ),
        pytest.param(
            "/fx/wt/locked-reason",
            WorktreeRecord(
                path=Path("/fx/wt/locked-reason"),
                head=SHA,
                branch="lr",
                locked=True,
                lock_reason="agent running",
            ),
            id="locked-with-reason",
        ),
    ],
)
def test_parse_worktree_porcelain_record_shapes(path, expected):
    records = {str(record.path): record for record in parse_worktree_porcelain(PORCELAIN)}
    assert records[path] == expected


def test_parse_worktree_porcelain_bare_record_has_no_head():
    records = parse_worktree_porcelain(BARE_PORCELAIN)
    assert records[0] == WorktreeRecord(
        path=Path("/fx/bare.git"), head=None, branch=None, bare=True
    )
    assert records[1] == WorktreeRecord(path=Path("/fx/wt/from-bare"), head=SHA, branch="main")


def test_parse_worktree_porcelain_ignores_unknown_attributes():
    output = f"worktree /fx/repo\nHEAD {SHA}\nbranch refs/heads/main\nfuture-attribute x\n\n"
    assert parse_worktree_porcelain(output) == [
        WorktreeRecord(path=Path("/fx/repo"), head=SHA, branch="main"),
    ]


def test_parse_worktree_porcelain_empty_output():
    assert parse_worktree_porcelain("") == []


def test_parse_status_porcelain_counts_tracked_changes_and_untracked_entries():
    counts = parse_status_porcelain(DIRTY_STATUS)
    assert counts == StatusCounts(modified=4, untracked=2)
    assert counts.is_clean is False


def test_parse_status_porcelain_clean_worktree():
    counts = parse_status_porcelain("")
    assert counts == StatusCounts(modified=0, untracked=0)
    assert counts.is_clean is True


def test_parse_status_porcelain_does_not_count_ignored_entries():
    assert parse_status_porcelain("!! node_modules/\n") == StatusCounts(modified=0, untracked=0)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        pytest.param("git version 2.50.1 (Apple Git-155)\n", (2, 50, 1), id="apple"),
        pytest.param("git version 2.43.0\n", (2, 43, 0), id="linux"),
        pytest.param("git version 2.45.1.windows.1\n", (2, 45, 1), id="windows-suffix"),
        pytest.param("git version 2.39\n", (2, 39, 0), id="no-patch"),
        pytest.param("", None, id="empty"),
        pytest.param("not git at all\n", None, id="garbage"),
    ],
)
def test_parse_git_version(output, expected):
    assert parse_git_version(output) == expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        pytest.param(MERGE_TREE_MIN_VERSION, True, id="exactly-minimum"),
        pytest.param((2, 50, 1), True, id="newer"),
        pytest.param((2, 37, 9), False, id="older"),
        pytest.param(None, False, id="unknown"),
    ],
)
def test_supports_merge_tree_write_tree(version, expected):
    assert supports_merge_tree_write_tree(version) is expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_git_plumbing.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'devdoctor.providers._git'`.

- [ ] **Step 3: Write the parsers**

Create `src/devdoctor/providers/_git.py`:

```python
"""Git plumbing for providers that inspect repositories.

This module owns how DevDoctor talks to git: the parsers for the output formats
the git worktree provider reads and, from Task 3 onward, the argv, environment,
timeout and failure handling every git call uses. It knows nothing about
providers, entries or risk.

Spec: docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# `git merge-tree --write-tree` first shipped in git 2.38. Older git falls back to
# `merge-base --is-ancestor` (spec §4.4).
MERGE_TREE_MIN_VERSION: tuple[int, int, int] = (2, 38, 0)

_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)(?:\.(\d+))?")
_BRANCH_REF_PREFIX = "refs/heads/"


def parse_git_version(output: str) -> tuple[int, int, int] | None:
    """Parse ``git version`` output such as ``git version 2.50.1 (Apple Git-155)``."""
    match = _VERSION_RE.match(output.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def supports_merge_tree_write_tree(version: tuple[int, int, int] | None) -> bool:
    return version is not None and version >= MERGE_TREE_MIN_VERSION


@dataclass(frozen=True)
class WorktreeRecord:
    """One record from ``git worktree list --porcelain``."""

    path: Path
    head: str | None
    branch: str | None
    detached: bool = False
    bare: bool = False
    locked: bool = False
    lock_reason: str | None = None
    prunable: bool = False
    prunable_reason: str | None = None


def parse_worktree_porcelain(output: str) -> list[WorktreeRecord]:
    """Parse ``git worktree list --porcelain`` into records, in git's order.

    The first record is always the repository's primary worktree. A path follows
    ``worktree `` verbatim, so paths containing spaces survive. Attributes this
    parser does not know are ignored, so newer git versions keep parsing.
    """
    records: list[WorktreeRecord] = []
    for block in output.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line:
                key, _, value = line.partition(" ")
                fields[key] = value
        if "worktree" not in fields:
            continue
        branch = fields.get("branch")
        records.append(
            WorktreeRecord(
                path=Path(fields["worktree"]),
                head=fields.get("HEAD"),
                branch=branch.removeprefix(_BRANCH_REF_PREFIX) if branch else None,
                detached="detached" in fields,
                bare="bare" in fields,
                locked="locked" in fields,
                lock_reason=fields.get("locked") or None,
                prunable="prunable" in fields,
                prunable_reason=fields.get("prunable") or None,
            )
        )
    return records


@dataclass(frozen=True)
class StatusCounts:
    """Counts from ``git status --porcelain``.

    ``modified`` counts every tracked entry with a staged or unstaged change:
    modifications, additions, deletions and renames. ``untracked`` counts ``??``
    entries; an untracked directory is one entry.
    """

    modified: int
    untracked: int

    @property
    def is_clean(self) -> bool:
        return self.modified == 0 and self.untracked == 0


def parse_status_porcelain(output: str) -> StatusCounts:
    modified = 0
    untracked = 0
    for line in output.splitlines():
        if not line:
            continue
        if line.startswith("?? "):
            untracked += 1
        elif not line.startswith("!! "):
            modified += 1
    return StatusCounts(modified=modified, untracked=untracked)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_git_plumbing.py -v`
Expected: all tests PASS (1 order test, 6 record shapes, bare, unknown attributes, empty, 3 status tests, 6 version cases, 4 merge-tree support cases).

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`; `already formatted`; `Success: no issues found`.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/_git.py tests/test_git_plumbing.py
git commit -m "feat: parse git version, worktree and status porcelain" -m "Pure parsers for the git output the worktree provider reads, tested against output captured from real git: detached HEAD, locked with and without a reason, prunable, bare records without HEAD, paths containing spaces, and every status line kind." -m "Refs #79" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Git invocation contract

**Files:**
- Modify: `src/devdoctor/providers/_git.py`
- Test: `tests/test_git_plumbing.py`

**Interfaces:**
- Consumes: `Shell.run(..., env=...)` from Task 1; `parse_git_version` from Task 2.
- Produces:
  - `GIT_CALL_TIMEOUT_S: float = 30.0`
  - `git_env(extra: Mapping[str, str] | None = None) -> dict[str, str]` — `extra` plus `GIT_TERMINAL_PROMPT=0` and `GIT_NO_LAZY_FETCH=1`, the guards winning any conflict
  - `merge_tree_env(temp_objects_dir: Path, common_git_dir: Path) -> dict[str, str]` — `GIT_OBJECT_DIRECTORY` and `GIT_ALTERNATE_OBJECT_DIRECTORIES`
  - `@dataclass(frozen=True) class GitResult` with fields `returncode: int | None`, `stdout: str`, `stderr: str`, `timed_out: bool`, `timeout_s: float`; property `ok: bool`; method `failure_summary() -> str`
  - `class GitRunner` with `__init__(self, shell: Shell, *, timeout_s: float = GIT_CALL_TIMEOUT_S)`, `run(self, directory: Path, args: Sequence[str], *, extra_env: Mapping[str, str] | None = None) -> GitResult`, and `version(self) -> tuple[int, int, int] | None`

- [ ] **Step 1: Write the failing tests**

Replace the imports at the top of `tests/test_git_plumbing.py` with:

```python
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from devdoctor.ports import RealShell
from devdoctor.providers._git import (
    GIT_CALL_TIMEOUT_S,
    MERGE_TREE_MIN_VERSION,
    GitResult,
    GitRunner,
    StatusCounts,
    WorktreeRecord,
    git_env,
    merge_tree_env,
    parse_git_version,
    parse_status_porcelain,
    parse_worktree_porcelain,
    supports_merge_tree_write_tree,
)
from devdoctor.types import ShellResult
from tests.conftest import FakeShell
```

Append to `tests/test_git_plumbing.py`:

```python
OFFLINE_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}
STATUS_ARGV = ("git", "--no-optional-locks", "-C", "/repo", "status", "--porcelain")


@dataclass
class _ScriptedShell:
    """Shell double that records timeouts and can raise, which FakeShell cannot."""

    result: ShellResult = field(
        default_factory=lambda: ShellResult(returncode=0, stdout="", stderr="")
    )
    raises: BaseException | None = None
    timeouts: list[float | None] = field(default_factory=list)

    def run(self, argv, *, check=False, timeout=None, env=None):
        self.timeouts.append(timeout)
        if self.raises is not None:
            raise self.raises
        return self.result

    def which(self, binary):
        return None


def test_runner_uses_no_optional_locks_and_the_directory():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    GitRunner(shell).run(Path("/repo"), ["status", "--porcelain"])
    assert shell.calls == [STATUS_ARGV]


def test_runner_sets_offline_guards_on_every_call():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    runner = GitRunner(shell)
    runner.run(Path("/repo"), ["status", "--porcelain"])
    runner.run(Path("/repo"), ["status", "--porcelain"])
    assert shell.envs == [OFFLINE_ENV, OFFLINE_ENV]


def test_runner_adds_extra_env_to_the_offline_guards():
    shell = FakeShell(responses={STATUS_ARGV: ShellResult(returncode=0, stdout="", stderr="")})
    GitRunner(shell).run(
        Path("/repo"), ["status", "--porcelain"], extra_env={"GIT_OBJECT_DIRECTORY": "/tmp/o"}
    )
    assert shell.envs == [{**OFFLINE_ENV, "GIT_OBJECT_DIRECTORY": "/tmp/o"}]


def test_offline_guards_cannot_be_overridden():
    assert git_env({"GIT_TERMINAL_PROMPT": "1", "GIT_NO_LAZY_FETCH": "0"}) == OFFLINE_ENV


def test_runner_default_timeout_is_30_seconds():
    shell = _ScriptedShell()
    GitRunner(shell).run(Path("/repo"), ["status"])
    assert GIT_CALL_TIMEOUT_S == 30.0
    assert shell.timeouts == [30.0]


def test_runner_success_is_a_result():
    shell = _ScriptedShell(result=ShellResult(returncode=0, stdout="out\n", stderr=""))
    result = GitRunner(shell).run(Path("/repo"), ["status"])
    assert result == GitResult(
        returncode=0, stdout="out\n", stderr="", timed_out=False, timeout_s=30.0
    )
    assert result.ok is True


def test_runner_non_zero_exit_is_a_result_with_the_first_stderr_line():
    stderr = "fatal: not a git repository: /x\nhint: something else\n"
    shell = _ScriptedShell(result=ShellResult(returncode=128, stdout="", stderr=stderr))
    result = GitRunner(shell).run(Path("/x"), ["rev-parse", "--show-toplevel"])
    assert result.ok is False
    assert result.failure_summary() == "fatal: not a git repository: /x"


def test_runner_timeout_is_a_result_not_an_exception():
    shell = _ScriptedShell(raises=subprocess.TimeoutExpired(cmd=["git"], timeout=30.0))
    result = GitRunner(shell).run(Path("/repo"), ["merge-tree", "--write-tree", "main", "HEAD"])
    assert result.timed_out is True
    assert result.ok is False
    assert result.returncode is None
    assert result.failure_summary() == "timed out after 30 s"


def test_runner_launch_failure_is_a_result_not_an_exception():
    shell = _ScriptedShell(raises=FileNotFoundError(2, "No such file or directory", "git"))
    result = GitRunner(shell).run(Path("/repo"), ["status"])
    assert result.ok is False
    assert result.timed_out is False
    assert "No such file or directory" in result.failure_summary()


def test_failure_summary_without_stderr_names_the_exit_code():
    shell = _ScriptedShell(result=ShellResult(returncode=1, stdout="", stderr=""))
    result = GitRunner(shell).run(Path("/repo"), ["merge-base", "--is-ancestor", "a", "b"])
    assert result.failure_summary() == "exit 1"


def test_merge_tree_env_redirects_object_writes_and_reads_the_real_store():
    assert merge_tree_env(Path("/tmp/objects"), Path("/repo/.git")) == {
        "GIT_OBJECT_DIRECTORY": "/tmp/objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/repo/.git/objects",
    }


def test_version_is_read_through_the_contract():
    argv = ("git", "--no-optional-locks", "-C", "/", "version")
    ok = ShellResult(returncode=0, stdout="git version 2.50.1 (Apple Git-155)\n", stderr="")
    shell = FakeShell(responses={argv: ok})
    assert GitRunner(shell).version() == (2, 50, 1)
    assert shell.envs == [OFFLINE_ENV]


def test_version_is_none_when_git_fails():
    shell = _ScriptedShell(result=ShellResult(returncode=1, stdout="", stderr="boom"))
    assert GitRunner(shell).version() is None


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_real_git_accepts_the_invocation_contract():
    # Smoke test: the global options and environment are valid for the git on this machine.
    version = GitRunner(RealShell()).version()
    assert version is not None
    assert version >= (2, 0, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_git_plumbing.py -v`
Expected: collection ERROR — `ImportError: cannot import name 'GIT_CALL_TIMEOUT_S' from 'devdoctor.providers._git'`.

- [ ] **Step 3: Implement the invocation contract**

In `src/devdoctor/providers/_git.py`, replace the import block:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
```

with:

```python
from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from devdoctor.ports import Shell
```

Then append to the end of `src/devdoctor/providers/_git.py`:

```python
# Every git call is bounded, so one hung repository cannot stall a scan (spec §4.3).
GIT_CALL_TIMEOUT_S = 30.0

# Set on every git call: never prompt for credentials, and never fetch missing
# objects from a promisor remote. Applied last, so no caller can switch them off.
_OFFLINE_ENV: dict[str, str] = {"GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}


def git_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment for one git call: ``extra`` plus the offline guards, which win."""
    return {**(extra or {}), **_OFFLINE_ENV}


def merge_tree_env(temp_objects_dir: Path, common_git_dir: Path) -> dict[str, str]:
    """Extra environment that sends ``git merge-tree``'s object writes to a temp dir.

    Reads still resolve through the repository's own object store. Only merge-tree
    may use this; every other call needs the real object store (spec §4.3).
    """
    return {
        "GIT_OBJECT_DIRECTORY": str(temp_objects_dir),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(common_git_dir / "objects"),
    }


@dataclass(frozen=True)
class GitResult:
    """The outcome of one git call. Failures are values, never exceptions."""

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    timeout_s: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def failure_summary(self) -> str:
        """One line describing a failure, for advice messages (spec §5.2)."""
        if self.timed_out:
            return f"timed out after {self.timeout_s:g} s"
        for line in self.stderr.splitlines():
            if line.strip():
                return line.strip()
        return f"exit {self.returncode}"


class GitRunner:
    """Runs git through the ``Shell`` port under the invocation contract (spec §4.3)."""

    def __init__(self, shell: Shell, *, timeout_s: float = GIT_CALL_TIMEOUT_S) -> None:
        self._shell = shell
        self._timeout_s = timeout_s

    def run(
        self,
        directory: Path,
        args: Sequence[str],
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> GitResult:
        argv = ["git", "--no-optional-locks", "-C", str(directory), *args]
        try:
            result = self._shell.run(
                argv,
                check=False,
                timeout=self._timeout_s,
                env=git_env(extra_env),
            )
        except subprocess.TimeoutExpired:
            return GitResult(None, "", "", timed_out=True, timeout_s=self._timeout_s)
        except OSError as exc:
            # git vanished or could not be launched: still a result, never a crash.
            return GitResult(None, "", str(exc), timed_out=False, timeout_s=self._timeout_s)
        return GitResult(
            result.returncode,
            result.stdout,
            result.stderr,
            timed_out=False,
            timeout_s=self._timeout_s,
        )

    def version(self) -> tuple[int, int, int] | None:
        """The installed git's version, or ``None`` if it cannot be determined."""
        # `version` is not repository-scoped; "/" is a directory that always exists.
        result = self.run(Path("/"), ["version"])
        return parse_git_version(result.stdout) if result.ok else None
```

Also update the module docstring's first paragraph, which Task 2 phrased provisionally. Replace:

```python
This module owns how DevDoctor talks to git: the parsers for the output formats
the git worktree provider reads and, from Task 3 onward, the argv, environment,
timeout and failure handling every git call uses. It knows nothing about
providers, entries or risk.
```

with:

```python
This module owns how DevDoctor talks to git: the argv, environment, timeout and
failure handling every git call uses, and parsers for the output formats the git
worktree provider reads. It knows nothing about providers, entries or risk.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_git_plumbing.py -v`
Expected: all tests PASS, including `test_real_git_accepts_the_invocation_contract` (SKIPPED only where git is not installed).

Run: `uv run --extra dev --extra web ruff check src tests && uv run --extra dev --extra web ruff format --check src tests && uv run --extra dev --extra web mypy`
Expected: `All checks passed!`; `already formatted`; `Success: no issues found`.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/_git.py tests/test_git_plumbing.py
git commit -m "feat: add the git invocation contract" -m "GitRunner runs every git call as git --no-optional-locks -C <dir> with GIT_TERMINAL_PROMPT=0 and GIT_NO_LAZY_FETCH=1, which callers cannot override, and a 30 s timeout. Timeouts, launch failures and non-zero exits come back as GitResult values with a one-line failure summary for advice messages. merge_tree_env redirects merge-tree's object writes to a temporary directory. Nothing in src uses it yet." -m "Refs #79" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Verify the PR and open it

**Files:**
- No source changes.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: PR 1 on GitHub.

- [ ] **Step 1: Confirm there is no behaviour change**

Run: `grep -rn --include='*.py' "providers\._git\|providers import _git" src/ || echo "no src imports of _git"`
Expected: `no src imports of _git`.

Run: `git diff --stat origin/main -- src/devdoctor/registry.py CHANGELOG.md`
Expected: no output.

- [ ] **Step 2: Run the full CI mirror**

Run each command from the Commands section.
Expected: ruff `All checks passed!`; ruff format `already formatted`; mypy `Success: no issues found`; pytest all pass with no failures.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/git-plumbing-foundation
gh pr create --base main --title "feat: Shell env support and git plumbing for the worktree provider" --body "$(cat <<'EOF'
PR 1 of 4 for #79, per the design spec (docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md §9). No user-visible behaviour change.

## What

- `Shell.run` gains an optional `env`, applied on top of the inherited environment, in `RealShell`, `_NullShell` and the test `FakeShell`. `FakeShell` records it in a separate `envs` list, so existing assertions on `calls` keep their shape.
- New `devdoctor.providers._git`:
  - parsers for `git version`, `git worktree list --porcelain` and `git status --porcelain`, tested against output captured from real git;
  - `GitRunner`, which runs every call as `git --no-optional-locks -C <dir>` with `GIT_TERMINAL_PROMPT=0` and `GIT_NO_LAZY_FETCH=1` and a 30 s timeout, and returns timeouts, launch failures and non-zero exits as values;
  - `merge_tree_env`, which redirects merge-tree's object writes to a temporary directory.

## Not in this PR

Nothing in `src` imports `_git.py` yet. Discovery and classification arrive in PR 2, unregistered; the provider is switched on in PR 3, together with containment.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Merge once the required checks pass**

The required checks are `Python (lint, types, tests)` and `Web (typecheck, tests, build)`. When both pass:

```bash
gh pr merge --squash --delete-branch
```

If a check fails, read its log, fix the cause on the branch, and push again. Do not merge on a red check.
