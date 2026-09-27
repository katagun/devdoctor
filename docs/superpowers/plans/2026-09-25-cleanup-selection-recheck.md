# Re-check Only the Selection: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A web cleanup's pre-job re-scan measures only the selected entries, while still finding every candidate fresh from disk.

**Architecture:**
- `Provider` gains `discover_selected(ids)`. Its default runs `discover()` and filters, which is correct everywhere.
- The heavy providers split into *find candidates* (cheap, unchanged) and *build entries* (sizing, git classification), and filter by id in between. `discover()` and `discover_selected()` share that code, so the entries are identical by construction.
- `discovery.scan(..., selection=)` gives each provider its share of the namespaced ids and skips providers with none.
- Only `routes_clean._scan_selection` passes a selection.

**Tech Stack:** Python 3.12, pytest, real git for the worktree tests (`git_fixture`).

**Spec:** `docs/superpowers/specs/2026-09-25-cleanup-selection-recheck-design.md`

## Global Constraints

- `discover_selected(ids)` must equal `[e for e in discover() if e.id in ids]` for the disk as it is: that equality is the contract every task tests.
- Candidates are found fresh on every call. Nothing is cached between scans.
- Only `POST /api/clean/jobs` passes a selection. Display scans, CLI `scan` and CLI `clean` are untouched.
- Provider-local ids: path providers `str(path)`; project artifacts `str(artifact)`; venvs `str(real)`; Xcode `str(path)` or `simulator:{udid}`; worktrees `str(record.path)`.
- Checks: `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`, `.venv/bin/mypy`, `.venv/bin/python -m pytest -q -p no:cacheprovider`. Tests live under `tests/`, whose autouse fixture pins HOME, XDG and `DEVDOCTOR_PROJECT_ROOTS` into `tmp_path`.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The pre-commit hook may reformat and abort; re-add and commit again.

---

### Task 1: The contract and the scan's selection

**Files:**
- Modify: `src/devdoctor/providers/base.py` (class `Provider`, after `discover`)
- Modify: `src/devdoctor/discovery.py` (`_discover_one`, `scan`)
- Test: `tests/test_discovery.py`

**Interfaces:**
- Produces:
  - `Provider.discover_selected(self, ids: frozenset[str]) -> list[Entry]`
  - `discovery.scan(..., selection: frozenset[str] | None = None)`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_discovery.py`)

```python
class _Selective(_Stub):
    """A stub that records what the scan asked it for."""

    def __init__(self, shell, name, entries):
        super().__init__(shell, name, entries)
        self.discover_calls = 0
        self.selected: list[frozenset[str]] = []

    def discover(self) -> list[Entry]:
        self.discover_calls += 1
        return super().discover()

    def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
        self.selected.append(ids)
        return [e for e in self._entries if e.id in ids]


def test_a_selection_asks_each_provider_only_for_its_own_ids():
    a = _Selective(FakeShell(), "a", [_e("a", "1", 10), _e("a", "2", 20), _e("a", "3", 30)])
    b = _Selective(FakeShell(), "b", [_e("b", "1", 10)])
    report = discovery.scan(
        [a, b],
        ScanFilters(),
        datetime.now(UTC),
        contain=False,
        selection=frozenset({"a:1", "a:3", "b:1"}),
    )
    assert a.selected == [frozenset({"1", "3"})]
    assert b.selected == [frozenset({"1"})]
    assert a.discover_calls == b.discover_calls == 0
    assert sorted(e.id for e in report.entries) == ["a:1", "a:3", "b:1"]


def test_a_provider_with_nothing_selected_is_not_run():
    a = _Selective(FakeShell(), "a", [_e("a", "1", 10)])
    idle = _Selective(FakeShell(), "idle", [_e("idle", "1", 10)])
    discovery.scan(
        [a, idle], ScanFilters(), datetime.now(UTC), contain=False, selection=frozenset({"a:1"})
    )
    assert idle.selected == []
    assert idle.discover_calls == 0


def test_the_default_discover_selected_is_discover_narrowed_to_the_ids():
    stub = _Stub(FakeShell(), "s", [_e("s", "x", 1), _e("s", "y", 2), _e("s", "z", 3)])
    assert [e.id for e in stub.discover_selected(frozenset({"x", "z", "nope"}))] == ["x", "z"]


def test_an_empty_selection_never_discovers():
    class _Exploding(_Stub):
        def discover(self) -> list[Entry]:
            raise AssertionError("an empty selection must not run discover()")

    assert _Exploding(FakeShell(), "s", []).discover_selected(frozenset()) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_discovery.py -q -p no:cacheprovider -k "selection or selected or nothing_selected"`
Expected: FAIL: `scan()` gets an unexpected keyword argument `selection`, and `_Stub` has no `discover_selected`.

- [ ] **Step 3: Implement**

In `src/devdoctor/providers/base.py`, class `Provider`, directly after the abstract `discover`:

```python
    def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
        """The entries ``discover()`` would report now whose (provider-local) id is in ``ids``.

        A web cleanup re-checks only what it will act on. This default is correct for
        every provider and no faster; a provider that finds its candidates cheaply
        overrides it and measures only the selected ones.
        """
        if not ids:
            return []
        return [entry for entry in self.discover() if entry.id in ids]
```

In `src/devdoctor/discovery.py`:

1. Give `_discover_one` a keyword-only `selection` and use it for the call inside `try:`:

```python
def _discover_one(
    p: Provider,
    on_progress: ScanProgressCallback | None = None,
    *,
    selection: frozenset[str] | None = None,
) -> _ProviderResult:
```

```python
        found = p.discover() if selection is None else p.discover_selected(selection)
        provider_entries = [e for e in found if e.display_bytes > 0 or e.is_unmeasured]
```

2. Add a helper next to `_notify`:

```python
def _share(selection: frozenset[str], provider: str) -> frozenset[str]:
    """The provider-local ids among the namespaced ``"{provider}:{id}"`` ones."""
    prefix = f"{provider}:"
    return frozenset(eid[len(prefix) :] for eid in selection if eid.startswith(prefix))
```

3. `scan` gains `selection: frozenset[str] | None = None` after `on_progress`. Document it in the docstring:

```
    ``selection`` holds the namespaced ids a web cleanup selected: each provider
    builds only its share of them (``discover_selected``), and a provider with
    none is not run.
```

Then replace the lines from `wanted = ...` through the executor block:

```python
    wanted = [p for p in providers if filters.providers is None or p.name in filters.providers]
    shares: dict[str, frozenset[str]] | None = None
    if selection is not None:
        shares = {p.name: _share(selection, p.name) for p in wanted}
        wanted = [p for p in wanted if shares[p.name]]
    available = [p for p in wanted if p.available()]

    _notify(on_progress, ScanStarted(providers=tuple(p.name for p in available)))

    entries: list[Entry] = []
    per_provider: list[ProviderTiming] = []
    diagnostics: list[str] = []

    if available:
        jobs = [(p, None if shares is None else shares[p.name]) for p in available]
        with ThreadPoolExecutor(max_workers=min(len(available), _MAX_WORKERS)) as executor:
            # executor.map preserves input order, so iterating the results
            # yields them in provider order no matter which thread finished
            # first. _discover_one swallows provider exceptions, so .result()
            # (inside map) never raises here.
            results = list(
                executor.map(
                    lambda job: _discover_one(job[0], on_progress, selection=job[1]), jobs
                )
            )
```

(Keep the loop over `results` and everything after it unchanged. `functools.partial` is no longer used; remove its import if nothing else needs it.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_discovery.py -q -p no:cacheprovider`, then ruff and mypy.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/base.py src/devdoctor/discovery.py tests/test_discovery.py
git commit -m "feat(scan): a selection asks each provider for its own entries only"
```

---

### Task 2: Path providers measure only the selected paths

**Files:**
- Modify: `src/devdoctor/providers/base.py` (`PathProvider.discover`)
- Test: `tests/test_path_provider.py`

**Interfaces:**
- Consumes: `Provider.discover_selected` (Task 1).

- [ ] **Step 1: Write the failing tests** (append; add `import devdoctor.providers.base as base` to the imports)

```python
def _three_caches(tmp_path: Path) -> PathProvider:
    for name, size in (("a", 100), ("b", 200), ("c", 300)):
        _mkfile(tmp_path / "caches" / name / "blob", size)
    spec = {
        "name": "caches",
        "description": "",
        "risk": "safe",
        "platforms": ["darwin", "linux"],
        "paths": [f"{tmp_path}/caches/*"],
        "recipe": "rm -rf {path}",
    }
    return PathProvider.from_yaml(spec, FakeShell())


@pytest.mark.parametrize("pick", [(), ("a",), ("a", "b", "c"), ("nope",), ("b", "nope")])
def test_discover_selected_is_discover_narrowed_to_the_selection(tmp_path: Path, pick) -> None:
    provider = _three_caches(tmp_path)
    ids = frozenset(str(tmp_path / "caches" / name) for name in pick)
    assert provider.discover_selected(ids) == [e for e in provider.discover() if e.id in ids]


def test_only_the_selected_paths_are_sized(tmp_path: Path, monkeypatch) -> None:
    provider = _three_caches(tmp_path)
    sized: list[Path] = []
    real = base.size_many

    def spy(paths, **kwargs):
        sized.extend(paths)
        return real(paths, **kwargs)

    monkeypatch.setattr(base, "size_many", spy)
    provider.discover_selected(frozenset({str(tmp_path / "caches" / "b")}))
    assert sized == [tmp_path / "caches" / "b"]
```

- [ ] **Step 2: Run them to verify the spy test fails**

Run: `.venv/bin/python -m pytest tests/test_path_provider.py -q -p no:cacheprovider -k "selected or selection"`
Expected: the equivalence cases pass through the default; `test_only_the_selected_paths_are_sized` FAILS because all three paths are sized.

- [ ] **Step 3: Implement**

In `PathProvider`, replace `discover` with:

```python
    def discover(self) -> list[Entry]:
        return self._entries(self.resolve_paths())

    def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
        if not ids:
            return []
        # Globs are cheap and decide what exists; only the selected paths are sized.
        return self._entries([p for p in self.resolve_paths() if str(p) in ids])

    def _entries(self, paths: list[Path]) -> list[Entry]:
        entries: list[Entry] = []
        for p, sizing in zip(paths, size_many(paths), strict=True):
            ...  # the former loop body of discover(), unchanged
        return entries
```

(Move the former `discover` loop body verbatim into `_entries`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_path_provider.py -q -p no:cacheprovider`, then ruff and mypy.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/base.py tests/test_path_provider.py
git commit -m "perf(providers): path providers size only the selected paths"
```

---

### Task 3: Project artifacts (node_modules, cargo, android, tox/nox, terraform)

**Files:**
- Modify: `src/devdoctor/providers/project_artifacts.py` (`NodeModulesProvider`, `CargoTargetsProvider`, `AndroidBuildProvider`, `ToxNoxProvider`, `TerraformProvider`)
- Test: `tests/test_project_artifact_providers.py`, `tests/test_terraform_provider.py`

**Interfaces:**
- Consumes: `Provider.discover_selected` (Task 1).
- Produces: `NodeModulesProvider._candidates() -> list[_Candidate]`, overridden by `CargoTargetsProvider` through a `_query: ClassVar[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_project_artifact_providers.py` (add `import pytest` and `from devdoctor.providers import project_artifacts`):

```python
def _two_of_each(root: Path) -> None:
    for name in ("web", "api"):
        _payload(root / name / "package.json")
        _payload(root / name / "node_modules" / "pkg" / "index.js")
    _payload(root / "web" / "pnpm-lock.yaml")  # api has none: dangerous advice
    for name in ("cli", "lib"):
        _payload(root / name / "Cargo.toml")
        _payload(root / name / "target" / "debug" / "app")
        _payload(root / f"{name}-android" / "build.gradle")
        _payload(root / f"{name}-android" / "build" / "out.apk")
        _payload(root / f"{name}-py" / "tox.ini")
        _payload(root / f"{name}-py" / ".tox" / "py312" / "marker")


@pytest.mark.parametrize(
    "provider_cls", [NodeModulesProvider, CargoTargetsProvider, AndroidBuildProvider, ToxNoxProvider]
)
def test_discover_selected_is_discover_narrowed_to_the_selection(
    tmp_path: Path, monkeypatch, provider_cls
) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    _two_of_each(root)
    provider = provider_cls(FakeShell(), index=ProjectArtifactIndex())
    everything = provider.discover()
    assert len(everything) == 2
    first = everything[0].id
    for ids in (
        frozenset(),
        frozenset({first}),
        frozenset(e.id for e in everything),
        frozenset({"/nope"}),
        frozenset({first, "/nope"}),
    ):
        assert provider.discover_selected(ids) == [e for e in everything if e.id in ids]


def test_only_the_selected_node_modules_are_sized(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    _two_of_each(root)
    sized: list[Path] = []
    real = project_artifacts.size_many

    def spy(paths, **kwargs):
        sized.extend(paths)
        return real(paths, **kwargs)

    monkeypatch.setattr(project_artifacts, "size_many", spy)
    target = root / "web" / "node_modules"
    NodeModulesProvider(FakeShell(), index=ProjectArtifactIndex()).discover_selected(
        frozenset({str(target)})
    )
    assert sized == [target]
```

Append to `tests/test_terraform_provider.py`:

```python
def test_a_selection_measures_its_workspace_and_skips_the_plugin_note(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv("DEVDOCTOR_PROJECT_ROOTS", str(root))
    dev = _workspace(root / "infra", "dev")
    prod = _workspace(root / "infra", "prod")
    _plugin(dev, 40_000)
    _plugin(prod, 40_000)

    full = TerraformProvider(FakeShell(), index=ProjectArtifactIndex())
    everything = full.discover()
    assert any("duplicate copies" in note for note in full.diagnostics)

    selective = TerraformProvider(FakeShell(), index=ProjectArtifactIndex())
    assert selective.discover_selected(frozenset({str(dev)})) == [
        e for e in everything if e.id == str(dev)
    ]
    # The note measures every workspace's plugins; a cleanup's re-check never shows it.
    assert selective.diagnostics == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_project_artifact_providers.py tests/test_terraform_provider.py -q -p no:cacheprovider -k "selected or selection"`
Expected:
- `test_only_the_selected_node_modules_are_sized` FAILS, because both node_modules are sized.
- The Terraform test FAILS, because the default runs the full `discover()` and adds the note.
- The equivalence tests pass through the default already. They guard the refactor.

- [ ] **Step 3: Implement**

In `src/devdoctor/providers/project_artifacts.py` (add `from typing import ClassVar`):

```python
class NodeModulesProvider(Provider):
    # ... class attributes and __init__ unchanged ...

    def discover(self) -> list[Entry]:
        return _sized_entries(self, self._candidates())

    def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
        if not ids:
            return []
        # Candidates come from the same fresh walk; only the selected ones are sized.
        return _sized_entries(self, [c for c in self._candidates() if str(c.artifact) in ids])

    def _candidates(self) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        for project, artifact in self._index.candidates("node"):
            ...  # the former discover() loop body, unchanged, ending in candidates.append(...)
        return candidates


class CargoTargetsProvider(NodeModulesProvider):
    # ... name, family, description, platforms, risk, details unchanged ...
    _query: ClassVar[str] = "cargo"

    def _candidates(self) -> list[_Candidate]:
        return [
            _Candidate(project, artifact, self.risk, DeletePathAction(artifact))
            for project, artifact in self._index.candidates(self._query)
        ]


class AndroidBuildProvider(CargoTargetsProvider):
    # ... attributes unchanged; delete its discover() ...
    _query = "android"


class ToxNoxProvider(CargoTargetsProvider):
    # ... attributes unchanged; delete its discover() ...
    _query = "tox-nox"


class TerraformProvider(CargoTargetsProvider):
    # ... attributes unchanged ...
    _query = "terraform"

    def discover(self) -> list[Entry]:
        candidates = self._candidates()
        entries = _sized_entries(self, candidates)
        self._note_duplicate_plugins([candidate.artifact for candidate in candidates])
        return entries

    # discover_selected is inherited: a cleanup's re-check skips the duplicate-plugin
    # note, a report diagnostic that measures every workspace's plugins.
```

Delete `CargoTargetsProvider.discover` and `CargoTargetsProvider._entries`; `NodeModulesProvider.discover` now serves every subclass. `grep -rn "_entries(" src tests` must show no remaining callers of the removed method.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_project_artifact_providers.py tests/test_terraform_provider.py tests/test_project_index_git_candidates.py -q -p no:cacheprovider`, then the full suite, ruff and mypy.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/project_artifacts.py tests/test_project_artifact_providers.py tests/test_terraform_provider.py
git commit -m "perf(providers): project artifacts size only the selected folders"
```

---

### Task 4: Python venvs

**Files:**
- Modify: `src/devdoctor/providers/venv.py` (`VenvProvider.discover`)
- Test: `tests/test_venv_provider.py`

**Interfaces:**
- Consumes: `Provider.discover_selected` (Task 1).

- [ ] **Step 1: Write the failing tests** (append; add `import pytest` and `from devdoctor.providers import venv`)

```python
def _three_venvs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.platform", "darwin")
    _mk_venv(home / "projects" / "a" / ".venv", payload_bytes=1024)
    _mk_venv(home / "projects" / "b" / ".venv", payload_bytes=2048)
    _mk_venv(home / "Code" / "c" / "venv", payload_bytes=4096)
    return VenvProvider(FakeShell())


def test_discover_selected_is_discover_narrowed_to_the_selection(tmp_path, monkeypatch):
    provider = _three_venvs(tmp_path, monkeypatch)
    everything = provider.discover()
    assert len(everything) == 3
    first = everything[0].id
    for ids in (frozenset(), frozenset({first}), frozenset(e.id for e in everything), frozenset({"/nope"})):
        assert provider.discover_selected(ids) == [e for e in everything if e.id in ids]


def test_only_the_selected_venv_is_sized(tmp_path, monkeypatch):
    provider = _three_venvs(tmp_path, monkeypatch)
    target = provider.discover()[0].path
    sized = []
    real = venv.size_many

    def spy(paths, **kwargs):
        sized.extend(paths)
        return real(paths, **kwargs)

    monkeypatch.setattr(venv, "size_many", spy)
    provider.discover_selected(frozenset({str(target)}))
    assert sized == [target]
```

- [ ] **Step 2: Run them to verify the spy test fails**

Run: `.venv/bin/python -m pytest tests/test_venv_provider.py -q -p no:cacheprovider -k "selected or selection"`
Expected: `test_only_the_selected_venv_is_sized` FAILS, because all three venvs are sized.

- [ ] **Step 3: Implement**

Split `VenvProvider.discover`:

```python
    def discover(self) -> list[Entry]:
        return self._entries(self._found())

    def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
        if not ids:
            return []
        # The walk and its inode dedup run in full; only the selected venvs are sized.
        return self._entries([found for found in self._found() if str(found[1]) in ids])

    def _found(self) -> list[tuple[Path, Path, os.stat_result]]:
        found: list[tuple[Path, Path, os.stat_result]] = []
        ...  # the former discover() body up to (not including) the size_many call, unchanged
        return found

    def _entries(self, found: list[tuple[Path, Path, os.stat_result]]) -> list[Entry]:
        # Sized together: the walks are independent and are most of the scan (#92).
        sizings = size_many([real for _venv_dir, real, _rst in found])
        entries: list[Entry] = []
        ...  # the former loop over zip(found, sizings), unchanged
        return entries
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_venv_provider.py -q -p no:cacheprovider`, then ruff and mypy.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/venv.py tests/test_venv_provider.py
git commit -m "perf(providers): venvs size only the selected environments"
```

---

### Task 5: Xcode development data

**Files:**
- Modify: `src/devdoctor/providers/mobile.py` (`XcodeProvider`)
- Test: `tests/test_ecosystem_providers.py`

**Interfaces:**
- Consumes: `Provider.discover_selected` (Task 1); `_path_entry` from `devdoctor.providers.tool_caches` (unchanged).

- [ ] **Step 1: Write the failing tests** (append; add `import pytest` and `from devdoctor.providers import tool_caches` if absent)

```python
def _xcode_home(tmp_path: Path, monkeypatch) -> list[Path]:
    monkeypatch.setenv("HOME", str(tmp_path))
    developer = tmp_path / "Library" / "Developer" / "Xcode"
    paths = [
        developer / "DerivedData" / "App-1",
        developer / "DerivedData" / "App-2",
        developer / "Archives" / "2026-09-05" / "App.xcarchive",
    ]
    for path in paths:
        _payload(path / "payload")
    return paths


def test_xcode_discover_selected_is_discover_narrowed_to_the_selection(tmp_path: Path, monkeypatch) -> None:
    paths = _xcode_home(tmp_path, monkeypatch)
    provider = XcodeProvider(FakeShell())
    everything = provider.discover()
    assert len(everything) == 3
    for ids in (
        frozenset(),
        frozenset({str(paths[0])}),
        frozenset(str(p) for p in paths),
        frozenset({"/nope"}),
    ):
        assert provider.discover_selected(ids) == [e for e in everything if e.id in ids]


def test_xcode_sizes_only_the_selected_entry(tmp_path: Path, monkeypatch) -> None:
    paths = _xcode_home(tmp_path, monkeypatch)
    sized: list[Path] = []
    real = tool_caches.size_path_detailed

    def spy(path):
        sized.append(path)
        return real(path)

    monkeypatch.setattr(tool_caches, "size_path_detailed", spy)
    XcodeProvider(FakeShell()).discover_selected(frozenset({str(paths[1])}))
    assert sized == [paths[1]]
```

- [ ] **Step 2: Run them to verify the spy test fails**

Run: `.venv/bin/python -m pytest tests/test_ecosystem_providers.py -q -p no:cacheprovider -k xcode`
Expected: `test_xcode_sizes_only_the_selected_entry` FAILS, because all three entries are sized.

- [ ] **Step 3: Implement**

In `src/devdoctor/providers/mobile.py`, import `from dataclasses import dataclass` and `CleanupAction` from `devdoctor.types`, then:

```python
@dataclass(frozen=True)
class _XcodeCandidate:
    """One Xcode path to measure, and how it will be offered."""

    path: Path
    id_: str
    label: str
    risk: Risk
    actions: tuple[CleanupAction, ...]
    reclaimable: bool | None


class XcodeProvider(Provider):
    # ... class attributes unchanged ...

    def discover(self) -> list[Entry]:
        return self._entries(self._candidates())

    def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
        if not ids:
            return []
        return self._entries([c for c in self._candidates() if c.id_ in ids])

    def _entries(self, candidates: list[_XcodeCandidate]) -> list[Entry]:
        entries: list[Entry] = []
        for c in candidates:
            entry = _path_entry(
                self,
                c.path,
                id_=c.id_,
                label=c.label,
                risk=c.risk,
                actions=c.actions,
                reclaimable=c.reclaimable,
            )
            if entry is not None:
                entries.append(entry)
        return entries

    def _candidates(self) -> list[_XcodeCandidate]:
        candidates: list[_XcodeCandidate] = []
        developer = Path("~/Library/Developer/Xcode").expanduser()
        for root_name, label_prefix in (
            ("DerivedData", "Xcode DerivedData"),
            ("iOS DeviceSupport", "iOS DeviceSupport"),
        ):
            root = developer / root_name
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                candidates.append(
                    _XcodeCandidate(
                        child,
                        str(child),
                        f"{label_prefix}: {child.name}",
                        Risk.RECLAIMABLE,
                        (DeletePathAction(child),),
                        True,
                    )
                )

        archives = developer / "Archives"
        if archives.is_dir():
            for archive in sorted(archives.glob("*/*.xcarchive")):
                candidates.append(
                    _XcodeCandidate(
                        archive,
                        str(archive),
                        f"Xcode archive: {archive.stem}",
                        Risk.DANGEROUS,
                        (
                            AdviceAction(
                                f"{archive} may be the only retained signed build. Export or "
                                "verify it in Xcode Organizer before deleting it."
                            ),
                        ),
                        None,
                    )
                )

        candidates.extend(self._unavailable_simulators())
        return candidates
```

`_unavailable_simulators` returns `list[_XcodeCandidate]`. Keep its body and replace the `_path_entry(...)` call and the `if entry is not None` append with:

```python
                candidates.append(
                    _XcodeCandidate(
                        path,
                        f"simulator:{udid}",
                        f"Unavailable simulator: {name or udid}",
                        Risk.RECLAIMABLE,
                        (CommandAction(("xcrun", "simctl", "delete", udid)),),
                        True,
                    )
                )
```

(Rename its local `entries` list to `candidates`. The early returns of `[]` are unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ecosystem_providers.py -q -p no:cacheprovider`, then ruff and mypy.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/mobile.py tests/test_ecosystem_providers.py
git commit -m "perf(providers): Xcode data measures only the selected entries"
```

---

### Task 6: Git worktrees

**Files:**
- Modify: `src/devdoctor/providers/git_worktrees.py` (`discover`, `_discover`)
- Test: `tests/test_git_worktrees_provider.py`

**Interfaces:**
- Consumes: `Provider.discover_selected` (Task 1).

- [ ] **Step 1: Write the failing tests** (append)

```python
def _one_integrated_one_not(app, projects):
    done = app.add_worktree(projects / "app" / ".worktrees" / "done", "done")
    _merge(app, done, branch="done")
    wip = app.add_worktree(projects / "wt" / "wip", "wip")
    wip.commit("Unmerged work", {"work.txt": "work\n"})
    app.publish()
    return done, wip


def test_discover_selected_is_discover_narrowed_to_the_selection(app, projects):
    done, wip = _one_integrated_one_not(app, projects)
    everything, _ = _discover()
    ids = [e.id for e in everything]
    assert str(done.path) in ids and str(wip.path) in ids
    for pick in (
        frozenset(),
        frozenset({str(done.path)}),
        frozenset({str(wip.path)}),
        frozenset(ids),
        frozenset({"/nope"}),
    ):
        provider = GitWorktreeProvider(RealShell())
        assert provider.discover_selected(pick) == [e for e in everything if e.id in pick]


def test_an_unselected_worktree_is_never_inspected(app, projects):
    done, wip = _one_integrated_one_not(app, projects)
    shell = RecordingShell()
    GitWorktreeProvider(shell).discover_selected(frozenset({str(done.path)}))
    touched = [argv for argv, _env in shell.calls if str(wip.path) in " ".join(argv)]
    assert touched == []
```

- [ ] **Step 2: Run them to verify the inspection test fails**

Run: `.venv/bin/python -m pytest tests/test_git_worktrees_provider.py -q -p no:cacheprovider -k "selected or selection"`
Expected: `test_an_unselected_worktree_is_never_inspected` FAILS, because git runs against `wip` too.

- [ ] **Step 3: Implement**

In `src/devdoctor/providers/git_worktrees.py`, rename the body of `discover` into `_run(self, wanted: frozenset[str] | None)`, passing `wanted` through to `_discover`:

```python
    def discover(self) -> list[Entry]:
        return self._run(None)

    def discover_selected(self, ids: frozenset[str]) -> list[Entry]:
        if not ids:
            return []
        return self._run(ids)

    def _run(self, wanted: frozenset[str] | None) -> list[Entry]:
        # ... the former discover() body, unchanged, except the last call:
        #     return self._discover(self._index.git_candidates(), objects_dir, wanted)
```

In `_discover`, add the parameter `wanted: frozenset[str] | None = None` and filter in two places:

```python
            listed.update(_real(record.path) for record in records)
            linked = self._linked_worktrees(repository, records)
            if wanted is not None:
                # Every repository is still listed above: whether a worktree may be
                # removed depends on what all of them register.
                linked = [record for record in linked if str(record.path) in wanted]
            if linked:
```

```python
        unverifiable = self._unverifiable_entries(candidates, listed, failed)
        if wanted is not None:
            unverifiable = [entry for entry in unverifiable if entry.id in wanted]
        entries.extend(unverifiable)
        return entries
```

(Replace the former `entries.extend(self._unverifiable_entries(candidates, listed, failed))`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_git_worktrees_provider.py tests/test_worktree_states.py tests/test_worktree_containment_e2e.py -q -p no:cacheprovider`, then the full suite, ruff and mypy.
Expected: all pass. One git-version test is skipped outside CI.

- [ ] **Step 5: Commit**

```bash
git add src/devdoctor/providers/git_worktrees.py tests/test_git_worktrees_provider.py
git commit -m "perf(providers): worktrees classify and size only the selected ones"
```

---

### Task 7: The cleanup route passes its selection; docs; measurement

**Files:**
- Modify: `src/devdoctor/web/routes_clean.py` (`_scan_selection`)
- Modify: `tests/web/test_routes_clean.py`
- Modify: `docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md` (§6.4, second bullet)
- Modify: `docs/superpowers/specs/2026-09-25-cleanup-selection-recheck-design.md` (Status line)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `discovery.scan(..., selection=)` (Task 1).

- [ ] **Step 1: Write the failing test** (append to `tests/web/test_routes_clean.py`)

```python
@pytest.mark.asyncio
async def test_the_job_rescan_builds_only_the_selected_entries(tmp_path, monkeypatch):
    from devdoctor.web import routes_clean

    app = _build(tmp_path, monkeypatch)
    real_scan = routes_clean.discovery.scan
    selections: list[object] = []

    def spy(providers, filters, now, **kwargs):
        selections.append(kwargs.get("selection"))
        return real_scan(providers, filters, now, **kwargs)

    monkeypatch.setattr(routes_clean.discovery, "scan", spy)
    entry_id = f"t:{tmp_path}/cache"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        r = await client.post(
            "/api/clean/jobs", json={"entry_ids": [entry_id]}, headers={"Host": "testserver"}
        )
        assert r.status_code == 200, r.text
        await app.state.runner_registry.active().cancel()
    assert selections == [frozenset({entry_id})]
```

In the same file, `test_cleanup_job_keeps_every_selected_entry_from_an_uncontained_scan` defines `def fake_scan(providers, filters, now, *, contain=True):`. Change it to `def fake_scan(providers, filters, now, *, contain=True, selection=None):` so it accepts the new keyword.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/web/test_routes_clean.py -q -p no:cacheprovider -k only_the_selected`
Expected: FAIL: `assert [None] == [frozenset({...})]`.

- [ ] **Step 3: Implement**

In `_scan_selection`, change the return to:

```python
    return discovery.scan(
        providers_list,
        filters,
        datetime.now(UTC),
        contain=False,
        selection=frozenset(entry_ids),
    )
```

In the §6.4 bullet that begins "**`POST /api/clean/jobs` scans with `contain=False`.**", append:

```markdown
  The scan builds only the selected entries: each provider finds its candidates from
  disk as `discover()` would, and measures only those selected (`discover_selected`,
  spec 2026-09-25).
```

In the new spec's header, change `**Status:** proposed, awaiting review` to `**Status:** accepted 2026-09-26`.

Add to `CHANGELOG.md`, `## [Unreleased]` → `### Changed`, as the first bullet:

```markdown
- **Starting a web cleanup re-checks only what you selected.** Before a job
  starts, the server confirms each selected entry against the disk. It used to
  re-run the entry's whole provider, so one `node_modules` folder re-sized all
  267 on the reference machine (about 58 s). Providers still find their
  candidates on disk as before, but measure only the selected ones.
```

- [ ] **Step 4: Verify**

Run: `.venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests && .venv/bin/mypy && .venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: all green.

- [ ] **Step 5: Measure on this machine (read-only) and record the numbers for the PR**

```bash
.venv/bin/python - <<'EOF'
import time
from datetime import UTC, datetime
from devdoctor import discovery, registry
from devdoctor.ports import RealShell
from devdoctor.types import ScanFilters
from devdoctor.web.routes_clean import _scan_selection

shell = RealShell()
providers = registry.load_providers(shell)
report = discovery.scan(
    providers,
    ScanFilters(providers=frozenset({"node-project-dependencies", "git-worktrees"})),
    datetime.now(UTC),
    contain=False,
)
node = max((e for e in report.entries if e.provider == "node-project-dependencies"), key=lambda e: e.display_bytes)
worktree = next(e for e in report.entries if e.provider == "git-worktrees")
for entry in (node, worktree):
    t0 = time.monotonic()
    _scan_selection(shell, [entry.id])
    print(f"{entry.provider}: {time.monotonic() - t0:.1f}s for {entry.label}")
EOF
```

Expected: node-project-dependencies is about 10 to 15 s (the spec measured 58 s before), and git-worktrees drops well below its ~60 s.

- [ ] **Step 6: Commit**

```bash
git add src/devdoctor/web/routes_clean.py tests/web/test_routes_clean.py docs/superpowers/specs/2026-09-12-git-worktree-provider-design.md docs/superpowers/specs/2026-09-25-cleanup-selection-recheck-design.md CHANGELOG.md
git commit -m "perf(web): a cleanup's re-check measures only the selected entries"
```
