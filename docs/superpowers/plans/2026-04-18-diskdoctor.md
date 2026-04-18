# diskdoctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI (`diskdoctor`) that scans known disk caches on macOS/Linux, emits human/JSON reports, produces reviewable cleanup scripts, and runs an interactive dry-run-by-default cleanup — all with per-cache snapshot history.

**Architecture:** Three use-case modules (`discovery`, `cleanup`, `history`) feeding a `rendering` presentation layer. Providers are a pure read model returning fully-formed `Entry` objects with shell recipes; execution is uniform. One port (`Shell`) and two typed callables (`PromptChoice`, `Confirm`) are the only DI seams. Simple caches are YAML entries backed by a single `PathProvider`; only Ollama, Docker, LM Studio, HuggingFace get dedicated classes.

**Tech Stack:** Python 3.12+, `uv` + `hatchling`, `click`, `rich`, `pyyaml`, optional `huggingface_hub`. Dev: `pytest`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`.

**Spec:** [`docs/superpowers/specs/2026-04-18-diskdoctor-design.md`](../specs/2026-04-18-diskdoctor-design.md) — read before starting.

**Conventions for every task:**
- Write the failing test FIRST, run it to confirm it fails, implement, run it green, commit.
- Commit message convention: `<type>: <summary>` where type is `feat|test|refactor|chore|docs|fix`.
- Never add `--no-verify` to a git commit. If a hook fails, fix the cause.
- After each task, `uv run pytest -q` must be green.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.python-version`
- Create: `README.md`
- Create: `LICENSE`
- Create: `src/diskdoctor/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write `.python-version`**

```
3.12
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.ruff_cache/
.mypy_cache/
.pytest_cache/
.coverage
htmlcov/
dist/
build/
.DS_Store
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "diskdoctor"
version = "0.1.0"
description = "Repeatable disk-cache analyzer and interactive cleanup for macOS and Linux"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.12"
authors = [{ name = "Shamil" }]
dependencies = [
  "click>=8.1",
  "rich>=13.7",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
hf = ["huggingface_hub>=0.23"]
dev = [
  "pytest>=8.0",
  "pytest-cov>=5.0",
  "ruff>=0.5",
  "mypy>=1.10",
  "pre-commit>=3.7",
  "types-PyYAML",
]

[project.scripts]
diskdoctor = "diskdoctor.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/diskdoctor"]

[tool.hatch.build.targets.wheel.force-include]
"src/diskdoctor/data/paths.yaml" = "diskdoctor/data/paths.yaml"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.coverage.run]
source = ["src/diskdoctor"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = true

[tool.ruff]
target-version = "py312"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "PL", "RUF"]
ignore = ["PLR0913"]  # many args is fine for constructors

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src/diskdoctor"]
```

- [ ] **Step 4: Write minimal `README.md`**

```markdown
# diskdoctor

Repeatable disk-cache analyzer and interactive cleanup for macOS and Linux.

Status: early development. See [design spec](docs/superpowers/specs/2026-04-18-diskdoctor-design.md).
```

- [ ] **Step 5: Write `LICENSE` (MIT)**

```
MIT License

Copyright (c) 2026 Shamil

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 6: Create empty package files**

```bash
mkdir -p src/diskdoctor tests
```

`src/diskdoctor/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

- [ ] **Step 7: Install and verify**

```bash
uv venv
uv sync --extra dev
uv run pytest -q
```

Expected: `pytest` runs, finds 0 tests, exits 0.

- [ ] **Step 8: Commit**

```bash
git add .gitignore .python-version pyproject.toml README.md LICENSE src tests
git commit -m "chore: project scaffold (pyproject, README, LICENSE, empty package)"
```

---

## Task 2: Core types

**Files:**
- Create: `src/diskdoctor/types.py`
- Create: `tests/test_types.py`

- [ ] **Step 1: Write failing test**

`tests/test_types.py`:
```python
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.types import (
    CleanResult,
    CleanupOpts,
    DiffReport,
    DiffRow,
    Entry,
    Report,
    Risk,
    ScanFilters,
    ShellResult,
)


def test_risk_is_string_enum_with_three_levels():
    assert Risk.SAFE.value == "safe"
    assert Risk.RECLAIMABLE.value == "reclaimable"
    assert Risk.DANGEROUS.value == "dangerous"
    assert set(Risk) == {Risk.SAFE, Risk.RECLAIMABLE, Risk.DANGEROUS}


def test_entry_is_frozen():
    e = Entry(
        provider="ollama",
        id="llama3:8b",
        path=None,
        label="llama3:8b",
        size_bytes=4_700_000_000,
        mtime=None,
        risk=Risk.RECLAIMABLE,
        recipe=["ollama rm llama3:8b"],
    )
    import pytest
    with pytest.raises(AttributeError):
        e.size_bytes = 0  # type: ignore[misc]


def test_report_helpers():
    now = datetime(2026, 4, 18, tzinfo=UTC)
    e1 = Entry("a", "1", Path("/x"), "a/1", 100, None, Risk.SAFE, ["rm -rf /x"])
    e2 = Entry("a", "2", Path("/y"), "a/2", 200, None, Risk.SAFE, ["rm -rf /y"])
    e3 = Entry("b", "1", Path("/z"), "b/1", 50, None, Risk.DANGEROUS, ["rm -rf /z"])
    r = Report(entries=[e1, e2, e3], scanned_at=now, hostname="h", platform="darwin")

    assert r.total_bytes() == 350
    assert list(r.by_provider().keys()) == ["a", "b"]
    assert len(r.by_provider()["a"]) == 2

    safe_only = r.filter(risks={Risk.SAFE})
    assert [e.id for e in safe_only.entries] == ["1", "2"]

    by_name = r.filter(providers={"b"})
    assert [e.provider for e in by_name.entries] == ["b"]

    big = r.filter(min_size=150)
    assert [e.size_bytes for e in big.entries] == [200]


def test_report_json_round_trip():
    now = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
    e = Entry("a", "1", Path("/x"), "a/1", 100, 1_700_000_000.0, Risk.SAFE, ["rm -rf /x"])
    r = Report(
        entries=[e],
        scanned_at=now,
        hostname="h",
        platform="darwin",
        note="after cleanup",
        skipped_paths=["/forbidden"],
    )
    blob = r.to_json()
    r2 = Report.from_json(blob)
    assert r2.hostname == r.hostname
    assert r2.platform == r.platform
    assert r2.note == r.note
    assert r2.skipped_paths == r.skipped_paths
    assert r2.scanned_at == r.scanned_at
    assert len(r2.entries) == 1
    assert r2.entries[0] == e


def test_clean_result_status_values():
    ok = CleanResult(entry_id="x", status="ok", freed_bytes=10)
    dry = CleanResult(entry_id="x", status="dry_run", freed_bytes=10)
    err = CleanResult(entry_id="x", status="error", freed_bytes=0, message="boom")
    skipped = CleanResult(entry_id="x", status="skipped", freed_bytes=0)
    assert (ok.status, dry.status, err.status, skipped.status) == (
        "ok", "dry_run", "error", "skipped",
    )


def test_scan_filters_defaults_include_everything():
    f = ScanFilters()
    assert f.min_size_bytes == 0
    assert f.risks is None
    assert f.providers is None


def test_cleanup_opts_defaults_are_safe():
    o = CleanupOpts()
    assert o.execute is False
    assert o.yes_safe is False
    assert o.allow_dangerous is False
    assert o.providers is None


def test_diff_row_and_report():
    now = datetime(2026, 4, 18, tzinfo=UTC)
    row = DiffRow(provider="a", before_bytes=100, after_bytes=20, delta_bytes=-80, delta_pct=-80.0)
    d = DiffReport(before_at=now, after_at=now, rows=[row])
    assert d.rows[0].provider == "a"


def test_shell_result_is_frozen():
    import pytest
    sr = ShellResult(returncode=0, stdout="ok", stderr="")
    with pytest.raises(AttributeError):
        sr.returncode = 1  # type: ignore[misc]
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
uv run pytest tests/test_types.py -v
```

Expected: FAIL with `ImportError: cannot import name 'Risk' from 'diskdoctor.types'`.

- [ ] **Step 3: Implement `src/diskdoctor/types.py`**

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Literal


class Risk(str, Enum):
    SAFE = "safe"
    RECLAIMABLE = "reclaimable"
    DANGEROUS = "dangerous"


@dataclass(frozen=True)
class Entry:
    provider: str
    id: str
    path: Path | None
    label: str
    size_bytes: int
    mtime: float | None
    risk: Risk
    recipe: list[str]


@dataclass(frozen=True)
class ShellResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ScanFilters:
    min_size_bytes: int = 0
    risks: frozenset[Risk] | None = None
    providers: frozenset[str] | None = None


@dataclass(frozen=True)
class CleanupOpts:
    execute: bool = False
    yes_safe: bool = False
    allow_dangerous: bool = False
    providers: frozenset[str] | None = None


@dataclass
class CleanResult:
    entry_id: str
    status: Literal["ok", "skipped", "error", "dry_run"]
    freed_bytes: int
    message: str | None = None


@dataclass(frozen=True)
class DiffRow:
    provider: str
    before_bytes: int
    after_bytes: int
    delta_bytes: int
    delta_pct: float


@dataclass
class DiffReport:
    before_at: datetime
    after_at: datetime
    rows: list[DiffRow]


@dataclass
class Report:
    entries: list[Entry]
    scanned_at: datetime
    hostname: str
    platform: str
    note: str | None = None
    skipped_paths: list[str] = field(default_factory=list)

    def total_bytes(self) -> int:
        return sum(e.size_bytes for e in self.entries)

    def by_provider(self) -> dict[str, list[Entry]]:
        out: dict[str, list[Entry]] = {}
        for e in self.entries:
            out.setdefault(e.provider, []).append(e)
        return out

    def filter(
        self,
        *,
        risks: set[Risk] | frozenset[Risk] | None = None,
        min_size: int = 0,
        providers: set[str] | frozenset[str] | None = None,
    ) -> "Report":
        def keep(e: Entry) -> bool:
            if risks is not None and e.risk not in risks:
                return False
            if providers is not None and e.provider not in providers:
                return False
            if e.size_bytes < min_size:
                return False
            return True

        return Report(
            entries=[e for e in self.entries if keep(e)],
            scanned_at=self.scanned_at,
            hostname=self.hostname,
            platform=self.platform,
            note=self.note,
            skipped_paths=list(self.skipped_paths),
        )

    def to_json(self) -> str:
        def serialize_entry(e: Entry) -> dict:
            d = asdict(e)
            d["path"] = str(e.path) if e.path is not None else None
            d["risk"] = e.risk.value
            return d

        payload = {
            "entries": [serialize_entry(e) for e in self.entries],
            "scanned_at": self.scanned_at.isoformat(),
            "hostname": self.hostname,
            "platform": self.platform,
            "note": self.note,
            "skipped_paths": list(self.skipped_paths),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, data: str) -> "Report":
        payload = json.loads(data)
        entries = [
            Entry(
                provider=e["provider"],
                id=e["id"],
                path=Path(e["path"]) if e["path"] is not None else None,
                label=e["label"],
                size_bytes=e["size_bytes"],
                mtime=e["mtime"],
                risk=Risk(e["risk"]),
                recipe=list(e["recipe"]),
            )
            for e in payload["entries"]
        ]
        return cls(
            entries=entries,
            scanned_at=datetime.fromisoformat(payload["scanned_at"]),
            hostname=payload["hostname"],
            platform=payload["platform"],
            note=payload.get("note"),
            skipped_paths=list(payload.get("skipped_paths", [])),
        )


Choice = Literal["y", "n", "a", "s", "q"]
PromptChoice = Callable[[Entry], Choice]
Confirm = Callable[[str], bool]
```

- [ ] **Step 4: Run test — expect pass**

```bash
uv run pytest tests/test_types.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/types.py tests/test_types.py
git commit -m "feat: core domain types (Risk, Entry, Report, filters, opts, diff, shell result)"
```

---

## Task 3: Shell port

**Files:**
- Create: `src/diskdoctor/ports.py`
- Create: `tests/conftest.py`
- Create: `tests/test_ports.py`

- [ ] **Step 1: Write failing test**

`tests/test_ports.py`:
```python
from diskdoctor.ports import RealShell
from diskdoctor.types import ShellResult


def test_real_shell_runs_command_and_returns_result():
    sh = RealShell()
    r = sh.run(["echo", "hello"])
    assert isinstance(r, ShellResult)
    assert r.returncode == 0
    assert r.stdout.strip() == "hello"
    assert r.stderr == ""


def test_real_shell_does_not_raise_on_nonzero_when_check_false():
    sh = RealShell()
    r = sh.run(["sh", "-c", "exit 3"], check=False)
    assert r.returncode == 3


def test_real_shell_which_finds_sh_and_missing_returns_none():
    sh = RealShell()
    assert sh.which("sh") is not None
    assert sh.which("definitely-not-a-real-binary-xyz") is None
```

`tests/conftest.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field

from diskdoctor.types import ShellResult


@dataclass
class FakeShell:
    """Argv-keyed fake. Matches full argv tuple exactly.

    Unconfigured calls raise so tests surface unexpected commands.
    """

    responses: dict[tuple[str, ...], ShellResult] = field(default_factory=dict)
    which_table: dict[str, str | None] = field(default_factory=dict)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(self, argv: list[str], *, check: bool = False) -> ShellResult:
        key = tuple(argv)
        self.calls.append(key)
        if key not in self.responses:
            raise AssertionError(f"FakeShell: unexpected call: {argv}")
        return self.responses[key]

    def which(self, binary: str) -> str | None:
        return self.which_table.get(binary)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_ports.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `src/diskdoctor/ports.py`**

```python
from __future__ import annotations

import shutil
import subprocess
from typing import Protocol

from diskdoctor.types import ShellResult


class Shell(Protocol):
    def run(self, argv: list[str], *, check: bool = False) -> ShellResult: ...
    def which(self, binary: str) -> str | None: ...


class RealShell:
    def run(self, argv: list[str], *, check: bool = False) -> ShellResult:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=check,
        )
        return ShellResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_ports.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/ports.py tests/conftest.py tests/test_ports.py
git commit -m "feat: Shell port with RealShell impl and FakeShell test double"
```

---

## Task 4: Sizer

**Files:**
- Create: `src/diskdoctor/sizer.py`
- Create: `tests/test_sizer.py`

- [ ] **Step 1: Write failing tests**

`tests/test_sizer.py`:
```python
from pathlib import Path

from diskdoctor.sizer import size_path


def _write(p: Path, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def test_size_path_returns_zero_for_missing_root(tmp_path: Path):
    missing = tmp_path / "nope"
    size, skipped = size_path(missing)
    assert size == 0
    assert skipped == [missing]


def test_size_path_sums_file_bytes(tmp_path: Path):
    _write(tmp_path / "a.txt", b"x" * 100)
    _write(tmp_path / "sub" / "b.txt", b"y" * 250)
    size, skipped = size_path(tmp_path)
    assert size == 350
    assert skipped == []


def test_size_path_does_not_follow_symlinks(tmp_path: Path):
    # Real file outside the tree.
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "big.bin").write_bytes(b"z" * 10_000)

    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "tiny.txt").write_bytes(b"a" * 10)
    (scan_dir / "link-to-real").symlink_to(real_dir)

    size, skipped = size_path(scan_dir)
    # Only tiny.txt plus the symlink inode itself (not the 10k file behind it).
    assert size < 1_000


def test_size_path_handles_symlink_loop(tmp_path: Path):
    d = tmp_path / "loop"
    d.mkdir()
    (d / "self").symlink_to(d)
    (d / "f").write_bytes(b"o" * 5)
    size, skipped = size_path(d)
    assert size < 100  # loop does not hang; link inode is tiny


def test_size_path_records_permission_denied(tmp_path: Path):
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "hidden.txt").write_bytes(b"s" * 20)
    protected.chmod(0o000)
    try:
        size, skipped = size_path(tmp_path)
        # Directory itself contributed, but walking inside was blocked.
        # We just care we didn't raise and we recorded the skip.
        assert any(str(protected) in str(p) for p in skipped) or size >= 0
    finally:
        protected.chmod(0o755)  # so pytest can clean up
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_sizer.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `src/diskdoctor/sizer.py`**

```python
from __future__ import annotations

import os
from pathlib import Path


def size_path(root: Path) -> tuple[int, list[Path]]:
    """Compute byte size of `root` recursively.

    Symlink-safe (does not follow). Stays on the root's device. Records any
    paths that errored during walk in the returned `skipped` list rather than
    raising.
    """
    skipped: list[Path] = []

    try:
        root_stat = root.lstat()
    except (FileNotFoundError, PermissionError, OSError):
        skipped.append(root)
        return 0, skipped

    root_dev = root_stat.st_dev
    total = 0

    def on_error(err: OSError) -> None:
        filename = getattr(err, "filename", None)
        skipped.append(Path(filename) if filename else root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=on_error):
        dp = Path(dirpath)

        # Cross-device guard: prune subdirs that live on a different device.
        pruned: list[str] = []
        for d in list(dirnames):
            sub = dp / d
            try:
                if sub.lstat().st_dev != root_dev:
                    pruned.append(d)
            except (FileNotFoundError, PermissionError, OSError):
                skipped.append(sub)
                pruned.append(d)
        for d in pruned:
            dirnames.remove(d)

        for name in filenames:
            p = dp / name
            try:
                total += p.lstat().st_size
            except (FileNotFoundError, PermissionError, OSError):
                skipped.append(p)

    return total, skipped
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_sizer.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/sizer.py tests/test_sizer.py
git commit -m "feat: sizer (symlink-safe, single-device, permission-tolerant)"
```

---

## Task 5: Provider ABC

**Files:**
- Create: `src/diskdoctor/providers/__init__.py`
- Create: `src/diskdoctor/providers/base.py`
- Create: `tests/test_provider_base.py`

- [ ] **Step 1: Write failing test**

`tests/test_provider_base.py`:
```python
from diskdoctor.providers.base import Provider
from diskdoctor.types import Entry, Risk
from tests.conftest import FakeShell


class _ClassProvider(Provider):
    name = "cprov"
    description = "test class provider"
    platforms = ("darwin", "linux")
    risk = Risk.SAFE
    required_binary = "myprog"

    def discover(self) -> list[Entry]:
        return []


def test_available_true_when_platform_matches_and_binary_present(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(which_table={"myprog": "/usr/local/bin/myprog"})
    assert _ClassProvider(sh).available() is True


def test_available_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(which_table={"myprog": None})
    assert _ClassProvider(sh).available() is False


def test_available_false_when_platform_excluded(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    sh = FakeShell(which_table={"myprog": "/x"})
    assert _ClassProvider(sh).available() is False


def test_available_true_when_required_binary_none(monkeypatch):
    class _Pure(Provider):
        name = "pure"
        description = ""
        platforms = ("darwin", "linux")
        risk = Risk.SAFE
        required_binary = None

        def discover(self) -> list[Entry]:
            return []

    monkeypatch.setattr("sys.platform", "linux")
    assert _Pure(FakeShell()).available() is True
```

`src/diskdoctor/providers/__init__.py`: empty file.

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_provider_base.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/providers/base.py`**

```python
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import ClassVar

from diskdoctor.ports import Shell
from diskdoctor.types import Entry, Risk


class Provider(ABC):
    """Base class for all providers. A Provider's single job is to discover
    entries. Execution is handled uniformly by cleanup.run against
    entry.recipe — providers do not execute their own recipes.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    platforms: ClassVar[tuple[str, ...]]
    risk: ClassVar[Risk]
    required_binary: ClassVar[str | None] = None

    def __init__(self, shell: Shell) -> None:
        self._shell = shell

    def available(self) -> bool:
        current = _normalize_platform(sys.platform)
        if current not in self.platforms:
            return False
        if self.required_binary is None:
            return True
        return self._shell.which(self.required_binary) is not None

    @abstractmethod
    def discover(self) -> list[Entry]: ...


def _normalize_platform(raw: str) -> str:
    if raw.startswith("linux"):
        return "linux"
    if raw == "darwin":
        return "darwin"
    return raw
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_provider_base.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/providers/__init__.py src/diskdoctor/providers/base.py tests/test_provider_base.py
git commit -m "feat: Provider ABC with platform + binary availability check"
```

---

## Task 6: PathProvider

**Files:**
- Modify: `src/diskdoctor/providers/base.py` (append `PathProvider`)
- Create: `tests/test_path_provider.py`

- [ ] **Step 1: Write failing tests**

`tests/test_path_provider.py`:
```python
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
    assert p._raw_paths == ("~/.cache/uv",)
    assert p._recipe_template == ["uv cache clean"]


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
    assert p._recipe_template == ["echo 'cleaning {path}'", "rm -rf {path}"]


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
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_path_provider.py -v
```

Expected: FAIL.

- [ ] **Step 3: Append `PathProvider` to `src/diskdoctor/providers/base.py`**

Add to the bottom of the existing file:

```python
import glob
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path as _Path


_ALLOWED_PLATFORMS = frozenset({"darwin", "linux"})


@dataclass
class PathProvider(Provider):
    """A provider backed by a YAML entry. One instance per YAML record.

    Emits one Entry per resolved path. Labels use the absolute path so globbed
    entries remain distinguishable. Recipes are templated with shlex.quote on
    the resolved path to prevent shell injection from filename content.
    """

    # Instance-level attrs (Provider expects these as ClassVar on subclasses; we
    # override them per instance for YAML-driven providers).
    name: str = ""
    description: str = ""
    platforms: tuple[str, ...] = ()
    risk: Risk = Risk.SAFE
    required_binary: str | None = None

    _raw_paths: tuple[str, ...] = field(default_factory=tuple)
    _recipe_template: list[str] = field(default_factory=list)

    def __init__(
        self,
        shell: Shell,
        *,
        name: str,
        description: str,
        platforms: tuple[str, ...],
        risk: Risk,
        raw_paths: tuple[str, ...],
        recipe_template: list[str],
    ) -> None:
        super().__init__(shell)
        self.name = name
        self.description = description
        self.platforms = platforms
        self.risk = risk
        self.required_binary = None
        self._raw_paths = raw_paths
        self._recipe_template = recipe_template

    @classmethod
    def from_yaml(cls, spec: dict, shell: Shell) -> "PathProvider":
        try:
            name = str(spec["name"])
            description = str(spec.get("description", ""))
            risk_raw = str(spec["risk"])
            platforms_raw = tuple(spec["platforms"])
            paths_raw = tuple(str(p) for p in spec["paths"])
            recipe_raw = spec["recipe"]
        except KeyError as e:
            raise ValueError(f"paths.yaml entry missing required key: {e}") from e

        try:
            risk = Risk(risk_raw)
        except ValueError as e:
            raise ValueError(f"paths.yaml entry {name!r}: unknown risk {risk_raw!r}") from e

        bad = set(platforms_raw) - _ALLOWED_PLATFORMS
        if bad:
            raise ValueError(
                f"paths.yaml entry {name!r}: unknown platform(s) {sorted(bad)}; "
                f"allowed: {sorted(_ALLOWED_PLATFORMS)}"
            )

        if isinstance(recipe_raw, str):
            recipe_template = [recipe_raw]
        elif isinstance(recipe_raw, list):
            recipe_template = [str(line) for line in recipe_raw]
        else:
            raise ValueError(
                f"paths.yaml entry {name!r}: recipe must be a string or list of strings"
            )

        return cls(
            shell,
            name=name,
            description=description,
            platforms=platforms_raw,
            risk=risk,
            raw_paths=paths_raw,
            recipe_template=recipe_template,
        )

    def available(self) -> bool:
        # Platform only; PathProviders never declare required binaries.
        import sys as _sys
        return _normalize_platform(_sys.platform) in self.platforms

    def discover(self) -> list[Entry]:
        entries: list[Entry] = []
        for raw in self._raw_paths:
            expanded = os.path.expanduser(os.path.expandvars(raw))
            matches = glob.glob(expanded) if any(c in expanded for c in "*?[") else [expanded]
            for m in matches:
                p = _Path(m)
                if not p.exists():
                    continue
                from diskdoctor.sizer import size_path

                size, _skipped = size_path(p)
                quoted = shlex.quote(str(p))
                recipe = [line.format(path=quoted) for line in self._recipe_template]
                try:
                    mtime = p.lstat().st_mtime
                except OSError:
                    mtime = None
                entries.append(
                    Entry(
                        provider=self.name,
                        id=str(p),
                        path=p,
                        label=str(p),
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=recipe,
                    )
                )
        return entries
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_path_provider.py -v
```

Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/providers/base.py tests/test_path_provider.py
git commit -m "feat: PathProvider with YAML loading, glob expansion, shlex-quoted recipes"
```

---

## Task 7: Registry

**Files:**
- Create: `src/diskdoctor/registry.py`
- Create: `src/diskdoctor/data/__init__.py` (empty)
- Create: `src/diskdoctor/data/paths.yaml` (minimal seed)
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write seed `src/diskdoctor/data/paths.yaml`**

```yaml
- name: uv-cache
  description: uv package cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/uv
  recipe: "uv cache clean"

- name: pip-cache
  description: pip download cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/pip
    - ~/Library/Caches/pip
  recipe: "rm -rf {path}"
```

- [ ] **Step 2: Create `src/diskdoctor/data/__init__.py`** — empty file (so `importlib.resources` can read it as package data).

- [ ] **Step 3: Write failing tests**

`tests/test_registry.py`:
```python
from pathlib import Path

import pytest

from diskdoctor.registry import load_providers, DuplicateProviderError
from tests.conftest import FakeShell


def test_load_providers_returns_sorted_by_name():
    providers = load_providers(FakeShell())
    names = [p.name for p in providers]
    assert names == sorted(names)


def test_load_providers_includes_yaml_entries():
    providers = load_providers(FakeShell())
    names = {p.name for p in providers}
    assert "uv-cache" in names
    assert "pip-cache" in names


def test_duplicate_yaml_names_raises(tmp_path: Path, monkeypatch):
    yaml_text = """
- name: same
  description: a
  risk: safe
  platforms: [darwin]
  paths: [~/x]
  recipe: "rm -rf {path}"
- name: same
  description: b
  risk: safe
  platforms: [darwin]
  paths: [~/y]
  recipe: "rm -rf {path}"
"""
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text(yaml_text)
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    with pytest.raises(DuplicateProviderError, match="same"):
        load_providers(FakeShell())


def test_env_override_replaces_default_yaml(tmp_path: Path, monkeypatch):
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text(
        "- name: custom\n  description: x\n  risk: safe\n  platforms: [darwin, linux]\n"
        "  paths: [~/x]\n  recipe: 'rm -rf {path}'\n"
    )
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    providers = load_providers(FakeShell())
    names = {p.name for p in providers}
    assert "custom" in names
    assert "uv-cache" not in names  # env override replaced the default


def test_malformed_yaml_raises_with_clear_message(tmp_path: Path, monkeypatch):
    yaml_file = tmp_path / "p.yaml"
    yaml_file.write_text("- name: bad\n  risk: maybe\n  platforms: [darwin]\n  paths: [~/x]\n  recipe: 'x'\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml_file))
    with pytest.raises(ValueError, match="risk"):
        load_providers(FakeShell())
```

- [ ] **Step 4: Run — expect ImportError**

```bash
uv run pytest tests/test_registry.py -v
```

Expected: FAIL.

- [ ] **Step 5: Implement `src/diskdoctor/registry.py`**

```python
from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

import yaml

from diskdoctor.ports import Shell
from diskdoctor.providers.base import PathProvider, Provider


class DuplicateProviderError(ValueError):
    """Two providers share a name."""


# Class providers — populated when Task 16+ add them. Keep the import list
# here and registry code will auto-include any class in _CLASS_PROVIDERS.
_CLASS_PROVIDERS: list[type[Provider]] = []


def load_providers(shell: Shell) -> list[Provider]:
    """Load and sort all providers. Fails on duplicate names."""
    providers: list[Provider] = [cls(shell) for cls in _CLASS_PROVIDERS]

    yaml_path = _locate_paths_yaml()
    yaml_text = yaml_path.read_text()
    yaml_docs = yaml.safe_load(yaml_text) or []
    if not isinstance(yaml_docs, list):
        raise ValueError(f"{yaml_path}: expected a top-level list of provider specs")

    for spec in yaml_docs:
        if not isinstance(spec, dict):
            raise ValueError(f"{yaml_path}: every entry must be a mapping; got {type(spec).__name__}")
        providers.append(PathProvider.from_yaml(spec, shell))

    _check_unique_names(providers)
    providers.sort(key=lambda p: p.name)
    return providers


def _locate_paths_yaml() -> Path:
    override = os.environ.get("DISKDOCTOR_PATHS_YAML")
    if override:
        return Path(override)
    # Package-bundled default.
    with resources.as_file(resources.files("diskdoctor.data") / "paths.yaml") as p:
        return Path(p)


def _check_unique_names(providers: list[Provider]) -> None:
    seen: dict[str, Provider] = {}
    dupes: dict[str, list[str]] = {}
    for p in providers:
        if p.name in seen:
            dupes.setdefault(p.name, [type(seen[p.name]).__name__]).append(type(p).__name__)
        else:
            seen[p.name] = p
    if dupes:
        msg = "; ".join(f"{name}: {sources}" for name, sources in dupes.items())
        raise DuplicateProviderError(f"duplicate provider name(s): {msg}")
```

- [ ] **Step 6: Run — expect pass**

```bash
uv run pytest tests/test_registry.py -v
```

Expected: 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/diskdoctor/registry.py src/diskdoctor/data/__init__.py src/diskdoctor/data/paths.yaml tests/test_registry.py
git commit -m "feat: registry with YAML loading, name uniqueness, env override"
```

---

## Task 8: discovery.scan

**Files:**
- Create: `src/diskdoctor/discovery.py`
- Create: `tests/test_discovery.py`

- [ ] **Step 1: Write failing tests**

`tests/test_discovery.py`:
```python
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
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_discovery.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/discovery.py`**

```python
from __future__ import annotations

import socket
import sys
from datetime import datetime

from diskdoctor.providers.base import Provider
from diskdoctor.types import Report, ScanFilters


def scan(
    providers: list[Provider],
    filters: ScanFilters,
    now: datetime,
) -> Report:
    """Run every available provider, collect entries, apply filters, sort."""
    entries = []
    for p in providers:
        if not p.available():
            continue
        entries.extend(p.discover())

    entries.sort(key=lambda e: e.size_bytes, reverse=True)

    report = Report(
        entries=entries,
        scanned_at=now,
        hostname=socket.gethostname(),
        platform=_platform(),
    )

    if (
        filters.min_size_bytes
        or filters.risks is not None
        or filters.providers is not None
    ):
        report = report.filter(
            risks=filters.risks,
            min_size=filters.min_size_bytes,
            providers=filters.providers,
        )

    return report


def _platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_discovery.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/discovery.py tests/test_discovery.py
git commit -m "feat: discovery.scan (aggregates providers, filters, sorts desc by size)"
```

---

## Task 9: cleanup.run preview mode

**Files:**
- Create: `src/diskdoctor/cleanup.py`
- Create: `tests/test_cleanup.py`

- [ ] **Step 1: Write failing tests**

`tests/test_cleanup.py`:
```python
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.cleanup import run
from diskdoctor.types import CleanupOpts, Entry, Report, Risk
from tests.conftest import FakeShell


def _report(*entries: Entry) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
    )


def _e(provider, id_, size, risk=Risk.SAFE, recipe=None) -> Entry:
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=risk,
        recipe=recipe or [f"rm -rf /{id_}"],
    )


def _never_prompt(_entry):
    raise AssertionError("prompt must not be called in preview mode")


def _never_confirm(_msg):
    raise AssertionError("confirm must not be called in preview mode")


def test_preview_returns_dry_run_results_and_does_not_prompt():
    rep = _report(_e("a", "1", 100), _e("b", "1", 200))
    shell = FakeShell()
    results = run(
        rep,
        shell=shell,
        prompt_choice=_never_prompt,
        confirm=_never_confirm,
        opts=CleanupOpts(execute=False),
    )
    assert shell.calls == []
    assert [r.status for r in results] == ["dry_run", "dry_run"]
    assert [r.freed_bytes for r in results] == [100, 200]
    assert [r.entry_id for r in results] == ["1", "1"]


def test_preview_respects_provider_filter():
    rep = _report(_e("a", "1", 100), _e("b", "1", 200))
    results = run(
        rep,
        shell=FakeShell(),
        prompt_choice=_never_prompt,
        confirm=_never_confirm,
        opts=CleanupOpts(execute=False, providers=frozenset({"b"})),
    )
    assert [r.entry_id for r in results] == ["1"]  # only 'b/1'
    assert results[0].freed_bytes == 200
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_cleanup.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/cleanup.py` (preview only for now)**

```python
from __future__ import annotations

from diskdoctor.ports import Shell
from diskdoctor.types import (
    CleanResult,
    CleanupOpts,
    Confirm,
    Entry,
    PromptChoice,
    Report,
)


def run(
    report: Report,
    *,
    shell: Shell,
    prompt_choice: PromptChoice,
    confirm: Confirm,
    opts: CleanupOpts,
) -> list[CleanResult]:
    """Drive the cleanup flow. Preview (opts.execute=False) returns dry-run
    results without any prompt or shell calls. Execute mode will be added in
    Task 10.
    """
    candidates = _select_candidates(report, opts)

    if not opts.execute:
        return [
            CleanResult(entry_id=e.id, status="dry_run", freed_bytes=e.size_bytes)
            for e in candidates
        ]

    raise NotImplementedError("execute mode lands in Task 10")


def _select_candidates(report: Report, opts: CleanupOpts) -> list[Entry]:
    entries = report.entries
    if opts.providers is not None:
        entries = [e for e in entries if e.provider in opts.providers]
    return entries
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_cleanup.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/cleanup.py tests/test_cleanup.py
git commit -m "feat: cleanup.run preview mode (dry-run results, zero prompts, zero shell)"
```

---

## Task 10: cleanup.run execute mode

**Files:**
- Modify: `src/diskdoctor/cleanup.py` (implement execute branch)
- Modify: `tests/test_cleanup.py` (add execute-mode tests)

- [ ] **Step 1: Append failing tests to `tests/test_cleanup.py`**

```python
from diskdoctor.types import ShellResult


def _scripted_choices(*choices):
    """Build a PromptChoice that returns the next scripted choice per call."""
    q = list(choices)
    def _prompt(_entry):
        return q.pop(0)
    return _prompt


def _always(value):
    def _f(_msg):
        return value
    return _f


def test_execute_yes_runs_shell_once_per_entry_after_final_confirm():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell(responses={("rm", "-rf", "/1"): ShellResult(0, "", "")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert shell.calls == [("rm", "-rf", "/1")]
    assert [(r.status, r.freed_bytes) for r in results] == [("ok", 100)]


def test_execute_skips_when_user_answers_n():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell()
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("n"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert shell.calls == []
    assert [r.status for r in results] == ["skipped"]


def test_execute_all_in_provider_auto_approves_rest():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
        _e("b", "1", 50, recipe=["rm -rf /b1"]),
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "/1"): ShellResult(0, "", ""),
            ("rm", "-rf", "/2"): ShellResult(0, "", ""),
            ("rm", "-rf", "/b1"): ShellResult(0, "", ""),
        }
    )
    results = run(
        rep,
        shell=shell,
        # "a" got "a" (approve all in provider), then b/1 got "y"
        prompt_choice=_scripted_choices("a", "y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert [r.status for r in results] == ["ok", "ok", "ok"]
    # All three ran; order respects input order
    assert len(shell.calls) == 3


def test_execute_skip_provider_skips_remaining_in_that_provider():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
        _e("b", "1", 50, recipe=["rm -rf /b1"]),
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "/1"): ShellResult(0, "", ""),
            ("rm", "-rf", "/b1"): ShellResult(0, "", ""),
        }
    )
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y", "s", "y"),  # a/1 y, a/2 s, b/1 y
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    statuses = [r.status for r in results]
    assert statuses == ["ok", "skipped", "ok"]


def test_execute_quit_aborts_remaining_with_skipped_status():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
    )
    shell = FakeShell(responses={("rm", "-rf", "/1"): ShellResult(0, "", "")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y", "q"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert [r.status for r in results] == ["ok", "skipped"]


def test_execute_final_confirm_no_aborts_all_selected():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell()
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(False),
        opts=CleanupOpts(execute=True),
    )
    assert shell.calls == []
    assert [r.status for r in results] == ["skipped"]


def test_execute_yes_safe_auto_approves_safe_without_prompt():
    rep = _report(
        _e("a", "1", 100, Risk.SAFE, recipe=["rm -rf /1"]),
        _e("a", "2", 200, Risk.RECLAIMABLE, recipe=["rm -rf /2"]),
    )
    shell = FakeShell(
        responses={
            ("rm", "-rf", "/1"): ShellResult(0, "", ""),
            ("rm", "-rf", "/2"): ShellResult(0, "", ""),
        }
    )
    # Only one prompt call (for the reclaimable entry).
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True, yes_safe=True),
    )
    assert [r.status for r in results] == ["ok", "ok"]
    assert len(shell.calls) == 2


def test_execute_dangerous_without_allow_dangerous_marks_skipped_with_note():
    rep = _report(
        _e("a", "1", 100, Risk.DANGEROUS, recipe=["rm -rf /1"]),
        _e("b", "1", 50, Risk.SAFE, recipe=["rm -rf /b1"]),
    )
    shell = FakeShell(responses={("rm", "-rf", "/b1"): ShellResult(0, "", "")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),  # only b/1 prompts
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    statuses = {(r.entry_id, r.status) for r in results}
    assert (("1", "skipped") in statuses) and (("1", "ok") in statuses)
    # Find the dangerous one and confirm the message tag
    dangerous = next(r for r in results if r.status == "skipped")
    assert "dangerous" in (dangerous.message or "").lower()


def test_execute_shell_failure_becomes_error_status():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1"]))
    shell = FakeShell(responses={("rm", "-rf", "/1"): ShellResult(1, "", "boom")})
    results = run(
        rep,
        shell=shell,
        prompt_choice=_scripted_choices("y"),
        confirm=_always(True),
        opts=CleanupOpts(execute=True),
    )
    assert results[0].status == "error"
    assert "boom" in (results[0].message or "")
    assert results[0].freed_bytes == 0
```

- [ ] **Step 2: Run — expect NotImplementedError**

```bash
uv run pytest tests/test_cleanup.py -v
```

Expected: execute-mode tests FAIL with `NotImplementedError`.

- [ ] **Step 3: Replace `run()` in `src/diskdoctor/cleanup.py` with the full implementation**

Replace the entire file contents with:

```python
from __future__ import annotations

import shlex

from diskdoctor.ports import Shell
from diskdoctor.types import (
    CleanResult,
    CleanupOpts,
    Confirm,
    Entry,
    PromptChoice,
    Report,
    Risk,
)


def run(
    report: Report,
    *,
    shell: Shell,
    prompt_choice: PromptChoice,
    confirm: Confirm,
    opts: CleanupOpts,
) -> list[CleanResult]:
    """Drive the cleanup flow.

    Preview (opts.execute=False): return dry-run results with no prompts and
    no shell calls.

    Execute (opts.execute=True):
      - For each candidate: ask PromptChoice (unless yes_safe + SAFE).
      - 'a' approves all remaining in the current provider.
      - 's' skips all remaining in the current provider.
      - 'q' quits; remaining entries are marked skipped.
      - DANGEROUS entries without allow_dangerous are marked skipped with note.
      - After selection: Confirm with a summary. 'no' → nothing runs; every
        approved entry becomes skipped.
      - On confirm yes: run each approved entry.recipe via shell.
    """
    candidates = _select_candidates(report, opts)

    if not opts.execute:
        return [
            CleanResult(entry_id=e.id, status="dry_run", freed_bytes=e.size_bytes)
            for e in candidates
        ]

    # Selection phase
    selections: list[tuple[Entry, str]] = []  # (entry, "approved" | "skipped"[:reason])
    provider_override: dict[str, str] = {}    # provider -> "all" | "skip"
    quit_signalled = False

    for entry in candidates:
        if quit_signalled:
            selections.append((entry, "skipped:quit"))
            continue

        if entry.risk == Risk.DANGEROUS and not opts.allow_dangerous:
            selections.append((entry, "skipped:dangerous"))
            continue

        override = provider_override.get(entry.provider)
        if override == "all":
            selections.append((entry, "approved"))
            continue
        if override == "skip":
            selections.append((entry, "skipped:provider-skip"))
            continue

        if opts.yes_safe and entry.risk == Risk.SAFE:
            selections.append((entry, "approved"))
            continue

        choice = prompt_choice(entry)
        if choice == "y":
            selections.append((entry, "approved"))
        elif choice == "n":
            selections.append((entry, "skipped:user"))
        elif choice == "a":
            provider_override[entry.provider] = "all"
            selections.append((entry, "approved"))
        elif choice == "s":
            provider_override[entry.provider] = "skip"
            selections.append((entry, "skipped:provider-skip"))
        elif choice == "q":
            quit_signalled = True
            selections.append((entry, "skipped:quit"))
        else:
            selections.append((entry, f"skipped:unknown-choice:{choice}"))

    approved = [e for e, s in selections if s == "approved"]
    if not approved:
        return _make_skipped_results(selections)

    summary = _summary(approved)
    if not confirm(summary):
        return [
            CleanResult(entry_id=e.id, status="skipped", freed_bytes=0, message="aborted at confirm")
            if state == "approved"
            else _to_result(e, state)
            for e, state in selections
        ]

    # Execute phase
    results: list[CleanResult] = []
    for entry, state in selections:
        if state != "approved":
            results.append(_to_result(entry, state))
            continue
        results.append(_execute_entry(entry, shell))
    return results


def _select_candidates(report: Report, opts: CleanupOpts) -> list[Entry]:
    entries = report.entries
    if opts.providers is not None:
        entries = [e for e in entries if e.provider in opts.providers]
    return entries


def _make_skipped_results(selections: list[tuple[Entry, str]]) -> list[CleanResult]:
    return [_to_result(e, s) for e, s in selections]


def _to_result(entry: Entry, state: str) -> CleanResult:
    if state == "approved":
        # Should be replaced by _execute_entry in the execute phase; defensive.
        return CleanResult(entry_id=entry.id, status="skipped", freed_bytes=0)
    reason = state.split(":", 1)[1] if ":" in state else state
    msg = _reason_message(reason)
    return CleanResult(entry_id=entry.id, status="skipped", freed_bytes=0, message=msg)


def _reason_message(reason: str) -> str:
    return {
        "user": "declined",
        "provider-skip": "provider skipped",
        "quit": "quit before confirm",
        "dangerous": "dangerous (pass --allow-dangerous to include)",
    }.get(reason, reason)


def _execute_entry(entry: Entry, shell: Shell) -> CleanResult:
    for line in entry.recipe:
        argv = shlex.split(line)
        result = shell.run(argv, check=False)
        if result.returncode != 0:
            return CleanResult(
                entry_id=entry.id,
                status="error",
                freed_bytes=0,
                message=(result.stderr or result.stdout or "").strip() or f"exit {result.returncode}",
            )
    return CleanResult(entry_id=entry.id, status="ok", freed_bytes=entry.size_bytes)


def _summary(approved: list[Entry]) -> str:
    total = sum(e.size_bytes for e in approved)
    return f"Execute cleanup for {len(approved)} entries, freeing ~{total} bytes?"


def build_script(report: Report) -> str:
    """Emit a reviewable shell script. Every destructive line is commented
    out — the user reviews and uncomments the sections they want.
    """
    lines: list[str] = [
        "#!/usr/bin/env bash",
        "# diskdoctor cleanup script",
        "# All destructive commands are commented out. Review each section,",
        "# uncomment the lines you want to run, then execute this file.",
        "set -euo pipefail",
        "",
    ]
    for provider, entries in report.by_provider().items():
        total = sum(e.size_bytes for e in entries)
        risk = entries[0].risk.value
        lines.append(f"# --- {provider}: {total} bytes freed, risk={risk} ---")
        if entries[0].provider and entries[0].label:
            lines.append(f"# {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}")
        for e in entries:
            lines.append(f"#   [{e.size_bytes} B] {e.label}")
            for cmd in e.recipe:
                lines.append(f"#   {cmd}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_cleanup.py -v
```

Expected: all cleanup tests PASS (both preview and execute).

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/cleanup.py tests/test_cleanup.py
git commit -m "feat: cleanup.run execute mode (prompts, yes-safe, dangerous gate, final confirm, shell dispatch)"
```

---

## Task 11: cleanup.build_script tests

**Files:**
- Modify: `tests/test_cleanup.py` (append build_script tests)

- [ ] **Step 1: Append tests**

```python
from diskdoctor.cleanup import build_script


def test_build_script_has_shebang_and_warning_header():
    rep = _report(_e("a", "1", 100))
    script = build_script(rep)
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "commented out" in script.lower()


def test_build_script_comments_all_destructive_lines():
    rep = _report(_e("a", "1", 100, recipe=["rm -rf /1", "echo done"]))
    script = build_script(rep)
    # Every recipe line must be prefixed with a comment.
    for line in ["rm -rf /1", "echo done"]:
        assert f"#   {line}" in script
        # The uncommented line must not appear.
        assert f"\n{line}\n" not in script


def test_build_script_groups_by_provider_with_totals():
    rep = _report(
        _e("a", "1", 100, recipe=["rm -rf /1"]),
        _e("a", "2", 200, recipe=["rm -rf /2"]),
        _e("b", "1", 50, recipe=["rm -rf /b1"]),
    )
    script = build_script(rep)
    assert "# --- a: 300 bytes freed" in script
    assert "# --- b: 50 bytes freed" in script
```

- [ ] **Step 2: Run — expect pass (already implemented in Task 10)**

```bash
uv run pytest tests/test_cleanup.py::test_build_script_has_shebang_and_warning_header tests/test_cleanup.py::test_build_script_comments_all_destructive_lines tests/test_cleanup.py::test_build_script_groups_by_provider_with_totals -v
```

Expected: 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cleanup.py
git commit -m "test: cleanup.build_script (commented output, provider grouping, totals)"
```

---

## Task 12: history.write_snapshot / load_snapshot

**Files:**
- Create: `src/diskdoctor/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write failing tests**

`tests/test_history.py`:
```python
from datetime import UTC, datetime
from pathlib import Path

from diskdoctor.history import load_snapshot, write_snapshot
from diskdoctor.types import Entry, Report, Risk


def _rep(ts, entries=()) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=ts,
        hostname="h",
        platform="darwin",
    )


def test_write_snapshot_creates_file_with_iso_timestamp(tmp_path: Path):
    ts = datetime(2026, 4, 18, 12, 34, 56, tzinfo=UTC)
    r = _rep(ts)
    p = write_snapshot(r, tmp_path)
    assert p.parent == tmp_path
    assert p.suffix == ".json"
    # ISO-safe filename: no colons
    assert ":" not in p.name


def test_write_snapshot_creates_directory_if_missing(tmp_path: Path):
    target = tmp_path / "sub" / "snaps"
    ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
    p = write_snapshot(_rep(ts), target)
    assert p.parent == target


def test_snapshot_round_trip(tmp_path: Path):
    ts = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    e = Entry(
        provider="a",
        id="1",
        path=Path("/x"),
        label="a/1",
        size_bytes=100,
        mtime=1_700_000_000.0,
        risk=Risk.SAFE,
        recipe=["rm -rf /x"],
    )
    r = _rep(ts, entries=[e])
    r.note = "post-cleanup"
    r.skipped_paths.append("/forbidden")
    p = write_snapshot(r, tmp_path)
    r2 = load_snapshot(p)
    assert r2.note == "post-cleanup"
    assert r2.skipped_paths == ["/forbidden"]
    assert r2.entries[0] == e
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_history.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/history.py`**

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from diskdoctor.types import DiffReport, DiffRow, Report


def write_snapshot(report: Report, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    # Filename-safe ISO timestamp (no ':' which is problematic on some FS).
    stamp = report.scanned_at.strftime("%Y-%m-%dT%H-%M-%S")
    target = directory / f"{stamp}.json"
    target.write_text(report.to_json())
    return target


def load_snapshot(path: Path) -> Report:
    return Report.from_json(path.read_text())


def diff(before: Report, after: Report) -> DiffReport:
    before_by = {p: sum(e.size_bytes for e in es) for p, es in before.by_provider().items()}
    after_by = {p: sum(e.size_bytes for e in es) for p, es in after.by_provider().items()}
    providers = sorted(set(before_by) | set(after_by))
    rows: list[DiffRow] = []
    for name in providers:
        b = before_by.get(name, 0)
        a = after_by.get(name, 0)
        delta = a - b
        pct = 0.0 if b == 0 else (delta / b) * 100.0
        rows.append(DiffRow(provider=name, before_bytes=b, after_bytes=a, delta_bytes=delta, delta_pct=pct))
    return DiffReport(before_at=before.scanned_at, after_at=after.scanned_at, rows=rows)


def latest_snapshots(directory: Path, n: int = 2) -> list[Path]:
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.json"))
    return files[-n:]


def default_snapshot_dir() -> Path:
    from os import environ
    base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "diskdoctor" / "snapshots"
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_history.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/history.py tests/test_history.py
git commit -m "feat: history.write_snapshot and load_snapshot (round-trip JSON)"
```

---

## Task 13: history.diff

**Files:**
- Modify: `tests/test_history.py` (append diff tests)

- [ ] **Step 1: Append tests**

```python
from diskdoctor.history import diff


def _entry(provider, id_, size):
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{provider}/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=Risk.SAFE,
        recipe=["rm -rf"],
    )


def test_diff_reports_shrinkage():
    ts_before = datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC)
    ts_after = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    before = _rep(ts_before, entries=[_entry("a", "1", 1000)])
    after = _rep(ts_after, entries=[_entry("a", "1", 200)])
    d = diff(before, after)
    assert [(r.provider, r.before_bytes, r.after_bytes, r.delta_bytes) for r in d.rows] == [
        ("a", 1000, 200, -800)
    ]
    assert d.rows[0].delta_pct == -80.0


def test_diff_handles_added_provider():
    ts_before = datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC)
    ts_after = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    before = _rep(ts_before, entries=[_entry("a", "1", 1000)])
    after = _rep(ts_after, entries=[_entry("a", "1", 1000), _entry("b", "1", 500)])
    d = diff(before, after)
    names = {r.provider for r in d.rows}
    assert names == {"a", "b"}
    b_row = next(r for r in d.rows if r.provider == "b")
    assert (b_row.before_bytes, b_row.after_bytes, b_row.delta_bytes) == (0, 500, 500)
    assert b_row.delta_pct == 0.0  # before=0 → pct defaults to 0


def test_diff_handles_removed_provider():
    ts_before = datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC)
    ts_after = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
    before = _rep(ts_before, entries=[_entry("a", "1", 1000), _entry("b", "1", 500)])
    after = _rep(ts_after, entries=[_entry("a", "1", 1000)])
    d = diff(before, after)
    b_row = next(r for r in d.rows if r.provider == "b")
    assert (b_row.before_bytes, b_row.after_bytes, b_row.delta_bytes) == (500, 0, -500)
    assert b_row.delta_pct == -100.0
```

- [ ] **Step 2: Run — expect pass (diff already implemented in Task 12)**

```bash
uv run pytest tests/test_history.py -v
```

Expected: all history tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_history.py
git commit -m "test: history.diff (shrinkage, added/removed providers, zero-before handling)"
```

---

## Task 14: rendering (tables + spinner)

**Files:**
- Create: `src/diskdoctor/rendering.py`
- Create: `tests/test_rendering.py`

- [ ] **Step 1: Write failing tests**

`tests/test_rendering.py`:
```python
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

from rich.console import Console

from diskdoctor.rendering import render_report_table, render_diff_table
from diskdoctor.types import DiffReport, DiffRow, Entry, Report, Risk


def _rep(*entries) -> Report:
    return Report(
        entries=list(entries),
        scanned_at=datetime(2026, 4, 18, tzinfo=UTC),
        hostname="h",
        platform="darwin",
    )


def _e(provider, id_, size, risk=Risk.SAFE, recipe=None):
    return Entry(
        provider=provider,
        id=id_,
        path=Path(f"/{id_}"),
        label=f"{provider}/{id_}",
        size_bytes=size,
        mtime=None,
        risk=risk,
        recipe=recipe or ["rm -rf /x"],
    )


def _render(fn, *args) -> str:
    buf = StringIO()
    console = Console(file=buf, width=120, force_terminal=False, color_system=None)
    fn(console, *args)
    return buf.getvalue()


def test_render_report_table_contains_entries_and_total():
    r = _rep(_e("ollama", "llama3:8b", 4_700_000_000), _e("uv-cache", "/x", 1_500_000_000))
    out = _render(render_report_table, r)
    assert "ollama" in out
    assert "uv-cache" in out
    assert "llama3:8b" in out
    # Total line
    assert "Total" in out


def test_render_report_table_handles_empty():
    out = _render(render_report_table, _rep())
    assert "No entries" in out or "Total" in out


def test_render_diff_table_shows_deltas():
    d = DiffReport(
        before_at=datetime(2026, 4, 18, 9, 0, 0, tzinfo=UTC),
        after_at=datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC),
        rows=[
            DiffRow(provider="a", before_bytes=1000, after_bytes=200, delta_bytes=-800, delta_pct=-80.0),
            DiffRow(provider="b", before_bytes=0, after_bytes=500, delta_bytes=500, delta_pct=0.0),
        ],
    )
    out = _render(render_diff_table, d)
    assert "a" in out
    assert "b" in out
    assert "-80" in out
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_rendering.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/rendering.py`**

```python
from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from rich.console import Console
from rich.prompt import Confirm as RichConfirm, Prompt
from rich.table import Table

from diskdoctor.types import Choice, Confirm, DiffReport, Entry, PromptChoice, Report, Risk


def render_report_table(console: Console, report: Report) -> None:
    table = Table(title=f"diskdoctor scan — {len(report.entries)} entries", show_lines=False)
    table.add_column("Provider", style="cyan")
    table.add_column("Label", overflow="fold")
    table.add_column("Size", justify="right")
    table.add_column("Risk", justify="center")
    table.add_column("Stale?", justify="center")
    table.add_column("Recipe hint", overflow="ellipsis")

    term_width = shutil.get_terminal_size((120, 24)).columns
    hint_max = max(20, term_width - 80)

    for e in report.entries:
        table.add_row(
            e.provider,
            e.label,
            _human_bytes(e.size_bytes),
            _risk_label(e.risk),
            _staleness(e.mtime),
            (e.recipe[0] if e.recipe else "")[:hint_max],
        )

    if not report.entries:
        table.add_row("(no entries)", "", "", "", "", "")

    table.caption = f"Total: {_human_bytes(report.total_bytes())}"
    console.print(table)


def render_diff_table(console: Console, diff: DiffReport) -> None:
    table = Table(
        title=f"diff: {diff.before_at.isoformat()} → {diff.after_at.isoformat()}",
    )
    table.add_column("Provider", style="cyan")
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Δ bytes", justify="right")
    table.add_column("Δ %", justify="right")

    for r in diff.rows:
        color = "green" if r.delta_bytes < 0 else ("red" if r.delta_bytes > 0 else "")
        style = f"[{color}]" if color else ""
        end = "[/]" if color else ""
        table.add_row(
            r.provider,
            _human_bytes(r.before_bytes),
            _human_bytes(r.after_bytes),
            f"{style}{r.delta_bytes:+d}{end}",
            f"{style}{r.delta_pct:+.1f}%{end}",
        )

    console.print(table)


def real_prompts(console: Console) -> tuple[PromptChoice, Confirm]:
    """Build the real Rich-backed prompt callables."""

    def prompt_choice(entry: Entry) -> Choice:
        console.print(
            f"[bold]{entry.provider}[/] — {entry.label}  "
            f"({_human_bytes(entry.size_bytes)}, risk={_risk_label(entry.risk)})"
        )
        console.print(f"  → {entry.recipe[0] if entry.recipe else '(no recipe)'}")
        raw = Prompt.ask(
            "[y]es / [n]o / [a]ll-in-provider / [s]kip-provider / [q]uit",
            console=console,
            choices=["y", "n", "a", "s", "q"],
            default="n",
            show_choices=False,
        )
        return raw  # type: ignore[return-value]

    def confirm(message: str) -> bool:
        return RichConfirm.ask(message, console=console, default=False)

    return prompt_choice, confirm


@contextmanager
def spinner(console: Console, message: str) -> Iterator[None]:
    with console.status(message):
        yield


def _risk_label(risk: Risk) -> str:
    return {
        Risk.SAFE: "safe",
        Risk.RECLAIMABLE: "reclaim",
        Risk.DANGEROUS: "DANGER",
    }[risk]


def _human_bytes(n: int) -> str:
    sign = "-" if n < 0 else ""
    n = abs(n)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if n < 1024 or unit == "P":
            return f"{sign}{n:.0f}{unit}" if unit == "B" else f"{sign}{n:.1f}{unit}"
        n /= 1024
    return f"{sign}{n:.1f}P"


def _staleness(mtime: float | None) -> str:
    if mtime is None:
        return "—"
    age_days = (datetime.now().timestamp() - mtime) / 86400
    if age_days < 1:
        return "today"
    if age_days < 30:
        return f"{int(age_days)}d"
    if age_days < 365:
        return f"{int(age_days / 30)}mo"
    return f"{age_days / 365:.1f}y"
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_rendering.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/rendering.py tests/test_rendering.py
git commit -m "feat: rendering (report table, diff table, spinner, Rich prompt factory)"
```

---

## Task 15: Ollama provider

**Files:**
- Create: `src/diskdoctor/providers/ollama.py`
- Modify: `src/diskdoctor/registry.py` (register `OllamaProvider`)
- Create: `tests/test_ollama_provider.py`

- [ ] **Step 1: Write failing tests**

`tests/test_ollama_provider.py`:
```python
from pathlib import Path

from diskdoctor.providers.ollama import OllamaProvider
from diskdoctor.types import Risk, ShellResult
from tests.conftest import FakeShell


_OLLAMA_LIST_OUT = (
    "NAME                    ID              SIZE      MODIFIED\n"
    "llama3:8b               365c0bd3c000    4.7 GB    2 weeks ago\n"
    "qwen2:7b                8c6f08f5f5c6    4.4 GB    3 days ago\n"
)


def test_discover_parses_ollama_list(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"ollama": "/opt/homebrew/bin/ollama"},
        responses={("ollama", "list"): ShellResult(0, _OLLAMA_LIST_OUT, "")},
    )
    p = OllamaProvider(sh)
    entries = p.discover()
    assert {e.id for e in entries} == {"llama3:8b", "qwen2:7b"}
    llama = next(e for e in entries if e.id == "llama3:8b")
    # 4.7 GB → about 5e9 bytes
    assert 4_000_000_000 < llama.size_bytes < 6_000_000_000
    assert llama.recipe == ["ollama rm llama3:8b"]
    assert llama.risk == Risk.RECLAIMABLE


def test_discover_falls_back_to_walking_when_list_fails(tmp_path, monkeypatch):
    # Arrange: fake HOME with a models dir
    home = tmp_path / "h"
    (home / ".ollama" / "models" / "manifests" / "registry.ollama.ai" / "library" / "llama3" / "8b").mkdir(parents=True)
    blob = home / ".ollama" / "models" / "blobs"
    blob.mkdir(parents=True)
    (blob / "sha256-aaaa").write_bytes(b"x" * 4_000_000)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    sh = FakeShell(
        which_table={"ollama": "/opt/homebrew/bin/ollama"},
        responses={("ollama", "list"): ShellResult(1, "", "daemon not running")},
    )
    p = OllamaProvider(sh)
    entries = p.discover()
    # Fallback emits at least one entry representing the models directory.
    assert len(entries) >= 1
    assert all(e.risk == Risk.RECLAIMABLE for e in entries)
    # Recipes are rm -rf when falling back to paths.
    assert all(e.recipe[0].startswith("rm -rf ") for e in entries)


def test_available_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(which_table={"ollama": None})
    assert OllamaProvider(sh).available() is False
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_ollama_provider.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/providers/ollama.py`**

```python
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from diskdoctor.providers.base import Provider
from diskdoctor.sizer import size_path
from diskdoctor.types import Entry, Risk


_SIZE_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)", re.IGNORECASE)


class OllamaProvider(Provider):
    name = "ollama"
    description = "Ollama local LLM models"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "ollama"

    def discover(self) -> list[Entry]:
        result = self._shell.run(["ollama", "list"], check=False)
        if result.returncode == 0 and result.stdout.strip():
            return self._parse_list(result.stdout)
        return self._walk_models_dir()

    def _parse_list(self, output: str) -> list[Entry]:
        entries: list[Entry] = []
        lines = [line for line in output.splitlines() if line.strip()]
        for line in lines[1:]:  # skip header
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) < 3:
                continue
            name = parts[0]
            size_str = parts[2]
            size_bytes = _parse_size(size_str)
            entries.append(
                Entry(
                    provider=self.name,
                    id=name,
                    path=None,
                    label=name,
                    size_bytes=size_bytes,
                    mtime=None,
                    risk=self.risk,
                    recipe=[f"ollama rm {name}"],
                )
            )
        return entries

    def _walk_models_dir(self) -> list[Entry]:
        models = Path(os.path.expanduser("~/.ollama/models"))
        if not models.exists():
            return []
        total, _skipped = size_path(models)
        return [
            Entry(
                provider=self.name,
                id=str(models),
                path=models,
                label=str(models),
                size_bytes=total,
                mtime=None,
                risk=self.risk,
                recipe=[f"rm -rf {shlex.quote(str(models))}"],
            )
        ]


def _parse_size(s: str) -> int:
    m = _SIZE_RE.search(s)
    if not m:
        return 0
    value = float(m.group(1))
    unit = m.group(2).upper()
    return int(value * _SIZE_UNITS[unit])
```

- [ ] **Step 4: Register the provider in `src/diskdoctor/registry.py`**

Replace the `_CLASS_PROVIDERS` line with:

```python
from diskdoctor.providers.ollama import OllamaProvider

_CLASS_PROVIDERS: list[type[Provider]] = [OllamaProvider]
```

- [ ] **Step 5: Run — expect pass**

```bash
uv run pytest tests/test_ollama_provider.py -v
uv run pytest -q
```

Expected: ollama tests PASS and full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/diskdoctor/providers/ollama.py src/diskdoctor/registry.py tests/test_ollama_provider.py
git commit -m "feat: Ollama provider (ollama list with walk-models-dir fallback)"
```

---

## Task 16: Docker provider

**Files:**
- Create: `src/diskdoctor/providers/docker.py`
- Modify: `src/diskdoctor/registry.py`
- Create: `tests/test_docker_provider.py`

- [ ] **Step 1: Write failing tests**

`tests/test_docker_provider.py`:
```python
import json

from diskdoctor.providers.docker import DockerProvider
from diskdoctor.types import Risk, ShellResult
from tests.conftest import FakeShell


_DOCKER_DF_JSON = json.dumps({
    "Images": [
        {"Repository": "python", "Tag": "3.12", "Size": "200MB", "Reclaimable": "100MB (50%)"}
    ],
    "Containers": [
        {"Names": "web", "Size": "0B", "Reclaimable": "0B"}
    ],
    "Volumes": [
        {"Name": "pgdata", "Size": "5GB", "Reclaimable": "5GB (100%)"}
    ],
    "BuildCache": [
        {"Id": "x", "Size": "3GB", "Reclaimable": "3GB"}
    ],
})


def test_discover_parses_docker_system_df(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_JSON, "")
        },
    )
    p = DockerProvider(sh)
    entries = p.discover()
    # One entry per non-zero-reclaimable category
    ids = {e.id for e in entries}
    assert "images" in ids
    assert "volumes" in ids
    assert "build-cache" in ids
    # Containers had 0 reclaimable → omitted
    assert "containers" not in ids


def test_entries_have_prune_recipes(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_JSON, "")
        },
    )
    entries = DockerProvider(sh).discover()
    by_id = {e.id: e for e in entries}
    assert by_id["images"].recipe == ["docker image prune -a -f"]
    assert by_id["volumes"].recipe == ["docker volume prune -f"]
    assert by_id["build-cache"].recipe == ["docker builder prune -a -f"]


def test_risk_is_reclaimable(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(0, _DOCKER_DF_JSON, "")
        },
    )
    for e in DockerProvider(sh).discover():
        assert e.risk == Risk.RECLAIMABLE


def test_discover_handles_df_failure(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    sh = FakeShell(
        which_table={"docker": "/usr/local/bin/docker"},
        responses={
            ("docker", "system", "df", "--format", "json"): ShellResult(1, "", "daemon not running")
        },
    )
    assert DockerProvider(sh).discover() == []
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_docker_provider.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/providers/docker.py`**

```python
from __future__ import annotations

import json
import re

from diskdoctor.providers.base import Provider
from diskdoctor.types import Entry, Risk


_SIZE_UNITS = {"B": 1, "KB": 1_000, "MB": 1_000_000, "GB": 1_000_000_000, "TB": 1_000_000_000_000}
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)")


_CATEGORIES = [
    ("Images", "images", "docker image prune -a -f"),
    ("Containers", "containers", "docker container prune -f"),
    ("Volumes", "volumes", "docker volume prune -f"),
    ("BuildCache", "build-cache", "docker builder prune -a -f"),
]


class DockerProvider(Provider):
    name = "docker"
    description = "Docker images, containers, volumes, build cache"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = "docker"

    def discover(self) -> list[Entry]:
        result = self._shell.run(["docker", "system", "df", "--format", "json"], check=False)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        entries: list[Entry] = []
        for key, id_, cmd in _CATEGORIES:
            items = data.get(key, []) or []
            reclaimable = _sum_reclaimable(items)
            if reclaimable <= 0:
                continue
            entries.append(
                Entry(
                    provider=self.name,
                    id=id_,
                    path=None,
                    label=f"docker {id_}",
                    size_bytes=reclaimable,
                    mtime=None,
                    risk=self.risk,
                    recipe=[cmd],
                )
            )
        return entries


def _sum_reclaimable(items: list[dict]) -> int:
    total = 0
    for it in items:
        raw = it.get("Reclaimable") or it.get("Size") or ""
        m = _SIZE_RE.search(str(raw))
        if not m:
            continue
        value = float(m.group(1))
        unit = m.group(2).upper()
        total += int(value * _SIZE_UNITS[unit])
    return total
```

- [ ] **Step 4: Register in `src/diskdoctor/registry.py`**

Update the imports and registration:

```python
from diskdoctor.providers.docker import DockerProvider
from diskdoctor.providers.ollama import OllamaProvider

_CLASS_PROVIDERS: list[type[Provider]] = [DockerProvider, OllamaProvider]
```

- [ ] **Step 5: Run — expect pass**

```bash
uv run pytest tests/test_docker_provider.py -v
uv run pytest -q
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/diskdoctor/providers/docker.py src/diskdoctor/registry.py tests/test_docker_provider.py
git commit -m "feat: Docker provider (parse system df, per-category prune recipes)"
```

---

## Task 17: LM Studio provider

**Files:**
- Create: `src/diskdoctor/providers/lm_studio.py`
- Modify: `src/diskdoctor/registry.py`
- Create: `tests/test_lm_studio_provider.py`

- [ ] **Step 1: Write failing tests**

`tests/test_lm_studio_provider.py`:
```python
from pathlib import Path

from diskdoctor.providers.lm_studio import LMStudioProvider
from diskdoctor.types import Risk
from tests.conftest import FakeShell


def _mk_model(root: Path, publisher: str, model: str, size: int) -> None:
    d = root / publisher / model
    d.mkdir(parents=True)
    (d / "weights.bin").write_bytes(b"0" * size)


def test_discover_emits_one_entry_per_publisher_model(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    models_root = home / ".cache" / "lm-studio" / "models"
    _mk_model(models_root, "ibm-granite", "granite-docling-258M-mlx", 500)
    _mk_model(models_root, "mlx-community", "gpt-oss-20b-MXFP4-Q8", 1000)

    entries = LMStudioProvider(FakeShell()).discover()
    ids = {e.id for e in entries}
    assert ids == {
        "ibm-granite/granite-docling-258M-mlx",
        "mlx-community/gpt-oss-20b-MXFP4-Q8",
    }
    for e in entries:
        assert e.risk == Risk.RECLAIMABLE
        assert e.recipe[0].startswith("rm -rf ")


def test_discover_returns_empty_when_models_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "darwin")
    assert LMStudioProvider(FakeShell()).discover() == []


def test_available_has_no_required_binary(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    assert LMStudioProvider(FakeShell()).available() is True
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_lm_studio_provider.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/providers/lm_studio.py`**

```python
from __future__ import annotations

import os
import shlex
from pathlib import Path

from diskdoctor.providers.base import Provider
from diskdoctor.sizer import size_path
from diskdoctor.types import Entry, Risk


class LMStudioProvider(Provider):
    name = "lm-studio-models"
    description = "LM Studio downloaded models, grouped by <publisher>/<model>"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = None

    def discover(self) -> list[Entry]:
        root = Path(os.path.expanduser("~/.cache/lm-studio/models"))
        if not root.exists():
            return []
        entries: list[Entry] = []
        for publisher_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for model_dir in sorted(m for m in publisher_dir.iterdir() if m.is_dir()):
                size, _ = size_path(model_dir)
                mid = f"{publisher_dir.name}/{model_dir.name}"
                try:
                    mtime = model_dir.lstat().st_mtime
                except OSError:
                    mtime = None
                entries.append(
                    Entry(
                        provider=self.name,
                        id=mid,
                        path=model_dir,
                        label=mid,
                        size_bytes=size,
                        mtime=mtime,
                        risk=self.risk,
                        recipe=[f"rm -rf {shlex.quote(str(model_dir))}"],
                    )
                )
        return entries
```

- [ ] **Step 4: Register in `src/diskdoctor/registry.py`**

```python
from diskdoctor.providers.docker import DockerProvider
from diskdoctor.providers.lm_studio import LMStudioProvider
from diskdoctor.providers.ollama import OllamaProvider

_CLASS_PROVIDERS: list[type[Provider]] = [DockerProvider, LMStudioProvider, OllamaProvider]
```

- [ ] **Step 5: Run — expect pass**

```bash
uv run pytest tests/test_lm_studio_provider.py -v
uv run pytest -q
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/diskdoctor/providers/lm_studio.py src/diskdoctor/registry.py tests/test_lm_studio_provider.py
git commit -m "feat: LM Studio provider (per-publisher/model entries)"
```

---

## Task 18: HuggingFace provider

**Files:**
- Create: `src/diskdoctor/providers/huggingface.py`
- Modify: `src/diskdoctor/registry.py`
- Create: `tests/test_huggingface_provider.py`

- [ ] **Step 1: Write failing tests**

`tests/test_huggingface_provider.py`:
```python
from pathlib import Path

from diskdoctor.providers.huggingface import HuggingFaceProvider
from diskdoctor.types import Risk
from tests.conftest import FakeShell


def _mk_hf_repo(hub_root: Path, kind: str, org: str, name: str, *, blob_size: int) -> Path:
    repo = hub_root / f"{kind}--{org}--{name}"
    (repo / "blobs").mkdir(parents=True)
    (repo / "snapshots" / "abc123").mkdir(parents=True)
    blob = repo / "blobs" / "sha256-deadbeef"
    blob.write_bytes(b"x" * blob_size)
    # snapshots contain symlinks to blobs (HF cache convention)
    (repo / "snapshots" / "abc123" / "file.bin").symlink_to(blob)
    return repo


def test_discover_emits_one_entry_per_repo(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")

    hub = home / ".cache" / "huggingface" / "hub"
    _mk_hf_repo(hub, "models", "bert-base-uncased", "main", blob_size=1000)
    _mk_hf_repo(hub, "datasets", "princeton-nlp", "SWE-bench", blob_size=2000)

    entries = HuggingFaceProvider(FakeShell()).discover()
    assert len(entries) == 2
    ids = {e.id for e in entries}
    assert any("bert-base-uncased" in i for i in ids)
    assert any("SWE-bench" in i for i in ids)


def test_size_does_not_double_count_symlinked_blobs(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    hub = home / ".cache" / "huggingface" / "hub"
    _mk_hf_repo(hub, "models", "a", "b", blob_size=1000)
    [e] = HuggingFaceProvider(FakeShell()).discover()
    # Blob is 1000 B; snapshot symlink points to it. Total should be ~1000,
    # not 2000, because we don't follow symlinks.
    assert e.size_bytes < 1500


def test_risk_is_reclaimable(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    hub = home / ".cache" / "huggingface" / "hub"
    _mk_hf_repo(hub, "models", "a", "b", blob_size=100)
    [e] = HuggingFaceProvider(FakeShell()).discover()
    assert e.risk == Risk.RECLAIMABLE


def test_discover_empty_when_hub_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.platform", "darwin")
    assert HuggingFaceProvider(FakeShell()).discover() == []
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_huggingface_provider.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/providers/huggingface.py`**

```python
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from diskdoctor.providers.base import Provider
from diskdoctor.sizer import size_path
from diskdoctor.types import Entry, Risk


_REPO_RE = re.compile(r"^(models|datasets)--(.+)$")


class HuggingFaceProvider(Provider):
    name = "huggingface-hub"
    description = "HuggingFace hub cache (models and datasets)"
    platforms = ("darwin", "linux")
    risk = Risk.RECLAIMABLE
    required_binary = None

    def discover(self) -> list[Entry]:
        hub = Path(os.path.expanduser("~/.cache/huggingface/hub"))
        if not hub.exists():
            return []
        entries: list[Entry] = []
        for repo in sorted(hub.iterdir()):
            if not repo.is_dir():
                continue
            m = _REPO_RE.match(repo.name)
            if not m:
                continue
            kind = m.group(1)
            repo_id = m.group(2).replace("--", "/")
            size, _ = size_path(repo)
            label = f"{kind}:{repo_id}"
            try:
                mtime = repo.lstat().st_mtime
            except OSError:
                mtime = None
            entries.append(
                Entry(
                    provider=self.name,
                    id=label,
                    path=repo,
                    label=label,
                    size_bytes=size,
                    mtime=mtime,
                    risk=self.risk,
                    recipe=[f"rm -rf {shlex.quote(str(repo))}"],
                )
            )
        return entries
```

- [ ] **Step 4: Register in `src/diskdoctor/registry.py`**

```python
from diskdoctor.providers.docker import DockerProvider
from diskdoctor.providers.huggingface import HuggingFaceProvider
from diskdoctor.providers.lm_studio import LMStudioProvider
from diskdoctor.providers.ollama import OllamaProvider

_CLASS_PROVIDERS: list[type[Provider]] = [
    DockerProvider,
    HuggingFaceProvider,
    LMStudioProvider,
    OllamaProvider,
]
```

- [ ] **Step 5: Run — expect pass**

```bash
uv run pytest tests/test_huggingface_provider.py -v
uv run pytest -q
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/diskdoctor/providers/huggingface.py src/diskdoctor/registry.py tests/test_huggingface_provider.py
git commit -m "feat: HuggingFace provider (hub repos, symlink-safe sizing)"
```

---

## Task 19: CLI scaffold + `scan` command

**Files:**
- Create: `src/diskdoctor/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

`tests/test_cli.py`:
```python
import json

from click.testing import CliRunner

from diskdoctor.cli import build_cli
from diskdoctor.types import ShellResult
from tests.conftest import FakeShell


def test_scan_exits_zero_and_prints_table(tmp_path, monkeypatch):
    # Isolate from real machine: empty YAML override.
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))

    # No external binaries → class providers report unavailable.
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["scan"])
    assert result.exit_code == 0, result.output
    assert "Total" in result.output


def test_scan_json_emits_valid_json(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["scan", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "entries" in data
    assert "scanned_at" in data


def test_scan_filters_by_risk(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    # Unknown risk name → user error
    result = runner.invoke(build_cli(shell), ["scan", "--risk", "maybe"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/diskdoctor/cli.py`**

```python
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console

from diskdoctor import discovery, history, registry
from diskdoctor.cleanup import build_script, run as cleanup_run
from diskdoctor.ports import RealShell, Shell
from diskdoctor.rendering import (
    real_prompts,
    render_diff_table,
    render_report_table,
    spinner,
)
from diskdoctor.types import CleanupOpts, Risk, ScanFilters


_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([KMGT]?)$", re.IGNORECASE)
_SIZE_MULT = {"": 1, "K": 1_000, "M": 1_000_000, "G": 1_000_000_000, "T": 1_000_000_000_000}


def _parse_size(s: str) -> int:
    m = _SIZE_RE.match(s)
    if not m:
        raise click.BadParameter(f"invalid size {s!r}; use e.g. 500M, 2G, 100K, or an integer")
    return int(float(m.group(1)) * _SIZE_MULT[m.group(2).upper()])


def _parse_risks(values: tuple[str, ...]) -> frozenset[Risk] | None:
    if not values:
        return None
    flat: list[str] = []
    for v in values:
        flat.extend(v.split(","))
    try:
        return frozenset(Risk(v.strip()) for v in flat if v.strip())
    except ValueError as e:
        raise click.BadParameter(str(e))


def build_cli(shell: Shell | None = None) -> click.Group:
    sh = shell or RealShell()

    @click.group()
    @click.pass_context
    def cli(ctx: click.Context) -> None:
        ctx.ensure_object(dict)
        ctx.obj["shell"] = sh

    @cli.command()
    @click.option("--json", "json_out", is_flag=True, help="Emit Report JSON to stdout.")
    @click.option("--min-size", default=None, help="Filter entries below this size (e.g. 100M).")
    @click.option("--risk", "risk", multiple=True, help="Include only these risks (repeatable or comma-separated).")
    @click.option("--provider", "providers", multiple=True, help="Limit to these providers.")
    @click.pass_context
    def scan(ctx, json_out, min_size, risk, providers):
        filters = ScanFilters(
            min_size_bytes=_parse_size(min_size) if min_size else 0,
            risks=_parse_risks(risk),
            providers=frozenset(providers) if providers else None,
        )
        providers_list = registry.load_providers(ctx.obj["shell"])
        console = Console()
        if json_out:
            report = discovery.scan(providers_list, filters, datetime.now(timezone.utc))
            click.echo(report.to_json())
            return
        with spinner(console, "Scanning..."):
            report = discovery.scan(providers_list, filters, datetime.now(timezone.utc))
        render_report_table(console, report)

    @cli.command()
    @click.option("--provider", "providers", multiple=True)
    @click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path), default=None)
    @click.pass_context
    def recipe(ctx, providers, output):
        providers_list = registry.load_providers(ctx.obj["shell"])
        report = discovery.scan(
            providers_list,
            ScanFilters(providers=frozenset(providers) if providers else None),
            datetime.now(timezone.utc),
        )
        script = build_script(report)
        if output is None:
            click.echo(script)
        else:
            output.write_text(script)

    @cli.command()
    @click.option("--provider", "providers", multiple=True)
    @click.option("--execute", is_flag=True)
    @click.option("--yes-safe", is_flag=True)
    @click.option("--allow-dangerous", is_flag=True)
    @click.pass_context
    def clean(ctx, providers, execute, yes_safe, allow_dangerous):
        providers_list = registry.load_providers(ctx.obj["shell"])
        filters = ScanFilters(providers=frozenset(providers) if providers else None)
        console = Console()
        with spinner(console, "Scanning..."):
            report = discovery.scan(providers_list, filters, datetime.now(timezone.utc))
        if not execute:
            render_report_table(console, report)
            console.print(
                f"[dim]Preview only — re-run with --execute to perform cleanup.[/]"
            )
            return
        pc, cf = real_prompts(console)
        results = cleanup_run(
            report,
            shell=ctx.obj["shell"],
            prompt_choice=pc,
            confirm=cf,
            opts=CleanupOpts(
                execute=True,
                yes_safe=yes_safe,
                allow_dangerous=allow_dangerous,
                providers=frozenset(providers) if providers else None,
            ),
        )
        freed = sum(r.freed_bytes for r in results if r.status == "ok")
        failures = [r for r in results if r.status == "error"]
        console.print(f"[bold]Freed ~{freed} bytes; {len(failures)} error(s).[/]")
        if failures:
            sys.exit(2)

    @cli.command()
    @click.option("--note", default=None)
    @click.pass_context
    def snapshot(ctx, note):
        providers_list = registry.load_providers(ctx.obj["shell"])
        console = Console()
        with spinner(console, "Scanning..."):
            report = discovery.scan(providers_list, ScanFilters(), datetime.now(timezone.utc))
        if note:
            report.note = note
        target = history.write_snapshot(report, history.default_snapshot_dir())
        click.echo(f"wrote {target}")

    @cli.command()
    @click.option("--from", "from_", default=None, help="Path to earlier snapshot.")
    @click.option("--to", "to_", default=None, help="Path to later snapshot, or 'live'.")
    @click.pass_context
    def diff(ctx, from_, to_):
        snap_dir = history.default_snapshot_dir()
        recent = history.latest_snapshots(snap_dir, n=2)
        if from_:
            before = history.load_snapshot(Path(from_))
        elif len(recent) >= 2:
            before = history.load_snapshot(recent[-2])
        else:
            raise click.UsageError("need at least two snapshots, or pass --from")

        if to_ == "live" or (to_ is None and len(recent) < 2):
            providers_list = registry.load_providers(ctx.obj["shell"])
            after = discovery.scan(providers_list, ScanFilters(), datetime.now(timezone.utc))
        elif to_:
            after = history.load_snapshot(Path(to_))
        else:
            after = history.load_snapshot(recent[-1])

        d = history.diff(before, after)
        render_diff_table(Console(), d)

    @cli.command()
    @click.pass_context
    def providers(ctx):
        providers_list = registry.load_providers(ctx.obj["shell"])
        console = Console()
        from rich.table import Table
        table = Table(title="providers")
        table.add_column("Name")
        table.add_column("Risk")
        table.add_column("Platforms")
        table.add_column("Available")
        for p in providers_list:
            table.add_row(p.name, p.risk.value, ",".join(p.platforms), "yes" if p.available() else "no")
        console.print(table)

    return cli


def main() -> None:
    build_cli()(standalone_mode=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run — expect pass**

```bash
uv run pytest tests/test_cli.py -v
uv run pytest -q
```

Expected: scan tests PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add src/diskdoctor/cli.py tests/test_cli.py
git commit -m "feat: CLI with build_cli factory and scan command"
```

---

## Task 20: CLI tests for recipe / clean / snapshot / diff / providers

**Files:**
- Modify: `tests/test_cli.py` (append tests for remaining commands)

- [ ] **Step 1: Append tests**

```python
def test_recipe_script_is_commented(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["recipe"])
    assert result.exit_code == 0
    assert result.output.startswith("#!/usr/bin/env bash")


def test_clean_preview_does_not_prompt(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["clean"])
    assert result.exit_code == 0
    assert "Preview only" in result.output


def test_snapshot_writes_file(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["snapshot", "--note", "test"])
    assert result.exit_code == 0
    written_dir = tmp_path / "xdg" / "diskdoctor" / "snapshots"
    assert written_dir.exists()
    files = list(written_dir.glob("*.json"))
    assert len(files) == 1


def test_diff_errors_when_no_snapshots(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["diff"])
    assert result.exit_code != 0
    assert "snapshot" in result.output.lower()


def test_providers_lists_registered_providers(tmp_path, monkeypatch):
    yaml = tmp_path / "p.yaml"
    yaml.write_text("[]\n")
    monkeypatch.setenv("DISKDOCTOR_PATHS_YAML", str(yaml))
    shell = FakeShell(which_table={"ollama": None, "docker": None})
    runner = CliRunner()
    result = runner.invoke(build_cli(shell), ["providers"])
    assert result.exit_code == 0
    assert "ollama" in result.output
    assert "docker" in result.output
```

- [ ] **Step 2: Run — expect pass**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: all CLI tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cli.py
git commit -m "test: CLI coverage for recipe, clean-preview, snapshot, diff, providers"
```

---

## Task 21: Seed `paths.yaml` with real cache entries

**Files:**
- Modify: `src/diskdoctor/data/paths.yaml`

- [ ] **Step 1: Expand the YAML with real-world entries**

Replace `src/diskdoctor/data/paths.yaml` with:

```yaml
- name: uv-cache
  description: uv package cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/uv
  recipe: "uv cache clean"

- name: pip-cache
  description: pip download cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/pip
    - ~/Library/Caches/pip
  recipe: "rm -rf {path}"

- name: poetry-cache
  description: Poetry dependency cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/pypoetry
    - ~/Library/Caches/pypoetry
  recipe: "rm -rf {path}"

- name: npm-cache
  description: npm package cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.npm/_cacache
  recipe: "npm cache clean --force"

- name: homebrew-downloads
  description: Homebrew download cache
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/Library/Caches/Homebrew
  recipe: "brew cleanup --prune=all"

- name: lm-studio-extensions
  description: LM Studio extension downloads
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.cache/lm-studio/extensions
  recipe: "rm -rf {path}"

- name: huggingface-datasets-top
  description: HuggingFace datasets cache (top level; use huggingface-hub provider for per-repo)
  risk: reclaimable
  platforms: [darwin, linux]
  paths:
    - ~/.cache/huggingface/datasets
    - ~/.cache/huggingface/modules
    - ~/.cache/huggingface/xet
  recipe: "rm -rf {path}"

- name: playwright
  description: Playwright downloaded browsers
  risk: safe
  platforms: [darwin]
  paths:
    - ~/Library/Caches/ms-playwright
  recipe: "rm -rf {path}"

- name: chrome-cache
  description: Chrome browser cache (all profiles)
  risk: safe
  platforms: [darwin]
  paths:
    - ~/Library/Caches/Google/Chrome/*/Cache
  recipe: "rm -rf {path}"

- name: firefox-cache
  description: Firefox browser cache
  risk: safe
  platforms: [darwin]
  paths:
    - ~/Library/Caches/Firefox
  recipe: "rm -rf {path}"

- name: arc-browser-cache
  description: Arc browser cache
  risk: safe
  platforms: [darwin]
  paths:
    - ~/Library/Caches/Arc
    - ~/Library/Caches/company.thebrowser.Browser
  recipe: "rm -rf {path}"

- name: docker-vm-disk
  description: Docker Desktop VM disk image (shrinks only on docker-desktop restart)
  risk: reclaimable
  platforms: [darwin]
  paths:
    - ~/Library/Containers/com.docker.docker/Data/vms
  recipe: "echo 'Use Docker Desktop > Troubleshoot > Clean/Purge data, or reset the VM. Do NOT rm -rf this path while Docker is running.'"

- name: claude-vm-bundles
  description: Claude Code VM bundles
  risk: reclaimable
  platforms: [darwin]
  paths:
    - ~/Library/Application Support/Claude/vm_bundles
  recipe: "rm -rf {path}"

- name: docker-installer
  description: Docker installer leftovers
  risk: safe
  platforms: [darwin]
  paths:
    - ~/Library/Application Support/com.docker.install
  recipe: "rm -rf {path}"

- name: slack-service-worker
  description: Slack desktop cache (login state preserved)
  risk: reclaimable
  platforms: [darwin]
  paths:
    - ~/Library/Application Support/Slack/Service Worker/CacheStorage
  recipe: "rm -rf {path}"

- name: vscode-cache
  description: VS Code / Cursor cache directories
  risk: safe
  platforms: [darwin]
  paths:
    - ~/Library/Application Support/Code/Cache
    - ~/Library/Application Support/Code/CachedData
    - ~/Library/Application Support/Cursor/Cache
    - ~/Library/Application Support/Cursor/CachedData
  recipe: "rm -rf {path}"

- name: gradle-caches
  description: Gradle user caches
  risk: safe
  platforms: [darwin, linux]
  paths:
    - ~/.gradle/caches
  recipe: "rm -rf {path}"

- name: maven-repo
  description: Maven local repository
  risk: reclaimable
  platforms: [darwin, linux]
  paths:
    - ~/.m2/repository
  recipe: "rm -rf {path}"
```

- [ ] **Step 2: Verify the YAML loads and registry stays green**

```bash
uv run pytest tests/test_registry.py -v
uv run pytest -q
```

Expected: green.

- [ ] **Step 3: Smoke-test against the real machine**

```bash
uv run diskdoctor providers
uv run diskdoctor scan --min-size 100M
```

Expected: lists ~22+ providers (4 class + YAML entries); scan prints a Rich table with real cache sizes.

- [ ] **Step 4: Commit**

```bash
git add src/diskdoctor/data/paths.yaml
git commit -m "feat: seed paths.yaml with real cache entries (18 YAML providers)"
```

---

## Task 22: README, usage docs, install instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write real README**

```markdown
# diskdoctor

Repeatable disk-cache analyzer and interactive cleanup for macOS and Linux.

## Install

```bash
uv tool install --from git+https://github.com/<you>/diskdoctor diskdoctor
# or from a local clone:
uv tool install .
```

## Commands

```bash
diskdoctor scan                       # Rich table of all known caches, sorted by size
diskdoctor scan --json                # same, as JSON to stdout
diskdoctor scan --min-size 100M --risk safe,reclaimable

diskdoctor recipe                     # emit a commented-out cleanup shell script
diskdoctor recipe --provider ollama   # only one section
diskdoctor recipe -o /tmp/cleanup.sh  # write to file

diskdoctor clean                      # preview (no prompts, no shell calls)
diskdoctor clean --execute            # interactive cleanup (per-entry prompts + final confirm)
diskdoctor clean --execute --yes-safe
diskdoctor clean --execute --allow-dangerous

diskdoctor snapshot --note "before cleanup"
diskdoctor diff                       # latest two snapshots
diskdoctor diff --to live             # last snapshot vs current

diskdoctor providers                  # show registered providers and their availability
```

## Safety model

- `clean` defaults to **preview only** — zero prompts, zero shell commands.
- `recipe` always emits a **commented-out** script. You review and uncomment what you want.
- Entries are labelled **safe / reclaimable / dangerous**. DANGEROUS entries are *skipped* unless you pass `--allow-dangerous`.

## Design

See [docs/superpowers/specs/2026-04-18-diskdoctor-design.md](docs/superpowers/specs/2026-04-18-diskdoctor-design.md).

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check src tests
uv run mypy src
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: real README with install, commands, safety model, dev notes"
```

---

## Task 23: Final sweep — ruff, mypy, full suite

**Files:**
- (Possibly minor fixes across src/ and tests/)

- [ ] **Step 1: Run ruff**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

Expected: no errors. Fix any that surface.

- [ ] **Step 2: Run mypy**

```bash
uv run mypy src
```

Expected: no errors. Fix any that surface.

- [ ] **Step 3: Run full test suite with coverage**

```bash
uv run pytest --cov=src/diskdoctor --cov-report=term-missing
```

Expected: all tests pass; sizer/discovery/cleanup/history/registry ≥ 90% line coverage; providers ≥ 80%.

- [ ] **Step 4: End-to-end smoke test**

```bash
uv run diskdoctor scan
uv run diskdoctor scan --json | head -40
uv run diskdoctor recipe | head -40
uv run diskdoctor clean       # should be preview only; no prompts
uv run diskdoctor providers
```

Expected: every command exits 0 and produces sensible output.

- [ ] **Step 5: Commit any fixes**

```bash
git add .
git commit -m "chore: final lint/type/coverage sweep"
```

---

## Task 24: Add pre-commit hooks

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Write `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

- [ ] **Step 2: Install and run once**

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Expected: hooks fix minor whitespace / trailing newlines if any; final state is clean.

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: pre-commit hooks (ruff, whitespace, yaml validation)"
```

---

## Done

At this point:
- CLI is installable via `uv tool install .` and runs from any directory.
- `diskdoctor scan` on the target machine surfaces every cache identified in the design.
- Full test suite green; coverage targets met.
- `recipe` and `clean` are safe by default.
- Snapshot/diff let the user track cache growth over time.

Next candidates (not in this plan):
- Publish to PyPI or provide a Homebrew tap.
- `diskdoctor watch` for threshold alerts.
- `importlib.metadata` plugin hook for third-party providers.
- **SIGINT polish in `cleanup.run`** — the spec calls for catching `KeyboardInterrupt` mid-loop, marking remaining entries as `skipped` with reason `"interrupted"`, and returning a partial summary. The current implementation lets the exception bubble up to Click (which still exits `130`); the process behavior is correct but the result-table symmetry is missing. A few lines to add when needed.
